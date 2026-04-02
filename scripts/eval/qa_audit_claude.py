"""
qa_audit_claude.py
──────────────────────────────────────────────────────────────────────────────
Pipeline: Draft JSON  +  CV PDF  →  Claude QA Audit  →  Corrected JSON
──────────────────────────────────────────────────────────────────────────────
Chạy:  python scripts/eval/qa_audit_claude.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF  →  pip install pymupdf
from anthropic import Anthropic, APIStatusError, APITimeoutError
from anthropic.types import TextBlock
from dotenv import load_dotenv

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
load_dotenv()

DRAFT_JSON_PATH   = Path("data_eval/ground_truth_draft.json")
PDF_DIR           = Path("data_eval/cv_synthetic")
OUTPUT_JSON_PATH  = Path("data_eval/ground_truth_corrected.json")
LOG_PATH          = Path("data_eval/qa_audit.log")

MODEL             = "claude-sonnet-4-6"
MAX_TOKENS        = 4096
RETRY_LIMIT       = 3
RETRY_DELAY_SEC   = 5       # giây chờ giữa các lần retry
INTER_REQUEST_SEC = 1.5     # throttle nhẹ giữa các record

# ──────────────────────────────────────────────────────────────────────────────
# System Prompt
# ──────────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Bạn là một Senior Data QA Engineer và Chuyên gia Kiểm toán Dữ liệu (Data Auditor).
Nhiệm vụ: nhận một bản nháp JSON và văn bản CV gốc, rà soát và sửa lỗi để bản JSON cuối cùng:
  - KHÔNG bịa đặt (Zero Hallucination) — mọi thông tin phải có trong CV gốc.
  - Tuân thủ nghiêm ngặt Ontology và Normalization Rules bên dưới.

<ONTOLOGY_SCHEMA>
Root Level: personnel_id, org_id, public_data, private_data.

public_data:
  - full_name (string), professional_summary (string), is_available (boolean).
  - skills, certificates, cultural_tags: List[str].
  - education: List[{ degree: "BACHELOR"|"MASTER"|"PHD"|"OTHER", major, school, year }].
  - experience: List[{ organization_name, project_name, role, tech_stack: List[str] }].

private_data:
  - contact: { email, phone, github, linkedin }  (chỉ 4 key này).
  - salary_expectation (string), project_technical_secrets (string).
  - interview_questions_history: List[{ question, answer, org }].
  - blacklist_orgs, evidence_links: List[str].
  - additional_information: List[{ "key": "...", "value": "..." }].
</ONTOLOGY_SCHEMA>

<NORMALIZATION_RULES>
1. skills / tech_stack: bắt buộc lowercase. Alias:
   reactjs/react.js → react | vuejs/vue.js → vue | nodejs/node js → node.js
   postgresql → postgres | k8s → kubernetes | tf → terraform
   js → javascript | ts → typescript | py → python | golang → go
   springboot/spring-boot → spring boot | aws lambda → aws | gcp → google cloud

2. education.degree:
   kỹ sư / ky su / cử nhân / cu nhan / bachelor → BACHELOR
   thạc sĩ / thac si / master → MASTER
   tiến sĩ / tien si / phd → PHD
   khác → OTHER

3. is_available: true nếu CV chứa "open for offers", "available", "immediate",
   "đang tìm việc". Ngược lại false.

5. additional_information: Loại bỏ bất kỳ thông tin định danh cá nhân nhạy cảm nào
   không phù hợp với hồ sơ tuyển dụng, bao gồm: số CMND/CCCD/passport, nhóm máu,
   tình trạng hôn nhân, tôn giáo, dân tộc. Chỉ giữ thông tin nghề nghiệp hợp lệ.
</NORMALIZATION_RULES>

TRẢ VỀ DUY NHẤT MỘT KHỐI JSON HỢP LỆ BỌC TRONG ```json ```.
Không giải thích. Không thêm text nào bên ngoài khối JSON."""


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def log(msg: str, level: str = "INFO") -> None:
    """In ra stdout và ghi vào log file."""
    prefix = {"INFO": "ℹ️ ", "OK": "✅", "WARN": "⚠️ ", "ERR": "❌"}.get(level, "")
    line = f"[{level}] {msg}"
    print(f"{prefix} {msg}")
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Đọc text từ PDF bằng PyMuPDF."""
    try:
        doc = fitz.open(str(pdf_path))
        pages: list[str] = [str(page.get_text("text")) for page in doc]
        return "\n".join(pages).strip()
    except Exception as exc:
        log(f"Không đọc được PDF {pdf_path.name}: {exc}", "ERR")
        return ""


def extract_json_from_response(text: str) -> dict[str, Any] | None:
    """Bóc tách JSON từ response của Claude (xử lý cả khi thiếu backtick)."""
    # Thử khối ```json ... ```
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        raw = match.group(1)
    else:
        # Fallback: tìm cặp ngoặc nhọn ngoài cùng
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        raw = match.group(1) if match else text

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        log(f"JSON parse error: {exc}", "ERR")
        return None


def build_user_message(draft: dict[str, Any], cv_text: str) -> str:
    return (
        f"<OPENAI_DRAFT_JSON>\n{json.dumps(draft, ensure_ascii=False, indent=2)}\n</OPENAI_DRAFT_JSON>\n\n"
        f"<RAW_DOCUMENT>\n{cv_text}\n</RAW_DOCUMENT>\n\n"
        "Hãy rà soát bản nháp trên theo đúng schema và normalization rules. "
        "Trả về một khối JSON đã được kiểm toán và sửa lỗi."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Core: gọi Claude với retry
# ──────────────────────────────────────────────────────────────────────────────

def audit_with_claude(
    client: Anthropic,
    draft: dict[str, Any],
    cv_text: str,
    personnel_id: str,
) -> dict[str, Any] | None:
    """Gửi draft + CV text lên Claude, nhận JSON đã được kiểm toán."""
    user_msg = build_user_message(draft, cv_text)

    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            log(f"  [{personnel_id}] Claude call (attempt {attempt}/{RETRY_LIMIT})…")
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            # Chỉ TextBlock mới có attribute .text — filter bỏ ThinkingBlock, ToolUseBlock, v.v.
            text_blocks = [b.text for b in response.content if isinstance(b, TextBlock)]
            if not text_blocks:
                log(f"  [{personnel_id}] Response không chứa TextBlock, retry…", "WARN")
                continue
            raw_text = "\n".join(text_blocks)
            result = extract_json_from_response(raw_text)
            if result:
                return result
            log(f"  [{personnel_id}] Không bóc được JSON từ response, retry…", "WARN")

        except (APIStatusError, APITimeoutError) as exc:
            log(f"  [{personnel_id}] API error: {exc}", "WARN")

        if attempt < RETRY_LIMIT:
            time.sleep(RETRY_DELAY_SEC)

    log(f"[{personnel_id}] Thất bại sau {RETRY_LIMIT} lần thử.", "ERR")
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ──────────────────────────────────────────────────────────────────────────────

def _slugify(s: str) -> str:
    """Bỏ ký tự đặc biệt, lowercase — dùng để so khớp linh hoạt."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def find_pdf(personnel_id: str, pdf_filename: str | None = None) -> Path | None:
    """
    Tìm PDF theo thứ tự ưu tiên:
      0. Exact filename match từ trường "file" trong draft  ← ưu tiên cao nhất
      1. Exact substring: "P_060"  in  "CV_P060_..."
      2. Slug match:      "p060"   in  "cvp060..."   (bỏ ký tự đặc biệt)
      3. Digits-only:     "060"    in  stem
    """
    if not PDF_DIR.exists():
        return None

    # Strategy 0: khớp chính xác theo tên file từ draft["file"]
    if pdf_filename:
        exact = PDF_DIR / pdf_filename
        if exact.exists():
            return exact
        # Thử case-insensitive trên Windows/Linux
        fname_lower = pdf_filename.lower()
        for pdf in PDF_DIR.glob("*.pdf"):
            if pdf.name.lower() == fname_lower:
                return pdf

    # Strategy 1-3: fuzzy match theo personnel_id
    pid_lower  = personnel_id.lower()
    pid_slug   = _slugify(personnel_id)
    pid_digits = re.sub(r"\D", "", personnel_id)

    for pdf in sorted(PDF_DIR.glob("*.pdf")):
        stem_lower = pdf.stem.lower()
        stem_slug  = _slugify(pdf.stem)

        if pid_lower  in stem_lower:              return pdf  # strategy 1
        if pid_slug   in stem_slug:               return pdf  # strategy 2
        if pid_digits and pid_digits in stem_lower: return pdf  # strategy 3

    return None


