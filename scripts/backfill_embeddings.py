from neo4j import GraphDatabase
from pipeline.vectorizer import embed_all_models
from pipeline.config import settings

ALLOWED_FIELDS = {
    "public_embeddings_gte",
    "public_embeddings_bge",
    "public_embeddings_minilm",
    "public_embeddings_e5",
    "public_embeddings_phobert",
}

def backfill_missing_embeddings():
    with GraphDatabase.driver(settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)) as driver:
        with driver.session() as session:
            # Bước 1: Tìm các Node Personnel bị thiếu model mới (retry cho partial writes)
            # Đồng thời kéo luôn phần text tóm tắt (summary) về để vectorize
            query_get = """
            MATCH (p:Personnel)
            WHERE (
                p.public_embeddings_gte IS NULL
                OR p.public_embeddings_bge IS NULL
                OR p.public_embeddings_minilm IS NULL
            )
              AND p.public_professional_summary IS NOT NULL
            RETURN p.id AS id, p.public_professional_summary AS text
            """
            records = session.run(query_get).data()

            print(f"Tìm thấy {len(records)} ứng viên cần update embeddings.")

            batch_rows = []
            failed_ids = []

            for record in records:
                p_id = record['id']
                text = record['text']

                print(f"Đang xử lý vector cho ID: {p_id}...")

                try:
                    # Bước 2: Chạy tính toán vector cho tất cả models
                    embeddings_dict = embed_all_models(text)

                    # Alias tương thích: e5 được dùng làm nguồn cho field minilm đích
                    if "public_embeddings_minilm" not in embeddings_dict and "public_embeddings_e5" in embeddings_dict:
                        embeddings_dict["public_embeddings_minilm"] = embeddings_dict["public_embeddings_e5"]

                    # WHITELIST: chỉ cho phép các field đã định nghĩa
                    unexpected = [key for key in embeddings_dict.keys() if key not in ALLOWED_FIELDS]
                    if unexpected:
                        raise ValueError(f"Unexpected embedding fields for {p_id}: {unexpected}")

                    # Bước 3: Build batch row cho update 1 lần bằng UNWIND
                    row = {
                        "id": p_id,
                        "public_embeddings_gte": embeddings_dict.get("public_embeddings_gte"),
                        "public_embeddings_bge": embeddings_dict.get("public_embeddings_bge"),
                        "public_embeddings_minilm": embeddings_dict.get("public_embeddings_minilm"),
                    }
                    batch_rows.append(row)
                    print(f"✅ Đã update thành công ID: {p_id}")
                except Exception as exc:
                    failed_ids.append(p_id)
                    print(f"❌ Lỗi khi xử lý ID {p_id}: {exc}")

            updated_count = 0
            if batch_rows:
                set_query = """
                UNWIND $batch AS row
                MATCH (p:Personnel {id: row.id})
                SET p.public_embeddings_gte = coalesce(row.public_embeddings_gte, p.public_embeddings_gte),
                    p.public_embeddings_bge = coalesce(row.public_embeddings_bge, p.public_embeddings_bge),
                    p.public_embeddings_minilm = coalesce(row.public_embeddings_minilm, p.public_embeddings_minilm),
                    p.last_updated = timestamp()
                RETURN count(p) AS updated_count
                """
                result = session.run(set_query, batch=batch_rows).single()
                updated_count = int(result["updated_count"]) if result and result.get("updated_count") is not None else 0

            print(f"Batch write hoàn tất: {updated_count}/{len(batch_rows)} records được ghi.")
            if failed_ids:
                print(f"⚠️ Tổng số records lỗi: {len(failed_ids)}")
                print("⚠️ Failed IDs:", ", ".join(failed_ids))
            else:
                print("Không có record lỗi.")

if __name__ == "__main__":
    backfill_missing_embeddings()