from __future__ import annotations

from datetime import datetime, timezone
import logging
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
logger = logging.getLogger(__name__)

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


def _resolve_graph_org_id(sb: Any, org_id: str) -> str:
    """Resolve incoming org identifier to Neo4j Organization id when possible."""
    normalized = str(org_id or "").strip()
    if not normalized:
        return normalized

    try:
        by_neo = (
            sb.schema("vdme")
            .table("users")
            .select("neo4j_id")
            .eq("neo4j_id", normalized)
            .maybe_single()
            .execute()
        ).data
        if by_neo and by_neo.get("neo4j_id"):
            return str(by_neo.get("neo4j_id"))
    except Exception:
        pass

    try:
        by_supabase = (
            sb.schema("vdme")
            .table("users")
            .select("neo4j_id")
            .eq("id", normalized)
            .maybe_single()
            .execute()
        ).data
        if by_supabase and by_supabase.get("neo4j_id"):
            return str(by_supabase.get("neo4j_id"))
    except Exception:
        pass

    return normalized


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
    try:
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
    except Exception as exc:
        # Do not fail the connection flow if notification persistence fails.
        logger.warning("notification insert failed (type=%s): %s", n_type, exc)


@router.post("/connect")
async def connect(
    req: ConnectRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if current_user.get("role") != "organization":
        raise HTTPException(status_code=403, detail="Chỉ Organization mới có thể kết nối")

    if current_user.get("neo4j_id") != req.org_id:
        raise HTTPException(status_code=403, detail="Bạn không được phép kết nối với org_id này")

    sb = get_supabase()
    graph_org_id = _resolve_graph_org_id(sb, req.org_id)

    existing = check_existing_relationship(req.personnel_id, graph_org_id)
    if existing:
        status = str(existing.get("status") or "").lower()
        if status == "accepted":
            raise HTTPException(status_code=400, detail="Đã kết nối trước đó")
        if status == "pending":
            raise HTTPException(status_code=400, detail="Đã gửi yêu cầu, đang chờ phản hồi")

    org_name = _get_user_name(sb, graph_org_id)
    personnel_email = _get_user_email(sb, req.personnel_id)

    if req.match_score > AUTO_CONNECT_THRESHOLD:
        now_iso = datetime.now(timezone.utc).isoformat()
        rel = create_neo4j_relationship(
            personnel_id=req.personnel_id,
            org_id=graph_org_id,
            status="accepted",
            match_score=req.match_score,
            job_title=req.job_title,
            auto_connected=True,
            connected_at=now_iso,
            requested_at=None,
        )
        if not rel:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Không tạo được kết nối: không tìm thấy organization/personnel trong Neo4j "
                    f"(org_id={graph_org_id}, personnel_id={req.personnel_id})"
                ),
            )

        _send_notification(
            recipient_neo4j_id=req.personnel_id,
            sender_neo4j_id=graph_org_id,
            n_type="connection_accepted",
            title="Bạn đã được kết nối",
            body=f"Bạn đã được {org_name} kết nối cho vị trí {req.job_title}",
            payload={
                "org_id": graph_org_id,
                "org_name": org_name,
                "job_title": req.job_title,
                "match_score": req.match_score,
            },
        )

        return {
            "status": "accepted",
            "auto_connected": True,
            "message": "Kết nối thành công. Bạn có thể bắt đầu phỏng vấn ngay.",
        }

    now_iso = datetime.now(timezone.utc).isoformat()
    rel = create_neo4j_relationship(
        personnel_id=req.personnel_id,
        org_id=graph_org_id,
        status="pending",
        match_score=req.match_score,
        job_title=req.job_title,
        auto_connected=False,
        connected_at=None,
        requested_at=now_iso,
    )
    if not rel:
        raise HTTPException(
            status_code=422,
            detail=(
                "Không tạo được request kết nối: không tìm thấy organization/personnel trong Neo4j "
                f"(org_id={graph_org_id}, personnel_id={req.personnel_id})"
            ),
        )

    _send_notification(
        recipient_neo4j_id=req.personnel_id,
        sender_neo4j_id=graph_org_id,
        n_type="connection_request",
        title="Yêu cầu kết nối mới",
        body=f"{org_name} muốn kết nối với bạn cho vị trí {req.job_title}",
        payload={
            "org_id": graph_org_id,
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
        "message": "Đã gửi yêu cầu kết nối. Đang chờ ứng viên phản hồi.",
    }


@router.patch("/connect/{personnel_id}/respond")
async def respond_connection(
    personnel_id: str,
    req: RespondConnectionRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    if current_user.get("role") != "personnel":
        raise HTTPException(status_code=403, detail="Chỉ Personnel mới có thể phản hồi")

    if current_user.get("neo4j_id") != personnel_id:
        raise HTTPException(status_code=403, detail="Bạn không được phép phản hồi request này")

    updated = respond_connection_relationship(
        personnel_id=personnel_id,
        org_id=req.org_id,
        action=req.action,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Không tìm thấy request pending")

    sb = get_supabase()
    personnel_name = _get_user_name(sb, personnel_id)
    job_title = str(updated.get("job_title") or "vị trí chưa xác định")

    if req.action == "accept":
        _send_notification(
            recipient_neo4j_id=req.org_id,
            sender_neo4j_id=personnel_id,
            n_type="connection_accepted",
            title="Yêu cầu kết nối đã được chấp nhận",
            body=f"{personnel_name} đã chấp nhận kết nối cho vị trí {job_title}",
            payload={"personnel_id": personnel_id, "org_id": req.org_id, "job_title": job_title},
        )
        return {"status": "accepted", "message": "Đã chấp nhận kết nối"}

    _send_notification(
        recipient_neo4j_id=req.org_id,
        sender_neo4j_id=personnel_id,
        n_type="connection_declined",
        title="Yêu cầu kết nối bị từ chối",
        body=f"{personnel_name} đã từ chối kết nối",
        payload={"personnel_id": personnel_id, "org_id": req.org_id},
    )
    return {"status": "declined", "message": "Đã từ chối kết nối"}
