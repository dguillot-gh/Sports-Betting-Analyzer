import asyncpg
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query, Request

from src.config import DATABASE_URL
from src.notification_store import (
    ensure_notifications_schema,
    fetch_notifications,
    mark_all_notifications_read,
    mark_notification_read,
    unread_notification_count,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/notifications", tags=["Notifications"])


async def _get_db_connection(request: Request) -> asyncpg.Connection:
    if hasattr(request.app.state, "pool") and request.app.state.pool:
        return await request.app.state.pool.acquire()
    return await asyncpg.connect(DATABASE_URL)


async def _release_db_connection(request: Request, conn: asyncpg.Connection) -> None:
    if hasattr(request.app.state, "pool") and request.app.state.pool:
        await request.app.state.pool.release(conn)
    else:
        await conn.close()


@router.get("")
async def get_notifications(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    unread_only: bool = Query(False),
):
    conn = None
    try:
        conn = await _get_db_connection(request)
        try:
            items = await fetch_notifications(conn, limit=limit, unread_only=unread_only)
        except asyncpg.UndefinedTableError:
            await _release_db_connection(request, conn)
            conn = None
            await ensure_notifications_schema(DATABASE_URL)
            conn = await _get_db_connection(request)
            items = await fetch_notifications(conn, limit=limit, unread_only=unread_only)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        logger.error("Failed to fetch notifications: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch notifications")
    finally:
        if conn:
            await _release_db_connection(request, conn)


@router.get("/unread-count")
async def get_unread_count(request: Request):
    conn = None
    try:
        conn = await _get_db_connection(request)
        try:
            count = await unread_notification_count(conn)
        except asyncpg.UndefinedTableError:
            await _release_db_connection(request, conn)
            conn = None
            await ensure_notifications_schema(DATABASE_URL)
            conn = await _get_db_connection(request)
            count = await unread_notification_count(conn)
        return {"count": count}
    except Exception as exc:
        logger.error("Failed to fetch unread notification count: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch unread count")
    finally:
        if conn:
            await _release_db_connection(request, conn)


@router.post("/{notification_id}/read")
async def mark_read(request: Request, notification_id: int):
    conn = None
    try:
        conn = await _get_db_connection(request)
        try:
            updated = await mark_notification_read(conn, notification_id)
        except asyncpg.UndefinedTableError:
            await _release_db_connection(request, conn)
            conn = None
            await ensure_notifications_schema(DATABASE_URL)
            conn = await _get_db_connection(request)
            updated = await mark_notification_read(conn, notification_id)
        return {"success": updated}
    except Exception as exc:
        logger.error("Failed to mark notification read: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to mark notification read")
    finally:
        if conn:
            await _release_db_connection(request, conn)


@router.post("/read-all")
async def mark_read_all(request: Request):
    conn = None
    try:
        conn = await _get_db_connection(request)
        try:
            updated_count = await mark_all_notifications_read(conn)
        except asyncpg.UndefinedTableError:
            await _release_db_connection(request, conn)
            conn = None
            await ensure_notifications_schema(DATABASE_URL)
            conn = await _get_db_connection(request)
            updated_count = await mark_all_notifications_read(conn)
        return {"success": True, "updated_count": updated_count}
    except Exception as exc:
        logger.error("Failed to mark all notifications read: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to mark all notifications read")
    finally:
        if conn:
            await _release_db_connection(request, conn)


@router.post("/test/{channel}")
async def test_notification_channel(channel: str):
    """
    Fire a test notification to a specific channel.
    Channels: in-app, web-push, fcm, all
    """
    from datetime import datetime

    valid_channels = ("in-app", "web-push", "fcm", "all")
    if channel not in valid_channels:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid channel '{channel}'. Valid: {', '.join(valid_channels)}",
        )

    timestamp = datetime.now().strftime("%I:%M:%S %p")
    title = f"🧪 Test — {channel.upper()}"
    message = f"This is a test notification sent at {timestamp}. If you're reading this, the {channel} channel is working!"

    results = {}

    # In-App (writes to DB, which also triggers FCM + Web Push via insert_notification)
    if channel in ("in-app", "all"):
        try:
            from src.notification_store import insert_notification

            await insert_notification(
                DATABASE_URL,
                severity="info",
                category="test",
                title=title if channel != "all" else "🧪 Test — ALL CHANNELS",
                message=message,
                source="admin.test_notification",
                metadata={"test": True, "channel": channel},
            )
            results["in-app"] = {"success": True, "detail": "Notification inserted (also triggers FCM + Web Push)"}
        except Exception as exc:
            results["in-app"] = {"success": False, "detail": str(exc)}

    # Web Push (direct, bypasses insert_notification)
    if channel == "web-push" or (channel == "all" and False):  # 'all' handled by in-app
        try:
            from src.push_store import send_web_push_to_all

            sent = await send_web_push_to_all(
                DATABASE_URL,
                title=title,
                message=message,
                severity="info",
            )
            results["web-push"] = {"success": True, "sent": sent}
        except Exception as exc:
            results["web-push"] = {"success": False, "detail": str(exc)}

    # FCM (direct, bypasses insert_notification)
    if channel == "fcm" or (channel == "all" and False):  # 'all' handled by in-app
        try:
            from src.fcm_store import send_fcm_to_all

            sent = await send_fcm_to_all(
                DATABASE_URL,
                title=title,
                message=message,
                severity="info",
            )
            results["fcm"] = {"success": True, "sent": sent}
        except Exception as exc:
            results["fcm"] = {"success": False, "detail": str(exc)}

    return {"channel": channel, "results": results}

