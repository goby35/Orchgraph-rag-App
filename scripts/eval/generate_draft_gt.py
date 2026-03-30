import pathlib
import sys
import json

# 1. Chống lỗi ModuleNotFoundError 'pipeline' khi chạy file trực tiếp
# BẮT BUỘC PHẢI ĐỂ ĐOẠN NÀY LÊN TRÊN CÙNG TRƯỚC KHI IMPORT PIPELINE
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.parser import parse_to_markdown
from pipeline.extractor import _call_llm
from pipeline.cleaner import clean_vietnamese_text

# ==========================================
# CÔNG TẮC AN TOÀN (TEST MODE)
# Để True: Chỉ chạy 1 file đầu tiên để test API & Schema
# Để False: Chạy toàn bộ 30 file sau khi test thành công
TEST_MODE = False 
# ==========================================

def main():
    CV_DIR = PROJECT_ROOT / "data_eval" / "cv_synthetic"

    pdf_files = sorted(CV_DIR.glob("*.pdf"))
    if not pdf_files:
        print(f"No PDF files found in {CV_DIR}")
        sys.exit(1)

    # Nếu đang bật Test Mode, cắt lấy đúng 1 file đầu tiên
    if TEST_MODE:
        print("\n⚠️ ĐANG BẬT CHẾ ĐỘ TEST: Chỉ xử lý 1 file đầu tiên để tiết kiệm API ⚠️")
        pdf_files = pdf_files[:1]
    else:
        print(f"\n🚀 Đang chạy thực tế cho toàn bộ {len(pdf_files)} files...")

    draft_data = []

    for file_path in pdf_files:
        try:
            print(f"\nĐang xử lý: {file_path.name}...")
            # Bóc tách text thô từ PDF
            text = parse_to_markdown(file_path)
            
            # Làm sạch văn bản và khử ký tự dị dạng
            cleaned_text = clean_vietnamese_text(text)
            safe_text = json.dumps(cleaned_text)[1:-1]
            
            # ĐI CỬA SAU: Gọi thẳng LLM, bỏ qua Pydantic
            raw_json_str = _call_llm(safe_text, file_hint=file_path.name)
            
            # Dọn dẹp các ký tự markdown bao quanh JSON (nếu có)
            raw_json_str = raw_json_str.strip()
            if raw_json_str.startswith("```json"):
                raw_json_str = raw_json_str[7:-3].strip()
            elif raw_json_str.startswith("```"):
                raw_json_str = raw_json_str[3:-3].strip()
            
            # Ép kiểu thẳng bằng JSON thuần của Python
            extracted_dict = json.loads(raw_json_str)

            pub_data = extracted_dict.get("public_data", {})
            priv_data = extracted_dict.get("private_data", {})

            # Cảnh báo nếu dữ liệu bị rỗng
            if not pub_data and not priv_data:
                print(f"❌ CẢNH BÁO: LLM không nhả ra public_data hoặc private_data cho file {file_path.name}!")

            entry = {
                "file": file_path.name,
                "public_data": pub_data,
                "private_data": priv_data,
            }
            draft_data.append(entry)
            print(f"✅ Processed {file_path.name}")
            
        except json.JSONDecodeError as e:
            print(f"❌ LỖI PARSE JSON TỪ LLM OUTPUT CHO FILE {file_path.name}: {e}")
            continue
        except Exception as e:
            # Gài bẫy lỗi để hệ thống không chết chùm
            print(f"❌ LỖI BỎ QUA FILE {file_path.name}: {e}")
            continue

    # Lưu ra file draft trực tiếp bằng json chuẩn
    out_path = PROJECT_ROOT / "data_eval" / "ground_truth_draft.json"
    
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(draft_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n🎉 Đã lưu file kết quả tại: {out_path}")
    
    if TEST_MODE:
        print("💡 HƯỚNG DẪN BƯỚC TIẾP THEO:")
        print("1. Mở file JSON trên ra xem đã có dữ liệu chưa (hết bị {} chưa).")
        print("2. Nếu ĐÃ CÓ DATA ĐẸP, hãy đổi `TEST_MODE = False` ở đầu script này.")
        print("3. Chạy lại script để càn quét nốt 29 file còn lại!")


if __name__ == "__main__":
    main()