#!/usr/bin/env python
"""Test what model settings are loaded."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.config import settings

print(f"CEREBRAS_MODEL = {settings.CEREBRAS_MODEL}")
print(f"OPENAI_MODEL = {settings.OPENAI_MODEL}")
