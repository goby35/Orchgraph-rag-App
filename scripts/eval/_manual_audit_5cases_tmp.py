import json
import os
import sys
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from datasets import Dataset
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall, answer_correctness
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pipeline.config import settings

TARGET_IDS = ["Q_041", "Q_042", "Q_044", "Q_049", "Q_052"]

qa_rows = json.loads(Path("data_eval/qa_dataset.json").read_text(encoding="utf-8-sig"))
qa_map = {row["qa_id"]: row for row in qa_rows}

audit_rows = json.loads(Path("results/prompt_tuning_lowtier_check.json").read_text(encoding="utf-8"))
audit_map = {row["qa_id"]: row for row in audit_rows}

llm = LangchainLLMWrapper(
    ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=settings.OPENAI_API_KEY)
)
emb = LangchainEmbeddingsWrapper(
    OpenAIEmbeddings(model="text-embedding-3-small", api_key=settings.OPENAI_API_KEY)
)
metrics = [faithfulness, answer_relevancy, context_precision, context_recall, answer_correctness]

report = []

for qa_id in TARGET_IDS:
    q = qa_map[qa_id]
    a = audit_map[qa_id]

    ds = Dataset.from_list([
        {
            "question": q["question"],
            "answer": a["answer"],
            "contexts": a.get("contexts", []),
            "ground_truth": q["ground_truth"],
        }
    ])

    result = evaluate(
        ds,
        metrics=metrics,
        llm=llm,
        embeddings=emb,
        show_progress=False,
        raise_exceptions=False,
    )
    row = result.to_pandas().iloc[0].to_dict()

    per_case_scores = {
        "faithfulness": float(row.get("faithfulness") or 0.0),
        "answer_relevancy": float(row.get("answer_relevancy") or 0.0),
        "context_precision": float(row.get("context_precision") or 0.0),
        "context_recall": float(row.get("context_recall") or 0.0),
        "answer_correctness": float(row.get("answer_correctness") or 0.0),
    }

    report.append(
        {
            "qa_id": qa_id,
            "question": q["question"],
            "ground_truth": q["ground_truth"],
            "context_chunks": a.get("contexts", []),
            "model_answer": a["answer"],
            "ragas_scores": per_case_scores,
        }
    )

Path("results/manual_audit_5cases.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

for item in report:
    print(f"=== QA_ID === {item['qa_id']}")
    print(f"=== QUESTION === {item['question']}")
    print(f"=== GROUND TRUTH === {item['ground_truth']}")
    print("=== CONTEXT CHUNKS ===")
    for i, c in enumerate(item["context_chunks"], 1):
        print(f"[{i}] {c}")
    print(f"=== MODEL ANSWER === {item['model_answer']}")
    print(f"=== RAGAS SCORES === {json.dumps(item['ragas_scores'], ensure_ascii=False)}")
    print()

print("Saved results/manual_audit_5cases.json")
