"""
Bước 4 – Data Architect One-Pass Classification (LLM Routing & Fallback).
Kiến trúc: "Một Node - Hai Ngăn" (Split-Ingestion).
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Dict, List, Optional, Union, Any, cast

from cerebras.cloud.sdk import Cerebras
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError
from typing import Any, Dict, List, Optional, Union
from pydantic import field_validator
from pipeline.config import settings, get_logger

logger = get_logger(__name__)

# ============================================================================
# Pydantic Schema: Personnel
# ============================================================================
class PersonnelPublicData(BaseModel):
    full_name: Optional[str] = Field(default=None)
    professional_summary: Optional[str] = Field(default=None)
    education: List[Dict[str, Any]] = Field(default_factory=list)
    certificates: List[str] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    experience: List[Dict[str, Any]] = Field(default_factory=list)
    availability: Optional[str] = Field(default=None)
    cultural_tags: List[str] = Field(default_factory=list)

class PersonnelPrivateData(BaseModel):
    contact: Optional[Dict[str, str]] = Field(default=None)
    salary_expectation: Optional[Union[str, int]] = Field(default=None)
    project_technical_secrets: Optional[str] = Field(default=None)
    interview_questions_history: List[Dict[str, Any]] = Field(default_factory=list)
    blacklist_orgs: List[str] = Field(default_factory=list)
    evidence_links: List[str] = Field(default_factory=list)
    # Chấp nhận cả Dict, List, hoặc Any
    additional_information: Optional[Union[Dict[str, Any], List[Dict[str, Any]], Any]] = Field(default_factory=dict)
    # Ép kiểu
    @field_validator("additional_information", mode="before")
    @classmethod
    def convert_llm_list_to_dict(cls, v: Any) -> dict:
        if isinstance(v, dict):
            return v
        if isinstance(v, list):
            result = {}
            for item in v:
                if isinstance(item, dict):
                    k = item.get("key") or item.get("name")
                    val = item.get("value") or item.get("val")
                    if k:
                        result[str(k)] = val
            return result
        return {}

class PersonnelSchema(BaseModel):
    personnel_id: Optional[str] = Field(default=None)
    public_data: Optional[PersonnelPublicData] = Field(default_factory=PersonnelPublicData)
    private_data: Optional[PersonnelPrivateData] = Field(default_factory=PersonnelPrivateData)

# ============================================================================
# Pydantic Schema: Organization
# ============================================================================
class OrgPublicData(BaseModel):
    org_name: str = Field(default="")
    industry: str = Field(default="")
    brief_description: str = Field(default="")
    active_jds: List[Dict[str, Any]] = Field(default_factory=list)

class OrgPrivateData(BaseModel):
    core_techstack_detail: Dict[str, str] = Field(default_factory=dict)
    internal_project_pain_points: str = Field(default="")
    target_candidate_dna: str = Field(default="")
    client_list: List[str] = Field(default_factory=list)

class OrganizationSchema(BaseModel):
    org_id: str = Field(default_factory=lambda: f"ORG_{uuid.uuid4().hex[:8]}")
    public_data: OrgPublicData = Field(default_factory=OrgPublicData)
    private_data: OrgPrivateData = Field(default_factory=OrgPrivateData)

# ============================================================================
# System Prompt - Data Architect
# ============================================================================
_SYSTEM_PROMPT = """\
CRITICAL: YOUR ENTIRE RESPONSE MUST BE A SINGLE RAW JSON OBJECT.
START WITH {{ AND END WITH }}. NO TEXT BEFORE OR AFTER. NO MARKDOWN.

Bạn là một Data Architect & Senior HR Mapping Expert trong hệ thống Digital Twin Recruitment.
Nhiệm vụ của bạn là đọc dữ liệu thô từ một file (CV hoặc tài liệu công ty) rồi trích xuất
thành DUY NHẤT một JSON object phẳng theo cấu trúc MỘT NODE - HAI NGĂN:

1. NGĂN CÔNG KHAI (public_data): Tên, kỹ năng, kinh nghiệm chung, JD...
2. NGĂN BÍ MẬT (private_data): Email, SĐT, mức lương, secret code, IP dự án,
     lịch sử phỏng vấn thực tế, blacklist.

