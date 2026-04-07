"""
Evaluate multiple embedding models for Vietnamese CV/JD retrieval.
Compares PhoBERT (stored), multilingual-e5, gte-multilingual, bge-m3.
"""

import sys
import pathlib
import json
import time
import tracemalloc
import math
import warnings
import argparse
import re

# ── Project root on sys.path ─────────────────────────────────────────────────
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer

from pipeline.config import settings
from pipeline.supabase_client import get_supabase
from pipeline.supabase_ingestion import _neo4j_id_to_uuid
from scripts.eval.utils import save_json, mean, std, print_table

# ── Constants ────────────────────────────────────────────────────────────────

JD_PATH = PROJECT_ROOT / "data_eval" / "jd_dataset.json"
QA_PATH = PROJECT_ROOT / "data_eval" / "qa_dataset.json"
CACHE_DIR = PROJECT_ROOT / "data_eval"
TASK_B_TOP_K = 5

MODELS = {
    "phobert_base_v2": {"model_id": "vinai/phobert-base-v2", "dim": 768, "prefix": "", "rpc_dim": 768},
    "multilingual_e5": {"model_id": "intfloat/multilingual-e5-base", "dim": 768, "prefix": "query: ", "rpc_dim": 768},
    "gte_multilingual": {"model_id": "Alibaba-NLP/gte-multilingual-base", "dim": 768, "prefix": "", "rpc_dim": 768},
    "bge_m3": {"model_id": "BAAI/bge-m3", "dim": 1024, "prefix": "", "rpc_dim": 768},
}

