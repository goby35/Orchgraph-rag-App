# ORCHGRAPH-RAG: MÔ HÌNH ĐA TÁC TỬ ĐIỀU PHỐI BẰNG ĐỒ THỊ CHO TUYỂN DỤNG THÔNG MINH VÀ TRUY XUẤT TRI THỨC CÁ NHÂN HÓA

Nền tảng tuyển dụng sử dụng **GraphRAG kết hợp AI Digital Twin**, cho phép tổ chức phỏng vấn ứng viên qua mô hình số trước khi gặp thực tế. Hệ thống xử lý CV tiếng Việt, trích xuất tri thức có cấu trúc, lưu trữ vào đồ thị tri thức (Neo4j) và cơ sở dữ liệu vector (Supabase/pgvector), phục vụ tìm kiếm hybrid và phỏng vấn Digital Twin qua streaming LLM.

---

## Kiến trúc tổng quan

```
graphRAG/
├── api/          ← FastAPI backend (REST + WebSocket)
├── pipeline/     ← Ingestion pipeline (parse → clean → extract → vectorize → ingest)
├── frontend/     ← Next.js 16 + React 19 (UI)
├── scripts/      ← Tiện ích vận hành + bộ đánh giá đầy đủ
├── data_eval/    ← Dataset đánh giá (ground truth, JD, QA, cache embedding)
├── results/      ← Kết quả đánh giá RAGAS hệ thống
└── neo4j/        ← Neo4j 5.26 (Docker volume)
```

**Mô hình Dual-DB:**
- **Neo4j** lưu public graph, multi-model embeddings và quan hệ Organization–Personnel phục vụ hybrid search và interview access control.
- **Supabase** lưu private profile vault, chat/schedule/notification data cùng chunk embeddings (pgvector) cho truy vấn ngữ nghĩa.

---

## Tech Stack

### Backend & Pipeline
| Layer | Công nghệ |
|-------|-----------|
| API Framework | FastAPI (Python 3.10+) |
| Graph DB | Neo4j 5.26 (Docker, APOC + GDS plugins) |
| Vector DB | Supabase (pgvector) |
| Embedding (primary) | PhoBERT-base-v2 (768d) |
| Embedding (eval) | multilingual-E5-base · GTE-multilingual-base · BGE-M3 |
| LLM Extraction | OpenAI gpt-4o-mini (primary) / Cerebras Llama3.1-8b (fallback) |
| Parser | LlamaParse → unstructured → Nutrient API (fallback chain) |
| Email | SMTP (Gmail App Password) |

### Frontend
| Layer | Công nghệ |
|-------|-----------|
| Framework | Next.js 16.2.1 + React 19.2.4 |
| Language | TypeScript 5 |
| Styling | Tailwind CSS v4 + ShadCN UI v4 |
| State | Zustand v5 + TanStack React Query v5 |
| Graph viz | ReactFlow 11 + Dagre layout |
| Form | React Hook Form v7 + Zod v4 |
| Auth | Supabase SSR (`@supabase/ssr`) |
| HTTP | Axios + openapi-typescript (type gen) |
| Toast | Sonner |
| Icons | Lucide React |

---

## Cấu trúc thư mục chi tiết

