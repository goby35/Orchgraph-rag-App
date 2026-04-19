"""Neo4j re-embedding worker for A/B testing embedding models.

This worker pulls text fields from Neo4j nodes, generates public/private
embeddings with a selected model, and writes vectors back to dynamic
properties on the same nodes.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from math import ceil
from typing import Any, Iterable, Iterator

import torch
from neo4j import Driver, GraphDatabase
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

from pipeline.config import get_logger, settings

LOGGER = get_logger("re_embedder")


@dataclass(frozen=True)
class ModelConfig:
    """Configuration for a supported embedding model."""

    alias: str
    hf_model: str
    dimension: int
    prop_suffix: str


MODEL_REGISTRY: dict[str, ModelConfig] = {
    "bge-m3": ModelConfig(
        alias="bge-m3",
        hf_model="BAAI/bge-m3",
        dimension=1024,
        prop_suffix="bge_m3",
    ),
    "gte": ModelConfig(
        alias="gte",
        hf_model="Alibaba-NLP/gte-multilingual-base",
        dimension=768,
        prop_suffix="gte",
    ),
}


@dataclass
class NodeTextRecord:
    """Text payload fetched from Neo4j for one node."""

    node_id: str
    label: str
    public_text: str
    private_text: str


def parse_args() -> argparse.Namespace:
    """Parse worker CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Re-embed Neo4j nodes directly for model A/B testing."
    )
    parser.add_argument(
        "--model",
        required=True,
        choices=sorted(MODEL_REGISTRY.keys()),
        help="Embedding model alias: bge-m3 or gte.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Batch size for embedding + Neo4j updates (default: 50).",
    )
    return parser.parse_args()


def resolve_device() -> str:
    """Prefer CUDA if available, otherwise CPU."""
    return "cuda" if torch.cuda.is_available() else "cpu"


def flatten_text(value: Any) -> str:
    """Flatten mixed JSON-like values into a plain string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        parts = [flatten_text(v) for v in value.values()]
        return " ".join(part for part in parts if part)
    if isinstance(value, list):
        parts = [flatten_text(item) for item in value]
        return " ".join(part for part in parts if part)
    return str(value).strip()


def normalize_private_blob(blob: Any) -> str:
    """Return stable string for private_data_blob.

    If blob is an object/list from Neo4j, serialize compact JSON to preserve
    important values before flattening fallback.
    """
    if isinstance(blob, str):
        return blob.strip()
    if isinstance(blob, (dict, list)):
        try:
            return json.dumps(blob, ensure_ascii=False)
        except TypeError:
            return flatten_text(blob)
    return flatten_text(blob)


def join_non_empty(parts: Iterable[str]) -> str:
    """Join non-empty text fragments into one string."""
    cleaned = [part.strip() for part in parts if part and part.strip()]
    return " ".join(cleaned)


def build_public_text(public_summary: Any, public_skills: Any) -> str:
    """Compose public_text from summary + skills."""
    summary_text = flatten_text(public_summary)
    skills_text = flatten_text(public_skills)
    return join_non_empty([summary_text, skills_text])


def fetch_node_texts(driver: Driver) -> list[NodeTextRecord]:
    """Fetch candidate node texts from Neo4j.

    Reads both Personnel and Organization nodes when they expose `id`.
    """
    cypher_fetch = """
    MATCH (n)
    WHERE (n:Personnel OR n:Organization) AND n.id IS NOT NULL
    RETURN
      toString(n.id) AS id,
      CASE
        WHEN n:Personnel THEN 'Personnel'
        WHEN n:Organization THEN 'Organization'
        ELSE 'Unknown'
      END AS label,
      n.public_summary AS public_summary,
      n.public_skills AS public_skills,
      n.private_data_blob AS private_data_blob
    ORDER BY id
    """

    records: list[NodeTextRecord] = []
    with driver.session() as session:
        result = session.run(cypher_fetch)
        for row in result:
            public_text = build_public_text(
                row.get("public_summary"),
                row.get("public_skills"),
            )
            private_text = normalize_private_blob(row.get("private_data_blob"))

            if not public_text or not private_text:
                LOGGER.warning(
                    "Skip node id=%s (%s): missing public/private text.",
                    row.get("id"),
                    row.get("label"),
                )
                continue

            records.append(
                NodeTextRecord(
                    node_id=str(row.get("id")),
                    label=str(row.get("label")),
                    public_text=public_text,
                    private_text=private_text,
                )
            )
    return records


def chunked(items: list[NodeTextRecord], size: int) -> Iterator[list[NodeTextRecord]]:
    """Yield fixed-size chunks from list."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


