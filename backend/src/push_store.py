"""
Web Push subscription storage and broadcast.

Stores browser push subscriptions in PostgreSQL and sends Web Push
notifications to all subscribers when new app notifications are created.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger(__name__)

# VAPID config — generate once with:
#   python -c "from pywebpush import webpush; from py_vapid import Vapid; v=Vapid(); v.generate_keys(); print('PRIVATE:', v.private_pem()); print('PUBLIC:', v.public_key)"
# Or use the helper script: python -m scripts.generate_vapid_keys
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_CLAIMS_EMAIL = os.getenv("VAPID_CLAIMS_EMAIL", "")


PUSH_SUBSCRIPTIONS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id BIGSERIAL PRIMARY KEY,
    endpoint TEXT NOT NULL UNIQUE,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_push_subscriptions_endpoint
    ON push_subscriptions(endpoint);
"""


async def ensure_push_schema(database_url: str) -> None:
    conn = None
    try:
        conn = await asyncpg.connect(database_url)
        await conn.execute(PUSH_SUBSCRIPTIONS_SCHEMA_SQL)
    finally:
        if conn:
            await conn.close()


async def save_subscription(
    database_url: str,
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str = "",
) -> None:
    conn = None
    try:
        conn = await asyncpg.connect(database_url)
        await conn.execute(
            """
            INSERT INTO push_subscriptions (endpoint, p256dh, auth, user_agent)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (endpoint)
            DO UPDATE SET p256dh = $2, auth = $3, user_agent = $4
            """,
            endpoint,
            p256dh,
            auth,
            user_agent,
        )
        logger.info("Push subscription saved: %s...", endpoint[:60])
    except Exception as exc:
        logger.warning("Failed to save push subscription: %s", exc)
    finally:
        if conn:
            await conn.close()


async def remove_subscription(database_url: str, endpoint: str) -> bool:
    conn = None
    try:
        conn = await asyncpg.connect(database_url)
        result = await conn.execute(
            "DELETE FROM push_subscriptions WHERE endpoint = $1", endpoint
        )
        return result.endswith("1")
    except Exception as exc:
        logger.warning("Failed to remove push subscription: %s", exc)
        return False
    finally:
        if conn:
            await conn.close()


async def get_all_subscriptions(database_url: str) -> List[Dict[str, Any]]:
    conn = None
    try:
        conn = await asyncpg.connect(database_url)
        rows = await conn.fetch(
            "SELECT endpoint, p256dh, auth FROM push_subscriptions"
        )
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("Failed to fetch push subscriptions: %s", exc)
        return []
    finally:
        if conn:
            await conn.close()


async def send_web_push_to_all(
    database_url: str,
    *,
    title: str,
    message: str,
    severity: str = "info",
    url: str = "/notifications",
) -> int:
    """
    Send a Web Push notification to all subscribers.
    Returns the number of successful sends.
    Silently skips if VAPID keys are not configured.
    """
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY or not VAPID_CLAIMS_EMAIL:
        logger.debug("Web Push not configured (VAPID keys missing) — skipping.")
        return 0

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        logger.debug("pywebpush not installed — skipping Web Push.")
        return 0

    subscriptions = await get_all_subscriptions(database_url)
    if not subscriptions:
        return 0

    payload = json.dumps({
        "title": title,
        "body": message,
        "icon": "/icon-192.png",
        "badge": "/icon-badge.png",
        "url": url,
        "severity": severity,
    })

    vapid_claims = {"sub": f"mailto:{VAPID_CLAIMS_EMAIL}"}
    sent = 0
    stale_endpoints = []

    for sub in subscriptions:
        subscription_info = {
            "endpoint": sub["endpoint"],
            "keys": {
                "p256dh": sub["p256dh"],
                "auth": sub["auth"],
            },
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=vapid_claims,
            )
            sent += 1
        except WebPushException as exc:
            # 410 Gone or 404 = subscription expired, clean it up
            if hasattr(exc, "response") and exc.response is not None:
                status = exc.response.status_code
                if status in (404, 410):
                    stale_endpoints.append(sub["endpoint"])
                    continue
            logger.warning("Web Push failed for %s...: %s", sub["endpoint"][:40], exc)
        except Exception as exc:
            logger.warning("Web Push unexpected error: %s", exc)

    # Clean up stale subscriptions
    for endpoint in stale_endpoints:
        await remove_subscription(database_url, endpoint)
        logger.info("Removed stale push subscription: %s...", endpoint[:40])

    logger.info("Web Push sent to %d/%d subscribers.", sent, len(subscriptions))
    return sent
