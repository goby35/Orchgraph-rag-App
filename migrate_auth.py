from __future__ import annotations

import json
import re
from typing import Any

import bcrypt
from neo4j import GraphDatabase
from tqdm import tqdm

from pipeline.config import settings

DEFAULT_PASSWORD = "admin123"


def _safe_parse_private_blob(private_blob: Any) -> dict[str, Any]:
    if private_blob is None:
        return {}
    if isinstance(private_blob, dict):
        return private_blob
    if not isinstance(private_blob, str) or not private_blob.strip():
        return {}

    try:
        parsed = json.loads(private_blob)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _extract_email(node_id: str, private_data: dict[str, Any]) -> str:
    direct_email = private_data.get("email") or private_data.get("contact_email")
    if isinstance(direct_email, str) and "@" in direct_email:
        return direct_email.strip().lower()

    contact = private_data.get("contact")
    if isinstance(contact, dict):
        contact_email = contact.get("email") or contact.get("contact_email")
        if isinstance(contact_email, str) and "@" in contact_email:
            return contact_email.strip().lower()

    return f"{node_id}@demo.com".lower()


def _slug_username(base: str, fallback: str) -> str:
    candidate = re.sub(r"[^a-zA-Z0-9._-]", "_", base.strip())
    candidate = candidate.strip("._-").lower()
    if candidate:
        return candidate
    return re.sub(r"[^a-zA-Z0-9._-]", "_", fallback).lower() or "user"


def _make_unique(base_username: str, used_usernames: set[str]) -> str:
    base = _slug_username(base_username, "user")
    if base not in used_usernames:
        used_usernames.add(base)
        return base

    idx = 1
    while True:
        candidate = f"{base}_{idx}"
        if candidate not in used_usernames:
            used_usernames.add(candidate)
            return candidate
        idx += 1


def run_migration() -> None:
    default_hash = bcrypt.hashpw(DEFAULT_PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )

    try:
        with driver.session() as session:
            existing_usernames_rows = session.run(
                """
                MATCH (n)
                WHERE (n:Personnel OR n:Organization)
                  AND n.username IS NOT NULL
                  AND trim(toString(n.username)) <> ''
                RETURN toLower(toString(n.username)) AS username
                """
            ).data()
            used_usernames = {
                str(row.get("username") or "").strip().lower()
                for row in existing_usernames_rows
                if str(row.get("username") or "").strip()
            }

            rows = session.run(
                """
                MATCH (n)
                WHERE (n:Personnel OR n:Organization)
                  AND n.username IS NULL
                RETURN
                    n.id AS node_id,
                    coalesce(n.public_name, n.name, n.id) AS display_name,
                    n.private_data_blob AS private_data_blob
                ORDER BY node_id
                """
            ).data()

            if not rows:
                print("Khong co node nao can migrate.")
                return

            migrated = 0
            skipped = 0

            for row in tqdm(rows, desc="Migrating auth", unit="node"):
                node_id = str(row.get("node_id") or "").strip()
                display_name = str(row.get("display_name") or node_id).strip()
                if not node_id:
                    skipped += 1
                    print("⚠️ Bo qua 1 node vi thieu id")
                    continue

                private_data = _safe_parse_private_blob(row.get("private_data_blob"))
                email = _extract_email(node_id=node_id, private_data=private_data)

                local_part = email.split("@", 1)[0] if "@" in email else node_id
                base_username = local_part or node_id
                username = _make_unique(base_username, used_usernames)

                session.run(
                    """
                    MATCH (n {id: $node_id})
                    WHERE n.username IS NULL
                    SET n.username = $username,
                        n.email = $email,
                        n.password_hash = $default_hash,
                        n.last_updated = timestamp()
                    """,
                    node_id=node_id,
                    username=username,
                    email=email,
                    default_hash=default_hash,
                )

                migrated += 1
                print(
                    f"✅ Da cap tai khoan cho {display_name} - Username: {username} - Mat khau: {DEFAULT_PASSWORD}"
                )

            print(f"\nMigration completed. Migrated={migrated}, Skipped={skipped}")
    finally:
        driver.close()


if __name__ == "__main__":
    run_migration()
