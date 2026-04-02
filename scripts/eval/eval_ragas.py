"""
eval_ragas.py
─────────────────────────────────────────────────────────────────────────────
So sánh 3 chế độ truy vấn (RAG / GraphRAG / Hybrid) bằng RAGAS framework.
Tương thích: ragas >= 0.2  |  Python 3.12
─────────────────────────────────────────────────────────────────────────────
Chạy:  python scripts/eval/eval_ragas.py
"""

from __future__ import annotations

import json
import os
import sys
import warnings
from typing import Any
from neo4j.exceptions import ServiceUnavailable
import asyncio
import sys

# Fix event loop cho Windows + Python 3.12+
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ── Path bootstrap ────────────────────────────────────────────────────────────
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

# ── Suppress noisy warnings ───────────────────────────────────────────────────
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", module=".*pyvi.*")
warnings.filterwarnings("ignore", message=".*align should be passed.*")

# ── Ragas imports (v0.2+ API) ─────────────────────────────────────────────────
try:
    from datasets import Dataset
    from ragas import evaluate
    # v0.2+: metrics là CLASS, phải khởi tạo bằng ()
    from ragas.metrics import (
        Faithfulness,
        AnswerRelevancy,
        ContextPrecision,
        ContextRecall,
        AnswerCorrectness,
    )
    from ragas.llms import LangchainLLMWrapper
    from langchain_openai import ChatOpenAI
except ImportError as exc:
    print(f"Missing required packages: {exc}")
    print("pip install ragas>=0.2 langchain-openai datasets")
    sys.exit(1)

# ── Dotenv ────────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Pipeline imports ──────────────────────────────────────────────────────────
try:
    import pipeline.hybrid_query_engine as hqe
    from pipeline.hybrid_query_engine import DigitalTwinInterviewEngine
except ImportError as exc:
    print(f"Error: Could not import pipeline modules. Details: {exc}")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
QA_DATASET_PATH = "data_eval/qa_dataset.json"

CONFIGS = [
    {"name": "RAG",      "alpha": 0.0, "beta": 1.0},
    {"name": "GraphRAG", "alpha": 1.0, "beta": 0.0},
    {"name": "Hybrid",   "alpha": 0.2, "beta": 0.8},
]

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def save_json(data: Any, filepath: str) -> None:
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def safe_get(result: Any, key: str) -> float:
    try:
        # ragas >= 0.2: result là EvaluationResult, dùng .to_pandas() để extract
        import pandas as pd
        if hasattr(result, "to_pandas"):
            df = result.to_pandas()
            if key in df.columns:
                val = df[key].mean()
                return float(val) if pd.notna(val) else 0.0
        # fallback dict-style
        val = result[key]
        return float(val) if val is not None else 0.0
    except Exception as e:
        print(f"  [WARN] safe_get('{key}') failed: {e}")
        return 0.0


