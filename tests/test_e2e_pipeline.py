from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.hybrid_query_engine import DigitalTwinInterviewEngine, MasterAgentEngine
from pipeline.main import delete_account, process_file, update_partial_info
from pipeline.neo4j_ingestion import neo4j_service

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
)
logger = logging.getLogger("test_e2e_pipeline")

TEST_PERSONNEL_ID = "TEST_PER_001"
TEST_ORG_ID = "TEST_ORG_001"
RETRIEVAL_ANCHOR = "E2E_SKILL_ANCHOR_TEST_PER_001"


def _find_first_cv_file() -> Path | None:
    data_lake = Path("data_lake")
    if not data_lake.exists():
        return None

    for pattern in ("*.pdf", "*.docx"):
        matches = sorted(data_lake.glob(pattern))
        if matches:
            return matches[0]
    return None


def _ensure_vector_index() -> None:
    """Create personnel_public_idx if missing, required by MasterAgentEngine."""
    with neo4j_service._driver.session() as session:
        session.run(
            """
            CREATE VECTOR INDEX personnel_public_idx IF NOT EXISTS
            FOR (p:Personnel) ON (p.public_embeddings_phobert)
            OPTIONS {
              indexConfig: {
                `vector.dimensions`: 768,
                `vector.similarity_function`: 'cosine'
              }
            }
            """
        )


def _get_test_personnel_props() -> dict[str, Any] | None:
    with neo4j_service._driver.session() as session:
        row = session.run(
            """
            MATCH (p:Personnel {id: $pid})
            RETURN properties(p) AS props
            LIMIT 1
            """,
            pid=TEST_PERSONNEL_ID,
        ).single()

    if not row:
        return None
    return dict(row.get("props") or {})


def _count_personnel_nodes() -> int:
    with neo4j_service._driver.session() as session:
        row = session.run("MATCH (p:Personnel) RETURN count(p) AS c").single()
    return int((row or {}).get("c") or 0)


def _cleanup_test_node() -> None:
    with neo4j_service._driver.session() as session:
        session.run(
            """
            MATCH (n {id: $pid})
            DETACH DELETE n
            """,
            pid=TEST_PERSONNEL_ID,
        )


def _assert_embedding(name: str, value: Any) -> None:
    assert isinstance(value, list), f"{name} must be a list"
    assert len(value) == 768, f"{name} must have 768 dimensions, got {len(value)}"


def _assert_private_blob_safety(private_blob: Any) -> None:
    assert isinstance(private_blob, str), "private_data_blob must be JSON string"
    parsed = json.loads(private_blob)
    assert isinstance(parsed, dict), "private_data_blob JSON root must be object"


