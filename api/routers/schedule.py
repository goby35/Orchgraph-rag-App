# api/routers/schedule.py
from __future__ import annotations
from typing import Any
from supabase_auth import Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from api.deps import get_current_user
from api.models.scheduling import (
    ScheduleCreate, ScheduleResponse,
    ScheduleReschedule, ScheduleStatusUpdate,
)
from pipeline.supabase_client import get_supabase
from pipeline.config import get_logger
from api.utils.supabase_helpers import sb_one
from typing import Any, cast
from openai.types.chat import ChatCompletion

logger = get_logger(__name__)
router = APIRouter()


def _notify(sb, recipient_neo4j_id: str, sender_neo4j_id: str,
            notif_type: str, title: str, body: str, payload: dict) -> None:
    """Helper: tạo notification row — fire-and-forget."""
    try:
        sb.schema("vdme").table("notifications").insert({
            "recipient_neo4j_id": recipient_neo4j_id,
            "sender_neo4j_id":    sender_neo4j_id,
            "type":               notif_type,
            "title":              title,
            "body":               body,
            "payload":            payload,
        }).execute()
    except Exception as e:
        logger.warning("[notify] Failed: %s", e)


def _get_chat_summary(org_neo4j_id: str, per_neo4j_id: str) -> str:
    """Lấy toàn bộ chat history và dùng LLM tóm tắt."""
    from pipeline.supabase_client import get_supabase as _sb
    from pipeline.config import get_extraction_client

    sb = _sb()
    raw_rows = (
        sb.schema("vdme").table("chat_messages")
        .select("role, content")
        .eq("org_neo4j_id", org_neo4j_id)
        .eq("per_neo4j_id", per_neo4j_id)
        .order("created_at")
        .execute()
    ).data or []

    rows: list[dict[str, Any]] = cast(list[dict[str, Any]], raw_rows)

    if not rows:
        return "Chưa có nội dung chat."

    conversation = "\n".join(
        f"{'[Nhà tuyển dụng]' if r.get('role') == 'user' else '[Digital Twin]'}: {r.get('content', '')}"
        for r in rows
    )

    client, model, _ = get_extraction_client()
    response = cast(ChatCompletion, client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content":
             "Bạn là trợ lý tóm tắt cuộc phỏng vấn. "
             "Tóm tắt ngắn gọn (3-5 điểm bullet) nội dung cuộc trò chuyện sau, "
             "tập trung vào: kỹ năng nổi bật, điểm phù hợp, và các thông tin quan trọng. "
             "Trả lời bằng tiếng Việt."},
            {"role": "user", "content": f"Cuộc trò chuyện:\n{conversation[:4000]}"},
        ],
        max_tokens=500,
        temperature=0,
        stream=False,
    ))
    return response.choices[0].message.content or "Không thể tóm tắt."


@router.post("", response_model=ScheduleResponse)
async def create_schedule(
    body:             ScheduleCreate,
    background_tasks: BackgroundTasks,
    user: dict        = Depends(get_current_user),
):
    """
    Org đặt lịch phỏng vấn thực.
    Trigger:
      1. Lưu vào interview_schedules
      2. [background] LLM summarize chat
      3. [background] Gửi email + .ics
      4. Tạo notification cho Personnel
    """
    user_dict = cast(dict[str, Any], user)
    if user_dict.get("role") != "organization":
        raise HTTPException(403, "Chỉ Organization mới có thể đặt lịch")

    sb = get_supabase()
    org_neo4j_id = user["neo4j_id"]

    # Tạo schedule record
    row: dict[str, Any] = sb_one(sb.schema("vdme").table("interview_schedules").insert({
        "org_neo4j_id":     org_neo4j_id,
        "per_neo4j_id":     body.per_neo4j_id,
        "proposed_at":      body.proposed_at.isoformat(),
        "duration_minutes": body.duration_minutes,
        "format":           body.format,
        "location":         body.location,
        "notes":            body.notes,
        "status":           "pending",
    }).execute())

    schedule_id: str = row.get("id", "")

    # Background: summarize + email + notification
    background_tasks.add_task(
        _process_schedule_created,
        schedule_id  = schedule_id,
        org_neo4j_id = org_neo4j_id,
        per_neo4j_id = body.per_neo4j_id,
        proposed_at  = body.proposed_at.isoformat(),
        duration     = body.duration_minutes,
        fmt          = body.format,
        location     = body.location or "",
        notes        = body.notes or "",
    )

    return row