```text
graphRAG/
│
├── api/                              ← FastAPI backend
│   ├── main.py                       ← App entry: CORS, router mount, lifespan
│   ├── deps.py                       ← Dependency injection (Supabase client, auth guard)
│   ├── models/
│   │   └── scheduling.py             ← Pydantic models cho lịch hẹn (slot, schedule)
│   ├── routers/
│   │   ├── auth.py                   ← POST /auth/register · /auth/login
│   │   ├── ingest.py                 ← POST /ingest (upload file → pipeline)
│   │   ├── search.py                 ← POST /search (hybrid search, org-only)
│   │   ├── interview.py              ← POST /interview · WS /interview/ws (Digital Twin)
│   │   ├── graph.py                  ← GET /graph (graph data cho ReactFlow)
│   │   ├── chat.py                   ← POST /chat/message · GET /chat/history/{id}
│   │   ├── availability.py           ← PUT /availability · GET /availability/{id}/slots
│   │   ├── schedule.py               ← CRUD lịch phỏng vấn thực (POST/GET/PATCH)
│   │   └── notification.py           ← GET/PATCH thông báo
│   ├── services/
│   │   └── email_service.py          ← Gửi email xác nhận lịch qua SMTP
│   └── utils/
│       └── supabase_helpers.py       ← Helper: sb_val(), coerce_bool()
│
├── pipeline/                         ← Ingestion pipeline
│   ├── main.py                       ← Orchestrator: process_file(), batch main()
│   ├── config.py                     ← Settings (env vars, Pydantic BaseSettings, logger)
│   ├── schemas.py                    ← RecruitmentNode Pydantic schema (public/private split)
│   ├── parser.py                     ← LlamaParse → unstructured → Nutrient fallback chain
│   ├── cleaner.py                    ← Làm sạch text tiếng Việt (regex, diacritics)
│   ├── extractor.py                  ← LLM extraction (gpt-4o-mini, JSON schema, map-reduce)
│   ├── vectorizer.py                 ← PhoBERT-base-v2 multi-field embedding (768d)
│   ├── hybrid_query_engine.py        ← Jaccard graph (α=0.4) + Vector cosine (β=0.6)
│   ├── neo4j_ingestion.py            ← Ghi Personnel/Organization node + relationship
│   ├── supabase_ingestion.py         ← Dual-write private chunks (pgvector, best-effort)
│   ├── supabase_client.py            ← Supabase client singleton
│   └── chat_service.py               ← Lưu/lấy lịch sử chat từ Supabase
│
├── frontend/                         ← Next.js App Router
│   └── src/
│       ├── app/
│       │   ├── (auth)/               ← /login · /register
│       │   ├── (dashboard)/
│       │   │   ├── layout.tsx        ← Dashboard layout (Sidebar + Header)
│       │   │   ├── search/           ← Tìm kiếm ứng viên hybrid
│       │   │   ├── interview/        ← Digital Twin interview UI (streaming)
│       │   │   ├── graph/            ← ReactFlow graph visualization
│       │   │   ├── schedule/         ← Quản lý lịch phỏng vấn thực
│       │   │   ├── availability/     ← Personnel cài lịch rảnh
│       │   │   ├── notifications/    ← Trung tâm thông báo (realtime)
│       │   │   └── profile/          ← Hồ sơ người dùng
│       │   ├── profile/              ← Public profile view
│       │   ├── search/               ← Public search page
│       │   ├── api/auth/callback/    ← Supabase OAuth callback route
│       │   ├── globals.css           ← Tailwind v4 base styles
│       │   ├── layout.tsx            ← Root layout (QueryProvider, Toaster)
│       │   └── page.tsx              ← Landing / redirect
│       ├── components/
│       │   ├── auth/                 ← LoginForm, RegisterForm
│       │   ├── chat/                 ← ChatBubble, ChatInput (streaming)
│       │   ├── graph/                ← PersonnelNode, OrgNode, GraphCanvas (ReactFlow)
│       │   ├── ingest/               ← FileDropzone, IngestProgress
│       │   ├── scheduling/           ← AvailabilityForm, ScheduleCard, SlotPicker
│       │   ├── search/               ← SearchBar, SearchResultCard
│       │   ├── shared/               ← Header, Sidebar, Layout, LoadingSpinner
│       │   └── ui/                   ← ShadCN base components (Button, Dialog, etc.)
│       ├── hooks/
│       │   ├── useDigitalTwinChat.ts ← WebSocket streaming interview hook
│       │   ├── useIngestStatus.ts    ← Polling ingest status
│       │   └── useRealtimeNotifications.ts ← Supabase Realtime notifications
│       ├── lib/
│       │   ├── api/                  ← Typed Axios wrappers
│       │   │   ├── client.ts         ← Axios instance (baseURL, interceptors)
│       │   │   ├── graph.ts          ← getGraphData()
│       │   │   ├── ingest.ts         ← uploadFile(), getIngestStatus()
│       │   │   ├── interview.ts      ← startInterview(), WebSocket helpers
│       │   │   ├── notification.ts   ← getNotifications(), markRead()
│       │   │   ├── schedule.ts       ← CRUD schedule API calls
│       │   │   ├── search.ts         ← hybridSearch()
│       │   │   └── index.ts          ← Re-export
│       │   ├── supabase/             ← Supabase client (browser + server)
│       │   ├── utils.ts              ← cn() class merge
│       │   └── variants.ts           ← CVA component variants
│       ├── store/
│       │   ├── auth.store.ts         ← Zustand: user session
│       │   └── ui.store.ts           ← Zustand: sidebar open state
│       ├── types/                    ← TypeScript types (+ openapi-typescript gen)
│       └── middleware.ts             ← Supabase session refresh middleware
│
├── scripts/                          ← Tiện ích vận hành
│   ├── reextract_and_ingest.py       ← Batch re-ingest theo type (personnel/org)
│   ├── clean_all_data.py             ← Xóa toàn bộ data Supabase
│   ├── reembed_supabase.py           ← Re-embed chunks Supabase
│   ├── backfill_embeddings.py        ← Backfill multi-model embeddings vào Neo4j
│   ├── backfill_graph_nodes.py       ← Backfill node thiếu trường
│   ├── migrate_users_to_supabase.py  ← Migrate user auth sang Supabase
│   ├── eval/                         ← Bộ đánh giá pipeline (6 module)
│   │   ├── run_all.py                ← Orchestrator: chạy toàn bộ hoặc từng bước
│   │   ├── eval_cleaner.py           ← Đánh giá cleaner (noise removal, VI ratio)
│   │   ├── eval_extractor.py         ← Đánh giá extractor (coverage, split acc, halluc)
│   │   ├── eval_embeddings.py        ← So sánh 4 embedding models (MRR, Recall, NDCG)
│   │   ├── eval_graph.py             ← Kiểm tra chất lượng Neo4j graph (completeness)
│   │   ├── eval_ragas.py             ← RAGAS eval: RAG / GraphRAG / Hybrid / DigitalTwin
│   │   ├── eval_privacy.py           ← Kiểm tra rò rỉ dữ liệu private (4 scenario)
│   │   ├── generate_draft_gt.py      ← Auto-generate draft ground truth từ CV thật
│   │   ├── qa_audit_claude.py        ← QA audit ground truth bằng Claude API
│   │   ├── visualize_eval.py         ← Sinh biểu đồ PNG từ kết quả eval
│   │   ├── utils.py                  ← save_json(), mean(), std(), print_table()
│   │   └── results/                  ← Kết quả eval từng module
│   │       ├── cleaner_eval.json
│   │       ├── embedding_eval.json
│   │       ├── extractor_eval.json
│   │       └── privacy_eval.json
│   └── sql/                          ← Schema migrations Supabase
│       ├── phase_0_25_vdme_bridge_upgrade.sql
│       ├── phase_0_26_chunk_gte_bge_backfill.sql
│       └── phase_0_27_chunk_e5_column.sql
│
├── data_eval/                        ← Dataset đánh giá
│   ├── ground_truth.json             ← Ground truth curated (25 CV + JD queries)
│   ├── ground_truth_corrected.json   ← Ground truth sau QA audit
│   ├── ground_truth_draft.json       ← Draft auto-generated
│   ├── jd_dataset.json               ← 24 JD queries với relevant_personnel
│   ├── qa_dataset.json               ← QA pairs cho RAGAS
│   ├── privacy_attacks.json          ← 12 câu tấn công privacy (4 scenario)
│   ├── qa_audit.log                  ← Log QA audit bởi Claude
│   ├── emb_cache_bge_m3.json         ← Cache embedding BGE-M3 (1.2 MB)
│   ├── emb_cache_gte_multilingual.json ← Cache embedding GTE (934 KB)
│   ├── emb_cache_multilingual_e5.json  ← Cache embedding E5 (933 KB)
│   └── cv_synthetic/                 ← CV tổng hợp dùng cho eval
│
├── results/                          ← Kết quả RAGAS hệ thống
│   ├── ragas_eval.json               ← RAG / GraphRAG / Hybrid (8 câu hỏi)
│   ├── ragas_digital_twin.json       ← Digital Twin RAGAS (subset)
│   ├── ragas_answers_RAG.json        ← Raw answers RAG
│   ├── ragas_answers_GraphRAG.json   ← Raw answers GraphRAG
│   ├── ragas_answers_Hybrid.json     ← Raw answers Hybrid
│   └── ragas_answers_digital_twin_DigitalTwin.json ← Raw answers Digital Twin
│
├── neo4j/
│   ├── data/                         ← Neo4j data volume (Docker mount)
│   ├── logs/                         ← Neo4j logs volume
│   └── plugins/                      ← APOC, GDS plugins
│
├── data_lake/                        ← File CV gốc (PDF, DOCX, ...)
├── fast_track/                       ← JSON batch (bypass LLM parsing)
├── archive_v1/                       ← Code phiên bản cũ (lưu trữ)
├── docker-compose.yml                ← Neo4j container definition
├── requirements.txt                  ← Python dependencies
├── batch_runner.py                   ← Batch job runner (parallel ingestion)
├── final_ingestion.py                ← Script ingestion cuối (production)
├── re_embedder.py                    ← Re-embed toàn bộ Personnel trong Neo4j
├── test_engine.py                    ← E2E test engine (4 test cases)
└── test_e2e_pipeline.py              ← Integration test pipeline end-to-end
```

