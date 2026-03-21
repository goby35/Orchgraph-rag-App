# graphRAG - Digital Twin Recruitment (Current State)

README nay duoc cap nhat theo code hien tai trong repository (thoi diem: 2026-03-15).

## 1) Tong quan

Du an xay dung he thong GraphRAG cho bai toan tuyen dung/noi bo, voi trong tam:

- Ingest du lieu vao Neo4j theo mo hinh Public/Private data compartment.
- Embedding tieng Viet bang PhoBERT (mac dinh) va ho tro re-embedding (BGE-M3, GTE).
- 2 query engine chinh:
  - MasterAgentEngine: tim ung vien theo JD bang vector search tren public data.
  - DigitalTwinInterviewEngine: tra loi phong van voi co che kiem soat truy cap private data qua relationship accepted.

## 2) Thanh phan dang dung on dinh

- Pipeline ingest chinh: `pipeline/main.py`
- Cau hinh: `pipeline/config.py`
- Parse/Clean/Extract/Vectorize:
  - `pipeline/parser.py`
  - `pipeline/cleaner.py`
  - `pipeline/extractor.py`
  - `pipeline/vectorizer.py`
- Neo4j ingestion (MERGE upsert): `pipeline/neo4j_ingestion.py`
- Query engines: `pipeline/hybrid_query_engine.py`
- E2E test: `test_engine.py`
- Re-embedding utility: `re_embedder.py`

## 3) Thanh phan can luu y (chua dong bo API)

Mot so script/file con dau vet tu version cu va hien khong khop 100% API hien tai:

- `app.py`
- `batch_runner.py`

Neu can UI Streamlit hoac batch runner, can refactor lai import va call signature de dong bo voi `pipeline/main.py`, `pipeline/neo4j_ingestion.py`, `pipeline/hybrid_query_engine.py`.

## 4) Cau truc thu muc chinh

```text
graphRAG/
|- app.py
|- batch_runner.py
|- check_models.py
|- clear_neo4j.py
|- docker-compose.yml
|- final_ingestion.py
|- re_embedder.py
|- requirements.txt
|- test_engine.py
|- test_settings.py
|- fast_track/
|- neo4j_ready/
|  |- bge-m3/
|  |- gte/
|  |- phobert-v2/
|- pipeline/
|  |- __init__.py
|  |- cleaner.py
|  |- chunker.py
|  |- config.py
|  |- extractor.py
|  |- hybrid_query_engine.py
|  |- main.py
|  |- neo4j_ingestion.py
|  |- parser.py
|  |- vectorizer.py
|- storage/
   |- cv/
   |- project/
   |- sop/
```

## 5) Yeu cau he thong

- Python 3.10+
- Docker + Docker Compose
- Neo4j 5.26 (duoc tao qua `docker-compose.yml`)
- Neu parse/embedding bang model local: can tai model HuggingFace (mang internet)

## 6) Cai dat

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Khoi dong Neo4j:

```powershell
docker compose up -d
```

## 7) Cau hinh `.env`

Tao file `.env` o thu muc goc:

```env
# LLM
CEREBRAS_API_KEY=
CEREBRAS_MODEL=llama3.1-8b
OPENAI_API_KEY=

# Optional
GROQ_API_KEY=
NUTRIENT_API_KEY=
NUTRIENT_BASE_URL=https://api.nutrient.io/build

# Neo4j
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password123

# ChromaDB (chi can cho script lien quan Chroma)
CHROMADB_HOST=localhost
CHROMADB_PORT=8000

# Logging
LOG_LEVEL=INFO
```

## 8) Luong ingest hien tai

### 8.1 Pipeline ingest chinh

Chay full pipeline tu code hien tai:

```powershell
python pipeline/main.py
```

Pipeline se quet cac nguon sau (neu ton tai):

