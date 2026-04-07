from __future__ import annotations

from typing import Any
from uuid import uuid4

from neo4j import GraphDatabase
from openai import OpenAI

from pipeline.config import get_logger
from pipeline.config import settings
from pipeline.supabase_client import get_supabase

logger = get_logger(__name__)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _coerce_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value != value:
            return None
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _normalize_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    summary: dict[str, Any] = {
        "skills": [],
        "seniority_years": None,
        "connection_strength": None,
        "match_score": None,
    }

    seen_skills: set[str] = set()
    raw_skills = value.get("skills")
    if isinstance(raw_skills, list):
        for skill in raw_skills:
            text = str(skill or "").strip()
            if text and text not in seen_skills:
                seen_skills.add(text)
                summary["skills"].append(text)

    for key in ("seniority_years", "connection_strength", "match_score"):
        numeric_value = _coerce_number(value.get(key))
        if numeric_value is not None:
            summary[key] = numeric_value

    if not summary["skills"] and all(summary[key] is None for key in ("seniority_years", "connection_strength", "match_score")):
        return None

    return summary


def build_reasoning_summary(
    existing_summary: Any | None,
    reasoning_payloads: list[Any],
) -> dict[str, Any] | None:
    summary = _normalize_summary(existing_summary) or {
        "skills": [],
        "seniority_years": None,
        "connection_strength": None,
        "match_score": None,
    }

    seen_skills = set(summary["skills"])

    def update_max(field: str, candidate: Any) -> None:
        current_value = _coerce_number(summary.get(field))
        candidate_value = _coerce_number(candidate)
        if candidate_value is None:
            return
        if current_value is None or candidate_value > current_value:
            summary[field] = candidate_value

    for raw_payload in reasoning_payloads:
        payload = _as_dict(raw_payload)
        if not payload:
            continue

        raw_skills = payload.get("skills")
        if isinstance(raw_skills, list):
            for skill in raw_skills:
                text = str(skill or "").strip()
                if text and text not in seen_skills:
                    seen_skills.add(text)
                    summary["skills"].append(text)

        update_max("seniority_years", payload.get("seniority_years"))
        update_max("connection_strength", payload.get("connection_strength"))
        update_max("match_score", payload.get("match_score"))

        validation = _as_dict(payload.get("validation"))
        update_max("match_score", validation.get("grounding_score"))

        debug_context = _as_dict(payload.get("debug_context"))
        update_max("connection_strength", debug_context.get("selected_similarity_max"))
        update_max("connection_strength", debug_context.get("raw_similarity_max"))
        update_max("match_score", debug_context.get("selected_similarity_max"))
        update_max("match_score", debug_context.get("raw_similarity_max"))

    if not summary["skills"] and all(summary[key] is None for key in ("seniority_years", "connection_strength", "match_score")):
        return None

    return summary


def _get_personnel_name(personnel_neo4j_id: str) -> str:
    try:
        driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
        try:
            with driver.session() as session:
                row = session.run(
                    """
                    MATCH (p:Personnel {id: $personnel_id})
                    RETURN coalesce(p.full_name, p.public_full_name, p.public_name, p.id) AS name
                    """,
                    personnel_id=personnel_neo4j_id,
                ).single()
        finally:
            driver.close()
    except Exception:
        return personnel_neo4j_id

    if not row:
        return personnel_neo4j_id
    return str(row.get("name") or personnel_neo4j_id)


def _get_personnel_public_summary(personnel_neo4j_id: str) -> str:
    if not personnel_neo4j_id:
        return ""

    try:
        driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
        try:
            with driver.session() as session:
                row = session.run(
                    """
                    MATCH (p:Personnel {id: $personnel_id})
                    RETURN coalesce(p.public_summary, p.public_professional_summary, '') AS summary
                    """,
                    personnel_id=personnel_neo4j_id,
                ).single()
        finally:
            driver.close()
    except Exception:
        return ""

    if not row:
        return ""
    return str(row.get("summary") or "").strip()