---

## Pipeline Ingestion

```
File Input (.pdf / .docx / .txt / .md / .json)
    ↓
[Parser]      LlamaParse → unstructured → Nutrient API (fallback chain)
    ↓
[Cleaner]     Làm sạch text tiếng Việt (regex noise, diacritics)
    ↓
[Chunker]     Chia chunk 7000 ký tự, overlap 400
    ↓
[Extractor]   LLM (gpt-4o-mini) → JSON schema (public/private split)
              Map-Reduce: nhiều chunk → 1 node hoàn chỉnh
    ↓
[Vectorizer]  PhoBERT-base-v2 → 768d embedding (multi-field)
    ↓
[Neo4j]       Ghi Personnel/Organization node + CONNECTED_TO relationship
    ↓
[Supabase]    Dual-write private chunks + pgvector (best-effort, non-fatal)
```

**Đặc biệt:** File `.json` bypass toàn bộ LLM extraction để tiết kiệm chi phí.

---

## API Endpoints

### Auth
| Method | Path | Mô tả |
|--------|------|-------|
| POST | `/auth/register` | Đăng ký tài khoản (org/personnel) |
| POST | `/auth/login` | Đăng nhập, trả JWT |

### Core
| Method | Path | Mô tả |
|--------|------|-------|
| POST | `/ingest` | Upload file → ingest pipeline |
| POST | `/search` | Hybrid search ứng viên (org-only, α=0.4 Jaccard + β=0.6 vector) |
| POST | `/interview` | Digital Twin interview (HTTP, single turn) |
| WS | `/interview/ws` | Streaming interview qua WebSocket |
| GET | `/graph` | Graph data cho ReactFlow visualization |
| GET | `/health` | Health check |

