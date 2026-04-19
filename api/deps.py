from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from pipeline.supabase_client import get_supabase

_bearer = HTTPBearer()


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict[str, Any]:
    """Verify Supabase JWT and return mapped user payload with neo4j bridge id."""
    sb = get_supabase()
    try:
        user_res = sb.auth.get_user(creds.credentials)
        user = getattr(user_res, "user", None)
        if not user:
            raise ValueError("invalid token")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không hợp lệ hoặc đã hết hạn",
        ) from exc

    row = (
        sb.schema("vdme")
        .table("users")
        .select("neo4j_id, role")
        .eq("id", str(user.id))
        .single()
        .execute()
    )

    if not row.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User chưa có profile",
        )

    profile = _as_dict(row.data)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User chưa có profile",
        )

    return {
        "supabase_id": str(user.id),
        "neo4j_id": profile.get("neo4j_id"),
        "role": str(profile.get("role", "")).lower(),
    }
