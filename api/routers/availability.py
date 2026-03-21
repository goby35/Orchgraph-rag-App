# api/routers/availability.py
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import zoneinfo
from fastapi import APIRouter, Depends, HTTPException
from supabase_auth import Any
from api.deps import get_current_user
from api.models.scheduling import AvailabilityUpsert, AvailabilityResponse, AvailableSlot
from pipeline.supabase_client import get_supabase
from api.utils.supabase_helpers import sb_val

router = APIRouter()


@router.put("", response_model=AvailabilityResponse)
async def upsert_availability(
    body: AvailabilityUpsert,
    user: dict = Depends(get_current_user),
):
    """Personnel thiết lập / cập nhật lịch rảnh."""
    if user["role"] != "personnel":
        raise HTTPException(403, "Chỉ Personnel mới có thể thiết lập availability")

    sb = get_supabase()
    user_id: str = sb_val(
        sb.schema("vdme").table("users")
        .select("id").eq("neo4j_id", user["neo4j_id"]).maybe_single().execute(),
        "id", ""
    )

    data = {
        "user_id":              user_id,
        "weekly_slots":         body.weekly_slots,
        "timezone":             body.timezone,
        "blocked_dates":        [d.isoformat() for d in body.blocked_dates],
        "advance_notice_hours": body.advance_notice_hours,
        "slot_duration_minutes": body.slot_duration_minutes,
        "is_active":            True,
    }
    row = (
        sb.schema("vdme").table("availability")
        .upsert(data, on_conflict="user_id").execute()
    ).data[0]
    return row


@router.get("/{per_neo4j_id}/slots", response_model=list[AvailableSlot])
async def get_available_slots(
    per_neo4j_id: str,
    days_ahead:   int = 14,   # compute 14 ngày tiếp theo
    user: dict = Depends(get_current_user),
):
    """
    Org xem danh sách slots available của Personnel.
    Compute từ weekly_slots template, loại trừ blocked_dates và advance_notice_hours.
    """
    sb = get_supabase()

    # Lấy Supabase user_id từ neo4j_id
    user_row: dict[str, Any] = sb_val(
        sb.schema("vdme").table("users")
        .select("id").eq("neo4j_id", per_neo4j_id).single().execute(),
        "id"
    )
    if not user_row:
        raise HTTPException(404, f"Không tìm thấy Personnel {per_neo4j_id}")

    avail_row: dict[str, Any] = sb_val(
        sb.schema("vdme").table("availability")
        .select("*").eq("user_id", user_row["id"]).eq("is_active", True)
        .maybe_single().execute(),
        "*"
    )
    if not avail_row:
        return []

    weekly_slots   = avail_row["weekly_slots"]    # {"Mon": ["09:00","18:00"]}
    blocked_dates  = set(avail_row.get("blocked_dates") or [])
    tz_str         = avail_row["timezone"]
    advance_hours  = avail_row["advance_notice_hours"]
    slot_duration  = avail_row["slot_duration_minutes"]

    tz      = zoneinfo.ZoneInfo(tz_str)
    now_utc = datetime.now(timezone.utc)
    slots:  list[AvailableSlot] = []

    DAY_MAP = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}

    for day_offset in range(days_ahead):
        target_date   = (now_utc + timedelta(days=day_offset)).date()
        day_name      = list(DAY_MAP.keys())[target_date.weekday()]
        time_range    = weekly_slots.get(day_name)

        if not time_range or target_date.isoformat() in blocked_dates:
            continue

        start_str, end_str = time_range[0], time_range[1]
        sh, sm = int(start_str[:2]), int(start_str[3:])
        eh, em = int(end_str[:2]),   int(end_str[3:])

        window_start = datetime(target_date.year, target_date.month, target_date.day,
                                sh, sm, tzinfo=tz)
        window_end   = datetime(target_date.year, target_date.month, target_date.day,
                                eh, em, tzinfo=tz)

        # Tạo slots theo slot_duration_minutes
        current = window_start
        while current + timedelta(minutes=slot_duration) <= window_end:
            slot_end = current + timedelta(minutes=slot_duration)
            # Kiểm tra advance_notice
            if current.astimezone(timezone.utc) > now_utc + timedelta(hours=advance_hours):
                slots.append(AvailableSlot(
                    start    = current.astimezone(timezone.utc),
                    end      = slot_end.astimezone(timezone.utc),
                    duration = slot_duration,
                ))
            current = slot_end

    return slots