from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
import logging

logger = logging.getLogger(__name__)
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from api.deps import get_current_user
from pipeline.hybrid_query_engine import DigitalTwinInterviewEngine
from pipeline.hybrid_query_engine import create_connection_request
from pipeline.supabase_client import get_supabase


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

# api/routers/interview.py — thêm endpoint mới

from pipeline.hybrid_query_engine import get_connection_status

@router.get("/connection-status/{per_neo4j_id}")
async def get_org_connection_status(
    per_neo4j_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, str | None]:
    """Org kiểm tra trạng thái kết nối với Personnel."""
    org_id = user.get("neo4j_id")
    if not org_id:
        raise HTTPException(400, "Không tìm thấy org_id")

    status = get_connection_status(
        org_id=org_id,
        personnel_id=per_neo4j_id,
    )
    return {"status": status}  # None | "pending" | "accepted" | "cancelled"


# api/routers/interview.py — thêm endpoint gửi request kết nối

@router.post("/request/{per_neo4j_id}")
async def send_interview_request(
    per_neo4j_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, str]:
    """Org gửi request kết nối tới Personnel."""
    if user.get("role") != "organization":
        raise HTTPException(403, "Chỉ Organization mới có thể gửi request")

    org_id = user.get("neo4j_id")
    if not org_id:
        raise HTTPException(400, "Không tìm thấy org_id")

    # Tạo CONNECTED_TO relationship với status pending
    success = create_connection_request(
        org_id=org_id,
        personnel_id=per_neo4j_id,
        status="pending",
    )
    if not success:
        raise HTTPException(404, "Không tìm thấy Personnel hoặc Organization")

    # Gửi notification cho Personnel
    try:
        sb = get_supabase()
        per_user_id = _get_user_id_by_neo4j_id(sb, per_neo4j_id)
        if per_user_id:
            sb.schema("vdme").table("notifications").insert({
                "recipient_neo4j_id": per_neo4j_id,
                "sender_neo4j_id":    org_id,
                "type":               "interview_request",
                "title":              "Bạn nhận được lời mời phỏng vấn",
                "body":               f"Tổ chức {org_id} muốn kết nối và phỏng vấn bạn.",
                "payload":            {"redirect_to": "/schedule"},
                "is_read":            False,
            }).execute()
    except Exception as exc:
        logger.warning("Notification insert failed: %s", exc)
        # Không raise — notification fail không block request

    return {"status": "pending", "message": "Đã gửi lời mời thành công"}


def _get_user_id_by_neo4j_id(sb, neo4j_id: str) -> str | None:
    """Helper lấy Supabase user_id từ neo4j_id."""
    try:
        result = sb.schema("vdme").table("users") \
            .select("id").eq("neo4j_id", neo4j_id).maybe_single().execute()
        return result.data["id"] if result.data else None
    except Exception:
        return None