COLUMN_MAP = {
    "phobert_base_v2": "embedding_phobert",
    "multilingual_e5": "embedding_e5",
    "gte_multilingual": "embedding_gte",
    "bge_m3": "embedding_bge",
}

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_st_model(model_id: str):
    """Load SentenceTransformer an toàn, tự động set max_seq_length cho PhoBERT"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = SentenceTransformer(model_id, trust_remote_code=True)
        if "phobert" in model_id.lower():
            model.max_seq_length = 256  # Cứu cánh chống lỗi IndexError
        return model

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

def _rank_corpus(query_emb: list[float], corpus: dict[str, list[float]]) -> list[str]:
    scored = [(pid, _cosine_similarity(query_emb, emb)) for pid, emb in corpus.items()]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [pid for pid, _ in scored]


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(float(v)) for v in values) + "]"


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").lower().strip().split())


def _extract_relevant_ids(qa_row: dict) -> list[str]:
    raw_ids = qa_row.get("relevant_chunk_ids")
    if not isinstance(raw_ids, list):
        return []
    cleaned = [str(chunk_id).strip() for chunk_id in raw_ids if str(chunk_id).strip()]
    return [chunk_id for chunk_id in cleaned if UUID_RE.match(chunk_id)]


def _extract_relevant_chunks(qa_row: dict) -> list[str]:
    chunks = qa_row.get("relevant_chunks")
    if isinstance(chunks, list):
        cleaned = [str(c).strip() for c in chunks if str(c).strip()]
        if cleaned:
            return cleaned

    ground_truth = str(qa_row.get("ground_truth") or "").strip()
    if not ground_truth:
        return []
    return [s.strip() for s in ground_truth.split(".") if s.strip()]


def _count_chunk_matches(
    relevant_chunks: list[str],
    retrieved_chunks: list[str],
    model_cfg: dict,
    st_model: SentenceTransformer | None,
    similarity_threshold: float = 0.6,
) -> tuple[int, int]:
    if not relevant_chunks or not retrieved_chunks:
        return 0, 0

    normalized_relevant = [_normalize_text(c) for c in relevant_chunks if _normalize_text(c)]
    normalized_retrieved = [_normalize_text(c) for c in retrieved_chunks if _normalize_text(c)]

    matched_relevant_indices = set()
    matched_retrieved_indices = set()

    # First pass: lexical containment for exact/near-exact chunk overlap.
    for r_idx, rel in enumerate(normalized_relevant):
        for t_idx, got in enumerate(normalized_retrieved):
            if rel in got or got in rel:
                matched_relevant_indices.add(r_idx)
                matched_retrieved_indices.add(t_idx)

    # Second pass: semantic overlap to handle paraphrased or reformatted chunks.
    if st_model is not None and (len(matched_relevant_indices) < len(normalized_relevant) or len(matched_retrieved_indices) < len(normalized_retrieved)):
        prefix = model_cfg.get("prefix", "")
        try:
            rel_embs = st_model.encode([prefix + text for text in normalized_relevant], convert_to_numpy=True)
            ret_embs = st_model.encode([prefix + text for text in normalized_retrieved], convert_to_numpy=True)

            for r_idx, rel_emb in enumerate(rel_embs):
                best = max((_cosine_similarity(rel_emb.tolist(), ret_emb.tolist()) for ret_emb in ret_embs), default=0.0)
                if best >= similarity_threshold:
                    matched_relevant_indices.add(r_idx)

            for t_idx, ret_emb in enumerate(ret_embs):
                best = max((_cosine_similarity(ret_emb.tolist(), rel_emb.tolist()) for rel_emb in rel_embs), default=0.0)
                if best >= similarity_threshold:
                    matched_retrieved_indices.add(t_idx)
        except Exception:
            pass

    return len(matched_retrieved_indices), len(matched_relevant_indices)


def _search_top_k_chunks_supabase(
    model_name: str,
    query_emb: list[float],
    personnel_neo4j_id: str,
    top_k: int,
    embedding_col: str | None = None,
) -> list[dict]:
    embedding_col = embedding_col or COLUMN_MAP.get(model_name)

    target_user_id = _neo4j_id_to_uuid(personnel_neo4j_id)
    sb = get_supabase().schema("vdme")

    # Keep query dimension aligned with RPC vector column expectation.
    rpc_dim = int(MODELS.get(model_name, {}).get("rpc_dim") or len(query_emb))
    if len(query_emb) > rpc_dim:
        query_emb = query_emb[:rpc_dim]

    base_params = {
        "query_embedding": _vector_literal(query_emb),
        "target_user_id": target_user_id,
        "match_count": top_k,
        "embedding_col": embedding_col,
    }

    last_error = None
    if not embedding_col:
        print(f"  [WARN] No embedding column mapping for model {model_name}")
        return []

    rows: list[dict] = []
    for rpc_name in ("match_private_chunks_dynamic", "match_public_chunks_dynamic"):
        try:
            raw = sb.rpc(rpc_name, base_params).execute().data
            if not isinstance(raw, list):
                continue
            for row in raw:
                if not isinstance(row, dict):
                    continue
                row_id = str(row.get("id") or "").strip()
                content = str(row.get("content") or "").strip()
                similarity = row.get("similarity")
                if not row_id or not content:
                    continue
                try:
                    if isinstance(similarity, (int, float, str)):
                        sim = float(similarity)
                    else:
                        sim = 0.0
                except (TypeError, ValueError):
                    sim = 0.0
                rows.append({"id": row_id, "content": content, "similarity": sim})
        except Exception as exc:
            last_error = exc

    if rows:
        rows.sort(key=lambda r: float(r.get("similarity") or 0.0), reverse=True)
        unique_rows: list[dict] = []
        seen_ids: set[str] = set()
        for row in rows:
            row_id = str(row.get("id") or "")
            if row_id in seen_ids:
                continue
            seen_ids.add(row_id)
            unique_rows.append({"id": row_id, "content": str(row.get("content") or "")})
            if len(unique_rows) >= top_k:
                break
        return unique_rows

    if last_error:
        print(f"  [WARN] Supabase RPC failed for {model_name}/{personnel_neo4j_id}: {last_error}")
    return []


def _compute_id_metrics(
    retrieved: list[dict],
    relevant_ids: list[str],
    k: int = 5,
) -> dict:
    """Precision@k and recall based on chunk IDs without semantic matching bias."""
    if not relevant_ids:
        return {
            "precision": None,
            "recall": None,
            "mrr": None,
            "hit_at_1": None,
            "note": "no_ground_truth",
        }

    top_k = [
        str(row.get("id"))
        for row in retrieved[:k]
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    ]
    rel_set = set(relevant_ids)
    tp = len(set(top_k) & rel_set)

    rr = 0.0
    for rank, chunk_id in enumerate(top_k, start=1):
        if chunk_id in rel_set:
            rr = 1.0 / rank
            break

    hit_at_1 = 1.0 if top_k and top_k[0] in rel_set else 0.0

    return {
        "precision": round(tp / k, 4) if k > 0 else 0.0,
        "recall": round(tp / len(rel_set), 4),
        "mrr": round(rr, 4),
        "hit_at_1": hit_at_1,
        "tp": tp,
        "k": k,
        "n_relevant": len(rel_set),
        "note": "ok",
    }

# ── Metrics ──────────────────────────────────────────────────────────────────

def mrr_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    for i, pid in enumerate(ranked[:k]):
        if pid in relevant:
            return 1.0 / (i + 1)
    return 0.0

def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    retrieved = set(ranked[:k])
    return len(retrieved & relevant) / len(relevant)

def ndcg_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    dcg = 0.0
    for i, pid in enumerate(ranked[:k]):
        if pid in relevant:
            dcg += 1.0 / math.log2(i + 2)
    ideal_count = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_count))
    if idcg == 0:
        return 0.0
    return dcg / idcg

# ── Neo4j corpus loader ─────────────────────────────────────────────────────

def _load_corpus_from_neo4j() -> list[dict]:
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )
    query = """
    MATCH (p:Personnel) WHERE p.id IS NOT NULL
    RETURN p.id AS id,
           p.public_embeddings_phobert AS phobert_emb,
           p.public_embeddings_multilingual_e5 AS e5_emb,
           p.public_embeddings_gte_multilingual AS gte_emb,
           p.public_embeddings_bge_m3 AS bge_emb,
           coalesce(p.public_skills_flat, []) AS skills,
           coalesce(p.public_professional_summary, '') AS summary
    """
    records = []
    with driver.session() as session:
        result = session.run(query)
        for rec in result:
            records.append({
                "id": rec["id"],
                "phobert_base_v2": list(rec["phobert_emb"]) if rec["phobert_emb"] else None,
                "multilingual_e5": list(rec["e5_emb"]) if rec["e5_emb"] else None,
                "gte_multilingual": list(rec["gte_emb"]) if rec["gte_emb"] else None,
                "bge_m3": list(rec["bge_emb"]) if rec["bge_emb"] else None,
                "skills": list(rec["skills"]) if rec["skills"] else [],
                "summary": rec["summary"] or "",
            })
    driver.close()
    print(f"Loaded {len(records)} personnel records from Neo4j.")
    return records

# ── Corpus embedding builder ────────────────────────────────────────────────

def _build_corpus_text(record: dict) -> str:
    return " ".join(record["skills"]) + " " + record["summary"]

def _get_corpus_embeddings(model_name: str, model_cfg: dict, corpus_records: list[dict]) -> dict[str, list[float]]:
    precalculated = {}
    missing_any = False
    for r in corpus_records:
        if r.get(model_name):
            precalculated[r["id"]] = r[model_name]
        else:
            missing_any = True
            
    if not missing_any and len(precalculated) > 0:
        print(f"  Loaded precalculated Neo4j vectors for {model_name}")
        return precalculated

    cache_file = CACHE_DIR / f"emb_cache_{model_name}.json"
    if cache_file.exists():
        print(f"  Loading cached corpus embeddings from {cache_file.name}")
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    print(f"  Encoding corpus with {model_cfg['model_id']}...")
    st_model = _load_st_model(model_cfg["model_id"])
    prefix = model_cfg["prefix"]

    texts = [prefix + _build_corpus_text(r) for r in corpus_records]
    embeddings = st_model.encode(texts, show_progress_bar=True, convert_to_numpy=True)

    result = {corpus_records[i]["id"]: embeddings[i].tolist() for i in range(len(corpus_records))}

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    print(f"  Cached to {cache_file.name}")

    return result

# ── Query encoding ───────────────────────────────────────────────────────────

def _encode_query(model_name: str, model_cfg: dict, text: str, st_model=None):
    prefix = model_cfg["prefix"]
    if st_model is None:
        st_model = _load_st_model(model_cfg["model_id"])
    emb = st_model.encode([prefix + text], convert_to_numpy=True)
    return emb[0].tolist(), st_model

# ── Efficiency benchmark ────────────────────────────────────────────────────

def _benchmark_efficiency(model_name: str, model_cfg: dict, sample_texts: list[str]):
    st_model = _load_st_model(model_cfg["model_id"])
    prefix = model_cfg["prefix"]
    texts = [prefix + t for t in sample_texts[:20]]

    times = []
    tracemalloc.start()

    for t in texts:
        start = time.perf_counter()
        st_model.encode([t], convert_to_numpy=True)
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)

    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return mean(times), std(times), peak / (1024 * 1024)


def eval_task_b(model_name: str, model_cfg: dict, qa_pairs: list[dict], top_k: int = TASK_B_TOP_K) -> dict:
    context_precision_list: list[float] = []
    context_recall_list: list[float] = []
    mrr_scores: list[float] = []
    hit_at_1_list: list[float] = []
    query_time_ms: list[float] = []

    st_model = None
    valid_queries = 0
    skipped_no_ground_truth = 0
    skipped_pending = 0

    for qa in qa_pairs:
        question = str(qa.get("question") or "").strip()
        targets = qa.get("targets") or []
        target_personnel = str(targets[0]).strip() if targets else ""
        chunk_source = str(qa.get("chunk_source") or "").strip().lower()
        relevant_ids = _extract_relevant_ids(qa)

        if chunk_source == "pending":
            qa_id = str(qa.get("qa_id") or "unknown")
            print(f"  [WARN] Skip {qa_id}: chunk_source=pending")
            skipped_pending += 1
            continue

        if chunk_source in {"not_found", "skipped"} or not relevant_ids:
            skipped_no_ground_truth += 1
            continue

        if not question or not target_personnel:
            continue

        q_emb, st_model = _encode_query(model_name, model_cfg, question, st_model)

        rpc_dim = int(model_cfg.get("rpc_dim") or len(q_emb))
        if len(q_emb) > rpc_dim:
            q_emb = q_emb[:rpc_dim]

        start = time.perf_counter()
        retrieved_rows = _search_top_k_chunks_supabase(
            model_name=model_name,
            query_emb=q_emb,
            personnel_neo4j_id=target_personnel,
            top_k=top_k,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        metrics = _compute_id_metrics(retrieved_rows, relevant_ids, k=top_k)
        if metrics.get("note") != "ok":
            skipped_no_ground_truth += 1
            continue
        context_precision = float(metrics.get("precision") or 0.0)
        context_recall = float(metrics.get("recall") or 0.0)
        mrr = float(metrics.get("mrr") or 0.0)
        hit_at_1 = float(metrics.get("hit_at_1") or 0.0)

        context_precision_list.append(context_precision)
        context_recall_list.append(context_recall)
        mrr_scores.append(mrr)
        hit_at_1_list.append(hit_at_1)
        query_time_ms.append(elapsed_ms)
        valid_queries += 1

    if valid_queries == 0:
        return {
            "context_precision": 0.0,
            "context_recall": 0.0,
            "mrr": 0.0,
            "hit_at_1": 0.0,
            "avg_query_time_ms": 0.0,
            "n_evaluated": 0,
            "queries_skipped_no_ground_truth": skipped_no_ground_truth,
            "queries_skipped_pending": skipped_pending,
        }

    return {
        "context_precision": round(mean(context_precision_list), 4),
        "context_recall": round(mean(context_recall_list), 4),
        "mrr": round(mean(mrr_scores), 4),
        "hit_at_1": round(mean(hit_at_1_list), 4),
        "avg_query_time_ms": round(mean(query_time_ms), 2),
        "n_evaluated": valid_queries,
        "queries_skipped_no_ground_truth": skipped_no_ground_truth,
        "queries_skipped_pending": skipped_pending,
    }

# ── Main ─────────────────────────────────────────────────────────────────────

def run_task_a() -> None:
    if not JD_PATH.exists():
        print(f"JD dataset not found at {JD_PATH}. Please provide the file.")
        sys.exit(1)

    with open(JD_PATH, "r", encoding="utf-8") as f:
        jd_queries = json.load(f)
    print(f"Loaded {len(jd_queries)} JD queries.")

    corpus_records = _load_corpus_from_neo4j()
    if not corpus_records:
        print("No personnel records found in Neo4j. Exiting.")
        sys.exit(1)

    sample_texts = [_build_corpus_text(r) for r in corpus_records[:20]]

    all_results = {}
    table_rows = []

    for model_name, model_cfg in MODELS.items():
        print(f"\n{'='*60}")
        print(f"Evaluating: {model_name} ({model_cfg['model_id']})")
        print(f"{'='*60}")

        corpus_embs = _get_corpus_embeddings(model_name, model_cfg, corpus_records)

        mrr5_list, recall5_list, recall10_list, ndcg5_list = [], [], [], []
        st_model = None

        valid_jd_count = 0

        for jd in jd_queries:
            if "jd_text" in jd:
                query_text = jd["jd_text"]
            else:
                input_data = jd.get("input_data", {})
                job_title = input_data.get("job_title", "")
                skills = " ".join(input_data.get("must_have_skills", []))
                desc = input_data.get("job_description", "")
                query_text = f"{job_title}\n{skills}\n{desc}"
                
            # Lấy đáp án từ object ground_truth
            ground_truth_obj = jd.get("ground_truth", {})
            relevant_list = ground_truth_obj.get("relevant_personnel", [])
            
            # Fallback nếu xài mấy format cũ
            if not relevant_list:
                relevant_list = jd.get("relevant_personnel_ids", jd.get("target_personnel", []))
                
            relevant = set(relevant_list)

            if not relevant:
                # Chỉ in cảnh báo ở model đầu tiên cho đỡ rác màn hình
                if model_name == "phobert_base_v2":
                    print(f"⚠️ Cảnh báo: Query {jd.get('query_id', 'unknown')} không có đáp án. Bỏ qua.")
                continue
            
            valid_jd_count += 1
            q_emb, st_model = _encode_query(model_name, model_cfg, query_text, st_model)
            ranked = _rank_corpus(q_emb, corpus_embs)

            mrr5_list.append(mrr_at_k(ranked, relevant, 5))
            recall5_list.append(recall_at_k(ranked, relevant, 5))
            recall10_list.append(recall_at_k(ranked, relevant, 10))
            ndcg5_list.append(ndcg_at_k(ranked, relevant, 5))

        if valid_jd_count == 0:
            print("❌ LỖI: Không có JD nào có đáp án hợp lệ! Vui lòng cập nhật file JD.")
            sys.exit(1)

        print(f"  Benchmarking efficiency...")
        avg_ms, std_ms, peak_mb = _benchmark_efficiency(model_name, model_cfg, sample_texts)

        model_result = {
            "mrr_at_5": round(mean(mrr5_list), 4) if mrr5_list else 0,
            "recall_at_5": round(mean(recall5_list), 4) if recall5_list else 0,
            "recall_at_10": round(mean(recall10_list), 4) if recall10_list else 0,
            "ndcg_at_5": round(mean(ndcg5_list), 4) if ndcg5_list else 0,
            "avg_time_ms": round(avg_ms, 2),
            "std_time_ms": round(std_ms, 2),
            "peak_memory_mb": round(peak_mb, 2),
        }
        all_results[model_name] = model_result

        table_rows.append({
            "model": model_name,
            "mrr_at_5": model_result["mrr_at_5"],
            "recall_at_5": model_result["recall_at_5"],
            "recall_at_10": model_result["recall_at_10"],
            "ndcg_at_5": model_result["ndcg_at_5"],
            "time_ms": f"{model_result['avg_time_ms']}±{model_result['std_time_ms']}",
            "mem_mb": model_result["peak_memory_mb"],
        })

    output_path = save_json(all_results, "embedding_eval_updated.json")

    print(f"\n{'='*80}")
    print("EMBEDDING EVALUATION RESULTS")
    print(f"{'='*80}")
    print_table(
        table_rows,
        columns=["model", "mrr_at_5", "recall_at_5", "recall_at_10", "ndcg_at_5", "time_ms", "mem_mb"],
    )
    print(f"\nSaved results to: {output_path}")


def run_task_b(top_k: int = TASK_B_TOP_K) -> None:
    if not QA_PATH.exists():
        print(f"QA dataset not found at {QA_PATH}. Please provide the file.")
        sys.exit(1)

    with open(QA_PATH, "r", encoding="utf-8") as f:
        qa_pairs = json.load(f)

    print(f"Loaded {len(qa_pairs)} QA pairs for Task B.")

    all_results: dict[str, dict] = {}
    table_rows: list[dict[str, str | float]] = []

    for model_name, model_cfg in MODELS.items():
        print(f"\n{'='*60}")
        print(f"Task B evaluating: {model_name} ({model_cfg['model_id']})")
        print(f"{'='*60}")

        result = eval_task_b(model_name, model_cfg, qa_pairs, top_k=top_k)
        all_results[model_name] = result

        table_rows.append({
            "Model": model_name,
            "Precision@5": result["context_precision"],
            "Context Recall": result["context_recall"],
            "MRR": result["mrr"],
            "Hit@1": result["hit_at_1"],
            "Avg Query Time (ms)": result["avg_query_time_ms"],
        })

    output_path = save_json(all_results, "embedding_eval_taskB_v2.json")

    print(f"\n{'='*80}")
    print("TASK B EMBEDDING EVALUATION RESULTS")
    print(f"{'='*80}")
    print_table(
        table_rows,
        columns=["Model", "Precision@5", "Context Recall", "MRR", "Hit@1", "Avg Query Time (ms)"],
    )
    print(f"\nSaved results to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate embedding models for Task A (JD retrieval) and Task B (chunk retrieval).")
    parser.add_argument(
        "--task",
        choices=["a", "b", "both"],
        default="both",
        help="Choose evaluation task: a=JD retrieval, b=Digital Twin chunk retrieval, both=run both tasks.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=TASK_B_TOP_K,
        help="Top-k chunks for Task B context metrics.",
    )
    args = parser.parse_args()

    if args.task in ("a", "both"):
        run_task_a()

    if args.task in ("b", "both"):
        run_task_b(top_k=args.top_k)

if __name__ == "__main__":
    main()