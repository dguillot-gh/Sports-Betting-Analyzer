"""
FCM device registration API endpoints.

Allows the MAUI app to register/unregister its FCM device token
so the backend can send native push notifications.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.config import DATABASE_URL
from src.fcm_store import (
    ensure_fcm_schema,
    save_device_token,
    remove_device_token,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/fcm", tags=["FCM Push"])


class RegisterTokenBody(BaseModel):
    device_token: str
    platform: str = "android"
    app_version: Optional[str] = ""


class UnregisterTokenBody(BaseModel):
    device_token: str


@router.post("/register")
async def register_token(body: RegisterTokenBody):
    """Register a device FCM token for push notifications."""
    if not body.device_token:
        raise HTTPException(status_code=400, detail="device_token is required")

    try:
        await ensure_fcm_schema(DATABASE_URL)
        await save_device_token(
            DATABASE_URL,
            device_token=body.device_token,
            platform=body.platform,
            app_version=body.app_version or "",
        )
        return {"success": True}
    except Exception as exc:
        logger.error("Failed to register FCM token: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to register token")


@router.post("/unregister")
async def unregister_token(body: UnregisterTokenBody):
    """Remove a device FCM token."""
    try:
        removed = await remove_device_token(DATABASE_URL, body.device_token)
        return {"success": removed}
    except Exception as exc:
        logger.error("Failed to unregister FCM token: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to unregister token")
