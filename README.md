# Digital Twin Recruitment Platform

Nền tảng tuyển dụng sử dụng GraphRAG kết hợp AI Digital Twin, cho phép tổ chức phỏng vấn ứng viên qua mô hình số trước khi gặp thực tế.

---

## Kiến trúc tổng quan

Hệ thống chia làm 4 thành phần chính:

```
graphRAG/
├── api/          ← FastAPI backend (REST + WebSocket)
├── pipeline/     ← Ingestion pipeline (parse → extract → ingest)
├── frontend/     ← Next.js 16 + React 19 (UI)
└── neo4j/        ← Neo4j 5.26 (Docker volume)
```

**Mô hình Dual-DB:**
- **Neo4j** lưu public graph, public embeddings và quan hệ Organization–Personnel phục vụ hybrid search và interview access control.
- **Supabase** lưu private profile vault, chat/schedule/notification data cùng chunk embeddings (pgvector) cho truy vấn ngữ nghĩa.

---

## Tech Stack

### Backend & Pipeline
| Layer | Công nghệ |
|-------|-----------|
| API Framework | FastAPI 2.0 |
| Graph DB | Neo4j 5.26 (Docker, APOC + GDS plugins) |
| Vector DB | Supabase (pgvector) |
| Embedding | PhoBERT-base-v2 (768 chiều) |
| LLM Extraction | OpenAI gpt-4o-mini (primary) / Cerebras (fallback) |
| Parser | LlamaParse → unstructured → Nutrient API (fallback chain) |
| Email | SMTP (Gmail App Password) |

### Frontend
| Layer | Công nghệ |
|-------|-----------|
| Framework | Next.js 16.2.1 + React 19 |
| Language | TypeScript 5 |
| Styling | Tailwind CSS v4 + ShadCN UI |
| State | Zustand + TanStack React Query v5 |
| Graph viz | ReactFlow 11 + Dagre layout |
| Form | React Hook Form + Zod |
| Auth | Supabase SSR |

---

## Cấu trúc thư mục chi tiết

