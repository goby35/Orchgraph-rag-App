"""
Re-Embedding Pipeline — NovaTech GraphRAG.

Thay thế trường ``embedding`` trong các file JSON đã qua pipeline 5 bước
(Parse → Clean → Chunk → Extract → Vectorize) bằng vector từ mô hình mới,
**giữ nguyên** toàn bộ ``original_clean_text``, ``segmented_text``,
``extracted_knowledge``.

Hỗ trợ 3 model:
    - vinai/phobert-base-v2   (768-d, CLS, cần segmented_text)
    - BAAI/bge-m3             (1024-d, CLS dense, original_clean_text)
    - Alibaba-NLP/gte-multilingual-base (768-d, mean-pooling, original_clean_text)

Usage::

    # Re-embed toàn bộ thư mục
    python re_embedder.py --model bge-m3 --input ./neo4j_ready/phobert-v2 --output ./neo4j_ready/bge-m3

    # Benchmark 3 model trên 1 file
    python re_embedder.py --benchmark --input ./neo4j_ready/phobert-v2/01_NguyenHoaiTuong_CEO.json
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import torch
from tqdm import tqdm

from pipeline.config import settings, get_logger

logger = get_logger("re_embedder")

# ============================================================================
# Model registry
# ============================================================================

MODEL_ALIAS: Dict[str, str] = {
    "phobert": "vinai/phobert-base-v2",
    "bge-m3": "BAAI/bge-m3",
    "gte": "Alibaba-NLP/gte-multilingual-base",
}

MODEL_DIM: Dict[str, int] = {
    "vinai/phobert-base-v2": 768,
    "BAAI/bge-m3": 1024,
    "Alibaba-NLP/gte-multilingual-base": 768,
}


def _resolve_device(device: str) -> torch.device:
    if device == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(device)


# ============================================================================
# Base embedder
# ============================================================================


class BaseEmbedder(ABC):
    """Abstract base for all embedding models."""

    model_id: str
    dim: int

    def __init__(self, device: str = "auto") -> None:
        self.device = _resolve_device(device)
        self._loaded = False

    @abstractmethod
    def load(self) -> None:
        """Download / load model + tokenizer into memory."""

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> np.ndarray:
        """Return (N, dim) L2-normalised float32 array."""

    def embed_one(self, text: str) -> List[float]:
        return self.embed_batch([text])[0].tolist()

    def text_field(self) -> str:
        """Which JSON field to use as input text."""
        return "original_clean_text"


# ============================================================================
# PhoBERT v2
# ============================================================================


class PhoBERTEmbedder(BaseEmbedder):
    model_id = "vinai/phobert-base-v2"
    dim = 768

    def text_field(self) -> str:
        return "segmented_text"

    def load(self) -> None:
        if self._loaded:
            return
        from transformers import AutoModel, AutoTokenizer

        logger.info("Loading %s …", self.model_id)
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_id)
        self.model = AutoModel.from_pretrained(self.model_id).to(self.device).eval()
        self._loaded = True
        logger.info("PhoBERT loaded on %s", self.device)

    @torch.no_grad()
    def embed_batch(self, texts: List[str]) -> np.ndarray:
        enc = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=256,
            return_tensors="pt",
        ).to(self.device)
        out = self.model(**enc)
        cls = out.last_hidden_state[:, 0, :]  # CLS pooling
        cls = cls.cpu().numpy().astype(np.float32)
        norms = np.linalg.norm(cls, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        return cls / norms


# ============================================================================
# BGE-M3
# ============================================================================


class BGEM3Embedder(BaseEmbedder):
    model_id = "BAAI/bge-m3"
    dim = 1024

    def load(self) -> None:
        if self._loaded:
            return
        from transformers import AutoModel, AutoTokenizer

        logger.info("Loading %s (≈2.3 GB) …", self.model_id)
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_id)
        self.model = AutoModel.from_pretrained(self.model_id).to(self.device).eval()
        self._loaded = True
        logger.info("BGE-M3 loaded on %s", self.device)

    @torch.no_grad()
    def embed_batch(self, texts: List[str]) -> np.ndarray:
        enc = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=8192,
            return_tensors="pt",
        ).to(self.device)
        out = self.model(**enc)
        cls = out.last_hidden_state[:, 0, :]  # CLS dense
        cls = cls.cpu().numpy().astype(np.float32)
        norms = np.linalg.norm(cls, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        return cls / norms


# ============================================================================
# GTE-Multilingual
# ============================================================================


class GTEMultilingualEmbedder(BaseEmbedder):
    model_id = "Alibaba-NLP/gte-multilingual-base"
    dim = 768

    def load(self) -> None:
        if self._loaded:
            return
        from transformers import AutoModel, AutoTokenizer

        logger.info("Loading %s (≈570 MB) …", self.model_id)
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_id, trust_remote_code=True
        )
        self.model = (
            AutoModel.from_pretrained(self.model_id, trust_remote_code=True)
            .to(self.device)
            .eval()
        )
        self._loaded = True
        logger.info("GTE-Multilingual loaded on %s", self.device)

    @torch.no_grad()
    def embed_batch(self, texts: List[str]) -> np.ndarray:
        enc = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=8192,
            return_tensors="pt",
        ).to(self.device)
        out = self.model(**enc)
        # Mean pooling (attention-mask weighted)
        mask = enc["attention_mask"].unsqueeze(-1).float()  # (B, T, 1)
        hidden = out.last_hidden_state * mask  # zero out padding
        summed = hidden.sum(dim=1)
        counts = mask.sum(dim=1).clamp(min=1e-9)
        mean_vec = (summed / counts).cpu().numpy().astype(np.float32)
        norms = np.linalg.norm(mean_vec, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        return mean_vec / norms


# ============================================================================
# Embedder factory
# ============================================================================

_EMBEDDER_MAP = {
    "vinai/phobert-base-v2": PhoBERTEmbedder,
    "BAAI/bge-m3": BGEM3Embedder,
    "Alibaba-NLP/gte-multilingual-base": GTEMultilingualEmbedder,
}


def create_embedder(model_name: str, device: str = "auto") -> BaseEmbedder:
    model_id = MODEL_ALIAS.get(model_name, model_name)
    cls = _EMBEDDER_MAP.get(model_id)
    if cls is None:
        raise ValueError(
            f"Unknown model '{model_name}'. "
            f"Supported: {list(MODEL_ALIAS.keys())} or full HuggingFace ID."
        )
    return cls(device=device)


# ============================================================================
# JSON I/O helpers
# ============================================================================


def _load_chunks(path: Path) -> List[Dict[str, Any]]:
    """Load chunks from JSON — supports both raw list and {metadata, chunks} wrapper."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "chunks" in data:
        return data["chunks"]
    raise ValueError(f"Unrecognised JSON format in {path}")