### Chat
| Method | Path | Mô tả |
|--------|------|-------|
| POST | `/chat/message` | Lưu message vào Supabase |
| GET | `/chat/history/{per_neo4j_id}` | Lấy lịch sử chat theo persona |

### Scheduling
| Method | Path | Mô tả |
|--------|------|-------|
| PUT | `/availability` | Personnel thiết lập lịch rảnh + blocked dates |
| GET | `/availability/{per_neo4j_id}/slots` | Org xem slots khả dụng |
| POST | `/schedule` | Org đặt lịch phỏng vấn thực |
| GET | `/schedule` | Liệt kê lịch theo user (role-based filter) |
| PATCH | `/schedule/{schedule_id}/status` | Confirm / cancel lịch |
| PATCH | `/schedule/{schedule_id}/reschedule` | Personnel đề xuất giờ khác |

### Notification
| Method | Path | Mô tả |
|--------|------|-------|
| GET | `/notification` | Lấy danh sách thông báo |
| GET | `/notification/unread-count` | Đếm thông báo chưa đọc |
| PATCH | `/notification/{notification_id}/read` | Đánh dấu đã đọc |
| PATCH | `/notification/read-all` | Đánh dấu toàn bộ đã đọc |

---

## Kết quả Đánh giá (Evaluation Results)

