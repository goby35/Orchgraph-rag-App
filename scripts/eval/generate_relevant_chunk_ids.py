"""
Generate relevant_chunk_ids for QA dataset using keyword overlap against Supabase chunks.

Constraints:
- No LLM
- No embeddings
- Keep existing relevant_chunks untouched
- Interactive review before writing file
"""

import json
import re
from pathlib import Path

from pipeline.supabase_client import get_supabase
from pipeline.supabase_ingestion import _neo4j_id_to_uuid

PROJECT_ROOT = Path(__file__).resolve().parents[2]
QA_PATH = PROJECT_ROOT / "data_eval" / "qa_dataset.json"

STOPWORDS = {
    # Tiếng Việt
    "tôi",
    "bạn",
    "có",
    "và",
    "là",
    "của",
    "trong",
    "với",
    "các",
    "những",
    "này",
    "đó",
    "được",
    "cho",
    "về",
    "từ",
    "khi",
    "hay",
    "hoặc",
    "nếu",
    "thì",
    "mà",
    "đã",
    "sẽ",
    "không",
    "rất",
    "nhiều",
    "một",
    "hai",
    "năm",
    # Tiếng Anh
    "i",
    "you",
    "he",
    "she",
    "we",
    "they",
    "it",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "a",
    "an",
    "the",
    "is",
    "are",
    "in",
    "was",
    "were",
    "be",
    "been",
    "and",
    "of",
    "to",
    "or",
    "but",
    "not",
    "no",
    "my",
    "your",
    "his",
    "her",
    "our",
    "their",
    "its",
    "at",
    "for",
    "on",
    "as",
    "with",
    "this",
    "that",
    "these",
    "those",
    "what",
    "which",
    "who",
    "how",
    "when",
    "where",
    "why",
    "about",
    "from",
    "into",
    "through",
    "during",
    "before",
    "after",
    "above",
    "below",
    "between",
    "each",
    "other",
    "than",
    "then",
    "so",
    "if",
    "up",
    "out",
    "any",
}

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def extract_keywords(text: str) -> set[str]:
    tokens = re.findall(r"\b\w+\b", (text or "").lower())
    return {t for t in tokens if len(t) > 2 and t not in STOPWORDS}


def score_chunk(chunk_content: str, keywords: set[str]) -> float:
    chunk_tokens = extract_keywords(chunk_content or "")
    if not keywords:
        return 0.0
    return len(keywords & chunk_tokens) / len(keywords)


def has_valid_ids(qa: dict) -> bool:
    ids = qa.get("relevant_chunk_ids", [])
    return bool(ids) and all(UUID_RE.match(str(x)) for x in ids)


def main() -> None:
    if not QA_PATH.exists():
        raise FileNotFoundError(f"QA dataset not found: {QA_PATH}")

    sb = get_supabase()

    with open(QA_PATH, "r", encoding="utf-8") as f:
        qa_data = json.load(f)

    for qa in qa_data:
        old_ids = qa.get("relevant_chunk_ids", [])
        if any(str(x).lower() in ("yes", "yess", "y", "") for x in old_ids):
            qa["relevant_chunk_ids"] = []
            qa["chunk_source"] = "pending"

    for i, qa in enumerate(qa_data):
        if has_valid_ids(qa):
            print(f"[{i}] ✓ Đã có IDs hợp lệ, bỏ qua")
            continue

        targets = qa.get("targets") or []
        personnel_id = str(targets[0]).strip() if targets else ""

        if not personnel_id:
            qa["relevant_chunk_ids"] = []
            qa["chunk_source"] = "not_found"
            continue

        user_uuid = _neo4j_id_to_uuid(personnel_id)
        result = (
            sb.schema("vdme")
            .table("document_chunks")
            .select("id, content")
            .eq("user_id", user_uuid)
            .execute()
        )

        print(f"  [DB] Tìm thấy {len(result.data or [])} chunks cho {personnel_id}")

        if not result.data:
            qa["relevant_chunk_ids"] = []
            qa["chunk_source"] = "not_found"
            continue

        keywords = extract_keywords(str(qa.get("question") or ""))

        scored: list[tuple[float, str, str]] = []
        for row in result.data:
            if not isinstance(row, dict):
                continue
            content = str(row.get("content") or "")
            score = score_chunk(content, keywords)
            if score > 0:
                scored.append((score, str(row["id"]), content[:120]))

        scored.sort(reverse=True)
        top3 = scored[:3]

        question = str(qa.get("question") or "")
        print(f"\n[{i}] Q: {question}")

        if top3:
            for rank, (score, chunk_id, preview) in enumerate(top3, start=1):
                print(f"  {rank}. score={score:.2f} id={chunk_id}")
                print(f"     \"{preview}...\"")

            print("  -> Ghi 3 IDs? (Enter=yes, s=skip, hoac nhap IDs thu cong)")
            try:
                resp = input("  > ").strip()
            except EOFError:
                resp = ""
                print("  [EOF — tự động chọn skip]")

            if resp == "s":
                qa["relevant_chunk_ids"] = []
                qa["chunk_source"] = "skipped"
            elif resp == "":
                qa["relevant_chunk_ids"] = [chunk_id for _, chunk_id, _ in top3]
                qa["chunk_source"] = "auto_keyword"
            else:
                qa["relevant_chunk_ids"] = [r.strip() for r in resp.split(",") if r.strip()]
                qa["chunk_source"] = "manual"
        else:
            print("  -> Khong tim thay chunk lien quan")
            qa["relevant_chunk_ids"] = []
            qa["chunk_source"] = "not_found"

    filled = sum(1 for q in qa_data if q.get("relevant_chunk_ids"))
    print(f"\nTong: {filled}/{len(qa_data)} QA pairs co relevant_chunk_ids")

    try:
        confirm = input("Ghi vao qa_dataset.json? (y/n) > ").strip().lower()
    except EOFError:
        confirm = "n"
        print("[EOF — hủy ghi file để an toàn]")
    if confirm == "y":
        with open(QA_PATH, "w", encoding="utf-8") as f:
            json.dump(qa_data, f, ensure_ascii=False, indent=2)
        print("Da ghi.")
    else:
        print("Huy - khong ghi file.")


if __name__ == "__main__":
    main()
