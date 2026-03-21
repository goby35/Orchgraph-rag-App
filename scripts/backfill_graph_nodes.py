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

from pipeline.neo4j_ingestion import neo4j_service
from pipeline.schemas import RecruitmentNode, _normalize_entity


def _normalize_degree(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "OTHER"
    if any(token in text for token in ["bachelor", "cử nhân", "ky su", "kỹ sư", "engineer"]):
        return "BACHELOR"
    if any(token in text for token in ["master", "thạc sĩ", "thac si", "msc", "mba"]):
        return "MASTER"
    if any(token in text for token in ["phd", "tiến sĩ", "tien si", "doctor"]):
        return "PHD"
    return "OTHER"


def _normalize_year(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if len(text) == 4 and text.isdigit():
        return int(text)
    for token in text.replace("/", " ").replace("-", " ").split():
        if len(token) == 4 and token.isdigit():
            return int(token)
    return None


def _parse_json_like(value: Any, default: Any) -> Any:
    if isinstance(value, type(default)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if (text.startswith("[") and text.endswith("]")) or (
            text.startswith("{") and text.endswith("}")
        ):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, type(default)):
                    return parsed
            except Exception:
                return default
    return default


def _clean_skill_list(raw_skills: list[Any]) -> list[str]:
    """Clean and normalize legacy skill strings from flat Neo4j props."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw_skills:
        if not isinstance(item, str):
            continue

        text = re.sub(r"\s*\(.*?\)", "", item).strip().lower()
        if not text:
            continue

        parts = re.split(r"[/,]", text)
        for part in parts:
            candidate = part.strip()
            if not candidate or len(candidate) <= 1:
                continue
            normalized = _normalize_entity(candidate)
            if normalized and normalized not in seen:
                seen.add(normalized)
                cleaned.append(normalized)

    return cleaned


def _to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _reconstruct_node_from_flat(props: dict[str, Any]) -> RecruitmentNode:
    personnel_id = str(props.get("id") or "").strip()

    full_name = str(props.get("public_full_name") or props.get("public_name") or "").strip()
    summary = str(
        props.get("public_professional_summary") or props.get("public_summary") or ""
    ).strip()

    is_available = _to_bool(props.get("public_is_available"))
    availability = str(props.get("public_availability") or "").strip()

    skills = _parse_json_like(props.get("public_skills_flat"), [])
    if not skills:
        skills = _parse_json_like(props.get("public_skills"), [])
    skills = _clean_skill_list(skills if isinstance(skills, list) else [])

    raw_education = _parse_json_like(props.get("public_education"), [])
    education: list[dict[str, Any]] = []
    for item in raw_education:
        if not isinstance(item, dict):
            continue
        education.append(
            {
                "degree": _normalize_degree(item.get("degree")),
                "major": str(item.get("major") or "").strip(),
                "school": str(item.get("school") or "").strip(),
                "year": _normalize_year(item.get("year")),
            }
        )

    raw_experience = _parse_json_like(props.get("public_experience"), [])
    experience: list[dict[str, Any]] = []
    for item in raw_experience:
        if not isinstance(item, dict):
            continue
        tech_stack = _parse_json_like(item.get("tech_stack"), [])
        tech_stack = _clean_skill_list(tech_stack if isinstance(tech_stack, list) else [])
        experience.append(
            {
                "organization_name": str(item.get("organization_name") or "").strip() or None,
                "project_name": str(item.get("project_name") or "").strip(),
                "role": str(item.get("role") or "").strip(),
                "tech_stack": tech_stack,
            }
        )

    payload: dict[str, Any] = {
        "personnel_id": personnel_id,
        "public_data": {
            "full_name": full_name,
            "professional_summary": summary,
            "skills": skills,
            "certificates": _parse_json_like(props.get("public_certificates"), []),
            "cultural_tags": _parse_json_like(props.get("public_cultural_tags"), []),
            "education": education,
            "experience": experience,
        },
        "private_data": {},
    }

    # Prefer explicit bool field, otherwise allow legacy availability-to-bool mapping in schema validator.
    if is_available is not None:
        payload["public_data"]["is_available"] = is_available
    elif availability:
        payload["public_data"]["availability"] = availability

    return RecruitmentNode.model_validate(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill graph nodes for Personnel")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview only. Do not write any graph nodes.",
    )
    args = parser.parse_args()

    if not neo4j_service.verify_connection():
        raise SystemExit(1)

    with neo4j_service._driver.session() as session:  # noqa: SLF001
        rows = session.run(
            """
            MATCH (p:Personnel)
            WHERE p._has_graph_nodes IS NULL
            RETURN properties(p) AS props
            ORDER BY p.id
            """
        ).data()

    scanned = len(rows)
    eligible = 0
    processed = 0
    failed = 0

    for row in rows:
        props = row.get("props") or {}
        if not isinstance(props, dict):
            continue

        try:
            node = _reconstruct_node_from_flat(props)
            eligible += 1
            if args.dry_run:
                continue

            ok = neo4j_service.ingest_personnel_graph(node)
            if ok:
                processed += 1
            else:
                failed += 1
        except Exception as exc:
            failed += 1
            node_id = props.get("id", "<unknown>")
            print(f"[FAIL] {node_id}: {exc}")

    print("=== Backfill Summary ===")
    print(f"Dry run: {args.dry_run}")
    print(f"Scanned Personnel: {scanned}")
    print(f"Eligible for graph backfill: {eligible}")
    print(f"Processed: {processed}")
    print(f"Failed: {failed}")


if __name__ == "__main__":
    main()
