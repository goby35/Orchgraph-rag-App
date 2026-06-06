# ORCHGRAPH-RAG

A smart recruitment platform utilizing GraphRAG + AI Digital Twin for Vietnamese CVs, operating on a dual-database model:

* **Neo4j:** Stores the public knowledge graph + Organization-Personnel relationships + vector indexes.
* **Supabase:** Stores the private vault, chat histories, appointment schedules, notifications, and chunk embeddings.

## 1. Architecture Overview

```text
graphRAG/
|- api/                # FastAPI backend (REST + WebSocket)
|- pipeline/           # Ingestion + hybrid retrieval + interview engine
|- frontend/           # Next.js 16 (App Router)
|- scripts/            # Migration, backfill, and evaluation utilities
|- data_eval/          # Evaluation datasets
|- results/            # Evaluation results
|- neo4j/              # Neo4j docker volumes/plugins
`- docker-compose.yml  # Local Neo4j setup

```

## 2. Tech Stack (Actual Implementation)

### Backend / Pipeline

* Python, FastAPI, Uvicorn
* Neo4j 5.x (with vector index support)
* Supabase (Auth + Postgres + Realtime)
* Multi-embedding:
* `vinai/phobert-base-v2`
* `Alibaba-NLP/gte-multilingual-base` (default active)
* `intfloat/multilingual-e5-base`
* `BAAI/bge-base-en-v1.5`


* LLM Extraction: OpenAI `gpt-4o-mini` (fallback Cerebras)
* Parser Fallback Chain: LlamaParse -> unstructured -> Nutrient API

### Frontend

* Next.js `16.2.1`, React `19.2.4`, TypeScript 5
* Tailwind CSS v4 + shadcn/ui
* Zustand + TanStack Query
* React Flow + react-force-graph-2d

## 3. Core Modules

### API (`api/main.py`)

* Automatically ensures Neo4j vector indexes on startup:
* `public_embeddings_phobert_idx`
* `public_embeddings_gte_idx`
* `public_embeddings_e5_idx`
* `public_embeddings_bge_idx`


* Mounted routers:
* `auth`, `ingest`, `search`, `interview`, `connect`, `graph`, `chat`, `availability`, `schedule`, `notification`


* Includes `/health` and a global exception handler.

### Ingestion Pipeline (`pipeline/main.py`)

* `.json` files: Bypass extraction and are ingested directly.
* Document files (`.pdf`, `.docx`, `.txt`, `.md`):
* Parse -> clean -> chunk -> extract by chunk -> merge map-reduce -> vectorize -> ingest into Neo4j -> dual-ingest into Supabase (best effort).



### Hybrid + Interview Engine (`pipeline/hybrid_query_engine.py`)

* Current hybrid score formula:

```text
score = 0.2 * graph_score + 0.8 * vector_score + bonus
bonus = 0.15 (if there is overlapping connected tech)

```

* Features a private/public mode mechanism based on the Organization-Personnel connection status.

## 4. Current API Endpoints

### Auth

* `POST /auth/register`

> **Note:** The backend uses Supabase JWT via `Authorization: Bearer <token>` for protected routes.

### Core

* `POST /ingest`
* `POST /search`
* `POST /interview`
* `WS /interview/ws`
* `GET /graph`
* `GET /health`

### Connect

* `POST /connect`
* `PATCH /connect/{personnel_id}/respond`

### Interview Utility

* `GET /interview/connection-status/{per_neo4j_id}`
* `POST /interview/connection-statuses`
* `POST /interview/request/{per_neo4j_id}`
* `PATCH /interview/request/{per_neo4j_id}/accept`
* `PATCH /interview/request/{per_neo4j_id}/reject`
* `GET /interview/profile/{per_neo4j_id}`

### Chat

* `POST /chat/sessions`
* `GET /chat/sessions?org_id=...`
* `GET /chat/sessions/{session_id}/fit-summary?org_id=...`
* `POST /chat/message`
* `GET /chat/history/{session_id}`

### Availability

* `PUT /availability`
* `GET /availability/{per_neo4j_id}/slots`

### Schedule

* `POST /schedule`
* `GET /schedule`
* `PATCH /schedule/{schedule_id}/status`
* `PATCH /schedule/{schedule_id}/reschedule`
* `PATCH /schedule/{schedule_id}/counter-propose`

### Notification

* `GET /notification`
* `GET /notification/unread-count`
* `PATCH /notification/{notification_id}/read`
* `PATCH /notification/read-all`

## 5. Local Setup and Installation

### Prerequisites

* Python 3.10+
* Node.js 20+
* Docker

### 5.1 Clone and Setup Backend

```bash
git clone <repo_url>
cd graphRAG
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env

