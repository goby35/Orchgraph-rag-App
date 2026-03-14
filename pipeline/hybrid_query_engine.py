"""
Hybrid Query Engine — Transparent AI Digital Twin.

Xử lý câu hỏi người dùng qua 4 bước:
  1. **Embed Query**   — PyVi + PhoBERT → vector 768-d.
  2. **Hybrid Retrieve** — Graph-First Entity Matching + Vector Search.
     - Luồng 1 (Graph Exact Match): Trích xuất tên riêng → MATCH Entity trực tiếp.
     - Luồng 2 (Vector Search):     Top-K cosine similarity trên embedding.
     - Gộp kết quả, ưu tiên Luồng 1 lên đầu, loại bỏ chunk trùng lặp.
  3. **Context Assembly** — Đóng gói ngữ cảnh có cấu trúc cho LLM.
  4. **LLM Synthesis**  — Cerebras (primary) / OpenAI (fallback) → câu trả lời.

Usage::

    python -m pipeline.hybrid_query_engine "Phạm Thúy Vi làm việc trong dự án nào?"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from typing import Any, Dict, List, Optional

from cerebras.cloud.sdk import Cerebras
from neo4j import GraphDatabase, Driver
from neo4j.exceptions import ServiceUnavailable, AuthError
from openai import OpenAI
from pyvi import ViTokenizer

from pipeline.config import settings, get_logger
from pipeline.vectorizer import _embedder  # reuse singleton PhoBERT

logger = get_logger("pipeline.hybrid_query_engine")


# ============================================================================
# YÊU CẦU 1: Embed Query
# ============================================================================


def embed_query(user_query: str) -> List[float]:
    """Nhúng câu hỏi người dùng thành vector 768-d.

    Pipeline đồng nhất với ingestion:
      1. ``pyvi.ViTokenizer.tokenize()`` — nối từ ghép tiếng Việt.
      2. PhoBERT CLS embedding — cùng model ``vinai/phobert-base-v2``.

    Args:
        user_query: Câu hỏi tiếng Việt dạng raw text.

    Returns:
        List[float] — vector 768 chiều.
    """
    segmented = ViTokenizer.tokenize(user_query) if user_query else ""
    logger.debug("Query segmented: %s", segmented[:120])
    embedding = _embedder.embed(segmented)
    logger.info("Đã nhúng câu hỏi (dim=%d).", len(embedding))
    return embedding


# ============================================================================
# YÊU CẦU 1.5: Query Decomposition — Trích xuất Anchor Entities bằng LLM
# ============================================================================

_ANCHOR_EXTRACTION_PROMPT = """\
Bạn là bộ phân tích câu hỏi tiếng Việt. Nhiệm vụ: trích xuất các thực thể \
mỏ neo (anchor entities) từ câu hỏi người dùng.

Trả về DUY NHẤT một JSON object (không markdown, không giải thích) với cấu trúc:
{
  "person_anchors": [],
  "project_anchors": [],
  "role_anchors": [],
  "concept_anchors": []
}

Quy tắc TUYỆT ĐỐI:
1. CHỈ trích xuất tên riêng / danh từ riêng THỰC SỰ xuất hiện trong câu hỏi.
2. Nếu câu hỏi nói "dự án" nhưng KHÔNG có tên dự án cụ thể → project_anchors = []
3. Nếu câu hỏi nói "ai" hoặc hỏi về người nhưng KHÔNG có tên người → person_anchors = []
4. KHÔNG ĐƯỢC bịa thêm bất kỳ thực thể nào không có trong câu hỏi.
5. KHÔNG điền các cụm mô tả như "chưa đề cập", "không rõ", "N/A".
6. Giữ nguyên tên riêng tiếng Việt, không dịch.
7. Mỗi anchor phải là TÊN RIÊNG cụ thể (ví dụ: "Phạm Thúy Vi", "BioHealth", "Backend Developer").

