"""
test_engine.py — Kiểm thử phân quyền truy cập Public / Private Data.

Chỉ test duy nhất một thứ: cơ chế kiểm soát truy cập của DigitalTwinInterviewEngine.
Không ingest file, không test vector search, không side-effects.

Flow:
  TC-1  Public mode  (chưa có CONNECTED_TO)   → engine chỉ dùng public_data
  TC-2  Pending mode (status = 'pending')     → vẫn bị chặn private_data
  TC-3  Private mode (status = 'accepted')    → engine truy cập private_data_blob
  TC-4  Revoke       (xóa relationship)       → rơi về public mode
  FINAL Cleanup toàn bộ test nodes
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

load_dotenv(_ROOT / ".env", override=False)

from pipeline.config import get_logger, settings
from pipeline.hybrid_query_engine import DigitalTwinInterviewEngine
from pipeline.neo4j_client import get_neo4j_driver

logger = get_logger("test_engine")

# ── Hằng số test ─────────────────────────────────────────────────────────────

ORG_TEST_ID  = "ORG_ACCESS_TEST"
PER_TEST_ID  = "PER_ACCESS_TEST"

# Câu hỏi chứa thông tin chỉ có trong private_data_blob
QUESTION_SALARY   = "Mức lương mong muốn của bạn là bao nhiêu?"
QUESTION_BLACKLIST = "Bạn có tổ chức nào không muốn làm việc không?"

# Payload private — chỉ engine trong private mode mới trả về
PRIVATE_PAYLOAD = {
    "salary_expectation": "USD 4,500/tháng",
    "salary_expectation_usd": 4500,
    "blacklist_orgs": ["CôngTyXYZ", "OutsourcingABC"],
    "project_technical_secrets": "Đã implement Flink stateful CEP với RocksDB state backend.",
    "note": "Private data dùng cho test phân quyền — không phải production.",
}

PUBLIC_PAYLOAD = {
    "full_name": "Nguyễn Test Access",
    "professional_summary": (
        "Senior Data Engineer với kinh nghiệm Flink, ClickHouse tại Fintech."
    ),
    "skills": ["Apache Flink", "ClickHouse", "Go", "Python"],
    "availability": "Open_for_offers",
}


# ── Kết quả test ─────────────────────────────────────────────────────────────

class Verdict(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"


@dataclass
class TestResult:
    name: str
    verdict: Verdict
    detail: str = ""

    def __str__(self) -> str:
        icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}[self.verdict.value]
        detail = f"\n     {self.detail}" if self.detail else ""
        return f"  {icon} {self.name}{detail}"


# ── Neo4j helpers ─────────────────────────────────────────────────────────────

def _setup_test_nodes(driver) -> None:
    """Tạo Org + Personnel test với đầy đủ public/private payload."""
    driver.execute_query(
        """
        MERGE (o:Organization {id: $org_id})
        SET   o.public_name = 'Test Organization'

        MERGE (p:Personnel {id: $per_id})
        SET   p.public_name          = $pub_name,
              p.public_full_name     = $pub_name,
              p.public_summary       = $pub_summary,
              p.public_professional_summary = $pub_summary,
              p.public_skills        = $pub_skills,
              p.public_availability  = $pub_availability,
              p.private_data_blob    = $private_blob
        """,
        org_id          = ORG_TEST_ID,
        per_id          = PER_TEST_ID,
        pub_name        = PUBLIC_PAYLOAD["full_name"],
        pub_summary     = PUBLIC_PAYLOAD["professional_summary"],
        pub_skills      = json.dumps(PUBLIC_PAYLOAD["skills"], ensure_ascii=False),
        pub_availability= PUBLIC_PAYLOAD["availability"],
        private_blob    = json.dumps(PRIVATE_PAYLOAD, ensure_ascii=False),
    )
    logger.info("[setup] Nodes %s, %s đã sẵn sàng.", ORG_TEST_ID, PER_TEST_ID)


def _set_relationship(driver, status: str | None) -> None:
    """Tạo / cập nhật / xóa CONNECTED_TO relationship."""
    if status is None:
        driver.execute_query(
            """
            MATCH (o:Organization {id: $org_id})-[r:CONNECTED_TO]->(p:Personnel {id: $per_id})
            DELETE r
            """,
            org_id=ORG_TEST_ID, per_id=PER_TEST_ID,
        )
        logger.info("[setup] Relationship đã bị xóa.")
    else:
        driver.execute_query(
            """
            MATCH (o:Organization {id: $org_id}), (p:Personnel {id: $per_id})
            MERGE (o)-[r:CONNECTED_TO]->(p)
            SET r.status = $status, r.updated_at = datetime()
            """,
            org_id=ORG_TEST_ID, per_id=PER_TEST_ID, status=status,
        )
        logger.info("[setup] Relationship status = '%s'.", status)


def _cleanup(driver) -> None:
    driver.execute_query(
        """
        MATCH (o:Organization {id: $org_id})
        OPTIONAL MATCH (o)-[r:CONNECTED_TO]->(p:Personnel {id: $per_id})
        DETACH DELETE o, p
        """,
        org_id=ORG_TEST_ID, per_id=PER_TEST_ID,
    )
    logger.info("[cleanup] Đã xóa toàn bộ test nodes.")


# ── Assertion helpers ─────────────────────────────────────────────────────────

def _is_private_mode(response: Any) -> bool:
    if isinstance(response, dict):
        return bool(response.get("is_private_mode"))
    return False


def _answer_text(response: Any) -> str:
    if isinstance(response, dict):
        return str(response.get("answer", response))
    return str(response)


def _contains_private_signal(text: str) -> bool:
    """Kiểm tra answer có lộ thông tin private không."""
    signals = [
        "4,500", "4500",             # salary_expectation_usd
        "CôngTyXYZ",                 # blacklist_orgs
        "OutsourcingABC",
        "Flink stateful CEP",        # project_technical_secrets
    ]
    return any(s.lower() in text.lower() for s in signals)


def _log_response(label: str, response: Any) -> None:
    """In chi tiết response theo từng bước để dễ trace."""
    mode = "PRIVATE" if _is_private_mode(response) else "PUBLIC"
    answer = _answer_text(response)
    rel_status = response.get("rel_status", "—") if isinstance(response, dict) else "—"

    print(f"\n  ── {label} ──")
    print(f"  Mode       : {mode}")
    print(f"  Rel status : {rel_status}")
    print(f"  Answer     :\n{textwrap.indent(textwrap.fill(answer, 72), '    ')}")

    # Log data sources nếu engine cung cấp
    if isinstance(response, dict) and response.get("reasoning"):
        r = response["reasoning"]
        print(f"  Data src   : {r.get('data_source', '—')}")
        print(f"  Priv unlock: {r.get('private_unlocked', '—')}")


# ── Test cases ────────────────────────────────────────────────────────────────

def _tc1_no_relationship(engine: DigitalTwinInterviewEngine) -> TestResult:
    """TC-1: Không có CONNECTED_TO → chỉ được dùng public data."""
    label = "TC-1 · Public (no relationship)"
    logger.info("[%s] Gọi engine...", label)

    resp = engine.answer_interview(
        org_id=ORG_TEST_ID,
        personnel_id=PER_TEST_ID,
        interview_question=QUESTION_SALARY,
    )
    _log_response(label, resp)

    answer = _answer_text(resp)
    has_private = _contains_private_signal(answer)
    in_private_mode = _is_private_mode(resp)

    if in_private_mode or has_private:
        return TestResult(
            label, Verdict.FAIL,
            f"Engine trả về private data khi chưa có relationship. "
            f"is_private_mode={in_private_mode}, has_private_signal={has_private}",
        )
    return TestResult(label, Verdict.PASS, "Chỉ public data, không lộ private.")


def _tc2_pending_relationship(engine: DigitalTwinInterviewEngine) -> TestResult:
    """TC-2: status = 'pending' → vẫn bị chặn private data."""
    label = "TC-2 · Pending (status=pending)"
    logger.info("[%s] Gọi engine...", label)

    resp = engine.answer_interview(
        org_id=ORG_TEST_ID,
        personnel_id=PER_TEST_ID,
        interview_question=QUESTION_SALARY,
    )
    _log_response(label, resp)

    answer = _answer_text(resp)
    has_private = _contains_private_signal(answer)
    in_private_mode = _is_private_mode(resp)

    if in_private_mode or has_private:
        return TestResult(
            label, Verdict.FAIL,
            f"Engine mở private data khi status='pending'. "
            f"is_private_mode={in_private_mode}",
        )
    return TestResult(label, Verdict.PASS, "Đúng — pending vẫn bị chặn private.")


def _tc3_accepted_relationship(engine: DigitalTwinInterviewEngine) -> TestResult:
    """TC-3: status = 'accepted' → engine được phép truy cập private_data_blob."""
    label = "TC-3 · Private (status=accepted)"
    logger.info("[%s] Gọi engine...", label)

    resp = engine.answer_interview(
        org_id=ORG_TEST_ID,
        personnel_id=PER_TEST_ID,
        interview_question=QUESTION_SALARY,
    )
    _log_response(label, resp)

    answer = _answer_text(resp)
    in_private_mode = _is_private_mode(resp)
    has_private = _contains_private_signal(answer)

    if not in_private_mode:
        return TestResult(
            label, Verdict.FAIL,
            "Engine không bật private mode dù đã accepted.",
        )
    if not has_private:
        return TestResult(
            label, Verdict.WARN,
            "is_private_mode=True nhưng answer không chứa salary '4500'. "
            "Kiểm tra LLM có đọc private_data_blob không.",
        )
    return TestResult(label, Verdict.PASS, "Private data được trả về đúng.")


def _tc4_revoke_then_public(engine: DigitalTwinInterviewEngine, driver) -> TestResult:
    """TC-4: Xóa relationship → rơi về public mode ngay lập tức."""
    label = "TC-4 · Revoke → Public"
    _set_relationship(driver, None)
    logger.info("[%s] Đã xóa relationship, gọi engine...", label)

    resp = engine.answer_interview(
        org_id=ORG_TEST_ID,
        personnel_id=PER_TEST_ID,
        interview_question=QUESTION_BLACKLIST,
    )
    _log_response(label, resp)

    answer = _answer_text(resp)
    in_private_mode = _is_private_mode(resp)
    has_private = _contains_private_signal(answer)

    if in_private_mode or has_private:
        return TestResult(
            label, Verdict.FAIL,
            "Engine vẫn trả về private data sau khi relationship bị xóa. "
            "Kiểm tra cache / session state trong engine.",
        )
    return TestResult(label, Verdict.PASS, "Đúng — private bị chặn sau khi revoke.")


# ── Runner ────────────────────────────────────────────────────────────────────

def _print_summary(results: list[TestResult]) -> None:
    total = len(results)
    passed = sum(1 for r in results if r.verdict == Verdict.PASS)
    failed = sum(1 for r in results if r.verdict == Verdict.FAIL)
    warned = sum(1 for r in results if r.verdict == Verdict.WARN)

    print("\n" + "═" * 60)
    print("  KẾT QUẢ KIỂM THỬ PHÂN QUYỀN TRUY CẬP")
    print("═" * 60)
    for r in results:
        print(r)
    print("─" * 60)
    print(f"  Tổng: {total}  |  ✅ {passed} PASS  |  ❌ {failed} FAIL  |  ⚠️  {warned} WARN")
    print("═" * 60)

    if failed > 0:
        print("\n  ❌ CÓ TEST CASE THẤT BẠI — kiểm tra log phía trên.")
    elif warned > 0:
        print("\n  ⚠️  Tất cả PASS nhưng có cảnh báo — xem xét thêm.")
    else:
        print("\n  ✅ Toàn bộ test PASS — cơ chế phân quyền hoạt động đúng.")


def run_access_control_test() -> None:
    print("\n" + "═" * 60)
    print("  TEST PHÂN QUYỀN PUBLIC / PRIVATE — Digital Twin")
    print(f"  Org: {ORG_TEST_ID}  |  Per: {PER_TEST_ID}")
    print("═" * 60)

    driver = get_neo4j_driver()
    logger.info("Kết nối Neo4j thành công.")

    results: list[TestResult] = []

    try:
        _setup_test_nodes(driver)

        with DigitalTwinInterviewEngine() as engine:

            # TC-1: không có relationship
            _set_relationship(driver, None)
            results.append(_tc1_no_relationship(engine))

            # TC-2: relationship pending
            _set_relationship(driver, "pending")
            results.append(_tc2_pending_relationship(engine))

            # TC-3: relationship accepted
            _set_relationship(driver, "accepted")
            results.append(_tc3_accepted_relationship(engine))

            # TC-4: revoke relationship → kiểm tra không cache sai
            results.append(_tc4_revoke_then_public(engine, driver))

    finally:
        print("\n[cleanup] Đang dọn dẹp test nodes...")
        try:
            _cleanup(driver)
        except Exception as e:
            logger.error("Cleanup lỗi: %s", e)
        try:
            driver.close()
        except Exception:
            pass

    _print_summary(results)

    # Exit code non-zero nếu có FAIL — tiện cho CI/CD
    failed = sum(1 for r in results if r.verdict == Verdict.FAIL)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    run_access_control_test()
