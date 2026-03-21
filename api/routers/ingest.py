from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api.deps import get_current_user
from pipeline.config import get_logger
from pipeline.main import process_file

router = APIRouter()
logger = get_logger(__name__)

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".json"}


@router.post("")
async def ingest_file(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
) -> dict[str, str]:
    """Upload and ingest one file into existing pipeline with user target binding."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type khong ho tro: {suffix}")

    content = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        process_file(
            tmp_path,
            target_node_id=str(user.get("neo4j_id") or "").strip() or None,
            target_role=str(user.get("role") or "").strip() or None,
        )
    except Exception as exc:
        logger.error("Ingest failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    return {
        "status": "ok",
        "filename": file.filename or "",
        "neo4j_id": str(user.get("neo4j_id") or ""),
    }