Ví dụ:
- "Phạm Thúy Vi làm việc trong dự án nào?" → {"person_anchors": ["Phạm Thúy Vi"], "project_anchors": [], "role_anchors": [], "concept_anchors": []}
- "Ai là Backend Developer trong dự án BioHealth?" → {"person_anchors": [], "project_anchors": ["BioHealth"], "role_anchors": ["Backend Developer"], "concept_anchors": []}
- "Quy trình onboarding nhân sự mới là gì?" → {"person_anchors": [], "project_anchors": [], "role_anchors": [], "concept_anchors": ["onboarding nhân sự mới"]}
"""


def _call_llm_for_anchors(user_query: str) -> Dict[str, List[str]]:
    """Gọi LLM nhỏ/nhanh để phân tích câu hỏi thành các Anchor Entities.

    Thử Cerebras (nhanh) → fallback OpenAI.

    Returns:
        Dict với keys: person_anchors, project_anchors, role_anchors, concept_anchors.
    """
    messages = [
        {"role": "system", "content": _ANCHOR_EXTRACTION_PROMPT},
        {"role": "user", "content": user_query},
    ]

    raw_text: str = ""

    # --- Primary: Cerebras (fast) ---
    try:
        client = Cerebras(api_key=settings.CEREBRAS_API_KEY)
        resp = client.chat.completions.create(
            model=settings.CEREBRAS_MODEL,
            messages=messages,
            temperature=0.0,
        )
        raw_text = resp.choices[0].message.content or ""
    except Exception as exc:
        logger.warning("Anchor LLM (Cerebras) lỗi: %s — fallback OpenAI.", exc)

    if not raw_text.strip():
        try:
            client_oai = OpenAI(api_key=settings.OPENAI_API_KEY)
            resp = client_oai.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=messages,
                temperature=0.0,
            )
            raw_text = resp.choices[0].message.content or ""
        except Exception as exc:
            logger.warning("Anchor LLM (OpenAI) cũng lỗi: %s", exc)
            return _empty_anchors()

    # --- Parse JSON ---
    return _parse_anchor_json(raw_text)


def _empty_anchors() -> Dict[str, List[str]]:
    return {
        "person_anchors": [],
        "project_anchors": [],
        "role_anchors": [],
        "concept_anchors": [],
    }


# Từ khóa rác LLM hay bịa ra thay vì trả list rỗng
_GARBAGE_ANCHOR_PATTERNS = re.compile(
    r"chưa (được )?(đề cập|rõ|xác định|biết)"
    r"|không (có|rõ|xác định)"
    r"|N/?A"
    r"|none"
    r"|null"
    r"|unknown"
    r"|not (mentioned|specified|available)",
    re.IGNORECASE,
)


def _is_valid_anchor(value: str) -> bool:
    """Loại bỏ các anchor rác / hallucination từ LLM."""
    if len(value) < 2:
        return False
    if _GARBAGE_ANCHOR_PATTERNS.search(value):
        return False
    return True


def _parse_anchor_json(raw_text: str) -> Dict[str, List[str]]:
    """Parse JSON trả về từ LLM, xử lý lỗi an toàn."""
    try:
        # Loại bỏ markdown code fences nếu LLM trả về ```json ... ```
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"```\s*$", "", cleaned)
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            logger.warning("Anchor JSON không phải dict — dùng rỗng.")
            return _empty_anchors()

        result = _empty_anchors()
        for key in result:
            if key in data and isinstance(data[key], list):
                result[key] = [
                    str(v).strip() for v in data[key]
                    if v and _is_valid_anchor(str(v).strip())
                ]
        return result

    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("Không parse được Anchor JSON: %s — raw: %s", exc, raw_text[:200])
        return _empty_anchors()


def extract_potential_entities(user_query: str) -> Dict[str, List[str]]:
    """Phân tích câu hỏi bằng LLM để trích xuất Anchor Entities phân loại.

    Gọi LLM nhỏ/nhanh (Cerebras → OpenAI fallback) để trả về JSON dict
    với 4 loại anchor: person, project, role, concept.

    Args:
        user_query: Câu hỏi tiếng Việt dạng raw text.

    Returns:
        Dict[str, List[str]] — các anchor đã phân loại.
    """
    if not user_query:
        return _empty_anchors()

    anchors = _call_llm_for_anchors(user_query)

    total = sum(len(v) for v in anchors.values())
    if total > 0:
        logger.info("Anchor Entities từ LLM: %s", anchors)
    else:
        logger.info("LLM không phát hiện anchor nào trong câu hỏi.")

    return anchors


# ============================================================================
# YÊU CẦU 2: Hybrid Retriever (Graph-First + Vector)
# ============================================================================

# --- Luồng 1: Graph Anchor Hits Scoring ---
# Đếm số anchor trùng khớp trên mỗi Chunk → xếp hạng → LIMIT → lấy Triplets
_GRAPH_ANCHOR_MAX_CHUNKS = 8

_GRAPH_ANCHOR_CYPHER = """
WITH $anchor_names AS anchors
UNWIND anchors AS aname

