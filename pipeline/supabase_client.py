from __future__ import annotations

import os
from functools import lru_cache

from supabase import Client, create_client

from pipeline.config import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    """Create and cache Supabase service client for server-side operations."""
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()

    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY chưa set trong .env")

    return create_client(url, key)
