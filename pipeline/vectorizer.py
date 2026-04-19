"""
Bước 5 – Vectorization (Multi-Embedding)
Sinh ra 2 vector embedding: public_embeddings và private_embeddings dựa trên nội dung gộp của từng mảng.
"""

from __future__ import annotations

import json
import hashlib
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List
import torch
import torch.nn.functional as F
from pipeline.config import settings, get_logger


def _runtime_hf_modules_cache_dir() -> str:
    """Use ephemeral modules cache so stale dynamic code does not persist on shared volume."""
    if os.path.isdir("/tmp"):
        return "/tmp/hf_modules_stable"
    return os.path.join(Path.home(), ".cache", "huggingface", "hf_modules_stable")


def _configure_hf_caches() -> None:
    """Pin Hugging Face caches to a stable, writable location before model imports."""
    cache_root = "/models" if os.path.isdir("/models") else os.path.join(Path.home(), ".cache", "huggingface")
    modules_cache = _runtime_hf_modules_cache_dir()
    os.makedirs(modules_cache, exist_ok=True)
    os.environ["HF_HOME"] = cache_root
    os.environ["HF_HUB_CACHE"] = os.path.join(cache_root, "hub")
    os.environ["HF_MODULES_CACHE"] = modules_cache


_configure_hf_caches()

from sentence_transformers import SentenceTransformer
from transformers import AutoModel, AutoTokenizer

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
        self._gte_cache_refreshed = False

    @staticmethod
    def _is_gte_model(model_id: str) -> bool:
        return model_id == "Alibaba-NLP/gte-multilingual-base"

    def _resolve_cache_dir(self) -> str | None:
        # In Modal runtime we mount model weights in /models; fallback to default HF cache locally.
        return "/models" if os.path.isdir("/models") else None

    @staticmethod
    def _set_isolated_hf_modules_cache(cache_root: str | None) -> None:
        _ = cache_root
        modules_cache = _runtime_hf_modules_cache_dir()
        os.makedirs(modules_cache, exist_ok=True)
        os.environ["HF_MODULES_CACHE"] = modules_cache

    @staticmethod
    def _purge_legacy_gte_module_cache() -> None:
        # Remove old Alibaba dynamic module cache that can be ABI-incompatible with newer libs.
        modules_cache = os.getenv("HF_MODULES_CACHE")
        if not modules_cache:
            return

        base = Path(modules_cache) / "transformers_modules"
        if not base.exists():
            return

        for candidate in base.glob("Alibaba*"):
            if candidate.is_dir():
                shutil.rmtree(candidate, ignore_errors=True)

    @staticmethod
    def _hash_embed(text: str, dim: int = 768) -> list[float]:
        """Deterministic fallback embedding that does not require model loading."""
        cleaned = str(text or "").strip().lower()
        if not cleaned:
            return [0.0] * dim

        vector = [0.0] * dim
        tokens = cleaned.split()
        for index, token in enumerate(tokens):
            digest = hashlib.sha256(f"{index}:{token}".encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            magnitude = (int.from_bytes(digest[5:9], "big") / 0xFFFFFFFF)
            vector[bucket] += sign * (0.5 + magnitude)

        norm = sum(value * value for value in vector) ** 0.5
        if norm <= 0.0:
            return vector
        return [value / norm for value in vector]
        
    def _get_or_load_embedder(self, model_id: str):
        if model_id not in self._models:
            logger.info(f"Đang tải {model_id}...")
            cache_dir = self._resolve_cache_dir()
            self._set_isolated_hf_modules_cache(cache_dir)
            if self._is_gte_model(model_id):
                if not self._gte_cache_refreshed:
                    self._purge_legacy_gte_module_cache()
                    self._gte_cache_refreshed = True
                device = "cuda" if torch.cuda.is_available() else "cpu"
                try:
                    model = SentenceTransformer(
                        model_id,
                        cache_folder=cache_dir,
                        trust_remote_code=True,
                        device=device,
                    )
                except Exception as exc:
                    logger.warning("GTE load failed, purging module cache and retrying once: %s", exc)
                    try:
                        self._purge_legacy_gte_module_cache()
                        model = SentenceTransformer(
                            model_id,
                            cache_folder=cache_dir,
                            trust_remote_code=True,
                            device=device,
                        )
                        self._models[model_id] = ("sentence_transformer", model)
                    except Exception as retry_exc:
                        logger.error("GTE load failed after retry, using fallback hash embeddings: %s", retry_exc)
                        self._models[model_id] = ("fallback_hash", 768)
                else:
                    self._models[model_id] = ("sentence_transformer", model)
            else:
                tokenizer = AutoTokenizer.from_pretrained(
                    model_id,
                    cache_dir=cache_dir,
                    trust_remote_code=True,
                )
                model = AutoModel.from_pretrained(model_id, trust_remote_code=True, cache_dir=cache_dir)
                model.eval()
                device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
                model.to(device)
                self._models[model_id] = ("transformers", tokenizer, model, device)
        return self._models[model_id]

    def embed(self, text: str, model_id: str) -> List[float]:
        model_bundle = self._get_or_load_embedder(model_id)

        if model_bundle[0] == "fallback_hash":
            return self._hash_embed(text, int(model_bundle[1]))

        if not text or not text.strip():
            if model_bundle[0] == "sentence_transformer":
                dim = int(model_bundle[1].get_sentence_embedding_dimension())
            else:
                _, _, model, _ = model_bundle
                dim = model.config.hidden_size if hasattr(model.config, 'hidden_size') else 768
            return [0.0] * dim

        prefix = "query: " if "e5" in model_id.lower() else ""
        text_w_prefix = prefix + text

        if model_bundle[0] == "sentence_transformer":
            _, model = model_bundle
            embeddings = model.encode(
                [text_w_prefix],
                normalize_embeddings=True,
                convert_to_numpy=True,
            )
            return embeddings[0].astype(float).tolist()

        _, tokenizer, model, device = model_bundle

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
