"""
Neo4j Ingestion Module — Transparent AI Digital Twin.

Đọc các file JSON từ ``./neo4j_ready/{embedding_model}/`` và nạp vào Neo4j Database
theo kiến trúc **Flat-Graph** xoay quanh Node Chunk.
Hỗ trợ 3 loại tài liệu: CV, SOP, PROJECT.

Graph Schema::

    (Document)-[:HAS_CHUNK]->(Chunk)-[:MENTIONS]->(Entity)
    (Entity)-[:RELATED_TO {action: ...}]->(Entity)

Node Labels:
    - Document   — tài liệu gốc, có thêm label động theo topic_category
    - Chunk      — đoạn văn bản, chứa vector embedding
    - Entity     — thực thể (đa dạng type theo doc_type)

Upsert Mode:
    Chỉ nạp file JSON mới chưa có Document node trong graph.

Usage::

    python -m pipeline.neo4j_ingestion [--dir ./neo4j_ready] [--model phobert-v2]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from neo4j import GraphDatabase, Driver, Session, ManagedTransaction
from neo4j.exceptions import (
    ServiceUnavailable,
    AuthError,
    ClientError,
)

from pipeline.config import settings, get_logger

logger = get_logger("pipeline.neo4j_ingestion")

# Topic category → dynamic label trên Document node
_TOPIC_LABEL_MAP = {
    # CV
    "PERSONNEL": "Personnel",
    "EXPERIENCE": "Experience",
    "EDUCATION": "Education",
    "SKILL": "Skill",
    "ACHIEVEMENT": "Achievement",
    # SOP
    "PROCESS_FLOW": "ProcessFlow",
    "APPROVAL": "Approval",
    "CONDITION": "Condition",
    "TOOL_USAGE": "ToolUsage",
    "COMPLIANCE": "Compliance",
    # PROJECT
    "OBJECTIVE": "Objective",
    "PLANNING": "Planning",
    "EXECUTION": "Execution",
    "RISK": "Risk",
    "REPORTING": "Reporting",
    # Legacy
    "POLICY": "Policy",
    "PROJECT": "Project",
}


# ============================================================================
# Neo4jIngestor (OOP)
# ============================================================================


class Neo4jIngestor:
    """Nạp dữ liệu JSON pipeline vào Neo4j.

    Args:
        uri: Bolt URI (mặc định từ ``settings.NEO4J_URI``).
        user: Tên đăng nhập Neo4j.
        password: Mật khẩu Neo4j.
    """

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> None:
        self._uri = uri or settings.NEO4J_URI
        self._user = user or settings.NEO4J_USER
        self._password = password or settings.NEO4J_PASSWORD
        self._driver: Optional[Driver] = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Tạo kết nối tới Neo4j."""
        logger.info("Kết nối Neo4j tại %s …", self._uri)
        self._driver = GraphDatabase.driver(
            self._uri,
            auth=(self._user, self._password),
        )
        # Verify connectivity
        self._driver.verify_connectivity()
        logger.info("Kết nối Neo4j thành công.")

    def close(self) -> None:
        """Đóng kết nối."""
        if self._driver:
            self._driver.close()
            self._driver = None
            logger.info("Đã đóng kết nối Neo4j.")

    def __enter__(self) -> "Neo4jIngestor":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @property
    def driver(self) -> Driver:
        if self._driver is None:
            raise RuntimeError("Chưa kết nối Neo4j. Gọi connect() trước.")
        return self._driver

    # ------------------------------------------------------------------
    # YÊU CẦU 2: Constraints & Indexes
    # ------------------------------------------------------------------

    def setup_schema(
        self,
        embedding_dim: int = 768,
        model_name: str = "phobert_v2",
    ) -> None:
        """Khởi tạo constraints và indexes (chạy 1 lần, idempotent).

        Args:
            embedding_dim: Chiều vector embedding (mặc định 768 cho PhoBERT).
            model_name: Tên model dùng để tạo vector index động
                (ví dụ: ``phobert_v2`` → index ``vector_index_phobert_v2``,
                property ``embedding_phobert_v2``).
        """
        logger.info("Thiết lập schema (constraints + indexes) …")

        with self.driver.session() as session:
            # Unique constraint: Entity.name
            session.run(
                "CREATE CONSTRAINT entity_name_unique IF NOT EXISTS "
                "FOR (e:Entity) REQUIRE e.name IS UNIQUE"
            )
            logger.info("  ✓ Constraint: Entity.name UNIQUE")

            # Unique constraint: Chunk.chunk_id
            session.run(
                "CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS "
                "FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE"
            )
            logger.info("  ✓ Constraint: Chunk.chunk_id UNIQUE")

            # Unique constraint: Document.source_file
            session.run(
                "CREATE CONSTRAINT document_source_unique IF NOT EXISTS "
                "FOR (d:Document) REQUIRE d.source_file IS UNIQUE"
            )
            logger.info("  ✓ Constraint: Document.source_file UNIQUE")

            # Vector index on Chunk.embedding_{model_name}
            index_name = f"vector_index_{model_name}"
            prop_name = f"embedding_{model_name}"
            try:
                session.run(
                    f"CREATE VECTOR INDEX `{index_name}` IF NOT EXISTS "
                    f"FOR (c:Chunk) ON (c.`{prop_name}`) "
                    "OPTIONS {indexConfig: {"
                    " `vector.dimensions`: $dim,"
                    " `vector.similarity_function`: 'cosine'"
                    "}}",
                    dim=embedding_dim,
                )
                logger.info(
                    "  ✓ Vector Index: %s → c.%s (dim=%d, cosine)",
                    index_name,
                    prop_name,
                    embedding_dim,
                )
            except ClientError as exc:
                # Index đã tồn tại với config khác → log warning
                if "equivalent index already exists" in str(exc).lower():
                    logger.warning(
                        "  ⚠ Vector index đã tồn tại, bỏ qua: %s", exc
                    )
                else:
                    raise

        logger.info("Schema sẵn sàng.")

    # ------------------------------------------------------------------
    # YÊU CẦU 3–4: Ingestion Flow & Transaction Management
    # ------------------------------------------------------------------

    def ingest_directory(
        self,
        directory: str | Path,
        embedding_dim: int | None = None,
        model_name: str = "phobert_v2",
    ) -> Dict[str, Any]:
        """Nạp toàn bộ file JSON trong một thư mục vào Neo4j.

        Args:
            directory: Đường dẫn thư mục chứa file JSON.
            embedding_dim: Chiều vector (nếu None, tự động detect từ JSON).
            model_name: Tên model embedding — quyết định tên property
                ``embedding_{model_name}`` và vector index.

        Returns:
            Dict thống kê: files_processed, files_failed, chunks_total, …
        """
        directory = Path(directory).resolve()
        if not directory.is_dir():
            raise FileNotFoundError(f"Thư mục không tồn tại: {directory}")

        json_files = sorted(directory.glob("*.json"))
        if not json_files:
            logger.warning("Không tìm thấy file JSON trong %s.", directory)
            return {"files_processed": 0, "files_failed": 0, "chunks_total": 0}

        logger.info(
            "Bắt đầu nạp %d file JSON từ %s (model: %s) …",
            len(json_files),
            directory,
            model_name,
        )

        # Auto-detect embedding_dim từ file đầu tiên
        if embedding_dim is None:
            embedding_dim = self._detect_embedding_dim(json_files[0])
        self.setup_schema(embedding_dim=embedding_dim, model_name=model_name)

        stats = {"files_processed": 0, "files_failed": 0, "chunks_total": 0}
        t0 = time.perf_counter()

        for file_path in json_files:
            try:
                # Upsert: kiểm tra source_file đã nạp chưa
                source_name = self._peek_source_file(file_path)
                if source_name and self._document_exists(source_name):
                    # Document đã có → chỉ cần SET embedding mới (A/B testing)
                    n_chunks = self._ingest_file(file_path, model_name=model_name)
                    stats["files_processed"] += 1
                    stats["chunks_total"] += n_chunks
                    logger.info(
                        "  ✓ %s — SET embedding_%s on %d existing chunks.",
                        file_path.name,
                        model_name,
                        n_chunks,
                    )
                    continue

                n_chunks = self._ingest_file(file_path, model_name=model_name)
                stats["files_processed"] += 1
                stats["chunks_total"] += n_chunks
                logger.info(
                    "  ✓ %s — %d chunks nạp thành công.",
                    file_path.name,
                    n_chunks,
                )
            except (ServiceUnavailable, AuthError) as exc:
                logger.error("Mất kết nối Neo4j: %s", exc)
                raise
            except Exception as exc:
                stats["files_failed"] += 1
                logger.error("  ✗ Lỗi nạp %s: %s", file_path.name, exc)

        elapsed = time.perf_counter() - t0
        skipped = stats.get("files_skipped", 0)
        logger.info(
            "HOÀN TẤT: %d/%d file, %d chunks, %d skipped (%.1fs).",
            stats["files_processed"],
            stats["files_processed"] + stats["files_failed"],
            stats["chunks_total"],
            skipped,
            elapsed,
        )
        return stats

    def _peek_source_file(self, json_path: Path) -> str:
        """Đọc source_file từ chunk đầu tiên trong file JSON.

        Hỗ trợ cả 2 format: list thuần và ``{"metadata": ..., "chunks": [...]}``.
        """
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            chunks = data
            if isinstance(data, dict) and "chunks" in data:
                chunks = data["chunks"]
            if chunks and isinstance(chunks, list):
                return chunks[0].get("source_file", "")
        except Exception:
            pass
        return ""

    def _document_exists(self, source_file: str) -> bool:
        """Kiểm tra Document node đã tồn tại trong Neo4j."""
        with self.driver.session() as session:
            result = session.run(
                "MATCH (d:Document {source_file: $sf}) RETURN count(d) AS cnt",
                sf=source_file,
            )
            record = result.single()
            return record is not None and record["cnt"] > 0

    def _detect_embedding_dim(self, json_path: Path) -> int:
        """Đọc file JSON để xác định chiều vector embedding.

        Hỗ trợ cả 2 format: list thuần và ``{"metadata": ..., "chunks": [...]}``.
        """
        data = json.loads(json_path.read_text(encoding="utf-8"))
        if not data:
            return 768  # fallback

        # Unwrap metadata envelope nếu có
        if isinstance(data, dict):
            if "metadata" in data and "embedding_dim" in data["metadata"]:
                return int(data["metadata"]["embedding_dim"])
            chunks = data.get("chunks", [])
        else:
            chunks = data

        if not chunks:
            return 768

        first = chunks[0]
        if "embedding" in first and isinstance(first["embedding"], list):
            return len(first["embedding"])
        if "embedding_dim" in first:
            return int(first["embedding_dim"])
        return 768

    def _ingest_file(self, file_path: Path, model_name: str = "phobert_v2") -> int:
        """Nạp một file JSON vào Neo4j.

        Mỗi file được xử lý trong một transaction duy nhất.
        Hỗ trợ cả 2 format: list thuần và ``{"metadata": ..., "chunks": [...]}``.

        Args:
            file_path: Đường dẫn file JSON.
            model_name: Tên model → embedding lưu vào ``embedding_{model_name}``.

        Returns:
            Số chunk đã nạp thành công.
        """
        raw = json.loads(file_path.read_text(encoding="utf-8"))

        # Unwrap metadata envelope
        if isinstance(raw, dict) and "chunks" in raw:
            data: List[Dict[str, Any]] = raw["chunks"]
        elif isinstance(raw, list):
            data = raw
        else:
            logger.warning("Unrecognised JSON format: %s", file_path.name)
            return 0

        if not data:
            logger.warning("File rỗng: %s", file_path.name)
            return 0

        with self.driver.session() as session:
            result = session.execute_write(
                self._ingest_chunks_tx, data, model_name
            )
        return result

    @staticmethod
    def _ingest_chunks_tx(
        tx: ManagedTransaction,
        chunks: List[Dict[str, Any]],
        model_name: str = "phobert_v2",
    ) -> int:
        """Transaction function: nạp toàn bộ chunks của 1 file.

        Thực hiện 3 logic:
            1. Core Nodes (Document + Chunk + HAS_CHUNK) + embedding động
            2. Entities (Entity + MENTIONS)
            3. Triplets (RELATED_TO)

        Embedding được lưu vào thuộc tính ``embedding_{model_name}`` để hỗ
        trợ A/B testing nhiều model trên cùng một đồ thị.
        """
        count = 0
        emb_prop = f"embedding_{model_name}"

        for chunk in chunks:
            chunk_id = chunk["chunk_id"]
            source_file = chunk.get("source_file", "unknown")
            chunk_index = chunk.get("chunk_index", 0)
            original_text = chunk.get("original_clean_text", "")
            segmented_text = chunk.get("segmented_text", "")
            embedding = chunk.get("embedding")
            knowledge = chunk.get("extracted_knowledge", {})
            topic_category = knowledge.get("topic_category", "PROJECT")
            entities = knowledge.get("entities", [])
            triplets = knowledge.get("triplets", [])

            # Dynamic label cho Document
            doc_label = _TOPIC_LABEL_MAP.get(topic_category, "Project")

            # --- Logic 1: Core Nodes ---
            # MERGE Document (với dynamic label qua APOC hoặc Cypher thuần)
            tx.run(
                "MERGE (d:Document {source_file: $source_file}) "
                "ON CREATE SET d.created_at = datetime() "
                "WITH d "
                "CALL apoc.create.addLabels(d, [$label]) YIELD node "
                "RETURN node",
                source_file=source_file,
                label=doc_label,
            )

            # MERGE Chunk + gắn embedding vào property động
            if embedding and isinstance(embedding, list) and len(embedding) > 5:
                # Full embedding vector → lưu vào embedding_{model_name}
                tx.run(
                    "MERGE (c:Chunk {chunk_id: $chunk_id}) "
                    "SET c.original_clean_text = $text, "
                    "    c.segmented_text = $seg, "
                    "    c.chunk_index = $idx, "
                    "    c.source_file = $source, "
                    f"    c.`{emb_prop}` = $embedding "
                    "WITH c "
                    "MATCH (d:Document {source_file: $source}) "
                    "MERGE (d)-[:HAS_CHUNK]->(c)",
                    chunk_id=chunk_id,
                    text=original_text,
                    seg=segmented_text,
                    idx=chunk_index,
                    source=source_file,
                    embedding=embedding,
                )
            else:
                # Không có embedding hoặc chỉ là preview
                tx.run(
                    "MERGE (c:Chunk {chunk_id: $chunk_id}) "
                    "SET c.original_clean_text = $text, "
                    "    c.segmented_text = $seg, "
                    "    c.chunk_index = $idx, "
                    "    c.source_file = $source "
                    "WITH c "
                    "MATCH (d:Document {source_file: $source}) "
                    "MERGE (d)-[:HAS_CHUNK]->(c)",
                    chunk_id=chunk_id,
                    text=original_text,
                    seg=segmented_text,
                    idx=chunk_index,
                    source=source_file,
                )

            # --- Logic 2: Entities ---
            for entity in entities:
                ent_name = entity.get("name", "").strip()
                ent_type = entity.get("type", "UNKNOWN")
                if not ent_name:
                    continue

                tx.run(
                    "MERGE (e:Entity {name: $name}) "
                    "SET e.type = $type "
                    "WITH e "
                    "MATCH (c:Chunk {chunk_id: $chunk_id}) "
                    "MERGE (c)-[:MENTIONS]->(e)",
                    name=ent_name,
                    type=ent_type,
                    chunk_id=chunk_id,
                )

            # --- Logic 3: Triplets ---
            for triplet in triplets:
                subj = triplet.get("subject", "").strip()
                rel = triplet.get("relation", "").strip()
                obj = triplet.get("object", "").strip()
                if not subj or not obj:
                    continue

                tx.run(
                    "MERGE (s:Entity {name: $subject}) "
                    "MERGE (o:Entity {name: $object}) "
                    "MERGE (s)-[r:RELATED_TO]->(o) "
                    "SET r.action = $relation",
                    subject=subj,
                    object=obj,
                    relation=rel,
                )

            count += 1

        return count