MATCH (chunk:Chunk)-[:MENTIONS]->(e:Entity)
WHERE toLower(e.name) CONTAINS toLower(aname)

WITH chunk, count(DISTINCT aname) AS match_score
ORDER BY match_score DESC
LIMIT $max_chunks

MATCH (doc:Document)-[:HAS_CHUNK]->(chunk)

OPTIONAL MATCH (chunk)-[:MENTIONS]->(all_ent:Entity)
OPTIONAL MATCH (chunk)-[:MENTIONS]->(src:Entity)-[rel:RELATED_TO]->(tgt:Entity)<-[:MENTIONS]-(chunk)

RETURN DISTINCT
    chunk.chunk_id            AS chunk_id,
    chunk.original_clean_text AS text,
    chunk.chunk_index         AS chunk_index,
    toFloat(match_score)      AS score,
    doc.source_file           AS source_file,
    labels(doc)               AS doc_labels,
    collect(DISTINCT {name: all_ent.name, type: all_ent.type}) AS entities,
    collect(DISTINCT {
        subject: src.name,
        action:  rel.action,
        object:  tgt.name
    }) AS triplets
ORDER BY score DESC
"""

# --- Luồng 2: Vector Search + Graph Traversal ---
# NOTE: Tên index được truyền động qua f-string tại retrieve_by_vector()
_VECTOR_SEARCH_CYPHER_TEMPLATE = """
CALL db.index.vector.queryNodes('{index_name}', $top_k, $query_vector)
YIELD node AS chunk, score

WITH chunk, score
ORDER BY score DESC

MATCH (doc:Document)-[:HAS_CHUNK]->(chunk)

OPTIONAL MATCH (chunk)-[:MENTIONS]->(entity:Entity)

OPTIONAL MATCH (chunk)-[:MENTIONS]->(src:Entity)-[rel:RELATED_TO]->(tgt:Entity)<-[:MENTIONS]-(chunk)

RETURN
    chunk.chunk_id        AS chunk_id,
    chunk.original_clean_text AS text,
    chunk.chunk_index     AS chunk_index,
    score,
    doc.source_file       AS source_file,
    labels(doc)           AS doc_labels,
    collect(DISTINCT {name: entity.name, type: entity.type}) AS entities,
    collect(DISTINCT {
        subject: src.name,
        action:  rel.action,
        object:  tgt.name
    }) AS triplets
