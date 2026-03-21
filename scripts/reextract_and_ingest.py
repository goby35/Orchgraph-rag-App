"""
scripts/reextract_and_ingest.py
Re-extract JSON v1 tu fast_track/ qua LLM (extractor.py) -> ingest Neo4j + Supabase.

Tai sao khong parse JSON v1 truc tiep:
  - JSON v1 co skills dang chuoi dai, LLM co kha nang normalize tot hon regex thuong.
  - LLM tach organization/project tu mo ta kinh nghiem phuc tap.
  - Schema v2 (DegreeLevel enum, nested Experience/Education) duoc enforce tu dong.

Dung:
  python scripts/reextract_and_ingest.py --dry-run          # xem text serialize
  python scripts/reextract_and_ingest.py --limit 3          # test 3 records dau
  python scripts/reextract_and_ingest.py --type personnel   # chi Personnel
  python scripts/reextract_and_ingest.py --type org         # chi Organization
  python scripts/reextract_and_ingest.py                    # toan bo
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

# Bootstrap sys.path de import pipeline
sys.path.insert(0, str(Path(__file__).parent.parent))


def serialize_personnel_to_text(v1: dict[str, Any]) -> str:
    pub  = v1.get("public_data", {}) if isinstance(v1.get("public_data"), dict) else {}
    priv = v1.get("private_data", {}) if isinstance(v1.get("private_data"), dict) else {}
    pid  = str(v1.get("personnel_id") or "")

    lines = [
        f"# {pub.get('full_name', pid)}",
        f"ID: {pid}",
        "",
        "## Tom tat chuyen mon",
        str(pub.get("professional_summary") or ""),
        "",
    ]

    edu_list = pub.get("education", []) if isinstance(pub.get("education"), list) else []
    if edu_list:
        lines.append("## Hoc van")
        for e in edu_list:
            if not isinstance(e, dict):
                continue
            year = e.get("year", "")
            lines.append(
                f"- {e.get('degree', '')} {e.get('major', '')} "
                f"tai {e.get('school', '')} ({year})"
            )
        lines.append("")

    exp_list = pub.get("experience", []) if isinstance(pub.get("experience"), list) else []
    if exp_list:
        lines.append("## Kinh nghiem lam viec")
        for ex in exp_list:
            if not isinstance(ex, dict):
                continue
            tech      = ex.get("tech_stack", [])
            tech_text = ", ".join(str(t) for t in tech) if isinstance(tech, list) else ""
            lines.append(f"- Du an: {ex.get('project_name', '')}")
            lines.append(f"  Vai tro: {ex.get('role', '')}")
            org_name = ex.get("organization_name", "")
            if org_name:
                lines.append(f"  To chuc: {org_name}")
            if tech_text:
                lines.append(f"  Cong nghe: {tech_text}")
        lines.append("")

    skills = pub.get("skills", []) if isinstance(pub.get("skills"), list) else []
    if skills:
        lines.append("## Ky nang")
        lines.append(", ".join(str(s) for s in skills))
        lines.append("")

    certs = pub.get("certificates", []) if isinstance(pub.get("certificates"), list) else []
    if certs:
        lines.append("## Chung chi")
        lines.append(", ".join(str(c) for c in certs))
        lines.append("")

    tags = pub.get("cultural_tags", []) if isinstance(pub.get("cultural_tags"), list) else []
    if tags:
        lines.append("## Van hoa lam viec")
        lines.append(", ".join(str(t) for t in tags))
        lines.append("")

    avail = pub.get("availability", "")
    if avail:
        lines.append(f"## Trang thai: {avail}")
        lines.append("")

    contact = priv.get("contact", {}) if isinstance(priv.get("contact"), dict) else {}
    if contact:
        lines.append("## THONG TIN LIEN HE (PRIVATE)")
        if contact.get("email"):
            lines.append(f"Email: {contact['email']}")
        if contact.get("phone"):
            lines.append(f"Phone: {contact['phone']}")
        if contact.get("github"):
            lines.append(f"GitHub: {contact['github']}")
        if contact.get("linkedin"):
            lines.append(f"LinkedIn: {contact['linkedin']}")
        lines.append("")

    salary = priv.get("salary_expectation", "")
    if salary:
        lines.append("## KY VONG LUONG (PRIVATE)")
        lines.append(str(salary))
        lines.append("")

    secrets = priv.get("project_technical_secrets", "")
    if secrets:
        lines.append("## BI MAT DU AN / DIEM KHAC BIET (PRIVATE)")
        lines.append(str(secrets))
        lines.append("")

    qa_list = (
        priv.get("interview_questions_history", [])
        if isinstance(priv.get("interview_questions_history"), list)
        else []
    )
    if qa_list:
        lines.append("## LICH SU CAU HOI PHONG VAN (PRIVATE)")
        for qa in qa_list:
            if not isinstance(qa, dict):
                continue
            lines.append(f"To chuc: {qa.get('org', '')}")
            lines.append(f"Cau hoi: {qa.get('question', '')}")
            lines.append(f"Tra loi: {qa.get('answer', '')}")
            lines.append("")

    blacklist = (
        priv.get("blacklist_orgs", [])
        if isinstance(priv.get("blacklist_orgs"), list)
        else []
    )
    if blacklist:
        lines.append("## MOI TRUONG KHONG PHU HOP (PRIVATE)")
        for b in blacklist:
            lines.append(f"- {b}")
        lines.append("")

    evidence = (
        priv.get("evidence_links", [])
        if isinstance(priv.get("evidence_links"), list)
        else []
    )
    if evidence:
        lines.append("## EVIDENCE LINKS")
        for link in evidence:
            lines.append(f"- {link}")
        lines.append("")

    return "\n".join(lines)


def serialize_org_to_text(v1: dict[str, Any]) -> str:
    pub  = v1.get("public_data", {}) if isinstance(v1.get("public_data"), dict) else {}
    priv = v1.get("private_data", {}) if isinstance(v1.get("private_data"), dict) else {}
    oid  = str(v1.get("org_id") or "")

    lines = [
        f"# {pub.get('org_name', oid)}",
        f"ID: {oid}",
        f"Nganh: {pub.get('industry', '')}",
        "",
        "## Mo ta to chuc",
        str(pub.get("brief_description") or ""),
        "",
    ]

    jds = pub.get("active_jds", []) if isinstance(pub.get("active_jds"), list) else []
    if jds:
        lines.append("## Vi tri tuyen dung")
        for jd in jds:
            if not isinstance(jd, dict):
                continue
            lines.append(f"### {jd.get('position', '')}")
            lines.append(str(jd.get("description") or ""))
            reqs = jd.get("requirements", []) if isinstance(jd.get("requirements"), list) else []
            if reqs:
                lines.append("Yeu cau ky thuat:")
                for r in reqs:
                    lines.append(f"- {r}")
            benefits = jd.get("benefits", []) if isinstance(jd.get("benefits"), list) else []
            if benefits:
                lines.append("Quyen loi:")
                for b in benefits:
                    lines.append(f"- {b}")
            loc = jd.get("location", "")
            if loc:
                lines.append(f"Dia diem: {loc}")
            lines.append("")

    techstack = (
        priv.get("core_techstack_detail", {})
        if isinstance(priv.get("core_techstack_detail"), dict)
        else {}
    )
    if techstack:
        lines.append("## CHI TIET KY THUAT NOI BO (PRIVATE)")
        for k, v in techstack.items():
            lines.append(f"{k}: {v}")
        lines.append("")

    pain_points = priv.get("internal_project_pain_points", "")
    if pain_points:
        lines.append("## PAIN POINTS KY THUAT (PRIVATE)")
        lines.append(str(pain_points))
        lines.append("")

    dna = priv.get("target_candidate_dna", "")
    if dna:
        lines.append("## DNA UNG VIEN LY TUONG (PRIVATE)")
        lines.append(str(dna))
        lines.append("")

    clients = (
        priv.get("client_list", [])
        if isinstance(priv.get("client_list"), list)
        else []
    )
    if clients:
        lines.append("## DANH SACH KHACH HANG (PRIVATE)")
        for c in clients:
            lines.append(f"- {c}")
        lines.append("")

    return "\n".join(lines)


def detect_type(
    data: dict[str, Any] | list[Any],
) -> tuple[str, list[dict[str, Any]]]:
    records            = data if isinstance(data, list) else [data]
    normalized_records = [r for r in records if isinstance(r, dict)]

    types: set[str] = set()
    for r in normalized_records:
        if "personnel_id" in r:
            types.add("personnel")
        elif "org_id" in r:
            types.add("org")

    if len(types) == 1:
        return next(iter(types)), normalized_records
    if len(types) > 1:
        return "mixed", normalized_records
    return "unknown", normalized_records


def _extract_payload(extracted: dict[str, Any]) -> dict[str, Any]:
    if isinstance(extracted.get("data"), dict):
        return extracted["data"]
    return extracted


# ── FIX 3: đảm bảo ID đúng loại sau extract ─────────────────────────────────
def _fix_node_id(payload: dict[str, Any], node_type: str, record: dict[str, Any]) -> None:
    """
    Sau khi LLM extract, đảm bảo:
    - Personnel có personnel_id đúng, không có org_id
    - Organization có org_id đúng, không có personnel_id

    Vấn đề cần giải quyết:
    - LLM đôi khi set org_id thay vì personnel_id cho Personnel (hoặc ngược lại)
    - _merge_and_validate dùng heuristic experience→personnel nhưng không
      nhận biết được file_hint loại nào → có thể gán nhầm
    """
    original_id = str(
        record.get("personnel_id") or record.get("org_id") or ""
    )

    if node_type == "personnel":
        # Đảm bảo personnel_id = ID gốc, xóa org_id nếu có
        payload["personnel_id"] = payload.get("personnel_id") or original_id
        payload["org_id"]       = None
        # Nếu LLM gán org_id thay vì personnel_id, sửa lại
        if not payload["personnel_id"] and payload.get("org_id"):
            payload["personnel_id"] = payload.pop("org_id")
            payload["org_id"]       = None

    else:  # org
        # Đảm bảo org_id = ID gốc, xóa personnel_id nếu có
        payload["org_id"]       = payload.get("org_id") or original_id
        payload["personnel_id"] = None
        # Nếu LLM gán personnel_id thay vì org_id, sửa lại
        if not payload["org_id"] and payload.get("personnel_id"):
            payload["org_id"]       = payload.pop("personnel_id")
            payload["personnel_id"] = None

    # Fallback cuối: nếu vẫn rỗng, dùng ID gốc từ record
    if node_type == "personnel" and not payload.get("personnel_id"):
        payload["personnel_id"] = original_id
    if node_type == "org" and not payload.get("org_id"):
        payload["org_id"] = original_id


# ── FIX 4: retry với exponential backoff cho rate limit ──────────────────────
def _process_one_inner(
    record: dict[str, Any],
    node_type: str,
) -> dict[str, Any]:
    """
    Lõi xử lý 1 record — không có retry.
    Tách riêng để _process_one_with_retry gọi lại khi cần.
    """
    from pipeline.extractor import extract
    from pipeline.neo4j_ingestion import neo4j_service
    from pipeline.schemas import RecruitmentNode
    from pipeline.supabase_ingestion import ingest_to_supabase
    from pipeline.vectorizer import vectorize_text

    node_id   = str(record.get("personnel_id") or record.get("org_id") or "?")
    file_hint = f"{node_type}_{node_id}"

    if node_type == "personnel":
        text = serialize_personnel_to_text(record)
    else:
        text = serialize_org_to_text(record)

    # Extract qua LLM
    extracted = extract(text, file_hint=file_hint)
    payload   = _extract_payload(extracted)

    # FIX 3: đảm bảo ID đúng loại sau extract
    _fix_node_id(payload, node_type, record)

    # FIX 2: kiểm tra neo4j_id không rỗng trước khi validate
    node = RecruitmentNode.model_validate(payload)
    if not node.neo4j_id:
        return {
            "status": "fail",
            "id":     node_id,
            "chunks": 0,
            "error":  "neo4j_id rỗng sau extract — bỏ qua để tránh ingest node không ID",
        }

    # Embedding
    summary_text     = node.public_data.professional_summary or text[:500]
    private_text     = json.dumps(node.private_data.model_dump(), ensure_ascii=False)
    public_embedding = vectorize_text(summary_text)
    private_embedding = vectorize_text(
        private_text[:1000] if private_text else summary_text
    )

    # Ingest Neo4j
    node_data = {
        "node_id": node.neo4j_id,
        "record_type": node.role,
        "public_data": node.public_data.model_dump(),
        "public_embeddings_phobert": public_embedding,        # chỉ giữ public embedding
        "source_file": file_hint,
    }
    neo4j_service.ingest_node(
        node_data,
        target_node_id=node.neo4j_id,
        target_role=node.role,
    )

    # Ingest Supabase
    ingest_to_supabase(node)

    return {"status": "ok", "id": node_id, "chunks": 0}


def process_one(
    record:   dict[str, Any],
    node_type: str,
    dry_run:  bool,
) -> dict[str, Any]:
    """
    Entry point xử lý 1 record.
    dry_run=True  → chỉ preview text, không gọi LLM.
    dry_run=False → gọi _process_one_with_retry (có retry + backoff).
    """
    node_id = str(record.get("personnel_id") or record.get("org_id") or "?")

    if dry_run:
        text    = serialize_personnel_to_text(record) if node_type == "personnel" \
                  else serialize_org_to_text(record)
        preview = text[:300] + "..." if len(text) > 300 else text
        print(f"\n[DRY] {node_id}:\n{preview}\n---")
        return {"status": "dry", "id": node_id, "chunks": 0}

    return _process_one_with_retry(record, node_type)


def _process_one_with_retry(
    record:    dict[str, Any],
    node_type: str,
    max_retries: int = 3,
) -> dict[str, Any]:
    """
    FIX 4: Gọi _process_one_inner với retry + exponential backoff.

    Retry khi:
    - openai.RateLimitError  (HTTP 429)
    - openai.APITimeoutError
    - Bất kỳ exception nào có "rate" hoặc "429" trong message

    Không retry khi:
    - ValidationError (data problem → retry cũng không giúp được)
    - neo4j_id rỗng (logic problem)
    """
    node_id = str(record.get("personnel_id") or record.get("org_id") or "?")

    for attempt in range(max_retries):
        try:
            return _process_one_inner(record, node_type)

        except Exception as exc:
            err_str = str(exc).lower()
            is_rate_limit = (
                "ratelimit" in err_str
                or "rate_limit" in err_str
                or "429" in err_str
                or "too many requests" in err_str
                or "timeout" in err_str
            )
            is_final_attempt = (attempt == max_retries - 1)

            if is_rate_limit and not is_final_attempt:
                wait_secs = 2 ** attempt   # 1s → 2s → 4s
                print(
                    f"    [RETRY {attempt + 1}/{max_retries}] "
                    f"Rate limit / timeout — chờ {wait_secs}s rồi thử lại..."
                )
                time.sleep(wait_secs)
                continue

            # Lỗi không retry được, hoặc hết lượt retry
            return {
                "status": "fail",
                "id":     node_id,
                "chunks": 0,
                "error":  f"[attempt {attempt + 1}] {exc}",
            }

    # Không bao giờ chạy đến đây nhưng type checker cần
    return {"status": "fail", "id": node_id, "chunks": 0, "error": "max retries exceeded"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview text serialize, khong goi LLM",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Chi xu ly N records dau (0 = tat ca)",
    )
    parser.add_argument(
        "--type",
        choices=["personnel", "org", "all"],
        default="all",
        help="Loc loai record",
    )
    args = parser.parse_args()

    # Luon resolve tuong doi voi project root, khong phu thuoc working directory
    fast_track = Path(__file__).parent.parent / "fast_track"
    json_files = sorted(
        f for f in fast_track.glob("*.json")
        if "test" not in f.name.lower()
    )

    results: list[dict[str, Any]] = []
    count = 0

    for fpath in json_files:
        data    = json.loads(fpath.read_text(encoding="utf-8"))
        _, records = detect_type(data)

        for record in records:
            rec_type = "personnel" if "personnel_id" in record else "org"
            if rec_type not in {"personnel", "org"}:
                continue
            if args.type != "all" and args.type != rec_type:
                continue
            if args.limit and count >= args.limit:
                break

            rec_id = record.get("personnel_id") or record.get("org_id")
            print(f"[{count + 1}] {fpath.name} -> {rec_type} {rec_id}")

            result = process_one(record, rec_type, dry_run=args.dry_run)
            results.append(result)
            count += 1

            icon   = {"ok": "OK", "fail": "FAIL", "dry": "DRY"}.get(result["status"], "?")
            suffix = f" - {result.get('error', '')}" if result["status"] == "fail" else ""
            print(f"    [{icon}] {result['status']}{suffix}")

        if args.limit and count >= args.limit:
            break

    ok   = sum(1 for r in results if r["status"] == "ok")
    fail = sum(1 for r in results if r["status"] == "fail")
    dry  = sum(1 for r in results if r["status"] == "dry")

    print("\n" + "-" * 50)
    dry_text = f" | DRY {dry}" if dry else ""
    print(f"Tong: {len(results)} | OK {ok} | FAIL {fail}{dry_text}")

    if fail:
        print("\nFailed records:")
        for r in results:
            if r["status"] == "fail":
                print(f"  {r['id']}: {r.get('error', '')}")
        sys.exit(1)


if __name__ == "__main__":
    main()