from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import get_current_user
from pipeline.config import get_logger
from pipeline.hybrid_query_engine import MasterAgentEngine, _explain_fit
from pipeline.neo4j_ingestion import get_connection_statuses_batch

router = APIRouter()
logger = get_logger(__name__)


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)
    include_explanation: bool = Field(default=False)


@router.post("")
async def search_candidates(
    body: SearchRequest,
    user: dict = Depends(get_current_user),
) -> dict[str, list[dict[str, object]]]:
    if user.get("role") != "organization":
        raise HTTPException(status_code=403, detail="Chỉ Organization mới có thể tìm ứng viên")

    logger.info("/search request received: top_k=%s include_explanation=%s", body.top_k, body.include_explanation)

    try:
        with MasterAgentEngine() as engine:
            results = engine.search_candidates(body.query, top_k=body.top_k)
    except Exception as exc:
        logger.exception("Search pipeline failed")
        raise HTTPException(status_code=503, detail=f"Search service unavailable: {exc}") from exc

    org_id = str(user.get("neo4j_id") or "")
    if not org_id:
        logger.error("User %s has no neo4j_id profile mapping", user.get("supabase_id"))
        raise HTTPException(status_code=400, detail="Tài khoản chưa được liên kết neo4j_id")

    personnel_ids = [str(item.id) for item in results]
    try:
        connection_statuses = get_connection_statuses_batch(personnel_ids, org_id)
    except Exception:
        logger.exception("Failed to load connection statuses")
        connection_statuses = {}

    output_rows: list[dict[str, object]] = []
    for item in results:
        fit_explanation = _explain_fit(item, body.query) if body.include_explanation else None
        output_rows.append(
            {
                "id": item.id,
                "personnel_id": item.id,
                "name": item.name,
                "score": item.score,
                "match_score": item.score,
                "skills": item.skills,
                "summary": item.summary,
                "reasoning_summary": {
                    "skills": item.skills,
                    "seniority_years": None,
                    "connection_strength": None,
                    "match_score": item.score,
                    "graph_score": getattr(item, "graph_score", None),
                    "vector_score": getattr(item, "vector_score", None),
                },
                "fit_explanation": fit_explanation,
                "connection_status": connection_statuses.get(str(item.id), "not_connected"),
            }
        )

    logger.info("/search returned %d candidates", len(output_rows))
    return {"results": output_rows}
