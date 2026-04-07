from __future__ import annotations

import json
import re
import uuid
from typing import Any

from pipeline.config import get_logger
from pipeline.schemas import RecruitmentNode
from pipeline.supabase_client import get_supabase
from pipeline.vectorizer import vectorize_text

logger = get_logger(__name__)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _neo4j_id_to_uuid(neo4j_id: str) -> str:
    """Deterministic UUID from Neo4j ID to keep stable bridge key mapping."""
    namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
    return str(uuid.uuid5(namespace, neo4j_id))


def _vector_literal(vector_values: list[float]) -> str:
    """PostgREST vector columns accept pgvector string literal format."""
    return "[" + ",".join(str(float(v)) for v in vector_values) + "]"


def _internal_email_from_neo4j_id(neo4j_id: str) -> str:
    local_part = re.sub(r"[^a-z0-9]", "", neo4j_id.lower())
    local_part = local_part or "internaluser"
    return f"{local_part}@internal.digitaltwins.local"


def _ensure_user_exists(sb: Any, user_id: str, node: RecruitmentNode) -> None:
    """Ensure auth/vdme user exists before writing FK-dependent rows."""
    row = (
        sb.schema("vdme")
        .table("users")
        .select("id")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    if row.data:
        return

    try:
        sb.auth.admin.create_user(
            {
                "id": user_id,
                "email": _internal_email_from_neo4j_id(node.neo4j_id),
                "password": "InternalOnly@2026!",
                "email_confirm": True,
                "user_metadata": {
                    "full_name": node.public_data.full_name or node.neo4j_id,
                    "role": node.role,
                    "neo4j_id": node.neo4j_id,
                },
            }
        )
    except Exception as exc:
        # Auth user may already exist; keep flow idempotent.
        logger.debug("[Supabase] ensure_user auth create: %s", exc)


def _make_chunks(node: RecruitmentNode, user_id: str) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    pub = node.public_data

    if pub.professional_summary:
        chunks.append(
            {
                "user_id": user_id,
                "is_public": True,
                "content": pub.professional_summary,
                "metadata": {"section": "summary"},
            }
        )

    if pub.skills:
        chunks.append(
            {
                "user_id": user_id,
                "is_public": True,
                "content": "Ky nang: " + ", ".join(pub.skills),
                "metadata": {"section": "skills"},
            }
        )

    # Phase 4 v2: mỗi experience là một chunk riêng.
    for exp in pub.experience:
        if isinstance(exp, dict):
            exp_data = exp
        else:
            exp_data = _as_dict(getattr(exp, "model_dump", lambda: {})())

        if not exp_data:
            continue

        parts = [
            f"Du an: {str(exp_data.get('project_name') or '').strip()}",
            f"Vai tro: {str(exp_data.get('role') or '').strip()}",
        ]
        org_name = str(exp_data.get("organization_name") or "").strip()
        if org_name:
            parts.append(f"Cong ty: {org_name}")

        tech_stack = exp_data.get("tech_stack")
        if isinstance(tech_stack, list) and tech_stack:
            tech_items = [str(t).strip() for t in tech_stack if str(t).strip()]
            if tech_items:
                parts.append(f"Cong nghe: {', '.join(tech_items)}")

        content = " | ".join([p for p in parts if p and not p.endswith(": ")]).strip()
        if not content:
            continue

        chunks.append(
            {
                "user_id": user_id,
                "is_public": True,
                "content": content,
                "metadata": {
                    "section": "experience",
                    "organization": org_name,
                    "project": str(exp_data.get("project_name") or "").strip(),
                },
            }
        )

    # Phase 4 v2: mỗi education là một chunk riêng.
    for edu in pub.education:
        if isinstance(edu, dict):
            edu_data = edu
        else:
            edu_data = _as_dict(getattr(edu, "model_dump", lambda: {})())

        if not edu_data:
            continue

        degree = str(edu_data.get("degree") or "").strip()
        major = str(edu_data.get("major") or "").strip()
        school = str(edu_data.get("school") or "").strip()
        year = edu_data.get("year")
        year_text = f" ({year})" if year is not None and str(year).strip() else ""

        edu_content = f"{degree} {major} tai {school}{year_text}".strip()
        if not edu_content:
            continue

        chunks.append(
            {
                "user_id": user_id,
                "is_public": True,
                "content": edu_content,
                "metadata": {"section": "education", "school": school},
            }
        )

    priv = node.private_data
    if priv.project_technical_secrets:
        chunks.append(
            {
                "user_id": user_id,
                "is_public": False,
                "content": f"[Bí mật kỹ thuật] {priv.project_technical_secrets}",
                "metadata": {"section": "secrets"},
            }
        )

    if priv.salary_expectation:
        chunks.append(
            {
                "user_id": user_id,
                "is_public": False,
                "content": f"[Lương kỳ vọng] {priv.salary_expectation}",
                "metadata": {"section": "salary"},
            }
        )

    for qa in priv.interview_questions_history:
        qa_data = qa.model_dump() if hasattr(qa, "model_dump") else _as_dict(qa)
        chunks.append(
            {
                "user_id": user_id,
                "is_public": False,
                "content": f"Q: {str(qa_data.get('question') or '')}\nA: {str(qa_data.get('answer') or '')}",
                "metadata": {"section": "interview_history", "org": str(qa_data.get('org') or '')},
            }
        )

    if priv.blacklist_orgs:
        chunks.append(
            {
                "user_id": user_id,
                "is_public": False,
                "content": "[Blacklist] " + ", ".join(priv.blacklist_orgs),
                "metadata": {"section": "blacklist"},
            }
        )

    return chunks


def _embed_chunks(user_id: str, model_name: str = "phobert") -> None:
    """Generate embeddings for chunks and store in vdme.chunk_embeddings."""
    sb = get_supabase()

    chunks = (
        sb.schema("vdme")
        .table("document_chunks")
        .select("id, content")
        .eq("user_id", user_id)
        .execute()
    ).data or []

    chunk_ids = [str(_as_dict(c).get("id")) for c in chunks if _as_dict(c).get("id") is not None]
    if not chunk_ids:
        return

    existing_rows = (
        sb.schema("vdme")
        .table("chunk_embeddings")
        .select("chunk_id")
        .eq("model_name", model_name)
        .in_("chunk_id", chunk_ids)
        .execute()
    ).data or []

    existing_chunk_ids = set()
    for raw_row in existing_rows:
        row = _as_dict(raw_row)
        if row.get("chunk_id") is not None:
            existing_chunk_ids.add(str(row.get("chunk_id")))

    to_embed = []
    for raw_chunk in chunks:
        chunk = _as_dict(raw_chunk)
        if not chunk:
            continue
        if str(chunk.get("id")) in existing_chunk_ids:
            continue
        to_embed.append(chunk)
    if not to_embed:
        return

    records: list[dict[str, Any]] = []
    for chunk in to_embed:
        chunk_id = chunk.get("id")
        content = str(chunk.get("content") or "")
        if not chunk_id or not content.strip():
            continue

        vector = vectorize_text(content)
        records.append(
            {
                "chunk_id": chunk_id,
                "model_name": model_name,
                "embedding_768": _vector_literal(vector),
            }
        )

    if records:
        (
            sb.schema("vdme")
            .table("chunk_embeddings")
            .upsert(records, on_conflict="chunk_id,model_name")
            .execute()
        )
        logger.info("[Supabase] Embedded %d chunks for user=%s", len(records), user_id)


def ingest_to_supabase(node: RecruitmentNode) -> None:
    """Write normalized node data into Supabase tables after Neo4j ingest succeeds."""
    # Defensive normalization for legacy payloads that may bypass modern extraction flow.
    node = RecruitmentNode.model_validate(node.model_dump())
    if not node.neo4j_id:
        return

    sb = get_supabase()
    user_id = _neo4j_id_to_uuid(node.neo4j_id)
    priv = node.private_data

    _ensure_user_exists(sb, user_id, node)

    (
        sb.schema("vdme")
        .table("users")
        .upsert(
            {
                "id": user_id,
                "role": node.role,
                "full_name": node.public_data.full_name or node.neo4j_id,
                "neo4j_id": node.neo4j_id,
            },
            on_conflict="id",
        )
        .execute()
    )

    (
        sb.schema("vdme")
        .table("profiles")
        .upsert(
            {
                "user_id": user_id,
                "email": priv.contact.email,
                "phone": priv.contact.phone,
                "salary_expectation": priv.salary_expectation,
                "project_technical_secrets": priv.project_technical_secrets,
                "contact_links": priv.contact.model_dump(),
                "interview_questions_history": [q.model_dump() for q in priv.interview_questions_history],
                "blacklist_orgs": priv.blacklist_orgs,
                "evidence_links": priv.evidence_links,
                "additional_information": priv.additional_information,
            },
            on_conflict="user_id",
        )
        .execute()
    )

    sb.schema("vdme").table("document_chunks").delete().eq("user_id", user_id).execute()
    chunks = _make_chunks(node, user_id)
    if chunks:
        sb.schema("vdme").table("document_chunks").insert(chunks).execute()

    try:
        _embed_chunks(user_id)
    except Exception as embed_err:
        logger.warning("[Supabase] Embed failed (non-fatal): %s", embed_err)

    logger.info("[Supabase] Ingest: %s -> %s, chunks=%d", node.neo4j_id, user_id, len(chunks))
