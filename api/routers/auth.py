from __future__ import annotations

import uuid

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from pipeline.config import settings
from pipeline.neo4j_client import get_neo4j_driver
from pipeline.supabase_client import get_supabase

router = APIRouter()


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)
    role: str
    full_name: str
    neo4j_id: str | None = None


def _sync_user_node_to_neo4j(*, neo4j_id: str, role_value: str, full_name: str) -> None:
    label = "Organization" if role_value == "ORGANIZATION" else "Personnel"
    name_value = str(full_name or "").strip()
    if not name_value:
        name_value = neo4j_id

    cypher = f"""
    MERGE (n:{label} {{id: $neo4j_id}})
    SET n.public_name = $full_name,
        n.public_full_name = $full_name,
        n.last_updated = timestamp()
    """

    driver = get_neo4j_driver()
    session_kwargs = {"database": settings.neo4j_database} if settings.neo4j_database else {}
    try:
        with driver.session(**session_kwargs) as session:
            session.run(cypher, neo4j_id=neo4j_id, full_name=name_value).consume()
    finally:
        driver.close()


@router.post("/register")
async def register(body: RegisterRequest) -> dict[str, str]:
    """Create auth user by service key and upsert vdme.users profile."""
    sb = get_supabase()
    role_value = body.role.upper().strip()
    if role_value not in {"PERSONNEL", "ORGANIZATION"}:
        raise HTTPException(status_code=400, detail="role phải là personnel hoặc organization")

    neo_id = (body.neo4j_id or "").strip() or str(uuid.uuid4())

    try:
        res = sb.auth.admin.create_user(
            {
                "email": body.email,
                "password": body.password,
                "email_confirm": True,
                "user_metadata": {
                    "full_name": body.full_name,
                    "role": role_value,
                    "neo4j_id": neo_id,
                },
            }
        )
        if not res.user:
            raise RuntimeError("Không tạo được user")

        sb.schema("vdme").table("users").upsert(
            {
                "id": str(res.user.id),
                "role": role_value,
                "neo4j_id": neo_id,
                "full_name": body.full_name,
            },
            on_conflict="id",
        ).execute()

        _sync_user_node_to_neo4j(
            neo4j_id=neo_id,
            role_value=role_value,
            full_name=body.full_name,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Không tạo được user: {exc}") from exc

    return {"user_id": str(res.user.id), "neo4j_id": neo_id}
