# api/routers/availability.py
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from unittest import result
import zoneinfo
from fastapi import APIRouter, Depends, HTTPException
from api.deps import get_current_user
from api.models.scheduling import AvailabilityUpsert, AvailabilityResponse, AvailableSlot
from pipeline.supabase_client import get_supabase
from api.utils.supabase_helpers import sb_val
from typing import Any

router = APIRouter()


@router.put("", response_model=AvailabilityResponse)
async def upsert_availability(
    body: AvailabilityUpsert,
    user: dict = Depends(get_current_user),
):
    try:
        if user["role"] != "personnel":
            raise HTTPException(403, "Chỉ Personnel mới có thể thiết lập availability")

        sb = get_supabase()
        user_id: str = sb_val(
            sb.schema("vdme").table("users")
            .select("id").eq("neo4j_id", user["neo4j_id"]).maybe_single().execute(),
            "id", ""
        )
        print(f"DEBUG neo4j_id={user['neo4j_id']!r} → user_id={user_id!r}")

        if not user_id:
            raise HTTPException(404, f"neo4j_id={user['neo4j_id']!r} không có trong vdme.users")

        data = {
            "user_id":               user_id,
            "weekly_slots":          body.weekly_slots,
            "timezone":              body.timezone,
            "blocked_dates":         [d.isoformat() for d in (body.blocked_dates or [])],
            "advance_notice_hours":  body.advance_notice_hours,
            "slot_duration_minutes": body.slot_duration_minutes,
            "is_active":             True,
        }
        print(f"DEBUG data={data}")

        result = (
            sb.schema("vdme").table("availability")
            .upsert(data, on_conflict="user_id").execute()
        )
        print(f"DEBUG result.data={result.data}")
        print(f"DEBUG result.error={getattr(result, 'error', None)}")

        if not result.data:
            raise HTTPException(500, f"Upsert trả về rỗng: {result}")

        return result.data[0]

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"EXCEPTION type: {type(e).__name__}")
        print(f"EXCEPTION str: {str(e)}")
        print(f"EXCEPTION repr: {repr(e)}")
        # Với Supabase APIError
        print(f"EXCEPTION code: {getattr(e, 'code', 'N/A')}")
        print(f"EXCEPTION message: {getattr(e, 'message', 'N/A')}")
        print(f"EXCEPTION details: {getattr(e, 'details', 'N/A')}")
        print(f"EXCEPTION hint: {getattr(e, 'hint', 'N/A')}")
        print(traceback.format_exc())
        raise

@router.get("/{per_neo4j_id}/slots", response_model=list[AvailableSlot])
async def get_available_slots(
    per_neo4j_id: str,
    days_ahead:   int = 14,
    user: dict = Depends(get_current_user),
):
    from typing import cast as _cast
    sb = get_supabase()

    # user_id là string UUID
    user_id: str = sb_val(
        sb.schema("vdme").table("users")
        .select("id").eq("neo4j_id", per_neo4j_id).maybe_single().execute(),
        "id", ""
    )
    if not user_id:
        raise HTTPException(404, f"Không tìm thấy Personnel {per_neo4j_id}")

    # avail_row: cast tường minh thành dict
    result = (
        sb.schema("vdme").table("availability")
        .select("*").eq("user_id", user_id).eq("is_active", True)
        .maybe_single().execute()
    )
    raw = result.data if result is not None else None
    
    if not raw:
        return []

    avail_row = _cast(dict[str, Any], raw)

    weekly_slots  = _cast(dict[str, list[str]], avail_row["weekly_slots"])
    blocked_dates = set(_cast(list[str], avail_row.get("blocked_dates") or []))
    tz_str        = _cast(str,  avail_row["timezone"])
    advance_hours = _cast(int,  avail_row["advance_notice_hours"])
    slot_duration = _cast(int,  avail_row["slot_duration_minutes"])

    tz      = zoneinfo.ZoneInfo(tz_str)
    now_utc = datetime.now(timezone.utc)
    slots:  list[AvailableSlot] = []

    DAY_MAP = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}

    for day_offset in range(days_ahead):
        target_date = (now_utc + timedelta(days=day_offset)).date()
        day_name    = list(DAY_MAP.keys())[target_date.weekday()]
        time_range  = weekly_slots.get(day_name)

        if not time_range or target_date.isoformat() in blocked_dates:
            continue

        start_str, end_str = time_range[0], time_range[1]
        sh, sm = int(start_str[:2]), int(start_str[3:])
        eh, em = int(end_str[:2]),   int(end_str[3:])

        window_start = datetime(
            target_date.year, target_date.month, target_date.day,
            sh, sm, tzinfo=tz,
        )
        window_end = datetime(
            target_date.year, target_date.month, target_date.day,
            eh, em, tzinfo=tz,
        )

        current = window_start
        while current + timedelta(minutes=slot_duration) <= window_end:
            slot_end = current + timedelta(minutes=slot_duration)
            if current.astimezone(timezone.utc) > now_utc + timedelta(hours=advance_hours):
                slots.append(AvailableSlot(
                    start    = current.astimezone(timezone.utc),
                    end      = slot_end.astimezone(timezone.utc),
                    duration = slot_duration,
                ))
            current = slot_end

    return slots