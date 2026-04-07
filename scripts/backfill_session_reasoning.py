from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.chat_service import build_reasoning_summary
from pipeline.config import get_logger
from pipeline.config import settings
from pipeline.hybrid_query_engine import MasterAgentEngine
from neo4j import GraphDatabase
from pipeline.supabase_client import get_supabase

logger = get_logger(__name__)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _is_reasoning_summary_missing(value: Any) -> bool:
    summary = _as_dict(value)
    if not summary:
        return True

    skills = summary.get("skills")
    has_skills = isinstance(skills, list) and any(str(skill or "").strip() for skill in skills)
    has_seniority = summary.get("seniority_years") is not None
    has_connection = summary.get("connection_strength") is not None
    has_match = summary.get("match_score") is not None
    return not (has_skills or has_seniority or has_connection or has_match)


def _session_key(row: dict[str, Any]) -> str:
    return str(row.get("session_id") or "").strip()


def _normalize_string_list(value: Any) -> list[str]:
    parsed_value = value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                parsed_value = parsed
        except Exception:
            cleaned = text.strip("[]")
            if cleaned:
                parsed_value = [part.strip().strip("\"'") for part in cleaned.split(",")]

    if not isinstance(parsed_value, list):
        return []
    seen: set[str] = set()
    normalized: list[str] = []
    for item in parsed_value:
        text = str(item or "").strip()
        if len(text) <= 1:
            continue
        if not re.search(r"[A-Za-zÀ-ỹ0-9]", text):
            continue
        if text and text not in seen:
            seen.add(text)
            normalized.append(text)
    return normalized


def _extract_years_from_text(*texts: Any) -> float | None:
    year_pattern = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:\+\s*)?(?:năm|nam|years?|yrs?)", re.IGNORECASE)
    candidates: list[float] = []
    for text in texts:
        text_value = str(text or "")
        for match in year_pattern.finditer(text_value):
            try:
                candidates.append(float(match.group(1).replace(",", ".")))
            except ValueError:
                continue
    if not candidates:
        return None
    return max(candidates)


def _get_connection_strength(org_id: Any, personnel_id: Any) -> float | None:
    org_value = str(org_id or "").strip()
    personnel_value = str(personnel_id or "").strip()
    if not org_value or not personnel_value:
        return None

    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )
    try:
        with driver.session() as session:
            row = session.run(
                """
                MATCH (o:Organization {id: $org_id})-[r:CONNECTED_TO]->(p:Personnel {id: $personnel_id})
                RETURN r.status AS status
                """,
                org_id=org_value,
                personnel_id=personnel_value,
            ).single()
    finally:
        driver.close()

    if not row:
        return None

    status = str(row.get("status") or "").strip().lower()
    if status == "accepted":
        return 1.0
    if status == "pending":
        return 0.5
    if status == "cancelled":
        return 0.0
    return None


