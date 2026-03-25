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

    # 1. Hứng cả success và org_name từ hàm đã sửa
    success, org_name = create_connection_request(
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
                # 2. Đổi {org_id} thành {org_name} cho mượt mà
                "body":               f"Tổ chức {org_name} muốn kết nối và phỏng vấn bạn.",
                "payload":            {"redirect_to": "/notifications", "per_neo4j_id": per_neo4j_id},
                "is_read":            False,
            }).execute()
    except Exception as exc:
        logger.warning("Notification insert failed: %s", exc)
        # Không raise — notification fail không block request

    return {"status": "pending", "message": "Đã gửi lời mời thành công"}

@router.patch("/request/{per_neo4j_id}/accept")
async def accept_interview_request(
    per_neo4j_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, str]:
    """Personnel accepts the connection request from an Org."""
    if user.get("role") != "personnel":
        raise HTTPException(403, "Chỉ Personnel mới có thể chấp nhận lời mời")

    from neo4j import GraphDatabase
    from pipeline.config import settings
    driver = GraphDatabase.driver(
        settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )
    try:
        with driver.session() as session:
            rows = session.run(
                """
                MATCH (o:Organization)-[r:CONNECTED_TO]->(p:Personnel {id: $per_id})
                WHERE r.status = 'pending'
                RETURN o.id AS org_id
                """,
                per_id=per_neo4j_id,
            ).data()
    finally:
        driver.close()

    if not rows:
        raise HTTPException(404, "Không tìm thấy lời mời đang chờ")

    org_id = rows[0]["org_id"]
    create_connection_request(org_id=org_id, personnel_id=per_neo4j_id, status="accepted")

    try:
        sb = get_supabase()
        sb.schema("vdme").table("notifications").insert({
            "recipient_neo4j_id": org_id,
            "sender_neo4j_id":    per_neo4j_id,
            "type":               "interview_accepted",
            "title":              "Lời mời phỏng vấn được chấp nhận",
            "body":               f"Ứng viên {per_neo4j_id} đã chấp nhận lời mời phỏng vấn.",
            "payload":            {"redirect_to": f"/interview/{per_neo4j_id}"},
            "is_read":            False,
        }).execute()
    except Exception as exc:
        logger.warning("Notification insert failed: %s", exc)

    return {"status": "accepted"}


@router.patch("/request/{per_neo4j_id}/reject")
async def reject_interview_request(
    per_neo4j_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, str]:
    """Personnel rejects the connection request."""
    if user.get("role") != "personnel":
        raise HTTPException(403, "Chỉ Personnel mới có thể từ chối lời mời")

    from neo4j import GraphDatabase
    from pipeline.config import settings
    driver = GraphDatabase.driver(
        settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )
    try:
        with driver.session() as session:
            rows = session.run(
                """
                MATCH (o:Organization)-[r:CONNECTED_TO]->(p:Personnel {id: $per_id})
                WHERE r.status = 'pending'
                RETURN o.id AS org_id
                """,
                per_id=per_neo4j_id,
            ).data()
    finally:
        driver.close()

    if not rows:
        raise HTTPException(404, "Không tìm thấy lời mời đang chờ")

    org_id = rows[0]["org_id"]
    create_connection_request(org_id=org_id, personnel_id=per_neo4j_id, status="cancelled")

    try:
        sb = get_supabase()
        sb.schema("vdme").table("notifications").insert({
            "recipient_neo4j_id": org_id,
            "sender_neo4j_id":    per_neo4j_id,
            "type":               "interview_rejected",
            "title":              "Lời mời phỏng vấn bị từ chối",
            "body":               f"Ứng viên {per_neo4j_id} đã từ chối lời mời phỏng vấn.",
            "payload":            {"redirect_to": "/search"},
            "is_read":            False,
        }).execute()
    except Exception as exc:
        logger.warning("Notification insert failed: %s", exc)

    return {"status": "cancelled"}


@router.get("/profile/{per_neo4j_id}")
async def get_personnel_profile(
    per_neo4j_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Return public profile data for a Personnel node."""
    from neo4j import GraphDatabase
    from pipeline.config import settings
    driver = GraphDatabase.driver(
        settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )
    try:
        with driver.session() as session:
            row = session.run(
                """
                MATCH (p:Personnel {id: $id})
                RETURN coalesce(p.public_name, p.public_full_name, p.id) AS name,
                       p.public_skills AS skills,
                       coalesce(p.public_professional_summary, p.public_summary, '') AS summary,
                       p.public_experience AS experience
                """,
                id=per_neo4j_id,
            ).single()
    finally:
        driver.close()

    if not row:
        raise HTTPException(404, "Không tìm thấy Personnel")

    import json as _json

    def _parse_list(value: object) -> list[Any]:
        if isinstance(value, list):
            return list(value)
        if isinstance(value, str):
            try:
                parsed = _json.loads(value)
                if isinstance(parsed, list):
                    return parsed
            except (ValueError, _json.JSONDecodeError):
                pass
        return []

    return {
        "neo4j_id":   per_neo4j_id,
        "name":       str(row.get("name") or per_neo4j_id),
        "skills":     _parse_list(row.get("skills")),
        "summary":    str(row.get("summary") or ""),
        "experience": _parse_list(row.get("experience")),
    }


def _get_user_id_by_neo4j_id(sb, neo4j_id: str) -> str | None:
    """Helper lấy Supabase user_id từ neo4j_id."""
    try:
        result = sb.schema("vdme").table("users") \
            .select("id").eq("neo4j_id", neo4j_id).maybe_single().execute()
        return result.data["id"] if result.data else None
    except Exception:
        return None