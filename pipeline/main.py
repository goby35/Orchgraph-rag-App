import json
from pathlib import Path
from typing import Any, Dict, List
from tqdm import tqdm

from pipeline.config import settings, get_logger
from pipeline.parser import parse_to_markdown
from pipeline.cleaner import clean_vietnamese_text
from pipeline.extractor import extract_knowledge
from pipeline.vectorizer import prepare_for_neo4j
from pipeline.neo4j_ingestion import neo4j_service

logger = get_logger(__name__)


def _dual_ingest_supabase_non_fatal(payload: Dict[str, Any]) -> None:
    """Best-effort Supabase dual-ingestion after Neo4j ingest succeeds."""
    try:
        from pipeline.schemas import RecruitmentNode
        from pipeline.supabase_ingestion import ingest_to_supabase

        node = RecruitmentNode.from_pipeline_payload(payload)
        ingest_to_supabase(node)
    except Exception as sb_err:
        logger.warning("[Supabase] Dual-ingest warning (non-fatal): %s", sb_err)


def _chunk_text_for_extraction(text: str, max_chars: int = 7000, overlap: int = 400) -> List[str]:
    """Chia text lớn thành nhiều chunk để tránh vượt giới hạn context của LLM."""
    if not text or not text.strip():
        return []

    if len(text) <= max_chars:
        return [text]

    chunks: List[str] = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(start + max_chars, text_len)
        if end < text_len:
            # Ưu tiên ngắt theo xuống dòng để giữ nghĩa đoạn văn.
            split_at = text.rfind("\n", start, end)
            if split_at > start + int(max_chars * 0.6):
                end = split_at

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= text_len:
            break
        start = max(0, end - overlap)

    return chunks


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


def _normalize_list_item(item: Any) -> str:
    if isinstance(item, (dict, list)):
        return json.dumps(item, ensure_ascii=False, sort_keys=True)
    return str(item)


def _merge_list_values(target_list: List[Any], incoming: Any) -> None:
    if not isinstance(incoming, list):
        return

    seen = {_normalize_list_item(v) for v in target_list}
    for item in incoming:
        key = _normalize_list_item(item)
        if key in seen:
            continue
        target_list.append(item)
        seen.add(key)


def _merge_nested_dict(target: Dict[str, Any], incoming: Dict[str, Any]) -> None:
    for key, value in incoming.items():
        if isinstance(value, list):
            if not isinstance(target.get(key), list):
                target[key] = []
            _merge_list_values(target[key], value)
        elif isinstance(value, dict):
            if not isinstance(target.get(key), dict):
                target[key] = {}
            _merge_nested_dict(target[key], value)
        else:
            if not _has_value(target.get(key)) and _has_value(value):
                target[key] = value


def _empty_extraction_template(record_type: str) -> Dict[str, Any]:
    if record_type == "ORGANIZATION":
        return {
            "record_type": "ORGANIZATION",
            "data": {
                "org_id": None,
                "public_data": {
                    "org_name": None,
                    "industry": None,
                    "brief_description": None,
                    "active_jds": [],
                },
                "private_data": {
                    "core_techstack_detail": {},
                    "internal_project_pain_points": None,
                    "target_candidate_dna": None,
                    "client_list": [],
                },
            },
        }

    return {
        "record_type": "PERSONNEL",
        "data": {
            "personnel_id": None,
            "public_data": {
                "full_name": None,
                "professional_summary": None,
                "education": [],
                "certificates": [],
                "skills": [],
                "experience": [],
                "availability": None,
                "cultural_tags": [],
            },
            "private_data": {
                "contact": {},
                "salary_expectation": None,
                "project_technical_secrets": None,
                "interview_questions_history": [],
                "blacklist_orgs": [],
                "evidence_links": [],
                "additional_information": {},
            },
        },
    }


