"""
Bước 5 – Vectorization (Multi-Embedding)
Sinh ra 2 vector embedding: public_embeddings và private_embeddings dựa trên nội dung gộp của từng mảng.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
import torch
import torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer

from pipeline.config import settings, get_logger

logger = get_logger(__name__)

class _GTEEmbedder:
    """Tải và cache model Embedding GTE"""
    def __init__(self) -> None:
        self._tokenizer, self._model, self._device = None, None, None

    def _ensure_loaded(self) -> None:
        if self._model is not None: return
        logger.info(f"Đang tải {settings.EMBEDDING_MODEL}...")
        self._tokenizer = AutoTokenizer.from_pretrained(settings.EMBEDDING_MODEL)
        self._model = AutoModel.from_pretrained(settings.EMBEDDING_MODEL, trust_remote_code=True)
        self._model.eval()
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._model.to(self._device)

    def embed(self, text: str) -> List[float]:
        self._ensure_loaded()
        tokenizer = self._tokenizer
        model = self._model
        device = self._device
        if tokenizer is None or model is None or device is None:
            raise RuntimeError("Embedding model/tokenizer/device chưa được khởi tạo")

        if not text or not text.strip():
            return [0.0] * 768

        inputs = tokenizer(
            text, return_tensors="pt", max_length=settings.EMBEDDING_MAX_TOKENS,
            truncation=True, padding=True
        )
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            outputs = model(**inputs)
            cls_embedding = outputs.last_hidden_state[:, 0, :]
            cls_embedding = F.normalize(cls_embedding, p=2, dim=1)
            cls_embedding = cls_embedding.cpu().numpy()
        return cls_embedding.flatten().tolist()

_embedder = _GTEEmbedder()


def vectorize_text(text: str) -> List[float]:
    """Public helper for text embedding to avoid leaking embedder internals."""
    return _embedder.embed(text)

def _stringify_value(val: Any) -> str:
    """Ép chuỗi đệ quy an toàn cho dict / list."""
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False)
    return str(val) if val else ""


def _safe_join_list(values: Any, sep: str = ", ") -> str:
    """Join list an toàn, bỏ qua None/chuỗi rỗng và ép kiểu về str."""
    if not isinstance(values, list):
        return ""
    normalized = [str(v).strip() for v in values if v is not None and str(v).strip()]
    return sep.join(normalized)


def _infer_record_type(node_data: Dict[str, Any], data: Dict[str, Any]) -> str:
    """Suy luận record_type cho JSON direct nếu đầu vào không có field record_type."""
    record_type = str(node_data.get("record_type", "")).upper().strip()
    if record_type in {"PERSONNEL", "ORGANIZATION"}:
        return record_type
    if "org_id" in data:
        return "ORGANIZATION"
    return "PERSONNEL"

def prepare_for_neo4j(node_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Nhận record data từ bước Extract (hoặc JSON direct), sinh 2 embedding và trả về dict gộp chuẩn bị nạp Neo4j.
    Kiện toàn mảng public và private.
    """
    logger.debug("Bắt đầu sinh Multi-Embeddings")
    data = node_data.get("data", node_data)  # Support direct json
    record_type = _infer_record_type(node_data, data)
    
    public_data = data.get("public_data", {})
    private_data = data.get("private_data", {})
    
    # Gom chuỗi text để nhúng public
    public_text_parts = []
    if record_type == "PERSONNEL":
        public_text_parts = [
            public_data.get("full_name", ""),
            public_data.get("professional_summary", ""),
            _safe_join_list(public_data.get("skills", []))
        ]
    else: # ORGANIZATION
        public_text_parts = [
            public_data.get("org_name", ""),
            public_data.get("brief_description", ""),
            _stringify_value(public_data.get("active_jds", []))
        ]
    public_text = " ".join([str(t).strip() for t in public_text_parts if t is not None and str(t).strip()])
    
    # Gom chuỗi text để nhúng private
    private_text_parts = []
    if record_type == "PERSONNEL":
        private_text_parts = [
            private_data.get("project_technical_secrets", ""),
            _stringify_value(private_data.get("interview_questions_history", []))
        ]
    else:
        private_text_parts = [
            private_data.get("internal_project_pain_points", ""),
            private_data.get("target_candidate_dna", "")
        ]
    private_text = " ".join([str(t).strip() for t in private_text_parts if t is not None and str(t).strip()])

    # Embeddings
    node_id = data.get("personnel_id") or data.get("org_id") or "UNKNOWN"
    res = {
        "node_id": node_id,
        "record_type": record_type,
        "public_data": public_data,
        "private_data": private_data,
        "public_embeddings_phobert": _embedder.embed(public_text),
        "private_embeddings_phobert": _embedder.embed(private_text),
        "source_file": node_data.get("source_file", "unknown")
    }
    
    logger.info(f"Hoàn tất vectorize Split-Compartment cho node {node_id}")
    return res
