"""
Bước 5 – Vectorization & Chuẩn bị dữ liệu cho Neo4j.

Luồng:
  1. Tách từ tiếng Việt bằng ``pyvi.ViTokenizer``.
  2. Tạo vector embedding bằng PhoBERT (``vinai/phobert-base-v2``).
  3. Đóng gói thành dict sẵn sàng nạp vào Neo4j / ChromaDB.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import torch
from pyvi import ViTokenizer
from transformers import AutoModel, AutoTokenizer

from pipeline.config import settings, get_logger
from pipeline.extractor import KnowledgeGraphExtraction

logger = get_logger(__name__)


# ============================================================================
# PhoBERT Embedder (Singleton)
# ============================================================================

class _PhoBERTEmbedder:
    """Tải và cache model PhoBERT, tạo embedding cho text tiếng Việt."""

    def __init__(self) -> None:
        self._tokenizer: Optional[AutoTokenizer] = None
        self._model: Optional[AutoModel] = None
        self._device: Optional[torch.device] = None

    def _ensure_loaded(self) -> None:
        """Lazy-load model lần đầu sử dụng."""
        if self._model is not None:
            return

        model_name = settings.PHOBERT_MODEL
        logger.info("Đang tải PhoBERT: %s …", model_name)
        self._tokenizer = AutoTokenizer.from_pretrained(model_name)
        self._model = AutoModel.from_pretrained(model_name)
        self._model.eval()
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._model.to(self._device)
        logger.info("PhoBERT loaded trên %s.", self._device)

    def embed(self, segmented_text: str) -> List[float]:
        """Tạo embedding vector (768-d) từ text đã tách từ.

        Args:
            segmented_text: Chuỗi đã qua ``ViTokenizer.tokenize()``.

        Returns:
            List[float] – vector 768 chiều.
        """
        self._ensure_loaded()

        if not segmented_text or not segmented_text.strip():
            return [0.0] * 768

        inputs = self._tokenizer(
            segmented_text,
            return_tensors="pt",
            max_length=settings.PHOBERT_MAX_TOKENS,
            truncation=True,
            padding=True,
        )
        inputs = {k: v.to(self._device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self._model(**inputs)
            # CLS token embedding
            cls_embedding = outputs.last_hidden_state[:, 0, :].cpu().numpy()

        return cls_embedding.flatten().tolist()


# Module-level singleton
_embedder = _PhoBERTEmbedder()


# ============================================================================
# Public API
# ============================================================================

def prepare_for_neo4j(
    chunk_text: str,
    extracted_json: KnowledgeGraphExtraction,
) -> Dict[str, Any]:
    """Chuẩn bị dữ liệu cho một chunk để nạp vào Neo4j / ChromaDB.

    Pipeline bên trong:
      1. Word Segmentation bằng ``pyvi``.
      2. PhoBERT embedding.
      3. Đóng gói kết quả.

    Args:
        chunk_text: Đoạn text gốc đã clean.
        extracted_json: Kết quả extraction từ bước 4.

    Returns:
        Dict chứa:
          - ``chunk_id``            : UUID duy nhất.
          - ``original_clean_text`` : Text gốc đã clean.
          - ``segmented_text``      : Text đã tách từ bằng pyvi.
          - ``embedding``           : List[float] 768-d.
          - ``extracted_knowledge`` : Dict (serializable) từ Pydantic model.
    """
    # 1. Word Segmentation
    segmented = ViTokenizer.tokenize(chunk_text) if chunk_text else ""
    logger.debug("Segmented: %s…", segmented[:80])

    # 2. PhoBERT Embedding
    embedding = _embedder.embed(segmented)
    logger.debug("Embedding dim: %d", len(embedding))

    # 3. Đóng gói
    result: Dict[str, Any] = {
        "chunk_id": str(uuid.uuid4()),
        "original_clean_text": chunk_text,
        "segmented_text": segmented,
        "embedding": embedding,
        "extracted_knowledge": extracted_json.model_dump(),
    }

    logger.info(
        "Chunk %s sẵn sàng (topic=%s, entities=%d, triplets=%d).",
        result["chunk_id"][:8],
        extracted_json.topic_category.value,
        len(extracted_json.entities),
        len(extracted_json.triplets),
    )
    return result
