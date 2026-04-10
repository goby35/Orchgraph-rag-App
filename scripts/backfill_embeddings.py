from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

load_dotenv(_ROOT / ".env", override=False)

from pipeline.supabase_client import get_supabase
from pipeline.vectorizer import embed_all_models

SCHEMA_NAME = "vdme"
CHUNKS_TABLE = "document_chunks"
EXPECTED_DIM = 768

ALLOWED_SOURCE_FIELDS = {
    "public_embeddings_gte",
    "public_embeddings_bge",
    "public_embeddings_e5",
    "public_embeddings_phobert",
}

SOURCE_TO_TARGET_FIELD = {
    "public_embeddings_gte": "embedding_gte",
    "public_embeddings_bge": "embedding_bge",
    "public_embeddings_e5": "embedding_e5",
}

ALLOWED_TARGET_FIELDS = {
    "embedding_gte",
    "embedding_bge",
    "embedding_e5",
}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(float(v)) for v in values) + "]"


def _update_chunk_embeddings(schema_client: Any, chunk_id: str, payload: dict[str, str]) -> None:
    (
        schema_client
        .table(CHUNKS_TABLE)
        .update(payload)
        .eq("id", chunk_id)
        .execute()
    )


def _to_vector_literal_if_valid(vector: Any, chunk_id: str, target_field: str) -> str | None:
    if not isinstance(vector, list) or not vector:
        return None
    if len(vector) != EXPECTED_DIM:
        print(
            f"[WARN] Skip field {target_field} for chunk {chunk_id}: "
            f"expected {EXPECTED_DIM} dims, got {len(vector)}"
        )
        return None
    return _vector_literal(vector)


def backfill_missing_embeddings(missing_field: str = "embedding_gte") -> None:
    if missing_field not in ALLOWED_TARGET_FIELDS:
        raise ValueError(f"Unsupported missing_field: {missing_field}")

    sb = get_supabase()
    schema_client = sb.schema(SCHEMA_NAME)

    # Update-only flow: process existing rows that still miss the selected embedding field.
    chunks = (
        schema_client
        .table(CHUNKS_TABLE)
        .select("id, content, embedding_gte, embedding_bge, embedding_e5")
        .is_(missing_field, "null")
        .not_.is_("content", "null")
        .neq("content", "")
        .execute()
    ).data or []

    print(f"Found {len(chunks)} chunks requiring {missing_field} backfill.")

    updated_total = 0
    failed_ids: list[str] = []

    for raw_chunk in chunks:
        chunk = _as_dict(raw_chunk)
        chunk_id = str(chunk.get("id") or "").strip()
        content = str(chunk.get("content") or "").strip()

        if not chunk_id or not content:
            continue

        try:
            embeddings_dict = embed_all_models(content)

            unexpected = [key for key in embeddings_dict.keys() if key not in ALLOWED_SOURCE_FIELDS]
            if unexpected:
                raise ValueError(f"Unexpected embedding fields for chunk {chunk_id}: {unexpected}")

            payload: dict[str, str] = {}
            for source_field, target_field in SOURCE_TO_TARGET_FIELD.items():
                if target_field not in ALLOWED_TARGET_FIELDS:
                    raise ValueError(f"Target field not whitelisted: {target_field}")

                # Write only missing embedding columns on existing rows.
                if chunk.get(target_field) is not None:
                    continue

                vector = embeddings_dict.get(source_field)
                literal = _to_vector_literal_if_valid(vector, chunk_id, target_field)
                if literal is not None:
                    payload[target_field] = literal

            if not payload:
                continue

            _update_chunk_embeddings(schema_client, chunk_id, payload)
            updated_total += 1
            if updated_total % 50 == 0:
                print(f"Updated {updated_total} chunks so far...")
        except Exception as exc:
            failed_ids.append(chunk_id)
            print(f"[WARN] Failed chunk {chunk_id}: {exc}")

    print(f"Backfill complete: {updated_total} chunks updated.")
    if failed_ids:
        print(f"[WARN] Failed chunks: {len(failed_ids)}")
        print(", ".join(failed_ids))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--missing-field",
        choices=sorted(ALLOWED_TARGET_FIELDS),
        default="embedding_gte",
        help="Select which missing embedding column to target.",
    )
    args = parser.parse_args()
    backfill_missing_embeddings(missing_field=args.missing_field)