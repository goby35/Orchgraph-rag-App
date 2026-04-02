from __future__ import annotations

import json
import re
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
# Filename resolution (robust — hỗ trợ nhiều schema khác nhau)
# ---------------------------------------------------------------------------

def _slugify(s: str) -> str:
    """Bỏ ký tự đặc biệt, lowercase — dùng để fuzzy-match tên file."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _find_pdf_by_id(candidate_id: str) -> Path | None:
    """
    Tìm PDF trong CV_DIR theo 3 chiến lược:
      1. Exact substring  : "P_060"  in  "CV_P060_..."
      2. Slug match       : "p060"   in  "cvp060..."
      3. Digits-only      : "060"    in  stem
    """
    if not CV_DIR.exists():
        return None

    cid_lower  = candidate_id.lower()
    cid_slug   = _slugify(candidate_id)
    cid_digits = re.sub(r"\D", "", candidate_id)

    for pdf in sorted(CV_DIR.glob("*.pdf")):
        stem_lower = pdf.stem.lower()
        stem_slug  = _slugify(pdf.stem)

        if cid_lower  in stem_lower:                return pdf
        if cid_slug   in stem_slug:                 return pdf
        if cid_digits and cid_digits in stem_lower: return pdf

    return None


def _resolve_pdf_path(entry: dict) -> tuple[str, Path] | None:
    """
    Trả về (filename, Path) từ entry, thử theo thứ tự:
      1. entry["file"]           → tên file trực tiếp
      2. entry["personnel_id"]   → fuzzy-match trong CV_DIR
      3. entry["org_id"]         → fuzzy-match trong CV_DIR
      4. entry["public_data"]["full_name"] → fuzzy-match (last resort)

    Trả về None nếu không tìm được.
    """
    # ── Strategy 1: key "file" ────────────────────────────────────────────────
    if file_val := entry.get("file"):
        p = CV_DIR / str(file_val)
        if p.exists():
            return str(file_val), p
        # Thử case-insensitive
        fname_lower = str(file_val).lower()
        for pdf in CV_DIR.glob("*.pdf"):
            if pdf.name.lower() == fname_lower:
                return pdf.name, pdf

    # ── Strategy 2 & 3: personnel_id / org_id ────────────────────────────────
    for key in ("personnel_id", "org_id"):
        if cid := entry.get(key):
            if found := _find_pdf_by_id(str(cid)):
                return found.name, found

    # ── Strategy 4: full_name từ public_data ─────────────────────────────────
    pub = entry.get("public_data") or {}
    if full_name := pub.get("full_name"):
        if found := _find_pdf_by_id(str(full_name)):
            return found.name, found

    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_nested(obj: dict, dotted_key: str):
    """Resolve 'contact.email' → obj['contact']['email'], returns None if missing."""
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
    # Guard: ground truth must exist
    if not GT_PATH.exists():
        print(f"Create {GT_PATH} first. Schema hint:")
        print(_GT_SCHEMA_HINT)
        sys.exit(0)

    # Lazy imports — only loaded when ground_truth.json exists
    from pipeline.extractor import extract_knowledge
    from pipeline.parser import parse_to_markdown

    with open(GT_PATH, encoding="utf-8") as f:
        ground_truth: list = json.load(f)

    # Chấp nhận cả list lẫn single object
    if isinstance(ground_truth, dict):
        ground_truth = [ground_truth]

    if not ground_truth:
        print("ground_truth.json is empty.")
        sys.exit(0)

    per_cv: list = []
    per_field_hits: dict = {f: 0 for f in PUBLIC_FIELDS + PRIVATE_FIELDS}

    for entry in ground_truth:
        # ── Resolve PDF path (robust, không KeyError) ─────────────────────────
        resolved = _resolve_pdf_path(entry)
        if resolved is None:
            # Log thân thiện: hiện các key có trong entry để debug
            known_keys = list(entry.keys())
            fallback_id = (
                entry.get("file")
                or entry.get("personnel_id")
                or entry.get("org_id")
                or "<unknown>"
            )
            print(f"[SKIP] Không tìm được PDF cho entry '{fallback_id}'. "
                  f"Keys trong entry: {known_keys}. "
                  f"PDF_DIR: {CV_DIR}")
            continue

        filename, pdf_path = resolved

        # Parse PDF → markdown text
        source_text = parse_to_markdown(pdf_path)

        # Extract via LLM pipeline
        t0 = time.perf_counter()
        result = extract_knowledge(source_text, file_hint=filename, target_role=None)
        elapsed = round(time.perf_counter() - t0, 3)

        # Unwrap {record_type, data} envelope nếu có
        predicted: dict = result.get("data", result) if isinstance(result, dict) else {}

        pub_pred  = predicted.get("public_data",  {}) or {}
        priv_pred = predicted.get("private_data", {}) or {}

        # Coverage
        cov_pub  = _coverage(pub_pred, PUBLIC_FIELDS)
        cov_priv = _coverage(priv_pred, PRIVATE_FIELDS)

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