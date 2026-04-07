from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.deps import get_current_user
from pipeline.chat_service import (
    create_session,
    get_session_fit_summary,
    list_sessions,
    load_history_by_session,
    save_message,
)

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
    personnel_id: str | None = None
    per_neo4j_id: str | None = None
    session_id: str
    role: str
    content: str
    job_title: str | None = None
    is_private_mode: bool = False
    reasoning: dict[str, Any] | None = None


class CreateSessionRequest(BaseModel):
    personnel_id: str
    org_id: str
    job_title: str | None = None
    reasoning_summary: dict[str, Any] | None = None


@router.post("/sessions")
async def post_session(
    body: CreateSessionRequest,
    user: dict = Depends(get_current_user),
) -> dict[str, str]:
    org_neo4j_id = _require_org_neo4j_id(user)
    if body.org_id != org_neo4j_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="org_id khong hop le",
        )
    session_id = create_session(
        org_neo4j_id=org_neo4j_id,
        personnel_neo4j_id=body.personnel_id,
        job_title=body.job_title,
        reasoning_summary=body.reasoning_summary,
    )
    return {"session_id": session_id}


@router.get("/sessions")
async def get_sessions(
    org_id: str,
    user: dict = Depends(get_current_user),
) -> list[dict[str, Any]]:
    org_neo4j_id = _require_org_neo4j_id(user)
    if org_id != org_neo4j_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="org_id khong hop le",
        )
    return list_sessions(org_neo4j_id=org_neo4j_id)


@router.get("/sessions/{session_id}/fit-summary")
async def get_fit_summary(
    session_id: str,
    org_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    org_neo4j_id = _require_org_neo4j_id(user)
    if org_id != org_neo4j_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="org_id khong hop le",
        )
    return get_session_fit_summary(org_neo4j_id=org_neo4j_id, session_id=session_id)


@router.post("/message")
async def post_message(
    body: MessageRequest,
    user: dict = Depends(get_current_user),
) -> dict[str, str]:
    org_neo4j_id = _require_org_neo4j_id(user)
    personnel_id = str(body.personnel_id or body.per_neo4j_id or "").strip()
    if not personnel_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="personnel_id la bat buoc",
        )
    if not body.session_id.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="session_id la bat buoc",
        )
    save_message(
        org_neo4j_id=org_neo4j_id,
        personnel_neo4j_id=personnel_id,
        session_id=body.session_id,
        job_title=body.job_title,
        message={
            "role": body.role,
            "content": body.content,
            "is_private_mode": body.is_private_mode,
            "reasoning": body.reasoning,
        },
    )
    return {"status": "ok"}


@router.get("/history/{session_id}")
async def get_history(
    session_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, list[dict[str, Any]]]:
    org_neo4j_id = _require_org_neo4j_id(user)
    messages = load_history_by_session(
        org_neo4j_id=org_neo4j_id,
        session_id=session_id,
    )
    return {"messages": messages}
