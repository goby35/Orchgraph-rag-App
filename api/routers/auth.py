from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from pipeline.supabase_client import get_supabase

router = APIRouter()


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)
    role: str
    full_name: str
    neo4j_id: str


@router.post("/register")
async def register(body: RegisterRequest) -> dict[str, str]:
    """Create auth user by service key and upsert vdme.users profile."""
    sb = get_supabase()
    role_value = body.role.upper().strip()
    if role_value not in {"PERSONNEL", "ORGANIZATION"}:
        raise HTTPException(status_code=400, detail="role phai la personnel hoac organization")

    try:
        res = sb.auth.admin.create_user(
            {
                "email": body.email,
                "password": body.password,
                "email_confirm": True,
                "user_metadata": {
                    "full_name": body.full_name,
                    "role": role_value,
                    "neo4j_id": body.neo4j_id,
                },
            }
        )
        if not res.user:
            raise RuntimeError("Khong tao duoc user")

        sb.schema("vdme").table("users").upsert(
            {
                "id": str(res.user.id),
                "role": role_value,
                "neo4j_id": body.neo4j_id,
                "full_name": body.full_name,
            },
            on_conflict="id",
        ).execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Khong tao duoc user: {exc}") from exc

    return {"user_id": str(res.user.id), "neo4j_id": body.neo4j_id}
