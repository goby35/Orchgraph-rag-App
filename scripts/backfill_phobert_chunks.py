from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# Path bootstrap for direct script execution.
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pipeline.supabase_client import get_supabase
from pipeline.vectorizer import vectorize_text_for_model

SCHEMA_NAME = "vdme"
CHUNKS_TABLE = "document_chunks"
PHOBERT_MODEL_ID = "vinai/phobert-base-v2"
EMBEDDING_COLUMN = "embedding_phobert"
BATCH_SIZE = 16
PAGE_SIZE = 500
ERROR_LOG_PATH = Path("scripts/eval/results/phobert_backfill_errors.json")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _fetch_pending_chunks(schema_client: Any) -> list[dict[str, Any]]:
    pending: list[dict[str, Any]] = []
    offset = 0

    while True:
        rows = (
            schema_client
            .table(CHUNKS_TABLE)
            .select("id,content")
            .is_(EMBEDDING_COLUMN, "null")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        ).data or []

        if not rows:
            break

        pending.extend(_as_dict(row) for row in rows)

        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return pending


def backfill_phobert_chunks() -> None:
    sb = get_supabase()
    schema_client = sb.schema(SCHEMA_NAME)

    # Warm up PhoBERT once so model/tokenizer are loaded before loop.
    _ = vectorize_text_for_model("warmup", PHOBERT_MODEL_ID)

    chunks = _fetch_pending_chunks(schema_client)
    total = len(chunks)
    print(f"Found {total} chunks requiring {EMBEDDING_COLUMN} backfill.")

    updated = 0
    skipped = 0
    errors: list[dict[str, str]] = []
    processed = 0

    for idx in range(0, total, BATCH_SIZE):
        batch = chunks[idx: idx + BATCH_SIZE]

        for raw_chunk in batch:
            processed += 1
            chunk = _as_dict(raw_chunk)
            chunk_id = str(chunk.get("id") or "").strip()
            content = str(chunk.get("content") or "").strip()

            if not chunk_id or not content:
                skipped += 1
                if processed % 10 == 0:
                    print(f"[{processed}/{total}] Embedded chunk {chunk_id or 'N/A'}...")
                continue

            try:
                emb = vectorize_text_for_model(content, PHOBERT_MODEL_ID)
                (
                    schema_client
                    .table(CHUNKS_TABLE)
                    .update({EMBEDDING_COLUMN: emb})
                    .eq("id", chunk_id)
                    .is_(EMBEDDING_COLUMN, "null")
                    .execute()
                )
                updated += 1
            except Exception as exc:
                errors.append({"id": chunk_id, "error": str(exc)})

            if processed % 10 == 0:
                print(f"[{processed}/{total}] Embedded chunk {chunk_id}...")

    ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ERROR_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(errors, f, ensure_ascii=False, indent=2)

    print(f"Done: {updated} rows updated, {skipped} skipped, {len(errors)} errors")
    print(f"Error log: {ERROR_LOG_PATH}")


if __name__ == "__main__":
    backfill_phobert_chunks()
