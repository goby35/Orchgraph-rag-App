from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.vectorizer import embed_all_models

test_dict = embed_all_models("Kiểm tra hệ thống vector")
print("Các trường đã tạo:", test_dict.keys())
for k, v in test_dict.items():
    print(f"- {k}: dimension = {len(v)}")
