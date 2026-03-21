from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from api.deps import get_current_user
from pipeline.hybrid_query_engine import DigitalTwinInterviewEngine

router = APIRouter()


class InterviewRequest(BaseModel):
    personnel_id: str
    question: str


@router.post("")
async def interview(
    body: InterviewRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    with DigitalTwinInterviewEngine() as engine:
        response = engine.answer_interview(
            org_id=str(user.get("neo4j_id") or ""),
            personnel_id=body.personnel_id,
            interview_question=body.question,
        )

    if isinstance(response, dict):
        return response
    return {"answer": str(response), "is_private_mode": False}


@router.websocket("/ws")
async def interview_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        data = await websocket.receive_json()
        token = str(data.get("token") or "")
        user = await get_current_user(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        )

        with DigitalTwinInterviewEngine() as engine:
            response = engine.answer_interview(
                org_id=str(user.get("neo4j_id") or ""),
                personnel_id=str(data.get("personnel_id") or ""),
                interview_question=str(data.get("question") or ""),
            )

        answer = response.get("answer", "") if isinstance(response, dict) else str(response)
        for word in answer.split():
            await websocket.send_json({"chunk": word + " "})

        await websocket.send_json(
            {
                "done": True,
                "is_private_mode": response.get("is_private_mode", False)
                if isinstance(response, dict)
                else False,
            }
        )
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await websocket.send_json({"error": str(exc)})
