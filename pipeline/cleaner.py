"""
Bước 2 – Làm sạch và chuẩn hóa văn bản tiếng Việt.

Thứ tự xử lý:
  1. Chuẩn hóa Unicode NFC.
  2. Xóa ký tự ẩn / rác (zero-width space, BOM, …).
  3. Nối dòng đứt gãy (giữ lại Markdown headers & bullet points).
  4. Xóa khoảng trắng thừa.
"""

from __future__ import annotations

import re
import unicodedata

from pipeline.config import get_logger

logger = get_logger(__name__)

# Các ký tự ẩn / zero-width cần loại bỏ
_INVISIBLE_CHARS = re.compile(
    "["
    "\u200b"   # zero-width space
    "\u200c"   # zero-width non-joiner
    "\u200d"   # zero-width joiner
    "\u200e"   # left-to-right mark
    "\u200f"   # right-to-left mark
    "\u00ad"   # soft hyphen
    "\ufeff"   # BOM / zero-width no-break space
    "\u2060"   # word joiner
    "\u2062"   # invisible times
    "\u2063"   # invisible separator
    "\u2064"   # invisible plus
    "]",
    flags=re.UNICODE,
)

# Regex phát hiện dòng mở đầu bằng Markdown header hoặc bullet point
_MD_STRUCTURE_LINE = re.compile(
    r"^(?:#{1,6}\s|[-*+]\s|\d+\.\s)",
)


def clean_vietnamese_text(raw_text: str) -> str:
    """Làm sạch và chuẩn hóa một đoạn văn bản tiếng Việt.

    Args:
        raw_text: Chuỗi thô (có thể chứa Markdown).

    Returns:
        Chuỗi đã chuẩn hóa, sẵn sàng cho bước chunking.
    """
    if not raw_text:
        return ""

    text = raw_text

    # 1. Chuẩn hóa Unicode NFC – đồng nhất bảng mã tiếng Việt
    text = unicodedata.normalize("NFC", text)
    logger.debug("Sau NFC normalize: %d ký tự.", len(text))

    # 2. Xóa ký tự ẩn / rác
    text = _INVISIBLE_CHARS.sub("", text)

    # 3. Nối dòng đứt gãy nhưng GIỮ LẠI newline của Markdown headers & bullets
    text = _join_broken_lines(text)

    # 4. Xóa khoảng trắng thừa (nhiều space liên tiếp → 1 space)
    #    Thực hiện trên từng dòng để giữ newline có ý nghĩa.
    lines = text.split("\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in lines]
    text = "\n".join(lines)

    # Loại bỏ các dòng trống liên tiếp (giữ tối đa 1 dòng trống)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    logger.info("Đã clean text: %d → %d ký tự.", len(raw_text), len(text))
    return text


# ---------------------------------------------------------------------------
#  Internal helpers
# ---------------------------------------------------------------------------

def _join_broken_lines(text: str) -> str:
    """Nối dòng bị ngắt giữa câu nhưng giữ nguyên dòng Markdown cấu trúc.

    Logic:
      - Nếu dòng tiếp theo bắt đầu bằng ``#``, ``-``, ``*``, ``+`` hoặc
        ``1.`` (header / bullet / ordered list) → giữ newline.
      - Nếu dòng hiện tại kết thúc giữa chừng (không phải `.`, `!`, `?`,
        `:`, dấu xuống dòng kép) → nối với dòng tiếp theo bằng 1 space.
    """
    lines = text.split("\n")
    merged: list[str] = []
    i = 0

    while i < len(lines):
        current = lines[i]

        # Nếu dòng tiếp theo là cấu trúc Markdown hoặc dòng trống → giữ nguyên
        if i + 1 >= len(lines):
            merged.append(current)
            break

        next_line = lines[i + 1]

        # Giữ nguyên nếu dòng hiện tại là trống
        if not current.strip():
            merged.append(current)
            i += 1
            continue

        # Giữ nguyên nếu dòng hiện tại là Markdown header/bullet
        if _MD_STRUCTURE_LINE.match(current.strip()):
            merged.append(current)
            i += 1
            continue

        # Giữ nguyên nếu dòng tiếp theo là cấu trúc Markdown hoặc trống
        if not next_line.strip() or _MD_STRUCTURE_LINE.match(next_line.strip()):
            merged.append(current)
            i += 1
            continue

        # Dòng hiện tại kết thúc "giữa câu" → nối với dòng tiếp theo
        stripped = current.rstrip()
        if stripped and stripped[-1] not in ".!?:;。":
            merged.append(stripped + " " + next_line.lstrip())
            i += 2  # bỏ qua dòng tiếp theo vì đã nối
        else:
            merged.append(current)
            i += 1

    return "\n".join(merged)
