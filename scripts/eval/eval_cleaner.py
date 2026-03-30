from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pypdf import PdfReader

from pipeline.cleaner import clean_vietnamese_text
from scripts.eval.utils import mean, print_table, save_json

CV_DIR = Path(__file__).resolve().parents[2] / "data_eval" / "cv_synthetic"

VI_SET = set(
    "àáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ"
    "ÀÁẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬÈÉẺẼẸÊẾỀỂỄỆÌÍỈĨỊÒÓỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÙÚỦŨỤƯỨỪỬỮỰỲÝỶỸỴĐ"
)


def _extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _vi_char_ratio(text: str) -> float:
    alpha_chars = [c for c in text if c.isalpha()]
    vi_chars = [c for c in alpha_chars if c in VI_SET]
    return len(vi_chars) / max(len(alpha_chars), 1)


def main() -> None:
    pdf_files = sorted(CV_DIR.glob("*.pdf"))
    if not pdf_files:
        print(f"No PDF files found in {CV_DIR}")
        return

    per_file: list[dict] = []

    for pdf_path in pdf_files:
        raw = _extract_pdf_text(pdf_path)
        cleaned = clean_vietnamese_text(raw)

        original_len = len(raw)
        cleaned_len = len(cleaned)
        noise_removal_pct = (original_len - cleaned_len) / max(original_len, 1) * 100
        vi_ratio_before = _vi_char_ratio(raw)
        vi_ratio_after = _vi_char_ratio(cleaned)

        per_file.append({
            "file": pdf_path.name,
            "original_len": original_len,
            "cleaned_len": cleaned_len,
            "noise_removal_pct": round(noise_removal_pct, 4),
            "vi_ratio_before": round(vi_ratio_before, 4),
            "vi_ratio_after": round(vi_ratio_after, 4),
        })

    summary = {
        "files_processed": len(per_file),
        "avg_noise_removal_pct": round(mean([r["noise_removal_pct"] for r in per_file]), 4),
        "avg_vi_ratio_before": round(mean([r["vi_ratio_before"] for r in per_file]), 4),
        "avg_vi_ratio_after": round(mean([r["vi_ratio_after"] for r in per_file]), 4),
    }

    result = {"summary": summary, "per_file": per_file}
    out_path = save_json(result, "cleaner_eval.json")
    print(f"Saved: {out_path}\n")

    print_table(
        per_file,
        columns=["file", "original_len", "cleaned_len", "noise_removal_pct", "vi_ratio_after"],
    )

    print(f"\nSummary:")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