### Neo4j Graph Quality (`graph_eval.json`)
| Metric | Giá trị |
|--------|---------|
| Tổng Personnel nodes | 56 |
| Có name | 100% |
| Có skills | 100% |
| Có summary | 100% |
| Có embedding | 98.21% |
| Có availability | 98.21% |
| Orphan rate | 1.79% |
| Unique skills | 559 |
| Avg skills/person | 22.46 |
| CONNECTED_TO relationships | 10 (6 accepted, 4 pending) |

### Embedding Model Comparison (`embedding_eval.json`)
Đánh giá trên 24 JD queries, corpus 56 Personnel từ Neo4j:

| Model | MRR@5 | Recall@5 | Recall@10 | NDCG@5 | Avg time (ms) |
|-------|-------|----------|-----------|--------|---------------|
| **GTE-multilingual** ⭐ | **0.7583** | **0.4208** | **0.4583** | **0.4855** | 239 |
| multilingual-E5 | 0.7425 | 0.4125 | 0.4354 | 0.4756 | 208 |
| BGE-M3 | 0.6937 | 0.3887 | 0.4513 | 0.4418 | 561 |
| PhoBERT-base-v2 | 0.1371 | 0.1050 | 0.1425 | 0.0846 | 175 |

> **Kết luận:** GTE-multilingual đạt hiệu năng tốt nhất. PhoBERT kém vì thiếu cross-lingual alignment với JD text.

### Extractor Quality (`extractor_eval.json`)
Đánh giá trên 25 CV thật (gpt-4o-mini):

| Metric | Giá trị |
|--------|---------|
| Avg field coverage (public) | 70.0% |
| Avg field coverage (private) | 65.6% |
| Avg Public/Private split accuracy | 82.4% |
| Avg hallucination candidates | 8.0% |
| Avg extraction time | 8.15s/CV |
| Trường có coverage 100% | full_name, summary, skills |
| Trường có coverage thấp nhất | is_available (0%), cultural_tags (12%) |

### Cleaner Quality (`cleaner_eval.json`)
Đánh giá trên 30 CV

> Vietnamese ratio ổn định sau cleaning → cleaner không làm mất diacritics.

### Privacy Protection (`privacy_eval.json`)
12 câu tấn công trên 4 scenario (direct / indirect / jailbreak / confusion):

| Scenario | Queries | Leaked | Leakage Rate |
|----------|---------|--------|--------------|
| Direct | 3 | 0 | **0%** |
| Indirect | 3 | 0 | **0%** |
| Jailbreak | 3 | 0 | **0%** |
| Confusion | 3 | 0 | **0%** |
| **Total** | **12** | **0** | **0% (Secure rate: 100%)** |

### RAGAS System Evaluation (`results/ragas_eval.json`)


> RAGAS scores thấp do bộ câu hỏi nhỏ (8 câu); Digital Twin được đánh giá trên subset khác.

---

## Cài đặt & Chạy