async def _process_schedule_created(
    schedule_id: str, org_neo4j_id: str, per_neo4j_id: str,
    proposed_at: str, duration: int, fmt: str, location: str, notes: str,
) -> None:
    """Background task: summarize + email + notify."""
    from api.services.email_service import send_schedule_email
    sb = get_supabase()

    # 1. Summarize chat
    try:
        summary = _get_chat_summary(org_neo4j_id, per_neo4j_id)
        sb.schema("vdme").table("interview_schedules").update(
            {"chat_summary": summary}
        ).eq("id", schedule_id).execute()
    except Exception as e:
        logger.warning("[schedule] Summary failed: %s", e)
        summary = ""

    # 2. Gửi email
    try:
        send_schedule_email(
            schedule_id  = schedule_id,
            org_neo4j_id = org_neo4j_id,
            per_neo4j_id = per_neo4j_id,
            proposed_at  = proposed_at,
            duration     = duration,
            fmt          = fmt,
            location     = location,
            notes        = notes,
            summary      = summary,
        )
        sb.schema("vdme").table("interview_schedules").update(
            {"email_sent": True, "email_sent_at": "now()"}
        ).eq("id", schedule_id).execute()
    except Exception as e:
        logger.error("[schedule] Email failed: %s", e)

    # 3. Push in-app notification
    _notify(
        sb               = sb,
        recipient_neo4j_id = per_neo4j_id,
        sender_neo4j_id  = org_neo4j_id,
        notif_type       = "schedule_request",
        title            = "Bạn có lời mời phỏng vấn mới",
        body             = f"Lịch hẹn vào {proposed_at[:16].replace('T', ' ')}",
        payload          = {"schedule_id": schedule_id, "redirect_to": f"/schedule/{schedule_id}"},
    )


@router.patch("/{schedule_id}/reschedule", response_model=ScheduleResponse)
async def reschedule(
    schedule_id: str,
    body:        ScheduleReschedule,
    user: dict   = Depends(get_current_user),
):
    """Personnel đề xuất lại giờ khác."""
    if user["role"] != "personnel":
        raise HTTPException(403, "Chỉ Personnel mới có thể reschedule")

    sb  = get_supabase()
    row: dict[str, Any] = sb_one(
        sb.schema("vdme").table("interview_schedules").update({
            "status":         "rescheduled",
            "rescheduled_at": body.rescheduled_at.isoformat(),
            "notes":          body.notes,
        }).eq("id", schedule_id).execute().data[0]
    )
    _notify(
        sb                 = sb,
        recipient_neo4j_id = row["org_neo4j_id"],
        sender_neo4j_id    = user["neo4j_id"],
        notif_type         = "schedule_rescheduled",
        title              = "Ứng viên đề xuất đổi lịch",
        body               = f"Giờ mới: {body.rescheduled_at.isoformat()[:16].replace('T', ' ')}",
        payload            = {"schedule_id": schedule_id},
    )
    return row


@router.patch("/{schedule_id}/status", response_model=ScheduleResponse)
async def update_status(
    schedule_id: str,
    body:        ScheduleStatusUpdate,
    user: dict   = Depends(get_current_user),
):
    """Personnel confirm hoặc cancel lịch."""
    if body.status not in ("confirmed", "cancelled"):
        raise HTTPException(400, "status phải là 'confirmed' hoặc 'cancelled'")

    sb       = get_supabase()
    update   = {"status": body.status}
    if body.status == "confirmed":
        update["confirmed_at"] = "now()"
    if body.notes:
        update["notes"] = body.notes

    row: dict[str, Any] = sb_one(
        sb.schema("vdme").table("interview_schedules").update(
            update
        ).eq("id", schedule_id).execute().data[0]
    )

    notif_type = "schedule_confirmed" if body.status == "confirmed" else "schedule_cancelled"
    title      = "Ứng viên đã xác nhận lịch" if body.status == "confirmed" \
                 else "Lịch phỏng vấn bị hủy"

    _notify(
        sb                 = sb,
        recipient_neo4j_id = row["org_neo4j_id"],
        sender_neo4j_id    = user["neo4j_id"],
        notif_type         = notif_type,
        title              = title,
        body               = body.notes or "",
        payload            = {"schedule_id": schedule_id},
    )
    return row


@router.get("", response_model=list[ScheduleResponse])
async def list_schedules(user: dict = Depends(get_current_user)):
    """Lấy tất cả lịch hẹn của user hiện tại."""
    sb    = get_supabase()
    field = "org_neo4j_id" if user["role"] == "organization" else "per_neo4j_id"
    rows  = (
        sb.schema("vdme").table("interview_schedules")
        .select("*").eq(field, user["neo4j_id"])
        .order("proposed_at", desc=True)
        .execute()
    ).data or []
    return rows