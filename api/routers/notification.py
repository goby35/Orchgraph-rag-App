# api/routers/notification.py
from fastapi import APIRouter, Depends
from api.deps import get_current_user
from api.models.scheduling import NotificationResponse
from pipeline.supabase_client import get_supabase

router = APIRouter()


@router.get("", response_model=list[NotificationResponse])
async def list_notifications(
    unread_only: bool = False,
    limit:       int  = 20,
    user: dict = Depends(get_current_user),
):
    sb    = get_supabase()
    query = (
        sb.schema("vdme").table("notifications")
        .select("*")
        .eq("recipient_neo4j_id", user["neo4j_id"])
        .order("created_at", desc=True)
        .limit(limit)
    )
    if unread_only:
        query = query.eq("is_read", False)
    return query.execute().data or []


@router.patch("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    user: dict = Depends(get_current_user),
):
    get_supabase().schema("vdme").table("notifications").update(
        {"is_read": True, "read_at": "now()"}
    ).eq("id", notification_id).eq("recipient_neo4j_id", user["neo4j_id"]).execute()
    return {"status": "ok"}


@router.patch("/read-all")
async def mark_all_read(user: dict = Depends(get_current_user)):
    get_supabase().schema("vdme").table("notifications").update(
        {"is_read": True, "read_at": "now()"}
    ).eq("recipient_neo4j_id", user["neo4j_id"]).eq("is_read", False).execute()
    return {"status": "ok"}


@router.get("/unread-count")
async def unread_count(user: dict = Depends(get_current_user)):
    rows = (
        get_supabase().schema("vdme").table("notifications")
        .select("id")
        .eq("recipient_neo4j_id", user["neo4j_id"])
        .eq("is_read", False)
        .execute()
    ).data or []
    return {"count": len(rows)}