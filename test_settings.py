#!/usr/bin/env python
"""Test what model settings are loaded."""
from pipeline.config import settings
print(f"CEREBRAS_MODEL = {settings.CEREBRAS_MODEL}")
print(f"OPENAI_MODEL = {settings.OPENAI_MODEL}")
