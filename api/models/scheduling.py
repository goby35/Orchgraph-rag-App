# api/models/scheduling.py
from __future__ import annotations
from datetime import datetime, date
from typing import Any
from pydantic import BaseModel, Field


# ── Availability ─────────────────────────────────────────────────

class WeeklySlot(BaseModel):
    """VD: {"Mon": ["09:00", "18:00"]}"""
    Mon: list[str] | None = None
    Tue: list[str] | None = None
    Wed: list[str] | None = None
    Thu: list[str] | None = None
    Fri: list[str] | None = None
    Sat: list[str] | None = None
    Sun: list[str] | None = None


class AvailabilityUpsert(BaseModel):
    weekly_slots:          dict[str, list[str]]  # {"Mon": ["09:00", "18:00"], ...}
    timezone:              str = "Asia/Ho_Chi_Minh"
    blocked_dates:         list[date] = Field(default_factory=list)
    advance_notice_hours:  int = 24
    slot_duration_minutes: int = 60


class AvailabilityResponse(AvailabilityUpsert):
    id:         str
    user_id:    str
    is_active:  bool
    updated_at: datetime


class AvailableSlot(BaseModel):
    """Một slot cụ thể được compute từ availability template."""
    start:    datetime
    end:      datetime
    duration: int  # minutes


# ── Schedule ──────────────────────────────────────────────────────

class ScheduleCreate(BaseModel):
    per_neo4j_id:     str
    proposed_at:      datetime    # UTC timestamp
    duration_minutes: int = 60
    format:           str = "online"  # "online" | "offline"
    location:         str | None = None
    notes:            str | None = None


class ScheduleResponse(BaseModel):
    id:              str
    org_neo4j_id:    str
    per_neo4j_id:    str
    proposed_at:     datetime
    rescheduled_at:  datetime | None
    confirmed_at:    datetime | None
    duration_minutes: int
    format:          str
    location:        str | None
    status:          str
    chat_summary:    str | None
    email_sent:      bool
    created_at:      datetime


class ScheduleReschedule(BaseModel):
    rescheduled_at: datetime
    notes:          str | None = None


class ScheduleStatusUpdate(BaseModel):
    status: str   # "confirmed" | "cancelled"
    notes:  str | None = None


# ── Notification ─────────────────────────────────────────────────

class NotificationResponse(BaseModel):
    id:                 str
    recipient_neo4j_id: str
    sender_neo4j_id:    str | None
    type:               str
    title:              str
    body:               str | None
    payload:            dict[str, Any]
    is_read:            bool
    read_at:            datetime | None
    created_at:         datetime