"""
Bước 1 – Parse tài liệu sang Markdown.

Chiến lược (Phase 1):
    1. Ưu tiên **LlamaParse** (cloud parser).
    2. Nếu chất lượng thấp hoặc lỗi -> fallback **unstructured** (local parser).
    3. Nếu vẫn lỗi -> fallback cuối **Nutrient API** để tăng độ bền vận hành.
"""

from __future__ import annotations

import os
import importlib
from pathlib import Path
from typing import Any, Optional

import requests

from pipeline.config import settings, get_logger

logger = get_logger(__name__)

_MIN_TEXT_LEN = int(os.getenv("PARSER_MIN_TEXT_LEN", "200"))


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------
LlamaParse: Any = None
partition: Any = None

try:
    LlamaParse = importlib.import_module("llama_parse").LlamaParse
    _LLAMAPARSE_AVAILABLE = True
except ImportError:
    _LLAMAPARSE_AVAILABLE = False
    logger.warning("llama-parse chưa cài. Sẽ fallback qua unstructured/Nutrient.")

try:
    partition = importlib.import_module("unstructured.partition.auto").partition
    _UNSTRUCTURED_AVAILABLE = True
except ImportError:
    _UNSTRUCTURED_AVAILABLE = False
    logger.warning("unstructured chưa cài. Sẽ fallback qua Nutrient.")


# ---------------------------------------------------------------------------
#  Public API
# ---------------------------------------------------------------------------

