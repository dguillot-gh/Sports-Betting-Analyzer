"""
Web Push API endpoints.

Allows the frontend to subscribe/unsubscribe for browser push notifications
and retrieve the public VAPID key for PushManager.subscribe().
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.config import DATABASE_URL
from src.push_store import (
    VAPID_PUBLIC_KEY,
    ensure_push_schema,
    save_subscription,
    remove_subscription,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/push", tags=["Web Push"])


class PushSubscriptionBody(BaseModel):
    endpoint: str
    keys: dict  # {"p256dh": "...", "auth": "..."}
    user_agent: Optional[str] = ""


class UnsubscribeBody(BaseModel):
    endpoint: str


@router.get("/vapid-key")
async def get_vapid_public_key():
    """Return the VAPID public key so the frontend can subscribe."""
    if not VAPID_PUBLIC_KEY:
        raise HTTPException(
            status_code=503,
            detail="Web Push not configured (VAPID_PUBLIC_KEY not set)",
        )
    return {"public_key": VAPID_PUBLIC_KEY}


@router.post("/subscribe")
async def subscribe(body: PushSubscriptionBody):
    """Save a browser push subscription."""
    if not body.endpoint or not body.keys.get("p256dh") or not body.keys.get("auth"):
        raise HTTPException(status_code=400, detail="Invalid subscription data")

    try:
        await ensure_push_schema(DATABASE_URL)
        await save_subscription(
            DATABASE_URL,
            endpoint=body.endpoint,
            p256dh=body.keys["p256dh"],
            auth=body.keys["auth"],
            user_agent=body.user_agent or "",
        )
        return {"success": True}
    except Exception as exc:
        logger.error("Failed to save push subscription: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to save subscription")


@router.post("/unsubscribe")
async def unsubscribe(body: UnsubscribeBody):
    """Remove a browser push subscription."""
    try:
        removed = await remove_subscription(DATABASE_URL, body.endpoint)
        return {"success": removed}
    except Exception as exc:
        logger.error("Failed to remove push subscription: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to remove subscription")
