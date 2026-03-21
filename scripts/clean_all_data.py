"""
scripts/clean_all_data.py
Xoa toan bo du lieu cu/test khoi Neo4j va Supabase.
Chay TRUOC re-ingest. Khong xoa schema/tables, chi xoa rows/nodes.

Dung:
  python scripts/clean_all_data.py --dry-run   # xem se xoa gi
  python scripts/clean_all_data.py             # xoa that
  python scripts/clean_all_data.py --neo4j     # chi xoa Neo4j
  python scripts/clean_all_data.py --supabase  # chi xoa Supabase
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any, cast

from neo4j import GraphDatabase

# Bootstrap sys.path de import pipeline package khi chay tu scripts/.
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.config import settings
from pipeline.supabase_client import get_supabase


@dataclass(frozen=True)
class Neo4jCleanupStep:
    name: str
    preview_query: str
    delete_query: str


NEO4J_CLEANUP_STEPS: list[Neo4jCleanupStep] = [
    Neo4jCleanupStep(
        "Test nodes",
        """
        MATCH (n)
        WHERE n.id IN ['ORG_ACCESS_TEST', 'PER_ACCESS_TEST',
                       'ORG_TEST', 'PER_TEST',
                       'ORG_TEST_ID', 'PER_TEST_ID']
        RETURN count(n) AS cnt
        """,
        """
        MATCH (n)
        WHERE n.id IN ['ORG_ACCESS_TEST', 'PER_ACCESS_TEST',
                       'ORG_TEST', 'PER_TEST',
                       'ORG_TEST_ID', 'PER_TEST_ID']
        DETACH DELETE n
        """,
    ),
    Neo4jCleanupStep(
        "Orphan Experience nodes",
        """
        MATCH (e:Experience)
        WHERE NOT EXISTS { MATCH (:Personnel)-[:HAS_EXPERIENCE]->(e) }
        RETURN count(e) AS cnt
        """,
        """
        MATCH (e:Experience)
        WHERE NOT EXISTS { MATCH (:Personnel)-[:HAS_EXPERIENCE]->(e) }
        DETACH DELETE e
        """,
    ),
    Neo4jCleanupStep(
        "Orphan Education nodes",
        """
        MATCH (e:Education)
        WHERE NOT EXISTS { MATCH (:Personnel)-[:HAS_EDUCATION]->(e) }
        RETURN count(e) AS cnt
        """,
        """
        MATCH (e:Education)
        WHERE NOT EXISTS { MATCH (:Personnel)-[:HAS_EDUCATION]->(e) }
        DETACH DELETE e
        """,
    ),
    Neo4jCleanupStep(
        "Orphan TechStack",
        """
        MATCH (t:TechStack)
        WHERE NOT EXISTS { MATCH ()-[]->(t) }
        RETURN count(t) AS cnt
        """,
        """
        MATCH (t:TechStack)
        WHERE NOT EXISTS { MATCH ()-[]->(t) }
        DELETE t
        """,
    ),
    Neo4jCleanupStep(
        "Orphan Organization",
        """
        MATCH (o:Organization)
        WHERE NOT EXISTS { MATCH ()-[]->(o) }
        RETURN count(o) AS cnt
        """,
        """
        MATCH (o:Organization)
        WHERE NOT EXISTS { MATCH ()-[]->(o) }
        DELETE o
        """,
    ),
    Neo4jCleanupStep(
        "Orphan School",
        """
        MATCH (s:School)
        WHERE NOT EXISTS { MATCH ()-[]->(s) }
        RETURN count(s) AS cnt
        """,
        """
        MATCH (s:School)
        WHERE NOT EXISTS { MATCH ()-[]->(s) }
        DELETE s
        """,
    ),
    Neo4jCleanupStep(
        "Orphan Role",
        """
        MATCH (r:Role)
        WHERE NOT EXISTS { MATCH ()-[]->(r) }
        RETURN count(r) AS cnt
        """,
        """
        MATCH (r:Role)
        WHERE NOT EXISTS { MATCH ()-[]->(r) }
        DELETE r
        """,
    ),
    Neo4jCleanupStep(
        "Orphan Project",
        """
        MATCH (p:Project)
        WHERE NOT EXISTS { MATCH ()-[]->(p) }
        RETURN count(p) AS cnt
        """,
        """
        MATCH (p:Project)
        WHERE NOT EXISTS { MATCH ()-[]->(p) }
        DELETE p
        """,
    ),
    Neo4jCleanupStep(
        "Orphan CulturalTag",
        """
        MATCH (c:CulturalTag)
        WHERE NOT EXISTS { MATCH ()-[]->(c) }
        RETURN count(c) AS cnt
        """,
        """
        MATCH (c:CulturalTag)
        WHERE NOT EXISTS { MATCH ()-[]->(c) }
        DELETE c
        """,
    ),
    Neo4jCleanupStep(
        "Orphan Certificate",
        """
        MATCH (c:Certificate)
        WHERE NOT EXISTS { MATCH ()-[]->(c) }
        RETURN count(c) AS cnt
        """,
        """
        MATCH (c:Certificate)
        WHERE NOT EXISTS { MATCH ()-[]->(c) }
        DELETE c
        """,
    ),
    Neo4jCleanupStep(
        "ChatSession nodes",
        "MATCH (s:ChatSession) RETURN count(s) AS cnt",
        "MATCH (s:ChatSession) DETACH DELETE s",
    ),
    Neo4jCleanupStep(
        "Message nodes",
        "MATCH (m:Message) RETURN count(m) AS cnt",
        "MATCH (m:Message) DETACH DELETE m",
    ),
    Neo4jCleanupStep(
        "All Personnel nodes",
        "MATCH (p:Personnel) RETURN count(p) AS cnt",
        "MATCH (p:Personnel) DETACH DELETE p",
    ),
    Neo4jCleanupStep(
        "All Organization nodes",
        "MATCH (o:Organization) RETURN count(o) AS cnt",
        "MATCH (o:Organization) DETACH DELETE o",
    ),
    Neo4jCleanupStep(
        "Remaining TechStack",
        "MATCH (t:TechStack) RETURN count(t) AS cnt",
        "MATCH (t:TechStack) DETACH DELETE t",
    ),
    Neo4jCleanupStep(
        "Remaining Role",
        "MATCH (r:Role) RETURN count(r) AS cnt",
        "MATCH (r:Role) DETACH DELETE r",
    ),
    Neo4jCleanupStep(
        "Remaining School",
        "MATCH (s:School) RETURN count(s) AS cnt",
        "MATCH (s:School) DETACH DELETE s",
    ),
    Neo4jCleanupStep(
        "Remaining Project",
        "MATCH (p:Project) RETURN count(p) AS cnt",
        "MATCH (p:Project) DETACH DELETE p",
    ),
    Neo4jCleanupStep(
        "Remaining CulturalTag",
        "MATCH (c:CulturalTag) RETURN count(c) AS cnt",
        "MATCH (c:CulturalTag) DETACH DELETE c",
    ),
    Neo4jCleanupStep(
        "Remaining Certificate",
        "MATCH (c:Certificate) RETURN count(c) AS cnt",
        "MATCH (c:Certificate) DETACH DELETE c",
    ),
]


def _count_neo4j(session: Any, query: str) -> int:
    row = session.run(cast(Any, query)).single()
    if not row:
        return 0
    return int(row.get("cnt") or 0)


def _run_neo4j_cleanup(dry_run: bool) -> None:
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )
    try:
        with driver.session() as session:
            if dry_run:
                print("[DRY RUN] Neo4j se xoa:")
                for step in NEO4J_CLEANUP_STEPS:
                    cnt = _count_neo4j(session, step.preview_query)
                    print(f"  - {step.name}: {cnt} nodes")
                return

            print("[RUN] Neo4j cleanup:")
            for step in NEO4J_CLEANUP_STEPS:
                before = _count_neo4j(session, step.preview_query)
                session.run(cast(Any, step.delete_query))
                print(f"  - {step.name}: deleted~{before}")
    finally:
        driver.close()


def _count_table(sb: Any, table: str, id_col: str) -> int:
    resp = (
        sb.schema("vdme")
        .table(table)
        .select(id_col, count=cast(Any, "exact"))
        .limit(1)
        .execute()
    )
    return int(resp.count or 0)


def _delete_table(sb: Any, table: str, id_col: str) -> None:
    # PostgREST delete all with a non-null filter to avoid accidental no-filter rejection.
    (
        sb.schema("vdme")
        .table(table)
        .delete()
        .not_.is_(id_col, "null")
        .execute()
    )


def _run_supabase_cleanup(dry_run: bool) -> None:
    sb = get_supabase()
    steps = [
        ("chunk_embeddings", "chunk_id"),
        ("document_chunks", "id"),
        ("profiles", "user_id"),
        ("users", "id"),
    ]

    if dry_run:
        print("[DRY RUN] Supabase se xoa:")
        for table, id_col in steps:
            cnt = _count_table(sb, table, id_col)
            print(f"  - vdme.{table}: {cnt} rows")
        return

    print("[RUN] Supabase cleanup:")
    for table, id_col in steps:
        before = _count_table(sb, table, id_col)
        _delete_table(sb, table, id_col)
        print(f"  - vdme.{table}: deleted~{before}")


def _verify_clean() -> bool:
    """Tra ve True neu ca 2 DB deu sach."""
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )
    sb = get_supabase()

    try:
        with driver.session() as session:
            row = session.run(
                """
                RETURN
                  count{MATCH (p:Personnel)} AS personnel,
                  count{MATCH (o:Organization)} AS org,
                  count{MATCH (t:TechStack)} AS tech
                """
            ).single()
            if row is None:
                row = {}
            neo4j_counts = {
                "personnel": int(row.get("personnel") or 0),
                "org": int(row.get("org") or 0),
                "tech": int(row.get("tech") or 0),
            }

        chunks = (
            sb.schema("vdme")
            .table("document_chunks")
            .select("id", count=cast(Any, "exact"))
            .execute()
        )
        users = (
            sb.schema("vdme")
            .table("users")
            .select("id", count=cast(Any, "exact"))
            .execute()
        )

        all_zero = all(v == 0 for v in neo4j_counts.values())
        supabase_clean = (int(chunks.count or 0) == 0) and (int(users.count or 0) == 0)

        print(f"Neo4j: {neo4j_counts}")
        print(f"Supabase chunks: {int(chunks.count or 0)}, users: {int(users.count or 0)}")
        return all_zero and supabase_clean
    finally:
        driver.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean old/test data in Neo4j and Supabase")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no deletion")
    parser.add_argument("--neo4j", action="store_true", help="Clean only Neo4j")
    parser.add_argument("--supabase", action="store_true", help="Clean only Supabase")
    args = parser.parse_args()

    run_neo4j = args.neo4j or (not args.neo4j and not args.supabase)
    run_supabase = args.supabase or (not args.neo4j and not args.supabase)

    if run_neo4j:
        _run_neo4j_cleanup(dry_run=args.dry_run)
    if run_supabase:
        _run_supabase_cleanup(dry_run=args.dry_run)

    if args.dry_run:
        print("\nChay lai khong co --dry-run de thuc su xoa.")
        return

    ok = _verify_clean()
    if ok:
        print("\n[SUCCESS] Neo4j + Supabase da duoc clean.")
    else:
        print("\n[WARN] Con du lieu ton du. Hay kiem tra logs/permissions.")


if __name__ == "__main__":
    main()
