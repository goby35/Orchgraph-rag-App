"""
Cấu hình tập trung – đọc biến môi trường từ .env và khai báo hằng số dùng chung.
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from cerebras.cloud.sdk import Cerebras
from openai import OpenAI as _OpenAI

# Load .env từ thư mục gốc của project bằng path tường minh (không phụ thuộc CWD)
_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _ROOT / ".env"
load_dotenv(_ENV_FILE, override=False)


class Settings:
    """Cấu hình toàn cục cho pipeline."""

    # --- API Keys ---
    NUTRIENT_API_KEY: str = os.getenv("NUTRIENT_API_KEY", "")
    NUTRIENT_BASE_URL: str = os.getenv("NUTRIENT_BASE_URL", "https://api.nutrient.io/build")
    CEREBRAS_API_KEY: str = os.getenv("CEREBRAS_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")

    # --- LLM Models ---
    CEREBRAS_MODEL: str = os.getenv("CEREBRAS_MODEL", "llama3.1-8b")
    OPENAI_MODEL: str = "gpt-4o"
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    # --- Chunking ---
    CHUNK_SIZE: int = 250
    CHUNK_OVERLAP: int = 20

    # --- Embedding ---
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "Alibaba-NLP/gte-multilingual-base")
    EMBEDDING_MAX_TOKENS: int = 256

    EMBEDDING_MODELS: list[str] = [
        "vinai/phobert-base-v2",
        "Alibaba-NLP/gte-multilingual-base",
        "intfloat/multilingual-e5-base",
        "BAAI/bge-base-en-v1.5",
    ]
    ACTIVE_EMBEDDING_MODEL: str = os.getenv("ACTIVE_EMBEDDING_MODEL", "Alibaba-NLP/gte-multilingual-base")

    # --- GTE ---
    GTE_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"

    # --- Neo4j ---
    NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "password")
    NEO4J_AURA_URI: str | None = os.getenv("NEO4J_AURA_URI")
    NEO4J_AURA_USERNAME: str | None = os.getenv("NEO4J_AURA_USERNAME")
    NEO4J_AURA_PASSWORD: str | None = os.getenv("NEO4J_AURA_PASSWORD")
    NEO4J_AURA_DATABASE: str = os.getenv("NEO4J_AURA_DATABASE", "neo4j")

    @property
    def neo4j_uri(self) -> str:
        return self.NEO4J_AURA_URI if self.NEO4J_AURA_URI else self.NEO4J_URI

    @property
    def neo4j_user(self) -> str:
        return self.NEO4J_AURA_USERNAME if self.NEO4J_AURA_USERNAME else self.NEO4J_USER

    @property
    def neo4j_password(self) -> str:
        return self.NEO4J_AURA_PASSWORD if self.NEO4J_AURA_PASSWORD else self.NEO4J_PASSWORD

    @property
    def neo4j_database(self) -> str:
        if self.NEO4J_AURA_URI:
            return self.NEO4J_AURA_DATABASE
        return "neo4j"

    @property
    def is_aura(self) -> bool:
        return bool(self.NEO4J_AURA_URI)

    # --- ChromaDB ---
    CHROMADB_HOST: str = os.getenv("CHROMADB_HOST", "localhost")
    CHROMADB_PORT: int = int(os.getenv("CHROMADB_PORT", "8000"))

    # --- Logging ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()

# ── Dual-path LLM routing ────────────────────────────────────────────────────
# Nguyên tắc: dùng đúng model cho đúng việc.
#   - Extraction (cần schema enforcement) → OpenAI gpt-4o-mini
#     Lý do: response_format json_schema strict = constrained decoding tại API level,
#     không phải instruction. LLM không thể generate token vi phạm schema.
#   - Tất cả việc khác (summarize, embed context, chat) → Cerebras (nhanh ~20x, rẻ hơn)

_openai_extraction_client = _OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)
OPENAI_EXTRACTION_MODEL = "gpt-4o-mini"   # đủ quality cho extraction, rẻ hơn gpt-4o 15x

# Dùng client Cerebras hiện có làm fallback extraction path khi thiếu OpenAI key.
cerebras_client = Cerebras(api_key=settings.CEREBRAS_API_KEY) if settings.CEREBRAS_API_KEY else None
CEREBRAS_MODEL = settings.CEREBRAS_MODEL


def get_extraction_client():
    """
    Trả về (client, model_name, provider) cho extraction task.
    Fallback: nếu OPENAI_API_KEY không có → dùng Cerebras với json_object mode.
    """
    if os.getenv("OPENAI_API_KEY"):
        return _openai_extraction_client, OPENAI_EXTRACTION_MODEL, "openai"
    # Fallback về Cerebras nếu chưa có OpenAI key
    if cerebras_client is None:
        raise RuntimeError("Neither OPENAI_API_KEY nor CEREBRAS_API_KEY is configured")
    return cerebras_client, CEREBRAS_MODEL, "cerebras"

# --- Logger factory ---
def get_logger(name: str) -> logging.Logger:
    """Tạo logger chuẩn cho từng module."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "[%(asctime)s] %(name)s — %(levelname)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    return logger