def _build_candidate_cache(job_titles: list[str]) -> dict[str, dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    with MasterAgentEngine() as engine:
        for job_title in job_titles:
            query = str(job_title or "").strip()
            if not query:
                continue
            if query in cache:
                continue

            try:
                results = engine.search_candidates(query, top_k=20)
            except Exception as exc:
                logger.warning("Search backfill failed for job_title=%s: %s", query, exc)
                cache[query] = {}
                continue

            cache[query] = {
                str(getattr(candidate, "id", "") or ""): candidate
                for candidate in results
                if str(getattr(candidate, "id", "") or "").strip()
            }

    return cache


def _merge_with_search_metrics(
    existing_summary: Any | None,
    reasoning_payloads: list[Any],
    job_title: Any,
    personnel_id: Any,
    org_id: Any,
    candidate_cache: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    summary = build_reasoning_summary(existing_summary, reasoning_payloads)
    if summary is None:
        summary = {
            "skills": [],
            "seniority_years": None,
            "connection_strength": None,
            "match_score": None,
        }

    job_title_value = str(job_title or "").strip()
    candidate_map = candidate_cache.get(job_title_value, {})
    candidate = candidate_map.get(str(personnel_id or "").strip())

    seen_skills = set(str(skill or "").strip() for skill in summary.get("skills", []) if str(skill or "").strip())
    if candidate is not None:
        candidate_skills = _normalize_string_list(getattr(candidate, "skills", []))
        for skill in candidate_skills:
            if skill not in seen_skills:
                seen_skills.add(skill)
                summary.setdefault("skills", []).append(skill)

        candidate_score = getattr(candidate, "score", None)
        if isinstance(candidate_score, (int, float)):
            current_score = summary.get("match_score")
            if current_score is None or float(candidate_score) > float(current_score):
                summary["match_score"] = float(candidate_score)

        if summary.get("seniority_years") is None:
            summary["seniority_years"] = _extract_years_from_text(
                getattr(candidate, "summary", None),
                job_title_value,
            )

    connection_strength = _get_connection_strength(org_id, personnel_id)
    if connection_strength is not None:
        current_strength = summary.get("connection_strength")
        if current_strength is None or connection_strength > float(current_strength):
            summary["connection_strength"] = connection_strength

    if summary.get("seniority_years") is None:
        summary["seniority_years"] = _extract_years_from_text(job_title_value)

    if not summary.get("skills") and all(summary.get(key) is None for key in ("seniority_years", "connection_strength", "match_score")):
        return None

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill interview session reasoning summaries")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview rows without writing updates to Supabase.",
    )
    args = parser.parse_args()

    sb = get_supabase()

    session_rows = (
        sb.schema("vdme")
        .table("chat_sessions")
        .select("session_id, org_id, personnel_id, job_title, reasoning_summary, created_at")
        .execute()
    ).data or []

    message_rows = (
        sb.schema("vdme")
        .table("chat_messages")
        .select("session_id, org_id, org_neo4j_id, personnel_neo4j_id, per_neo4j_id, job_title, role, reasoning, created_at")
        .execute()
    ).data or []

    sessions_by_id: dict[str, dict[str, Any]] = {}
    reasoning_payloads_by_session: dict[str, list[Any]] = {}

    for raw_row in session_rows:
        row = _as_dict(raw_row)
        session_id = _session_key(row)
        if not session_id:
            continue
        sessions_by_id[session_id] = row

    for raw_row in message_rows:
        row = _as_dict(raw_row)
        session_id = _session_key(row)
        if not session_id:
            continue

        reasoning_payload = row.get("reasoning")
        if reasoning_payload is not None:
            reasoning_payloads_by_session.setdefault(session_id, []).append(reasoning_payload)

        if session_id not in sessions_by_id:
            sessions_by_id[session_id] = {
                "session_id": session_id,
                "org_id": row.get("org_id") or row.get("org_neo4j_id"),
                "personnel_id": row.get("personnel_neo4j_id") or row.get("per_neo4j_id"),
                "job_title": row.get("job_title"),
                "reasoning_summary": None,
                "created_at": row.get("created_at"),
            }
        else:
            session_row = sessions_by_id[session_id]
            if not session_row.get("org_id"):
                session_row["org_id"] = row.get("org_id") or row.get("org_neo4j_id")
            if not session_row.get("personnel_id"):
                session_row["personnel_id"] = row.get("personnel_neo4j_id") or row.get("per_neo4j_id")
            if not session_row.get("job_title"):
                session_row["job_title"] = row.get("job_title")
            if not session_row.get("created_at"):
                session_row["created_at"] = row.get("created_at")

    scanned = 0
    updated = 0
    skipped = 0
    unchanged = 0

    candidate_cache = _build_candidate_cache(
        [str(row.get("job_title") or "").strip() for row in sessions_by_id.values() if str(row.get("job_title") or "").strip()]
    )

    for session_id, row in sessions_by_id.items():
        scanned += 1
        existing_summary = row.get("reasoning_summary")
        derived_summary = _merge_with_search_metrics(
            existing_summary,
            reasoning_payloads_by_session.get(session_id, []),
            row.get("job_title"),
            row.get("personnel_id"),
            row.get("org_id"),
            candidate_cache,
        )

        if derived_summary is None:
            skipped += 1
            continue

        if derived_summary == existing_summary:
            unchanged += 1
            continue

        payload = {
            "session_id": session_id,
            "org_id": row.get("org_id"),
            "personnel_id": row.get("personnel_id"),
            "job_title": row.get("job_title"),
            "reasoning_summary": derived_summary,
        }

        if args.dry_run:
            logger.info("[dry-run] would backfill session=%s payload=%s", session_id, payload)
            updated += 1
            continue

        sb.schema("vdme").table("chat_sessions").upsert(
            payload,
            on_conflict="session_id",
        ).execute()
        updated += 1

    print("=== Reasoning Summary Backfill ===")
    print(f"Dry run: {args.dry_run}")
    print(f"Scanned sessions: {scanned}")
    print(f"Updated sessions: {updated}")
    print(f"Unchanged sessions: {unchanged}")
    print(f"Skipped sessions: {skipped}")


if __name__ == "__main__":
    main()