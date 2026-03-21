# api/services/email_service.py
"""
Email service cho scheduling.
Fixed accounts cho demo — không cần OAuth.
"""
from __future__ import annotations
import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from pipeline.config import get_logger
from icalendar import Calendar, Event, vText
from datetime import timezone
import uuid as _uuid
from api.utils.supabase_helpers import sb_val

logger = get_logger(__name__)

SENDER_EMAIL    = os.getenv("DEMO_SENDER_EMAIL", "")
SENDER_PASSWORD = os.getenv("DEMO_SENDER_APP_PASSWORD", "")
CALENDAR_EMAIL  = os.getenv("DEMO_CALENDAR_EMAIL", "")
RECIPIENT_EMAIL = os.getenv("DEMO_RECIPIENT_EMAIL", "")  # fallback khi chưa có email thật


def _build_ics(
    schedule_id:  str,
    proposed_at:  str,
    duration:     int,
    fmt:          str,
    location:     str,
    org_name:     str,
    per_name:     str,
    summary_text: str,
) -> bytes:
    from datetime import timedelta

    cal = Calendar()
    cal.add("prodid", "-//Digital Twin Recruitment//VI")
    cal.add("version", "2.0")
    cal.add("method", "REQUEST")  # khiến Gmail hiển thị nút Accept/Decline

    event = Event()
    dt_start = datetime.fromisoformat(proposed_at).replace(tzinfo=timezone.utc)
    dt_end   = dt_start + timedelta(minutes=duration)

    event.add("uid",         schedule_id)
    event.add("summary",     f"Phỏng vấn: {org_name} × {per_name}")
    event.add("dtstart",     dt_start)
    event.add("dtend",       dt_end)
    event.add("description", (
        f"Hình thức: {'Online' if fmt == 'online' else 'Offline'}\n"
        f"Địa điểm: {location}\n\n"
        f"Tóm tắt cuộc trò chuyện:\n{summary_text}"
    ))
    event.add("location",    location or ("Google Meet" if fmt == "online" else "Văn phòng"))
    event.add("organizer",   vText(f"MAILTO:{os.getenv('DEMO_SENDER_EMAIL', '')}"))

    cal.add_component(event)
    return cal.to_ical()

def _build_html_body(
    org_name:     str,
    per_name:     str,
    proposed_at:  str,
    duration:     int,
    fmt:          str,
    location:     str,
    notes:        str,
    summary_text: str,
) -> str:
    """HTML email template."""
    dt = datetime.fromisoformat(proposed_at).replace(tzinfo=timezone.utc)
    dt_formatted = dt.strftime("%H:%M, %d/%m/%Y (UTC)")
    fmt_label    = "Online (Google Meet)" if fmt == "online" else "Offline (Tại văn phòng)"

    summary_html = "".join(
        f"<li>{line.lstrip('•- ')}</li>"
        for line in summary_text.split("\n")
        if line.strip()
    )

    return f"""
    <html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: auto;">
      <div style="background:#0D1219;padding:20px;border-radius:8px;margin-bottom:20px;">
        <h2 style="color:#00C9B8;margin:0;">Digital Twin Recruitment</h2>
        <p style="color:#8E99AE;margin:4px 0 0;">Lời mời phỏng vấn</p>
      </div>

      <p>Xin chào <strong>{per_name}</strong>,</p>
      <p><strong>{org_name}</strong> đã xem xét hồ sơ và muốn sắp xếp buổi gặp mặt với bạn.</p>

      <div style="background:#f5f5f5;padding:16px;border-radius:8px;margin:20px 0;">
        <h3 style="margin:0 0 12px;">Thông tin lịch hẹn</h3>
        <table style="width:100%;border-collapse:collapse;">
          <tr><td style="padding:6px 0;color:#666;">Thời gian</td>
              <td><strong>{dt_formatted}</strong></td></tr>
          <tr><td style="padding:6px 0;color:#666;">Thời lượng</td>
              <td>{duration} phút</td></tr>
          <tr><td style="padding:6px 0;color:#666;">Hình thức</td>
              <td>{fmt_label}</td></tr>
          <tr><td style="padding:6px 0;color:#666;">Địa điểm</td>
              <td>{location or "Sẽ được chia sẻ sau"}</td></tr>
          {f'<tr><td style="padding:6px 0;color:#666;">Ghi chú</td><td>{notes}</td></tr>' if notes else ''}
        </table>
      </div>

      <div style="background:#e8f4f8;padding:16px;border-radius:8px;margin:20px 0;">
        <h3 style="margin:0 0 12px;">Tóm tắt cuộc trò chuyện với Digital Twin</h3>
        <ul style="margin:0;padding-left:20px;">
          {summary_html}
        </ul>
      </div>

      <p>File <strong>.ics</strong> đã được đính kèm — bạn có thể import vào Google Calendar,
      Outlook, hoặc Apple Calendar.</p>

      <p style="color:#999;font-size:12px;margin-top:30px;">
        Email này được gửi tự động từ hệ thống Digital Twin Recruitment.<br>
        Vui lòng không reply trực tiếp email này.
      </p>
    </body></html>
    """


