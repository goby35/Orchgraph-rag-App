from __future__ import annotations

from neo4j import GraphDatabase

from pipeline.config import settings
from pipeline.supabase_client import get_supabase

TEMP_PASSWORD = "ChangeMe@2026!"


def main() -> None:
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )
    sb = get_supabase()

    with driver.session() as session:
        rows = session.run(
            """
            MATCH (u)
            WHERE (u:Organization OR u:Personnel)
              AND coalesce(u.email, '') <> ''
            RETURN u.id AS neo4j_id,
                   u.email AS email,
                   labels(u)[0] AS role,
                   coalesce(u.public_name, u.id) AS full_name
            """
        ).data()

    for row in rows:
        neo4j_id = row.get("neo4j_id")
        email = row.get("email")
        role = str(row.get("role") or "").upper()
        full_name = row.get("full_name")

        if not neo4j_id or not email or role not in {"PERSONNEL", "ORGANIZATION"}:
            print(f"SKIP invalid row: {row}")
            continue

        try:
            res = sb.auth.admin.create_user(
                {
                    "email": email,
                    "password": TEMP_PASSWORD,
                    "email_confirm": True,
                    "user_metadata": {
                        "full_name": full_name,
                        "role": role,
                        "neo4j_id": neo4j_id,
                    },
                }
            )

            user_id = str(res.user.id) if res.user else None
            if not user_id:
                raise RuntimeError("create_user returned empty user")

            sb.schema("vdme").table("users").upsert(
                {
                    "id": user_id,
                    "role": role,
                    "neo4j_id": neo4j_id,
                    "full_name": full_name,
                },
                on_conflict="id",
            ).execute()

            print(f"OK {neo4j_id} -> {user_id}")
        except Exception as exc:
            print(f"WARN {neo4j_id}: {exc}")

    driver.close()


if __name__ == "__main__":
    main()
