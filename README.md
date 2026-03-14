# Transparent AI Digital Twin — GraphRAG

Hệ thống **Knowledge Graph** tiếng Việt cho dữ liệu doanh nghiệp (CV nhân sự, Quy trình SOP, Dự án), kết hợp **Hybrid Vector + Graph Search** và **LLM** để trả lời câu hỏi minh bạch với nguồn trích dẫn rõ ràng.

---

## Mục lục

- [Kiến trúc tổng quan](#kiến-trúc-tổng-quan)
- [Tech Stack](#tech-stack)
- [Cấu trúc thư mục](#cấu-trúc-thư-mục)
- [Cài đặt](#cài-đặt)
- [Cấu hình](#cấu-hình)
- [Khởi chạy](#khởi-chạy)
- [Pipeline xử lý dữ liệu](#pipeline-xử-lý-dữ-liệu)
- [Re-Embedding (A/B Testing)](#re-embedding-ab-testing)
- [Graph Schema (Neo4j)](#graph-schema-neo4j)
- [Query Engine](#query-engine)
- [Batch Runner](#batch-runner)
- [Giao diện Web (Streamlit)](#giao-diện-web-streamlit)
- [Lệnh CLI](#lệnh-cli)
- [Tiện ích](#tiện-ích)
- [Loại tài liệu hỗ trợ](#loại-tài-liệu-hỗ-trợ)

---

## Kiến trúc tổng quan

```
┌──────────────────────────────────────────────────────────────────┐
│                          Streamlit UI                            │
│   Khách (Guest)  ·  Quản trị viên (Admin)  ·  Người dùng nội bộ │
│   Upload & Ingest  ·  Chat Query  ·  Trích dẫn [VEC] / [GRF]   │
└───────────────────────────┬──────────────────────────────────────┘
                            │
          ┌─────────────────┴─────────────────┐
          ▼                                   ▼
┌──────────────────┐               ┌─────────────────────┐
│  Data Pipeline   │               │   Hybrid Query      │
│  (5 bước)        │               │   Engine             │
│                  │               │                     │
│ Parse → Clean    │               │ NER (regex)         │
│ → Chunk          │               │ → Graph exact-match │
│ → Extract (LLM)  │               │ → Vector cosine     │
│ → Vectorize      │               │ → LLM Synthesis     │
└────────┬─────────┘               └──────────┬──────────┘
         │                                    │
         ▼                                    ▼
┌──────────────────────────────────────────────────────────────┐
│                       Neo4j 5.26 Database                    │
│  (Document)─[:HAS_CHUNK]─>(Chunk)─[:MENTIONS]─>(Entity)     │
│                     (Entity)─[:RELATED_TO]─>(Entity)         │
│  Vector Index: vector_index_{model} (768-d / 1024-d cosine)  │
│  Multi-embedding: embedding_phobert_v2, embedding_bge_m3, …  │
└──────────────────────────────────────────────────────────────┘
```

**Ba thành phần chính:**

| # | Thành phần | Mô tả |
|---|-----------|-------|
| 1 | **Streamlit Web App** (`app.py`) | Giao diện 3 vai trò: upload tài liệu (Admin), chat hỏi đáp (User), hiển thị reasoning minh bạch với trích dẫn `[VEC]` / `[GRF]` |
| 2 | **Data Pipeline** (`pipeline/`) | Chuỗi 5 bước: Parse → Clean → Chunk → Extract → Vectorize, trích xuất entity & triplet bằng LLM |
| 3 | **Hybrid Query Engine** (`pipeline/hybrid_query_engine.py`) | Kết hợp graph exact-match (entity name) + vector cosine similarity, tổng hợp câu trả lời bằng LLM kèm trích dẫn nguồn |

---

## Tech Stack

| Thành phần | Công nghệ |
|-----------|-----------|
| **Database** | Neo4j 5.26.0 (APOC + GDS plugins) |
| **Embedding chính** | PhoBERT v2 (`vinai/phobert-base-v2`) — 768 chiều |
| **Embedding A/B** | BGE-M3 (`BAAI/bge-m3`) — 1024 chiều, GTE (`Alibaba-NLP/gte-multilingual-base`) — 768 chiều |
| **Tokenizer tiếng Việt** | PyVi (`ViTokenizer`) |
| **LLM chính** | Cerebras (`llama3.1-8b`) |
| **LLM dự phòng** | OpenAI (`gpt-4o`) |
| **Document Parsing** | Docling (primary) + Nutrient.io API (fallback) |
| **OCR** | EasyOCR (cho tài liệu scan) |
| **Chunking** | LlamaIndex `SentenceSplitter` (250 tokens, overlap 20) |
| **Frontend** | Streamlit |
| **Validation** | Pydantic v2 |
| **Infra** | Docker Compose (Neo4j) |

---

## Cấu trúc thư mục

```
graphRAG/
├── app.py                          # Streamlit web app (3 vai trò)
├── batch_runner.py                 # Xử lý hàng loạt: quét storage → pipeline → Neo4j
├── re_embedder.py                  # Re-embedding: thay đổi model embedding (A/B testing)
├── final_ingestion.py              # Nạp song song Neo4j + ChromaDB (Employee-centric)
├── docker-compose.yml              # Neo4j container
├── requirements.txt                # Dependencies
├── .env                            # API keys & config (tạo thủ công)
│
├── pipeline/                       # Package xử lý dữ liệu
│   ├── __init__.py                 # Public API exports
│   ├── config.py                   # Cấu hình tập trung (env vars, logging)
│   ├── parser.py                   # Bước 1: PDF/DOCX → Markdown (Docling → Nutrient fallback)
│   ├── cleaner.py                  # Bước 2: Unicode NFC, xóa ký tự ẩn, nối dòng gãy
│   ├── chunker.py                  # Bước 3: SentenceSplitter ≤250 tokens (overlap 20)
│   ├── extractor.py                # Bước 4: Trích xuất entity & triplet (Cerebras → OpenAI)
│   ├── vectorizer.py               # Bước 5: PyVi tokenize → PhoBERT embedding (768-d)
│   ├── main.py                     # Orchestrator: chạy 5 bước tuần tự + skip check
│   ├── neo4j_ingestion.py          # Nạp JSON vào Neo4j (MERGE/upsert, dynamic labels)
│   └── hybrid_query_engine.py      # Hybrid: graph exact-match + vector search → LLM
│
├── data_lake/                      # Tài liệu upload từ Streamlit UI
│   └── 01_raw/                     # File gốc theo loại (cv/, sop/, project/)
│
├── storage/                        # Tài liệu gốc (input cho batch_runner)
│   ├── cv/                         # File DOCX/PDF CV nhân sự
│   ├── sop/                        # File DOCX/PDF quy trình vận hành
│   └── project/                    # File DOCX/PDF tài liệu dự án
│
├── neo4j_ready/                    # JSON output đã qua pipeline
│   ├── phobert-v2/                 # PhoBERT v2 embeddings (768-d) — primary
│   ├── bge-m3/                     # BGE-M3 embeddings (1024-d) — A/B test
│   └── gte/                        # GTE-Multilingual embeddings (768-d) — A/B test
│
├── neo4j/                          # Neo4j data volume (Docker)
├── chromadb/                       # ChromaDB data volume (Docker)
│
├── check_models.py                 # Liệt kê model Cerebras khả dụng
├── clear_neo4j.py                  # Xóa toàn bộ graph (node, constraint, vector index)
├── verify_graph.py                 # Thống kê graph: node, relationship, vector index
├── test_settings.py                # In cấu hình model LLM đang load
└── word_to_input.py                # Trích xuất CV → JSON cấu trúc (TASK profile)
```

---

## Cài đặt

### Yêu cầu

- Python ≥ 3.10
- Docker & Docker Compose
- GPU (khuyến nghị) hoặc CPU cho PhoBERT / BGE-M3 / GTE

### Các bước

```bash
# 1. Clone repo
git clone <repo-url>
cd graphRAG

# 2. Tạo virtual environment
python -m venv venv
venv\Scripts\Activate.ps1          # Windows PowerShell
# source venv/bin/activate          # Linux/macOS

# 3. Cài dependencies
pip install -r requirements.txt

# 4. Khởi động Neo4j
docker compose up -d

# 5. Tạo file .env (xem mục Cấu hình)
```

---

## Cấu hình

Tạo file `.env` tại thư mục gốc:

```env
# ── LLM APIs ──
CEREBRAS_API_KEY=<your-cerebras-api-key>
CEREBRAS_MODEL=llama3.1-8b
OPENAI_API_KEY=<your-openai-api-key>
GROQ_API_KEY=<your-groq-api-key>

# ── Document Parsing (fallback) ──
NUTRIENT_API_KEY=<your-nutrient-api-key>
NUTRIENT_BASE_URL=https://api.nutrient.io/build

# ── Neo4j ──
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password123

# ── ChromaDB (optional) ──
CHROMADB_HOST=localhost
CHROMADB_PORT=8000

# ── Logging ──
LOG_LEVEL=INFO
```

| Biến | Mô tả | Mặc định |
|------|-------|----------|
| `CEREBRAS_API_KEY` | API key cho Cerebras Cloud | *(bắt buộc)* |
| `CEREBRAS_MODEL` | Model LLM của Cerebras | `llama3.1-8b` |
| `OPENAI_API_KEY` | API key OpenAI (LLM dự phòng) | *(bắt buộc)* |
| `GROQ_API_KEY` | API key Groq (tùy chọn) | *(tùy chọn)* |
| `NUTRIENT_API_KEY` | API key Nutrient.io (parsing fallback) | *(tùy chọn)* |
| `NEO4J_URI` | Bolt URI kết nối Neo4j | `bolt://127.0.0.1:7687` |
| `NEO4J_USER` | Tên đăng nhập Neo4j | `neo4j` |
| `NEO4J_PASSWORD` | Mật khẩu Neo4j | `password123` |
| `LOG_LEVEL` | Mức log (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |

---

## Khởi chạy

```bash
# Khởi động Neo4j
docker compose up -d

# Chạy web app
streamlit run app.py

# Hoặc xử lý hàng loạt (không cần UI)
python batch_runner.py
```

Truy cập giao diện tại **http://localhost:8501**.

---

## Pipeline xử lý dữ liệu

Pipeline gồm **5 bước tuần tự** cho mỗi tài liệu:

```
 File gốc (.docx/.pdf/.md)
       │
       ▼
 ┌─────────────┐
 │  1. PARSE   │  Docling (primary) → Nutrient.io API (fallback)
 │  → Markdown │  Timeout: 120s cho Nutrient
 └──────┬──────┘
        ▼
 ┌─────────────┐
 │  2. CLEAN   │  Unicode NFC, xóa ký tự ẩn (zero-width, BOM),
 │  → Text     │  nối dòng gãy, giữ cấu trúc Markdown (#, -, *)
 └──────┬──────┘
        ▼
 ┌─────────────┐
 │  3. CHUNK   │  SentenceSplitter (250 tokens, overlap 20)
 │  → Chunks   │  paragraph_separator="\n\n", regex=[.。!?;]\s*
 └──────┬──────┘
        ▼
 ┌──────────────┐
 │  4. EXTRACT  │  Cerebras (~30s) → OpenAI (~60s) fallback
 │  → Knowledge │  → Entity + Triplet (Pydantic validation)
 └──────┬───────┘
        ▼
 ┌───────────────┐
 │  5. VECTORIZE │  PyVi tokenize → PhoBERT CLS embedding (768-d)
 │  → JSON       │  Auto-detect CUDA / CPU
 └───────────────┘
```

### Tự động nhận diện

- **Loại tài liệu**: phát hiện từ đường dẫn thư mục (`cv/`, `sop/`, `project/`)
- **Chủ thể lõi (core entity)**: phát hiện từ nội dung — tên người (CV), tên quy trình (SOP), tên dự án (PROJECT)
- **Checkpoint**: nếu `neo4j_ready/{model}/filename.json` đã tồn tại → bỏ qua

### Output

Mỗi file tạo ra một file JSON trong `neo4j_ready/phobert-v2/`, chứa danh sách chunks:

```json
[
  {
    "chunk_id": "uuid-...",
    "source_file": "filename.docx",
    "chunk_index": 1,
    "original_clean_text": "Nội dung gốc đã clean...",
    "segmented_text": "Nội_dung gốc đã clean...",
    "embedding": [0.012, -0.045, ...],
    "extracted_knowledge": {
      "doc_type": "CV",
      "topic_category": "EXPERIENCE",
      "entities": [
        {"name": "Nguyễn Văn A", "type": "PERSON"}
      ],
      "triplets": [
        {"subject": "Nguyễn Văn A", "relation": "đảm nhận", "object": "CTO"}
      ]
    }
  }
]
```

---

## Re-Embedding (A/B Testing)

Script `re_embedder.py` cho phép thay thế embedding bằng model khác mà **không chạy lại** pipeline 5 bước:

| Model | Alias | Dimensions | Pooling | Input text |
|-------|-------|-----------|---------|------------|
| `vinai/phobert-base-v2` | `phobert` | 768 | CLS | `segmented_text` |
| `BAAI/bge-m3` | `bge-m3` | 1024 | CLS dense | `original_clean_text` |
| `Alibaba-NLP/gte-multilingual-base` | `gte` | 768 | Mean pooling | `original_clean_text` |

### Sử dụng

```bash
# Re-embed toàn bộ thư mục sang BGE-M3
python re_embedder.py --model bge-m3 --input ./neo4j_ready/phobert-v2 --output ./neo4j_ready/bge-m3

# Re-embed sang GTE
python re_embedder.py --model gte --input ./neo4j_ready/phobert-v2 --output ./neo4j_ready/gte

# Benchmark 3 model trên 1 file
python re_embedder.py --benchmark --input ./neo4j_ready/phobert-v2/01_NguyenHoaiTuong_CEO.json
```

Embedding được L2-normalize về unit vector. Output JSON chứa metadata envelope ghi nhận source model, target model, timestamp, và embedding dimension.

---

## Graph Schema (Neo4j)

### Node types

| Label | Mô tả | Key Property |
|-------|-------|--------------|
| `Document` | Tài liệu gốc (+ label động theo `topic_category`) | `source_file` (UNIQUE) |
| `Chunk` | Đoạn văn bản, chứa multi-embedding (`embedding_{model}`) | `chunk_id` (UNIQUE) |
| `Entity` | Thực thể trích xuất (Person, Org, Skill, ...) | `name` (UNIQUE) |

### Relationships

```
(Document)-[:HAS_CHUNK]->(Chunk)
(Chunk)-[:MENTIONS]->(Entity)
(Entity)-[:RELATED_TO {action: "..."}]->(Entity)
```

### Dynamic Labels (Document)

Dựa trên `topic_category`, Document node tự động nhận label phụ (qua `apoc.create.addLabels()`):

| Doc Type | Topic Category | Dynamic Label |
|----------|---------------|---------------|
| CV | PERSONNEL | `Personnel` |
| CV | EXPERIENCE | `Experience` |
| CV | EDUCATION | `Education` |
| CV | SKILL | `Skill` |
| CV | ACHIEVEMENT | `Achievement` |
| SOP | PROCESS_FLOW | `ProcessFlow` |
| SOP | APPROVAL | `Approval` |
| SOP | CONDITION | `Condition` |
| SOP | TOOL_USAGE | `ToolUsage` |
| SOP | COMPLIANCE | `Compliance` |
| PROJECT | OBJECTIVE | `Objective` |
| PROJECT | PLANNING | `Planning` |
| PROJECT | EXECUTION | `Execution` |
| PROJECT | RISK | `Risk` |
| PROJECT | REPORTING | `Reporting` |

### Multi-Embedding (A/B Testing)

Chunk node lưu trữ nhiều embedding cùng lúc qua dynamic property:

```
(Chunk {
  chunk_id: "...",
  embedding_phobert_v2: [768-d vector],
  embedding_bge_m3:     [1024-d vector],
  embedding_gte:        [768-d vector]
})
```

Mỗi model có vector index riêng: `vector_index_{model_name}`.

### Constraints & Indexes

```cypher
-- Constraints (idempotent)
CREATE CONSTRAINT entity_name_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.name IS UNIQUE
CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE
CREATE CONSTRAINT document_source_unique IF NOT EXISTS FOR (d:Document) REQUIRE d.source_file IS UNIQUE

-- Vector Index (dynamic per model — cosine similarity)
CREATE VECTOR INDEX vector_index_phobert_v2 IF NOT EXISTS
  FOR (c:Chunk) ON (c.embedding_phobert_v2)
  OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}

CREATE VECTOR INDEX vector_index_bge_m3 IF NOT EXISTS
  FOR (c:Chunk) ON (c.embedding_bge_m3)
  OPTIONS {indexConfig: {`vector.dimensions`: 1024, `vector.similarity_function`: 'cosine'}}
```

---

## Query Engine

Hybrid Query Engine kết hợp **graph exact-match** và **vector search** qua 4 bước:

```
 Câu hỏi (tiếng Việt)
       │
       ▼
 ┌──────────────────┐
 │  1. Embed câu hỏi│  PyVi tokenize → PhoBERT → 768-d vector
 └────────┬─────────┘
          ▼
 ┌──────────────────────────────────────────────────────┐
 │  2. Named Entity Extraction                          │
 │     Regex NER: tên người, tên dự án (CamelCase)     │
 └────────┬─────────────────────────────────────────────┘
          ▼
 ┌──────────────────────────────────────────────────────┐
 │  3. Hybrid Retrieval                                 │
 │                                                      │
 │  Luồng 1 — Graph Exact Match (score=1.0):            │
 │    Entity name → MATCH (e:Entity) → traverse → Chunk │
 │                                                      │
 │  Luồng 2 — Vector Search:                            │
 │    db.index.vector.queryNodes(vector_index_{model})  │
 │    → top-K chunks (cosine similarity)                │
 │                                                      │
 │  Merge: union → deduplicate by chunk_id              │
 │         → ưu tiên Graph matches                      │
 └────────┬─────────────────────────────────────────────┘
          ▼
 ┌──────────────────────────────────────────────────────┐
 │  4. Context Assembly (2 kênh)                        │
 │                                                      │
 │  [VEC channel]: original text + metadata + score     │
 │  [GRF channel]: entities + triplets (structured)     │
 └────────┬─────────────────────────────────────────────┘
          ▼
 ┌──────────────────┐
 │  5. LLM Synthesis│  Cerebras (primary) → OpenAI (fallback)
 │  + Trích dẫn     │  Bắt buộc ghi nguồn [VEC: ...] / [GRF: ...]
 └──────────────────┘
```

### CLI

```bash
python -m pipeline.hybrid_query_engine "Ai là CEO của công ty?" --top-k 5
```

---

## Batch Runner

Script `batch_runner.py` để xử lý hàng loạt toàn bộ thư mục `storage/`:

```bash
python batch_runner.py [--storage ./storage] [--output ./neo4j_ready] [--delay 15]
```

### Tính năng

| Tính năng | Mô tả |
|----------|-------|
| **Checkpoint** | Kiểm tra file JSON output đã tồn tại → bỏ qua file đã xử lý |
| **Fault Tolerance** | `try/except` bọc từng file — 1 file lỗi không crash chương trình |
| **Rate Limiting** | `time.sleep(N)` giữa mỗi file (mặc định 15 giây) |
| **Auto Ingest** | Tự động nạp vào Neo4j sau khi pipeline hoàn tất mỗi file |
| **Báo cáo** | In tiến độ `Processing file {i}/{total}` + bảng tổng kết (succeeded/failed/skipped) |

### Tham số

| Flag | Mô tả | Mặc định |
|------|-------|----------|
| `--storage` | Thư mục chứa tài liệu gốc | `./storage` |
| `--output` | Thư mục lưu JSON output | `./neo4j_ready` |
| `--delay` | Giây nghỉ giữa mỗi file | `15` |

---

## Giao diện Web (Streamlit)

### Vai trò

| Vai trò | Quyền |
|---------|-------|
| **Khách** | Xem giới thiệu hệ thống, hướng dẫn chọn vai trò |
| **Quản trị viên** | Upload tài liệu (PDF/DOCX) → chạy pipeline 5 bước → nạp vào Neo4j |
| **Người dùng nội bộ** | Chat hỏi đáp với trợ lý AI, xem trích dẫn và reasoning |

### Luồng Admin (Module 2)

1. Upload file (PDF/DOCX) qua file uploader
2. Chọn loại tài liệu: Hồ sơ nhân sự / Quy trình vận hành / Dự án
3. File lưu vào `./data_lake/01_raw/{cv|sop|project}/`
4. Pipeline tự động: Parse → Clean → Chunk → Extract → Vectorize
5. JSON output lưu vào `./neo4j_ready/phobert-v2/`
6. Nạp vào Neo4j với progress tracking

### Luồng Query (Module 3 + 4)

1. Nhập câu hỏi tiếng Việt vào chat input
2. Hybrid search: graph exact-match + vector similarity
3. LLM tổng hợp câu trả lời kèm trích dẫn `[VEC: ...]` / `[GRF: ...]`
4. Hiển thị:
   - Câu trả lời với footnotes (superscript)
   - Trích dẫn nguồn dữ liệu (📄 Văn bản / 🔗 Đồ thị)
   - Chi tiết mạng lưới suy luận (triplets: Chủ thể → Quan hệ → Đối tượng)
   - Metadata: nguồn, số đoạn truy xuất, thời gian

---

## Lệnh CLI

```bash
# ── Web App ──
streamlit run app.py

# ── Pipeline (file đơn hoặc thư mục) ──
python -m pipeline.main <file_or_folder> [--output results.json] [--core-entity "Tên"]

# ── Batch Processing ──
python batch_runner.py --storage ./storage --output ./neo4j_ready --delay 15

# ── Neo4j Ingestion (nạp JSON đã có sẵn) ──
python -m pipeline.neo4j_ingestion --dir ./neo4j_ready --model phobert-v2

# ── Hybrid Query (CLI) ──
python -m pipeline.hybrid_query_engine "Câu hỏi tiếng Việt" --top-k 5

# ── Re-Embedding (thay đổi model embedding) ──
python re_embedder.py --model bge-m3 --input ./neo4j_ready/phobert-v2 --output ./neo4j_ready/bge-m3
python re_embedder.py --model gte --input ./neo4j_ready/phobert-v2 --output ./neo4j_ready/gte
python re_embedder.py --benchmark --input ./neo4j_ready/phobert-v2/file.json

# ── Docker ──
docker compose up -d        # Khởi động Neo4j
docker compose down          # Dừng services
```

---

## Tiện ích

| Script | Lệnh | Mô tả |
|--------|------|-------|
| `check_models.py` | `python check_models.py` | Liệt kê model Cerebras khả dụng |
| `clear_neo4j.py` | `python clear_neo4j.py` | Xóa toàn bộ node, constraint, vector index trong Neo4j |
| `verify_graph.py` | `python verify_graph.py` | Thống kê graph: số node theo label, relationship, triplet mẫu, trạng thái vector index |
| `test_settings.py` | `python test_settings.py` | In cấu hình model LLM đang được load |
| `word_to_input.py` | `python word_to_input.py --input storage/cv` | Trích xuất CV → JSON cấu trúc TASK (Thinking-Attitude-Skill-Knowledge) |
| `final_ingestion.py` | `python final_ingestion.py` | Nạp dữ liệu song song vào Neo4j + ChromaDB (Employee-centric model) |
| `re_embedder.py` | `python re_embedder.py --model bge-m3 ...` | Re-embed JSON với model mới (A/B testing) |

---

## Loại tài liệu hỗ trợ

### Định dạng file

`.pdf`, `.docx`, `.doc`, `.md`

### Phân loại nội dung

| Loại | Thư mục | Core Entity | Ví dụ |
|------|---------|-------------|-------|
| **CV** | `storage/cv/` | Tên nhân sự | CEO, CTO, Dev, Sales, HR, QA... |
| **SOP** | `storage/sop/` | Tên quy trình | Phê duyệt dự án, Phát triển phần mềm, Tuyển dụng... |
| **PROJECT** | `storage/project/` | Tên dự án | TSC, Velora, NovaFlow, AIInsight... |

### Entity Types (Taxonomy)

**Chung** (mọi loại tài liệu): `PERSON`, `ORG`, `ROLE`, `TOOL`, `METRIC`, `TIME`, `CONCEPT`

**Riêng theo loại:**

| CV | SOP | PROJECT |
|----|-----|---------|
| `SKILL` | `PROCESS` | `MILESTONE` |
| `CERT` | `CONDITION` | `RISK` |
| `LANGUAGE` | `DOCUMENT` | `KPI` |
| `EVENT` | `STANDARD` | `PHASE` |
| `PRODUCT` | | `BUDGET` |

### Quan hệ (Relations) theo loại

| CV | SOP | PROJECT |
|----|-----|---------|
| làm việc tại | bắt đầu bằng | có mục tiêu |
| giữ chức vụ | tiếp theo là | bao gồm giai đoạn |
| có kỹ năng | kích hoạt khi | đạt milestone |
| tốt nghiệp | sử dụng công cụ | có rủi ro |
| lãnh đạo | tạo tài liệu | báo cáo lên |

---

## Luồng End-to-End

```
1. Admin upload tài liệu qua Streamlit UI
       ↓
2. File lưu vào ./data_lake/01_raw/{cv|sop|project}/
       ↓
3. Pipeline tự động chạy 5 bước (Parse → Clean → Chunk → Extract → Vectorize)
       ↓
4. JSON output → ./neo4j_ready/phobert-v2/
       ↓
5. Nạp vào Neo4j (MERGE — upsert, không trùng lặp node)
       ↓
6. (Tùy chọn) Re-embed sang BGE-M3 / GTE → nạp thêm vector index
       ↓
7. User hỏi câu hỏi → Graph exact-match + Vector search → LLM trả lời kèm [VEC] / [GRF]
```
