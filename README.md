# ORCHGRAPH-RAG

Nen tang tuyen dung thong minh su dung GraphRAG + AI Digital Twin cho CV tieng Viet, voi mo hinh dual-database:
- Neo4j luu do thi tri thuc public + relationship Organization-Personnel + vector index.
- Supabase luu private vault, lich chat, lich hen, notification, va chunk embeddings.

## 1. Tong quan kien truc

```text
graphRAG/
|- api/                # FastAPI backend (REST + WebSocket)
|- pipeline/           # Ingestion + hybrid retrieval + interview engine
|- frontend/           # Next.js 16 (App Router)
|- scripts/            # Migration, backfill, eval utilities
|- data_eval/          # Dataset danh gia
|- results/            # Ket qua danh gia
|- neo4j/              # Neo4j docker volumes/plugins
`- docker-compose.yml  # Neo4j local
```

## 2. Tech stack (thuc te trong code)

### Backend / Pipeline
- Python, FastAPI, Uvicorn
- Neo4j 5.x (co vector index)
- Supabase (Auth + Postgres + Realtime)
- Multi-embedding:
  - vinai/phobert-base-v2
  - Alibaba-NLP/gte-multilingual-base (active mac dinh)
  - intfloat/multilingual-e5-base
  - BAAI/bge-base-en-v1.5
- LLM extraction: OpenAI `gpt-4o-mini` (fallback Cerebras)
- Parser fallback chain: LlamaParse -> unstructured -> Nutrient API

### Frontend
- Next.js `16.2.1`, React `19.2.4`, TypeScript 5
- Tailwind CSS v4 + shadcn/ui
- Zustand + TanStack Query
- React Flow + react-force-graph-2d

## 3. Cac module chinh

### API (`api/main.py`)
- Tu dong ensure Neo4j vector indexes khi startup:
  - `public_embeddings_phobert_idx`
  - `public_embeddings_gte_idx`
  - `public_embeddings_e5_idx`
  - `public_embeddings_bge_idx`
- Router dang mount:
  - `auth`, `ingest`, `search`, `interview`, `connect`, `graph`, `chat`, `availability`, `schedule`, `notification`
- Co `/health` va global exception handler.

### Ingestion pipeline (`pipeline/main.py`)
- File `.json`: bypass extraction, ingest truc tiep.
- File tai lieu (`.pdf`, `.docx`, `.txt`, `.md`):
  - Parse -> clean -> chunk -> extract theo chunk -> merge map-reduce -> vectorize -> ingest Neo4j -> dual-ingest Supabase (best effort).

### Hybrid + Interview engine (`pipeline/hybrid_query_engine.py`)
- Hybrid score hien tai:

```text
score = 0.2 * graph_score + 0.8 * vector_score + bonus
bonus = 0.15 (neu co overlap connected tech)
```

- Co co che private/public mode theo trang thai ket noi Organization-Personnel.

## 4. API endpoints hien tai

### Auth
- `POST /auth/register`

Luu y: backend dung Supabase JWT qua `Authorization: Bearer <token>` cho cac route bao ve.

### Core
- `POST /ingest`
- `POST /search`
- `POST /interview`
- `WS /interview/ws`
- `GET /graph`
- `GET /health`

### Connect
- `POST /connect`
- `PATCH /connect/{personnel_id}/respond`

### Interview utility
- `GET /interview/connection-status/{per_neo4j_id}`
- `POST /interview/connection-statuses`
- `POST /interview/request/{per_neo4j_id}`
- `PATCH /interview/request/{per_neo4j_id}/accept`
- `PATCH /interview/request/{per_neo4j_id}/reject`
- `GET /interview/profile/{per_neo4j_id}`

### Chat
- `POST /chat/sessions`
- `GET /chat/sessions?org_id=...`
- `GET /chat/sessions/{session_id}/fit-summary?org_id=...`
- `POST /chat/message`
- `GET /chat/history/{session_id}`

### Availability
- `PUT /availability`
- `GET /availability/{per_neo4j_id}/slots`

### Schedule
- `POST /schedule`
- `GET /schedule`
- `PATCH /schedule/{schedule_id}/status`
- `PATCH /schedule/{schedule_id}/reschedule`
- `PATCH /schedule/{schedule_id}/counter-propose`

### Notification
- `GET /notification`
- `GET /notification/unread-count`
- `PATCH /notification/{notification_id}/read`
- `PATCH /notification/read-all`

## 5. Cai dat va chay local

## Yeu cau
- Python 3.10+
- Node.js 20+
- Docker

## 5.1 Clone va cai dat backend

```bash
git clone <repo_url>
cd graphRAG
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Neu dung PowerShell, co the can:

```powershell
.\.venv\Scripts\Activate.ps1
```

## 5.2 Chay Neo4j

```bash
docker-compose up -d
```

- Neo4j Browser: http://localhost:7474
- Bolt: bolt://localhost:7687

## 5.3 Chay backend

```bash
uvicorn api.main:app --reload --port 8000
```

- Swagger: http://localhost:8000/docs