def encode_batch(
    model: SentenceTransformer,
    rows: list[NodeTextRecord],
) -> list[dict[str, Any]]:
    """Encode one batch and return parameter rows for Cypher update."""
    public_texts = [row.public_text for row in rows]
    private_texts = [row.private_text for row in rows]

    public_vectors = model.encode(
        public_texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    private_vectors = model.encode(
        private_texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    payload: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        payload.append(
            {
                "id": row.node_id,
                "label": row.label,
                "pub_vec": public_vectors[idx].tolist(),
                "priv_vec": private_vectors[idx].tolist(),
            }
        )
    return payload


def update_embeddings_batch(
    tx: Any,
    batch_payload: list[dict[str, Any]],
    prop_suffix: str,
) -> None:
    """Write one embedding batch to Neo4j with dynamic property keys."""
    cypher_update = f"""
    UNWIND $batch AS row
    MATCH (n {{id: row.id}})
    WHERE row.label IN labels(n)
    SET n.public_embeddings_{prop_suffix} = row.pub_vec,
        n.private_embeddings_{prop_suffix} = row.priv_vec
    """
    tx.run(cypher_update, batch=batch_payload)


def create_vector_indexes(tx: Any, cfg: ModelConfig) -> None:
    """Create model-specific vector indexes if not exists."""
    personnel_public_idx = f"personnel_public_idx_{cfg.prop_suffix}"
    personnel_private_idx = f"personnel_private_idx_{cfg.prop_suffix}"

    cypher_public = f"""
    CREATE VECTOR INDEX {personnel_public_idx} IF NOT EXISTS
    FOR (p:Personnel) ON (p.public_embeddings_{cfg.prop_suffix})
    OPTIONS {{indexConfig: {{
      `vector.dimensions`: {cfg.dimension},
      `vector.similarity_function`: 'cosine'
    }}}}
    """

    cypher_private = f"""
    CREATE VECTOR INDEX {personnel_private_idx} IF NOT EXISTS
    FOR (p:Personnel) ON (p.private_embeddings_{cfg.prop_suffix})
    OPTIONS {{indexConfig: {{
      `vector.dimensions`: {cfg.dimension},
      `vector.similarity_function`: 'cosine'
    }}}}
    """

    tx.run(cypher_public)
    tx.run(cypher_private)


def run_worker(model_alias: str, batch_size: int) -> None:
    """Execute Neo4j re-embedding workflow end-to-end."""
    cfg = MODEL_REGISTRY[model_alias]
    device = resolve_device()

    LOGGER.info("Model: %s (%s)", cfg.hf_model, cfg.alias)
    LOGGER.info("Device: %s", device)
    LOGGER.info("Batch size: %d", batch_size)

    model = SentenceTransformer(cfg.hf_model, device=device, trust_remote_code=True)

    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )

    try:
        driver.verify_connectivity()
        LOGGER.info("Connected to Neo4j: %s", settings.NEO4J_URI)

        records = fetch_node_texts(driver)
        if not records:
            LOGGER.warning("No eligible nodes found for re-embedding.")
            return

        total_batches = ceil(len(records) / batch_size)
        LOGGER.info("Eligible nodes: %d", len(records))

        with driver.session() as session:
            for rows in tqdm(
                chunked(records, batch_size),
                total=total_batches,
                desc="Re-embedding batches",
                unit="batch",
            ):
                payload = encode_batch(model, rows)
                session.execute_write(
                    update_embeddings_batch,
                    payload,
                    cfg.prop_suffix,
                )

            session.execute_write(create_vector_indexes, cfg)

        LOGGER.info(
            "\033[92m[SUCCESS]\033[0m Re-embedding completed for model=%s. Updated %d nodes.",
            cfg.alias,
            len(records),
        )

    finally:
        driver.close()
        LOGGER.info("Neo4j driver closed.")


def main() -> None:
    """CLI entrypoint."""
    args = parse_args()

    if args.batch_size <= 0:
        raise ValueError("--batch-size must be greater than 0")

    run_worker(model_alias=args.model, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
