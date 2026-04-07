from __future__ import annotations

import json
import os
from pathlib import Path

from neo4j import GraphDatabase

DEFAULT_URI = "bolt://localhost:7687"
DEFAULT_USER = os.getenv("NEO4J_USER", "neo4j")
DEFAULT_PASSWORD = os.getenv("NEO4J_PASSWORD", "password123")
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "neo4j_export.json"


def export_graph(output_path: Path) -> tuple[int, int]:
    driver = GraphDatabase.driver(
        DEFAULT_URI,
        auth=(DEFAULT_USER, DEFAULT_PASSWORD),
    )

    try:
        with driver.session() as session:
            nodes = session.run(
                """
                MATCH (n)
                RETURN elementId(n) AS id,
                       labels(n) AS labels,
                       properties(n) AS properties
                """
            ).data()

            relationships = session.run(
                """
                MATCH (a)-[r]->(b)
                RETURN elementId(r) AS id,
                       type(r) AS type,
                       elementId(a) AS start_node_id,
                       elementId(b) AS end_node_id,
                       properties(r) AS properties
                """
            ).data()

        payload = {
            "nodes": nodes,
            "relationships": relationships,
        }

        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return len(nodes), len(relationships)
    finally:
        driver.close()


def main() -> None:
    output_path = DEFAULT_OUTPUT
    node_count, relationship_count = export_graph(output_path)
    print(f"Exported {node_count} nodes and {relationship_count} relationships to {output_path}")


if __name__ == "__main__":
    main()
