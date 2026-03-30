from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.eval.utils import flatten_dict, has_value, mean, print_table, save_json

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

CV_DIR  = Path(__file__).resolve().parents[2] / "data_eval" / "cv_synthetic"
GT_PATH = Path(__file__).resolve().parents[2] / "data_eval" / "ground_truth.json"

PUBLIC_FIELDS = [
    "full_name", "professional_summary", "skills", "experience",
    "education", "certificates", "is_available", "cultural_tags",
]
PRIVATE_FIELDS = [
    "contact.email", "contact.phone", "salary_expectation",
    "project_technical_secrets", "blacklist_orgs",
]
SPLIT_EVAL = [
    ("contact.email",             "private"),
    ("salary_expectation",        "private"),
    ("project_technical_secrets", "private"),
    ("skills",                    "public"),
    ("professional_summary",      "public"),
]

_GT_SCHEMA_HINT = json.dumps([{
    "file": "CV_NguyenHaiDang.pdf",
    "public_data": {
        "full_name": "str", "skills": ["str"], "professional_summary": "str",
        "experience": ["..."], "education": ["..."], "certificates": ["str"],
        "is_available": "bool", "cultural_tags": ["str"],
    },
    "private_data": {
        "contact": {"email": "str", "phone": "str"},
        "salary_expectation": "str", "project_technical_secrets": "str",
        "blacklist_orgs": ["str"],
    },
}], indent=2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_nested(obj: dict, dotted_key: str):
    """Resolve 'contact.email' -> obj['contact']['email'], returns None if missing."""
    parts = dotted_key.split(".")
    cur = obj
    for part in parts:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _coverage(predicted: dict, fields: list) -> float:
    """Fraction of fields that have_value in predicted."""
    if not fields:
        return 0.0
    hits = sum(1 for f in fields if has_value(_get_nested(predicted, f)))
    return hits / len(fields)


def _split_accuracy(predicted: dict) -> float:
    """Check that each SPLIT_EVAL field lives in the correct compartment."""
    correct = 0
    for field, expected_side in SPLIT_EVAL:
        if expected_side == "public":
            val = _get_nested(predicted.get("public_data", {}), field)
        else:
            val = _get_nested(predicted.get("private_data", {}), field)
        if has_value(val):
            correct += 1
    return correct / len(SPLIT_EVAL)


def _hallucination_candidates(predicted: dict, source_text: str) -> int:
    """
    Count scalar string values in predicted that are NOT traceable to source_text.
    Heuristic (no LLM):
      - value.lower() substring not in source_text.lower()
      - AND no word longer than 5 chars from value found in source_text
    """
    source_lower = source_text.lower()
    flat = flatten_dict(predicted)
    count = 0
    for _key, val in flat.items():
        if not isinstance(val, str) or not val.strip():
            continue
        v_lower = val.strip().lower()
        if v_lower in source_lower:
            continue
        long_words = [w for w in v_lower.split() if len(w) > 5]
        if any(w in source_lower for w in long_words):
            continue
        count += 1
    return count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # Guard: ground truth must exist (fast check before heavy imports)
    if not GT_PATH.exists():
        print(f"Create {GT_PATH} first. Schema:")
        print(_GT_SCHEMA_HINT)
        sys.exit(0)

    # Lazy imports — only loaded when ground_truth.json exists
    from pipeline.extractor import extract_knowledge
    from pipeline.parser import parse_to_markdown

    with open(GT_PATH, encoding="utf-8") as f:
        ground_truth: list = json.load(f)

    if not ground_truth:
        print("ground_truth.json is empty.")
        sys.exit(0)

    per_cv: list = []
    per_field_hits: dict = {f: 0 for f in PUBLIC_FIELDS + PRIVATE_FIELDS}

    for entry in ground_truth:
        filename: str = entry["file"]
        pdf_path = CV_DIR / filename
        if not pdf_path.exists():
            print(f"[SKIP] {filename} not found in {CV_DIR}")
            continue

        # Parse PDF -> markdown text
        source_text = parse_to_markdown(pdf_path)

        # Extract via LLM pipeline
        t0 = time.perf_counter()
        result = extract_knowledge(source_text, file_hint=filename, target_role=None)
        elapsed = round(time.perf_counter() - t0, 3)

        # Unwrap {record_type, data} envelope if present
        predicted: dict = result.get("data", result) if isinstance(result, dict) else {}

        pub_pred  = predicted.get("public_data",  {}) or {}
        priv_pred = predicted.get("private_data", {}) or {}

        # Coverage
        cov_pub  = _coverage(pub_pred,  PUBLIC_FIELDS)
        priv_leaf_fields = []
        for f in PRIVATE_FIELDS:
            if "." in f:
                priv_leaf_fields.append(f)   # keep dotted so _get_nested works on priv_pred
            else:
                priv_leaf_fields.append(f)
        cov_priv = _coverage(priv_pred, priv_leaf_fields)

        # Per-field tracking
        for f in PUBLIC_FIELDS:
            if has_value(_get_nested(pub_pred, f)):
                per_field_hits[f] += 1
        for f in PRIVATE_FIELDS:
            if "." in f:
                top, leaf = f.split(".", 1)
                container = priv_pred.get(top, {}) or {}
                val = container.get(leaf) if isinstance(container, dict) else None
            else:
                val = priv_pred.get(f)
            if has_value(val):
                per_field_hits[f] += 1

        # Split accuracy — operates on top-level predicted dict
        split_acc = _split_accuracy(predicted)

        # Hallucination candidates
        halluc = _hallucination_candidates(predicted, source_text)

        per_cv.append({
            "file":      filename,
            "cov_pub":   round(cov_pub,   4),
            "cov_priv":  round(cov_priv,  4),
            "split_acc": round(split_acc, 4),
            "halluc":    halluc,
            "time_s":    elapsed,
        })

    if not per_cv:
        print("No CVs evaluated.")
        sys.exit(0)

    n = len(per_cv)
    per_field_coverage = {
        f: round(per_field_hits[f] / n, 4)
        for f in PUBLIC_FIELDS + PRIVATE_FIELDS
    }

    summary = {
        "avg_coverage_public":          round(mean([r["cov_pub"]   for r in per_cv]), 4),
        "avg_coverage_private":         round(mean([r["cov_priv"]  for r in per_cv]), 4),
        "avg_split_accuracy":           round(mean([r["split_acc"] for r in per_cv]), 4),
        "avg_hallucination_candidates": round(mean([r["halluc"]    for r in per_cv]), 4),
        "avg_extraction_time_s":        round(mean([r["time_s"]    for r in per_cv]), 4),
    }

    output = {
        "summary":            summary,
        "per_field_coverage": per_field_coverage,
        "per_cv":             per_cv,
    }

    out_path = save_json(output, "extractor_eval.json")
    print(f"Saved: {out_path}\n")

    # Table 1 – per-field coverage
    field_rows = [{"field": f, "coverage": v} for f, v in per_field_coverage.items()]
    print("=== Per-Field Coverage ===")
    print_table(field_rows, columns=["field", "coverage"])

    # Table 2 – per-CV results
    print("\n=== Per-CV Results ===")
    print_table(per_cv, columns=["file", "cov_pub", "cov_priv", "split_acc", "halluc", "time_s"])

    print("\n=== Summary ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
