"""
Pipeline Orchestrator — Transparent AI Digital Twin.

Chạy tuần tự 5 bước cho một hoặc nhiều file đầu vào:
  Parse → Clean → Chunk → Extract → Vectorize

Hỗ trợ 3 loại tài liệu: CV, SOP, PROJECT.
Tự detect core_entity và doc_type từ nội dung + đường dẫn.

Usage:
    python -m pipeline.main <file_or_folder> [--output results.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from pipeline.config import settings, get_logger
from pipeline.parser import parse_document
from pipeline.cleaner import clean_vietnamese_text
from pipeline.chunker import chunk_cleaned_text
from pipeline.extractor import extract_knowledge
from pipeline.vectorizer import prepare_for_neo4j

logger = get_logger("pipeline.main")

# Các đuôi file được hỗ trợ
_SUPPORTED_EXTS = {".pdf", ".docx", ".doc", ".md"}


def _detect_core_entity(cleaned_text: str, doc_hint: str = "") -> str:
    """Phát hiện chủ thể lõi từ nội dung văn bản đã clean.

    Tuỳ loại tài liệu:
      - CV:      Tên người ở dòng đầu (2–5 từ viết hoa).
      - SOP:     Tên quy trình (dòng chứa "SOP", "Quy trình", "Quy chuẩn", …).
      - PROJECT: Tên dự án (dòng chứa "Dự án", "Project", hoặc dòng đầu tiên).

    Args:
        cleaned_text: Văn bản đã clean.
        doc_hint: Gợi ý loại tài liệu từ đường dẫn ("cv", "sop", "project").
    """
    hint = doc_hint.lower()

    # --- SOP detection ---
    if hint == "sop":
        for line in cleaned_text.split("\n"):
            line = line.strip().strip("*#_")
            if not line or len(line) < 3:
                continue
            # Dòng chứa từ khóa quy trình
            if re.search(r"(?i)(SOP|quy trình|quy chuẩn|hướng dẫn|vận hành)", line):
                return line
        # Fallback: dòng đầu tiên có ý nghĩa
        for line in cleaned_text.split("\n"):
            line = line.strip().strip("*#_")
            if line and len(line) >= 5:
                return line
        return ""

    # --- PROJECT detection ---
    if hint == "project":
        for line in cleaned_text.split("\n"):
            line = line.strip().strip("*#_")
            if not line or len(line) < 3:
                continue
            if re.search(r"(?i)(dự án|project|kế hoạch|chương trình)", line):
                return line
        # Fallback: dòng đầu tiên
        for line in cleaned_text.split("\n"):
            line = line.strip().strip("*#_")
            if line and len(line) >= 5:
                return line
        return ""

    # --- CV detection (default) ---
    for line in cleaned_text.split("\n"):
        line = line.strip().strip("*#_")
        if not line or len(line) < 3:
            continue
        if any(c in line for c in ("@", "http", "://", "+84", "**")):
            continue
        words = line.split()
        if 2 <= len(words) <= 5 and all(w[0].isupper() for w in words):
            return line
        break
    return ""


def _infer_doc_hint(file_path: Path) -> str:
    """Suy luận doc_hint từ đường dẫn thư mục cha.

    Ví dụ: storage/cv/file.docx → "cv", storage/sop/file.docx → "sop".
    """
    parent = file_path.parent.name.lower()
    if parent in ("cv", "sop", "project"):
        return parent
    return ""


def _neo4j_ready_path(source_file: str, model_name: str | None = None) -> Path:
    """Trả về đường dẫn neo4j_ready JSON dự kiến cho một source file."""
    if model_name is None:
        model_name = settings.PHOBERT_MODEL
    model_dir = _model_to_dirname(model_name)
    return (Path("./neo4j_ready").resolve() / model_dir
            / (Path(source_file).stem + ".json"))


def process_single_file(
    file_path: Path,
    core_entity: str = "",
    doc_hint: str = "",
) -> List[Dict[str, Any]]:
    """Chạy toàn bộ pipeline cho một file.

    Args:
        file_path: Đường dẫn tới file tài liệu.
        core_entity: Tên chủ thể lõi (tự detect nếu rỗng).
        doc_hint: Gợi ý loại tài liệu ("cv", "sop", "project").

    Returns:
        Danh sách dict (mỗi chunk đã qua 5 bước), sẵn sàng nạp Neo4j/ChromaDB.
    """
    # --- Skip nếu output đã tồn tại ---
    neo4j_out = _neo4j_ready_path(file_path.name)
    if neo4j_out.exists():
        logger.info("Skipping %s — Already processed (%s)", file_path.name, neo4j_out)
        return []
    logger.info("=" * 60)
    logger.info("BẮT ĐẦU XỬ LÝ: %s", file_path.name)
    logger.info("=" * 60)
    t0 = time.perf_counter()

    # Bước 1: Parse
    logger.info("[1/5] Parse document → Markdown")
    markdown_text = parse_document(file_path)
    logger.info("  → %d ký tự Markdown.", len(markdown_text))

    # Bước 2: Clean
    logger.info("[2/5] Clean & chuẩn hóa tiếng Việt")
    cleaned_text = clean_vietnamese_text(markdown_text)
    logger.info("  → %d ký tự sau clean.", len(cleaned_text))

    # Bước 3: Chunk
    logger.info("[3/5] Semantic Chunking (≤256 tokens)")
    chunks = chunk_cleaned_text(cleaned_text)
    logger.info("  → %d chunk.", len(chunks))

    # Phát hiện core_entity nếu chưa có
    if not doc_hint:
        doc_hint = _infer_doc_hint(file_path)
    if not core_entity:
        core_entity = _detect_core_entity(cleaned_text, doc_hint=doc_hint)
    if core_entity:
        logger.info("Core entity: %s (hint=%s)", core_entity, doc_hint or "auto")
    else:
        logger.warning("Không phát hiện được core entity — coreference sẽ bị hạn chế.")

    # Bước 4 + 5: Extract & Vectorize cho từng chunk
    results: List[Dict[str, Any]] = []
    for idx, chunk in enumerate(chunks, start=1):
        logger.info("[4-5/5] Chunk %d/%d — Extract + Vectorize", idx, len(chunks))
        try:
            extraction = extract_knowledge(chunk, core_entity=core_entity)
        except RuntimeError as exc:
            logger.error("  ✗ Bỏ qua chunk %d: %s", idx, exc)
            continue

        prepared = prepare_for_neo4j(chunk, extraction)
        prepared["source_file"] = file_path.name
        prepared["chunk_index"] = idx
        results.append(prepared)

    elapsed = time.perf_counter() - t0
    logger.info(
        "HOÀN TẤT %s — %d/%d chunk thành công (%.1fs).",
        file_path.name,
        len(results),
        len(chunks),
        elapsed,
    )
    return results


def run_pipeline(
    input_path: str | Path,
    output_path: str | Path | None = None,
    core_entity: str = "",
) -> List[Dict[str, Any]]:
    """Chạy pipeline cho file hoặc thư mục.

    Args:
        input_path: Đường dẫn tới file hoặc folder chứa tài liệu.
        output_path: (Tùy chọn) Nơi ghi kết quả JSON.
        core_entity: Tên chủ thể lõi (tự detect nếu rỗng).

    Returns:
        Tổng hợp kết quả từ tất cả file.
    """
    input_path = Path(input_path).resolve()
    all_results: List[Dict[str, Any]] = []

    if input_path.is_file():
        files = [input_path]
    elif input_path.is_dir():
        # Tìm file trong thư mục hiện tại VÀ các thư mục con (cv, sop, project)
        files = sorted(
            f for f in input_path.rglob("*") if f.suffix.lower() in _SUPPORTED_EXTS
        )
        logger.info("Tìm thấy %d file trong %s.", len(files), input_path)
    else:
        raise FileNotFoundError(f"Không tồn tại: {input_path}")

    skipped = 0
    for file in files:
        try:
            results = process_single_file(file, core_entity=core_entity)
            if not results:
                skipped += 1
                continue
            all_results.extend(results)
        except Exception as exc:
            logger.error("Lỗi khi xử lý %s: %s", file.name, exc)

    logger.info(
        "TỔNG KẾT: %d chunk từ %d file (%d skipped).",
        len(all_results), len(files), skipped,
    )

    # Ghi output nếu được yêu cầu
    if output_path:
        out = Path(output_path)
        # Embedding quá dài → lưu riêng flag
        serializable = _make_serializable(all_results)
        out.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Đã ghi kết quả vào %s.", out)

    # Lưu Neo4j-ready JSON phân loại theo embedding model
    saved_paths: List[Path] = []
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in all_results:
        src = r.get("source_file", "unknown")
        groups.setdefault(src, []).append(r)
    for src_name, group_results in groups.items():
        saved = save_neo4j_ready(group_results, src_name)
        saved_paths.append(saved)
    if saved_paths:
        logger.info("Neo4j-ready files: %s", [str(p) for p in saved_paths])

    return all_results


# ============================================================================
# Neo4j-ready JSON Saver
# ============================================================================

_MODEL_SLUG_MAP = {
    "vinai/phobert-base-v2": "phobert-v2",
    "vinai/phobert-base": "phobert-v1",
    "BAAI/bge-m3": "bge-m3",
    "intfloat/multilingual-e5-large": "e5-large-v2",
}


def _model_to_dirname(model_name: str) -> str:
    """Chuyển tên model thành tên thư mục thân thiện.

    Ví dụ: 'vinai/phobert-base-v2' → 'phobert-v2'
    """
    if model_name in _MODEL_SLUG_MAP:
        return _MODEL_SLUG_MAP[model_name]
    # Fallback: lấy phần sau '/', thay ký tự không hợp lệ
    slug = model_name.split("/")[-1].lower()
    slug = slug.replace(" ", "-")
    return slug


def save_neo4j_ready(
    results: List[Dict[str, Any]],
    source_file: str | Path,
    base_dir: str | Path = "./neo4j_ready",
    model_name: str | None = None,
) -> Path:
    """Lưu kết quả pipeline thành JSON phân loại theo embedding model.

    Cấu trúc::

        neo4j_ready/
        ├── phobert-v2/
        │   └── {base_filename}.json
        └── ...

    Args:
        results: Danh sách dict đầu ra từ pipeline (có embedding đầy đủ).
        source_file: Tên hoặc path file nguồn (để tạo tên file JSON).
        base_dir: Thư mục gốc (mặc định ``./neo4j_ready``).
        model_name: Tên embedding model. Mặc định lấy từ ``settings.PHOBERT_MODEL``.

    Returns:
        ``Path`` tuyệt đối tới file JSON đã lưu.
    """
    if model_name is None:
        model_name = settings.PHOBERT_MODEL

    model_dir = _model_to_dirname(model_name)
    out_dir = Path(base_dir).resolve() / model_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    base_filename = Path(source_file).stem + ".json"
    out_file = out_dir / base_filename

    out_file.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Đã lưu Neo4j-ready JSON → %s", out_file)
    return out_file


def _make_serializable(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rút gọn embedding để JSON output không quá lớn."""
    out = []
    for r in results:
        item = {**r}
        emb = item.get("embedding", [])
        # Chỉ giữ 5 phần tử đầu + dim count để tiết kiệm dung lượng
        item["embedding_preview"] = emb[:5] if emb else []
        item["embedding_dim"] = len(emb)
        del item["embedding"]
        out.append(item)
    return out


# ============================================================================
# CLI
# ============================================================================

def main() -> None:
    """Entry-point khi chạy ``python -m pipeline.main``."""
    parser = argparse.ArgumentParser(
        description="Transparent AI Digital Twin — Data Processing Pipeline",
    )
    parser.add_argument(
        "input",
        help="Đường dẫn tới file (.pdf/.docx/.md) hoặc folder chứa tài liệu.",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="File JSON để ghi kết quả (mặc định: không ghi).",
    )
    parser.add_argument(
        "--core-entity",
        default="",
        help="Tên chủ thể lõi (vd: 'Nguyễn Hoài Tưởng' / 'SOP-02 ...' / 'NovaFlow ERP'). Mặc định: tự detect.",
    )
    args = parser.parse_args()

    run_pipeline(args.input, args.output, core_entity=args.core_entity)


if __name__ == "__main__":
    main()
