from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from api.deps import get_current_user
from pipeline.config import settings
from pipeline.neo4j_client import get_neo4j_driver

router = APIRouter()


def _parse_json_field(value: object) -> list[str]:
    """Parse JSON string field từ Neo4j → list[str]."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        except (json.JSONDecodeError, ValueError):
            pass
    return []


def _normalize_node_type(labels: list[str]) -> str:
    preferred = {"personnel", "org", "organization", "skill"}
    for label in labels:
        lowered = label.lower()
        if lowered in preferred:
            return "org" if lowered == "organization" else lowered
    return labels[0].lower() if labels else "unknown"


def _build_node_payload(node: Any) -> dict[str, object] | None:
    if node is None:
        return None

    node_id = node.get("id") or str(node.element_id)
    labels = list(node.labels)
    node_type = _normalize_node_type(labels)
    personnel_full_name = (
        node.get("public_full_name")
        or node.get("full_name")
        or node.get("public_name")
    )
    label = (
        personnel_full_name
        or node.get("public_name")
        or node.get("name")
        or node.get("title")
        or node.get("label")
        or node_id
    )

    node_data: dict[str, object] = {
        "label": label,
        "type": node_type,
    }

    if node_type == "personnel":
        node_data["public_full_name"] = personnel_full_name or node_id
        node_data["skills"] = _parse_json_field(node.get("public_skills"))
        node_data["summary"] = node.get("public_professional_summary", "")
        node_data["availability"] = bool(node.get("public_is_available", False))

    return {
        "id": node_id,
        "type": node_type,
        "data": node_data,
    }


@router.get("")
async def get_graph(
    show_all: bool = Query(False),
    focus_id: str | None = Query(None),
    focus_node_id: str | None = Query(None),
    user: dict = Depends(get_current_user),
) -> dict[str, list[dict[str, object]]]:
    user_id = user.get("neo4j_id") or user.get("sub") or user.get("id")
    target_id = focus_id or focus_node_id or user_id

    driver = get_neo4j_driver(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
    )

    try:
        session_kwargs = {"database": settings.neo4j_database} if settings.neo4j_database else {}
        with driver.session(**session_kwargs) as session:
            params: dict[str, Any]
            if show_all:
                query = "MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 200"
                params = {}
            else:
                query = """
                MATCH (focus)
                WHERE focus.id = $focus_id
                   OR focus.personnel_id = $focus_id
                   OR focus.org_id = $focus_id
                OPTIONAL MATCH p = (focus)-[*1..1]-(other)
                RETURN focus, p
                """
                params = {"focus_id": target_id}

            records = session.run(query, **params)

            nodes = []
            edges = []
            seen_nodes = set()
            seen_edges = set()

            def add_node(node: object):
                payload = _build_node_payload(node)
                if payload is None:
                    return

                node_id = str(payload["id"])
                if node_id in seen_nodes:
                    return

                nodes.append({
                    **payload,
                    "position": {"x": 0, "y": 0},
                })
                seen_nodes.add(node_id)

            def add_path(path: Any):
                if path is None:
                    return

                for path_node in path.nodes:
                    add_node(path_node)

                for rel in path.relationships:
                    source_id = rel.start_node.get("id") or str(rel.start_node.element_id)
                    target_id = rel.end_node.get("id") or str(rel.end_node.element_id)
                    rel_type = rel.type
                    edge_id = f"{source_id}-{rel_type}-{target_id}"

                    if edge_id in seen_edges:
                        continue

                    rel_status = rel.get("status") or rel_type
                    edges.append({
                        "id": edge_id,
                        "source": source_id,
                        "target": target_id,
                        "label": rel_status,
                        "style": {"stroke": "#22C55E" if rel_status == "accepted" else "#9CA3AF"},
                    })
                    seen_edges.add(edge_id)

            if show_all:
                for record in records:
                    n = record.get("n")
                    r = record.get("r")
                    m = record.get("m")

                    add_node(n)
                    add_node(m)

                    if r is None:
                        continue

                    source_id = r.start_node.get("id") or str(r.start_node.element_id)
                    target_id = r.end_node.get("id") or str(r.end_node.element_id)
                    rel_type = r.type
                    edge_id = f"{source_id}-{rel_type}-{target_id}"

                    if edge_id in seen_edges:
                        continue

                    rel_status = r.get("status") or rel_type
                    edges.append({
                        "id": edge_id,
                        "source": source_id,
                        "target": target_id,
                        "label": rel_status,
                        "style": {"stroke": "#22C55E" if rel_status == "accepted" else "#9CA3AF"},
                    })
                    seen_edges.add(edge_id)
            else:
                for record in records:
                    add_node(record.get("focus"))
                    add_path(record.get("p"))

                related_query = """
                MATCH (focus)
                WHERE (focus.id = $focus_id
                   OR focus.personnel_id = $focus_id
                   OR focus.org_id = $focus_id)
                  AND any(label IN labels(focus) WHERE toLower(label) IN ["org", "organization"])
                MATCH (focus)-[*1..1]-(per)
                WHERE any(label IN labels(per) WHERE toLower(label) = "personnel")
                OPTIONAL MATCH p = (per)-[*1..1]-(related)
                WHERE related <> focus
                RETURN p
                """
                related_records = session.run(related_query, **params)
                for record in related_records:
                    add_path(record.get("p"))

    finally:
        driver.close()

    return {"nodes": nodes, "edges": edges}