def send_schedule_email(
    schedule_id:  str,
    org_neo4j_id: str,
    per_neo4j_id: str,
    proposed_at:  str,
    duration:     int,
    fmt:          str,
    location:     str,
    notes:        str,
    summary:      str,
) -> None:
    """
    Gửi email thông báo lịch hẹn kèm .ics file.

    Demo mode:
    - Gửi từ DEMO_SENDER_EMAIL
    - Gửi đến DEMO_RECIPIENT_EMAIL (hoặc email thật của Personnel nếu có)
    - CC đến DEMO_CALENDAR_EMAIL (để import calendar)
    """
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        logger.warning("[email] DEMO_SENDER_EMAIL / DEMO_SENDER_APP_PASSWORD chưa được set")
        return

    # Lấy tên Org và Personnel từ Neo4j (để hiển thị trong email)
    org_name = org_neo4j_id   # fallback nếu không query được
    per_name = per_neo4j_id
    recipient = RECIPIENT_EMAIL  # demo mode: gửi đến fixed address

    try:
        from pipeline.supabase_client import get_supabase
        sb = get_supabase()
        per_row: str = sb_val(
            sb.schema("vdme").table("users")
            .select("full_name").eq("neo4j_id", per_neo4j_id).maybe_single().execute(),
            "full_name"
        )
        org_row: str = sb_val(
            sb.schema("vdme").table("users")
            .select("full_name").eq("neo4j_id", org_neo4j_id).maybe_single().execute(),
            "full_name"
        )
        if per_row:
            per_name = per_row
        if org_row:
            org_name = org_row
    except Exception:
        pass

    # Build email
    msg = MIMEMultipart("mixed")
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = recipient
    msg["Subject"] = f"[Digital Twin] Lời mời phỏng vấn từ {org_name}"

    # CC calendar email để import .ics
    if CALENDAR_EMAIL and CALENDAR_EMAIL != recipient:
        msg["Cc"] = CALENDAR_EMAIL

    # HTML body
    html_body = _build_html_body(
        org_name    = org_name,
        per_name    = per_name,
        proposed_at = proposed_at,
        duration    = duration,
        fmt         = fmt,
        location    = location,
        notes       = notes,
        summary_text = summary,
    )
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # .ics attachment
    ics_content = _build_ics(
        schedule_id  = schedule_id,
        proposed_at  = proposed_at,
        duration     = duration,
        fmt          = fmt,
        location     = location,
        org_name     = org_name,
        per_name     = per_name,
        summary_text = summary,
    )
    ics_part = MIMEBase("text", "calendar", method="REQUEST", name="interview.ics")
    ics_part.set_payload(ics_content)
    encoders.encode_base64(ics_part)
    ics_part.add_header(
        "Content-Disposition",
        "attachment",
        filename="interview.ics",
    )
    msg.attach(ics_part)

    # Gửi qua Gmail SMTP
    all_recipients = [recipient]
    if CALENDAR_EMAIL and CALENDAR_EMAIL != recipient:
        all_recipients.append(CALENDAR_EMAIL)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(SENDER_EMAIL, SENDER_PASSWORD)
        smtp.sendmail(SENDER_EMAIL, all_recipients, msg.as_string())

    logger.info(
        "[email] Gửi thành công: schedule=%s, to=%s",
        schedule_id, all_recipients,
    )   