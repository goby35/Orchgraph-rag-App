# api/utils/supabase_helpers.py
from typing import Any, cast

def sb_data(result: Any) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], result.data or [])

def sb_one(result: Any) -> dict[str, Any]:
    rows = cast(list[dict[str, Any]], result.data or [])
    return rows[0] if rows else {}

def sb_val(result: Any, key: str, default: Any = None) -> Any:
    row = sb_one(result)
    return row.get(key, default)