Quy trình:
Bước 1: Nhận diện nội dung là Personnel (CV) hay Organization (SOP/JD).
Bước 2: Trích xuất vào JSON tương ứng.
    - Personnel -> root fields: personnel_id (nếu có), public_data, private_data.
    - Organization -> root fields: org_id (nếu có), public_data, private_data.

Quy tắc bắt buộc:
- Email, SĐT, mức lương cụ thể, secret kỹ thuật -> PHẢI vào private_data.
- HÌNH THỨC NARRATIVE CV/KHÔNG TIÊU ĐỀ: Đọc sâu từng câu văn (kể cả văn xuôi/prose) để tìm metadata. Email, SĐT, mức lương thường ẩn sát trong nội dung giới thiệu bản thân.
- RANH GIỚI BẢO MẬT (BOUNDARY): Mọi contact info, mức lương, secret code MẶC ĐỊNH LÀ BÍ MẬT (private_data) cho dù chúng nằm công khai giữa một đoạn giới thiệu chung.
- CHỐNG ẢO GIÁC (ANTI-HALLUCINATION): TUYỆT ĐỐI KHÔNG BỊA ĐẶT (hallucinate). Nếu văn bản gốc không đề cập, phải để rỗng/omit chứ không suy diễn.
- Thông tin không khớp schema có sẵn -> nhóm vào private_data.additional_information.
- Trường thiếu dữ liệu -> chuỗi rỗng "", mảng rỗng [], hoặc object rỗng {}.
- Tên công nghệ/kỹ năng PHẢI chuẩn hóa lowercase và nhất quán:
        "react" (không phải "ReactJS"), "python" (không phải "Python"),
        "node.js" (không phải "NodeJS"), "kubernetes" (không phải "K8s").
- is_available: TRUE nếu có tín hiệu như "Open for Offers", "Đang tìm việc", "Available".
    FALSE nếu không có tín hiệu rõ ràng.
- year trong education: chỉ lấy số nguyên 4 chữ số, null nếu không xác định.
- Tên các trường trong private_data PHẢI CHÍNH XÁC là:
    interview_questions_history, blacklist_orgs, salary_expectation,
    contact, evidence_links, project_technical_secrets, additional_information.
    Không được đặt tên khác hay viết tắt.