def _save_output(
    chunks: List[Dict[str, Any]],
    output_path: Path,
    source_model: str,
    target_model: str,
    embedding_dim: int,
    source_input: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": {
            "source_model": source_model,
            "target_model": target_model,
            "re_embedded_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
            "total_chunks": len(chunks),
            "embedding_dim": embedding_dim,
            "source_input": source_input,
        },
        "chunks": chunks,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _detect_source_model(chunks: List[Dict[str, Any]]) -> str:
    """Try to detect the model that produced the existing embeddings."""
    for c in chunks:
        if "embedding_model" in c:
            return c["embedding_model"]
    # Default assumption — original pipeline uses PhoBERT
    return "vinai/phobert-base-v2"


# ============================================================================
# ReEmbedder — core processing logic
# ============================================================================


class ReEmbedder:
    """Orchestrate re-embedding of JSON chunk files."""

    def __init__(self, embedder: BaseEmbedder) -> None:
        self.embedder = embedder

    # ------------------------------------------------------------------ #
    # Process a single file
    # ------------------------------------------------------------------ #

    def process_file(
        self,
        input_path: str | Path,
        output_path: str | Path,
        batch_size: int = 32,
    ) -> Dict[str, Any]:
        input_path = Path(input_path).resolve()
        output_path = Path(output_path).resolve()

        chunks = _load_chunks(input_path)
        source_model = _detect_source_model(chunks)

        if not chunks:
            logger.warning("File %s has 0 chunks — skipping.", input_path.name)
            return {"processed": 0, "errors": 0, "time_s": 0.0, "output": str(output_path)}

        t0 = time.perf_counter()
        text_field = self.embedder.text_field()
        errors = 0

        # Collect texts, track indices with empty text
        texts: List[str] = []
        empty_indices: set = set()

        for idx, chunk in enumerate(chunks):
            txt = chunk.get(text_field, "") or ""
            if not txt.strip():
                logger.warning(
                    "Chunk %s (index %d) — empty '%s', will use zero vector.",
                    chunk.get("chunk_id", "?"),
                    chunk.get("chunk_index", idx),
                    text_field,
                )
                texts.append("")
                empty_indices.add(idx)
            else:
                texts.append(txt)

        # Batch embed with OOM retry
        all_vectors = self._batch_embed_with_retry(texts, empty_indices, batch_size)

        # Build output chunks (deep copy to preserve extracted_knowledge exactly)
        out_chunks: List[Dict[str, Any]] = []
        for idx, chunk in enumerate(chunks):
            new_chunk = copy.deepcopy(chunk)
            if idx in empty_indices:
                new_chunk["embedding"] = [0.0] * self.embedder.dim
                new_chunk["embedding_error"] = True
                errors += 1
            else:
                new_chunk["embedding"] = all_vectors[idx].tolist()
            new_chunk["embedding_model"] = self.embedder.model_id
            new_chunk["embedding_dim"] = self.embedder.dim
            out_chunks.append(new_chunk)

        elapsed = time.perf_counter() - t0

        _save_output(
            chunks=out_chunks,
            output_path=output_path,
            source_model=source_model,
            target_model=self.embedder.model_id,
            embedding_dim=self.embedder.dim,
            source_input=str(input_path),
        )

        stats = {
            "processed": len(out_chunks),
            "errors": errors,
            "time_s": round(elapsed, 2),
            "output": str(output_path),
        }
        logger.info(
            "✓ %s — %d chunks in %.1fs (%d errors)",
            input_path.name,
            stats["processed"],
            stats["time_s"],
            stats["errors"],
        )
        return stats

    # ------------------------------------------------------------------ #
    # Process a whole folder
    # ------------------------------------------------------------------ #

    def process_folder(
        self,
        input_dir: str | Path,
        output_dir: str | Path,
        batch_size: int = 32,
    ) -> Dict[str, Any]:
        input_dir = Path(input_dir).resolve()
        output_dir = Path(output_dir).resolve()

        if not input_dir.is_dir():
            raise FileNotFoundError(f"Input directory not found: {input_dir}")

        json_files = sorted(input_dir.glob("*.json"))
        if not json_files:
            logger.warning("No JSON files found in %s", input_dir)
            return {"files": 0, "total_chunks": 0, "total_errors": 0, "time_s": 0.0}

        logger.info("Processing %d files from %s …", len(json_files), input_dir)
        agg = {"files": 0, "total_chunks": 0, "total_errors": 0, "time_s": 0.0}
        t0 = time.perf_counter()

        for jf in tqdm(json_files, desc="Re-embedding files"):
            out_path = output_dir / jf.name
            stats = self.process_file(jf, out_path, batch_size=batch_size)
            agg["files"] += 1
            agg["total_chunks"] += stats["processed"]
            agg["total_errors"] += stats["errors"]

        agg["time_s"] = round(time.perf_counter() - t0, 2)
        logger.info(
            "Folder done — %d files, %d chunks, %d errors, %.1fs total",
            agg["files"],
            agg["total_chunks"],
            agg["total_errors"],
            agg["time_s"],
        )
        return agg

    # ------------------------------------------------------------------ #
    # Benchmark mode
    # ------------------------------------------------------------------ #

    def benchmark(self, input_path: str | Path) -> None:
        """Run all 3 models on the same file, print comparison table."""
        import psutil
        from itertools import combinations

        input_path = Path(input_path).resolve()
        chunks = _load_chunks(input_path)
        if not chunks:
            logger.error("No chunks in %s — cannot benchmark.", input_path)
            return

        logger.info("Benchmark on %s (%d chunks)", input_path.name, len(chunks))

        models = ["phobert", "bge-m3", "gte"]
        labels = ["PhoBERT v2", "BGE-M3", "GTE-Multilingual"]
        results: List[Dict[str, Any]] = []
        first_vectors: Dict[str, np.ndarray] = {}

        for alias, label in zip(models, labels):
            emb = create_embedder(alias, device=str(self.embedder.device))
            emb.load()

            text_field = emb.text_field()
            texts = []
            for c in chunks:
                txt = c.get(text_field, "") or ""
                texts.append(txt if txt.strip() else "")

            proc = psutil.Process(os.getpid())
            mem_before = proc.memory_info().rss

            t0 = time.perf_counter()
            vecs = emb.embed_batch(texts)
            elapsed = time.perf_counter() - t0

            mem_after = proc.memory_info().rss
            mem_used_mb = (mem_after - mem_before) / (1024 * 1024)
            if mem_used_mb < 0:
                mem_used_mb = proc.memory_info().rss / (1024 * 1024)

            avg_norm = float(np.mean(np.linalg.norm(vecs, axis=1)))
            first_vectors[label] = vecs[0]

            results.append(
                {
                    "label": label,
                    "dim": emb.dim,
                    "time_s": round(elapsed, 1),
                    "avg_norm": round(avg_norm, 4),
                    "ram_mb": round(mem_used_mb),
                }
            )
            # Free GPU memory
            del emb
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        # Print table
        print()
        print("╔══════════════════════════════════════════════════════════════╗")
        print("║              EMBEDDING BENCHMARK REPORT                     ║")
        print("╠══════════════════╦═════════╦══════════╦══════════╦══════════╣")
        print("║ Model            ║ Dim     ║ Time (s) ║ Avg Norm ║ RAM (MB) ║")
        print("╠══════════════════╬═════════╬══════════╬══════════╬══════════╣")
        for r in results:
            print(
                f"║ {r['label']:<16} ║ {r['dim']:<7} ║ {r['time_s']:>8} ║ {r['avg_norm']:>8} ║ {r['ram_mb']:>8} ║"
            )
        print("╚══════════════════╩═════════╩══════════╩══════════╩══════════╝")

        # Cosine similarity between model pairs on chunk #0
        print(f"\nCosine Similarity giữa các model (trên chunk #0):")
        for (l1, v1), (l2, v2) in combinations(first_vectors.items(), 2):
            # Vectors are already L2-normalised → dot = cosine
            # Pad to same dim for comparison
            max_dim = max(len(v1), len(v2))
            a = np.zeros(max_dim, dtype=np.float32)
            b = np.zeros(max_dim, dtype=np.float32)
            a[: len(v1)] = v1
            b[: len(v2)] = v2
            na = np.linalg.norm(a)
            nb = np.linalg.norm(b)
            cos = float(np.dot(a, b) / (na * nb)) if na > 0 and nb > 0 else 0.0
            short1 = l1.split()[0]
            short2 = l2.split()[0]
            print(f"  {short1:<9} ↔ {short2:<9}:  {cos:.3f}")

        # Save chunk #0 vectors for manual inspection
        out_dir = Path("benchmark_output")
        out_dir.mkdir(exist_ok=True)
        for label, vec in first_vectors.items():
            safe_name = label.replace(" ", "_").lower()
            np.save(out_dir / f"chunk0_{safe_name}.npy", vec)
        print(f"\nChunk #0 vectors saved to {out_dir}/")

    # ------------------------------------------------------------------ #
    # Internal: batch embed with OOM retry
    # ------------------------------------------------------------------ #

    def _batch_embed_with_retry(
        self,
        texts: List[str],
        empty_indices: set,
        batch_size: int,
    ) -> np.ndarray:
        """Embed texts in batches with automatic batch-size reduction on OOM."""
        n = len(texts)
        result = np.zeros((n, self.embedder.dim), dtype=np.float32)
        current_bs = batch_size
        i = 0

        while i < n:
            batch_end = min(i + current_bs, n)
            batch_texts = texts[i:batch_end]

            # Skip purely empty batches
            non_empty = [
                (j, t)
                for j, t in enumerate(batch_texts, start=i)
                if j not in empty_indices
            ]
            if not non_empty:
                i = batch_end
                continue

            indices_in_batch = [idx for idx, _ in non_empty]
            texts_in_batch = [t for _, t in non_empty]

            try:
                vecs = self.embedder.embed_batch(texts_in_batch)
                for k, idx in enumerate(indices_in_batch):
                    result[idx] = vecs[k]
                i = batch_end
            except (torch.cuda.OutOfMemoryError, RuntimeError) as exc:
                if "out of memory" in str(exc).lower() and current_bs > 1:
                    new_bs = max(1, current_bs // 2)
                    logger.warning(
                        "OOM at batch_size=%d — reducing to %d and retrying.",
                        current_bs,
                        new_bs,
                    )
                    current_bs = new_bs
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    # Don't advance i — retry same position
                else:
                    raise

        return result


# ============================================================================
# Neo4j Re-Ingestion
# ============================================================================


class Neo4jReIngester:
    """Update only embedding vectors in Neo4j — no structural changes."""

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> None:
        from neo4j import GraphDatabase

        self._uri = uri or settings.NEO4J_URI
        self._user = user or settings.NEO4J_USER
        self._password = password or settings.NEO4J_PASSWORD
        self._driver = GraphDatabase.driver(
            self._uri, auth=(self._user, self._password)
        )
        self._driver.verify_connectivity()
        logger.info("Neo4jReIngester connected to %s", self._uri)

    def close(self) -> None:
        if self._driver:
            self._driver.close()

    def __enter__(self) -> "Neo4jReIngester":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Update embeddings
    # ------------------------------------------------------------------ #

    def update_embeddings(
        self, json_path: str | Path, batch_size: int = 100
    ) -> int:
        json_path = Path(json_path).resolve()
        chunks = _load_chunks(json_path)
        total = len(chunks)

        if total == 0:
            logger.warning("No chunks in %s — nothing to update.", json_path)
            return 0

        updated = 0
        for start in range(0, total, batch_size):
            batch = chunks[start : start + batch_size]
            with self._driver.session() as session:
                for chunk in batch:
                    cid = chunk.get("chunk_id")
                    vec = chunk.get("embedding")
                    model = chunk.get("embedding_model", "")
                    dim = chunk.get("embedding_dim", 0)
                    if cid is None or vec is None:
                        continue
                    session.run(
                        "MATCH (c:Chunk {chunk_id: $id}) "
                        "SET c.embedding = $vec, "
                        "    c.embedding_model = $model, "
                        "    c.embedding_dim = $dim",
                        id=cid,
                        vec=vec,
                        model=model,
                        dim=dim,
                    )
                    updated += 1
            logger.info("Updated %d/%d chunks …", min(start + batch_size, total), total)

        logger.info("Embedding update complete — %d/%d chunks updated.", updated, total)
        return updated

    # ------------------------------------------------------------------ #
    # Recreate vector index
    # ------------------------------------------------------------------ #

    def recreate_vector_index(self, dim: int) -> None:
        with self._driver.session() as session:
            session.run("DROP INDEX chunk_embedding_index IF EXISTS")
            logger.info("Dropped old vector index.")
            session.run(
                "CREATE VECTOR INDEX chunk_embedding_index "
                "FOR (c:Chunk) ON (c.embedding) "
                "OPTIONS {indexConfig: {"
                " `vector.dimensions`: $dim,"
                " `vector.similarity_function`: 'cosine'"
                "}}",
                dim=dim,
            )
            logger.info(
                "Created vector index chunk_embedding_index (dim=%d, cosine).", dim
            )


# ============================================================================
# Standalone helper for Neo4j re-ingestion
# ============================================================================


def reingest_to_neo4j(
    json_path: str | Path,
    neo4j_uri: str | None = None,
    user: str | None = None,
    password: str | None = None,
) -> int:
    """Convenience function — update embeddings & recreate index in one call."""
    path = Path(json_path)
    chunks = _load_chunks(path)
    dim = 0
    for c in chunks:
        if c.get("embedding"):
            dim = len(c["embedding"])
            break

    with Neo4jReIngester(uri=neo4j_uri, user=user, password=password) as ing:
        updated = ing.update_embeddings(path)
        if dim > 0:
            ing.recreate_vector_index(dim)
    return updated


# ============================================================================
# CLI
# ============================================================================


def _parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Re-embed NovaTech GraphRAG JSON chunks with a new model."
    )
    p.add_argument(
        "--model",
        choices=["phobert", "bge-m3", "gte"],
        default="bge-m3",
        help="Embedding model alias (default: bge-m3)",
    )
    p.add_argument(
        "--input",
        required=True,
        help="Input JSON file or directory of JSON files",
    )
    p.add_argument(
        "--output",
        default=None,
        help="Output directory (required unless --benchmark)",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Chunks per batch (default: 32)",
    )
    p.add_argument(
        "--device",
        choices=["cuda", "cpu", "auto"],
        default="auto",
        help="Compute device (default: auto)",
    )
    p.add_argument(
        "--benchmark",
        action="store_true",
        help="Run all 3 models and print comparison table (no file output)",
    )
    return p.parse_args(argv)


