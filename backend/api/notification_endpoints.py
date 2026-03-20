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