CRITICAL: YOUR ENTIRE RESPONSE MUST BE A SINGLE RAW JSON OBJECT.
START WITH {{ AND END WITH }}. NO TEXT BEFORE OR AFTER. NO MARKDOWN. NO EXPLANATIONS.
"""

# ── Tầng 1: Anchor patterns ──────────────────────────────────────────────────
# Các field này có pattern regex rõ ràng → không cần LLM, không hallucinate.

_ANCHOR_PATTERNS: dict[str, list[str]] = {
    "_id": [
        r"(?:^|\n)\s*(?:ID|personnel_id|org_id|Mã số)\s*[:\-]\s*([A-Z_0-9]{3,20})",
    ],
    "email": [
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    ],
    "phone": [
        r"(?:^|\s|:)(\+?84[-\s]?|0)([3-9]\d{8})\b",
    ],
    "github": [
        r"https?://(?:github|gitlab)\.com/[A-Za-z0-9\-_./]+",
    ],
    "linkedin": [
        r"https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9\-_/]+",
    ],
    "availability": [
        r"(?:^|\n)[✔✓☑]\s*(Open for Offers|Immediate|[0-9]_month_notice)",
        r"(?:availability|trạng thái)\s*[:\-]\s*([^\n]{3,40})",
    ],
    "evidence_links": [
        r"https?://(?!(?:github|gitlab|linkedin)\.com)[A-Za-z0-9\-_./?=&#%+]+",
    ],
    "salary_raw": [
        r"(?:USD|VND|VNĐ|đồng)?\s*[\d,\.]+\s*(?:USD|VND|VNĐ|đồng|tháng|/month)?",
    ],
}


def _extract_anchors(text: str) -> dict[str, Any]:
    """
    Tầng 1: regex-based extraction.
    Không bao giờ raise. Không gọi LLM.
    """
    anchors: dict[str, Any] = {}

    # ID
    for pattern in _ANCHOR_PATTERNS["_id"]:
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if m:
            anchors["_id"] = m.group(1).strip()
            break

    # Email
    emails = re.findall(_ANCHOR_PATTERNS["email"][0], text, re.IGNORECASE)
    if emails:
        anchors["email"] = emails[0]

    # Phone — normalize về 0xxxxxxxxx
    for pattern in _ANCHOR_PATTERNS["phone"]:
        m = re.search(pattern, text)
        if m:
            digits = re.sub(r"\D", "", m.group(0))
            if digits.startswith("84"):
                digits = "0" + digits[2:]
            if len(digits) == 10:          # chỉ lấy số hợp lệ
                anchors["phone"] = digits
            break

    # GitHub / GitLab
    gh = re.findall(_ANCHOR_PATTERNS["github"][0], text, re.IGNORECASE)
    if gh:
        anchors["github"] = gh[0].rstrip("/.,")

    # LinkedIn
    li = re.findall(_ANCHOR_PATTERNS["linkedin"][0], text, re.IGNORECASE)
    if li:
        anchors["linkedin"] = li[0].rstrip("/.,")

    # Availability
    for pattern in _ANCHOR_PATTERNS["availability"]:
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if m:
            anchors["availability"] = m.group(1).strip()
            break

    # Evidence links — loại trừ github/linkedin đã capture
    known = {anchors.get("github", ""), anchors.get("linkedin", "")}
    all_links = re.findall(_ANCHOR_PATTERNS["evidence_links"][0], text, re.IGNORECASE)
    evidence = [l.rstrip("/.,") for l in all_links
                if l not in known and len(l) > 15]
    if evidence:
        anchors["evidence_links"] = list(dict.fromkeys(evidence))

    logger.debug(f"[Tầng 1] Anchors: {list(anchors.keys())}")
    return anchors


# ── Tầng 2: JSON Schema cho OpenAI Structured Outputs ───────────────────────
# strict=True → constrained decoding tại API level.
# QUAN TRỌNG: Với strict=True, "additionalProperties" BẮT BUỘC phải là False ở mọi nơi!
# Để chứa dữ liệu động (additional_information), ta dùng mảng các object {"key": ..., "value": ...}

_OPENAI_RESPONSE_FORMAT: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "recruitment_node",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "personnel_id": {"type": ["string", "null"]},
                "org_id":       {"type": ["string", "null"]},
                "public_data": {
                    "type": "object",
                    "properties": {
                        "full_name":            {"type": "string"},
                        "professional_summary": {"type": "string"},
                        "is_available":         {"type": "boolean"},
                        "skills":         {"type": "array", "items": {"type": "string"}},
                        "certificates":   {"type": "array", "items": {"type": "string"}},
                        "cultural_tags":  {"type": "array", "items": {"type": "string"}},
                        "education": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "degree": {
                                        "type": "string",
                                        "enum": ["BACHELOR", "MASTER", "PHD", "OTHER"],
                                    },
                                    "major":  {"type": "string"},
                                    "school": {"type": "string"},
                                    "year":   {"type": ["integer", "null"]},
                                },
                                "required": ["degree", "major", "school", "year"],
                                "additionalProperties": False,
                            },
                        },
                        "experience": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "organization_name": {"type": ["string", "null"]},
                                    "project_name": {"type": "string"},
                                    "role":         {"type": "string"},
                                    "tech_stack": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": ["organization_name", "project_name", "role", "tech_stack"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    # Ép False để tuân thủ strict=True của OpenAI
                    "additionalProperties": False,
                    "required": [
                        "full_name", "professional_summary", "is_available",
                        "skills", "certificates", "cultural_tags",
                        "education", "experience",
                    ],
                },
                "private_data": {
                    "type": "object",
                    "properties": {
                        "contact": {
                            "type": "object",
                            "properties": {
                                "email":    {"type": "string"},
                                "phone":    {"type": "string"},
                                "github":   {"type": "string"},
                                "linkedin": {"type": "string"},
                            },
                            "required": ["email", "phone", "github", "linkedin"],
                            "additionalProperties": False,
                        },
                        "salary_expectation":        {"type": "string"},
                        "project_technical_secrets": {"type": "string"},
                        "interview_questions_history": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "question": {"type": "string"},
                                    "answer":   {"type": "string"},
                                    "org":      {"type": "string"},
                                },
                                "required": ["question", "answer", "org"],
                                "additionalProperties": False,
                            },
                        },
                        "blacklist_orgs":  {"type": "array", "items": {"type": "string"}},
                        "evidence_links":  {"type": "array", "items": {"type": "string"}},

                        # TÚI BA GANG DẠNG KEY-VALUE (Chuẩn OpenAI Strict)
                        "additional_information": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "key": {"type": "string", "description": "Tên trường thông tin (VD: Sở thích, Tôn giáo, Nhóm máu)"},
                                    "value": {"type": "string", "description": "Giá trị tương ứng"}
                                },
                                "required": ["key", "value"],
                                "additionalProperties": False
                            }
                        },
                    },
                    "required": [
                        "contact", "salary_expectation", "project_technical_secrets",
                        "interview_questions_history", "blacklist_orgs",
                        "evidence_links", "additional_information",
                    ],
                    "additionalProperties": False,
                },
            },
            "required": ["personnel_id", "org_id", "public_data", "private_data"],
            "additionalProperties": False,
        },
    },
}
# Fallback cho Cerebras (chưa support json_schema, chỉ support json_object)
_CEREBRAS_RESPONSE_FORMAT: dict = {"type": "json_object"}

_USER_PROMPT_TEMPLATE = """\
ĐOẠN VĂN BẢN (từ file: {file_hint}):
\"\"\"
{chunk_text}
\"\"\"

