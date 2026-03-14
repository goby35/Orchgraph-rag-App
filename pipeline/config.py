"""
Cấu hình tập trung – đọc biến môi trường từ .env và khai báo hằng số dùng chung.
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load .env từ thư mục gốc của project
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)


class Settings:
    """Cấu hình toàn cục cho pipeline."""

    # --- API Keys ---
    NUTRIENT_API_KEY: str = os.getenv("NUTRIENT_API_KEY", "")
    NUTRIENT_BASE_URL: str = os.getenv("NUTRIENT_BASE_URL", "https://api.nutrient.io/build")
    CEREBRAS_API_KEY: str = os.getenv("CEREBRAS_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")

    # --- LLM Models ---
    CEREBRAS_MODEL: str = os.getenv("CEREBRAS_MODEL", "llama3.1-8b")
    OPENAI_MODEL: str = "gpt-4o"

    # --- Chunking ---
    CHUNK_SIZE: int = 250
    CHUNK_OVERLAP: int = 20

    # --- PhoBERT ---
    PHOBERT_MODEL: str = "vinai/phobert-base-v2"
    PHOBERT_MAX_TOKENS: int = 256

    # --- Neo4j ---
    NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "password123")

    # --- ChromaDB ---
    CHROMADB_HOST: str = os.getenv("CHROMADB_HOST", "localhost")
    CHROMADB_PORT: int = int(os.getenv("CHROMADB_PORT", "8000"))

    # --- Logging ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()

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
