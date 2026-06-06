#!/usr/bin/env python
"""Check available Cerebras models."""
from pathlib import Path
import os

from cerebras.cloud.sdk import Cerebras
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]

# Load .env from repo root.
env_path = ROOT / ".env"
load_dotenv(env_path)

try:
    api_key = os.getenv('CEREBRAS_API_KEY')
    if not api_key:
        print("Error: CEREBRAS_API_KEY not set in .env")
        exit(1)

    c = Cerebras(api_key=api_key)
    models = c.models.list()
    print("Available Cerebras models:")
    print(f"Type: {type(models)}")
    print(f"Content: {models}")
    if hasattr(models, '__iter__'):
        for m in models:
            print(f"  - {m}")
except Exception as e:
    import traceback

    print(f"Error: {e}")
    traceback.print_exc()