def build_metrics(eval_llm: Any) -> list[Any]:
    """
    Khởi tạo metrics dưới dạng OBJECTS (bắt buộc từ ragas >= 0.2).
    Mỗi metric nhận llm qua constructor để tránh lỗi 'no llm set'.
    """
    return [
        Faithfulness(llm=eval_llm),
        AnswerRelevancy(llm=eval_llm),
        ContextPrecision(llm=eval_llm),
        ContextRecall(llm=eval_llm),
        AnswerCorrectness(llm=eval_llm),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    # ── Tạo template nếu dataset chưa có ─────────────────────────────────────
    if not os.path.exists(QA_DATASET_PATH):
        os.makedirs(os.path.dirname(QA_DATASET_PATH) or ".", exist_ok=True)
        template = [
            {
                "question_id": f"q_{i + 1}",
                "target_personnel": ["sample_personnel_id"],
                "org_id": "sample_org_id",
                "question": "Sample interview question?",
                "ground_truth": "Expected ideal answer goes here.",
                "qa_type": "technical",
            }
            for i in range(3)
        ]
        save_json(template, QA_DATASET_PATH)
        print(f"Created template dataset at {QA_DATASET_PATH}")
        print("Please fill in the real QA pairs and run this script again.")
        sys.exit(0)

    with open(QA_DATASET_PATH, "r", encoding="utf-8") as f:
        qa_dataset: list[dict] = json.load(f)

    os.makedirs("results", exist_ok=True)

    # ── LLM judge ─────────────────────────────────────────────────────────────
    eval_llm = LangchainLLMWrapper(ChatOpenAI(model="gpt-4o-mini", temperature=0, n=1))

    final_eval_results: dict[str, dict[str, float]] = {}

    for config in CONFIGS:
        name  = config["name"]
        alpha = float(config["alpha"])
        beta  = float(config["beta"])

        cache_file = f"results/ragas_answers_{name}.json"

        # ── Load cache hoặc chạy engine ───────────────────────────────────────
        if os.path.exists(cache_file):
            print(f"[{name}] Loading cached answers from {cache_file}...")
            with open(cache_file, "r", encoding="utf-8") as f:
                results_cache: list[dict] = json.load(f)
        else:
            print(f"[{name}] Running engine queries (alpha={alpha}, beta={beta})...")
            results_cache = []

            orig_alpha = getattr(hqe, "_ALPHA_GRAPH", 0.4)
            orig_beta  = getattr(hqe, "_BETA_VECTOR", 0.6)

            engine = DigitalTwinInterviewEngine()
            try:
                hqe._ALPHA_GRAPH = alpha
                hqe._BETA_VECTOR = beta
                engine.connect()

                for item in qa_dataset:
                    org_id       = item.get("org_id", "default_org")
                    targets      = item.get("target_personnel", [])
                    if not targets:
                        continue
                    per_id       = targets[0]
                    question     = item.get("question", "")
                    ground_truth = item.get("ground_truth", "")

                    try:
                        response = engine.answer_interview(org_id, per_id, question)
                    except Exception as e:
                        print(f"  [WARN] answer_interview failed for {per_id}: {e}")
                        response = {"answer": "", "contexts": []}

                    results_cache.append({
                        "qa_id":        item.get("question_id", ""),
                        "question":     question,
                        "answer":       response.get("answer", ""),
                        "contexts":     response.get("contexts") or ["No context retrieved"],
                        "ground_truth": ground_truth,
                    })

            except ServiceUnavailable as e:
                print(f"[{name}] ⚠ Neo4j unavailable — skipping this config.")
                print(f"  Start Neo4j with: docker-compose up -d")
                print(f"  Then delete results/ragas_answers_{name}.json and re-run.")
                hqe._ALPHA_GRAPH = orig_alpha
                hqe._BETA_VECTOR = orig_beta
                continue   # skip to next config

            finally:
                engine.close()
                hqe._ALPHA_GRAPH = orig_alpha
                hqe._BETA_VECTOR = orig_beta

            save_json(results_cache, cache_file)

        # ── Bỏ qua config nếu cache rỗng ─────────────────────────────────────
        if not results_cache:
            print(f"[{name}] Không có dữ liệu để eval, bỏ qua.")
            continue

        # ── Build Ragas Dataset ───────────────────────────────────────────────
        data_dict = {
            "question":     [x["question"]     for x in results_cache],
            "answer":       [x["answer"]        for x in results_cache],
            # Fix: đảm bảo mỗi item là List[str], không phải str
            "contexts":     [
                x["contexts"] if isinstance(x["contexts"], list) else [x["contexts"]]
                for x in results_cache
            ],
            "ground_truth": [x["ground_truth"]  for x in results_cache],
        }
        dataset = Dataset.from_dict(data_dict)

        # ── Evaluate ─────────────────────────────────────────────────────────
        print(f"[{name}] Evaluating with RAGAS (ragas >= 0.2 API)...")

        # Khởi tạo metric objects mới cho mỗi config (tránh state leak)
        metrics = build_metrics(eval_llm)

        result = evaluate(dataset, metrics=metrics)  # type: ignore[arg-type]

        final_eval_results[name] = {
            "faithfulness":       safe_get(result, "faithfulness"),
            "answer_relevancy":   safe_get(result, "answer_relevancy"),
            "context_precision":  safe_get(result, "context_precision"),
            "context_recall":     safe_get(result, "context_recall"),
            "answer_correctness": safe_get(result, "answer_correctness"),
        }

    # ── Lưu kết quả tổng hợp ─────────────────────────────────────────────────
    os.makedirs("results", exist_ok=True)
    save_json(final_eval_results, "results/ragas_eval.json")

    # ── In bảng so sánh ───────────────────────────────────────────────────────
    print("\n" + "=" * 75)
    row_fmt = "{:<25} | {:<12} | {:<12} | {:<12}"
    print(row_fmt.format("Metric", "RAG", "GraphRAG", "Hybrid"))
    print("-" * 75)

    metric_keys = [
        "faithfulness",
        "answer_relevancy",
        "context_precision",
        "context_recall",
        "answer_correctness",
    ]
    for m in metric_keys:
        vals = [
            f"{final_eval_results.get(cfg, {}).get(m, 0.0):.4f}"
            for cfg in ("RAG", "GraphRAG", "Hybrid")
        ]
        print(row_fmt.format(m, *vals))

    print("=" * 75)
    print("Evaluation complete. Results saved to ragas_eval.json")


if __name__ == "__main__":
    main()