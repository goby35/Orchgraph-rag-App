# api/utils/supabase_helpers.py
# from typing import Any, cast

# def sb_data(result: Any) -> list[dict[str, Any]]:
#     return cast(list[dict[str, Any]], result.data or [])

# def sb_one(result: Any) -> dict[str, Any]:
#     rows = cast(list[dict[str, Any]], result.data or [])
#     return rows[0] if rows else {}

# def sb_val(result: Any, key: str, default: Any = None) -> Any:
#     row = sb_one(result)
#     return row.get(key, default)

from typing import Any, cast

def sb_data(result: Any) -> list[dict[str, Any]]:
    data = result.data
    if isinstance(data, list):
        return cast(list[dict[str, Any]], data)
    if isinstance(data, dict):
        return [cast(dict[str, Any], data)]
    return []

def sb_one(result: Any) -> dict[str, Any]:
    data = result.data
    if isinstance(data, dict):
        return cast(dict[str, Any], data)    # maybe_single → trả về dict trực tiếp
    if isinstance(data, list) and data:
        return cast(dict[str, Any], data[0]) # single → trả về list[1]
    return {}

def sb_val(result: Any, key: str, default: Any = None) -> Any:
    row = sb_one(result)
    return row.get(key, default)