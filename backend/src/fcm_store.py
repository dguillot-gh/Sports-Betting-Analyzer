"""
FCM device token storage and Firebase Cloud Messaging broadcast.

Stores FCM device tokens in PostgreSQL and sends native push
notifications to all registered Android/iOS devices.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger(__name__)

# Path to the Firebase service account JSON file
FIREBASE_SERVICE_ACCOUNT_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "")

# Module-level flag to avoid re-initializing Firebase
_firebase_initialized = False

FCM_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS fcm_device_tokens (
    id BIGSERIAL PRIMARY KEY,
    device_token TEXT NOT NULL UNIQUE,
    platform TEXT NOT NULL DEFAULT 'android',
    app_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fcm_device_tokens_token
    ON fcm_device_tokens(device_token);
"""


async def ensure_fcm_schema(database_url: str) -> None:
    conn = None
    try:
        conn = await asyncpg.connect(database_url)
        await conn.execute(FCM_SCHEMA_SQL)
    finally:
        if conn:
            await conn.close()


async def save_device_token(
    database_url: str,
    *,
    device_token: str,
    platform: str = "android",
    app_version: str = "",
) -> None:
    conn = None
    try:
        conn = await asyncpg.connect(database_url)
        await conn.execute(
            """
            INSERT INTO fcm_device_tokens (device_token, platform, app_version)
            VALUES ($1, $2, $3)
            ON CONFLICT (device_token)
            DO UPDATE SET platform = $2, app_version = $3, last_seen_at = NOW()
            """,
            device_token,
            platform,
            app_version,
        )
        logger.info("FCM device token saved: %s...", device_token[:20])
    except Exception as exc:
        logger.warning("Failed to save FCM device token: %s", exc)
    finally:
        if conn:
            await conn.close()


async def remove_device_token(database_url: str, device_token: str) -> bool:
    conn = None
    try:
        conn = await asyncpg.connect(database_url)
        result = await conn.execute(
            "DELETE FROM fcm_device_tokens WHERE device_token = $1", device_token
        )
        return result.endswith("1")
    except Exception as exc:
        logger.warning("Failed to remove FCM device token: %s", exc)
        return False
    finally:
        if conn:
            await conn.close()


async def get_all_device_tokens(database_url: str) -> List[str]:
    conn = None
    try:
        conn = await asyncpg.connect(database_url)
        rows = await conn.fetch("SELECT device_token FROM fcm_device_tokens")
        return [r["device_token"] for r in rows]
    except Exception as exc:
        logger.warning("Failed to fetch FCM device tokens: %s", exc)
        return []
    finally:
        if conn:
            await conn.close()


def _init_firebase() -> bool:
    """Initialize Firebase Admin SDK. Returns True if successful."""
    global _firebase_initialized
    if _firebase_initialized:
        return True

    if not FIREBASE_SERVICE_ACCOUNT_JSON:
        logger.debug("FCM not configured (FIREBASE_SERVICE_ACCOUNT_JSON not set).")
        return False

    try:
        import firebase_admin
        from firebase_admin import credentials

        # Support both file path and inline JSON
        if os.path.isfile(FIREBASE_SERVICE_ACCOUNT_JSON):
            cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT_JSON)
        else:
            cred = credentials.Certificate(json.loads(FIREBASE_SERVICE_ACCOUNT_JSON))

        firebase_admin.initialize_app(cred)
        _firebase_initialized = True
        logger.info("Firebase Admin SDK initialized successfully.")
        return True
    except Exception as exc:
        logger.warning("Failed to initialize Firebase Admin SDK: %s", exc)
        return False


async def send_fcm_to_all(
    database_url: str,
    *,
    title: str,
    message: str,
    severity: str = "info",
    url: str = "/notifications",
) -> int:
    """
    Send an FCM notification to all registered devices.
    Returns the number of successful sends.
    """
    if not _init_firebase():
        return 0

    try:
        from firebase_admin import messaging
    except ImportError:
        logger.debug("firebase-admin not installed — skipping FCM.")
        return 0

    tokens = await get_all_device_tokens(database_url)
    if not tokens:
        return 0

    notification = messaging.Notification(
        title=title,
        body=message,
    )

    data = {
        "severity": severity,
        "url": url,
        "click_action": "OPEN_NOTIFICATIONS",
    }

    # Send to up to 500 tokens at a time (FCM limit)
    sent = 0
    stale_tokens = []

    for i in range(0, len(tokens), 500):
        batch = tokens[i : i + 500]
        multicast = messaging.MulticastMessage(
            notification=notification,
            data=data,
            tokens=batch,
        )

        try:
            response = messaging.send_each_for_multicast(multicast)
            sent += response.success_count

            # Collect stale tokens for cleanup
            for idx, send_response in enumerate(response.responses):
                if send_response.exception is not None:
                    error_code = getattr(send_response.exception, "code", "")
                    if error_code in (
                        "NOT_FOUND",
                        "UNREGISTERED",
                        "INVALID_ARGUMENT",
                    ):
                        stale_tokens.append(batch[idx])

        except Exception as exc:
            logger.warning("FCM multicast send failed: %s", exc)

    # Clean up stale tokens
    for token in stale_tokens:
        await remove_device_token(database_url, token)
        logger.info("Removed stale FCM token: %s...", token[:20])

    logger.info("FCM sent to %d/%d devices.", sent, len(tokens))
    return sent
