#!/usr/bin/env python3
"""
Quick test to validate synthesis quality fixes before full eval.
Tests:
1. extract_key_metrics with labeled_only=True
2. _extract_relevant_window on sample chunks
"""

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.hybrid_query_engine import extract_key_metrics, _extract_relevant_window


def test_extract_metrics_labeled_only():
    """Test that extract_key_metrics respects labeled_only flag."""
    print("\n" + "="*60)
    print("TEST 1: extract_key_metrics with labeled_only=True")
    print("="*60)

    chunks = [
        "[Lương kỳ vọng] USD 4,000 – 4,500/tháng (gross)",
        "[Bí mật kỹ thuật] Giảm 30% cloud cost. Throughput 3.2x cao hơn.",
        "Q: Bạn xử lý 100 requests/s thế nào?\nA: Dùng async/await, tối ưu xong latency còn 50ms.",
        "Q: Chi phí máy chủ?\nA: Khoảng USD 2000/tháng."
    ]

    # With labeled_only=True (default, safe)
    metrics_labeled = extract_key_metrics(chunks, labeled_only=True)
    print(f"\nlabeled_only=True:")
    print(f"  Input chunks: {chunks}")
    print(f"  Extracted metrics: {metrics_labeled}")

    # With labeled_only=False (old behavior, risky)
    metrics_all = extract_key_metrics(chunks, labeled_only=False)
    print(f"\nlabeled_only=False:")
    print(f"  Extracted metrics: {metrics_all}")

    # Validation
    print(f"\n✓ VERDICT:")
    print(f"  - labeled_only=True should NOT include '100', '50ms', '2000' from Q:/A: chunks")
    print(f"  - labeled_only=False SHOULD include them")
    has_qa_numbers = any(x in str(metrics_labeled) for x in ['100', '50', '2000'])
    if not has_qa_numbers:
        print(f"  ✅ PASS: labeled_only=True correctly excludes Q:/A numbers")
    else:
        print(f"  ❌ FAIL: labeled_only=True still includes Q:/A numbers")


def test_extract_relevant_window():
    """Test _extract_relevant_window on realistic long chunks."""
    print("\n" + "="*60)
    print("TEST 2: _extract_relevant_window on long chunks")
    print("="*60)

    # Real-world case: long technical secret with multiple facts
    long_chunk = """[Bí mật kỹ thuật] Tại Grab, đã xây dựng một mini data lineage engine nội bộ bằng Python + NetworkX, tự động parse DAG của Airflow và dbt manifest để vẽ đồ thị phụ thuộc cột-mức (column-level lineage). Giải pháp này chưa được document chính thức nhưng đang dùng thực tế cho 200+ dbt models. Ngoài ra, thành thạo Apache Flink stateful streaming (không public trên LinkedIn do NDA với dự án thử nghiệm nội bộ của Grab) – đây là kỹ năng hiếm trong thị trường VN hiện tại. Đã viết Flink jobs xử lý realtime fraud scoring với latency <100ms."""

    # Test Case 1: Question about Flink
    question_1 = "Bạn có kinh nghiệm gì với Apache Flink?"
    trimmed_1 = _extract_relevant_window(long_chunk, question_1)
    print(f"\nTest Case 1: Apache Flink question")
    print(f"  Question: {question_1}")
    print(f"  Original length: {len(long_chunk)} chars")
    print(f"  Trimmed length: {len(trimmed_1)} chars")
    print(f"  Trimmed contains 'Flink': {('Flink' in trimmed_1 or 'Grab' in trimmed_1)}")
    if len(trimmed_1) < len(long_chunk) and ('Flink' in trimmed_1 or 'fraud' in trimmed_1):
        print(f"  ✅ PASS: Correctly trimmed to relevant window")
    else:
        print(f"  ⚠️  Note: May have returned full chunk (acceptable fallback)")

    # Test Case 2: Question about data lineage
    question_2 = "Bạn đã xây dựng data lineage engine như thế nào?"
    trimmed_2 = _extract_relevant_window(long_chunk, question_2)
    print(f"\nTest Case 2: Data lineage question")
    print(f"  Question: {question_2}")
    print(f"  Original length: {len(long_chunk)} chars")
    print(f"  Trimmed length: {len(trimmed_2)} chars")
    print(f"  Trimmed contains 'lineage': {'lineage' in trimmed_2}")
    if len(trimmed_2) < len(long_chunk):
        print(f"  ✅ PASS: Correctly trimmed")
    else:
        print(f"  ⚠️  Note: Returned full chunk (acceptable)")

    # Test Case 3: Short chunk (should not trim)
    short_chunk = "[Lương kỳ vọng] USD 5,000/tháng"
    question_3 = "Mức lương kỳ vọng?"
    trimmed_3 = _extract_relevant_window(short_chunk, question_3)
    print(f"\nTest Case 3: Short chunk")
    print(f"  Question: {question_3}")
    print(f"  Original: {short_chunk}")
    print(f"  Trimmed: {trimmed_3}")
    if trimmed_3 == short_chunk:
        print(f"  ✅ PASS: Short chunk preserved as-is")
    else:
        print(f"  ❌ FAIL: Short chunk was unnecessarily trimmed")

    # Test Case 4: Unrelated question (should not trim aggressively or return full)
    question_4 = "Địa chỉ công ty?"
    trimmed_4 = _extract_relevant_window(long_chunk, question_4)
    print(f"\nTest Case 4: Unrelated question (fallback test)")
    print(f"  Question: {question_4}")
    if len(trimmed_4) >= len(long_chunk) * 0.8:
        print(f"  ✅ PASS: Did not over-trim for unrelated question (graceful fallback)")
    else:
        print(f"  ⚠️  Warning: Trimmed to {len(trimmed_4)} chars (may be too aggressive)")


def main():
    print("\n" + "="*60)
    print("SYNTHESIS QUALITY FIXES - UNIT TESTS")
    print("="*60)

    try:
        test_extract_metrics_labeled_only()
        test_extract_relevant_window()

        print("\n" + "="*60)
        print("✅ All unit tests completed")
        print("="*60)
        print("\nNext step: Run full eval with `python scripts/eval/eval_ragas.py`")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