```text
graphRAG/
├── api/
│   ├── main.py                 ← FastAPI app, CORS, router mount
│   ├── deps.py                 ← Dependency injection (DB session, auth)
│   ├── models/
│   │   └── scheduling.py       ← Pydantic models cho lịch hẹn
│   ├── routers/
│   │   ├── auth.py             ← Đăng ký / đăng nhập
│   │   ├── ingest.py           ← Upload file → pipeline
│   │   ├── search.py           ← Hybrid search
│   │   ├── interview.py        ← Digital Twin interview (HTTP + WS)
│   │   ├── graph.py            ← Graph data cho visualization
│   │   ├── chat.py             ← Lưu & lấy lịch sử chat
│   │   ├── availability.py     ← Personnel thiết lập lịch rảnh
│   │   ├── schedule.py         ← Đặt lịch phỏng vấn thực
│   │   └── notification.py     ← Quản lý thông báo
│   ├── services/
│   │   └── email_service.py    ← Gửi email thông báo (SMTP)
│   └── utils/
│
├── pipeline/
│   ├── main.py                 ← Orchestrator: process_file(), batch main()
│   ├── config.py               ← Settings (env vars, logger)
│   ├── schemas.py              ← RecruitmentNode schema
│   ├── parser.py               ← LlamaParse / unstructured / Nutrient
│   ├── cleaner.py              ← Làm sạch text tiếng Việt
│   ├── extractor.py            ← LLM extraction (JSON schema)
│   ├── vectorizer.py           ← PhoBERT embedding
│   ├── hybrid_query_engine.py  ← Jaccard graph (α=0.4) + Vector (β=0.6)
│   ├── neo4j_ingestion.py      ← Ghi node/relationship vào Neo4j
│   ├── supabase_ingestion.py   ← Dual-write sang Supabase (best-effort)
│   └── supabase_client.py      ← Supabase client wrapper
│
├── frontend/
│   └── src/
│       ├── app/
│       │   ├── (auth)/         ← Login / Register pages
│       │   ├── (dashboard)/
│       │   │   ├── search/     ← Tìm kiếm ứng viên
│       │   │   ├── interview/  ← Digital Twin interview UI
│       │   │   ├── graph/      ← Graph visualization
│       │   │   ├── schedule/   ← Quản lý lịch phỏng vấn
│       │   │   ├── availability/ ← Cài lịch rảnh (Personnel)
│       │   │   ├── notifications/ ← Trung tâm thông báo
│       │   │   └── profile/    ← Hồ sơ người dùng
│       │   └── profile/        ← Public profile view
│       ├── components/
│       │   ├── auth/           ← Form đăng nhập / đăng ký
│       │   ├── chat/           ← Chat UI
│       │   ├── graph/          ← ReactFlow graph components
│       │   ├── ingest/         ← Dropzone upload
│       │   ├── scheduling/     ← Lịch hẹn components
│       │   ├── search/         ← Kết quả tìm kiếm
│       │   ├── shared/         ← Header, Sidebar, Layout
│       │   └── ui/             ← ShadCN base components
│       ├── hooks/              ← Custom React hooks
│       ├── lib/                ← API client, utils
│       ├── store/              ← Zustand stores
│       └── types/              ← TypeScript types (+ openapi-typescript gen)
│
├── neo4j/
│   ├── data/                   ← Neo4j data volume
│   ├── logs/                   ← Neo4j logs volume
│   └── plugins/                ← APOC, GDS plugins
│
├── scripts/
│   ├── reextract_and_ingest.py ← Batch re-ingest theo type
│   ├── clean_all_data.py       ← Xóa toàn bộ data Supabase
│   ├── reembed_supabase.py     ← Re-embed chunks Supabase
│   └── sql/                    ← SQL migration files
│
├── fast_track/                 ← JSON batch (bypass LLM)
├── data_lake/                  ← File gốc (PDF, DOCX, ...)
├── archive_v1/                 ← Code phiên bản cũ
├── docker-compose.yml          ← Neo4j container
└── requirements.txt
```

---

## Pipeline Ingestion

```
File Input (.pdf / .docx / .txt / .md)
    ↓
[Parser]      LlamaParse → unstructured → Nutrient (fallback chain)
    ↓
[Cleaner]     Làm sạch text tiếng Việt
    ↓
[Chunker]     Chia chunk 7000 ký tự, overlap 400
    ↓
[Extractor]   LLM (gpt-4o-mini) → JSON schema (public/private data)
    ↓
[Merger]      Map-Reduce merge nhiều chunk → 1 node hoàn chỉnh
    ↓
[Vectorizer]  PhoBERT-base-v2 → 768d embedding
    ↓
[Neo4j]       Ingest public graph + embeddings
    ↓
[Supabase]    Dual-write private chunks (best-effort, non-fatal)
```

**Đặc biệt:** File `.json` bypass toàn bộ LLM để tiết kiệm chi phí.

---

## API Endpoints

### Auth
| Method | Path | Mô tả |
|--------|------|-------|
| POST | /auth/register | Đăng ký tài khoản |
| POST | /auth/login | Đăng nhập |

### Core
| Method | Path | Mô tả |
|--------|------|-------|
| POST | /ingest | Upload file → ingest pipeline |
| POST | /search | Hybrid search ứng viên (chỉ Organization) |
| POST | /interview | Digital Twin interview (HTTP) |
| WS | /interview/ws | Streaming interview qua WebSocket |
| GET | /graph | Graph data cho visualization |
| GET | /health | Health check |

### Chat
| Method | Path | Mô tả |
|--------|------|-------|
| POST | /chat/message | Lưu message |
| GET | /chat/history/{per_neo4j_id} | Lấy lịch sử chat |