"""


class HybridRetriever:
    """Truy xuất lai (Vector + Graph) từ Neo4j.

    Args:
        uri: Bolt URI.
        user: Neo4j username.
        password: Neo4j password.
        top_k: Số chunk tương đồng nhất cần lấy.
        model_name: Tên model embedding (vd: ``phobert_v2``, ``bge_m3``).
            Quyết định vector index ``vector_index_{model_name}`` để
            query. Mặc định ``phobert_v2`` (backward compatible).
    """

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        top_k: int = 5,
        model_name: str = "phobert_v2",
    ) -> None:
        self._uri = uri or settings.NEO4J_URI
        self._user = user or settings.NEO4J_USER
        self._password = password or settings.NEO4J_PASSWORD
        self.top_k = top_k
        self.model_name = model_name
        self._driver: Optional[Driver] = None

    # --- Connection ---

    def connect(self) -> None:
        self._driver = GraphDatabase.driver(
            self._uri, auth=(self._user, self._password),
        )
        self._driver.verify_connectivity()
        logger.info("Neo4j connected (%s).", self._uri)

    def close(self) -> None:
        if self._driver:
            self._driver.close()
            self._driver = None

    def __enter__(self) -> "HybridRetriever":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def driver(self) -> Driver:
        if self._driver is None:
            raise RuntimeError("Chưa kết nối Neo4j. Gọi connect() trước.")
        return self._driver

    # --- Core retrieval ---

    @staticmethod
    def _parse_records(result) -> List[Dict[str, Any]]:
        """Chuyển đổi Cypher result thành danh sách dict chuẩn."""
        records: List[Dict[str, Any]] = []
        for record in result:
            entities = [
                e for e in record["entities"]
                if e.get("name") is not None
            ]
            triplets = [
                t for t in record["triplets"]
                if t.get("subject") is not None and t.get("object") is not None
            ]
            records.append({
                "chunk_id": record["chunk_id"],
                "text": record["text"],
                "chunk_index": record["chunk_index"],
                "score": record["score"],
                "source_file": record["source_file"],
                "doc_labels": record["doc_labels"],
                "entities": entities,
                "triplets": triplets,
            })
        return records

    def retrieve_by_anchors(self, anchor_names: List[str]) -> List[Dict[str, Any]]:
        """Luồng 1 — Graph Anchor Hits Scoring: xếp hạng Chunk theo số anchor trùng.

        Mỗi Chunk được chấm điểm = số lượng anchor DISTINCT mà nó MENTIONS.
        Chunk nào chứa nhiều anchor nhất → xếp đầu → LIMIT top N.

        Args:
            anchor_names: Danh sách tên anchor (person, project, role, concept).

        Returns:
            Danh sách dict chunk, score = số anchor trùng khớp.
        """
        with self.driver.session() as session:
            result = session.run(
                _GRAPH_ANCHOR_CYPHER,
                anchor_names=anchor_names,
                max_chunks=_GRAPH_ANCHOR_MAX_CHUNKS,
            )
            records = self._parse_records(result)
        logger.info(
            "Luồng 1 (Anchor Hits Scoring): %d chunk cho anchors %s.",
            len(records), anchor_names,
        )
        return records

    def retrieve_by_vector(self, query_vector: List[float]) -> List[Dict[str, Any]]:
        """Luồng 2 — Vector Search: tìm Chunk qua cosine similarity.

        Sử dụng vector index ``vector_index_{model_name}`` tương ứng
        với model đã chọn lúc khởi tạo.

        Args:
            query_vector: Vector embedding của câu hỏi.

        Returns:
            Danh sách dict chunk, sắp xếp theo score giảm dần.
        """
        index_name = f"vector_index_{self.model_name}"
        cypher = _VECTOR_SEARCH_CYPHER_TEMPLATE.format(index_name=index_name)
        with self.driver.session() as session:
            result = session.run(
                cypher,
                query_vector=query_vector,
                top_k=self.top_k,
            )
            records = self._parse_records(result)
        logger.info(
            "Luồng 2 (Vector Search): %d chunk (index=%s, top_k=%d).",
            len(records), index_name, self.top_k,
        )
        return records

    def retrieve(
        self,
        query_vector: List[float],
        anchors: Dict[str, List[str]] | None = None,
    ) -> List[Dict[str, Any]]:
        """Truy xuất Graph-First Anchor Traversal + Vector Search.

        Luồng 1 (Graph Anchor): chạy nếu có anchor entities (person/project/role/concept).
            Sử dụng traversal depth limit [*1..3] để ngăn lan truyền quá xa.
        Luồng 2 (Vector Search): luôn chạy với top_k giảm (=3) nếu đã có kết quả
            Graph, hoặc top_k gốc nếu không có anchor.

        Kết quả gộp: ưu tiên 100% chunk từ Luồng Graph, chỉ bổ sung
        chunk Vector nếu chưa tồn tại trong tập Graph.

        Args:
            query_vector: Vector embedding của câu hỏi (768-d).
            anchors: Dict anchor đã phân loại từ LLM (có thể None).

        Returns:
            Danh sách dict chunk đã gộp và loại trùng.
        """
        # --- Gộp tất cả anchor names thành 1 list phẳng ---
        anchor_names: List[str] = []
        if anchors:
            for key in ("person_anchors", "project_anchors",
                        "role_anchors", "concept_anchors"):
                anchor_names.extend(anchors.get(key, []))

        graph_records: List[Dict[str, Any]] = []

        # --- Luồng 1: Graph Anchor Traversal (nếu có anchor) ---
        if anchor_names:
            try:
                graph_records = self.retrieve_by_anchors(anchor_names)
                logger.info(
                    "Luồng 1 kết quả: %d chunk từ %d anchors.",
                    len(graph_records), len(anchor_names),
                )
            except Exception as exc:
                logger.warning("Luồng 1 (Graph Anchor) lỗi: %s — bỏ qua.", exc)

        # --- Luồng 2: Vector Search ---
        # Giảm top_k xuống 3 nếu Graph đã có kết quả (tránh nhiễu)
        vector_top_k = 3 if graph_records else self.top_k
        original_top_k = self.top_k
        self.top_k = vector_top_k

        vector_records: List[Dict[str, Any]] = []
        try:
            vector_records = self.retrieve_by_vector(query_vector)
            logger.info(
                "Luồng 2 kết quả: %d chunk (top_k=%d, giảm từ %d).",
                len(vector_records), vector_top_k, original_top_k,
            )
        except Exception as exc:
            logger.warning("Luồng 2 (Vector Search) lỗi: %s", exc)
        finally:
            self.top_k = original_top_k  # restore

        # --- Gộp kết quả: Graph-first, loại trùng theo chunk_id ---
        seen_ids: set[str] = set()
        merged: List[Dict[str, Any]] = []

        # Ưu tiên 100%: xếp chunk từ Luồng 1 lên đầu
        for rec in graph_records:
            cid = rec["chunk_id"]
            if cid not in seen_ids:
                seen_ids.add(cid)
                merged.append(rec)

        # Bổ sung chunk từ Luồng 2 (chỉ thêm nếu chưa có)
        for rec in vector_records:
            cid = rec["chunk_id"]
            if cid not in seen_ids:
                seen_ids.add(cid)
                merged.append(rec)

        logger.info(
            "Tổng hợp: %d chunk (Graph: %d, Vector: %d, trùng loại: %d).",
            len(merged),
            len(graph_records),
            len(vector_records),
            len(graph_records) + len(vector_records) - len(merged),
        )
        return merged


# ============================================================================
# YÊU CẦU 3: Context Assembly (2 kênh: VEC + GRF)
# ============================================================================


def _format_vector_context(retrieved_records: List[Dict[str, Any]]) -> str:
    """Định dạng phần [VEC] — văn bản gốc từ các chunk."""
    if not retrieved_records:
        return "(Không có chunk nào được truy xuất.)"

    blocks: List[str] = []
    for idx, rec in enumerate(retrieved_records, start=1):
        labels = [la for la in rec.get("doc_labels", []) if la != "Document"]
        label_str = ", ".join(labels) if labels else "N/A"
        source = rec.get("source_file", "Không rõ")
        score = rec.get("score", 0.0)
        text = rec.get("text", "").strip()

        header = f"[NGUỒN {idx}: {source} | {label_str} | score: {score:.4f}]"

        # Entities gắn liền chunk
        entities = rec.get("entities", [])
        if entities:
            ent_str = ", ".join(
                f"{e['name']} ({e['type']})" for e in entities
            )
            ent_line = f"Thực thể: {ent_str}"
        else:
            ent_line = ""

        parts = [header, text]
        if ent_line:
            parts.append(ent_line)
        blocks.append("\n".join(parts))

    return "\n\n".join(blocks)


def _format_graph_context(retrieved_records: List[Dict[str, Any]]) -> str:
    """Định dạng phần [GRF] — quan hệ logic (triplets) deduplicated."""
    seen: set[str] = set()
    lines: List[str] = []

    for rec in retrieved_records:
        source = rec.get("source_file", "")
        for t in rec.get("triplets", []):
            subj = t.get("subject", "")
            action = t.get("action", "")
            obj = t.get("object", "")
            if not subj or not obj:
                continue
            key = f"{subj}|{action}|{obj}"
            if key in seen:
                continue
            seen.add(key)

            # Tìm type cho subject và object trong entities cùng chunk
            ent_map: Dict[str, str] = {}
            for e in rec.get("entities", []):
                if e.get("name"):
                    ent_map[e["name"]] = e.get("type", "")

            subj_type = ent_map.get(subj, "")
            obj_type = ent_map.get(obj, "")

            subj_label = f" [{subj_type}]" if subj_type else ""
            obj_label = f" [{obj_type}]" if obj_type else ""

            line = f"({subj}){subj_label} –[{action}]→ ({obj}){obj_label}"
            if source:
                line += f"  (nguồn: {source})"
            lines.append(line)

    if not lines:
        return "(Không có quan hệ logic nào được truy xuất.)"
    return "\n".join(lines)


def format_context(retrieved_records: List[Dict[str, Any]]) -> str:
    """Biến kết quả retrieval thành chuỗi ngữ cảnh tổng hợp (backward compat).

    Kết hợp cả [VEC] và [GRF] thành 1 chuỗi duy nhất.
    Dùng cho hiển thị UI / debug. LLM dùng 2 kênh riêng qua ``generate_response``.

    Args:
        retrieved_records: Output từ ``HybridRetriever.retrieve()``.

    Returns:
        Formatted string.
    """
    if not retrieved_records:
        return "(Không tìm thấy ngữ cảnh liên quan trong cơ sở tri thức.)"

    vec = _format_vector_context(retrieved_records)
    grf = _format_graph_context(retrieved_records)

    return (
        "━━━ NGỮ CẢNH VĂN BẢN [VEC] ━━━\n"
        f"{vec}\n\n"
        "━━━ QUAN HỆ LOGIC [GRF] ━━━\n"
        f"{grf}"
    )


# ============================================================================
# YÊU CẦU 4: LLM Synthesis & Fallback
# ============================================================================

_SYSTEM_PROMPT = """\
Bạn là Digital Twin Agent của NovaTech Solutions — một trợ lý phân tích nhân \
sự minh bạch, có khả năng lý luận đa bước dựa trên Đồ thị Tri thức (Knowledge Graph).