def _fallback_fit_explanation(
    personnel_name: str,
    job_title: str,
    summary: dict[str, Any],
) -> str:
    skills = list(summary.get("skills") or [])
    skills_text = ", ".join(str(skill).strip() for skill in skills[:4] if str(skill).strip())

    clauses: list[str] = []
    if skills_text:
        clauses.append(f"Ứng viên có nhóm kỹ năng trọng tâm gồm {skills_text}, phù hợp trực tiếp với yêu cầu của vị trí {job_title}.")

    seniority = _coerce_number(summary.get("seniority_years"))
    if seniority is not None:
        clauses.append(f"Mức kinh nghiệm khoảng {seniority:.0f} năm cho thấy ứng viên có nền tảng đủ để xử lý các nhiệm vụ cốt lõi của JD.")

    match_score = _coerce_number(summary.get("match_score"))
    if match_score is not None:
        clauses.append(f"Tín hiệu matching hiện tại đạt khoảng {round(match_score * 100)}%, phản ánh mức độ liên quan tốt giữa hồ sơ và JD.")

    connection_strength = _coerce_number(summary.get("connection_strength"))
    if connection_strength is not None:
        clauses.append(f"Mức độ kết nối dữ liệu khoảng {round(connection_strength * 100)}% giúp tăng độ tin cậy khi đánh giá mức phù hợp.")

    if not clauses:
        return f"{personnel_name} có các tín hiệu phù hợp cơ bản với vị trí {job_title}. Nên tiếp tục phỏng vấn để xác nhận chiều sâu kỹ năng và mức độ đáp ứng theo từng nhiệm vụ cụ thể."

    clauses.append("Khuyến nghị dùng buổi interview để kiểm chứng thêm các yêu cầu ưu tiên cao và mức độ sẵn sàng triển khai thực tế.")
    return " ".join(clauses)


def _generate_fit_explanation_with_llm(
    personnel_name: str,
    job_title: str,
    summary: dict[str, Any],
    profile_summary: str,
) -> str:
    if not settings.OPENAI_API_KEY:
        return _fallback_fit_explanation(personnel_name, job_title, summary)

    skills = list(summary.get("skills") or [])
    skill_text = ", ".join(str(skill).strip() for skill in skills[:8] if str(skill).strip())
    seniority = summary.get("seniority_years")
    connection_strength = summary.get("connection_strength")
    match_score = summary.get("match_score")

    prompt = (
        "Bạn là trợ lý tuyển dụng. Hãy viết 3-4 câu tiếng Việt giải thích ngắn gọn vì sao ứng viên phù hợp với JD. "
        "Giọng điệu chuyên nghiệp, có căn cứ, không phóng đại, không thêm dữ kiện ngoài input.\n\n"
        f"Ứng viên: {personnel_name}\n"
        f"JD: {job_title}\n"
        f"Skills nổi bật: {skill_text or 'Không rõ'}\n"
        f"Kinh nghiệm (năm): {seniority}\n"
        f"Connection strength: {connection_strength}\n"
        f"Match score: {match_score}\n"
        f"Tóm tắt hồ sơ: {profile_summary[:500] if profile_summary else 'Không có'}"
    )

    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "Chỉ trả về đoạn văn ngắn tiếng Việt, không markdown, không bullet.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.2,
        )
        content = str(response.choices[0].message.content or "").strip()
        if content:
            return content
    except Exception as exc:
        logger.warning("Generate fit explanation failed, fallback template is used: %s", exc)

    return _fallback_fit_explanation(personnel_name, job_title, summary)


def _upsert_session_row(
    org_neo4j_id: str,
    personnel_neo4j_id: str,
    session_id: str,
    job_title: str | None = None,
    reasoning_summary: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "session_id": session_id,
        "org_id": org_neo4j_id,
        "personnel_id": personnel_neo4j_id,
    }
    if job_title is not None:
        payload["job_title"] = job_title
    if reasoning_summary is not None:
        payload["reasoning_summary"] = reasoning_summary

    get_supabase().schema("vdme").table("chat_sessions").upsert(
        payload,
        on_conflict="session_id",
    ).execute()


def create_session(
    org_neo4j_id: str,
    personnel_neo4j_id: str,
    job_title: str | None = None,
    reasoning_summary: dict[str, Any] | None = None,
) -> str:
    # Session IDs are generated application-side so the frontend can connect WS immediately.
    session_id = str(uuid4())
    _upsert_session_row(
        org_neo4j_id=org_neo4j_id,
        personnel_neo4j_id=personnel_neo4j_id,
        session_id=session_id,
        job_title=job_title,
        reasoning_summary=reasoning_summary,
    )
    return session_id