### Scheduling
| Method | Path | Mô tả |
|--------|------|-------|
| PUT | /availability | Personnel thiết lập lịch rảnh |
| GET | /availability/{per_neo4j_id}/slots | Org xem slots khả dụng |
| POST | /schedule | Org đặt lịch phỏng vấn thực |
| GET | /schedule | Liệt kê lịch theo user |
| PATCH | /schedule/{schedule_id}/status | Confirm / cancel lịch |
| PATCH | /schedule/{schedule_id}/reschedule | Personnel đề xuất giờ khác |

### Notification
| Method | Path | Mô tả |
|--------|------|-------|
| GET | /notification | Lấy danh sách thông báo |
| GET | /notification/unread-count | Đếm thông báo chưa đọc |
| PATCH | /notification/{notification_id}/read | Đánh dấu đã đọc |
| PATCH | /notification/read-all | Đánh dấu toàn bộ đã đọc |

---

## Cài đặt & Chạy

### Yêu cầu
- Python 3.10+
- Node.js 18+
- Docker (cho Neo4j)
- Supabase account

### 1. Backend

```bash
# Clone và cài dependencies
git clone <repo_url>
cd graphRAG
pip install -r requirements.txt

# Tạo file .env (xem mẫu bên dưới)

# Khởi động Neo4j
docker-compose up -d

# Chạy API
uvicorn api.main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install

# Tạo file .env.local (xem mẫu bên dưới)

# Generate TypeScript types từ OpenAPI (cần API đang chạy)
npm run gen:types

# Chạy dev server
npm run dev
# → http://localhost:3000
```

### 3. Ingest data

```bash
# Setup Supabase schema
# Chạy SQL migration trong scripts/sql/

# Ingest
python scripts/reextract_and_ingest.py --type personnel
python scripts/reextract_and_ingest.py --type org
```

---

## Biến môi trường

### Backend `.env`
```env
# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password123

# Supabase
SUPABASE_URL=
SUPABASE_SERVICE_KEY=

# LLM
OPENAI_API_KEY=           # primary extractor
CEREBRAS_API_KEY=         # fallback extractor / interview LLM
CEREBRAS_MODEL=llama3.1-8b

# Parser
LLAMA_CLOUD_API_KEY=      # primary parser
PARSER_MIN_TEXT_LEN=200

# Email (SMTP)
DEMO_SENDER_EMAIL=
DEMO_SENDER_APP_PASSWORD=
DEMO_CALENDAR_EMAIL=
DEMO_RECIPIENT_EMAIL=

# Optional
NUTRIENT_API_KEY=
NUTRIENT_BASE_URL=https://api.nutrient.io/build
LOG_LEVEL=INFO
```

### Frontend `.env.local`
```env
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## Lệnh thường dùng

```bash
# Chạy test engine
python test_engine.py
# Expected: Tong: 4  |  PASS 4  |  FAIL 0  |  WARN 0

# Re-ingest toàn bộ data
# 1. Xóa Neo4j (Neo4j Browser):  MATCH (n) DETACH DELETE n
# 2. Xóa Supabase:
python scripts/clean_all_data.py
# 3. Re-ingest:
python scripts/reextract_and_ingest.py --type personnel
python scripts/reextract_and_ingest.py --type org

# Re-embed Supabase chunks
python scripts/reembed_supabase.py

# Xem log API
tail -f uvicorn.log
```

---

## Hybrid Search

Điểm tìm kiếm được tính theo công thức:

```
score = α × jaccard_graph_score + β × vector_similarity
      = 0.4 × jaccard + 0.6 × cosine(PhoBERT)
```

- **Jaccard graph score**: dựa trên quan hệ trong Neo4j graph.
- **Vector similarity**: cosine similarity giữa embedding ứng viên và query.

---

## Phát triển tiếp theo

- [ ] Google Calendar integration cho scheduling
- [ ] Multi-language support (EN/VI)
- [ ] Notification push real-time (WebSocket)
- [ ] Admin dashboard: thống kê, quản lý user

## kích hoạt environment
.venv\Scripts\activate

## API backend
npm run dev