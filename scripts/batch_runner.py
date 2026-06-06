"""
Batch Runner — Transparent AI Digital Twin.

Quét toàn bộ thư mục ``./storage/`` (đệ quy), chạy pipeline cho từng file
chưa được xử lý, rồi nạp kết quả vào Neo4j.

Có cơ chế:
  - Checkpoint: bỏ qua file đã có JSON output.
  - Rate Limiting: nghỉ giữa các file để tránh bị chặn API.
  - Fault Tolerance: lỗi ở 1 file không crash toàn bộ chương trình.
  - Báo cáo tổng kết cuối script.

Usage::

    python batch_runner.py
    python batch_runner.py --storage ./storage --output ./neo4j_ready --delay 15
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

load_dotenv(_ROOT / ".env", override=False)

from pipeline.config import settings, get_logger
from pipeline.main import process_single_file, save_neo4j_ready, _SUPPORTED_EXTS
from pipeline.neo4j_ingestion import Neo4jIngestor

logger = get_logger("batch_runner")

# ============================================================================
# Cấu hình mặc định
# ============================================================================

DEFAULT_STORAGE_DIR = Path("./storage")
DEFAULT_OUTPUT_DIR = Path("./neo4j_ready")
DEFAULT_DELAY_SECONDS = 15  # Thời gian nghỉ giữa các file (giây)


# ============================================================================
# Kết quả tổng kết
# ============================================================================

@dataclass
class BatchReport:
    """Tổng hợp kết quả chạy batch."""

    total_scanned: int = 0
    skipped: int = 0
    succeeded: int = 0
    failed: int = 0
    failed_files: List[str] = field(default_factory=list)

    def print_summary(self) -> None:
        """In bảng tổng kết ra màn hình."""
        width = 50
        logger.info("=" * width)
        logger.info("  BÁO CÁO TỔNG KẾT BATCH RUNNER")
        logger.info("=" * width)
        logger.info("  Tổng số file đã quét   : %d", self.total_scanned)
        logger.info("  Bỏ qua (đã xử lý)     : %d", self.skipped)
        logger.info("  Nạp mới thành công     : %d", self.succeeded)
        logger.info("  Thất bại               : %d", self.failed)
        if self.failed_files:
            logger.info("-" * width)
            logger.info("  Danh sách file lỗi:")
            for f in self.failed_files:
                logger.info("    • %s", f)
        logger.info("=" * width)


# ============================================================================
# Hàm quét thư mục và lọc file (Directory Scanner)
# ============================================================================

def scan_files(storage_dir: Path) -> List[Path]:
    """Duyệt đệ quy ``storage_dir`` và trả về danh sách file hỗ trợ.

    Args:
        storage_dir: Thư mục gốc chứa tài liệu (.docx, .pdf, .doc, .md).

    Returns:
        Danh sách Path tới các file hỗ trợ, đã sắp xếp.
    """
    if not storage_dir.is_dir():
        raise FileNotFoundError(f"Thư mục không tồn tại: {storage_dir}")

    files = sorted(
        f for f in storage_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in _SUPPORTED_EXTS
    )
    logger.info("Quét thư mục %s → tìm thấy %d file.", storage_dir, len(files))
    return files


def get_expected_json_path(file_path: Path, output_dir: Path) -> Path:
    """Trả về đường dẫn JSON output dự kiến cho một file nguồn.

    Quy ước: ``{output_dir}/{model_slug}/{stem}.json``
    """
    model_name = settings.PHOBERT_MODEL
    # Dùng cùng logic slug với pipeline.main
    from pipeline.main import _model_to_dirname
    model_slug = _model_to_dirname(model_name)
    return output_dir.resolve() / model_slug / (file_path.stem + ".json")


def filter_unprocessed(
    files: List[Path],
    output_dir: Path,
) -> tuple[List[Path], int]:
    """Lọc bỏ các file đã có JSON output (checkpoint).

    Returns:
        (danh sách file cần xử lý, số file đã bỏ qua)
    """
    pending: List[Path] = []
    skipped = 0

    for f in files:
        json_path = get_expected_json_path(f, output_dir)
        if json_path.exists():
            logger.info("Skipping %s — Already processed (%s)", f.name, json_path)
            skipped += 1
        else:
            pending.append(f)

    logger.info(
        "Checkpoint: %d file cần xử lý, %d file đã bỏ qua.",
        len(pending), skipped,
    )
    return pending, skipped


# ============================================================================
# Vòng lặp xử lý chính (Execution Loop)
# ============================================================================

def run_batch(
    storage_dir: Path = DEFAULT_STORAGE_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    delay_seconds: int = DEFAULT_DELAY_SECONDS,
) -> BatchReport:
    """Chạy batch pipeline + nạp Neo4j cho toàn bộ file trong ``storage_dir``.

    Args:
        storage_dir: Thư mục gốc chứa tài liệu.
        output_dir: Thư mục lưu JSON output (neo4j_ready).
        delay_seconds: Số giây nghỉ giữa mỗi file (rate limiting).

    Returns:
        ``BatchReport`` chứa thống kê chi tiết.
    """
    report = BatchReport()

    # --- 1. Quét và lọc file ---
    all_files = scan_files(storage_dir)
    report.total_scanned = len(all_files)

    pending, skipped = filter_unprocessed(all_files, output_dir)
    report.skipped = skipped

    if not pending:
        logger.info("Không có file mới cần xử lý. Kết thúc.")
        report.print_summary()
        return report

    total = len(pending)

    # --- 2. Mở kết nối Neo4j (dùng context manager) ---
    # Hàm ingest sử dụng MERGE để tự động upsert, không tạo node trùng lặp.
    with Neo4jIngestor() as ingestor:
        ingestor.setup_schema()

        # --- 3. Vòng lặp xử lý ---
        for idx, file_path in enumerate(pending, start=1):
            logger.info(
                "Processing file %d/%d: %s",
                idx, total, file_path.name,
            )

            try:
                # Bước 1: Chạy pipeline (Parse → Clean → Chunk → Extract → Vectorize)
                results = process_single_file(file_path)

                if not results:
                    logger.warning(
                        "File %s không trả về kết quả (có thể đã bị skip nội bộ).",
                        file_path.name,
                    )
                    report.skipped += 1
                    continue

                # Lưu JSON output vào neo4j_ready/
                saved_path = save_neo4j_ready(results, file_path.name, base_dir=output_dir)
                logger.info("Đã lưu JSON → %s", saved_path)

                # Bước 2: Nạp vào Neo4j.
                # Neo4jIngestor dùng lệnh MERGE để tự động hợp nhất (upsert)
                # các thực thể trùng lặp vào mạng lưới đồ thị hiện có,
                # không tạo node/relationship bị duplicate.
                n_chunks = ingestor._ingest_file(saved_path)
                logger.info(
                    "Đã nạp %d chunks vào Neo4j cho %s.",
                    n_chunks, file_path.name,
                )

                report.succeeded += 1

            except Exception as e:
                logger.error(
                    "LỖI khi xử lý file %s: %s",
                    file_path.name, e,
                    exc_info=True,
                )
                report.failed += 1
                report.failed_files.append(file_path.name)

            # Rate Limiting: nghỉ giữa các file để tránh bị chặn API
            if idx < total:
                logger.info(
                    "Rate limiting — nghỉ %d giây trước file tiếp theo…",
                    delay_seconds,
                )
                time.sleep(delay_seconds)

    # --- 4. Báo cáo tổng kết ---
    report.print_summary()
    return report


# ============================================================================
# CLI Entry Point
# ============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch Runner — Quét storage, chạy pipeline, nạp Neo4j.",
    )
    parser.add_argument(
        "--storage",
        type=Path,
        default=DEFAULT_STORAGE_DIR,
        help=f"Thư mục gốc chứa tài liệu (mặc định: {DEFAULT_STORAGE_DIR}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Thư mục lưu JSON output (mặc định: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=DEFAULT_DELAY_SECONDS,
        help=f"Số giây nghỉ giữa mỗi file — rate limiting (mặc định: {DEFAULT_DELAY_SECONDS}).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    logger.info("=" * 60)
    logger.info("  BATCH RUNNER — Transparent AI Digital Twin")
    logger.info("  Storage : %s", args.storage.resolve())
    logger.info("  Output  : %s", args.output.resolve())
    logger.info("  Delay   : %d giây", args.delay)
    logger.info("=" * 60)

    report = run_batch(
        storage_dir=args.storage,
        output_dir=args.output,
        delay_seconds=args.delay,
    )

    # Exit code phản ánh kết quả
    if report.failed > 0:
        sys.exit(1)
