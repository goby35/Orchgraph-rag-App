from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import traceback as _traceback
from fastapi import Request
from fastapi.responses import JSONResponse

from api.routers import auth, chat, graph, ingest, interview, search, availability, schedule, notification

app = FastAPI(title="Digital Twin Recruitment API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://your-production-domain.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(ingest.router, prefix="/ingest", tags=["Ingestion"])
app.include_router(search.router, prefix="/search", tags=["Search"])
app.include_router(interview.router, prefix="/interview", tags=["Interview"])
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
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
        headers={"Access-Control-Allow-Origin": "http://localhost:3000"},
    )