def parse_to_markdown(file_path: str | Path) -> str:
    """Parse file sang Markdown theo 3-tier fallback.

    Args:
        file_path: Đường dẫn file đầu vào.

    Returns:
        Chuỗi Markdown thu được từ parser.

    Raises:
        RuntimeError: Khi mọi parser đều thất bại.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {path}")

    if path.suffix.lower() in {".md", ".txt"}:
        logger.info("File text/markdown, đọc trực tiếp: %s", path.name)
        return path.read_text(encoding="utf-8")

    tier_errors: list[str] = []

    # Tier 1: LlamaParse (primary)
    if _LLAMAPARSE_AVAILABLE:
        try:
            logger.info("[Parser] Tier 1 LlamaParse: %s", path.name)
            md = _parse_with_llamaparse(path)
            is_good, reason = _quality_check(md, path)
            if is_good:
                logger.info("[Parser] Tier 1 OK (%d chars)", len(md))
                return md
            logger.warning("[Parser] Tier 1 quality thấp (%s) -> fallback Tier 2", reason)
            tier_errors.append(f"Tier1 quality thấp: {reason}")
        except Exception as exc:
            logger.warning("[Parser] Tier 1 lỗi: %s", exc)
            tier_errors.append(f"Tier1 lỗi: {exc}")

    # Tier 2: unstructured (local fallback)
    if _UNSTRUCTURED_AVAILABLE:
        try:
            logger.info("[Parser] Tier 2 unstructured: %s", path.name)
            md = _parse_with_unstructured(path)
            is_good, reason = _quality_check(md, path)
            if is_good:
                logger.info("[Parser] Tier 2 OK (%d chars)", len(md))
                return md
            logger.warning("[Parser] Tier 2 quality thấp (%s)", reason)
            tier_errors.append(f"Tier2 quality thấp: {reason}")
        except Exception as exc:
            logger.warning("[Parser] Tier 2 lỗi: %s", exc)
            tier_errors.append(f"Tier2 lỗi: {exc}")

    # Tier 3: Nutrient API (rescue fallback)
    md = _parse_with_nutrient(path)
    if md:
        logger.info("[Parser] Tier 3 Nutrient OK (%d chars)", len(md))
        return md
    tier_errors.append("Tier3 Nutrient thất bại hoặc không có API key")

    raise RuntimeError(
        f"Không thể parse '{path.name}'. "
        + " | ".join(tier_errors)
    )


def parse_document(file_path: str | Path) -> str:
    """Backward-compatible shim cho callsites cũ."""
    return parse_to_markdown(file_path)


# ---------------------------------------------------------------------------
#  Internal helpers
# ---------------------------------------------------------------------------

def _parse_with_llamaparse(path: Path) -> str:
    """Tier 1: Parse bằng LlamaParse, trả về markdown text."""
    if LlamaParse is None:
        raise RuntimeError("LlamaParse không khả dụng")

    api_key = (
        os.getenv("LLAMA_CLOUD_API_KEY", "").strip()
        or os.getenv("LLAMAPARSE_API_KEY", "").strip()
    )
    if not api_key:
        raise ValueError("Thiếu LLAMA_CLOUD_API_KEY/LLAMAPARSE_API_KEY")

    parser = LlamaParse(
        api_key=api_key,
        result_type="markdown",
        num_workers=1,
        verbose=False,
        language="vi",
    )
    documents = parser.load_data(str(path))
    text = "\n\n".join((getattr(doc, "text", "") or "").strip() for doc in documents).strip()
    if not text:
        raise RuntimeError("LlamaParse trả về nội dung rỗng")
    return text


def _parse_with_unstructured(path: Path) -> str:
    """Tier 2: Parse local bằng unstructured và map ra markdown cơ bản."""
    if partition is None:
        raise RuntimeError("unstructured không khả dụng")

    elements = partition(
        filename=str(path),
        strategy="hi_res",
        infer_table_structure=True,
        include_metadata=True,
    )

    lines: list[str] = []
    for el in elements:
        text = str(el).strip()
        if not text:
            continue

        category = str(getattr(el, "category", type(el).__name__)).lower()
        if category == "title":
            lines.append(f"## {text}")
        elif category == "listitem":
            lines.append(f"- {text}")
        else:
            lines.append(text)

    markdown = "\n\n".join(lines).strip()
    if not markdown:
        raise RuntimeError("unstructured trả về nội dung rỗng")
    return markdown


def _quality_check(text: str, file_path: Path) -> tuple[bool, str]:
    """Đánh giá nhanh chất lượng output parser để quyết định fallback."""
    cleaned = text.strip()
    if len(cleaned) < _MIN_TEXT_LEN:
        return False, f"text quá ngắn ({len(cleaned)} < {_MIN_TEXT_LEN})"

    if file_path.suffix.lower() == ".pdf":
        try:
            fitz = importlib.import_module("fitz")

            doc = fitz.open(str(file_path))
            pages_with_text = sum(1 for p in doc if (p.get_text() or "").strip())
            total_pages = len(doc)
            doc.close()

            if total_pages > 0 and (pages_with_text / total_pages) < 0.3:
                return False, (
                    f"PDF dạng scan/image-heavy ({pages_with_text}/{total_pages} trang có text)"
                )
        except Exception:
            # fitz là kiểm tra bổ sung, lỗi import/runtime không làm fail parser.
            pass

    return True, "ok"


def _parse_with_nutrient(path: Path) -> Optional[str]:
    """Gọi Nutrient.io REST API để chuyển tài liệu sang text/Markdown.

    API endpoint: POST {base_url}/build
    Tham khảo: https://www.nutrient.io/api/
    """
    api_key = settings.NUTRIENT_API_KEY
    if not api_key:
        logger.error("NUTRIENT_API_KEY chưa được cấu hình trong .env.")
        return None

    base_url = settings.NUTRIENT_BASE_URL.rstrip("/")
    url = f"{base_url}"

    logger.info("Đang gọi Nutrient API cho: %s", path.name)
    try:
        with open(path, "rb") as f:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (path.name, f, "application/octet-stream")},
                data={
                    "instructions": '{"parts":[{"type":"text"}]}',
                },
                timeout=120,
            )

        if resp.status_code == 200:
            # Nutrient trả về plain text / markdown
            text = resp.text.strip()
            if text:
                logger.info("Nutrient API trả về thành công (%d ký tự).", len(text))
                return text
            logger.warning("Nutrient API trả về nội dung rỗng.")
        else:
            logger.error(
                "Nutrient API lỗi %d: %s", resp.status_code, resp.text[:300]
            )
    except requests.RequestException as exc:
        logger.error("Nutrient API request thất bại: %s", exc)

    return None
