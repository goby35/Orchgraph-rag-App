"""
Bước 4 – Context-Aware One-Pass Knowledge Extraction (LLM Routing & Fallback).

Hỗ trợ 3 loại tài liệu: CV, SOP, PROJECT.
Chiến lược:
  1. Gọi **Cerebras API** (llama3.1-8b) làm chính — tốc độ nhanh, chi phí thấp.
  2. Nếu Cerebras timeout / lỗi → fallback sang **OpenAI API** (gpt-4o).

Kết quả trả về tuân theo Pydantic schema ``KnowledgeGraphExtraction``.
"""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Dict, List, Optional, Union

from cerebras.cloud.sdk import Cerebras
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from pipeline.config import settings, get_logger

logger = get_logger(__name__)

# ============================================================================
# Pydantic Schema
# ============================================================================

class DocType(str, Enum):
    """Loại tài liệu."""
    CV = "CV"
    SOP = "SOP"
    PROJECT = "PROJECT"


class TopicCategory(str, Enum):
    """Phân loại chủ đề chính của chunk."""
    # CV
    PERSONNEL = "PERSONNEL"
    EXPERIENCE = "EXPERIENCE"
    EDUCATION = "EDUCATION"
    SKILL = "SKILL"
    ACHIEVEMENT = "ACHIEVEMENT"
    # SOP
    PROCESS_FLOW = "PROCESS_FLOW"
    APPROVAL = "APPROVAL"
    CONDITION = "CONDITION"
    TOOL_USAGE = "TOOL_USAGE"
    COMPLIANCE = "COMPLIANCE"
    # PROJECT
    OBJECTIVE = "OBJECTIVE"
    PLANNING = "PLANNING"
    EXECUTION = "EXECUTION"
    RISK = "RISK"
    REPORTING = "REPORTING"
    # Legacy
    POLICY = "POLICY"
    PROJECT = "PROJECT"


class Entity(BaseModel):
    """Một thực thể được nhận diện."""
    name: str = Field(..., description="Tên thực thể")
    type: str = Field(
        ...,
        description=(
            "Loại thực thể — xem taxonomy chung + đặc thù theo doc_type"
        ),
    )


class Triplet(BaseModel):
    """Một quan hệ ba ngôi (subject – relation – object)."""
    subject: str = Field(..., description="Chủ thể — phải nằm trong entities")
    relation: str = Field(..., description="Quan hệ / hành động")
    object: str = Field(..., description="Đối tượng — phải nằm trong entities")


class KnowledgeGraphExtraction(BaseModel):
    """Schema đầu ra cho bước trích xuất tri thức."""
    doc_type: DocType = Field(default=DocType.CV)
    topic_category: TopicCategory
    entities: List[Entity] = Field(default_factory=list)
    triplets: List[Triplet] = Field(default_factory=list)


# ============================================================================
# System Prompt — Context-Aware (CV / SOP / PROJECT)
# ============================================================================

