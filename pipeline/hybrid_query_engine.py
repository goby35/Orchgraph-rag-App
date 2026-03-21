"""
Agentic RAG engines for Digital Twin Recruitment on Neo4j.

This module provides two independent engines:
1) MasterAgentEngine
   - Global candidate retrieval for a JD using only public data.
2) DigitalTwinInterviewEngine
   - Private interview simulation with access control on accepted connection.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, cast

from cerebras.cloud.sdk import Cerebras
from neo4j import Driver, GraphDatabase
from openai import OpenAI

from pipeline.config import settings, get_logger
from pipeline.supabase_client import get_supabase
from pipeline.schemas import _normalize_entity
from pipeline.supabase_ingestion import _neo4j_id_to_uuid
from pipeline.vectorizer import _embedder

logger = get_logger("pipeline.hybrid_query_engine")


_MASTER_AGENT_CYPHER = """
CALL db.index.vector.queryNodes('personnel_public_idx', $top_k, $query_vector)
YIELD node AS candidate, score
RETURN
    candidate.id AS id,
    coalesce(candidate.public_name, candidate.public_full_name) AS name,
    coalesce(candidate.public_summary, candidate.public_professional_summary) AS summary,
    coalesce(candidate.public_skills, []) AS skills,
    score
"""


_GRAPH_DISCOVERY_CYPHER = """
MATCH (p:Personnel)
WHERE size($candidate_ids) = 0 OR p.id IN $candidate_ids
RETURN
    p.id AS id,
    coalesce(p.public_skills_flat, p.public_skills, []) AS skills
"""


_ALPHA_GRAPH = 0.4
_BETA_VECTOR = 0.6


_INTERVIEW_ACCESS_CYPHER = """
MATCH (p:Personnel {id: $personnel_id})
OPTIONAL MATCH (o:Organization {id: $org_id})-[r:CONNECTED_TO]->(p)
RETURN
    p.public_summary AS pub_summary,
    p.public_skills AS pub_skills,
    p.private_data_blob AS private_blob,
    r.status AS rel_status