def save_message(
    org_neo4j_id: str,
    personnel_neo4j_id: str,
    session_id: str,
    message: dict[str, Any],
    job_title: str | None = None,
) -> None:
    _upsert_session_row(
        org_neo4j_id=org_neo4j_id,
        personnel_neo4j_id=personnel_neo4j_id,
        session_id=session_id,
        job_title=job_title,
    )
    get_supabase().schema("vdme").table("chat_messages").insert(
        {
            "org_id": org_neo4j_id,
            "personnel_neo4j_id": personnel_neo4j_id,
            "org_neo4j_id": org_neo4j_id,
            "per_neo4j_id": personnel_neo4j_id,
            "role": message.get("role", "user"),
            "content": message.get("content", ""),
            "session_id": session_id,
            "job_title": job_title,
            "is_private_mode": message.get("is_private_mode", False),
            "reasoning": message.get("reasoning"),
        }
    ).execute()


def load_history_by_session(org_neo4j_id: str, session_id: str) -> list[dict[str, Any]]:
    rows = (
        get_supabase()
        .schema("vdme")
        .table("chat_messages")
        .select("id, role, content, reasoning, is_private_mode, created_at")
        .or_(f"org_id.eq.{org_neo4j_id},org_neo4j_id.eq.{org_neo4j_id}")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    )

    messages: list[dict[str, Any]] = []
    for raw_row in rows.data or []:
        row = _as_dict(raw_row)
        if not row:
            continue
        msg: dict[str, Any] = {
            "id": str(row.get("id") or ""),
            "role": row.get("role", "assistant"),
            "content": row.get("content", ""),
            "created_at": row.get("created_at"),
        }
        if row.get("reasoning") is not None:
            msg["reasoning"] = row.get("reasoning")
        if row.get("is_private_mode") is not None:
            msg["is_private_mode"] = row.get("is_private_mode")
        messages.append(msg)

    return messages


def list_sessions(org_neo4j_id: str) -> list[dict[str, Any]]:
    session_rows = (
        get_supabase()
        .schema("vdme")
        .table("chat_sessions")
        .select("session_id, org_id, personnel_id, job_title, reasoning_summary, created_at")
        .eq("org_id", org_neo4j_id)
        .order("created_at", desc=True)
        .execute()
    )

    message_rows = (
        get_supabase()
        .schema("vdme")
        .table("chat_messages")
        .select("session_id, content, reasoning, created_at")
        .or_(f"org_id.eq.{org_neo4j_id},org_neo4j_id.eq.{org_neo4j_id}")
        .order("created_at", desc=True)
        .execute()
    )

    message_stats: dict[str, dict[str, Any]] = {}
    reasoning_payloads_by_session: dict[str, list[Any]] = {}
    for raw_row in message_rows.data or []:
        row = _as_dict(raw_row)
        session_id = str(row.get("session_id") or "").strip()
        if not session_id:
            continue

        stats = message_stats.setdefault(
            session_id,
            {
                "last_message": None,
                "message_count": 0,
            },
        )
        stats["message_count"] += 1
        if stats["last_message"] is None:
            content = str(row.get("content") or "").strip()
            stats["last_message"] = content[:60] if content else None

        reasoning_payload = row.get("reasoning")
        if reasoning_payload is not None:
            reasoning_payloads_by_session.setdefault(session_id, []).append(reasoning_payload)

    sessions: list[dict[str, Any]] = []
    seen_session_ids: set[str] = set()

    for raw_row in session_rows.data or []:
        row = _as_dict(raw_row)
        session_id = str(row.get("session_id") or "").strip()
        if not session_id:
          continue

        seen_session_ids.add(session_id)
        personnel_id = str(row.get("personnel_id") or "").strip()
        reasoning_summary = build_reasoning_summary(
            row.get("reasoning_summary"),
            reasoning_payloads_by_session.get(session_id, []),
        )
        sessions.append(
            {
                "session_id": session_id,
                "personnel_id": personnel_id,
                "personnel_name": _get_personnel_name(personnel_id) if personnel_id else personnel_id,
                "job_title": row.get("job_title"),
                "reasoning_summary": reasoning_summary,
                "created_at": row.get("created_at"),
                "last_message": message_stats.get(session_id, {}).get("last_message"),
                "message_count": message_stats.get(session_id, {}).get("message_count", 0),
            }
        )

    # Backward compatibility for legacy sessions that only exist in chat_messages.
    legacy_rows = (
        get_supabase()
        .schema("vdme")
        .table("chat_messages")
        .select("session_id, personnel_neo4j_id, per_neo4j_id, job_title, reasoning, created_at")
        .or_(f"org_id.eq.{org_neo4j_id},org_neo4j_id.eq.{org_neo4j_id}")
        .order("created_at", desc=True)
        .execute()
    )

    for raw_row in legacy_rows.data or []:
        row = _as_dict(raw_row)
        session_id = str(row.get("session_id") or "").strip()
        if not session_id or session_id in seen_session_ids:
            continue

        personnel_id = str(row.get("personnel_neo4j_id") or row.get("per_neo4j_id") or "").strip()
        reasoning_summary = build_reasoning_summary(
            row.get("reasoning"),
            reasoning_payloads_by_session.get(session_id, []),
        )
        sessions.append(
            {
                "session_id": session_id,
                "personnel_id": personnel_id,
                "personnel_name": _get_personnel_name(personnel_id) if personnel_id else personnel_id,
                "job_title": row.get("job_title"),
                "reasoning_summary": reasoning_summary,
                "created_at": row.get("created_at"),
                "last_message": message_stats.get(session_id, {}).get("last_message"),
                "message_count": message_stats.get(session_id, {}).get("message_count", 0),
            }
        )

    sessions.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return sessions