def run_pipeline() -> None:
    # ── Kiểm tra cấu hình ─────────────────────────────────────────────────────
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        log("ANTHROPIC_API_KEY chưa được set trong .env", "ERR")
        sys.exit(1)

    if not DRAFT_JSON_PATH.exists():
        log(f"Không tìm thấy file draft: {DRAFT_JSON_PATH}", "ERR")
        sys.exit(1)

    # ── Load draft ─────────────────────────────────────────────────────────────
    with DRAFT_JSON_PATH.open(encoding="utf-8") as f:
        drafts_raw = json.load(f)

    # Chấp nhận cả list và dict đơn lẻ
    drafts: list[dict] = drafts_raw if isinstance(drafts_raw, list) else [drafts_raw]
    log(f"Loaded {len(drafts)} record(s) từ {DRAFT_JSON_PATH}")

    # ── Diagnostic: in cấu trúc record đầu tiên để debug key mismatch ─────────
    if drafts:
        sample = drafts[0]
        log(f"  Sample keys (record[0]): {list(sample.keys())}")
        pid_sample = sample.get("personnel_id") or sample.get("org_id")
        log(f"  personnel_id / org_id của record[0]: {pid_sample!r}")

    # ── Diagnostic: liệt kê PDF files đang có ─────────────────────────────────
    if PDF_DIR.exists():
        pdf_files = sorted(PDF_DIR.glob("*.pdf"))
        log(f"  PDF files trong {PDF_DIR} ({len(pdf_files)} files):")
        for p in pdf_files[:5]:
            log(f"    • {p.name}")
        if len(pdf_files) > 5:
            log(f"    … và {len(pdf_files) - 5} file nữa")
    else:
        log(f"  ⚠ Thư mục PDF không tồn tại: {PDF_DIR}", "WARN")

    client = Anthropic(api_key=api_key)
    corrected: list[dict[str, Any]] = []
    stats = {"ok": 0, "missing_pdf": 0, "failed": 0}

    for i, draft in enumerate(drafts, start=1):
        # ── Resolve định danh theo thứ tự ưu tiên ────────────────────────────
        # 1. personnel_id / org_id (schema chuẩn)
        # 2. "file" field → dùng làm tên PDF trực tiếp
        # 3. Fallback record_N
        pid = (
            draft.get("personnel_id")
            or draft.get("org_id")
            or f"record_{i}"
        )
        # Lấy tên file PDF nếu có — ưu tiên hơn pid khi tìm file
        pdf_filename: str | None = draft.get("file")   # VD: "CV_Vo_Hoang_Yen.pdf"

        log(f"\n{'─'*60}")
        log(f"[{i}/{len(drafts)}] Xử lý: {pid}  (file={pdf_filename!r})")

        # ── Tìm PDF ───────────────────────────────────────────────────────────
        pdf_path = find_pdf(pid, pdf_filename)
        if pdf_path is None:
            hint = pdf_filename or pid
            log(f"  Không tìm thấy PDF '{hint}' trong {PDF_DIR}", "WARN")
            corrected.append(draft)
            stats["missing_pdf"] += 1
            continue

        log(f"  PDF: {pdf_path.name}")
        cv_text = extract_text_from_pdf(pdf_path)
        if not cv_text:
            log(f"  PDF rỗng hoặc lỗi → giữ nguyên draft.", "WARN")
            corrected.append(draft)
            stats["missing_pdf"] += 1
            continue

        # ── Gọi Claude ────────────────────────────────────────────────────────
        result = audit_with_claude(client, draft, cv_text, pid)
        if result:
            corrected.append(result)
            stats["ok"] += 1
            log(f"  [{pid}] Kiểm toán thành công.", "OK")
        else:
            corrected.append(draft)   # fallback: giữ bản nháp gốc
            stats["failed"] += 1
            log(f"  [{pid}] Dùng bản nháp gốc do Claude thất bại.", "WARN")

        # Throttle để tránh rate-limit
        if i < len(drafts):
            time.sleep(INTER_REQUEST_SEC)

    # ── Ghi output ────────────────────────────────────────────────────────────
    OUTPUT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_JSON_PATH.open("w", encoding="utf-8") as f:
        output = corrected if len(corrected) > 1 else corrected[0]
        json.dump(output, f, ensure_ascii=False, indent=2)

    log(f"\n{'═'*60}")
    log(f"Hoàn tất pipeline.")
    log(f"  ✅ Thành công : {stats['ok']}")
    log(f"  ⚠️  Thiếu PDF  : {stats['missing_pdf']}")
    log(f"  ❌ Thất bại   : {stats['failed']}")
    log(f"Output → {OUTPUT_JSON_PATH}", "OK")
    log(f"Log    → {LOG_PATH}", "OK")


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    run_pipeline()