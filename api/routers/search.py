from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import get_current_user
from pipeline.hybrid_query_engine import MasterAgentEngine

router = APIRouter()


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)


@router.post("")
async def search_candidates(
    body: SearchRequest,
    user: dict = Depends(get_current_user),
) -> dict[str, list[dict[str, object]]]:
    if user.get("role") != "organization":
        raise HTTPException(status_code=403, detail="Chi Organization moi co the tim ung vien")

    with MasterAgentEngine() as engine:
        results = engine.search_candidates(body.query, top_k=body.top_k)

    return {
        "results": [
            {
                "id": item.id,
                "name": item.name,
                "score": item.score,
                "skills": item.skills,
                "summary": item.summary,
            }
            for item in results
        ]
    }
