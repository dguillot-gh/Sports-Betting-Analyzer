#!/usr/bin/env python3
"""
Test script to send an FCM native push notification to all registered devices.
"""

import asyncio
import os
import sys

# Ensure the backend directory is in the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.config import DATABASE_URL
from src.fcm_store import send_fcm_to_all

async def main():
    print("Sending test FCM push notification constraint...")
    
    count = await send_fcm_to_all(
        DATABASE_URL,
        title="FCM Test Notification",
        message="This is a test native push notification from the Sports Betting Analyzer backend via Firebase Cloud Messaging!",
        severity="info"
    )
    
    if count > 0:
        print(f"Success! Notification sent to {count} device(s).")
    else:
        print("No devices were sent a notification. Are there any devices registered in fcm_device_tokens?")

if __name__ == "__main__":
    asyncio.run(main())
