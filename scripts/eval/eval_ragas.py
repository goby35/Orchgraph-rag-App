import sys
import os
import json
import warnings
from typing import Union, List, Dict, Any

# Ép hệ thống nhận diện thư mục gốc (graphRAG) để import pipeline
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

# Ẩn các cảnh báo DeprecationWarning từ Ragas hoặc Pyvi/NumPy
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", module=".*pyvi.*")
warnings.filterwarnings("ignore", message=".*align should be passed.*")

try:
    from datasets import Dataset
    from ragas import evaluate
    from ragas.metrics.collections import (
        faithfulness,
        answer_relevancy,
        context_precision,
        context_recall,
        answer_correctness
    )
    from ragas.llms import LangchainLLMWrapper
    from langchain_openai import ChatOpenAI
except ImportError as e:
    print(f"Missing required packages: {e}")
    print("pip install ragas langchain-openai datasets")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Import pipeline modules
try:
    import pipeline.hybrid_query_engine as hqe
    from pipeline.hybrid_query_engine import DigitalTwinInterviewEngine
except ImportError as e:
    print(f"Error: Could not import pipeline modules. Details: {e}")
    sys.exit(1)

QA_DATASET_PATH = "data_eval/qa_dataset.json"

CONFIGS = [
    {"name": "RAG",      "alpha": 0.0, "beta": 1.0},
    {"name": "GraphRAG", "alpha": 1.0, "beta": 0.0},
    {"name": "Hybrid",   "alpha": 0.2, "beta": 0.8},
]

def save_json(data: Union[Dict[str, Any], List[Any]], filepath: str):
    """Utility to save dictionary or list as JSON."""
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def safe_get(res: Any, key: str) -> float:
    """Safely extract float metrics from EvaluationResult object."""
    try:
        # EvaluationResult supports bracket access but not .get()
        val = res[key]
        return float(val) if val is not None else 0.0
    except Exception:
        return 0.0

def main():
    if not os.path.exists(QA_DATASET_PATH):
        os.makedirs(os.path.dirname(QA_DATASET_PATH) or ".", exist_ok=True)
        template = [
            {
                "qa_id": f"q_{i+1}",
                "per_id": "sample_personnel_id",
                "org_id": "sample_org_id",
                "question": "Sample interview question?",
                "ground_truth": "Expected ideal answer goes here.",
                "qa_type": "technical",
                "contexts": ["Relevant context snippet 1", "Relevant context snippet 2"]
            } for i in range(3)
        ]
        save_json(template, QA_DATASET_PATH)
        print(f"Created template dataset at {QA_DATASET_PATH}")
        print("Please fill in the real QA pairs and run this script again.")
        sys.exit(0)

    with open(QA_DATASET_PATH, "r", encoding="utf-8") as f:
        qa_dataset = json.load(f)

    os.makedirs("results", exist_ok=True)
    
    eval_llm = LangchainLLMWrapper(ChatOpenAI(model="gpt-4o-mini", temperature=0))
    metrics = [
        faithfulness,
        answer_relevancy,
        context_precision,
        context_recall,
        answer_correctness
    ]

    final_eval_results = {}

    for config in CONFIGS:
        name = config["name"]
        alpha = config["alpha"]
        beta = config["beta"]
        
        cache_file = f"results/ragas_answers_{name}.json"
        
        if os.path.exists(cache_file):
            print(f"[{name}] Loading cached answers from {cache_file}...")
            with open(cache_file, "r", encoding="utf-8") as f:
                results_cache = json.load(f)
        else:
            print(f"[{name}] Running engine queries (alpha={alpha}, beta={beta})...")
            results_cache = []
            
            orig_alpha = getattr(hqe, "_ALPHA_GRAPH", 0.5)
            orig_beta = getattr(hqe, "_BETA_VECTOR", 0.5)
            
            engine = DigitalTwinInterviewEngine()
            try:
                hqe._ALPHA_GRAPH = alpha
                hqe._BETA_VECTOR = beta
                
                engine.connect()
                
                for item in qa_dataset:
                    # Lấy org_id mặc định vì JSON của bạn không có
                    org_id = item.get("org_id", "default_org")
                    
                    # Trích xuất per_id từ mảng target_personnel
                    targets = item.get("target_personnel", [])
                    if not targets:
                        print(f"⚠️ Bỏ qua câu hỏi '{item.get('question')}' vì không có target_personnel.")
                        continue
                    per_id = targets[0]
                    
                    question = item.get("question", "")
                    qa_id = item.get("question_id", "")
                    ground_truth = item.get("ground_truth", "")
                    
                    # Gọi engine
                    response = engine.answer_interview(org_id, per_id, question)
                    
                    # RAGAS bắt buộc phải có 'contexts' (dữ liệu retrieve được) để chấm điểm.
                    # Giả định engine của bạn trả về danh sách context dưới key "contexts" hoặc "source_documents"
                    retrieved_contexts = response.get("contexts", [])
                    
                    # Nếu engine không trả về context nào, dùng fallback để Ragas không bị crash
                    if not retrieved_contexts or not isinstance(retrieved_contexts, list):
                        retrieved_contexts = ["No context retrieved by engine"]
                    
                    results_cache.append({
                        "qa_id": qa_id,
                        "question": question,
                        "answer": response.get("answer", "No answer generated"),
                        "contexts": retrieved_contexts,
                        "ground_truth": ground_truth
                    })
            finally:
                engine.close()
                hqe._ALPHA_GRAPH = orig_alpha
                hqe._BETA_VECTOR = orig_beta
                
            save_json(results_cache, cache_file)

        data_dict = {
            "question": [x["question"] for x in results_cache],
            "answer": [x["answer"] for x in results_cache],
            "contexts": [x["contexts"] for x in results_cache],
            "ground_truth": [x["ground_truth"] for x in results_cache]
        }
        
        dataset = Dataset.from_dict(data_dict)
        
        print(f"[{name}] Evaluating metrics with RAGAS...")
        # Sử dụng type: ignore để ép Pylance bỏ qua việc kiểm tra kiểu dữ liệu giả của list metrics
        result = evaluate(dataset, metrics=metrics, llm=eval_llm)  # type: ignore
        
        final_eval_results[name] = {
            "faithfulness": safe_get(result, "faithfulness"),
            "answer_relevancy": safe_get(result, "answer_relevancy"),
            "context_precision": safe_get(result, "context_precision"),
            "context_recall": safe_get(result, "context_recall"),
            "answer_correctness": safe_get(result, "answer_correctness")
        }

    save_json(final_eval_results, "ragas_eval.json")

    print("\n" + "="*75)
    headers = ["Metric", "RAG", "GraphRAG", "Hybrid"]
    row_format = "{:<25} | {:<12} | {:<12} | {:<12}"
    print(row_format.format(*headers))
    print("-" * 75)
    
    metric_keys = [
        "faithfulness", 
        "answer_relevancy", 
        "context_precision", 
        "context_recall", 
        "answer_correctness"
    ]
    
    for m in metric_keys:
        r_val = f"{final_eval_results.get('RAG', {}).get(m, 0.0):.4f}"
        g_val = f"{final_eval_results.get('GraphRAG', {}).get(m, 0.0):.4f}"
        h_val = f"{final_eval_results.get('Hybrid', {}).get(m, 0.0):.4f}"
        print(row_format.format(m, r_val, g_val, h_val))
    print("="*75)
    print("Evaluation complete. Results saved to ragas_eval.json")

if __name__ == "__main__":
    main()