def _merge_extracted_chunks(chunks_data: List[Dict[str, Any]], default_record_type: str) -> Dict[str, Any]:
    """Map-Reduce merge cho extraction nhiều chunk để tránh mất dữ liệu."""
    merged = _empty_extraction_template(default_record_type)

    for chunk_dict in chunks_data:
        if not isinstance(chunk_dict, dict) or not chunk_dict:
            continue

        chunk_record_type = str(chunk_dict.get("record_type", "")).upper().strip()
        if chunk_record_type in {"PERSONNEL", "ORGANIZATION"}:
            merged["record_type"] = chunk_record_type

        data = chunk_dict.get("data")
        if not isinstance(data, dict):
            continue

        merged_data = merged.setdefault("data", {})

        # Merge định danh đơn trị: điền nếu chưa có
        for id_key in ("personnel_id", "org_id"):
            if not _has_value(merged_data.get(id_key)) and _has_value(data.get(id_key)):
                merged_data[id_key] = data.get(id_key)

        # Merge public/private data
        public_in = data.get("public_data")
        if isinstance(public_in, dict):
            if not isinstance(merged_data.get("public_data"), dict):
                merged_data["public_data"] = {}
            _merge_nested_dict(merged_data["public_data"], public_in)

        private_in = data.get("private_data")
        if isinstance(private_in, dict):
            if not isinstance(merged_data.get("private_data"), dict):
                merged_data["private_data"] = {}
            _merge_nested_dict(merged_data["private_data"], private_in)

    return merged

def process_file(file_path: Path, target_node_id: str | None = None, target_role: str | None = None):
    """
    Xử lý 1 file duy nhất. 
    Nếu là JSON thì xử lý direct ingestion.
    Nếu ko thì chạy parse, clean, extract như thường.
    """
    file_ext = file_path.suffix.lower()
    
    # 1. Bypass LLM cho file JSON để tiết kiệm chi phí
    if file_ext == '.json':
        logger.info(f"Phát hiện file JSON, bypass LLM cho file: {file_path.name}")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # data can be list or dict
            nodes = data if isinstance(data, list) else [data]
            for node in nodes:
                node["source_file"] = file_path.name
                if target_node_id:
                    node["node_id"] = target_node_id
                if target_role:
                    node["record_type"] = target_role
                
                # 2. Vectorization
                vectorized_data = prepare_for_neo4j(node)
                
                # 3. Neo4j Ingestion
                neo4j_service.ingest_node(
                    vectorized_data,
                    target_node_id=target_node_id,
                    target_role=target_role,
                )
                _dual_ingest_supabase_non_fatal(node)
                
            logger.info(f"✅ Đã phân tách Public/Private thành công cho file: {file_path.name}")    
            return
            
        except Exception as e:
            logger.error(f"Lỗi khi xử lý file JSON {file_path.name}: {e}")
            return
            
    # 2. Các file tài liệu (.docx, .pdf, .md, .txt) dùng Pydantic & Llama
    logger.info(f"Bắt đầu pipeline chuẩn cho file: {file_path.name}")
    try:
        # A. Parse
        raw_text = parse_to_markdown(file_path)

        # B. Clean
        clean_text = clean_vietnamese_text(raw_text)

        # C. Chunking + LLM Extraction
        # default là PERSONNEL, có thể cải tiến auto detect dựa trên keywords
        record_type = "PERSONNEL" if "JD" not in str(file_path.name).upper() else "ORGANIZATION"
        chunks = _chunk_text_for_extraction(clean_text)
        if not chunks:
            raise RuntimeError("Nội dung sau khi clean rỗng, không thể extract")

        logger.info("Tách %d chunk trước extract cho file: %s", len(chunks), file_path.name)
        extraction_candidates: List[Dict[str, Any]] = []
        for idx, chunk in enumerate(chunks):
            logger.info("Extract chunk %d/%d cho file: %s", idx + 1, len(chunks), file_path.name)
            extraction_candidates.append(
                extract_knowledge(
                    chunk,
                    file_hint=f"{file_path.name}#chunk{idx + 1}",
                    target_role=record_type,
                )
            )
        extraction_result = _merge_extracted_chunks(extraction_candidates, record_type)
        
        import uuid as _uuid

        # extraction_result đã là dict
        node_data = extraction_result
        node_data["source_file"] = file_path.name
        node_data["record_type"] = extraction_result.get("record_type", record_type)

        # Sinh ID tự động nếu LLM không tìm thấy
        data_block = node_data.get("data", {})
        if target_node_id:
            # User đã login và upload → dùng ID của họ
            if record_type == "ORGANIZATION":
                data_block["org_id"] = target_node_id
            else:
                data_block["personnel_id"] = target_node_id
        else:
            # PDF không có ID → sinh ngẫu nhiên
            if not data_block.get("personnel_id") and not data_block.get("org_id"):
                prefix = "ORG" if record_type == "ORGANIZATION" else "P"
                data_block[
                    "org_id" if record_type == "ORGANIZATION" else "personnel_id"
                ] = f"{prefix}_{_uuid.uuid4().hex[:8].upper()}"
                logger.info(
                    "[main] Sinh ID tự động: %s",
                    data_block.get("personnel_id") or data_block.get("org_id"),
                )
        
        # D. Vectorize
        vectorized_data = prepare_for_neo4j(node_data)
        
        # E. Neo4j Ingest 
        neo4j_service.ingest_node(
            vectorized_data,
            target_node_id=target_node_id,
            target_role=target_role,
        )
        _dual_ingest_supabase_non_fatal(node_data)
        
        logger.info(f"✅ Đã phân tách Public/Private thành công cho file: {file_path.name}")
        
    except Exception as e:
        logger.error(f"Lỗi quy trình cho file {file_path.name}: {e}")