def main(argv: List[str] | None = None) -> None:
    args = _parse_args(argv)
    input_path = Path(args.input).resolve()

    if not input_path.exists():
        logger.error("Input path does not exist: %s", input_path)
        sys.exit(1)

    # --- Benchmark mode ---
    if args.benchmark:
        if not input_path.is_file():
            logger.error("Benchmark mode requires a single JSON file as --input.")
            sys.exit(1)
        # Use any embedder just to carry device info
        emb = create_embedder(args.model, device=args.device)
        runner = ReEmbedder(emb)
        runner.benchmark(input_path)
        return

    # --- Normal mode ---
    if args.output is None:
        logger.error("--output is required when not using --benchmark.")
        sys.exit(1)

    output_path = Path(args.output).resolve()

    # Safety: do not allow overwriting input
    if input_path.is_file():
        if output_path == input_path or (
            output_path.is_dir() and (output_path / input_path.name) == input_path
        ):
            logger.error("Output must not overwrite input. Choose a different --output.")
            sys.exit(1)
    elif input_path.is_dir():
        if output_path == input_path:
            logger.error("Output directory must differ from input directory.")
            sys.exit(1)

    embedder = create_embedder(args.model, device=args.device)
    embedder.load()
    runner = ReEmbedder(embedder)

    if input_path.is_file():
        if output_path.suffix == ".json":
            out = output_path
        else:
            output_path.mkdir(parents=True, exist_ok=True)
            out = output_path / input_path.name
        runner.process_file(input_path, out, batch_size=args.batch_size)
    elif input_path.is_dir():
        runner.process_folder(input_path, output_path, batch_size=args.batch_size)
    else:
        logger.error("Input is neither file nor directory: %s", input_path)
        sys.exit(1)


if __name__ == "__main__":
    main()