def get_session_fit_summary(org_neo4j_id: str, session_id: str) -> dict[str, Any]:
    cleaned_session_id = str(session_id or "").strip()
    if not cleaned_session_id:
        return {"session_id": "", "fit_summary": None, "reasoning_summary": None}

    session_rows = (
        get_supabase()
        .schema("vdme")
        .table("chat_sessions")
        .select("session_id, org_id, personnel_id, job_title, reasoning_summary")
        .eq("org_id", org_neo4j_id)
        .eq("session_id", cleaned_session_id)
        .limit(1)
        .execute()
    )

    session_row = _as_dict((session_rows.data or [None])[0])
    personnel_id = str(session_row.get("personnel_id") or "").strip()
    job_title = str(session_row.get("job_title") or "").strip() or "Vị trí chưa xác định"
    existing_summary = session_row.get("reasoning_summary")

    message_rows = (
        get_supabase()
        .schema("vdme")
        .table("chat_messages")
        .select("personnel_neo4j_id, per_neo4j_id, job_title, reasoning")
        .or_(f"org_id.eq.{org_neo4j_id},org_neo4j_id.eq.{org_neo4j_id}")
        .eq("session_id", cleaned_session_id)
        .order("created_at", desc=True)
        .execute()
    )

    reasoning_payloads: list[Any] = []
    for raw_row in message_rows.data or []:
        row = _as_dict(raw_row)
        if not personnel_id:
            personnel_id = str(row.get("personnel_neo4j_id") or row.get("per_neo4j_id") or "").strip()
        if (not job_title or job_title == "Vị trí chưa xác định") and row.get("job_title"):
            job_title = str(row.get("job_title") or "").strip() or job_title
        if row.get("reasoning") is not None:
            reasoning_payloads.append(row.get("reasoning"))

    reasoning_summary = build_reasoning_summary(existing_summary, reasoning_payloads)
    if not reasoning_summary:
        return {
            "session_id": cleaned_session_id,
            "fit_summary": None,
            "reasoning_summary": None,
        }

    cached_explanation = ""
    if isinstance(existing_summary, dict):
        cached_explanation = str(existing_summary.get("fit_explanation") or "").strip()

    if cached_explanation:
        return {
            "session_id": cleaned_session_id,
            "fit_summary": cached_explanation,
            "reasoning_summary": reasoning_summary,
        }

    personnel_name = _get_personnel_name(personnel_id) if personnel_id else "Ứng viên"
    profile_summary = _get_personnel_public_summary(personnel_id)
    fit_summary = _generate_fit_explanation_with_llm(
        personnel_name=personnel_name,
        job_title=job_title,
        summary=reasoning_summary,
        profile_summary=profile_summary,
    )

    try:
        payload_summary = dict(reasoning_summary)
        payload_summary["fit_explanation"] = fit_summary
        _upsert_session_row(
            org_neo4j_id=org_neo4j_id,
            personnel_neo4j_id=personnel_id,
            session_id=cleaned_session_id,
            job_title=job_title,
            reasoning_summary=payload_summary,
        )
    except Exception as exc:
        logger.warning("Could not cache fit explanation for session %s: %s", cleaned_session_id, exc)

    return {
        "session_id": cleaned_session_id,
        "fit_summary": fit_summary,
        "reasoning_summary": reasoning_summary,
    }