```

If using PowerShell, you might need to run:

```powershell
.\.venv\Scripts\Activate.ps1

```

### 5.2 Run Neo4j

```bash
docker-compose up -d

```

* Neo4j Browser: http://localhost:7474
* Bolt: bolt://localhost:7687

### 5.3 Run Backend

```bash
uvicorn api.main:app --reload --port 8000

```

* Swagger UI: http://localhost:8000/docs

### 5.4 Run Frontend

```bash
cd frontend
npm install
npm run gen:types
npm run dev

```

* Frontend UI: http://localhost:3000

### 5.5 Run Full Stack via Root Scripts

The project root contains a `package.json` to run both the backend and frontend simultaneously:

```bash
npm install
npm run dev

```

Available root scripts:

* `npm run dev` -> Runs backend with reload + frontend in dev mode concurrently.
* `npm run prod` -> Runs backend without reload + frontend build/start concurrently.
* `npm run prod:backend`
* `npm run prod:frontend`
* `npm run build:frontend`
* `npm run start:frontend`

## 6. Crucial Environment Variables

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
# If calling the backend on Modal, use the ASGI function URL:
# NEXT_PUBLIC_API_URL=https://<username>--orchgraph-rag-fastapi-app.modal.run

```

## 7. Data Ingestion

```bash
# personnel
python scripts/reextract_and_ingest.py --type personnel

# organization
python scripts/reextract_and_ingest.py --type org

```

JSON files bypass the extraction phase to save processing costs.

## 8. SQL Migrations and Existing Scripts

### SQL Migrations (`scripts/sql/`)

* `phase_0_25_vdme_bridge_upgrade.sql`
* `phase_0_26_chat_sessions.sql`
* `phase_0_26_chunk_gte_bge_backfill.sql`
* `phase_0_27_chunk_e5_column.sql`
* `phase_0_28_dynamic_embedding_rpc.sql`
* `phase_0_29_phobert_chunk_backfill.sql`
* `phase_0_31_schedule_reschedule_flow.sql`
* `phase_X_session_reasoning.sql`

### Utility Scripts (`scripts/`)

* `reextract_and_ingest.py`
* `clean_all_data.py`
* `reembed_supabase.py`
* `backfill_embeddings.py`
* `backfill_graph_nodes.py`
* `backfill_phobert_chunks.py`
* `backfill_session_reasoning.py`
* `migrate_users_to_supabase.py`
* `neo4j_export.py`
* `neo4j_import.py`

## 9. Evaluation

Run the full evaluation suite:

```bash
python scripts/eval/run_all.py

```

Run specific evaluation steps:

```bash
python scripts/eval/run_all.py cleaner
python scripts/eval/run_all.py extractor
python scripts/eval/run_all.py embedding
python scripts/eval/run_all.py graph
python scripts/eval/run_all.py ragas
python scripts/eval/run_all.py privacy

```

View the list of available steps:

```bash
python scripts/eval/run_all.py --list

```

## 10. WebSocket Interview Test (Payload mapping to current code)

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
            "question": "What outstanding Python skills does the candidate have?",
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

## 11. Quick Notes

* The current API routes do not include `POST /auth/login`.
* The chat history route requires a `session_id`: `GET /chat/history/{session_id}`.
* The current hybrid score formula is `0.2 graph + 0.8 vector + bonus`, not `0.4/0.6`.
* If the frontend requires new OpenAPI types, run `npm run gen:types` inside the `frontend/` directory to regenerate them.