"""
Bước 1 – Parse tài liệu (PDF / Word) sang Markdown.

Chiến lược:
  1. Ưu tiên dùng **docling** (hỗ trợ OCR, giữ cấu trúc heading).
  2. Nếu docling thất bại → gọi **Nutrient.io API** qua requests.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

import requests

from pipeline.config import settings, get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Docling (lazy import)
# ---------------------------------------------------------------------------
try:
    from docling.document_converter import DocumentConverter

    _DOCLING_AVAILABLE = True
except ImportError:
    _DOCLING_AVAILABLE = False
    logger.warning("docling chưa cài. Sẽ dùng Nutrient API làm fallback.")


# ---------------------------------------------------------------------------
#  Public API
# ---------------------------------------------------------------------------

def parse_document(file_path: str | Path) -> str:
    """Parse PDF/Word thành Markdown text.

    Args:
        file_path: Đường dẫn tuyệt đối hoặc tương đối tới file .pdf / .docx / .doc.

    Returns:
        Chuỗi Markdown thu được từ tài liệu.

    Raises:
        RuntimeError: Khi cả docling lẫn Nutrient đều thất bại.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {path}")

    # Nếu file đã là .md → đọc thẳng
    if path.suffix.lower() == ".md":
        logger.info("File đã là Markdown, đọc trực tiếp: %s", path.name)
        return path.read_text(encoding="utf-8")

    # --- Thử docling trước ---
    if _DOCLING_AVAILABLE:
        md = _parse_with_docling(path)
        if md:
            return md

    # --- Fallback: Nutrient.io API ---
    md = _parse_with_nutrient(path)
    if md:
        return md

    raise RuntimeError(
        f"Không thể parse '{path.name}': "
        f"docling={'có' if _DOCLING_AVAILABLE else 'không'}, "
        f"Nutrient API={'có key' if settings.NUTRIENT_API_KEY else 'không key'}."
    )


# ---------------------------------------------------------------------------
#  Internal helpers
# ---------------------------------------------------------------------------

def _parse_with_docling(path: Path) -> Optional[str]:
    """Dùng docling để convert tài liệu sang Markdown."""
    try:
        logger.info("Đang parse bằng docling: %s", path.name)
        converter = DocumentConverter()
        result = converter.convert(str(path))
        md: str = result.document.export_to_markdown()
        if md and md.strip():
            logger.info("docling parse thành công (%d ký tự).", len(md))
            return md
        logger.warning("docling trả về nội dung rỗng cho %s.", path.name)
    except Exception as exc:
        logger.warning("docling thất bại (%s). Chuyển sang Nutrient API.", exc)
    return None


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