Ngữ cảnh được cung cấp gồm 2 dạng:
  [VEC] Các chunk được embedding từ Neo4j (đoạn CV / SOP / PROJECT liên quan nhất)
  [GRF] Các quan hệ logic từ Neo4j theo dạng: (Subject) –[relation]→ (Object) [type]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NGUYÊN TẮC SUY LUẬN (áp dụng theo thứ tự ưu tiên)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

① ƯU TIÊN SUY LUẬN QUA TRIPLET — KHÔNG CHỈ LỌC THEO TYPE
  Khi người dùng hỏi về "dự án", ĐỪNG chỉ tìm entity có type PROJECT.
  Thay vào đó, duyệt qua các triplet có relation:
    • "phát triển", "xây dựng", "triển khai", "chủ trì", "dẫn dắt"
    • "phụ trách", "tham gia", "đạt milestone", "bao gồm giai đoạn"
  Object của các triplet đó — dù được label PRODUCT, TOOL, hay CONCEPT —
  ĐỀU có thể là dự án mà người đó đã tham gia.

  Ví dụ: (Nguyễn Hoài Tưởng) –[phát triển]→ (NovaFlow) [type: PRODUCT]
  → "NovaFlow" LÀ một dự án anh ấy đã làm, dù type là PRODUCT.