### Yêu cầu
- Python 3.10+
- Node.js 18+
- Docker (cho Neo4j)
- Supabase account (free tier đủ)

### 1. Clone & cài backend

```bash
git clone <repo_url>
cd graphRAG
pip install -r requirements.txt
cp .env.example .env   # Điền các API keys (xem phần Biến môi trường)
```

### 2. Khởi động Neo4j

```bash
docker-compose up -d
# Neo4j Browser: http://localhost:7474
# Bolt: bolt://localhost:7687
```

### 3. Chạy API

```bash
# Kích hoạt venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux/macOS

uvicorn api.main:app --reload --port 8000
# Swagger UI: http://localhost:8000/docs
```

### 4. Frontend

```bash
cd frontend
npm install

# Tạo .env.local (xem mẫu bên dưới)

# Generate TypeScript types từ OpenAPI (cần API đang chạy)
npm run gen:types

# Chạy dev server
npm run dev
# → http://localhost:3000
```

### 5. Ingest data

```bash
# Setup Supabase schema: chạy SQL migrations trong scripts/sql/ (theo thứ tự phase)

# Ingest CV Personnel
python scripts/reextract_and_ingest.py --type personnel

# Ingest Organization profiles
python scripts/reextract_and_ingest.py --type org
```

### 6. Deploy backend lên Modal

```bash
# Tạo secret group (chạy 1 lần)
modal secret create orchgraph-secrets \
    NEO4J_URI=... \
    NEO4J_USER=... \
    NEO4J_PASSWORD=... \
    SUPABASE_URL=... \
    SUPABASE_SERVICE_KEY=... \
    OPENAI_API_KEY=... \
    ANTHROPIC_API_KEY=... \
    CEREBRAS_API_KEY=... \
    LLAMA_CLOUD_API_KEY=... \
    DEMO_SENDER_EMAIL=... \
    DEMO_SENDER_APP_PASSWORD=...

# Lần đầu: cache models
modal run modal_app.py::download_models

# Deploy
modal deploy modal_app.py

# Xem logs
modal app logs orchgraph-rag

# Health check sau deploy
python check_modal_health.py https://<username>--orchgraph-rag.modal.run
```

### WebSocket Test (sau deploy)

```python
# test_ws.py (chạy từ client)
import asyncio
import json
import websockets

async def test_interview_ws():
    """Test WebSocket streaming interview endpoint."""
    modal_url = input("Nhập Modal URL (e.g., https://username--orchgraph-rag.modal.run): ").strip()
    ws_url = modal_url.replace("https://", "wss://").replace("http://", "ws://")
    ws_url += "/interview/ws"
    
    try:
        async with websockets.connect(ws_url, ping_interval=20) as websocket:
            print("✓ WebSocket connected")
            
            # Gửi yêu cầu interview (định dạng phụ thuộc api/routers/interview.py)
            interview_request = {
                "personnel_neo4j_id": "p001",
                "jd_text": "Senior Python Engineer seeking 5+ years experience"
            }
            
            await websocket.send(json.dumps(interview_request))
            print("→ Request sent")
            
            # Nhận streaming response
            while True:
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=30)
                    print(f"← {response[:100]}...")  # Print first 100 chars
                except asyncio.TimeoutError:
                    print("(No more messages - stream ended)")
                    break
                    
    except Exception as e:
        print(f"✗ Connection error: {e}")

if __name__ == "__main__":
    asyncio.run(test_interview_ws())
```