- `neo4j_ready/bge-m3/*.json`
- `fast_track/*.json`
- `storage/cv`, `storage/project`, `storage/sop`, `storage` voi cac ext: `.pdf .docx .txt .md .json`

### 8.2 Logic ingest theo loai file

- File `.json`:
  - Bo qua parse/extract LLM.
  - Di thang qua `prepare_for_neo4j(...)` va ingest Neo4j.
- File tai lieu (`.pdf/.docx/.md/.txt`):
  - Parse -> Clean -> Extract (LLM) -> Vectorize -> Ingest Neo4j.

## 9) Query engine hien tai

### 9.1 MasterAgentEngine

- Query vector index: `personnel_public_idx`
- Property embedding: `Personnel.public_embeddings_phobert`
- Chieu vector ky vong: 768

Neu index chua ton tai, tao trong Neo4j Browser:

```cypher
CREATE VECTOR INDEX personnel_public_idx IF NOT EXISTS
FOR (p:Personnel) ON (p.public_embeddings_phobert)
OPTIONS {indexConfig: {
  `vector.dimensions`: 768,
  `vector.similarity_function`: 'cosine'
}}
```

### 9.2 DigitalTwinInterviewEngine

Chi cho phep truy cap private context khi co quan he:

```text
(:Organization)-[:CONNECTED_TO {status:'accepted'}]->(:Personnel)
```

Neu khong co accepted relationship, engine tra ve thong diep chan truy cap.

## 10) Kiem thu nhanh

### 10.1 Test settings model

```powershell
python test_settings.py
```

### 10.2 E2E test engine

```powershell
python test_engine.py
```

`test_engine.py` se:

1. (Neu co) ingest file moi trong `fast_track/`
2. Dam bao index `personnel_public_idx`
3. Test public matching
4. Test blocked interview (khong accepted)
5. Tao accepted relationship va test private interview
6. Cleanup du lieu test

## 11) Re-embedding (A/B)

Script: `re_embedder.py`

Vi du:

```powershell
python re_embedder.py --model bge-m3 --input .\neo4j_ready\phobert-v2 --output .\neo4j_ready\bge-m3
python re_embedder.py --benchmark --input .\neo4j_ready\phobert-v2\01_NguyenHoaiTuong_CEO.json
```

Model alias ho tro:

- `phobert` -> `vinai/phobert-base-v2` (768)
- `bge-m3` -> `BAAI/bge-m3` (1024)
- `gte` -> `Alibaba-NLP/gte-multilingual-base` (768)

## 12) Script tien ich

- `check_models.py`: kiem tra danh sach model Cerebras kha dung.
- `clear_neo4j.py`: xoa toan bo node + constraints + vector indexes trong Neo4j local.
- `final_ingestion.py`: luong ingest hybrid Neo4j + ChromaDB theo schema Employee/TASK (kha nang legacy, dung khi ban muon flow nay).

## 13) Troubleshooting

### Neo4j khong ket noi duoc

- Kiem tra container:

```powershell
docker compose ps
```

- Kiem tra credential trong `.env` co trung `docker-compose.yml` (mac dinh `neo4j/password123`).

### LLM khong tra loi

- Kiem tra API key trong `.env` (`CEREBRAS_API_KEY`, `OPENAI_API_KEY`).
- Extractor co fallback Cerebras -> OpenAI, nhung neu ca hai khong co key se fail.

### Query MasterAgentEngine loi vector index

- Tao index `personnel_public_idx` theo lenh Cypher o muc 9.1.

## 14) Lenh da duoc xac nhan chay trong moi truong hien tai

- `docker compose up -d` (thanh cong)
- `python test_engine.py` (thanh cong)
- Ingest nhanh toan bo `fast_track/*.json` qua `pipeline.main.process_file(...)` (thanh cong)

---

Neu ban muon, buoc tiep theo hop ly la minh co the refactor `app.py` va `batch_runner.py` de README co them muc "Web UI / Batch Runner (fully working)".
