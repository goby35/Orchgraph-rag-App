from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(__file__).parent / "results"


def save_json(data: Any, filename: str, results_dir: Path = RESULTS_DIR) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    filepath = results_dir / filename
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return filepath


def mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = mean(values)
    variance = sum((x - m) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(variance)


def print_table(rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    if not rows:
        print("(empty)")
        return

    cols = columns or list(rows[0].keys())
    col_widths = {
        col: max(len(col), max(len(str(row.get(col, ""))) for row in rows))
        for col in cols
    }

    header = "  ".join(col.ljust(col_widths[col]) for col in cols)
    separator = "  ".join("-" * col_widths[col] for col in cols)
    print(header)
    print(separator)
    for row in rows:
        line = "  ".join(str(row.get(col, "")).ljust(col_widths[col]) for col in cols)
        print(line)


def flatten_dict(obj: dict[str, Any], prefix: str = "", sep: str = ".") -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in obj.items():
        full_key = f"{prefix}{sep}{key}" if prefix else key
        if isinstance(value, dict):
            result.update(flatten_dict(value, prefix=full_key, sep=sep))
        else:
            result[full_key] = value
    return result


def has_value(obj: Any) -> bool:
    if obj is None:
        return False
    if isinstance(obj, (str, list, dict, tuple, set)):
        return len(obj) > 0
    if isinstance(obj, float) and math.isnan(obj):
        return False
    return True