def _resolve_record_type(role: str) -> str:
    role_norm = str(role or "").strip().lower()
    return "ORGANIZATION" if role_norm in {"organization", "org"} else "PERSONNEL"


def update_partial_info(node_id: str, role: str, compartment: str, field_name: str, new_value: Any):
    """Read -> Modify -> ReEmbed -> Write cho cập nhật partial field."""
    record_type = _resolve_record_type(role)
    label = "Organization" if record_type == "ORGANIZATION" else "Personnel"
    compartment_norm = str(compartment or "").strip().lower()
    if compartment_norm not in {"public", "public_data", "private", "private_data"}:
        raise ValueError("compartment phải là public_data hoặc private_data")

    try:
        with neo4j_service._driver.session() as session:
            node = session.run(
                """
                MATCH (n {id: $node_id})
                WHERE $label IN labels(n)
                RETURN properties(n) AS props
                LIMIT 1
                """,
                node_id=node_id,
                label=label,
            ).single()

        if not node:
            raise ValueError(f"Không tìm thấy node {label} với id={node_id}")

        props = dict(node.get("props") or {})

        public_data: Dict[str, Any] = {}
        for key, value in props.items():
            if not str(key).startswith("public_"):
                continue
            clean_key = str(key)[7:]
            parsed_value = value
            if isinstance(value, str):
                text = value.strip()
                if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
                    try:
                        parsed_value = json.loads(text)
                    except Exception:
                        parsed_value = value
            public_data[clean_key] = parsed_value

        private_blob = props.get("private_data_blob") or "{}"
        private_data = {}
        if isinstance(private_blob, str):
            try:
                private_data = json.loads(private_blob)
            except Exception:
                private_data = {}
        elif isinstance(private_blob, dict):
            private_data = dict(private_blob)

        if compartment_norm in {"public", "public_data"}:
            target_map = public_data
        else:
            target_map = private_data

        if new_value is None or (isinstance(new_value, str) and not new_value.strip()):
            target_map.pop(field_name, None)
        else:
            target_map[field_name] = new_value

        data: Dict[str, Any] = {
            "public_data": public_data,
            "private_data": private_data,
        }
        if record_type == "ORGANIZATION":
            data["org_id"] = node_id
        else:
            data["personnel_id"] = node_id

        node_data = {
            "record_type": record_type,
            "data": data,
            "source_file": props.get("source_file", "manual_update"),
        }

        vectorized_data = prepare_for_neo4j(node_data)
        neo4j_service.ingest_node(
            vectorized_data,
            target_node_id=node_id,
            target_role=record_type,
        )
    except Exception as e:
        logger.error("Lỗi update_partial_info cho %s (%s): %s", node_id, role, e, exc_info=True)
        raise


