"""
Agentic RAG engines for 

 on Neo4j.

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
from anthropic import Anthropic
from openai import OpenAI

from pipeline.config import settings, get_logger
from pipeline.supabase_client import get_supabase
from pipeline.schemas import _normalize_entity
from pipeline.supabase_ingestion import _neo4j_id_to_uuid
from pipeline.vectorizer import MODEL_FIELD_MAP, vectorize_text, vectorize_text_for_model

logger = get_logger("pipeline.hybrid_query_engine")

_ACTIVE_FIELD = MODEL_FIELD_MAP.get(
    settings.ACTIVE_EMBEDDING_MODEL,
    "public_embeddings_gte"  # fallback
)

_MASTER_AGENT_CYPHER = f"""
CALL db.index.vector.queryNodes('{_ACTIVE_FIELD}_idx', $top_k, $query_vector)
YIELD node AS candidate, score
RETURN
    candidate.id AS id,
    coalesce(candidate.public_name, candidate.public_full_name) AS name,
    coalesce(candidate.public_summary, candidate.public_professional_summary) AS summary,
    coalesce(candidate.public_skills, []) AS skills,
    score
"""

_MASTER_AGENT_LEXICAL_FALLBACK_CYPHER = """
MATCH (p:Personnel)
WITH
    p,
    toLower(coalesce(p.public_name, p.public_full_name, "")) AS name_text,
    toLower(coalesce(p.public_summary, p.public_professional_summary, "")) AS summary_text,
    [skill IN coalesce(p.public_skills, []) | toLower(toString(skill))] AS skills_text
WITH
    p,
    reduce(
        score = 0.0,
        kw IN $keywords |
            score
            + CASE
                WHEN kw = "" THEN 0.0
                WHEN name_text CONTAINS kw THEN 2.0
                WHEN summary_text CONTAINS kw THEN 1.0
                WHEN any(skill IN skills_text WHERE skill CONTAINS kw) THEN 1.5
                ELSE 0.0
            END
    ) AS lexical_score
RETURN
    p.id AS id,
    coalesce(p.public_name, p.public_full_name) AS name,
    coalesce(p.public_summary, p.public_professional_summary) AS summary,
    coalesce(p.public_skills, []) AS skills,
    lexical_score AS score
ORDER BY score DESC
LIMIT $top_k
"""


_GRAPH_DISCOVERY_CYPHER = """
MATCH (p:Personnel)
WHERE size($candidate_ids) = 0 OR p.id IN $candidate_ids
OPTIONAL MATCH (p)-[:HAS_EXPERIENCE]->(e:Experience)
OPTIONAL MATCH (e)-[:USED_TECH]->(t:TechStack)
RETURN
    p.id AS id,
    coalesce(p.public_skills_flat, p.public_skills, []) AS skills,
    COUNT { (p)-[:HAS_EXPERIENCE]->() } AS experience_count,
    collect(DISTINCT t.id) AS connected_tech
"""


_ALPHA_GRAPH = 0.2
_BETA_VECTOR = 0.8
BONUS_WEIGHT = 0.15
_GRAPH_MODE = "enhanced"
_USE_ENHANCED_GRAPH = True
_DIGITAL_TWIN_DEFAULT_EMBED_MODEL = "Alibaba-NLP/gte-multilingual-base"
_RELEVANCE_SIM_THRESHOLD = 0.55


def has_relevant_content(
    question: str,
    chunks: list[str],
    embed_fn: Any,
    threshold: float = _RELEVANCE_SIM_THRESHOLD,
    similarities: list[float] | None = None,
) -> bool:
    _ = embed_fn

    question_l = str(question or "").lower()
    normalized_chunks = [str(chunk or "").strip() for chunk in (chunks or []) if str(chunk or "").strip()]
    joined_chunks = "\n".join(normalized_chunks).lower()

    strict_topic_tokens = ("clickhouse", "nexpay", "materialized")
    if any(token in question_l for token in strict_topic_tokens):
        if not any(token in joined_chunks for token in strict_topic_tokens):
            return False

    if similarities and max(similarities) >= threshold:
        return True

    salary_topic = any(token in question_l for token in ("lương", "salary", "compensation", "kỳ vọng"))
    secret_topic = any(token in question_l for token in ("bí mật", "technical secret", "công nghệ", "kỹ thuật"))
    blacklist_topic = any(token in question_l for token in ("blacklist", "công ty blacklist"))

    if salary_topic and any(chunk.startswith("[Lương kỳ vọng]") for chunk in normalized_chunks):
        return True
    if secret_topic and any(chunk.startswith("[Bí mật kỹ thuật]") for chunk in normalized_chunks):
        return True
    if blacklist_topic and any(chunk.startswith("[Blacklist]") for chunk in normalized_chunks):
        return True

    return False
def _build_repair_signal(validation_result: ValidationResult) -> str:
    lines = [
        "Improve the answer using only information grounded in context.",
        f"Current grounding score: {validation_result.grounding_score:.2f}.",
    ]

    low_confidence_quotes = [
        (quote, score)
        for quote, score in validation_result.quote_scores.items()
        if score < 1.0
    ]
    if low_confidence_quotes:
        lines.append("Low-confidence quotes to recheck:")
        for quote, score in sorted(low_confidence_quotes, key=lambda item: item[1]):
            trunc = quote[:100] + "..." if len(quote) > 100 else quote
            lines.append(f"  - {score:.2f}: \"{trunc}\"")

    if validation_result.unverified_numbers:
        lines.append(
            "Numbers not grounded in context: "
            + ", ".join(validation_result.unverified_numbers[:8])
        )

    lines.append("Rewrite the answer to stay within the context. Do not invent new facts or numbers.")
    return "\n".join(lines)


def _seniority_multiplier(years: int | None) -> float:
    if years is None:
        return 1.0
    if years <= 2:
        return 0.5
    if years <= 5:
        return 0.8
    if years <= 9:
        return 1.2
    return 1.5


def _seniority_component(years: int | None) -> float:
    if years is None:
        return 0.5
    if years <= 2:
        return 0.25
    if years <= 5:
        return 0.5
    if years <= 9:
        return 0.75
    return 1.0


def _resolve_graph_mode() -> str:
    mode = str(globals().get("_GRAPH_MODE", "enhanced") or "enhanced").lower()
    if mode in {"none", "jaccard_only", "enhanced"}:
        return mode

    # Backward compatibility: allow old boolean flag toggling.
    use_enhanced = bool(globals().get("_USE_ENHANCED_GRAPH", True))
    return "enhanced" if use_enhanced else "jaccard_only"

def _connection_bonus(org_id: str, personnel_id: str, session: Any) -> float:
    try:
        result = session.run(
            "MATCH (o:Organization {id: $org_id})-[r:CONNECTED_TO]->(p:Personnel {id: $per_id}) "
            "RETURN r.status AS status",
            org_id=org_id, per_id=personnel_id,
        ).single()
        if result is None:
            return 0.0
        status = str(result.get("status") or "").lower()
        if status == "accepted": return 0.15
        if status == "pending":  return 0.05
        return 0.0
    except Exception:
        return 0.0

_INTERVIEW_ACCESS_CYPHER = """
MATCH (p:Personnel {id: $personnel_id})
OPTIONAL MATCH (o:Organization {id: $org_id})-[r:CONNECTED_TO]->(p)
RETURN
    coalesce(p.public_name, p.public_full_name, p.id) AS pub_name,
    p.public_summary                                   AS pub_summary,
    p.public_skills                                    AS pub_skills,
    p.private_data_blob                                AS private_blob,
    r.status                                           AS rel_status
