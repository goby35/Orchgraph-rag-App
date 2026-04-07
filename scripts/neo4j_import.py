from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase
from tqdm import tqdm

DEFAULT_USER = os.getenv("NEO4J_USER", "neo4j")
DEFAULT_PASSWORD = os.getenv("NEO4J_PASSWORD", "password123")
AURA_URI = os.getenv("NEO4J_AURA_URI", "")
EXPORT_FILE = Path(__file__).resolve().parents[1] / "neo4j_export.json"
BATCH_SIZE = 100


def chunked(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def quote_label(label: str) -> str:
    return "`" + label.replace("`", "``") + "`"


def quote_rel_type(rel_type: str) -> str:
    return "`" + rel_type.replace("`", "``") + "`"


def load_export(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    nodes = payload.get("nodes", [])
    relationships = payload.get("relationships", [])
    if not isinstance(nodes, list) or not isinstance(relationships, list):
        raise ValueError("Invalid export format: expected keys 'nodes' and 'relationships' as lists")
    return nodes, relationships


def import_nodes(session, nodes: list[dict[str, Any]]) -> None:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        labels = tuple(node.get("labels", []))
        groups[labels].append(node)

    total_batches = sum(len(chunked(group_nodes, BATCH_SIZE)) for group_nodes in groups.values())
    with tqdm(total=total_batches, desc="Importing nodes", unit="batch") as pbar:
        for labels, grouped_nodes in groups.items():
            label_fragment = "".join(f":{quote_label(label)}" for label in labels)
            query = (
                f"UNWIND $rows AS row "
                f"CREATE (n{label_fragment}) "
                f"SET n += row.properties, n._import_id = row.id"
            )

            for batch in chunked(grouped_nodes, BATCH_SIZE):
                rows = [{"id": n["id"], "properties": n.get("properties", {})} for n in batch]
                session.run(query, rows=rows).consume()
                pbar.update(1)


def import_relationships(session, relationships: list[dict[str, Any]]) -> None:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rel in relationships:
        rel_type = rel.get("type")
        if not rel_type:
            continue
        groups[rel_type].append(rel)

    total_batches = sum(len(chunked(group_rels, BATCH_SIZE)) for group_rels in groups.values())
    with tqdm(total=total_batches, desc="Importing relationships", unit="batch") as pbar:
        for rel_type, grouped_rels in groups.items():
            rel_fragment = quote_rel_type(rel_type)
            query = (
                f"UNWIND $rows AS row "
                f"MATCH (s {{_import_id: row.start_node_id}}) "
                f"MATCH (e {{_import_id: row.end_node_id}}) "
                f"CREATE (s)-[r:{rel_fragment}]->(e) "
                f"SET r += row.properties"
            )

            for batch in chunked(grouped_rels, BATCH_SIZE):
                rows = [
                    {
                        "start_node_id": r["start_node_id"],
                        "end_node_id": r["end_node_id"],
                        "properties": r.get("properties", {}),
                    }
                    for r in batch
                ]
                session.run(query, rows=rows).consume()
                pbar.update(1)


def verify_import(session, expected_nodes: int, expected_relationships: int) -> None:
    actual_nodes = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
    actual_relationships = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]

    print("Verification summary:")
    print(f"- Nodes: expected={expected_nodes}, actual={actual_nodes}")
    print(f"- Relationships: expected={expected_relationships}, actual={actual_relationships}")

    if actual_nodes != expected_nodes or actual_relationships != expected_relationships:
        raise RuntimeError("Import verification failed: counts do not match export")


def main() -> None:
    if not AURA_URI:
        raise EnvironmentError("Missing NEO4J_AURA_URI environment variable")
    if not EXPORT_FILE.exists():
        raise FileNotFoundError(f"Export file not found: {EXPORT_FILE}")

    nodes, relationships = load_export(EXPORT_FILE)

    driver = GraphDatabase.driver(
        AURA_URI,
        auth=(DEFAULT_USER, DEFAULT_PASSWORD),
    )

    try:
        with driver.session() as session:
            session.run("CREATE INDEX neo4j_import_node_id IF NOT EXISTS FOR (n) ON (n._import_id)").consume()
            import_nodes(session, nodes)
            import_relationships(session, relationships)
            session.run("MATCH (n) REMOVE n._import_id").consume()
            verify_import(session, len(nodes), len(relationships))
    finally:
        driver.close()


if __name__ == "__main__":
    main()