## 5.4 Chay frontend

```bash
cd frontend
npm install
npm run gen:types
npm run dev
```

- Frontend: http://localhost:3000

## 5.5 Chay full stack bang root scripts

Project root co `package.json` de chay ca backend + frontend:

```bash
npm install
npm run dev
```

Cac script root:
- `npm run dev` -> concurrently backend reload + frontend dev
- `npm run prod` -> concurrently backend non-reload + frontend build/start
- `npm run prod:backend`
- `npm run prod:frontend`
- `npm run build:frontend`
- `npm run start:frontend`

## 6. Bien moi truong quan trong

### Backend `.env`

```env
# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=
NEO4J_AURA_URI=
NEO4J_AURA_USERNAME=
NEO4J_AURA_PASSWORD=
NEO4J_AURA_DATABASE=neo4j

# Supabase
SUPABASE_URL=
SUPABASE_SERVICE_KEY=
SUPABASE_JWT_SECRET=

# LLM
OPENAI_API_KEY=
CEREBRAS_API_KEY=
CEREBRAS_MODEL=llama3.1-8b
ANTHROPIC_API_KEY=
GROQ_API_KEY=

# Parser
LLAMA_CLOUD_API_KEY=
LLAMAPARSE_API_KEY=
PARSER_MIN_TEXT_LEN=200
UNSTRUCTURED_API_KEY=
UNSTRUCTURED_BASE_URL=https://platform.unstructuredapp.io/api/v1
NUTRIENT_API_KEY=
NUTRIENT_BASE_URL=https://api.nutrient.io/build

# Embedding
ACTIVE_EMBEDDING_MODEL=Alibaba-NLP/gte-multilingual-base
EMBEDDING_MODEL=Alibaba-NLP/gte-multilingual-base

# Email demo
DEMO_SENDER_EMAIL=
DEMO_SENDER_APP_PASSWORD=
DEMO_CALENDAR_EMAIL=
DEMO_RECIPIENT_EMAIL=

# Logging
LOG_LEVEL=INFO
```

### Frontend `frontend/.env.local`

```env
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## 7. Ingest du lieu

```bash
# personnel
python scripts/reextract_and_ingest.py --type personnel

# organization
python scripts/reextract_and_ingest.py --type org
```

File JSON duoc bypass extraction de tiet kiem chi phi.

## 8. SQL migration va scripts hien co

### SQL migration (`scripts/sql/`)
- `phase_0_25_vdme_bridge_upgrade.sql`
- `phase_0_26_chat_sessions.sql`
- `phase_0_26_chunk_gte_bge_backfill.sql`
- `phase_0_27_chunk_e5_column.sql`
- `phase_0_28_dynamic_embedding_rpc.sql`
- `phase_0_29_phobert_chunk_backfill.sql`
- `phase_0_31_schedule_reschedule_flow.sql`
- `phase_X_session_reasoning.sql`

### Utility scripts (`scripts/`)
- `reextract_and_ingest.py`
- `clean_all_data.py`
- `reembed_supabase.py`
- `backfill_embeddings.py`
- `backfill_graph_nodes.py`
- `backfill_phobert_chunks.py`
- `backfill_session_reasoning.py`
- `migrate_users_to_supabase.py`
- `neo4j_export.py`
- `neo4j_import.py`

## 9. Evaluation

Chay toan bo:

```bash
python scripts/eval/run_all.py
```

Chay theo tung step:

```bash
python scripts/eval/run_all.py cleaner
python scripts/eval/run_all.py extractor
python scripts/eval/run_all.py embedding
python scripts/eval/run_all.py graph
python scripts/eval/run_all.py ragas
python scripts/eval/run_all.py privacy
```

Xem danh sach step:

```bash
python scripts/eval/run_all.py --list
```

## 10. WebSocket interview test (payload dung theo code hien tai)

```python
import asyncio
import json
import websockets

async def test_interview_ws(base_url: str, token: str):
    ws_url = base_url.replace("https://", "wss://").replace("http://", "ws://") + "/interview/ws"

    async with websockets.connect(ws_url, ping_interval=20) as websocket:
        payload = {
            "token": token,
            "session_id": "demo-session-001",
            "personnel_id": "p001",
            "question": "Ung vien co ky nang Python nao noi bat?",
        }
        await websocket.send(json.dumps(payload))

        while True:
            try:
                msg = await asyncio.wait_for(websocket.recv(), timeout=30)
                print(msg)
            except asyncio.TimeoutError:
                break

if __name__ == "__main__":
    asyncio.run(test_interview_ws("http://localhost:8000", "<SUPABASE_ACCESS_TOKEN>"))
```

## 11. Ghi chu nhanh

- API route hien tai khong co `POST /auth/login`.
- Chat history route dung `session_id`: `GET /chat/history/{session_id}`.
- Cong thuc hybrid hien tai la `0.2 graph + 0.8 vector + bonus`, khong phai `0.4/0.6`.
- Neu frontend can OpenAPI type moi, chay lai `npm run gen:types` trong `frontend/`.