_SYSTEM_PROMPT = """\
Bạn là chuyên gia trích xuất Đồ thị Tri thức (Knowledge Graph) tiếng Việt, \
có khả năng xử lý 3 loại tài liệu doanh nghiệp: CV nhân sự, SOP quy trình, \
và Kế hoạch dự án.

Nhiệm vụ: Đọc đoạn văn bản → tự nhận diện loại tài liệu → áp dụng luật \
trích xuất tương ứng → trả về DUY NHẤT một JSON object hợp lệ.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BƯỚC 1 — NHẬN DIỆN LOẠI TÀI LIỆU (doc_type)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Nhìn vào CORE_ENTITY và nội dung đoạn văn để xác định:

  CV       — Tài liệu hồ sơ cá nhân. Dấu hiệu: tên người, kinh nghiệm
             làm việc, học vấn, kỹ năng, chứng chỉ cá nhân.
             CORE_ENTITY = Tên người (VD: "Nguyễn Hoài Tưởng")

  SOP      — Quy trình / Hướng dẫn vận hành. Dấu hiệu: bước thực hiện,
             điều kiện kích hoạt, người thực hiện, công cụ sử dụng,
             từ khoá "quy trình", "bước", "thực hiện", "phê duyệt".
             CORE_ENTITY = Tên quy trình (VD: "SOP-02 Phê duyệt Ngân sách")

  PROJECT  — Kế hoạch / Báo cáo dự án. Dấu hiệu: mục tiêu, milestone,
             ngân sách, rủi ro, KPI, từ khoá "dự án", "giai đoạn", "sprint".
             CORE_ENTITY = Tên dự án (VD: "NovaFlow ERP")

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BƯỚC 2A — ENTITY TAXONOMY CHUNG (áp dụng cho cả 3 loại)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  PERSON    — Tên người thật (Nguyễn Hoài Tưởng, Lê Văn Tám)
  ORG       — Công ty, phòng ban, trường học (TechVision JSC, Phòng Tài chính)
  ROLE      — Chức danh, vị trí (CEO, Project Manager, Trưởng phòng)
  TOOL      — Phần mềm, công nghệ, hệ thống (Odoo, Jira, Docker, Python)
  METRIC    — Chỉ số, con số đo lường (45%, $2M, 120 nhân sự, 30 ngày)
  TIME      — Mốc hoặc khoảng thời gian (Q1/2025, Tháng 03/2025, Sprint 2)
  CONCEPT   — Khái niệm trừu tượng (chuyển đổi số, văn hoá doanh nghiệp)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BƯỚC 2B — ENTITY TAXONOMY ĐẶC THÙ THEO LOẠI TÀI LIỆU
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  [Chỉ dùng cho CV]
    SKILL     — Kỹ năng, năng lực cá nhân (Lãnh đạo chiến lược, System Design)
    CERT      — Chứng chỉ, bằng cấp (AWS Certified, MBA, PMP)
    LANGUAGE  — Ngôn ngữ giao tiếp (Tiếng Anh, Tiếng Nhật)
    EVENT     — Sự kiện cá nhân hoặc nghề nghiệp (VietAI Summit, Series A)
    PRODUCT   — Sản phẩm/hệ thống đã xây dựng (SaaS platform, hệ thống ERP)

  [Chỉ dùng cho SOP]
    PROCESS   — Tên quy trình hoặc bước (Bước 1: Tiếp nhận yêu cầu, SOP-01)
    CONDITION — Điều kiện kích hoạt/phân nhánh (Nếu > 50 triệu, Nếu từ chối)
    DOCUMENT  — Biểu mẫu, hồ sơ (Form-01, Phiếu đề xuất, Hợp đồng)
    STANDARD  — Tiêu chuẩn, quy định (ISO 9001, Nghị định 47/2021)

  [Chỉ dùng cho PROJECT]
    MILESTONE — Cột mốc dự án (Go-live, UAT hoàn thành, Kick-off)
    RISK      — Rủi ro đã nhận diện (Rủi ro thiếu nhân lực, Rủi ro ngân sách)
    KPI       — Chỉ tiêu thành công (Uptime 99.9%, NPS > 70, MAU 10,000)
    PHASE     — Giai đoạn dự án (Giai đoạn 1: Phân tích, Sprint 3)
    BUDGET    — Ngân sách (Ngân sách Q1: 500 triệu, Dự phòng 10%)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BƯỚC 2C — RELATION VOCABULARY THEO LOẠI TÀI LIỆU
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Ưu tiên dùng đúng từ trong danh sách — KHÔNG tự đặt quan hệ tuỳ tiện.

  [CV — quan hệ về con người]
    làm việc tại | giữ chức vụ | làm việc từ | tốt nghiệp | học tại
    có kỹ năng | sử dụng | có chứng chỉ | nói được | đạt điểm
    phát triển | lãnh đạo | đạt thành tích | tham gia sự kiện

  [SOP — quan hệ về quy trình]
    bắt đầu bằng | tiếp theo là | kết thúc bằng | thực hiện bởi
    sử dụng công cụ | tạo ra tài liệu | yêu cầu phê duyệt từ
    kích hoạt khi | rẽ nhánh nếu | chuyển sang bước | áp dụng tiêu chuẩn
    có thời hạn | lưu trữ tại

  [PROJECT — quan hệ về dự án]
    có mục tiêu | bao gồm giai đoạn | đạt milestone | phân công cho
    sử dụng công nghệ | có ngân sách | có rủi ro | đo bằng KPI
    bắt đầu vào | kết thúc vào | phụ thuộc vào | báo cáo lên

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BƯỚC 3 — OUTPUT SCHEMA BẮT BUỘC
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  "doc_type": "CV" | "SOP" | "PROJECT",
  "topic_category": "<xem danh sách bên dưới>",
  "entities": [
    {"name": "<tên thực thể>", "type": "<từ taxonomy tương ứng doc_type>"}
  ],
  "triplets": [
    {"subject": "<name>", "relation": "<từ relation vocabulary>", "object": "<name>"}
  ]
}

  topic_category hợp lệ theo doc_type:
    CV      → PERSONNEL | EXPERIENCE | EDUCATION | SKILL | ACHIEVEMENT
    SOP     → PROCESS_FLOW | APPROVAL | CONDITION | TOOL_USAGE | COMPLIANCE
    PROJECT → OBJECTIVE | PLANNING | EXECUTION | RISK | REPORTING

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
QUY TẮC THÉP (áp dụng cho CẢ 3 LOẠI — vi phạm = output không hợp lệ)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

R1 — ĐỒNG NHẤT CHỦ THỂ LÕI:
  • CV:      Mọi đại từ (ông, bà, anh, hắn, người này, vị CEO) → thay bằng
             tên đầy đủ của CORE_ENTITY.
  • SOP:     Mọi "bước này", "quy trình trên" → thay bằng tên PROCESS/STEP cụ thể.
  • PROJECT: Mọi "dự án", "chương trình này" → thay bằng tên PROJECT cụ thể.
  • TUYỆT ĐỐI KHÔNG dùng đại từ hoặc động từ làm Subject trong triplet.

R2 — ENTITY TRƯỚC TRIPLET:
  • Mọi Subject và Object trong triplets PHẢI là .name của một entity
    trong danh sách entities của cùng chunk.
  • CORE_ENTITY phải được khai báo trong entities nếu xuất hiện trong triplet.

R3 — KHÔNG BỎ SÓT DANH SÁCH LIỆT KÊ:
  • CV:  kỹ năng / chứng chỉ / ngôn ngữ / công cụ → tạo triplet nối
         CORE_ENTITY với từng mục.
  • SOP: danh sách bước → tạo triplet "tiếp theo là" nối các bước tuần tự.
  • PROJECT: danh sách milestone / KPI / rủi ro → nối với CORE_ENTITY.

R4 — DÙNG ĐÚNG ENTITY TYPE THEO DOC_TYPE:
  • Không dùng SKILL/CERT/LANGUAGE cho SOP hoặc PROJECT.
  • Không dùng PROCESS/CONDITION/DOCUMENT cho CV hoặc PROJECT.
  • Không dùng MILESTONE/RISK/KPI/PHASE/BUDGET cho CV hoặc SOP.

R5 — FORMAT OUTPUT:
  • Trả về JSON thuần tuý — KHÔNG markdown ```json```, KHÔNG giải thích.
  • Empty fallback: {"doc_type":"CV","topic_category":"PERSONNEL","entities":[],"triplets":[]}
"""