② PHÂN BIỆT ORG VÀ PROJECT — KHÔNG ĐƯỢC NHẦM LẪN
  • ORG  = Nơi người đó làm việc (TechVision JSC, NovaTech Solutions)
           Triplet điển hình: (Person) –[làm việc tại]→ (ORG)
  • PROJECT_REF = Sản phẩm/hệ thống người đó XÂY DỰNG hoặc PHỤ TRÁCH
           Triplet điển hình: (Person) –[phát triển/xây dựng/triển khai]→ (Object)
  TUYỆT ĐỐI không gọi một ORG là "dự án". Nếu không có triplet rõ ràng,
  hãy nói: "Thông tin về dự án cụ thể chưa được ghi nhận trong hồ sơ."

③ TỪ CHỐI LÀ PHƯƠNG ÁN CUỐI CÙNG — SAU KHI ĐÃ SUY LUẬN ĐẦY ĐỦ
  Chỉ nói "không có thông tin" khi:
    (a) Không có triplet nào có relation phù hợp VÀ
    (b) Văn bản gốc [VEC] không nhắc đến chủ đề đó VÀ
    (c) Không thể suy luận gián tiếp qua chuỗi triplet
  Nếu chỉ thiếu (a) nhưng có (b), vẫn phải trả lời từ văn bản.

