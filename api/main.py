from __future__ import annotations

import os
import re
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import traceback as _traceback
from fastapi import Request
from fastapi.responses import JSONResponse
from typing import Any, cast

from api.routers import auth, chat, connect, graph, ingest, interview, search, availability, schedule, notification
from pipeline.config import get_logger, settings
from pipeline.neo4j_client import get_neo4j_driver

logger = get_logger(__name__)

app = FastAPI(title="Digital Twin Recruitment API", version="2.0")
VERCEL_ORIGIN_REGEX = re.compile(r"^https://.*\.vercel\.app$")


def _ensure_vector_indexes() -> None:
    driver = get_neo4j_driver()
    index_specs = (
        ("public_embeddings_phobert_idx", "public_embeddings_phobert"),
        ("public_embeddings_gte_idx", "public_embeddings_gte"),
        ("public_embeddings_e5_idx", "public_embeddings_e5"),
        ("public_embeddings_bge_idx", "public_embeddings_bge"),
    )

    try:
        with driver.session(database=settings.neo4j_database) as session:
            for index_name, field_name in index_specs:
                try:
                    cypher = (
                        "CREATE VECTOR INDEX {index_name} IF NOT EXISTS "
                        "FOR (p:Personnel) ON (p.{field_name}) "
                        "OPTIONS {{ indexConfig: {{ `vector.dimensions`: 768, `vector.similarity_function`: 'cosine' }} }}"
                    ).format(index_name=index_name, field_name=field_name)
                    session.run(cast(Any, cypher)).consume()
                except Exception as exc:
                    logger.warning("Could not ensure vector index %s: %s", index_name, exc)
    finally:
        driver.close()


@app.on_event("startup")
async def _startup() -> None:
    try:
        _ensure_vector_indexes()
    except Exception as exc:
        logger.warning("Startup vector index check failed: %s", exc)

CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "https://orchgraph-rag.vercel.app"

]

frontend_url = os.getenv("FRONTEND_URL", "").strip()
if frontend_url and frontend_url not in CORS_ORIGINS:
    CORS_ORIGINS.append(frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(ingest.router, prefix="/ingest", tags=["Ingestion"])
app.include_router(search.router, prefix="/search", tags=["Search"])
app.include_router(interview.router, prefix="/interview", tags=["Interview"])
app.include_router(connect.router, tags=["Connect"])
app.include_router(graph.router, prefix="/graph", tags=["Graph"])
app.include_router(chat.router, prefix="/chat", tags=["Chat"])
app.include_router(availability.router,  prefix="/availability",  tags=["Availability"])
app.include_router(schedule.router,      prefix="/schedule",      tags=["Schedule"])
app.include_router(notification.router,  prefix="/notification",  tags=["Notification"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

@app.exception_handler(Exception)
async def _debug_handler(request: Request, exc: Exception) -> JSONResponse:
    print(_traceback.format_exc())
    request_origin = request.headers.get("origin", "")
    is_vercel_origin = bool(VERCEL_ORIGIN_REGEX.match(request_origin))
    allow_origin = request_origin if request_origin in CORS_ORIGINS or is_vercel_origin else "http://localhost:3000"
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
        headers={"Access-Control-Allow-Origin": allow_origin},
    )