```bash
# Hoặc dùng wscat (npm install -g wscat)
wscat -c wss://<username>--orchgraph-rag.modal.run/interview/ws
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
OPENAI_API_KEY=           # primary extractor (gpt-4o-mini)
CEREBRAS_API_KEY=         # fallback extractor + interview LLM
CEREBRAS_MODEL=llama3.1-8b

# Parser
LLAMA_CLOUD_API_KEY=      # primary parser (LlamaParse)
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

# ── Re-ingest toàn bộ ──────────────────────────────────────────────────────
# 1. Xóa Neo4j (Neo4j Browser): MATCH (n) DETACH DELETE n
# 2. Xóa Supabase:
python scripts/clean_all_data.py
# 3. Re-ingest:
python scripts/reextract_and_ingest.py --type personnel
python scripts/reextract_and_ingest.py --type org

# ── Embedding ───────────────────────────────────────────────────────────────
# Re-embed Supabase chunks
python scripts/reembed_supabase.py

# Backfill multi-model embeddings vào Neo4j (E5, GTE, BGE-M3)
python scripts/backfill_embeddings.py

# ── Evaluation ──────────────────────────────────────────────────────────────
# Chạy toàn bộ evaluation suite
python scripts/eval/run_all.py

# Chạy từng step riêng lẻ
python scripts/eval/run_all.py cleaner
python scripts/eval/run_all.py extractor
python scripts/eval/run_all.py embedding
python scripts/eval/run_all.py graph
python scripts/eval/run_all.py ragas
python scripts/eval/run_all.py privacy

# Sinh biểu đồ từ kết quả eval
python scripts/eval/visualize_eval.py

# ── Tiện ích khác ───────────────────────────────────────────────────────────
# Xem log API
tail -f uvicorn.log

# Xóa Neo4j trực tiếp (Cypher)
# MATCH (n) DETACH DELETE n
```

---

## Hybrid Search

Điểm tìm kiếm được tính theo công thức:

```
score = α × jaccard_graph_score + β × vector_similarity
      = 0.4 × jaccard + 0.6 × cosine(PhoBERT)
```

- **Jaccard graph score**: Dựa trên kỹ năng trùng khớp trong Neo4j graph (set intersection).
- **Vector similarity**: Cosine similarity giữa embedding ứng viên và embedding query JD.

---

## Evaluation Suite

Bộ đánh giá hoàn chỉnh trong `scripts/eval/`, chạy qua `run_all.py`:

| Module | Mô tả | Output |
|--------|-------|--------|
| `eval_cleaner` | Đánh giá noise removal, VI char ratio | `cleaner_eval.json` |
| `eval_extractor` | Field coverage, public/private split, hallucination | `extractor_eval.json` |
| `eval_embeddings` | MRR@5, Recall@5/10, NDCG@5 cho 4 embedding models | `embedding_eval.json` |
| `eval_graph` | Node completeness, skill stats, orphan rate | `graph_eval.json` |
| `eval_ragas` | RAGAS metrics: faithfulness, relevancy, precision, recall, correctness | `ragas_eval.json` |
| `eval_privacy` | Privacy leakage test (4 attack scenarios) | `privacy_eval.json` |
| `generate_draft_gt` | Auto-generate ground truth draft từ CV + pipeline | `ground_truth_draft.json` |
| `qa_audit_claude` | QA audit ground truth bằng Claude API | `qa_audit.log` |
| `visualize_eval` | Sinh dashboard PNG từ kết quả eval | `graph_eval_dashboard.png` |

---

## Phát triển tiếp theo

- [ ] Nâng cấp embedding sang GTE-multilingual (thay PhoBERT trong production)
- [ ] Google Calendar integration cho scheduling
- [ ] Multi-language support (EN/VI)
- [ ] Notification push real-time qua WebSocket
- [ ] Admin dashboard: thống kê, quản lý user
- [ ] Tăng bộ RAGAS eval lên 50+ câu hỏi

---

## Ghi chú kích hoạt môi trường

```bash
# Backend
.venv\Scripts\activate
uvicorn api.main:app --reload --port 8000

# Frontend
cd frontend && npm run dev
```
npm run build
npm run start

Lệnh	Mục đích
npm run prod	Production: Build + run frontend, run backend
npm run dev	Development: Frontend dev server + backend reload
npm run prod:backend	Chỉ chạy backend production
npm run prod:frontend	Chỉ build + chạy frontend production