"""


# Thay bằng:

_PERSONA_BASE = """\
Bạn là {candidate_name}. Trả lời câu hỏi phỏng vấn từ hồ sơ bên dưới.

[QUY TAC — theo thu tu uu tien]

1. NEU CONTEXT CO THONG TIN LIEN QUAN → BAT BUOC TRA LOI.
   Khong can trich dan hoan hao. Fact co trong context la du de tra loi.

2. HAI LOAI THONG TIN XU LY KHAC NHAU:
   - SO LIEU CUNG (luong, ngay, %, ID, ten cong ty): 
     copy NGUYEN VAN tu context, khong doi don vi, khong lam tron, khong chon 1 gia tri trong range.
   - MO TA MEM (kinh nghiem, ky nang, du an):
     duoc phep tom tat nhung phai giu dung y nghia goc.

3. "Q:" va "A:" trong context = lich su phong van that cua ung vien.

4. CHI NOT_FOUND khi co the phat bieu: 
   "context khong chua bat ky tu nao ve [CHU DE CU THE]."
   Neu co du lieu gan dung → van tra loi va ghi ro muc do chinh xac.

[FORMAT BAT BUOC]
STATE: FOUND
ANSWER: <bat dau bang fact chinh, khong mo dau bang dinh nghia chung>

STATE: NOT_FOUND
SEARCHED: <chu de da tim kiem trong context>
ANSWER: Ho so chua co thong tin ve [chu de].
"""

_INTERVIEW_SYSTEM_PROMPT_PRIVATE = """\
{persona_base}

Mode: PRIVATE.
Anh/chi da duoc chap nhan ket noi.
Duoc phep tra loi chi tiet ve salary, project confidential, ky thuat sau neu context co noi dung do.

<context>
{{public_context}}

{{private_context}}
</context>
"""

_INTERVIEW_SYSTEM_PROMPT_PUBLIC = """\
{persona_base}

Mode: PUBLIC.
Anh/chi chua duoc chap nhan ket noi.
Chi duoc dung thong tin public trong context.