_USER_PROMPT_TEMPLATE = """\
CORE_ENTITY: {core_entity}
(Đây là chủ thể lõi của đoạn văn — người/quy trình/dự án được nhắc đến nhiều nhất)

ĐOẠN VĂN CẦN PHÂN TÍCH:
\"\"\"
{chunk_text}
\"\"\"

Thực hiện theo 3 bước:
1. Xác định doc_type (CV / SOP / PROJECT) dựa vào CORE_ENTITY và nội dung.
2. Chọn Entity Taxonomy và Relation Vocabulary tương ứng.
3. Trả về JSON theo schema — tuân thủ 5 Quy tắc Thép.\
"""


# ============================================================================
# LLM Clients (lazy init)
# ============================================================================

def _cerebras_client() -> Cerebras:
    """Tạo Cerebras SDK client từ API key trong .env."""
    return Cerebras(api_key=settings.CEREBRAS_API_KEY)


def _openai_client() -> OpenAI:
    """Tạo OpenAI client."""
    return OpenAI(api_key=settings.OPENAI_API_KEY)


# ============================================================================
# Core extraction logic
# ============================================================================

def _build_user_prompt(chunk_text: str, core_entity: str) -> str:
    """Tạo User Prompt với core_entity và chunk_text."""
    return _USER_PROMPT_TEMPLATE.format(
        core_entity=core_entity,
        chunk_text=chunk_text,
    )