④ KHÔNG "VƠ VÀO" ĐỂ CHO ĐỦ
  Nếu chỉ tìm được 1–2 dự án có bằng chứng rõ ràng, hãy liệt kê đúng
  1–2. ĐỪNG cố thêm entity mơ hồ để câu trả lời trông "đầy đủ" hơn.
  Độ chính xác quan trọng hơn độ dài.

⑤ KHÔNG THÊM CÂU PHỦ NHẬN SAU KHI ĐÃ TRẢ LỜI
  Sai: "Anh Tưởng đã phát triển NovaFlow và EduSphere. Tuy nhiên, không
        có thông tin cụ thể về các dự án..."
  Đúng: "Anh Tưởng đã phát triển NovaFlow và EduSphere. Nếu cần thêm
         chi tiết về từng dự án, vui lòng cung cấp tài liệu bổ sung."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
QUY TẮC TRÌNH BÀY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

F1 — TRÍCH DẪN NGUỒN BẮT BUỘC
  Mỗi thông tin chính phải có nguồn dẫn ngay phía sau:
    • [VEC: <tên file>] cho thông tin từ văn bản gốc
    • [GRF: <subject> → <object>] cho thông tin từ triplet

F2 — CẤU TRÚC CÂU TRẢ LỜI RÕ RÀNG
  Câu trả lời nên theo cấu trúc:
    1. Trả lời trực tiếp câu hỏi (1–2 câu)
    2. Bằng chứng từ ngữ cảnh (triplets + văn bản)
    3. Ghi chú nếu thông tin chưa đầy đủ (nếu cần)
  KHÔNG bắt đầu câu trả lời bằng "Dựa trên ngữ cảnh được cung cấp..."

F3 — MỨC ĐỘ TỰ TIN RÕ RÀNG
  Dùng ngôn ngữ phân cấp để phản ánh độ chắc chắn:
    • Có triplet trực tiếp → "Anh X đã / có / là..."
    • Suy luận từ văn bản  → "Theo hồ sơ, có thể hiểu rằng..."
    • Không đủ bằng chứng  → "Hồ sơ hiện tại chưa ghi nhận thông tin về..."

F4 — NGÔN NGỮ
  Trả lời bằng tiếng Việt. Giữ tên riêng (tên người, tên dự án, tên công
  nghệ) đúng nguyên gốc, không dịch.
"""

_USER_PROMPT_TEMPLATE = """\
CÂU HỎI: {question}

━━━ NGỮ CẢNH TỪ NEO4J [VEC] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{vector_context}