# ============================================================================
# CLI
# ============================================================================


def main() -> None:
    """Entry-point: ``python -m pipeline.neo4j_ingestion``."""
    parser = argparse.ArgumentParser(
        description="Neo4j Ingestion — Transparent AI Digital Twin",
    )
    parser.add_argument(
        "--dir",
        default="./neo4j_ready",
        help="Thư mục gốc neo4j_ready (mặc định: ./neo4j_ready).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Tên thư mục model (vd: phobert-v2). Mặc định: nạp tất cả.",
    )
    parser.add_argument(
        "--model-name",
        default=None,
        help=(
            "Tên model dùng cho property động embedding_{model_name} và "
            "vector index. Nếu không chỉ định, tự suy từ --model "
            "(thay '-' bằng '_'). Ví dụ: phobert_v2, bge_m3, gte."
        ),
    )
    parser.add_argument(
        "--dim",
        type=int,
        default=None,
        help="Chiều vector embedding (mặc định: tự detect từ JSON).",
    )
    args = parser.parse_args()

    base_dir = Path(args.dir).resolve()
    if not base_dir.is_dir():
        logger.error("Thư mục không tồn tại: %s", base_dir)
        sys.exit(1)

    # Tìm các thư mục model cần nạp
    if args.model:
        model_dirs = [base_dir / args.model]
        if not model_dirs[0].is_dir():
            logger.error("Thư mục model không tồn tại: %s", model_dirs[0])
            sys.exit(1)
    else:
        model_dirs = sorted(
            d for d in base_dir.iterdir() if d.is_dir()
        )

    if not model_dirs:
        logger.error("Không tìm thấy thư mục model nào trong %s.", base_dir)
        sys.exit(1)

    try:
        with Neo4jIngestor() as ingestor:
            for model_dir in model_dirs:
                # Xác định model_name: CLI flag → tên thư mục (chuẩn hóa)
                if args.model_name:
                    m_name = args.model_name
                else:
                    m_name = model_dir.name.replace("-", "_")

                logger.info("═" * 50)
                logger.info(
                    "NẠP MODEL: %s → embedding_%s", model_dir.name, m_name
                )
                logger.info("═" * 50)
                ingestor.ingest_directory(
                    model_dir,
                    embedding_dim=args.dim,
                    model_name=m_name,
                )
    except ServiceUnavailable as exc:
        logger.error("Không thể kết nối Neo4j: %s", exc)
        sys.exit(1)
    except AuthError as exc:
        logger.error("Lỗi xác thực Neo4j: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
