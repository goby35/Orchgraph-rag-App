"""
Bước 3 – Semantic Chunking (≤ 256 tokens cho PhoBERT).

Dùng llama-index ``SentenceSplitter`` để chia nhỏ văn bản đã clean,
với ``chunk_size=250`` và ``chunk_overlap=20`` để đảm bảo không vượt
ngưỡng 256 tokens của PhoBERT.
"""

from __future__ import annotations

from typing import List

from llama_index.core.node_parser import SentenceSplitter

from pipeline.config import settings, get_logger

logger = get_logger(__name__)


def chunk_cleaned_text(cleaned_text: str) -> List[str]:
    """Chia văn bản đã clean thành các chunk nhỏ ≤ 256 tokens.

    Args:
        cleaned_text: Văn bản tiếng Việt đã qua ``clean_vietnamese_text``.

    Returns:
        Danh sách các chunk text (chuỗi thuần).
    """
    if not cleaned_text or not cleaned_text.strip():
        logger.warning("Đầu vào rỗng, trả về danh sách rỗng.")
        return []

    splitter = SentenceSplitter(
        chunk_size=settings.CHUNK_SIZE,        # 250 tokens
        chunk_overlap=settings.CHUNK_OVERLAP,  # 20 tokens overlap
        paragraph_separator="\n\n",
        secondary_chunking_regex=r"[.。!?！？;；]\s*",
    )

    chunks: List[str] = splitter.split_text(cleaned_text)
    logger.info(
        "Đã chia thành %d chunk (size=%d, overlap=%d).",
        len(chunks),
        settings.CHUNK_SIZE,
        settings.CHUNK_OVERLAP,
    )
    return chunks