def _call_cerebras(
    chunk_text: str,
    core_entity: str,
    timeout: float = 30.0,
) -> str:
    """Gọi Cerebras API qua SDK và trả về raw content string."""
    client = _cerebras_client()
    response = client.chat.completions.create(
        model=settings.CEREBRAS_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(chunk_text, core_entity)},
        ],
        temperature=0,
        timeout=timeout,
    )
    return response.choices[0].message.content if response.choices else ""


def _call_openai(
    chunk_text: str,
    core_entity: str,
    timeout: float = 60.0,
) -> str:
    """Gọi OpenAI API và trả về raw content string."""
    client = _openai_client()
    response = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(chunk_text, core_entity)},
        ],
        temperature=0,
        timeout=timeout,
    )
    return response.choices[0].message.content or ""


def _parse_extraction_with_retry(
    raw: str,
    max_retries: int = 2,
) -> KnowledgeGraphExtraction:
    """Parse raw JSON string thành Pydantic model với retry logic.

    Args:
        raw: Raw response string từ LLM.
        max_retries: Số lần thử lại tối đa nếu JSON không hợp lệ.

    Returns:
        Parsed KnowledgeGraphExtraction object.

    Raises:
        ValueError: Nếu sau max_retries lần vẫn không parse được JSON hợp lệ.
    """
    for attempt in range(max_retries + 1):
        try:
            # Loại bỏ markdown code fences nếu LLM trả kèm
            cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
            cleaned = re.sub(r"\s*```$", "", cleaned).strip()

            # Tìm JSON object đầu tiên
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if not match:
                raise ValueError(
                    f"Không tìm thấy JSON object trong response: {raw[:300]}"
                )

            data = json.loads(match.group())
            result = KnowledgeGraphExtraction(**data)
            logger.info("Parse JSON thành công ở lần thứ %d.", attempt + 1)
            return result

        except (json.JSONDecodeError, ValueError, ValidationError) as exc:
            if attempt < max_retries:
                logger.warning(
                    "Lần thứ %d thất bại (%s). Thử lại…",
                    attempt + 1,
                    exc,
                )
            else:
                logger.error(
                    "Đã thử %d lần vẫn không parse được JSON: %s",
                    max_retries + 1,
                    exc,
                )
                raise ValueError(
                    f"Không thể parse JSON sau {max_retries + 1} lần: {exc}"
                ) from exc


# ============================================================================
# Post-processing: đảm bảo triplet subjects/objects tồn tại trong entities
# ============================================================================