def delete_account(node_id: str, role: str, hard_delete: bool = False):
    """Xóa tài khoản: mặc định soft delete để bảo toàn quan hệ đồ thị."""
    record_type = _resolve_record_type(role)
    label = "Organization" if record_type == "ORGANIZATION" else "Personnel"

    try:
        with neo4j_service._driver.session() as session:
            if hard_delete:
                session.run(
                    """
                    MATCH (n {id: $node_id})
                    WHERE $label IN labels(n)
                    DETACH DELETE n
                    """,
                    node_id=node_id,
                    label=label,
                )
                return

            row = session.run(
                """
                MATCH (n {id: $node_id})
                WHERE $label IN labels(n)
                RETURN keys(n) AS keys
                LIMIT 1
                """,
                node_id=node_id,
                label=label,
            ).single()
            if not row:
                raise ValueError(f"Không tìm thấy node {label} với id={node_id}")

            prop_keys = [k for k in (row.get("keys") or []) if isinstance(k, str) and k.startswith("public_")]
            zero_vector = [0.0] * 768

            session.run(
                """
                MATCH (n {id: $node_id})
                WHERE $label IN labels(n)
                SET n.is_deleted = true,
                    n.private_data_blob = '{}',
                    n.public_name = 'Tài khoản đã bị xóa',
                    n.public_full_name = 'Tài khoản đã bị xóa',
                    n.public_embeddings_phobert = $zero_vector,
                    n.private_embeddings_phobert = $zero_vector,
                    n.last_updated = timestamp()
                FOREACH (k IN $public_keys | SET n[k] = null)
                """,
                node_id=node_id,
                label=label,
                zero_vector=zero_vector,
                public_keys=prop_keys,
            )
    except Exception as e:
        logger.error("Lỗi delete_account cho %s (%s): %s", node_id, role, e, exc_info=True)
        raise

def main():
    logger.info("Khởi động orchgraph-rag pipeline...")
    
    if not neo4j_service.verify_connection():
         return
    neo4j_service.setup_indices()

    input_folders = ["storage/cv", "storage/project", "storage/sop", "storage", "data_lake"]
    
    all_files = []
    # Test batch ready dir 
    ready_dir = Path("neo4j_ready/bge-m3")
    if ready_dir.exists():
        all_files.extend(list(ready_dir.glob("*.json")))

    # Fast-track JSON batch (raw public/private, chưa có embedding)
    fast_track_dir = Path("fast_track")
    if fast_track_dir.exists():
        all_files.extend(list(fast_track_dir.glob("*.json")))

    for folder in input_folders:
        folder_path = Path(folder)
        if folder_path.exists():
             for ext in ('*.pdf', '*.docx', '*.txt', '*.md', '*.json'):
                all_files.extend(list(folder_path.rglob(ext)))

    if not all_files:
        logger.info("Không tìm thấy file nào để xử lý.")
        return

    logger.info(f"Tìm thấy {len(all_files)} files. Bắt đầu ingest...")
    for idx, f in enumerate(tqdm(all_files, desc="Đang phân tích Node")):
         logger.info(f"[{idx+1}/{len(all_files)}] Xử lý: {f.name}")
         process_file(f)

    logger.info("Đã hoàn tất toàn bộ pipeline!")
    neo4j_service.close()

if __name__ == "__main__":
    main()
