from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import get_current_user
from api.services.email_service import send_connection_request_email
from pipeline.neo4j_ingestion import (
    check_existing_relationship,
    create_neo4j_relationship,
    respond_connection_relationship,
)
from pipeline.supabase_client import get_supabase

router = APIRouter()

AUTO_CONNECT_THRESHOLD = 0.6


class ConnectRequest(BaseModel):
    personnel_id: str
    org_id: str
    match_score: float = Field(ge=0.0, le=1.0)
    job_title: str = Field(min_length=1, max_length=250)


class RespondConnectionRequest(BaseModel):
    org_id: str
    action: Literal["accept", "decline"]


def _get_user_name(sb: Any, neo4j_id: str) -> str:
    try:
        row = (
            sb.schema("vdme")
            .table("users")
            .select("full_name")
            .eq("neo4j_id", neo4j_id)
            .maybe_single()
            .execute()
        ).data
        if row and row.get("full_name"):
            return str(row.get("full_name"))
    except Exception:
        pass
    return neo4j_id


def _get_user_email(sb: Any, neo4j_id: str) -> str:
    try:
        row = (
            sb.schema("vdme")
            .table("users")
            .select("email")
            .eq("neo4j_id", neo4j_id)
            .maybe_single()
            .execute()
        ).data
        if row and row.get("email"):
            return str(row.get("email"))
    except Exception:
        pass
    return ""


def _send_notification(
    *,
    recipient_neo4j_id: str,
    sender_neo4j_id: str,
    n_type: str,
    title: str,
    body: str,
    payload: dict[str, Any],
) -> None:
    sb = get_supabase()
    sb.schema("vdme").table("notifications").insert(
        {
            "recipient_neo4j_id": recipient_neo4j_id,
            "sender_neo4j_id": sender_neo4j_id,
            "type": n_type,
            "title": title,
            "body": body,
            "payload": payload,
            "is_read": False,
        }
    ).execute()


@router.post("/connect")
async def connect(
    req: ConnectRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if current_user.get("role") != "organization":
        raise HTTPException(status_code=403, detail="Chi Organization moi co the ket noi")

    if current_user.get("neo4j_id") != req.org_id:
        raise HTTPException(status_code=403, detail="Ban khong duoc phep ket noi voi org_id nay")

    existing = check_existing_relationship(req.personnel_id, req.org_id)
    if existing:
        status = str(existing.get("status") or "").lower()
        if status == "accepted":
            raise HTTPException(status_code=400, detail="Da ket noi truoc do")
        if status == "pending":
            raise HTTPException(status_code=400, detail="Da gui yeu cau, dang cho phan hoi")

    sb = get_supabase()
    org_name = _get_user_name(sb, req.org_id)
    personnel_email = _get_user_email(sb, req.personnel_id)

    if req.match_score > AUTO_CONNECT_THRESHOLD:
        now_iso = datetime.now(timezone.utc).isoformat()
        rel = create_neo4j_relationship(
            personnel_id=req.personnel_id,
            org_id=req.org_id,
            status="accepted",
            match_score=req.match_score,
            job_title=req.job_title,
            auto_connected=True,
            connected_at=now_iso,
            requested_at=None,
        )
        if not rel:
            raise HTTPException(status_code=404, detail="Khong tim thay organization/personnel")

        _send_notification(
            recipient_neo4j_id=req.personnel_id,
            sender_neo4j_id=req.org_id,
            n_type="auto_connected",
            title="Ban da duoc ket noi",
            body=f"Ban da duoc {org_name} ket noi cho vi tri {req.job_title}",
            payload={
                "org_id": req.org_id,
                "org_name": org_name,
                "job_title": req.job_title,
                "match_score": req.match_score,
            },
        )

        return {
            "status": "accepted",
            "auto_connected": True,
            "message": "Ket noi thanh cong. Ban co the bat dau phong van ngay.",
        }

    now_iso = datetime.now(timezone.utc).isoformat()
    rel = create_neo4j_relationship(
        personnel_id=req.personnel_id,
        org_id=req.org_id,
        status="pending",
        match_score=req.match_score,
        job_title=req.job_title,
        auto_connected=False,
        connected_at=None,
        requested_at=now_iso,
    )
    if not rel:
        raise HTTPException(status_code=404, detail="Khong tim thay organization/personnel")

    _send_notification(
        recipient_neo4j_id=req.personnel_id,
        sender_neo4j_id=req.org_id,
        n_type="connection_request",
        title="Yeu cau ket noi moi",
        body=f"{org_name} muon ket noi voi ban cho vi tri {req.job_title}",
        payload={
            "org_id": req.org_id,
            "org_name": org_name,
            "job_title": req.job_title,
            "match_score": req.match_score,
        },
    )

    send_connection_request_email(
        to_email=personnel_email,
        org_name=org_name,
        job_title=req.job_title,
    )

    return {
        "status": "pending",
        "auto_connected": False,
        "message": "Da gui yeu cau ket noi. Dang cho ung vien phan hoi.",
    }


@router.patch("/connect/{personnel_id}/respond")
async def respond_connection(
    personnel_id: str,
    req: RespondConnectionRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    if current_user.get("role") != "personnel":
        raise HTTPException(status_code=403, detail="Chi Personnel moi co the phan hoi")

    if current_user.get("neo4j_id") != personnel_id:
        raise HTTPException(status_code=403, detail="Ban khong duoc phep phan hoi request nay")

    updated = respond_connection_relationship(
        personnel_id=personnel_id,
        org_id=req.org_id,
        action=req.action,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Khong tim thay request pending")

    sb = get_supabase()
    personnel_name = _get_user_name(sb, personnel_id)
    job_title = str(updated.get("job_title") or "vi tri chua xac dinh")

    if req.action == "accept":
        _send_notification(
            recipient_neo4j_id=req.org_id,
            sender_neo4j_id=personnel_id,
            n_type="connection_accepted",
            title="Yeu cau ket noi da duoc chap nhan",
            body=f"{personnel_name} da chap nhan ket noi cho vi tri {job_title}",
            payload={"personnel_id": personnel_id, "org_id": req.org_id, "job_title": job_title},
        )
        return {"status": "accepted", "message": "Da chap nhan ket noi"}

    _send_notification(
        recipient_neo4j_id=req.org_id,
        sender_neo4j_id=personnel_id,
        n_type="connection_declined",
        title="Yeu cau ket noi da bi tu choi",
        body=f"{personnel_name} da tu choi ket noi",
        payload={"personnel_id": personnel_id, "org_id": req.org_id},
    )
    return {"status": "declined", "message": "Da tu choi ket noi"}
