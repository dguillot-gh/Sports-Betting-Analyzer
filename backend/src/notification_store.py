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
        # Fire-and-forget push + email broadcasts for ALL notifications
        sev_lower = (severity or "info").lower()
        try:
            import asyncio
            from src.push_store import send_web_push_to_all
            from src.fcm_store import send_fcm_to_all

            loop = asyncio.get_running_loop()
            loop.create_task(
                send_web_push_to_all(
                    database_url,
                    title=title,
                    message=message,
                    severity=sev_lower,
                )
            )
            loop.create_task(
                send_fcm_to_all(
                    database_url,
                    title=title,
                    message=message,
                    severity=sev_lower,
                )
            )
            # Also fire-and-forget a simple email for every notification
            loop.run_in_executor(
                None,
                _send_notification_email,
                title,
                message,
                sev_lower,
                category,
            )
        except RuntimeError:
            pass  # No running loop (script context)
    except Exception as exc:
        logger.warning("Failed to insert notification: %s", exc)
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


def _send_notification_email(title: str, message: str, severity: str, category: str) -> None:
    """
    Fire-and-forget email for every notification.
    Uses the same SMTP config as the main email reports.
    Runs synchronously in a thread-safe callback.
    """
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    report_to = os.getenv("REPORT_EMAIL_TO")
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))

    if not smtp_user or not smtp_pass or not report_to:
        return

    severity_emoji = {"error": "🔴", "warning": "🟡", "success": "🟢", "info": "🔵"}.get(severity, "📬")
    subject = f"{severity_emoji} [{severity.upper()}] {title}"

    html_body = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: #0f172a; color: white; padding: 16px 20px; border-radius: 12px 12px 0 0;">
            <h2 style="margin: 0; font-size: 16px;">{severity_emoji} {title}</h2>
            <p style="margin: 4px 0 0; font-size: 12px; color: #94a3b8;">{category} • {severity.upper()}</p>
        </div>
        <div style="background: white; padding: 20px; border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 12px 12px;">
            <p style="white-space: pre-wrap; color: #334155; font-size: 14px; line-height: 1.6;">{message}</p>
        </div>
    </div>
    """

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"Sports Betting Analyzer <{smtp_user}>"
        msg["To"] = report_to
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, report_to, msg.as_string())

        logger.info("Notification email sent: %s", title)
    except Exception as exc:
        logger.warning("Failed to send notification email: %s", exc)
