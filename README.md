# 🚀 AI Digital Twin Recruitment Platform (SocialFi) - Backend 2.0

**Trạng thái:** ✅ Đã tái cấu trúc sang kiến trúc **Backend API-first (v2.0)**  
**Cập nhật:** 2026-03-20

---

## 🎯 Tổng quan

Dự án xây dựng nền tảng tuyển dụng bằng **AI Digital Twin + GraphRAG**, tập trung vào:

- **Ingestion pipeline** chuẩn hóa dữ liệu hồ sơ/tài liệu vào Neo4j.
- **Tìm kiếm ứng viên** dựa trên vector search (public profile).
- **Phỏng vấn Digital Twin** có kiểm soát phân quyền public/private theo relationship.
- **Xác thực người dùng** qua Supabase JWT + bảng bridge `vdme.users`.

> Phiên bản hiện tại là backend service độc lập. UI Streamlit v1 đã được tách lưu trữ tại thư mục `archive_v1/`.

---

## 🧱 Kiến trúc hệ thống v2.0

```text
[Client Apps / Frontend]
          |
          v
   FastAPI Backend (api/main.py)
          |
          +--> Auth + Profile Bridge (Supabase)
          +--> Ingestion Pipeline (pipeline/main.py)
          +--> Search Engine (MasterAgentEngine)
          +--> Interview Engine (DigitalTwinInterviewEngine)
          +--> Chat History Service
          |
          v
        Neo4j (Graph + Vector Index)
```

### Thành phần chính

- **API Layer**: `api/`
  - `auth.py` - đăng ký user qua Supabase Admin API.
  - `ingest.py` - upload file và gọi pipeline ingest.
  - `search.py` - tìm ứng viên (chỉ role Organization).
  - `interview.py` - Q&A Digital Twin (HTTP + WebSocket).
  - `graph.py` - trả graph nodes/edges cho client.
  - `chat.py` - lưu/lấy lịch sử hội thoại.
- **Domain Pipeline**: `pipeline/`
  - Parse -> Clean -> Extract -> Vectorize -> Ingest Neo4j.
  - Dual-ingest best-effort sang Supabase (không làm fail pipeline nếu lỗi).
- **Data Stores**:
  - Neo4j 5.26 (graph + vector index).
  - Supabase (auth + bảng `vdme.users`).

---

## 📁 Cấu trúc thư mục

```text
graphRAG/
├── api/
│   ├── main.py
│   ├── deps.py
│   └── routers/
├── pipeline/
├── scripts/
│   └── sql/
├── fast_track/
├── data_lake/
├── neo4j/
├── chromadb/
├── archive_v1/                # Di sản v1 (Streamlit)
│   ├── app.py
│   ├── README copy.md
│   └── README copy 2.md
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## 🛠️ Công nghệ sử dụng

- **Backend API**: FastAPI, Uvicorn
- **Graph DB**: Neo4j 5.26 (+ APOC, GDS)
- **Auth / User Profile Bridge**: Supabase
- **LLM/AI**: Cerebras, OpenAI
- **Embedding / NLP**: PhoBERT, Transformers, Sentence-Transformers
- **Parsing / ETL**: python-docx, docling, unstructured flow trong pipeline

---

## ✅ Yêu cầu hệ thống

- Python **3.10+**
- Docker + Docker Compose
- Neo4j chạy local qua `docker-compose.yml`
- Supabase project (để dùng auth + profile bridge)

---

## ⚙️ Cài đặt nhanh

### 1. Tạo môi trường và cài thư viện

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Khởi động Neo4j

```powershell
docker compose up -d
```

### 3. Tạo file `.env`

```env
# LLM
CEREBRAS_API_KEY=
CEREBRAS_MODEL=llama3.1-8b
OPENAI_API_KEY=
GROQ_API_KEY=

# Parser (Phase 1)
LLAMA_CLOUD_API_KEY=
PARSER_MIN_TEXT_LEN=200

# Neo4j
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password123

# Supabase
SUPABASE_URL=
SUPABASE_SERVICE_KEY=

# Optional (legacy/utility)
CHROMADB_HOST=localhost
CHROMADB_PORT=8000
NUTRIENT_API_KEY=
NUTRIENT_BASE_URL=https://api.nutrient.io/build

# Logging
LOG_LEVEL=INFO
```

### 4. Chạy API server

```powershell
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Health check:

```text
GET http://localhost:8000/health
```

---

## 🔐 Cơ chế xác thực

- API dùng **Bearer JWT** từ Supabase.
- Dependency `get_current_user()` sẽ:
  - verify token với Supabase Auth,
  - map user sang `vdme.users` để lấy `neo4j_id` và `role`.
- Role hiện tại:
  - `organization`
  - `personnel`

---

## 📡 API endpoints (v2.0)

### Auth

- `POST /auth/register`

### Ingestion

- `POST /ingest` (multipart file upload)

### Search

- `POST /search` (chỉ Organization)

### Interview

- `POST /interview`
- `WS /interview/ws`

### Graph

- `GET /graph?show_all=false`

### Chat

- `POST /chat/message`
- `GET /chat/history/{per_neo4j_id}`
- `POST /chat/history/{per_neo4j_id}`

---

## 🧠 Nghiệp vụ lõi

### 1) Ingestion Pipeline

- File hỗ trợ: `.pdf`, `.docx`, `.txt`, `.md`, `.json`
- JSON sẽ đi luồng ingest trực tiếp (bypass extract LLM).
- Document text đi qua:
  - Parse -> Clean -> Chunk -> Extract -> Merge -> Vectorize -> Neo4j ingest.

### 2) Candidate Search (MasterAgentEngine)

- Tìm ứng viên theo JD/query trên public vector space.
- Trả về danh sách score + summary + skills.

### 3) Digital Twin Interview

- Engine chỉ mở private context khi relationship:

```text
(:Organization)-[:CONNECTED_TO {status:'accepted'}]->(:Personnel)
```

- Nếu chưa accepted, câu trả lời ở **public mode**.

---

## 🧪 Kiểm thử

```powershell
python test_settings.py
python test_engine.py
python test_e2e_pipeline.py
```

---

## 🧰 Script tiện ích

- `check_models.py` - kiểm tra model khả dụng.
- `clear_neo4j.py` - xóa dữ liệu/constraints/index local Neo4j.
- `migrate_auth.py` - hỗ trợ migration auth dữ liệu cũ.
- `re_embedder.py` - re-embedding A/B test.
- `batch_runner.py` - xử lý batch ingest theo folder.

---

## 🧹 Cleanup v1 đã thực hiện

- Đã tạo `archive_v1/` tại root.
- Đã di chuyển UI cũ `app.py` vào `archive_v1/`.
- Đã di chuyển tài liệu README cũ liên quan v1 vào `archive_v1/`.
- Đã loại bỏ dependency Streamlit khỏi `requirements.txt`:
  - `streamlit`
  - `streamlit-shadcn-ui`
  - `streamlit-agraph`

---

## 📌 Ghi chú vận hành

- Backend v2.0 không phụ thuộc Streamlit.
- Frontend mới có thể tích hợp qua HTTP/WS API hiện tại.
- Nên thêm reverse proxy + TLS + rate limit khi triển khai production.

**Digital Twin Recruitment 2.0 đang ở trạng thái sẵn sàng để tích hợp Frontend mới và mở rộng production.** 🔥
