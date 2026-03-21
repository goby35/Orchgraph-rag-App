from __future__ import annotations

from typing import Any

from pipeline.config import get_logger
from pipeline.supabase_client import get_supabase

logger = get_logger(__name__)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def save_message(org_neo4j_id: str, per_neo4j_id: str, message: dict[str, Any]) -> None:
    get_supabase().schema("vdme").table("chat_messages").insert(
        {
            "org_neo4j_id": org_neo4j_id,
            "per_neo4j_id": per_neo4j_id,
            "role": message.get("role", "user"),
            "content": message.get("content", ""),
            "is_private_mode": message.get("is_private_mode", False),
            "reasoning": message.get("reasoning"),
        }
    ).execute()


def load_history(org_neo4j_id: str, per_neo4j_id: str) -> list[dict[str, Any]]:
    rows = (
        get_supabase()
        .schema("vdme")
        .table("chat_messages")
        .select("role, content, reasoning, is_private_mode")
        .eq("org_neo4j_id", org_neo4j_id)
        .eq("per_neo4j_id", per_neo4j_id)
        .order("created_at")
        .execute()
    )

    messages: list[dict[str, Any]] = []
    for raw_row in rows.data or []:
        row = _as_dict(raw_row)
        if not row:
            continue
        msg: dict[str, Any] = {
            "role": row.get("role", "assistant"),
            "content": row.get("content", ""),
        }
        if row.get("reasoning") is not None:
            msg["reasoning"] = row.get("reasoning")
        if row.get("is_private_mode") is not None:
            msg["is_private_mode"] = row.get("is_private_mode")
        messages.append(msg)

    return messages
