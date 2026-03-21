from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from neo4j import GraphDatabase

from api.deps import get_current_user
from pipeline.config import settings

router = APIRouter()


@router.get("")
async def get_graph(
    show_all: bool = Query(False),
    user: dict = Depends(get_current_user),
) -> dict[str, list[dict[str, object]]]:
    # user dependency is required to protect graph endpoint for authenticated users.
    _ = user

    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )

    try:
        with driver.session() as session:
            if show_all:
                records = session.run(
                    """
                    MATCH (p:Personnel)
                    OPTIONAL MATCH (o:Organization)-[r:CONNECTED_TO]->(p)
                    RETURN p.id AS personnel_id,
                           coalesce(p.public_name, p.id) AS personnel_name,
                           o.id AS org_id,
                           r.status AS rel_status
                    LIMIT 200
                    """
                ).data()
            else:
                records = session.run(
                    """
                    MATCH (o:Organization)-[r:CONNECTED_TO]->(p:Personnel)
                    RETURN o.id AS org_id,
                           p.id AS personnel_id,
                           coalesce(p.public_name, p.id) AS personnel_name,
                           r.status AS rel_status
                    LIMIT 200
                    """
                ).data()
    finally:
        driver.close()

    nodes: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    seen_nodes: set[str] = set()
    seen_edges: set[tuple[str, str]] = set()

    for row in records:
        oid = row.get("org_id")
        pid = row.get("personnel_id")
        pname = row.get("personnel_name") or pid
        status = row.get("rel_status") or "pending"

        if isinstance(oid, str) and oid not in seen_nodes:
            nodes.append(
                {
                    "id": oid,
                    "type": "org",
                    "data": {"label": oid, "type": "organization"},
                    "position": {"x": 0, "y": 0},
                }
            )
            seen_nodes.add(oid)

        if isinstance(pid, str) and pid not in seen_nodes:
            nodes.append(
                {
                    "id": pid,
                    "type": "personnel",
                    "data": {"label": pname, "type": "personnel"},
                    "position": {"x": 0, "y": 0},
                }
            )
            seen_nodes.add(pid)

        if isinstance(oid, str) and isinstance(pid, str) and (oid, pid) not in seen_edges:
            edges.append(
                {
                    "id": f"{oid}-{pid}",
                    "source": oid,
                    "target": pid,
                    "label": status,
                    "style": {"stroke": "#22C55E" if status == "accepted" else "#9CA3AF"},
                }
            )
            seen_edges.add((oid, pid))

    return {"nodes": nodes, "edges": edges}