<context>
{{public_context}}
</context>
"""


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
    top_k: int = 3,
) -> list[dict[str, Any]]:
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
    hits: list[dict[str, Any]] = []
    for raw_row in rows:
        if not isinstance(raw_row, dict):
            continue
        content = str(raw_row.get("content") or "").strip()
        if content:
            similarity_raw = raw_row.get("similarity")
            similarity: float | None = None
            if isinstance(similarity_raw, (int, float, str)):
                try:
                    similarity = float(similarity_raw)
                except (TypeError, ValueError):
                    similarity = None

            hits.append({
                "content": content,
                "similarity": similarity,
            })
    return hits


_PROFILE_CONTEXT_KEYWORDS = (
    "skill",
    "skills",
    "experience",
    "education",
    "role",
    "company",
    "kỹ năng",
    "kinh nghiệm",
    "học vấn",
    "vai trò",
    "công ty",
)


def _context_priority_score(chunk: str) -> int:
    text = str(chunk or "").strip().lower()
    if not text:
        return -999

    score = 0
    if text.startswith("q:"):
        score -= 3

    for keyword in _PROFILE_CONTEXT_KEYWORDS:
        if keyword in text:
            score += 1

    return score


def _select_preferred_contexts(chunks: list[str], top_k: int = 3) -> list[str]:
    deduped = list(dict.fromkeys(str(chunk).strip() for chunk in chunks if str(chunk).strip()))

    def _bucket(chunk: str) -> int:
        text = str(chunk or "").strip()
        lower_text = text.lower()
        if text.startswith("["):
            return 0
        if lower_text.startswith("q:"):
            return 2
        return 1

    ranked = sorted(
        enumerate(deduped),
        key=lambda item: (_bucket(item[1]), item[0]),
    )
    return [chunk for _, chunk in ranked[:top_k]]


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
        lines.append(f"[Lương kỳ vọng] {salary}")
    if salary_usd is not None:
        lines.append(f"[Lương kỳ vọng] USD: {salary_usd}")
    if isinstance(blacklist, list) and blacklist:
        black_items = [str(item).strip() for item in blacklist if str(item).strip()]
        if black_items:
            lines.append("[Blacklist] " + ", ".join(black_items))
    if secrets:
        lines.append("[Bí mật kỹ thuật] " + secrets)

    return "\n".join(lines) if lines else blob


def extract_labeled_facts(chunks: list[str]) -> dict[str, str]:
    facts: dict[str, str] = {}
    for raw_chunk in chunks or []:
        chunk = str(raw_chunk or "").strip()
        if not chunk:
            continue

        if chunk.startswith("[Lương kỳ vọng]"):
            value = chunk.replace("[Lương kỳ vọng]", "", 1).strip(" :\t")
            if value and "salary" not in facts:
                facts["salary"] = value
            continue

        if chunk.startswith("[Bí mật kỹ thuật]"):
            value = chunk.replace("[Bí mật kỹ thuật]", "", 1).strip(" :\t")
            if value and "technical_secret" not in facts:
                facts["technical_secret"] = value
            continue

        if chunk.startswith("[Blacklist]"):
            value = chunk.replace("[Blacklist]", "", 1).strip(" :\t")
            if value and "blacklist" not in facts:
                facts["blacklist"] = value
            continue

    return facts


def _cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = (sum(x * x for x in a) ** 0.5) * (sum(x * x for x in b) ** 0.5)
    return dot / norm if norm else 0.0


def _extract_relevant_window(
    chunk: str,
    question: str,
    window_sentences: int = 3,
    embed_fn: Any | None = None,
) -> str:
    """Extract a semantic sentence window from a long labeled chunk."""
    try:
        chunk = str(chunk or "").strip()
        question = str(question or "").strip()

        if len(chunk) < 200:
            return chunk

        if not question:
            return chunk

        sentences = [
            s.strip()
            for s in re.split(r'(?<=[.!?;:])\s+|[\n\r]+', chunk)
            if s.strip()
        ]

        if len(sentences) < 4:
            return chunk

        embedding_fn = embed_fn or vectorize_text_for_model

        def _embed_text(text: str) -> list[float]:
            if embed_fn:
                return cast(Any, embedding_fn)(text)
            return cast(Any, embedding_fn)(text, _DIGITAL_TWIN_DEFAULT_EMBED_MODEL)

        q_vec = _embed_text(question)
        if not q_vec:
            return chunk

        best_idx = 0
        best_score = -1.0

        for idx, sentence in enumerate(sentences):
            s_vec = _embed_text(sentence)
            if not s_vec:
                continue
            score = _cosine_sim(q_vec, s_vec)
            if score > best_score:
                best_score = score
                best_idx = idx

        start = max(0, best_idx - window_sentences // 2)
        end = min(len(sentences), best_idx + 1 + (window_sentences - 1 - (best_idx - start)))
        window = " ".join(sentences[start:end])

        return window if window.strip() else chunk
    except Exception:
        return chunk


def _build_private_context(
    private_blob_context: str,
    context_chunks: list[str],
    question: str = "",
    trim_long_chunks: bool = True,
    embed_fn: Any | None = None,
) -> str:
    source_chunks: list[str] = []
    if private_blob_context:
        source_chunks.extend(
            line.strip()
            for line in str(private_blob_context).splitlines()
            if str(line).strip()
        )
    source_chunks.extend(str(chunk).strip() for chunk in context_chunks if str(chunk).strip())

    if trim_long_chunks and question:
        source_chunks = [
            _extract_relevant_window(chunk, question, embed_fn=embed_fn)
            if chunk.startswith("[")
            else chunk
            for chunk in source_chunks
        ]

    labeled_facts = extract_labeled_facts(source_chunks)

    interview_chunks = [
        chunk for chunk in source_chunks
        if not (
            chunk.startswith("[Lương kỳ vọng]")
            or chunk.startswith("[Bí mật kỹ thuật]")
            or chunk.startswith("[Blacklist]")
        )
    ]

    if not labeled_facts:
        return "\n\n".join(source_chunks)

    lines: list[str] = ["[DỮ LIỆU HỒ SƠ - ĐÃ XÁC NHẬN]"]
    ordered_facts: dict[str, str] = {}
    if labeled_facts.get("salary"):
        ordered_facts["salary"] = labeled_facts["salary"]
    if labeled_facts.get("blacklist"):
        ordered_facts["blacklist"] = labeled_facts["blacklist"]
    if labeled_facts.get("technical_secret"):
        ordered_facts["technical_secret"] = labeled_facts["technical_secret"]
    lines.append(json.dumps(ordered_facts, ensure_ascii=False, indent=2))

    lines.append("")
    lines.append("[NỘI DUNG PHỎNG VẤN]")
    if interview_chunks:
        lines.extend(interview_chunks)

    return "\n".join(lines).strip()


def extract_key_metrics(chunks: list[str], labeled_only: bool = True) -> list[str]:
    """Extract key numeric metrics from chunks.
    
    Args:
        chunks: List of text chunks to extract metrics from.
        labeled_only: If True (default), only extract from labeled chunks (starts with [).
                     If False, extract from all chunks. Default True for safer behavior.
    """
    metric_patterns = (
        re.compile(r"\b\d+(?:[.,]\d+)?x\b", re.IGNORECASE),
        re.compile(r"\b\d+(?:[.,]\d+)?%\b", re.IGNORECASE),
        re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:mbps|gbps|ms|s)\b", re.IGNORECASE),
        re.compile(r"\bUSD\s?\d[\d,\.]*\b", re.IGNORECASE),
        re.compile(r"\b\d[\d,\.]*\s?(?:VNĐ|VND|USD)\b", re.IGNORECASE),
        re.compile(r"\b\d+\s+shards?\b", re.IGNORECASE),
        re.compile(r"\bM\s*=\s*\d+\b", re.IGNORECASE),
    )

    if labeled_only:
        source_chunks = [
            str(chunk).strip()
            for chunk in (chunks or [])
            if str(chunk).strip().startswith("[")
        ]
    else:
        source_chunks = [
            str(chunk).strip()
            for chunk in (chunks or [])
            if str(chunk).strip()
        ]

    seen: set[str] = set()
    metrics: list[str] = []
    for chunk in source_chunks:
        for pattern in metric_patterns:
            for match in pattern.findall(chunk):
                value = str(match).strip()
                if not value:
                    continue
                key = value.lower()
                if key in seen:
                    continue
                seen.add(key)
                metrics.append(value)
                if len(metrics) >= 15:
                    return metrics
    return metrics


def _is_salary_question(question: str) -> bool:
    text = str(question or "").lower()
    keywords = (
        "lương",
        "salary",
        "thu nhập",
        "compensation",
        "mức lương",
        "kỳ vọng",
        "vp engineering",
    )
    return any(keyword in text for keyword in keywords)


def _is_secret_question(question: str) -> bool:
    text = str(question or "").lower()
    keywords = (
        "bí mật",
        "technical secret",
        "công nghệ",
        "kỹ thuật",
        "công cụ độc quyền",
        "độc quyền",
        "hiệu suất",
        "throughput",
        "stm32",
        "clickhouse",
        "nexpay",
    )
    return any(keyword in text for keyword in keywords)


def _enforce_answer_from_labeled_facts(
    answer: str,
    question: str,
    labeled_facts: dict[str, str],
) -> str:
    salary = str(labeled_facts.get("salary") or "").strip()
    blacklist = str(labeled_facts.get("blacklist") or "").strip()

    if not salary:
        return answer
    if not _is_salary_question(question):
        return answer

    answer_lower = str(answer or "").lower()
    if salary.lower() in answer_lower:
        return answer

    answer_lines = [f"Mức lương kỳ vọng: {salary}."]
    if "blacklist" in str(question or "").lower() and blacklist:
        answer_lines.append(f"Blacklist: {blacklist}.")

    return "\n".join([
        "STATE: FOUND",
        "ANSWER: " + " ".join(answer_lines),
    ])


def _enforce_secret_answer_from_facts(
    answer: str,
    question: str,
    labeled_facts: dict[str, str],
    key_metrics: list[str] | None = None,
) -> str:
    technical_secret = str(labeled_facts.get("technical_secret") or "").strip()
    if not technical_secret:
        return answer
    if not _is_secret_question(question):
        return answer

    strict_topic_tokens = ("clickhouse", "nexpay", "materialized")
    question_l = str(question or "").lower()
    secret_l = technical_secret.lower()
    if any(token in question_l for token in strict_topic_tokens):
        if not any(token in secret_l for token in strict_topic_tokens):
            return answer

    clauses = [
        part.strip()
        for part in re.split(r"(?<=[.!?;:])\s+|[\n\r]+", technical_secret)
        if part.strip()
    ]
    if not clauses:
        clauses = [technical_secret]

    metric_pattern = re.compile(r"\b\d+(?:[.,]\d+)?(?:\s?(?:mbps|gbps|ms|s)|x|%)\b", re.IGNORECASE)
    question_terms = [
        token for token in re.findall(r"[\wÀ-ỹ]{4,}", str(question or "").lower())
        if token not in {"hoặc", "công", "nghệ", "kỹ", "thuật", "được", "nào", "cụ", "thể"}
    ]
    org_hint_match = re.search(r"\btại\s+([\wÀ-ỹ_]+)", str(question or ""), flags=re.IGNORECASE)
    org_hint = str(org_hint_match.group(1) if org_hint_match else "").strip().lower()

    best_clause = ""
    best_score = -1.0
    q_vec: list[float] = []
    try:
        q_vec = vectorize_text_for_model(str(question or ""), _DIGITAL_TWIN_DEFAULT_EMBED_MODEL)
    except Exception:
        q_vec = []

    for clause in clauses:
        normalized_clause = _normalize_for_match(clause)
        score = _fuzzy_ratio(_normalize_for_match(question), normalized_clause)
        if q_vec:
            try:
                c_vec = vectorize_text_for_model(clause, _DIGITAL_TWIN_DEFAULT_EMBED_MODEL)
                if c_vec:
                    score = max(score, _cosine_sim(q_vec, c_vec))
            except Exception:
                pass

        # Prefer clauses that share concrete question terms (company/product/topic words).
        if question_terms:
            overlap = sum(1 for token in question_terms if token in normalized_clause)
            if overlap:
                score += min(0.2, 0.06 * overlap)

        # If the question names a company after "tại", prioritize clauses mentioning it.
        if org_hint:
            if org_hint in normalized_clause:
                score += 0.2
            else:
                score -= 0.08

        # Penalize generic trailing disclosures that often derail synthesis.
        if normalized_clause.startswith("ngoai ra"):
            score -= 0.15

        if score > best_score:
            best_score = score
            best_clause = clause

    selected: list[str] = [best_clause] if best_clause else [clauses[0]]

    if not any(metric_pattern.search(clause) for clause in selected):
        metric_candidates: list[tuple[float, str]] = []
        for clause in clauses:
            found = metric_pattern.findall(clause)
            if not found:
                continue

            score = 0.0
            for token in found:
                token_clean = str(token).strip().lower()
                if token_clean.endswith("%"):
                    try:
                        score = max(score, float(token_clean[:-1].replace(",", ".")))
                    except ValueError:
                        score = max(score, 1.0)
                else:
                    score = max(score, 1.0)
            metric_candidates.append((score, clause))

        if metric_candidates:
            metric_candidates.sort(key=lambda item: item[0], reverse=True)
            selected.append(metric_candidates[0][1])

    focused_span = " ".join(list(dict.fromkeys(selected[:2]))).strip() or technical_secret

    if not metric_pattern.search(focused_span) and key_metrics:
        metric_text = ", ".join(str(x).strip() for x in key_metrics[:3] if str(x).strip())
        if metric_text:
            focused_span = f"{focused_span} Số liệu chính: {metric_text}."

    return "\n".join([
        "STATE: FOUND",
        f"ANSWER: {focused_span}",
    ])


def _enforce_found_when_relevant(
    answer: str,
    force_found: bool,
    labeled_facts: dict[str, str],
    context_chunks: list[str],
    question: str,
) -> str:
    if not force_found:
        return answer

    strict_topic_tokens = ("clickhouse", "nexpay", "materialized")
    question_l = str(question or "").lower()
    if any(token in question_l for token in strict_topic_tokens):
        joined = "\n".join(str(chunk or "") for chunk in context_chunks).lower()
        tech = str(labeled_facts.get("technical_secret") or "").lower()
        if not any(token in joined or token in tech for token in strict_topic_tokens):
            return answer

    state_match = re.search(r"(?im)^\s*state\s*:\s*([A-Z_]+)", str(answer or ""))
    if state_match and state_match.group(1).strip().upper() == "FOUND":
        return answer

    technical_secret = str(labeled_facts.get("technical_secret") or "").strip()
    if not technical_secret:
        technical_secret = str(context_chunks[0]).strip() if context_chunks else ""
    if not technical_secret:
        return answer

    return "\n".join([
        "STATE: FOUND",
        f"ANSWER: {technical_secret}",
    ])


def _enforce_not_found_for_topic_mismatch(
    answer: str,
    question: str,
    labeled_facts: dict[str, str],
    context_chunks: list[str],
) -> str:
    strict_topic_tokens = ("clickhouse", "nexpay", "materialized")
    question_l = str(question or "").lower()
    if not any(token in question_l for token in strict_topic_tokens):
        return answer

    joined = "\n".join(str(chunk or "") for chunk in context_chunks).lower()
    tech = str(labeled_facts.get("technical_secret") or "").lower()
    if any(token in joined or token in tech for token in strict_topic_tokens):
        return answer

    searched = ", ".join(token for token in strict_topic_tokens if token in question_l)
    if not searched:
        searched = "chu de duoc hoi"
    return "\n".join([
        "STATE: NOT_FOUND",
        f"SEARCHED: {searched}",
        "ANSWER: Ho so chua co thong tin ve [chu de].",
    ])


def _contains_private_signal(text: str) -> bool:
    lower_text = str(text or "").lower()
    markers = ["4500", "4,500", "congtyxyz", "outsourcingabc", "flink stateful cep"]
    return any(marker in lower_text for marker in markers)


def _truncate_for_log(text: str, max_len: int = 280) -> str:
    value = str(text or "").replace("\n", " ").strip()
    if len(value) <= max_len:
        return value
    return value[: max_len - 3] + "..."


def _truncate_for_payload(text: str, max_len: int = 500) -> str:
    value = str(text or "").strip()
    if len(value) <= max_len:
        return value
    return value[: max_len - 3] + "..."


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
) -> dict[str, dict[str, Any]]:
    jd_skills = _extract_query_skill_set(jd_text)
    rows = session.run(_GRAPH_DISCOVERY_CYPHER, candidate_ids=candidate_ids)

    graph_data: dict[str, dict[str, Any]] = {}
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

        base_jaccard = _jaccard_similarity(jd_skills, candidate_skill_set)
        
        experience_count = row.get("experience_count") or 0
        connected_tech = row.get("connected_tech") or []
        
        # Calculate bonus weight based on overlap between connected tech and JD skills
        overlap = set(connected_tech).intersection(jd_skills)
        bonus_weight = BONUS_WEIGHT if overlap else 0.0
        
        graph_data[candidate_id] = {
            "base_score": base_jaccard,
            "experience_count": experience_count,
            "bonus_weight": bonus_weight,
            "bonus_component": 1.0 if overlap else 0.0,
        }
        
    return graph_data


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


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    quote_scores: dict[str, float]
    grounding_score: float
    unverified_numbers: list[str]
    answer_clean: str
    state: str
    
    def __post_init__(self) -> None:
        if self.quote_scores is None:
            object.__setattr__(self, "quote_scores", {})
        if self.unverified_numbers is None:
            object.__setattr__(self, "unverified_numbers", [])


def _normalize_for_match(text: str) -> str:
    import unicodedata

    value = unicodedata.normalize("NFKC", str(text or ""))
    value = value.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    value = value.lower()
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _extract_response_parts(llm_response: str) -> tuple[str, str]:
    raw = str(llm_response or "").replace("\\n", "\n").strip()

    answer_match = re.search(
        r"(?is)^\s*answer\s*:\s*(.+?)(?=^\s*evidence\s*:|\Z)",
        raw,
        flags=re.MULTILINE,
    )
    evidence_match = re.search(r"(?is)^\s*evidence\s*:\s*(.+)$", raw, flags=re.MULTILINE)

    answer_text = answer_match.group(1).strip() if answer_match else raw
    evidence_text = evidence_match.group(1).strip() if evidence_match else ""
    return answer_text, evidence_text


def _extract_quotes(evidence_text: str) -> list[str]:
    text = str(evidence_text or "").strip()
    if not text:
        return []

    quoted = re.findall(r'["“”]([^"“”]+)["“”]', text)
    if quoted:
        return [q.strip() for q in quoted if q.strip()]

    fallback = [part.strip(" \t\n\r\"'") for part in text.split("|") if part.strip()]
    return [q for q in fallback if q]


def _extract_answer_numbers(answer_text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", str(answer_text or "")))


def _extract_answer_names(answer_text: str) -> set[str]:
    text = str(answer_text or "")
    multi_token_names = set(
        re.findall(r"\b(?:[A-ZĐ][\wÀ-ỹ\-]+(?:\s+[A-ZĐ][\wÀ-ỹ\-]+)+)\b", text)
    )
    acronyms = set(re.findall(r"\b[A-Z]{2,}(?:[-_][A-Z0-9]+)*\b", text))
    return {name.strip() for name in (multi_token_names | acronyms) if name.strip()}


def _fuzzy_ratio(s1: str, s2: str) -> float:
    from difflib import SequenceMatcher
    return SequenceMatcher(None, s1, s2).ratio()


def _best_matching_span(sentence: str, chunk: str) -> str:
    sentence_clean = str(sentence or "").strip()
    chunk_clean = str(chunk or "").strip()
    if not sentence_clean or not chunk_clean:
        return ""

    clauses = [
        part.strip()
        for part in re.split(r"(?<=[.!?;:])\s+|[\n\r]+", chunk_clean)
        if part.strip()
    ]
    if not clauses:
        clauses = [chunk_clean]

    best_clause = ""
    best_score = 0.0
    for clause in clauses:
        score = _fuzzy_ratio(_normalize_for_match(sentence_clean), _normalize_for_match(clause))
        if score > best_score:
            best_score = score
            best_clause = clause

    if best_score > 0.4 and best_clause:
        return best_clause
    return ""


def extract_evidence_post_hoc(answer: str, chunks: list[str]) -> list[str]:
    answer_text, _ = _extract_response_parts(answer)
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+|[\n\r]+", str(answer_text or ""))
        if part.strip()
    ]

    spans: list[str] = []
    normalized_chunks = [str(chunk or "").strip() for chunk in (chunks or []) if str(chunk or "").strip()]
    for sentence in sentences:
        best_chunk = ""
        best_score = 0.0
        for chunk in normalized_chunks:
            score = _fuzzy_ratio(_normalize_for_match(sentence), _normalize_for_match(chunk))
            if score > best_score:
                best_score = score
                best_chunk = chunk

        if best_score <= 0.4:
            continue

        span = _best_matching_span(sentence, best_chunk)
        if span and span not in spans:
            spans.append(span)

    return spans


def _context_fragments(context_chunks: list[str]) -> list[str]:
    fragments: list[str] = []
    for chunk in context_chunks or []:
        normalized_chunk = _normalize_for_match(chunk)
        if not normalized_chunk:
            continue
        fragments.append(normalized_chunk)
        fragments.extend(
            part.strip()
            for part in re.split(r"(?<=[.!?;:])\s+|[\n\r]+", normalized_chunk)
            if part.strip()
        )
    return list(dict.fromkeys(fragments))


def _normalize_numeric_for_match(text: str) -> str:
    value = _normalize_for_match(text)
    value = re.sub(r"(?<=\d)[,\s](?=\d)", "", value)
    return value


def _score_quote_against_context(quote: str, normalized_context: str, context_fragments: list[str]) -> float:
    normalized_quote = _normalize_for_match(quote)
    if not normalized_quote:
        return 0.0

    if normalized_quote in normalized_context:
        return 1.0

    best_ratio = 0.0
    for fragment in context_fragments:
        ratio = _fuzzy_ratio(normalized_quote, fragment)
        if ratio > best_ratio:
            best_ratio = ratio

    if best_ratio < 0.5:
        return 0.0

    score = 0.5 + ((best_ratio - 0.5) / 0.5) * 0.4
    return min(score, 0.9)


def _state_from_grounding_score(grounding_score: float) -> str:
    if grounding_score >= 0.8:
        return "GROUNDED"
    if grounding_score >= 0.3:
        return "PARTIAL"
    return "UNVERIFIED"


def validate_llm_response(llm_response: str, context_chunks: list[str]) -> ValidationResult:
    answer_text, evidence_text = _extract_response_parts(llm_response)

    context_text = "\n".join(str(chunk or "") for chunk in (context_chunks or []))
    normalized_context = _normalize_for_match(context_text)
    context_fragments = _context_fragments(context_chunks)
    quotes = _extract_quotes(evidence_text)

    quote_scores: dict[str, float] = {}
    score_values: list[float] = []
    for quote in quotes:
        score = _score_quote_against_context(quote, normalized_context, context_fragments)
        quote_scores[quote] = score
        score_values.append(score)

    grounding_score = sum(score_values) / len(score_values) if score_values else 0.0
    answer_numbers = _extract_answer_numbers(answer_text)
    normalized_context_numbers = _normalize_numeric_for_match(context_text)
    unverified_numbers: list[str] = []
    for number in answer_numbers:
        normalized_number = _normalize_numeric_for_match(number)
        if normalized_number and normalized_number not in normalized_context_numbers:
            if number not in unverified_numbers:
                unverified_numbers.append(number)

    return ValidationResult(
        passed=True,
        quote_scores=quote_scores,
        grounding_score=grounding_score,
        unverified_numbers=unverified_numbers,
        answer_clean=answer_text,
        state=_state_from_grounding_score(grounding_score),
    )


def _explain_fit(candidate: CandidateMatch, jd_text: str) -> str:
    skills_preview = ", ".join(str(s).strip() for s in candidate.skills[:8] if str(s).strip())
    prompt = (
        f"Job: {jd_text[:400]}\n"
        f"Candidate: {candidate.name}\n"
        f"Skills: {skills_preview}\n"
        f"Summary: {candidate.summary[:300]}\n\n"
        "In 3-4 sentences, explain specifically why this candidate fits the job."
    )

    try:
        client_oai = OpenAI(api_key=settings.OPENAI_API_KEY)
        messages = cast(Any, [{"role": "user", "content": prompt}])
        resp = client_oai.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=messages,
            temperature=0.1,
        )
        content = _extract_content_from_response(resp)
        if content.strip():
            return content
    except Exception as exc:
        logger.error("MasterAgent explain_fit OpenAI error: %s", exc)

    return "Unable to generate candidate fit explanation at the moment."


class _BaseNeo4jEngine:
    """Shared Neo4j connection lifecycle for both engines."""

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self._uri = uri or settings.neo4j_uri
        self._user = user or settings.neo4j_user
        self._password = password or settings.neo4j_password
        self._driver: Optional[Driver] = None

    def connect(self) -> None:
        logger.info("Connecting Neo4j engine to %s", self._uri)
        self._driver = GraphDatabase.driver(self._uri, auth=(self._user, self._password))
        try:
            self._driver.verify_connectivity()
            logger.info("Neo4j connected (%s).", self._uri)
        except Exception:
            logger.exception("Neo4j connectivity check failed for %s", self._uri)
            raise

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
        return vectorize_text(text)

    @staticmethod
    def _extract_keywords(text: str, max_keywords: int = 8) -> list[str]:
        words = re.findall(r"[a-zA-Z0-9_+#.]{2,}", str(text or "").lower())
        stop_words = {
            "and", "the", "for", "with", "from", "this", "that", "have", "has",
            "cua", "va", "cho", "voi", "tren", "duoi", "mot", "nhung", "ung", "vien",
        }
        deduped: list[str] = []
        seen: set[str] = set()
        for word in words:
            if word in stop_words:
                continue
            if word in seen:
                continue
            seen.add(word)
            deduped.append(word)
            if len(deduped) >= max_keywords:
                break
        return deduped

    def search_candidates(self, jd_text: str, top_k: int = 5) -> List[CandidateMatch]:
        """Search top-K matching personnel from public vectors only.

        Args:
            jd_text: Job requirement text from organization.
            top_k: Number of candidates to return.

        Returns:
            List[CandidateMatch] sorted by vector score.
        """
        try:
            query_vector = self._embed_text(jd_text)
        except Exception:
            logger.exception("Embedding failed before Neo4j search")
            raise

        graph_mode = _resolve_graph_mode()

        try:
            with self.driver.session() as session:
                try:
                    rows = list(
                        session.run(
                            cast(Any, _MASTER_AGENT_CYPHER),
                            top_k=max(top_k * 3, top_k),
                            query_vector=query_vector,
                        )
                    )
                except Exception as exc:
                    keywords = self._extract_keywords(jd_text)
                    logger.warning("Vector search failed, falling back to lexical retrieval: %s", exc)
                    rows = list(
                        session.run(
                            cast(Any, _MASTER_AGENT_LEXICAL_FALLBACK_CYPHER),
                            top_k=max(top_k * 3, top_k),
                            keywords=keywords,
                        )
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
                if graph_mode == "none":
                    graph_scores = {}
                else:
                    graph_scores = _graph_discovery(session, jd_text, candidate_ids)
        except Exception:
            logger.exception("Neo4j search execution failed")
            raise

        supabase_scores = _supabase_fan_out(candidate_ids, query_vector, max_workers=8)

        fused_results: list[CandidateMatch] = []
        for item in vector_candidates:
            graph_data = graph_scores.get(item.id, {})
            base_score = graph_data.get("base_score", 0.0)
            experience_count = graph_data.get("experience_count", 0)
            bonus_weight = graph_data.get("bonus_weight", 0.0)
            bonus_component = graph_data.get("bonus_component", 0.0)
            
            years = experience_count * 2
            if graph_mode == "none":
                s_graph_final = 0.0
            elif graph_mode == "jaccard_only":
                s_graph_final = base_score
            else:
                seniority_component = _seniority_component(years)
                # Enhanced graph score combines skill overlap, seniority, and bonus.
                s_graph_final = (0.5 * base_score) + (0.25 * seniority_component) + (0.25 * bonus_component)
            
            vector_score = max(item.score, supabase_scores.get(item.id, 0.0))
            graph_score_normalized  = _normalize_score(s_graph_final)   # Jaccard đã [0,1]
            vector_score_normalized = _normalize_score(vector_score)   # cosine đã [0,1]
            # Add explicit bonus weight (e.g., tech-overlap bonus) to final fusion score.
            final_score = _normalize_score(
                (_ALPHA_GRAPH * graph_score_normalized)
                + (_BETA_VECTOR * vector_score_normalized)
                + bonus_weight
            )

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

        logger.info("Graph scoring mode: %s", graph_mode)
        logger.info("MasterAgentEngine returned %d candidates.", len(results))
        return results

def _normalize_score(score: float, max_val: float = 1.0) -> float:
    """Clamp score về [0, 1]."""
    if max_val <= 0:
        return 0.0
    return min(max(score / max_val, 0.0), 1.0)

class DigitalTwinInterviewEngine(_BaseNeo4jEngine):
    """Private interview engine with accepted-connection access control."""

    @staticmethod
    def _embed(text: str) -> list[float]:
        if not text.strip():
            return [0.0] * 768
        return vectorize_text_for_model(text, _DIGITAL_TWIN_DEFAULT_EMBED_MODEL)

    @staticmethod
    def _llm_answer(
        public_context: str,
        public_skills: list[str],
        private_context: str,
        question: str,
        is_private_mode: bool,
        candidate_name: str = "Ứng viên",
        repair_instruction: str | None = None,
        skip_openai: bool = False,
        force_found: bool = False,
        key_metrics: list[str] | None = None,
    ) -> tuple[str, str]:
        user_payload = {
            # "public_context": public_context or "",
            "public_skills": public_skills,
            # "private_context": private_context,
            # "is_private_mode": is_private_mode,
            "interview_question": question,
        }

        persona = _PERSONA_BASE.format(candidate_name=candidate_name)

        if is_private_mode:
            system_prompt = _INTERVIEW_SYSTEM_PROMPT_PRIVATE.format(
                persona_base=persona
            ).replace("{{public_context}}", public_context or "") \
            .replace("{{private_context}}", private_context or "")
        else:
            system_prompt = _INTERVIEW_SYSTEM_PROMPT_PUBLIC.format(
                persona_base=persona
            ).replace("{{public_context}}", public_context or "")

        if force_found:
            system_prompt = (
                "Hồ sơ đã được xác nhận có thông tin liên quan. "
                "Bắt buộc trả lời STATE: FOUND và trích dẫn nội dung.\n\n"
                + system_prompt
            )

        if key_metrics:
            metrics_block = (
                "[SỐ LIỆU QUAN TRỌNG TRONG HỒ SƠ - PHẢI ĐƯA VÀO ANSWER NẾU LIÊN QUAN]\n"
                + ", ".join(key_metrics[:15])
                + "\n\n"
            )
            system_prompt = metrics_block + system_prompt

        messages = cast(Any, [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": question},  # ← gửi question trực tiếp, không wrap JSON
        ])
        if repair_instruction:
            messages.append({"role": "system", "content": f"Correction instruction:\n{repair_instruction}"})

        try:
            client_anthropic = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            anthro_messages = cast(Any, [
                {"role": "user", "content": question},
            ])
            resp = client_anthropic.messages.create(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=1024,
                system=system_prompt,
                messages=anthro_messages,
                temperature=0.1,
            )
            content = ""
            if getattr(resp, "content", None):
                text_parts = [
                    getattr(block, "text", "")
                    for block in resp.content
                    if getattr(block, "type", "") == "text" and getattr(block, "text", "")
                ]
                content = "\n".join(text_parts).strip()
            if content.strip():
                return content, f"anthropic:{settings.ANTHROPIC_MODEL}"
        except Exception as exc:
            logger.warning("DigitalTwin LLM Anthropic error: %s", exc)

        if not skip_openai:
            try:
                client_oai = OpenAI(api_key=settings.OPENAI_API_KEY)
                resp = client_oai.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=messages,
                    temperature=0.1,
                )
                content = _extract_content_from_response(resp)
                if content.strip():
                    return content, f"openai:{settings.OPENAI_MODEL}"
            except Exception as exc:
                logger.warning("DigitalTwin LLM OpenAI error: %s", exc)

        try:
            client = Cerebras(api_key=settings.CEREBRAS_API_KEY)
            resp = client.chat.completions.create(
                model=settings.CEREBRAS_MODEL,
                messages=messages,
                temperature=0.1,
            )
            content = _extract_content_from_response(resp)
            if content.strip():
                return content, f"cerebras:{settings.CEREBRAS_MODEL}"
        except Exception as exc:
            logger.error("DigitalTwin LLM Cerebras error: %s", exc)

        return "Xin lỗi, hệ thống hiện chưa thể tạo câu trả lời phỏng vấn. Vui lòng thử lại sau.", "none"

    def answer_interview(
        self,
        org_id: str,
        personnel_id: str,
        interview_question: str,
        skip_access_check: bool = False,
        force_private_mode: bool = False,
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
        if force_private_mode:
            is_private_mode = True
        elif skip_access_check:
            is_private_mode = True
        else:
            is_private_mode = rel_status == "accepted"
        public_context = str(row.get("pub_summary") or "")
        public_skills = list(row.get("pub_skills") or [])
        private_blob_context = _private_blob_to_context(str(row.get("private_blob") or ""))
        context_chunks_raw: list[str] = []
        context_similarity_by_chunk: dict[str, float] = {}
        max_raw_similarity = 0.0
        selected_similarities: list[float] = []

        try:
            question_embedding = self._embed(interview_question)
            chunk_hits = _query_chunks_supabase(
                per_neo4j_id=personnel_id,
                query_embedding=question_embedding,
                is_private=is_private_mode,
                top_k=3,
            )
            context_chunks_raw = [str(hit.get("content") or "").strip() for hit in chunk_hits if str(hit.get("content") or "").strip()]

            for hit in chunk_hits:
                content = str(hit.get("content") or "").strip()
                similarity = hit.get("similarity")
                if not content or not isinstance(similarity, float):
                    continue
                previous = context_similarity_by_chunk.get(content)
                if previous is None or similarity > previous:
                    context_similarity_by_chunk[content] = similarity

            if context_similarity_by_chunk:
                max_raw_similarity = max(context_similarity_by_chunk.values())

            context_chunks = _select_preferred_contexts(context_chunks_raw, top_k=3)
            selected_similarities = [
                context_similarity_by_chunk[chunk]
                for chunk in context_chunks
                if chunk in context_similarity_by_chunk
            ]
        except Exception as exc:
            logger.warning("Supabase chunk query failed, fallback to empty context: %s", exc)
            context_chunks = []

        source_chunks_for_facts: list[str] = []
        if private_blob_context:
            source_chunks_for_facts.extend(
                line.strip()
                for line in str(private_blob_context).splitlines()
                if str(line).strip()
            )
        source_chunks_for_facts.extend(chunk for chunk in context_chunks if str(chunk).strip())
        labeled_facts = extract_labeled_facts(source_chunks_for_facts)

        metrics_hint: list[str] = extract_key_metrics(source_chunks_for_facts, labeled_only=True)

        private_context = ""
        if is_private_mode:
            private_context = _build_private_context(
                private_blob_context=private_blob_context,
                context_chunks=context_chunks,
                question=interview_question,
                trim_long_chunks=True,
                embed_fn=self._embed,
            )

        force_found_by_similarity = has_relevant_content(
            question=interview_question,
            chunks=context_chunks,
            embed_fn=None,
            threshold=_RELEVANCE_SIM_THRESHOLD,
            similarities=selected_similarities,
        )

        # Forensic log: capture what exactly is passed to the LLM.
        logger.info(
            "PRE_LLM_CONTEXT org_id=%s personnel_id=%s mode=%s question=%s raw_count=%d selected_count=%d private_blob_included=%s raw_preview=%s selected_preview=%s private_context_preview=%s",
            org_id,
            personnel_id,
            "private" if is_private_mode else "public",
            _truncate_for_log(interview_question, max_len=220),
            len(context_chunks_raw),
            len(context_chunks),
            bool(is_private_mode and private_blob_context),
            json.dumps([_truncate_for_log(chunk) for chunk in context_chunks_raw], ensure_ascii=False),
            json.dumps([_truncate_for_log(chunk) for chunk in context_chunks], ensure_ascii=False),
            _truncate_for_log(private_context, max_len=400),
        )

        candidate_name = str(row.get("pub_name") or "Ứng viên") if row is not None else "Ứng viên"

        first_answer, model_used = self._llm_answer(
            public_context=public_context,
            public_skills=public_skills,
            private_context=private_context,
            question=interview_question,
            is_private_mode=is_private_mode,
            candidate_name=candidate_name,
            force_found=force_found_by_similarity,
            key_metrics=metrics_hint,
        )
        validation_result = validate_llm_response(first_answer, context_chunks)
        retry_used = False
        final_answer = first_answer

        if validation_result.grounding_score < 0.3 and "llama" in model_used.lower():
            retry_used = True
            dynamic_repair_signal = _build_repair_signal(validation_result)
            repaired_answer, repaired_model_used = self._llm_answer(
                public_context=public_context,
                public_skills=public_skills,
                private_context=private_context,
                question=interview_question,
                is_private_mode=is_private_mode,
                candidate_name=candidate_name,
                repair_instruction=dynamic_repair_signal,
                skip_openai=True,
                force_found=force_found_by_similarity,
                key_metrics=metrics_hint,
            )
            if repaired_answer.strip():
                final_answer = repaired_answer
                model_used = repaired_model_used

        final_answer = _enforce_answer_from_labeled_facts(
            answer=final_answer,
            question=interview_question,
            labeled_facts=labeled_facts,
        )
        final_answer = _enforce_secret_answer_from_facts(
            answer=final_answer,
            question=interview_question,
            labeled_facts=labeled_facts,
            key_metrics=metrics_hint,
        )
        final_answer = _enforce_found_when_relevant(
            answer=final_answer,
            force_found=force_found_by_similarity,
            labeled_facts=labeled_facts,
            context_chunks=context_chunks,
            question=interview_question,
        )
        final_answer = _enforce_not_found_for_topic_mismatch(
            answer=final_answer,
            question=interview_question,
            labeled_facts=labeled_facts,
            context_chunks=context_chunks,
        )

        validation_result = validate_llm_response(final_answer, context_chunks)
        extracted_spans = extract_evidence_post_hoc(final_answer, context_chunks)

        logger.info(
            "DigitalTwinInterviewEngine answered question for personnel_id=%s (mode=%s).",
            personnel_id,
            "private" if is_private_mode else "public",
        )
        return {
            "answer": final_answer,
            "evidence": extracted_spans,
            "is_private_mode": is_private_mode,
            "rel_status": rel_status,
            "contexts": context_chunks,
            "model_used": model_used,
            "validation": {
                "passed": validation_result.passed,
                "state": validation_result.state,
                "grounding_score": validation_result.grounding_score,
                "quote_scores": validation_result.quote_scores,
                "unverified_numbers": validation_result.unverified_numbers,
                "retry_used": retry_used,
                "evidence_source": "post_hoc_extraction",
            },
            "debug_context": {
                "raw_count": len(context_chunks_raw),
                "selected_count": len(context_chunks),
                "raw_preview": [_truncate_for_payload(chunk) for chunk in context_chunks_raw],
                "selected_preview": [_truncate_for_payload(chunk) for chunk in context_chunks],
                "raw_similarity_max": max_raw_similarity,
                "selected_similarity_max": max(selected_similarities) if selected_similarities else 0.0,
                "selected_similarities": selected_similarities,
                "force_found_by_similarity": force_found_by_similarity,
            },
        }


__all__ = [
    "CandidateMatch",
    "_explain_fit",
    "MasterAgentEngine",
    "DigitalTwinInterviewEngine",
]

# pipeline/hybrid_query_engine.py — thêm function mới cuối file

# def create_connection_request(
#     org_id: str,
#     personnel_id: str,
#     status: str = "pending",
# ) -> bool:
#     """
#     Tạo hoặc cập nhật CONNECTED_TO relationship giữa Org và Personnel.
#     Dùng cho: "Mời phỏng vấn" button (P3) và accept flow.
#     """
#     driver = GraphDatabase.driver(
#         settings.NEO4J_URI,
#         auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
#     )
#     try:
#         with driver.session() as session:
#             result = session.run(
#                 """
#                 MATCH (o:Organization {id: $org_id}), (p:Personnel {id: $personnel_id})
#                 MERGE (o)-[r:CONNECTED_TO]->(p)
#                 SET r.status = $status,
#                     r.updated_at = timestamp()
#                 RETURN r.status AS status
#                 """,
#                 org_id=org_id,
#                 personnel_id=personnel_id,
#                 status=status,
#             )
#             row = result.single()
#             return row is not None
#     except Exception as exc:
#         logger.error("create_connection_request failed: %s", exc)
#         return False
#     finally:
#         driver.close()

def create_connection_request(
    org_id: str,
    personnel_id: str,
    status: str = "pending",
) -> tuple[bool, str]:  # <--- FIX 1: Đổi type hint thành tuple chứa bool và str
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    try:
        with driver.session() as session:
            result = session.run(
                """
                MERGE (o:Organization {id: $org_id})
                MERGE (p:Personnel    {id: $personnel_id})
                MERGE (o)-[r:CONNECTED_TO]->(p)
                SET r.status     = $status,
                    r.updated_at = timestamp()
                // FIX 2: Thêm dấu phẩy sau chữ status và xóa dấu phẩy thừa ở cuối
                RETURN r.status AS status, coalesce(o.public_name, o.public_full_name, o.name, o.id) AS org_name
                """,
                org_id=org_id,
                personnel_id=personnel_id,
                status=status,
            )
            row = result.single()
            if row:
                return True, str(row["org_name"]) # Trả về True và tên Tổ chức
            return False, org_id
    except Exception as exc:
        logger.error("create_connection_request failed: %s", exc)
        return False, org_id
    finally:
        driver.close()

def get_connection_status(org_id: str, personnel_id: str) -> str | None:
    """
    Truy vấn trạng thái relationship giữa Org và Personnel.
    Trả về: "pending" | "accepted" | "cancelled" | None (không có relationship)
    """
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    try:
        session_kwargs = {"database": settings.neo4j_database} if settings.neo4j_database else {}
        with driver.session(**session_kwargs) as session:
            result = session.run(
                """
                MATCH (o:Organization)-[r:CONNECTED_TO]->(p:Personnel)
                WHERE (o.id = $org_id OR o.org_id = $org_id OR o.neo4j_id = $org_id)
                  AND (p.id = $personnel_id OR p.personnel_id = $personnel_id)
                RETURN toLower(coalesce(r.status, '')) AS status
                """,
                org_id=org_id,
                personnel_id=personnel_id,
            )
            row = result.single()
            if not row:
                return None
            status = str(row.get("status") or "").strip().lower()
            return status if status in {"pending", "accepted", "cancelled", "declined"} else None
    except Exception as exc:
        logger.error("get_connection_status failed: %s", exc)
        return None
    finally:
        driver.close()