def _validate_and_fix(
    result: KnowledgeGraphExtraction,
    core_entity: str,
) -> KnowledgeGraphExtraction:
    """Hậu xử lý đảm bảo chất lượng đồ thị:

    1. Thay thế literal "CORE_ENTITY" và đại từ bằng tên thật.
    2. Đảm bảo core_entity nằm trong entities.
    3. Đảm bảo mọi subject/object trong triplets đều có trong entities.
    4. Loại bỏ triplet rác (subject/object là cụm vô nghĩa).
    """
    # Các pattern LLM có thể trả về thay vì tên thật
    _PLACEHOLDER_PATTERNS = {
        "CORE_ENTITY", "core_entity",
        "ĐOẠN VĂN CẦN PHÂN TÍCH", "Đoạn văn cần phân tích",
    }

    # 1. Thay thế placeholder trong entities
    if core_entity:
        for entity in result.entities:
            if entity.name in _PLACEHOLDER_PATTERNS:
                entity.name = core_entity

    # 2. Thay thế placeholder trong triplets
    if core_entity:
        for triplet in result.triplets:
            if triplet.subject in _PLACEHOLDER_PATTERNS:
                triplet.subject = core_entity
            if triplet.object in _PLACEHOLDER_PATTERNS:
                triplet.object = core_entity

    # 3. Loại bỏ triplet rác (subject == object, hoặc quá ngắn)
    result.triplets = [
        t for t in result.triplets
        if t.subject != t.object and len(t.subject) > 1 and len(t.object) > 1
    ]

    # 4. Đảm bảo core_entity luôn có trong entities (type phụ thuộc doc_type)
    entity_names = {e.name for e in result.entities}
    if core_entity and core_entity not in entity_names:
        core_type = {
            DocType.CV: "PERSON",
            DocType.SOP: "PROCESS",
            DocType.PROJECT: "CONCEPT",
        }.get(result.doc_type, "CONCEPT")
        result.entities.insert(0, Entity(name=core_entity, type=core_type))
        entity_names.add(core_entity)

    # 5. Đảm bảo mọi subject/object trong triplets có trong entities
    for triplet in result.triplets:
        if triplet.subject not in entity_names:
            result.entities.append(Entity(name=triplet.subject, type="CONCEPT"))
            entity_names.add(triplet.subject)
            logger.debug("Auto-add entity từ subject: %s", triplet.subject)
        if triplet.object not in entity_names:
            result.entities.append(Entity(name=triplet.object, type="CONCEPT"))
            entity_names.add(triplet.object)
            logger.debug("Auto-add entity từ object: %s", triplet.object)

    return result


def extract_knowledge(
    chunk_text: str,
    core_entity: str = "",
) -> KnowledgeGraphExtraction:
    """Trích xuất tri thức từ một chunk văn bản.

    Args:
        chunk_text: Đoạn text đã chunk (≤ 256 tokens).
        core_entity: Tên chủ thể lõi của CV (vd: "Nguyễn Hoài Tưởng").
            Dùng để giải quyết đại từ và đảm bảo đồ thị kết nối.

    Returns:
        ``KnowledgeGraphExtraction`` chứa topic_category, entities, triplets.

    Raises:
        RuntimeError: Khi cả Cerebras và OpenAI đều thất bại.
    """
    # --- Thử Cerebras trước ---
    if settings.CEREBRAS_API_KEY:
        try:
            logger.debug("Gọi Cerebras (%s)…", settings.CEREBRAS_MODEL)
            raw = _call_cerebras(chunk_text, core_entity, timeout=30.0)
            result = _parse_extraction_with_retry(raw, max_retries=2)
            result = _validate_and_fix(result, core_entity)
            logger.info("Cerebras trích xuất OK: %s", result.topic_category.value)
            return result
        except Exception as exc:
            logger.warning("Cerebras thất bại (%s). Chuyển sang OpenAI.", exc)

    # --- Fallback: OpenAI ---
    if settings.OPENAI_API_KEY:
        try:
            logger.debug("Gọi OpenAI (%s)…", settings.OPENAI_MODEL)
            raw = _call_openai(chunk_text, core_entity, timeout=60.0)
            result = _parse_extraction_with_retry(raw, max_retries=2)
            result = _validate_and_fix(result, core_entity)
            logger.info("OpenAI trích xuất OK: %s", result.topic_category.value)
            return result
        except Exception as exc:
            logger.error("OpenAI cũng thất bại: %s", exc)

    raise RuntimeError(
        "Không thể trích xuất tri thức: cả Cerebras và OpenAI đều thất bại. "
        "Kiểm tra API key trong .env."
    )
