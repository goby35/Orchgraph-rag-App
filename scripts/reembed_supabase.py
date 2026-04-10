from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

load_dotenv(_ROOT / ".env", override=False)

from pipeline.config import get_logger
from pipeline.supabase_client import get_supabase
from pipeline.supabase_ingestion import _vector_literal
from pipeline.vectorizer import _embedder

logger = get_logger(__name__)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="phobert")
    args = parser.parse_args()

    if args.model != "phobert":
        raise ValueError("Current script supports only phobert in this repository state")

    sb = get_supabase()

    chunks = (
        sb.schema("vdme")
        .table("document_chunks")
        .select("id, content")
        .execute()
    ).data or []

    for raw_chunk in chunks:
        chunk = _as_dict(raw_chunk)
        if not chunk:
            continue
        chunk_id = chunk.get("id")
        content = str(chunk.get("content") or "")
        if not chunk_id or not content.strip():
            continue

        vector = _embedder.embed(content)
        sb.schema("vdme").table("chunk_embeddings").upsert(
            {
                "chunk_id": chunk_id,
                "model_name": args.model,
                "embedding_768": _vector_literal(vector),
            },
            on_conflict="chunk_id,model_name",
        ).execute()

    logger.info("Done re-embedding %d chunks", len(chunks))


if __name__ == "__main__":
    main()
