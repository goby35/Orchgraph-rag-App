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

# ── Project root on sys.path ─────────────────────────────────────────────────
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer

from pipeline.config import settings
from scripts.eval.utils import save_json, mean, std, print_table

# ── Constants ────────────────────────────────────────────────────────────────

JD_PATH = PROJECT_ROOT / "data_eval" / "jd_dataset.json"
CACHE_DIR = PROJECT_ROOT / "data_eval"

MODELS = {
    "phobert_base_v2": {"model_id": "vinai/phobert-base-v2", "dim": 768, "prefix": ""},
    "multilingual_e5": {"model_id": "intfloat/multilingual-e5-base", "dim": 768, "prefix": "query: "},
    "gte_multilingual": {"model_id": "Alibaba-NLP/gte-multilingual-base", "dim": 768, "prefix": ""},
    "bge_m3": {"model_id": "BAAI/bge-m3", "dim": 1024, "prefix": ""},
}

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
    MATCH (p:Personnel) WHERE p.public_embeddings_phobert IS NOT NULL
    RETURN p.id AS id,
           p.public_embeddings_phobert AS phobert_emb,
           coalesce(p.public_skills_flat, []) AS skills,
           coalesce(p.public_professional_summary, '') AS summary
    """
    records = []
    with driver.session() as session:
        result = session.run(query)
        for rec in result:
            records.append({
                "id": rec["id"],
                "phobert_emb": list(rec["phobert_emb"]),
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
    if model_name == "phobert_base_v2":
        return {r["id"]: r["phobert_emb"] for r in corpus_records}

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

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
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

    save_json(all_results, "embedding_eval.json")

    print(f"\n{'='*80}")
    print("EMBEDDING EVALUATION RESULTS")
    print(f"{'='*80}")
    print_table(
        table_rows,
        columns=["model", "mrr_at_5", "recall_at_5", "recall_at_10", "ndcg_at_5", "time_ms", "mem_mb"],
    )

if __name__ == "__main__":
    main()