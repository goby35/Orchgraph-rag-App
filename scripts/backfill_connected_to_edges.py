from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.config import get_logger, settings
from pipeline.neo4j_client import get_neo4j_driver
from pipeline.supabase_client import get_supabase

logger = get_logger(__name__)


@dataclass(frozen=True)
class EdgeEvent:
    org_id: str
    personnel_id: str
    status: str
    event_time: str | None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_status(value: str) -> str | None:
    status = str(value or "").strip().lower()
    if status in {"pending", "accepted"}:
        return status
    return None


def _pick_higher_status(current: str | None, incoming: str) -> str:
    if current == "accepted":
        return current
    if incoming == "accepted":
        return incoming
    if current == "pending":
        return current
    return incoming


def _collect_events(limit: int = 0) -> list[EdgeEvent]:
    sb = get_supabase()
    events: list[EdgeEvent] = []

    # Source 1: Interview notifications preserve pending/accepted transitions.
    notification_rows = (
        sb.schema("vdme")
        .table("notifications")
        .select("type, sender_neo4j_id, recipient_neo4j_id, created_at")
        .in_("type", ["interview_request", "interview_accepted"])
        .order("created_at")
        .execute()
    ).data or []

    for raw in notification_rows:
        row = _as_dict(raw)
        n_type = str(row.get("type") or "").strip().lower()
        sender = str(row.get("sender_neo4j_id") or "").strip()
        recipient = str(row.get("recipient_neo4j_id") or "").strip()
        created_at = str(row.get("created_at") or "").strip() or None

        if n_type == "interview_request":
            org_id, personnel_id, status = sender, recipient, "pending"
        elif n_type == "interview_accepted":
            org_id, personnel_id, status = recipient, sender, "accepted"
        else:
            continue

        if org_id and personnel_id:
            events.append(
                EdgeEvent(
                    org_id=org_id,
                    personnel_id=personnel_id,
                    status=status,
                    event_time=created_at,
                )
            )

    # Source 2: Existing chat sessions imply accepted relationship historically.
    session_rows = (
        sb.schema("vdme")
        .table("chat_sessions")
        .select("org_id, personnel_id, created_at")
        .order("created_at")
        .execute()
    ).data or []

    for raw in session_rows:
        row = _as_dict(raw)
        org_id = str(row.get("org_id") or "").strip()
        personnel_id = str(row.get("personnel_id") or "").strip()
        created_at = str(row.get("created_at") or "").strip() or None
        if org_id and personnel_id:
            events.append(
                EdgeEvent(
                    org_id=org_id,
                    personnel_id=personnel_id,
                    status="accepted",
                    event_time=created_at,
                )
            )

    if limit > 0:
        return events[:limit]
    return events


def _collapse_events(events: list[EdgeEvent]) -> list[EdgeEvent]:
    by_pair: dict[tuple[str, str], EdgeEvent] = {}
    for event in events:
        key = (event.org_id, event.personnel_id)
        existing = by_pair.get(key)
        if existing is None:
            by_pair[key] = event
            continue

        next_status = _pick_higher_status(existing.status, event.status)
        event_time = event.event_time or existing.event_time
        by_pair[key] = EdgeEvent(
            org_id=event.org_id,
            personnel_id=event.personnel_id,
            status=next_status,
            event_time=event_time,
        )

    return list(by_pair.values())


def _upsert_edges(edges: list[EdgeEvent], dry_run: bool) -> tuple[int, int]:
    driver = get_neo4j_driver(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
    )

    merged_count = 0
    skipped_count = 0

    cypher = """
    MATCH (o:Organization)
    WHERE o.id = $org_id OR o.org_id = $org_id OR o.neo4j_id = $org_id
    MATCH (p:Personnel)
    WHERE p.id = $personnel_id OR p.personnel_id = $personnel_id
    MERGE (o)-[r:CONNECTED_TO]->(p)
    SET r.status = $status,
        r.updated_at = coalesce($event_time, $now_iso),
        r.org_id = coalesce(o.id, $org_id),
        r.personnel_id = coalesce(p.id, $personnel_id),
        r.requested_at = CASE
            WHEN $status = 'pending' THEN coalesce(r.requested_at, $event_time, $now_iso)
            ELSE r.requested_at
        END,
        r.connected_at = CASE
            WHEN $status = 'accepted' THEN coalesce(r.connected_at, $event_time, $now_iso)
            ELSE r.connected_at
        END
    RETURN coalesce(o.id, o.org_id, o.neo4j_id) AS org_id, coalesce(p.id, p.personnel_id) AS personnel_id
    """

    session_kwargs = {"database": settings.neo4j_database} if settings.neo4j_database else {}
    try:
        with driver.session(**session_kwargs) as session:
            for edge in edges:
                now_iso = datetime.now(timezone.utc).isoformat()
                if dry_run:
                    logger.info("[DRY-RUN] %s -> %s status=%s", edge.org_id, edge.personnel_id, edge.status)
                    merged_count += 1
                    continue

                row = session.run(
                    cypher,
                    org_id=edge.org_id,
                    personnel_id=edge.personnel_id,
                    status=edge.status,
                    event_time=edge.event_time,
                    now_iso=now_iso,
                ).single()
                if row:
                    merged_count += 1
                else:
                    skipped_count += 1
    finally:
        driver.close()

    return merged_count, skipped_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill CONNECTED_TO edges from existing interview status data")
    parser.add_argument("--dry-run", action="store_true", help="Preview edges without writing to Neo4j")
    parser.add_argument("--limit", type=int, default=0, help="Process only first N source events")
    args = parser.parse_args()

    events = _collect_events(limit=max(0, args.limit))
    if not events:
        logger.info("No source events found for backfill.")
        return

    collapsed = _collapse_events(events)
    pending_count = sum(1 for edge in collapsed if edge.status == "pending")
    accepted_count = sum(1 for edge in collapsed if edge.status == "accepted")

    logger.info("Collected %d events, collapsed to %d edges", len(events), len(collapsed))
    logger.info("Edge status summary: pending=%d accepted=%d", pending_count, accepted_count)

    merged, skipped = _upsert_edges(collapsed, dry_run=args.dry_run)
    logger.info("Backfill done. merged=%d skipped=%d dry_run=%s", merged, skipped, args.dry_run)


if __name__ == "__main__":
    main()
