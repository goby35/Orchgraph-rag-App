# Digital Twin Recruitment Platform

GraphRAG-powered recruitment platform với AI Digital Twin cho phép
tổ chức phỏng vấn ứng viên qua mô hình số trước khi gặp thực tế.

## Kiến trúc tổng quan

Hệ thống dùng mô hình dual-DB:

- Neo4j lưu public graph, public embeddings và relationship Organization-Personnel để phục vụ search và interview access control.
- Supabase lưu private profile vault, chat/schedule/notification data, cùng chunk embeddings (pgvector) cho truy vấn ngữ nghĩa.

FastAPI backend ở api/main.py điều phối toàn bộ endpoint nghiệp vụ.
Pipeline ingestion ở pipeline/main.py xử lý file đầu vào theo chuỗi parse -> clean -> extract -> merge -> vectorize -> ingest Neo4j, sau đó dual-write sang Supabase theo cơ chế best-effort.

## Tech Stack

### Backend
| Layer | Technology |
|-------|-----------|
| API | FastAPI |
| Graph DB | Neo4j 5.x |
| Vector DB | Supabase (pgvector) |
| Embedding | PhoBERT-base-v2 (768d) |
| LLM Extraction | OpenAI gpt-4o-mini / Cerebras (fallback) |
| Parser | LlamaParse -> unstructured -> Nutrient API (fallback) |

### Data Pipeline
- 3-layer extraction: Regex anchors -> LLM structured output (JSON schema) -> Merge nhiều chunk + normalize schema.
- Dual-write ingestion: Neo4j public graph + Supabase private chunks.
- Hybrid search: Jaccard graph score (alpha=0.4) + Vector similarity (beta=0.6).

## Cấu trúc thư mục

```text
graphRAG/
|- api/
|  |- deps.py
|  |- main.py
|  |- models/
|  |- routers/
|  |- services/
|  `- utils/
|- pipeline/
|  |- main.py
|  |- parser.py
|  |- extractor.py
|  |- vectorizer.py
|  |- hybrid_query_engine.py
|  |- neo4j_ingestion.py
|  `- supabase_ingestion.py
|- scripts/
|  |- reextract_and_ingest.py
|  |- clean_all_data.py
|  |- reembed_supabase.py
|  `- sql/
|- fast_track/
|- data_lake/
|- neo4j/
|- chromadb/
|- archive_v1/
|- docker-compose.yml
|- requirements.txt
`- README.md
```

## Cài đặt

### Yêu cầu
- Python 3.10+
- Neo4j 5.x (local hoặc AuraDB)
- Supabase account

### Các bước
```bash
# 1. Clone và cài dependencies
git clone <repo_url>
cd graphRAG
pip install -r requirements.txt

# 2. Tạo và điền env
# Repo hiện chưa có .env.example, tạo file .env thủ công theo mẫu ở phần "Biến môi trường"

# 3. Setup Neo4j constraints/index
# API sẽ tự tạo index cơ bản khi ingest; có thể chuẩn bị thêm script Cypher riêng nếu cần

# 4. Setup Supabase schema
# Chạy SQL migration trong scripts/sql/ (ví dụ: phase_0_25_vdme_bridge_upgrade.sql)

# 5. Chạy ingestion
python scripts/reextract_and_ingest.py --type personnel
python scripts/reextract_and_ingest.py --type org

# 6. Khởi động API
uvicorn api.main:app --reload --port 8000
```

## Biến môi trường
```env
# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=

# Supabase
SUPABASE_URL=
SUPABASE_SERVICE_KEY=

# LLM
OPENAI_API_KEY=           # primary extractor
CEREBRAS_API_KEY=         # fallback extractor / interview
CEREBRAS_MODEL=llama3.1-8b

# Parser
LLAMA_CLOUD_API_KEY=      # primary parser
PARSER_MIN_TEXT_LEN=200

# Email (demo)
DEMO_SENDER_EMAIL=
DEMO_SENDER_APP_PASSWORD=
DEMO_CALENDAR_EMAIL=
DEMO_RECIPIENT_EMAIL=

# Optional utility
NUTRIENT_API_KEY=
NUTRIENT_BASE_URL=https://api.nutrient.io/build
LOG_LEVEL=INFO
```

## API Endpoints

### Core
| Method | Path | Mô tả |
|--------|------|-------|
| POST | /auth/register | Đăng ký tài khoản |
| POST | /ingest | Upload file -> ingest pipeline |
| POST | /search | Tìm ứng viên (hybrid search, chỉ Organization) |
| POST | /interview | Digital Twin interview (HTTP) |
| GET | /graph | Graph data cho visualization |

### Scheduling (mới)
| Method | Path | Mô tả |
|--------|------|-------|
| PUT | /availability | Personnel thiết lập lịch rảnh |
| GET | /availability/{per_neo4j_id}/slots | Org xem slots available |
| POST | /schedule | Org đặt lịch phỏng vấn thực |
| PATCH | /schedule/{schedule_id}/status | Confirm / cancel lịch |
| PATCH | /schedule/{schedule_id}/reschedule | Personnel đề xuất giờ khác |
| GET | /notification | Lấy danh sách thông báo |

### Bổ sung đang có trong code
| Method | Path | Mô tả |
|--------|------|-------|
| WS | /interview/ws | Streaming interview qua WebSocket |
| POST | /chat/message | Lưu message chat |
| GET, POST | /chat/history/{per_neo4j_id} | Lấy lịch sử chat |
| GET | /schedule | Liệt kê lịch theo user |
| PATCH | /notification/{notification_id}/read | Đánh dấu 1 thông báo đã đọc |
| PATCH | /notification/read-all | Đánh dấu toàn bộ đã đọc |
| GET | /notification/unread-count | Đếm thông báo chưa đọc |
| GET | /health | Health check |

## Chạy test
```bash
python test_engine.py
# Expected summary: Tong: 4  |  PASS 4  |  FAIL 0  |  WARN 0
```

## Re-ingest toàn bộ data
```bash
# Xoa data cu Neo4j (Neo4j Browser)
# MATCH (n) DETACH DELETE n

# Xoa Supabase
python scripts/clean_all_data.py

# Re-ingest
python scripts/reextract_and_ingest.py --type personnel
python scripts/reextract_and_ingest.py --type org
```

## Phát triển tiếp theo

- [ ] Next.js frontend (scheduling UI, chat UI, notification)
- [ ] Google Calendar integration
- [ ] Multi-language support (EN/VI)