━━━ QUAN HỆ TỪ NEO4J [GRF] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{graph_context}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Hãy trả lời theo 5 Nguyên tắc Suy luận và 4 Quy tắc Trình bày đã được mô tả.\
"""


def generate_response(
    user_query: str,
    vector_context: str,
    graph_context: str,
) -> str:
    """Tổng hợp câu trả lời bằng LLM (Cerebras primary → OpenAI fallback).

    Args:
        user_query: Câu hỏi gốc của người dùng.
        vector_context: Chuỗi [VEC] từ ``_format_vector_context()``.
        graph_context: Chuỗi [GRF] từ ``_format_graph_context()``.

    Returns:
        Câu trả lời tiếng Việt từ LLM.
    """
    user_message = _USER_PROMPT_TEMPLATE.format(
        question=user_query,
        vector_context=vector_context,
        graph_context=graph_context,
    )

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    # --- Primary: Cerebras ---
    try:
        logger.info("Gọi Cerebras (%s) …", settings.CEREBRAS_MODEL)
        client = Cerebras(api_key=settings.CEREBRAS_API_KEY)
        response = client.chat.completions.create(
            model=settings.CEREBRAS_MODEL,
            messages=messages,
            temperature=0.2,
        )
        answer = response.choices[0].message.content or ""
        logger.info("Cerebras trả lời (%d ký tự).", len(answer))
        return answer

    except Exception as exc:
        logger.warning("Cerebras lỗi: %s — fallback sang OpenAI.", exc)

    # --- Fallback: OpenAI ---
    try:
        logger.info("Gọi OpenAI (%s) …", settings.OPENAI_MODEL)
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=messages,
            temperature=0.2,
        )
        answer = response.choices[0].message.content or ""
        logger.info("OpenAI trả lời (%d ký tự).", len(answer))
        return answer

    except Exception as exc:
        logger.error("Cả Cerebras và OpenAI đều thất bại: %s", exc)
        return (
            "Xin lỗi, hệ thống không thể tạo câu trả lời vào lúc này. "
            "Vui lòng thử lại sau."
        )


# ============================================================================
# Orchestrator: Kết hợp tất cả
# ============================================================================


def ask(
    question: str,
    top_k: int = 5,
    neo4j_uri: str | None = None,
    neo4j_user: str | None = None,
    neo4j_password: str | None = None,
    model_name: str = "phobert_v2",
) -> Dict[str, Any]:
    """Pipeline truy vấn end-to-end: Embed → Retrieve → Format → Generate.

    Args:
        question: Câu hỏi tiếng Việt.
        top_k: Số chunk tương đồng nhất.
        model_name: Tên model embedding dùng cho vector search
            (quyết định index ``vector_index_{model_name}``).

    Returns:
        Dict chứa:
          - ``question``  : Câu hỏi gốc.
          - ``answer``    : Câu trả lời.
          - ``context``   : Formatted context string.
          - ``sources``   : Danh sách source_file.
          - ``num_chunks``: Số chunk truy xuất.
          - ``elapsed``   : Thời gian xử lý (giây).
    """
    t0 = time.perf_counter()

    # 1. Embed
    query_vector = embed_query(question)

    # 1.5. Query Decomposition — trích xuất Anchor Entities bằng LLM
    anchors = extract_potential_entities(question)

    # 2. Retrieve (Graph-First Anchor Traversal + Vector)
    with HybridRetriever(
        uri=neo4j_uri,
        user=neo4j_user,
        password=neo4j_password,
        top_k=top_k,
        model_name=model_name,
    ) as retriever:
        records = retriever.retrieve(query_vector, anchors=anchors)

    # 3. Format context (2 kênh riêng cho LLM + 1 kênh gộp cho UI)
    vector_context = _format_vector_context(records)
    graph_context = _format_graph_context(records)
    context = format_context(records)  # backward-compat cho UI / debug

    # 4. Generate (truyền 2 kênh riêng để LLM phân biệt VEC vs GRF)
    answer = generate_response(question, vector_context, graph_context)

    elapsed = time.perf_counter() - t0
    sources = list({r["source_file"] for r in records})

    logger.info("Hoàn tất truy vấn (%.1fs, %d chunks).", elapsed, len(records))

    return {
        "question": question,
        "answer": answer,
        "context": context,
        "records": records,
        "sources": sources,
        "num_chunks": len(records),
        "elapsed": round(elapsed, 2),
    }


# ============================================================================
# CLI
# ============================================================================


def main() -> None:
    """Entry-point: ``python -m pipeline.hybrid_query_engine "câu hỏi"``."""
    parser = argparse.ArgumentParser(
        description="Hybrid Query Engine — Transparent AI Digital Twin",
    )
    parser.add_argument(
        "question",
        help="Câu hỏi tiếng Việt cần truy vấn.",
    )
    parser.add_argument(
        "--top-k", "-k",
        type=int,
        default=5,
        help="Số chunk tương đồng nhất (mặc định: 5).",
    )
    parser.add_argument(
        "--model", "-m",
        default="phobert_v2",
        help=(
            "Tên model embedding cho vector search. "
            "Quyết định index vector_index_{model}. "
            "Ví dụ: phobert_v2, bge_m3, gte (mặc định: phobert_v2)."
        ),
    )
    args = parser.parse_args()

    result = ask(args.question, top_k=args.top_k, model_name=args.model)

    print("\n" + "=" * 70)
    print("CÂU HỎI:", result["question"])
    print("=" * 70)
    print("\n--- NGỮ CẢNH TRUY XUẤT ---\n")
    print(result["context"])
    print("\n--- CÂU TRẢ LỜI ---\n")
    print(result["answer"])
    print("\n" + "-" * 70)
    print(
        "Nguồn: %s | Chunks: %d | Thời gian: %.1fs"
        % (", ".join(result["sources"]), result["num_chunks"], result["elapsed"])
    )
    print("-" * 70)


if __name__ == "__main__":
    main()
