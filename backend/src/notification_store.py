import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import asyncpg


logger = logging.getLogger(__name__)

WARNING_TTL_HOURS = int(os.getenv("APP_NOTIFICATION_WARNING_TTL_HOURS", "72"))
INFO_TTL_HOURS = int(os.getenv("APP_NOTIFICATION_INFO_TTL_HOURS", "24"))
SUCCESS_TTL_HOURS = int(os.getenv("APP_NOTIFICATION_SUCCESS_TTL_HOURS", "24"))


NOTIFICATIONS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS app_notifications (
    id BIGSERIAL PRIMARY KEY,
    severity VARCHAR(16) NOT NULL,
    category VARCHAR(64) NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    source VARCHAR(128),
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_app_notifications_created_at
    ON app_notifications(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_app_notifications_read_at
    ON app_notifications(read_at);
"""


async def ensure_notifications_schema(database_url: str) -> None:
    conn = None
    try:
        conn = await asyncpg.connect(database_url)
        await conn.execute(NOTIFICATIONS_SCHEMA_SQL)
    finally:
        if conn:
            await conn.close()


async def insert_notification(
    database_url: str,
    *,
    severity: str,
    category: str,
    title: str,
    message: str,
    source: str = "",
    metadata: Dict[str, Any] | None = None,
) -> None:
    conn = None
    try:
        conn = await asyncpg.connect(database_url)
        sev = (severity or "info").lower()
        expires_at = None
        ttl_hours = _default_ttl_hours(sev)
        if ttl_hours and ttl_hours > 0:
            expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)

        await conn.execute(
            """
            INSERT INTO app_notifications
                (severity, category, title, message, source, metadata_json, expires_at)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
            """,
            sev,
            category,
            title,
            message,
            source,
            json.dumps(metadata or {}),
            expires_at,
        )
        # Fire-and-forget push broadcasts for ALL notifications
        sev_lower = (severity or "info").lower()
        try:
            import asyncio
            from src.push_store import send_web_push_to_all
            from src.fcm_store import send_fcm_to_all

            async def _safe_push(coro, label: str):
                """Wrapper that catches exceptions so create_task futures never go unhandled."""
                try:
                    await coro
                except Exception as exc:
                    logger.debug("Fire-and-forget %s failed (non-critical): %s", label, exc)

            loop = asyncio.get_running_loop()
            loop.create_task(
                _safe_push(
                    send_web_push_to_all(database_url, title=title, message=message, severity=sev_lower),
                    "web_push",
                )
            )
            loop.create_task(
                _safe_push(
                    send_fcm_to_all(database_url, title=title, message=message, severity=sev_lower),
                    "fcm",
                )
            )
        except RuntimeError:
            pass  # No running loop (script context)
    except Exception as exc:
        logger.error("Failed to insert notification: %s", exc, exc_info=True)
    finally:
        if conn:
            await conn.close()


async def fetch_notifications(conn: asyncpg.Connection, limit: int, unread_only: bool) -> List[Dict[str, Any]]:
    if unread_only:
        rows = await conn.fetch(
            """
            SELECT id, severity, category, title, message, source, metadata_json, created_at, read_at, expires_at
            FROM app_notifications
            WHERE read_at IS NULL
              AND (expires_at IS NULL OR expires_at > NOW())
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT id, severity, category, title, message, source, metadata_json, created_at, read_at, expires_at
            FROM app_notifications
            WHERE expires_at IS NULL OR expires_at > NOW()
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [dict(r) for r in rows]


async def mark_notification_read(conn: asyncpg.Connection, notification_id: int) -> bool:
    result = await conn.execute(
        "UPDATE app_notifications SET read_at = NOW() WHERE id = $1 AND read_at IS NULL",
        notification_id,
    )
    return result.endswith("1")


async def mark_all_notifications_read(conn: asyncpg.Connection) -> int:
    rows = await conn.fetch(
        """
        UPDATE app_notifications
        SET read_at = NOW()
        WHERE read_at IS NULL
          AND (expires_at IS NULL OR expires_at > NOW())
        RETURNING id
        """
    )
    return len(rows)


async def unread_notification_count(conn: asyncpg.Connection) -> int:
    return int(
        await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM app_notifications
            WHERE read_at IS NULL
              AND (expires_at IS NULL OR expires_at > NOW())
            """
        )
    )


def _default_ttl_hours(severity: str) -> int | None:
    if severity == "warning":
        return WARNING_TTL_HOURS
    if severity == "success":
        return SUCCESS_TTL_HOURS
    if severity == "info":
        return INFO_TTL_HOURS
    return None


# _send_notification_email removed — all alerts go through push channels only
