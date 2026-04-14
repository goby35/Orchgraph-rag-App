"""
Bước 5 – Vectorization (Multi-Embedding)
Sinh ra 2 vector embedding: public_embeddings và private_embeddings dựa trên nội dung gộp của từng mảng.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List
import torch
import torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer

from pipeline.config import settings, get_logger

logger = get_logger(__name__)

MODEL_FIELD_MAP = {
    "vinai/phobert-base-v2":             "public_embeddings_phobert",
    "Alibaba-NLP/gte-multilingual-base": "public_embeddings_gte",
    "intfloat/multilingual-e5-base":     "public_embeddings_e5",
    "BAAI/bge-base-en-v1.5":             "public_embeddings_bge",
}

class _EmbedderHub:
    def __init__(self):
        self._models = {}

    def _resolve_cache_dir(self) -> str | None:
        # In Modal runtime we mount model weights in /models; fallback to default HF cache locally.
        return "/models" if os.path.isdir("/models") else None
        
    def _get_or_load_embedder(self, model_id: str):
        if model_id not in self._models:
            logger.info(f"Đang tải {model_id}...")
            cache_dir = self._resolve_cache_dir()
            tokenizer = AutoTokenizer.from_pretrained(model_id, cache_dir=cache_dir)
            model = AutoModel.from_pretrained(model_id, trust_remote_code=True, cache_dir=cache_dir)
            model.eval()
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model.to(device)
            self._models[model_id] = (tokenizer, model, device)
        return self._models[model_id]

    def embed(self, text: str, model_id: str) -> List[float]:
        tokenizer, model, device = self._get_or_load_embedder(model_id)

        if not text or not text.strip():
            dim = model.config.hidden_size if hasattr(model.config, 'hidden_size') else 768
            return [0.0] * dim

        prefix = "query: " if "e5" in model_id.lower() else ""
        text_w_prefix = prefix + text

        inputs = tokenizer(
            text_w_prefix, return_tensors="pt", max_length=settings.EMBEDDING_MAX_TOKENS,
            truncation=True, padding=True
        )
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            outputs = model(**inputs)
            cls_embedding = outputs.last_hidden_state[:, 0, :]
            cls_embedding = F.normalize(cls_embedding, p=2, dim=1)
            cls_embedding = cls_embedding.cpu().numpy()
        return cls_embedding.flatten().tolist()

_embedder_hub = _EmbedderHub()

def vectorize_text(text: str) -> List[float]:
    """Public helper for text embedding (active model)."""
    return _embedder_hub.embed(text, settings.ACTIVE_EMBEDDING_MODEL)


def vectorize_text_for_model(text: str, model_id: str) -> List[float]:
    """Public helper for text embedding with an explicit model id."""
    return _embedder_hub.embed(text, model_id)

def embed_all_models(text: str) -> dict[str, list[float]]:
    """Trả về dict {field_name: vector} cho tất cả models được config."""
    result = {}
    for model_id in settings.EMBEDDING_MODELS:
        field_name = MODEL_FIELD_MAP.get(model_id)
        if not field_name:
            continue
        result[field_name] = _embedder_hub.embed(text, model_id)
    return result

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
        "source_file": node_data.get("source_file", "unknown")
    }

    # Sinh tất cả embeddings
    public_embs = embed_all_models(public_text)
    private_embs = embed_all_models(private_text)

    for field_name, vector in public_embs.items():
        res[field_name] = vector
    for field_name, vector in private_embs.items():
        # Field cho private, e.g. "private_embeddings_phobert"
        priv_field = field_name.replace("public_", "private_")
        res[priv_field] = vector
    
    logger.info(f"Hoàn tất vectorize Split-Compartment cho node {node_id}")
    return res