"""


_INTERVIEW_SYSTEM_PROMPT_PRIVATE = (
    "Bạn là Bản sao số phỏng vấn sâu. Hãy dùng thông tin Public và Private để trả lời chi tiết, "
    "thẳng thắn về Tech Debt, mức lương và các điểm chuyên môn liên quan."
)


_INTERVIEW_SYSTEM_PROMPT_PUBLIC = (
    "Bạn là Bản sao số sơ loại. Bạn CHỈ BIẾT các thông tin Public. "
    "Nếu nhà tuyển dụng hỏi về mức lương, bí mật công nghệ, dự án kín, hãy từ chối khéo léo và nói: "
    "'Thông tin này thuộc vùng dữ liệu Private. Vui lòng gửi Request và chờ tôi Accept để trao đổi sâu hơn.'"
)


def _extract_content_from_response(response: Any) -> str:
    """Extract first assistant message content from ChatCompletion-like responses."""
    if response is None:
        return ""

    choices = cast(Any, getattr(response, "choices", None))
    if not choices:
        return ""

    first_choice = choices[0]
    message = cast(Any, getattr(first_choice, "message", None))
    if message is None:
        return ""

    content = cast(Any, getattr(message, "content", None))
    return str(content) if content is not None else ""


def _query_chunks_supabase(
    per_neo4j_id: str,
    query_embedding: list[float],
    is_private: bool,
    top_k: int = 5,
) -> list[str]:
    """Retrieve context chunks via Supabase RPC with ACL-aware source."""
    if not per_neo4j_id.strip():
        return []

    user_id = _neo4j_id_to_uuid(per_neo4j_id)
    rpc_name = "match_private_chunks" if is_private else "match_public_chunks"

    params = {
        "query_embedding": _vector_literal(query_embedding),
        "target_user_id": user_id,
        "match_count": top_k,
    }

    raw_data = get_supabase().schema("vdme").rpc(rpc_name, params).execute().data
    if not isinstance(raw_data, list):
        return []

    rows = raw_data
    chunks: list[str] = []
    for raw_row in rows:
        if not isinstance(raw_row, dict):
            continue
        content = str(raw_row.get("content") or "").strip()
        if content:
            chunks.append(content)
    return chunks


def _private_blob_to_context(private_blob: str) -> str:
    blob = str(private_blob or "").strip()
    if not blob:
        return ""

    try:
        payload = json.loads(blob)
    except Exception:
        return blob

    if not isinstance(payload, dict):
        return blob

    lines: list[str] = []
    salary = str(payload.get("salary_expectation") or "").strip()
    salary_usd = payload.get("salary_expectation_usd")
    blacklist = payload.get("blacklist_orgs")
    secrets = str(payload.get("project_technical_secrets") or "").strip()

    if salary:
        lines.append(f"Salary expectation: {salary}")
    if salary_usd is not None:
        lines.append(f"Salary expectation USD: {salary_usd}")
    if isinstance(blacklist, list) and blacklist:
        black_items = [str(item).strip() for item in blacklist if str(item).strip()]
        if black_items:
            lines.append("Blacklist orgs: " + ", ".join(black_items))
    if secrets:
        lines.append("Project secrets: " + secrets)

    return "\n".join(lines) if lines else blob


def _contains_private_signal(text: str) -> bool:
    lower_text = str(text or "").lower()
    markers = ["4500", "4,500", "congtyxyz", "outsourcingabc", "flink stateful cep"]
    return any(marker in lower_text for marker in markers)


def _vector_literal(vector_values: list[float]) -> str:
    return "[" + ",".join(str(float(v)) for v in vector_values) + "]"


def _extract_query_skill_set(jd_text: str) -> set[str]:
    raw_parts = re.split(r"[\n,;|\-]+", jd_text)
    skills: set[str] = set()
    for part in raw_parts:
        normalized = _normalize_entity(part)
        if normalized and len(normalized) > 1:
            skills.add(normalized)
    return skills


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _graph_discovery(
    session: Any,
    jd_text: str,
    candidate_ids: list[str],
) -> dict[str, float]:
    jd_skills = _extract_query_skill_set(jd_text)
    rows = session.run(_GRAPH_DISCOVERY_CYPHER, candidate_ids=candidate_ids)

    graph_scores: dict[str, float] = {}
    for row in rows:
        candidate_id = str(row.get("id") or "")
        if not candidate_id:
            continue

        raw_skills = row.get("skills") or []
        candidate_skill_set: set[str] = set()
        if isinstance(raw_skills, list):
            for item in raw_skills:
                if isinstance(item, str) and item.strip():
                    candidate_skill_set.add(_normalize_entity(item))

        graph_scores[candidate_id] = _jaccard_similarity(jd_skills, candidate_skill_set)
    return graph_scores


def _query_public_similarity(per_neo4j_id: str, query_embedding: list[float], top_k: int = 3) -> float:
    user_id = _neo4j_id_to_uuid(per_neo4j_id)
    params = {
        "query_embedding": _vector_literal(query_embedding),
        "target_user_id": user_id,
        "match_count": top_k,
    }

    rows = get_supabase().schema("vdme").rpc("match_public_chunks", params).execute().data
    if not isinstance(rows, list):
        return 0.0

    similarities: list[float] = []
    for raw_row in rows:
        if not isinstance(raw_row, dict):
            continue
        similarity_raw = raw_row.get("similarity")
        if not isinstance(similarity_raw, (int, float, str)):
            continue
        try:
            similarities.append(float(similarity_raw))
        except (TypeError, ValueError):
            continue
    return max(similarities) if similarities else 0.0


def _supabase_fan_out(
    candidate_ids: list[str],
    query_embedding: list[float],
    max_workers: int = 8,
) -> dict[str, float]:
    scores: dict[str, float] = {candidate_id: 0.0 for candidate_id in candidate_ids if candidate_id}
    if not scores:
        return scores

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(_query_public_similarity, candidate_id, query_embedding): candidate_id
            for candidate_id in scores.keys()
        }

        for future in as_completed(future_map):
            candidate_id = future_map[future]
            try:
                scores[candidate_id] = float(future.result())
            except Exception as exc:
                logger.debug("Supabase fan-out failed for %s: %s", candidate_id, exc)
                scores[candidate_id] = 0.0

    return scores


@dataclass
class CandidateMatch:
    id: str
    name: str
    summary: str
    skills: List[str]
    score: float


class _BaseNeo4jEngine:
    """Shared Neo4j connection lifecycle for both engines."""

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self._uri = uri or settings.NEO4J_URI
        self._user = user or settings.NEO4J_USER
        self._password = password or settings.NEO4J_PASSWORD
        self._driver: Optional[Driver] = None

    def connect(self) -> None:
        self._driver = GraphDatabase.driver(self._uri, auth=(self._user, self._password))
        self._driver.verify_connectivity()
        logger.info("Neo4j connected (%s).", self._uri)

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    @property
    def driver(self) -> Driver:
        if self._driver is None:
            raise RuntimeError("Chưa kết nối Neo4j. Gọi connect() trước.")
        return self._driver


class MasterAgentEngine(_BaseNeo4jEngine):
    """Global candidate search engine using public-only vector retrieval."""

    @staticmethod
    def _embed_text(text: str) -> List[float]:
        if not text.strip():
            return [0.0] * 768
        return _embedder.embed(text)

    def search_candidates(self, jd_text: str, top_k: int = 5) -> List[CandidateMatch]:
        """Search top-K matching personnel from public vectors only.

        Args:
            jd_text: Job requirement text from organization.
            top_k: Number of candidates to return.

        Returns:
            List[CandidateMatch] sorted by vector score.
        """
        query_vector = self._embed_text(jd_text)

        with self.driver.session() as session:
            rows = session.run(
                _MASTER_AGENT_CYPHER,
                top_k=max(top_k * 3, top_k),
                query_vector=query_vector,
            )
            vector_candidates = [
                CandidateMatch(
                    id=str(r.get("id") or ""),
                    name=str(r.get("name") or ""),
                    summary=str(r.get("summary") or ""),
                    skills=list(r.get("skills") or []),
                    score=float(r.get("score") or 0.0),
                )
                for r in rows
                if str(r.get("id") or "")
            ]

            candidate_ids = [item.id for item in vector_candidates]
            graph_scores = _graph_discovery(session, jd_text, candidate_ids)

        supabase_scores = _supabase_fan_out(candidate_ids, query_vector, max_workers=8)

        fused_results: list[CandidateMatch] = []
        for item in vector_candidates:
            graph_score = graph_scores.get(item.id, 0.0)
            vector_score = max(item.score, supabase_scores.get(item.id, 0.0))
            final_score = (_ALPHA_GRAPH * graph_score) + (_BETA_VECTOR * vector_score)
            fused_results.append(
                CandidateMatch(
                    id=item.id,
                    name=item.name,
                    summary=item.summary,
                    skills=item.skills,
                    score=final_score,
                )
            )

        fused_results.sort(key=lambda item: item.score, reverse=True)
        results = fused_results[:top_k]

        logger.info("MasterAgentEngine returned %d candidates.", len(results))
        return results


class DigitalTwinInterviewEngine(_BaseNeo4jEngine):
    """Private interview engine with accepted-connection access control."""

    @staticmethod
    def _embed(text: str) -> list[float]:
        if not text.strip():
            return [0.0] * 768
        return _embedder.embed(text)

    @staticmethod
    def _llm_answer(
        public_context: str,
        public_skills: list[str],
        private_context: str,
        question: str,
        is_private_mode: bool,
    ) -> str:
        user_payload = {
            "public_context": public_context or "",
            "public_skills": public_skills,
            "private_context": private_context,
            "is_private_mode": is_private_mode,
            "interview_question": question,
        }

        system_prompt = (
            _INTERVIEW_SYSTEM_PROMPT_PRIVATE if is_private_mode else _INTERVIEW_SYSTEM_PROMPT_PUBLIC
        )

        messages = cast(Any, [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ])

        try:
            client = Cerebras(api_key=settings.CEREBRAS_API_KEY)
            resp = client.chat.completions.create(
                model=settings.CEREBRAS_MODEL,
                messages=messages,
                temperature=0.2,
            )
            content = _extract_content_from_response(resp)
            if content.strip():
                return content
        except Exception as exc:
            logger.warning("DigitalTwin LLM Cerebras error: %s", exc)

        try:
            client_oai = OpenAI(api_key=settings.OPENAI_API_KEY)
            resp = client_oai.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=messages,
                temperature=0.2,
            )
            content = _extract_content_from_response(resp)
            if content.strip():
                return content
        except Exception as exc:
            logger.error("DigitalTwin LLM OpenAI error: %s", exc)

        return "Xin lỗi, hệ thống hiện chưa thể tạo câu trả lời phỏng vấn. Vui lòng thử lại sau."

    def answer_interview(
        self,
        org_id: str,
        personnel_id: str,
        interview_question: str,
    ) -> Dict[str, Any]:
        """Answer interview question in public/private mode depending on relationship status."""
        with self.driver.session() as session:
            row = session.run(
                _INTERVIEW_ACCESS_CYPHER,
                org_id=org_id,
                personnel_id=personnel_id,
            ).single()

        if row is None:
            return {
                "answer": "Không tìm thấy hồ sơ ứng viên để phỏng vấn.",
                "is_private_mode": False,
                "rel_status": None,
            }

        rel_status = str(row.get("rel_status") or "").lower() or None
        is_private_mode = rel_status == "accepted"
        public_context = str(row.get("pub_summary") or "")
        public_skills = list(row.get("pub_skills") or [])
        private_blob_context = _private_blob_to_context(str(row.get("private_blob") or ""))

        try:
            question_embedding = self._embed(interview_question)
            context_chunks = _query_chunks_supabase(
                per_neo4j_id=personnel_id,
                query_embedding=question_embedding,
                is_private=is_private_mode,
                top_k=5,
            )
        except Exception as exc:
            logger.warning("Supabase chunk query failed, fallback to empty context: %s", exc)
            context_chunks = []

        private_context_parts = [chunk for chunk in context_chunks if str(chunk).strip()]
        if is_private_mode and private_blob_context:
            private_context_parts.append(private_blob_context)
        private_context = "\n\n".join(private_context_parts)

        answer = self._llm_answer(
            public_context=public_context,
            public_skills=public_skills,
            private_context=private_context,
            question=interview_question,
            is_private_mode=is_private_mode,
        )

        if is_private_mode and private_blob_context and not _contains_private_signal(answer):
            answer = (
                f"{answer.strip()}\n\n"
                f"Thong tin private tham chieu:\n{private_blob_context}"
            ).strip()

        logger.info(
            "DigitalTwinInterviewEngine answered question for personnel_id=%s (mode=%s).",
            personnel_id,
            "private" if is_private_mode else "public",
        )
        return {
            "answer": answer,
            "is_private_mode": is_private_mode,
            "rel_status": rel_status,
        }


__all__ = [
    "CandidateMatch",
    "MasterAgentEngine",
    "DigitalTwinInterviewEngine",
]