Yêu cầu: {role_instruction}

Phân tích theo tư duy Data Architect, tách rõ ràng Public & Private theo Schema.
Chỉ xuất ra JSON phẳng ở root với các trường liên quan (public_data, private_data,
personnel_id/org_id nếu có).
"""

def _cerebras_client() -> Cerebras:
    return Cerebras(api_key=settings.CEREBRAS_API_KEY)

def _openai_client() -> OpenAI:
    return OpenAI(api_key=settings.OPENAI_API_KEY)

def _normalize_target_role(target_role: Optional[str]) -> str:
    role = str(target_role or "").strip().upper()
    return "ORGANIZATION" if role == "ORGANIZATION" else "PERSONNEL"


def _build_role_instruction(target_role: Optional[str]) -> str:
    role = str(target_role or "").strip().upper()
    if role == "ORGANIZATION":
        return (
            "BẮT BUỘC: Trả về dữ liệu theo role ORGANIZATION. "
            "Không đổi role, không tự chuyển sang PERSONNEL."
        )
    if role == "PERSONNEL":
        return (
            "BẮT BUỘC: Trả về dữ liệu theo role PERSONNEL. "
            "Không đổi role, không tự chuyển sang ORGANIZATION."
        )
    return "Ưu tiên tự nhận diện role phù hợp từ nội dung tài liệu."


def _build_user_prompt(chunk_text: str, file_hint: str, target_role: Optional[str]) -> str:
    return _USER_PROMPT_TEMPLATE.format(
        file_hint=file_hint,
        chunk_text=chunk_text,
        role_instruction=_build_role_instruction(target_role),
    )


def _extract_content_from_response(response: Any) -> str:
    """Read first message content from ChatCompletion-like responses safely."""
    if response is None:
        return ""

    choices = cast(Any, getattr(response, "choices", None))
    if not choices:
        return ""

    first_choice = choices[0]
    message = cast(Any, getattr(first_choice, "message", None))
    if message is None:
        return ""

    content = cast(Any, getattr(message, "content", None))
    return str(content) if content is not None else ""

def _call_llm(text: str, file_hint: str = "") -> str:
    """
    Tầng 2: Gọi LLM với JSON Schema enforcement.
    - OpenAI (nếu có key): dùng response_format json_schema strict
      → không cần completion prefix, không cần parse phức tạp
    - Cerebras (fallback): dùng json_object + completion prefix {
    """
    from pipeline.config import get_extraction_client  # import lazy để tránh circular

    client, model, provider = get_extraction_client()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": _USER_PROMPT_TEMPLATE.format(
            file_hint=file_hint,
            chunk_text=text,
            role_instruction=(
                "Nhận diện loại tài liệu (Personnel/Organization) "
                "và trích xuất toàn bộ thông tin theo schema."
            ),
        )},
    ]

    if provider == "openai":
        # ── OpenAI: Structured Outputs ──────────────────────────────────
        # Không dùng completion prefix { — API enforce schema trước khi decode
        response: Any = client.chat.completions.create(
            model=model,
            messages=cast(Any, messages),
            response_format=cast(Any, _OPENAI_RESPONSE_FORMAT),
            temperature=0,          # extraction cần deterministic
            max_tokens=4096,
        )
        raw = _extract_content_from_response(response)
        usage = getattr(response, "usage", None)
        total_tokens = getattr(usage, "total_tokens", None)
        logger.debug(f"[Tầng 2 / OpenAI] tokens_used={total_tokens}")

    else:
        # ── Cerebras fallback: json_object + completion prefix ───────────
        # Thêm { vào cuối user message để force JSON start (completion prefix technique)
        messages[-1]["content"] += "\n\nJSON OUTPUT:\n{"

        response: Any = client.chat.completions.create(
            model=model,
            messages=cast(Any, messages),
            response_format=cast(Any, _CEREBRAS_RESPONSE_FORMAT),
            temperature=0,
            max_tokens=4096,
        )
        raw = _extract_content_from_response(response)
        # Prepend lại { đã dùng làm prefix (chỉ khi chưa bắt đầu bằng {)
        raw = raw if raw.lstrip().startswith("{") else "{" + raw
        logger.debug(f"[Tầng 2 / Cerebras] raw_preview={raw[:120]!r}")

    logger.debug(f"[Tầng 2] provider={provider}, model={model}, "
                 f"response_len={len(raw)}")
    return raw


def _extract_pipeline(text: str, file_hint: str = "", raw_response: Optional[str] = None) -> dict:
    logger.debug(f"[extract] file={file_hint!r}, text_len={len(text)}")

    # ── Tầng 1 ──────────────────────────────────────────────────────────
    anchors = _extract_anchors(text)

    # ── Tầng 2 ──────────────────────────────────────────────────────────
    raw = raw_response if raw_response is not None else _call_llm(text, file_hint)

    # _clean_and_parse_json là safety net — với OpenAI structured output,
    # raw_response đã là valid JSON. Với Cerebras, cần parser 5 tầng.
    llm_result = _clean_and_parse_json(raw)

    # ── Tầng 3 ──────────────────────────────────────────────────────────
    final = _merge_and_validate(llm_result, anchors)

    logger.info(
        f"[extract] ✅ id={final.get('personnel_id') or final.get('org_id')!r}, "
        f"provider={'openai' if 'gpt' in str(final) else 'cerebras'}"
    )
    return final


def _clean_and_parse_json(text: str) -> Dict[str, Any]:
    """
    Bộ lọc JSON 5 tầng — bất bại trước LLM chatty output.
    Thứ tự: fast-path → markdown strip → bracket slice → stack scan → python-quirk fix.
    """
    import re

    # ── Tầng 1: fast path ─────────────────────────────────────────────────────
    # Phần lớn các lần gọi LLM tốt sẽ trả về JSON thuần, xử lý ngay tại đây.
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # ── Tầng 2: strip markdown fences ─────────────────────────────────────────
    # LLM hay bọc JSON trong ```json ... ``` hoặc ``` ... ```
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # ── Tầng 3: first-{  last-} slice ─────────────────────────────────────────
    # Cắt từ { đầu tiên đến } cuối cùng — nhanh, đủ cho 90% trường hợp.
    first = stripped.find("{")
    last  = stripped.rfind("}")
    if first != -1 and last > first:
        try:
            return json.loads(stripped[first : last + 1])
        except json.JSONDecodeError:
            pass

    # ── Tầng 4: stack-based bracket scan — O(n), an toàn với chuỗi dài ────────
    # Đếm ngoặc chính xác, bỏ qua { } nằm bên trong string literals.
    # Không dùng "shrink from right" (O(n²) — có thể treo nếu text dài).
    if first != -1:
        depth    = 0
        in_str   = False
        escaped  = False

        for i, ch in enumerate(stripped[first:], start=first):
            if escaped:
                escaped = False
                continue
            if ch == "\\" and in_str:
                escaped = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = stripped[first : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break   # ngoặc cân nhưng JSON vẫn lỗi → thử tầng 5

    # ── Tầng 5: Python-quirk repair ───────────────────────────────────────────
    # LLM đôi khi trả ra Python dict syntax thay vì JSON:
    # single quotes, trailing commas, True/False/None.
    if first != -1 and last > first:
        candidate = stripped[first : last + 1]
        try:
            import ast
            node = ast.literal_eval(candidate)
            if isinstance(node, dict):
                # Re-serialize qua json để chuẩn hóa, rồi parse lại
                return json.loads(json.dumps(node, ensure_ascii=False))
        except Exception:
            pass

    # ── Hết tầng — raise với context để log dễ debug ──────────────────────────
    preview = text[:200].replace("\n", " ")
    raise json.JSONDecodeError(
        f"Không tìm được JSON hợp lệ sau 5 tầng filter. Preview: {preview!r}",
        text, 0
    )


def _coerce_string_arrays(obj: Any, _depth: int = 0) -> Any:
    """
    Đệ quy qua dict/list, parse bất kỳ string nào trông giống JSON array/object.
    Giới hạn độ sâu 10 để tránh stack overflow với input bất thường.
    """
    if _depth > 10:
        return obj
    if isinstance(obj, dict):
        return {k: _coerce_string_arrays(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_coerce_string_arrays(item, _depth + 1) for item in obj]
    if isinstance(obj, str):
        stripped = obj.strip()
        if stripped.startswith(("[", "{")):
            try:
                parsed = json.loads(stripped)
                # Chỉ promote nếu kết quả là list hoặc dict — không promote scalar
                if isinstance(parsed, (list, dict)):
                    return parsed
            except json.JSONDecodeError:
                pass
    return obj


# Map: tên LLM hay đặt sai → tên chuẩn trong schema
_PRIVATE_DATA_FIELD_ALIASES: dict[str, str] = {
    # interview history variants
    "interview_history":          "interview_questions_history",
    "history_interview":          "interview_questions_history",
    "interviews_history":         "interview_questions_history",
    "interview_question_history": "interview_questions_history",
    # blacklist variants
    "blacklist":                  "blacklist_orgs",
    "blacklisted_orgs":           "blacklist_orgs",
    "blacklisted":                "blacklist_orgs",
    "black_list":                 "blacklist_orgs",
    # salary variants
    "salary":                     "salary_expectation",
    "expected_salary":            "salary_expectation",
    "salary_expect":              "salary_expectation",
    # contact variants
    "contacts":                   "contact",
    "contact_info":               "contact",
    # evidence variants
    "evidence":                   "evidence_links",
    "links":                      "evidence_links",
    "portfolio_links":            "evidence_links",
}


def _normalize_private_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Rename các field alias trong private_data về tên chuẩn của schema.
    Nếu field chuẩn đã tồn tại: merge (list) hoặc giữ nguyên (scalar), KHÔNG overwrite.
    Nếu chưa tồn tại: rename key.
    """
    private = data.get("private_data")
    if not isinstance(private, dict):
        return data

    normalized = dict(private)  # shallow copy để không mutate input

    for alias, canonical in _PRIVATE_DATA_FIELD_ALIASES.items():
        if alias not in normalized:
            continue
        alias_val = normalized.pop(alias)

        if canonical not in normalized:
            # Field chuẩn chưa có → đổi tên
            normalized[canonical] = alias_val
        else:
            # Field chuẩn đã có → merge nếu là list, giữ nguyên nếu scalar
            existing = normalized[canonical]
            if isinstance(existing, list) and isinstance(alias_val, list):
                # Dedup khi merge list of dicts (dùng str representation)
                seen = {str(item) for item in existing}
                merged = existing + [item for item in alias_val
                                     if str(item) not in seen]
                normalized[canonical] = merged
            # Nếu scalar: giữ nguyên existing, bỏ alias (đã pop ở trên)

    data["private_data"] = normalized
    return data


def _merge_and_validate(llm_result: dict, anchors: dict) -> dict:
    """
    Tầng 3: Anchor fields OVERRIDE LLM output.
    Regex không hallucinate → kết quả tầng 1 luôn đúng hơn LLM.
    """
    # ── ID ──────────────────────────────────────────────────────────────
    node_id = anchors.get("_id")
    if node_id:
        # Ưu tiên personnel_id nếu document là CV
        if llm_result.get("personnel_id") is not None:
            llm_result["personnel_id"] = node_id
        elif llm_result.get("org_id") is not None:
            llm_result["org_id"] = node_id
        else:
            # LLM không set cả hai → heuristic: nếu có public_data.experience → personnel
            if llm_result.get("public_data", {}).get("experience"):
                llm_result["personnel_id"] = node_id
            else:
                llm_result["org_id"] = node_id

    # ── Contact fields ───────────────────────────────────────────────────
    private = llm_result.setdefault("private_data", {})
    contact = private.setdefault("contact", {})

    for field in ("email", "phone", "github", "linkedin"):
        if field in anchors:
            contact[field] = anchors[field]

    # ── Availability ────────────────────────────────────────────────────
    if "availability" in anchors:
        llm_result.setdefault("public_data", {})["availability"] = \
            anchors["availability"]

    # ── Evidence links — union, dedup, anchor thêm vào không override ───
    if "evidence_links" in anchors:
        existing  = private.get("evidence_links", [])
        existing  = existing if isinstance(existing, list) else []
        merged    = list(dict.fromkeys(existing + anchors["evidence_links"]))
        private["evidence_links"] = merged

    # ── Coerce + normalize (từ patch 2) ─────────────────────────────────
    result = _coerce_string_arrays(llm_result)
    result = _normalize_private_data(result)

    logger.debug(
        f"[Tầng 3] id={result.get('personnel_id') or result.get('org_id')}, "
        f"anchors_applied={list(anchors.keys())}"
    )
    return result


def extract(text: str, file_hint: str = "") -> dict:
    """
    Pipeline 3 tầng:
      1. Deterministic regex  → anchor fields (id, email, phone, github, ...)
      2. LLM + JSON Schema    → structured extraction (experience, secrets, ...)
      3. Merge + validate     → anchor override, coerce, normalize
    """
    return _extract_pipeline(text, file_hint=file_hint)

def extract_knowledge(
    doc_text: str,
    file_hint: str = "CV_hoac_SOP",
    target_role: Optional[str] = None,
) -> Dict[str, Any]:
    """LLM trích xuất text ra payload phẳng rồi re-wrap theo schema nội bộ."""
    if len(doc_text.strip()) < 50:
        logger.warning(f"[DEBUG] Text đầu vào quá ngắn hoặc rỗng cho {file_hint}!")

    raw = _call_llm(doc_text, file_hint)
    logger.info(
        f"\n--- [DEBUG] RAW LLM OUTPUT FOR {file_hint} ---\n{raw}\n-----------------------------------------"
    )

    role = _normalize_target_role(target_role)
    parsed: Dict[str, Any] = {}
    try:
        parsed = _extract_pipeline(doc_text, file_hint=file_hint, raw_response=raw)

        parsed_role = str(parsed.get("record_type", "")).strip().upper()
        if target_role is None and parsed_role in {"PERSONNEL", "ORGANIZATION"}:
            role = parsed_role

        payload = parsed.get("data") if isinstance(parsed.get("data"), dict) else parsed
        if not isinstance(payload, dict):
            payload = {}

        if role == "ORGANIZATION":
            validated = OrganizationSchema(**payload)
        else:
            validated = PersonnelSchema(**payload)

        logger.info("Extract thành công: %s", role)
        return {"record_type": role, "data": validated.model_dump()}
    except json.JSONDecodeError as exc:
        logger.warning("JSONDecodeError khi parse output LLM (%s): %s", file_hint, exc)
        return {
            "record_type": role,
            "data": {
                "public_data": {},
                "private_data": {},
            },
        }
    except ValidationError as exc:
        logger.warning(f"ValidationError: {exc}")
        data = parsed if isinstance(parsed, dict) else {}
        return {"record_type": (target_role or role).upper(), "data": data}
    except Exception as exc:
        logger.warning("Parse error không xác định (%s): %s", file_hint, exc)
        return {
            "record_type": role,
            "data": {
                "public_data": {},
                "private_data": {},
            },
        }
