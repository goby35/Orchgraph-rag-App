from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.deps import get_current_user
from pipeline.chat_service import load_history, save_message

router = APIRouter()


def _require_org_neo4j_id(user: dict[str, Any]) -> str:
    org_neo4j_id = str(user.get("neo4j_id") or "").strip()
    if not org_neo4j_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User chua duoc gan neo4j_id",
        )
    return org_neo4j_id


class MessageRequest(BaseModel):
    per_neo4j_id: str
    role: str
    content: str
    is_private_mode: bool = False
    reasoning: dict[str, Any] | None = None


@router.post("/message")
async def post_message(
    body: MessageRequest,
    user: dict = Depends(get_current_user),
) -> dict[str, str]:
    org_neo4j_id = _require_org_neo4j_id(user)
    save_message(
        org_neo4j_id=org_neo4j_id,
        per_neo4j_id=body.per_neo4j_id,
        message={
            "role": body.role,
            "content": body.content,
            "is_private_mode": body.is_private_mode,
            "reasoning": body.reasoning,
        },
    )
    return {"status": "ok"}


@router.api_route("/history/{per_neo4j_id}", methods=["GET", "POST"])
async def get_history(
    per_neo4j_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, list[dict[str, Any]]]:
    org_neo4j_id = _require_org_neo4j_id(user)
    messages = load_history(
        org_neo4j_id=org_neo4j_id,
        per_neo4j_id=per_neo4j_id,
    )
    return {"messages": messages}
