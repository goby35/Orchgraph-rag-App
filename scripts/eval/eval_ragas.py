"""Run RAGAS evaluation for retrieval-ablation configs on qa_dataset.

Usage:
    python -m scripts.eval.eval_ragas
    python -m scripts.eval.eval_ragas --dataset data_eval/qa_dataset.json --top-k 3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from neo4j.exceptions import ServiceUnavailable

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
DEFAULT_DATASET_PATH = "data_eval/qa_dataset.json"


class GraphMode(str, Enum):
    NONE = "none"
    JACCARD_ONLY = "jaccard_only"
    ENHANCED = "enhanced"


@dataclass(frozen=True)
class RetrievalConfig:
    name: str
    alpha: float
    beta: float
    graph_mode: GraphMode


RETRIEVAL_CONFIGS: list[RetrievalConfig] = [
    RetrievalConfig(name="RAG", alpha=0.0, beta=1.0, graph_mode=GraphMode.NONE),
    RetrievalConfig(name="GraphRAG", alpha=1.0, beta=0.0, graph_mode=GraphMode.JACCARD_ONLY),
    RetrievalConfig(name="Hybrid", alpha=0.4, beta=0.6, graph_mode=GraphMode.JACCARD_ONLY),
    RetrievalConfig(name="HybridPlus", alpha=0.4, beta=0.6, graph_mode=GraphMode.ENHANCED),
]

OUTPUT_FILES = {
    "RAG": "results/ragas_RAG.json",
    "GraphRAG": "results/ragas_GraphRAG.json",
    "Hybrid": "results/ragas_Hybrid.json",
    "HybridPlus": "results/ragas_HybridPlus.json",
}

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
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=DEFAULT_DATASET_PATH)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--force-rerun", action="store_true")
    parser.add_argument(
        "--debug-context",
        action="store_true",
        help="Include retrieval debug fields (raw_count/selected_count/raw_preview) in eval cache rows.",
    )
    args = parser.parse_args()

    dataset_path = args.dataset

    if not os.path.exists(dataset_path):
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    with open(dataset_path, "r", encoding="utf-8-sig") as f:
        eval_dataset: list[dict] = json.load(f)

    os.makedirs("results", exist_ok=True)

    # ── LLM judge ─────────────────────────────────────────────────────────────
    eval_llm = LangchainLLMWrapper(ChatOpenAI(model="gpt-4o-mini", temperature=0, n=1))

    final_eval_results: dict[str, dict[str, float]] = {}
    runtime_seconds_by_config: dict[str, float] = {}

    for idx, config in enumerate(RETRIEVAL_CONFIGS, start=1):
        name = config.name
        cache_file = f"results/ragas_answers_{name}.json"

        print(
            f"\n[{idx}/{len(RETRIEVAL_CONFIGS)}] {name} | "
            f"alpha={config.alpha}, beta={config.beta}, graph_mode={config.graph_mode.value}"
        )

        started_at = time.perf_counter()
        results_cache: list[dict]

        if os.path.exists(cache_file) and not args.force_rerun:
            print(f"[{name}] Loading cached answers from {cache_file}...")
            with open(cache_file, "r", encoding="utf-8-sig") as f:
                results_cache = json.load(f)
        else:
            print(f"[{name}] Running engine queries...")
            results_cache = []

            orig_alpha = getattr(hqe, "_ALPHA_GRAPH", 0.4)
            orig_beta = getattr(hqe, "_BETA_VECTOR", 0.6)
            orig_graph_mode = getattr(hqe, "_GRAPH_MODE", "enhanced")
            orig_use_enhanced = getattr(hqe, "_USE_ENHANCED_GRAPH", True)

            engine = DigitalTwinInterviewEngine()
            try:
                hqe._ALPHA_GRAPH = config.alpha
                hqe._BETA_VECTOR = config.beta
                hqe._GRAPH_MODE = config.graph_mode.value
                hqe._USE_ENHANCED_GRAPH = config.graph_mode == GraphMode.ENHANCED

                engine.connect()
                for item in eval_dataset:
                    org_id = str(item.get("org_id") or "default_org")
                    targets = item.get("targets") or []
                    if not isinstance(targets, list) or not targets:
                        continue

                    per_id = str(targets[0]).strip()
                    question = str(item.get("question") or "").strip()
                    ground_truth = str(item.get("ground_truth") or "").strip()
                    qa_id = str(item.get("qa_id") or "")
                    if not per_id or not question:
                        continue

                    try:
                        response = engine.answer_interview(
                            org_id,
                            per_id,
                            question,
                            skip_access_check=True,
                            force_private_mode=True,
                        )
                    except Exception as exc:
                        print(f"  [WARN] answer_interview failed for {qa_id or per_id}: {exc}")
                        response = {"answer": "", "contexts": []}

                    contexts = response.get("contexts") or []
                    if not isinstance(contexts, list):
                        contexts = [str(contexts)]
                    normalized_contexts = [str(c).strip() for c in contexts if str(c).strip()]

                    row_payload: dict[str, Any] = {
                        "qa_id": qa_id,
                        "question": question,
                        "answer": str(response.get("answer") or ""),
                        "contexts": normalized_contexts,
                        "ground_truth": ground_truth,
                    }

                    if args.debug_context:
                        debug_ctx = response.get("debug_context") or {}
                        if not isinstance(debug_ctx, dict):
                            debug_ctx = {}
                        row_payload["raw_count"] = int(debug_ctx.get("raw_count") or 0)
                        row_payload["selected_count"] = int(debug_ctx.get("selected_count") or 0)
                        raw_preview = debug_ctx.get("raw_preview") or []
                        if not isinstance(raw_preview, list):
                            raw_preview = [str(raw_preview)]
                        row_payload["raw_preview"] = [str(x) for x in raw_preview]

                    results_cache.append(row_payload)

            except ServiceUnavailable:
                print(f"[{name}] ⚠ Neo4j unavailable. Start with: docker-compose up -d")
                continue
            finally:
                engine.close()
                hqe._ALPHA_GRAPH = orig_alpha
                hqe._BETA_VECTOR = orig_beta
                hqe._GRAPH_MODE = orig_graph_mode
                hqe._USE_ENHANCED_GRAPH = orig_use_enhanced

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

        result = evaluate(
            dataset,
            metrics=metrics,
            show_progress=False,
            raise_exceptions=False,
        )  # type: ignore[arg-type]

        metrics_payload = {
            "faithfulness":       safe_get(result, "faithfulness"),
            "answer_relevancy":   safe_get(result, "answer_relevancy"),
            "context_precision":  safe_get(result, "context_precision"),
            "context_recall":     safe_get(result, "context_recall"),
            "answer_correctness": safe_get(result, "answer_correctness"),
        }

        elapsed = time.perf_counter() - started_at
        runtime_seconds_by_config[name] = elapsed
        final_eval_results[name] = metrics_payload

        config_result = {
            "config": {
                "name": name,
                "alpha": config.alpha,
                "beta": config.beta,
                "graph_mode": config.graph_mode.value,
            },
            "dataset": dataset_path,
            "judge": {
                "model": "gpt-4o-mini",
                "temperature": 0,
            },
            "runtime_seconds": round(elapsed, 3),
            "num_samples": len(results_cache),
            "metrics": metrics_payload,
        }
        save_json(config_result, OUTPUT_FILES[name])
        print(f"[{name}] Done in {elapsed:.2f}s. Saved: {OUTPUT_FILES[name]}")

    comparison_table = {
        "configs": ["RAG", "GraphRAG", "Hybrid", "Hybrid+"],
        "metrics": {
            "faithfulness": [
                final_eval_results.get("RAG", {}).get("faithfulness", 0.0),
                final_eval_results.get("GraphRAG", {}).get("faithfulness", 0.0),
                final_eval_results.get("Hybrid", {}).get("faithfulness", 0.0),
                final_eval_results.get("HybridPlus", {}).get("faithfulness", 0.0),
            ],
            "answer_relevancy": [
                final_eval_results.get("RAG", {}).get("answer_relevancy", 0.0),
                final_eval_results.get("GraphRAG", {}).get("answer_relevancy", 0.0),
                final_eval_results.get("Hybrid", {}).get("answer_relevancy", 0.0),
                final_eval_results.get("HybridPlus", {}).get("answer_relevancy", 0.0),
            ],
            "context_precision": [
                final_eval_results.get("RAG", {}).get("context_precision", 0.0),
                final_eval_results.get("GraphRAG", {}).get("context_precision", 0.0),
                final_eval_results.get("Hybrid", {}).get("context_precision", 0.0),
                final_eval_results.get("HybridPlus", {}).get("context_precision", 0.0),
            ],
            "context_recall": [
                final_eval_results.get("RAG", {}).get("context_recall", 0.0),
                final_eval_results.get("GraphRAG", {}).get("context_recall", 0.0),
                final_eval_results.get("Hybrid", {}).get("context_recall", 0.0),
                final_eval_results.get("HybridPlus", {}).get("context_recall", 0.0),
            ],
            "answer_correctness": [
                final_eval_results.get("RAG", {}).get("answer_correctness", 0.0),
                final_eval_results.get("GraphRAG", {}).get("answer_correctness", 0.0),
                final_eval_results.get("Hybrid", {}).get("answer_correctness", 0.0),
                final_eval_results.get("HybridPlus", {}).get("answer_correctness", 0.0),
            ],
        },
        "ablation_notes": {
            "graph_contribution": "Hybrid vs RAG",
            "graph_complexity_contribution": "Hybrid+ vs Hybrid",
            "pure_graph_vs_hybrid": "GraphRAG vs Hybrid",
        },
        "runtime_seconds": {
            "RAG": round(runtime_seconds_by_config.get("RAG", 0.0), 3),
            "GraphRAG": round(runtime_seconds_by_config.get("GraphRAG", 0.0), 3),
            "Hybrid": round(runtime_seconds_by_config.get("Hybrid", 0.0), 3),
            "HybridPlus": round(runtime_seconds_by_config.get("HybridPlus", 0.0), 3),
        },
    }
    save_json(comparison_table, "results/ragas_comparison_table.json")

    # ── In bảng so sánh ───────────────────────────────────────────────────────
    print("\n" + "=" * 75)
    row_fmt = "{:<25} | " + " | ".join(["{:<12}"] * 4)
    print(row_fmt.format("Metric", "RAG", "GraphRAG", "Hybrid", "Hybrid+"))
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
            f"{final_eval_results.get('RAG', {}).get(m, 0.0):.4f}",
            f"{final_eval_results.get('GraphRAG', {}).get(m, 0.0):.4f}",
            f"{final_eval_results.get('Hybrid', {}).get(m, 0.0):.4f}",
            f"{final_eval_results.get('HybridPlus', {}).get(m, 0.0):.4f}",
        ]
        print(row_fmt.format(m, *vals))

    print("=" * 75)
    print("Evaluation complete. Results saved to results/ragas_comparison_table.json")


if __name__ == "__main__":
    main()