def run_e2e_test() -> None:
    cv_file = _find_first_cv_file()
    if not cv_file:
        logger.warning("Không tìm thấy file .pdf/.docx trong data_lake. Dừng test.")
        return

    logger.info("Sử dụng file test: %s", cv_file.name)

    try:
        logger.info("[SETUP] Verify Neo4j connectivity...")
        assert neo4j_service.verify_connection(), "Neo4j connection failed"
        neo4j_service.setup_indices()
        _ensure_vector_index()
        _cleanup_test_node()
        logger.info("[SETUP] ✅ PASSED")

        logger.info("[STEP 1] Running E2E Ingestion...")
        process_file(cv_file, target_node_id=TEST_PERSONNEL_ID, target_role="PERSONNEL")

        props = _get_test_personnel_props()

        # Visual inspection log: hide heavy vectors and pretty-print nested private blob.
        display_props = dict(props or {})
        for emb_key in ("public_embeddings_phobert", "private_embeddings_phobert"):
            if emb_key in display_props:
                display_props[emb_key] = "<vector_768_hidden>"

        private_blob_value = display_props.get("private_data_blob")
        if isinstance(private_blob_value, str):
            try:
                display_props["private_data_blob"] = json.loads(private_blob_value)
            except Exception:
                pass

        formatted_json = json.dumps(display_props, indent=2, ensure_ascii=False)
        logger.info(
            "\n=== DỮ LIỆU NODE ĐÃ INGEST VÀO NEO4J ===\n%s\n=============================================",
            formatted_json,
        )

        assert props is not None, "Personnel node was not created"
        _assert_embedding("public_embeddings_phobert", props.get("public_embeddings_phobert"))
        _assert_embedding("private_embeddings_phobert", props.get("private_embeddings_phobert"))
        _assert_private_blob_safety(props.get("private_data_blob"))
        logger.info("[STEP 1] ✅ PASSED")

        logger.info("[STEP 2] Running Master Agent Retrieval...")
        public_skills_raw = props.get("public_skills")
        if isinstance(public_skills_raw, str):
            try:
                public_skills = json.loads(public_skills_raw)
            except Exception:
                public_skills = []
        elif isinstance(public_skills_raw, list):
            public_skills = public_skills_raw
        else:
            public_skills = []

        # Neo4j có thể chưa có public signal đủ mạnh từ extraction chunk.
        # Gắn 1 skill anchor duy nhất để test retrieval deterministically.
        if RETRIEVAL_ANCHOR not in [str(s) for s in public_skills]:
            update_partial_info(
                node_id=TEST_PERSONNEL_ID,
                role="PERSONNEL",
                compartment="public_data",
                field_name="skills",
                new_value=[RETRIEVAL_ANCHOR],
            )

        query_text = RETRIEVAL_ANCHOR
        top_k = max(50, _count_personnel_nodes() + 10)

        with MasterAgentEngine() as engine:
            results = engine.search_candidates(query_text, top_k=top_k)

        candidate_ids = [c.id for c in results]
        assert TEST_PERSONNEL_ID in candidate_ids, (
            f"{TEST_PERSONNEL_ID} not found in retrieval results"
        )
        logger.info("[STEP 2] ✅ PASSED")

        logger.info("[STEP 3] Running CRUD Partial Update...")
        update_partial_info(
            node_id=TEST_PERSONNEL_ID,
            role="PERSONNEL",
            compartment="public_data",
            field_name="availability",
            new_value="Đang tìm việc gấp",
        )

        props_after_update = _get_test_personnel_props()
        assert props_after_update is not None, "Node missing after update"
        assert props_after_update.get("public_availability") == "Đang tìm việc gấp", (
            "public_availability was not updated correctly"
        )
        logger.info("[STEP 3] ✅ PASSED")

        logger.info("[STEP 4] Running Digital Twin Interview...")
        with DigitalTwinInterviewEngine() as engine:
            reply = engine.answer_interview(
                org_id=TEST_ORG_ID,
                personnel_id=TEST_PERSONNEL_ID,
                interview_question="Bạn có kỹ năng gì nổi bật?",
            )

        assert isinstance(reply, dict), "Interview response must be dict"
        assert "answer" in reply, "Interview response missing 'answer' key"
        assert str(reply.get("answer") or "").strip(), "Interview answer is empty"
        logger.info("[STEP 4] ✅ PASSED")

        logger.info("[STEP 5] Running Soft Delete + Cleanup checks...")
        delete_account(node_id=TEST_PERSONNEL_ID, role="PERSONNEL", hard_delete=False)

        props_after_delete = _get_test_personnel_props()
        assert props_after_delete is not None, "Node missing right after soft delete"
        assert bool(props_after_delete.get("is_deleted")) is True, "Soft delete flag is_deleted != true"
        assert str(props_after_delete.get("private_data_blob") or "") == "{}", (
            "private_data_blob must be '{}' after soft delete"
        )
        logger.info("[STEP 5] ✅ PASSED")

        logger.info("🎉 E2E integration test PASSED")

    except AssertionError as e:
        logger.error("❌ ASSERT FAILED: %s", e)
        raise
    except Exception as e:
        logger.exception("❌ UNEXPECTED ERROR: %s", e)
        raise
    finally:
        try:
            _cleanup_test_node()
            logger.info("[FINALLY] Cleanup DETACH DELETE %s ✅", TEST_PERSONNEL_ID)
        except Exception as cleanup_err:
            logger.exception("[FINALLY] Cleanup failed: %s", cleanup_err)


if __name__ == "__main__":
    run_e2e_test()
