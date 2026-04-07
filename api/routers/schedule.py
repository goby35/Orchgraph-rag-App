# api/routers/schedule.py
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from api.deps import get_current_user
from api.models.scheduling import (
    ScheduleCounterPropose,
    ScheduleCreate,
    ScheduleResponse,
    ScheduleReschedule,
    ScheduleStatusUpdate,
)
from pipeline.supabase_client import get_supabase
from pipeline.config import get_logger
from api.utils.supabase_helpers import sb_one
from openai.types.chat import ChatCompletion

logger = get_logger(__name__)
router = APIRouter()

_AWAITING_STATUSES = {"awaiting_org_response", "awaiting_personnel_response", "rescheduled"}
_REMINDER_NOTIFICATION_TYPE = "schedule_pending_reminder"


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


def _insert_schedule_row(sb: Any, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return sb_one(sb.schema("vdme").table("interview_schedules").insert(payload).execute())
    except Exception as exc:
        if "reschedule_history" not in str(exc):
            raise

        fallback_payload = dict(payload)
        fallback_payload.pop("reschedule_history", None)
        logger.warning("[schedule] Falling back without reschedule_history column: %s", exc)
        return sb_one(sb.schema("vdme").table("interview_schedules").insert(fallback_payload).execute())


def _update_schedule_row(sb: Any, schedule_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return sb_one(
            sb.schema("vdme").table("interview_schedules")
            .update(payload)
            .eq("id", schedule_id)
            .execute()
        )
    except Exception as exc:
        if "reschedule_history" not in str(exc):
            raise

        fallback_payload = dict(payload)
        fallback_payload.pop("reschedule_history", None)
        logger.warning("[schedule] Falling back update without reschedule_history column: %s", exc)
        return sb_one(
            sb.schema("vdme").table("interview_schedules")
            .update(fallback_payload)
            .eq("id", schedule_id)
            .execute()
        )


def _parse_iso_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _normalize_reschedule_history(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    history: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        by = str(item.get("by") or "").strip()
        proposed_time = str(item.get("proposed_time") or "").strip()
        timestamp = str(item.get("timestamp") or "").strip()
        if not by or not proposed_time or not timestamp:
            continue
        entry: dict[str, Any] = {
            "by": by,
            "proposed_time": proposed_time,
            "timestamp": timestamp,
        }
        notes = item.get("notes")
        if notes:
            entry["notes"] = str(notes)
        history.append(entry)
    return history


def _append_reschedule_history(row: dict[str, Any], by: str, proposed_time: datetime, notes: str | None = None) -> list[dict[str, Any]]:
    history = _normalize_reschedule_history(row.get("reschedule_history"))
    entry: dict[str, Any] = {
        "by": by,
        "proposed_time": proposed_time.isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if notes:
        entry["notes"] = notes
    history.append(entry)
    return history


def _schedule_reference_time(row: dict[str, Any]) -> datetime | None:
    history = _normalize_reschedule_history(row.get("reschedule_history"))
    if history:
        last_entry = history[-1]
        parsed = _parse_iso_datetime(last_entry.get("timestamp"))
        if parsed:
            return parsed

    for key in ("updated_at", "confirmed_at", "rescheduled_at", "created_at"):
        parsed = _parse_iso_datetime(row.get(key))
        if parsed:
            return parsed
    return None


def _schedule_needs_reminder(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "").strip().lower()
    if status not in _AWAITING_STATUSES:
        return False

    touched_at = _schedule_reference_time(row)
    if not touched_at:
        return False
    return datetime.now(timezone.utc) - touched_at >= timedelta(hours=24)


def _reminder_exists(sb: Any, recipient_neo4j_id: str, schedule_id: str) -> bool:
    rows = (
        sb.schema("vdme").table("notifications")
        .select("id, payload, type")
        .eq("recipient_neo4j_id", recipient_neo4j_id)
        .eq("type", _REMINDER_NOTIFICATION_TYPE)
        .execute()
    ).data or []

    for raw_row in rows:
        row = cast(dict[str, Any], raw_row)
        payload = row.get("payload")
        if isinstance(payload, dict) and str(payload.get("schedule_id") or "") == schedule_id:
            return True
    return False


def _send_schedule_transition_email(
    *,
    recipient_role: str,
    schedule_id: str,
    org_neo4j_id: str,
    per_neo4j_id: str,
    proposed_time: str,
    action_label: str,
    notes: str | None = None,
) -> None:
    from api.services.email_service import send_schedule_notification_email

    message = (
        f"{action_label} cho lịch hẹn lúc {proposed_time[:16].replace('T', ' ')}."
    )
    if notes:
        message += f" Ghi chú: {notes}"

    try:
        send_schedule_notification_email(
            subject=f"[Digital Twin] {action_label}",
            headline=action_label,
            message=message,
            org_neo4j_id=org_neo4j_id,
            per_neo4j_id=per_neo4j_id,
            recipient_role=recipient_role,
        )
    except Exception as exc:
        logger.warning("[schedule] Transition email failed: %s", exc)


def _maybe_create_schedule_reminder(sb: Any, row: dict[str, Any]) -> None:
    if not _schedule_needs_reminder(row):
        return

    status = str(row.get("status") or "").strip().lower()
    recipient_neo4j_id = str(row.get("org_neo4j_id") if status in {"awaiting_org_response", "rescheduled"} else row.get("per_neo4j_id") or "").strip()
    if not recipient_neo4j_id:
        return
    schedule_id = str(row.get("id") or "").strip()
    if not schedule_id or _reminder_exists(sb, recipient_neo4j_id, schedule_id):
        return

    _notify(
        sb=sb,
        recipient_neo4j_id=recipient_neo4j_id,
        sender_neo4j_id=str(row.get("org_neo4j_id") or ""),
        notif_type=_REMINDER_NOTIFICATION_TYPE,
        title="Lịch hẹn đang chờ phản hồi",
        body="Lịch hẹn này đã chờ hơn 24 giờ mà chưa có phản hồi.",
        payload={"schedule_id": schedule_id, "status": status, "redirect_to": "/schedule"},
    )


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
    row: dict[str, Any] = _insert_schedule_row(sb, {
        "org_neo4j_id":     org_neo4j_id,
        "per_neo4j_id":     body.per_neo4j_id,
        "proposed_at":      body.proposed_at.isoformat(),
        "duration_minutes": body.duration_minutes,
        "format":           body.format,
        "location":         body.location,
        "notes":            body.notes,
        "status":           "pending",
        "reschedule_history": [],
    })

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
        payload          = {"schedule_id": schedule_id, "redirect_to": "/schedule"},
    )


@router.patch("/{schedule_id}/reschedule", response_model=ScheduleResponse)
async def reschedule(
    schedule_id: str,
    body: ScheduleReschedule,
    user: dict = Depends(get_current_user),
):
    """Personnel đề xuất lại giờ khác."""
    if user["role"] != "personnel":
        raise HTTPException(403, "Chỉ Personnel mới có thể reschedule")

    sb = get_supabase()
    current_row: dict[str, Any] = sb_one(
        sb.schema("vdme").table("interview_schedules")
        .select("*")
        .eq("id", schedule_id)
        .execute()
    )
    history = _append_reschedule_history(current_row, "personnel", body.rescheduled_at, body.notes)

    row: dict[str, Any] = _update_schedule_row(sb, schedule_id, {
        "status":            "awaiting_org_response",
        "rescheduled_at":    body.rescheduled_at.isoformat(),
        "notes":             body.notes,
        "reschedule_history": history,
    })

    _notify(
        sb=sb,
        recipient_neo4j_id=row["org_neo4j_id"],
        sender_neo4j_id=user["neo4j_id"],
        notif_type="schedule_rescheduled",
        title="Ứng viên đề xuất đổi lịch",
        body=f"Giờ mới: {body.rescheduled_at.isoformat()[:16].replace('T', ' ')}",
        payload={"schedule_id": schedule_id, "proposed_time": body.rescheduled_at.isoformat(), "status": "awaiting_org_response", "redirect_to": "/schedule"},
    )

    _send_schedule_transition_email(
        recipient_role="organization",
        schedule_id=schedule_id,
        org_neo4j_id=row["org_neo4j_id"],
        per_neo4j_id=row["per_neo4j_id"],
        proposed_time=body.rescheduled_at.isoformat(),
        action_label="Ứng viên đề xuất đổi lịch",
        notes=body.notes,
    )
    return row


@router.patch("/{schedule_id}/counter-propose", response_model=ScheduleResponse)
async def counter_propose(
    schedule_id: str,
    body: ScheduleCounterPropose,
    user: dict = Depends(get_current_user),
):
    """Org đề xuất một giờ khác cho lịch hẹn."""
    if user["role"] != "organization":
        raise HTTPException(403, "Chỉ Organization mới có thể counter-propose")

    sb = get_supabase()
    current_row: dict[str, Any] = sb_one(
        sb.schema("vdme").table("interview_schedules")
        .select("*")
        .eq("id", schedule_id)
        .execute()
    )
    history = _append_reschedule_history(current_row, "org", body.proposed_time, body.notes)

    row: dict[str, Any] = _update_schedule_row(sb, schedule_id, {
        "status":            "awaiting_personnel_response",
        "rescheduled_at":    body.proposed_time.isoformat(),
        "notes":             body.notes,
        "reschedule_history": history,
    })

    _notify(
        sb=sb,
        recipient_neo4j_id=row["per_neo4j_id"],
        sender_neo4j_id=user["neo4j_id"],
        notif_type="schedule_counter_proposed",
        title="Org đề xuất giờ khác",
        body=f"Giờ mới: {body.proposed_time.isoformat()[:16].replace('T', ' ')}",
        payload={"schedule_id": schedule_id, "proposed_time": body.proposed_time.isoformat(), "status": "awaiting_personnel_response", "redirect_to": "/schedule"},
    )

    _send_schedule_transition_email(
        recipient_role="personnel",
        schedule_id=schedule_id,
        org_neo4j_id=row["org_neo4j_id"],
        per_neo4j_id=row["per_neo4j_id"],
        proposed_time=body.proposed_time.isoformat(),
        action_label="Org đề xuất giờ khác",
        notes=body.notes,
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
        ).eq("id", schedule_id).execute()
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

    for raw_row in rows:
        row = cast(dict[str, Any], raw_row)
        _maybe_create_schedule_reminder(sb, row)

    return rows