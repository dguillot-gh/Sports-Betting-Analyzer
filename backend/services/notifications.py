"""
Notification Service
Handles sending alerts via Pushover (and potentially Email/SMS in future).
"""

import logging
import aiohttp
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Config
PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

class NotificationService:
    
    @staticmethod
    async def send_pushover_notification(title: str, message: str, priority: int = 0) -> bool:
        """
        Send a notification via Pushover.
        Priority: -1 (Low), 0 (Normal), 1 (High)
        """
        if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
            # Silent warning to avoid log spam if just not configured
            # logger.warning("Pushover credentials not configured.")
            return False

        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "token": PUSHOVER_API_TOKEN,
                    "user": PUSHOVER_USER_KEY,
                    "title": title,
                    "message": message,
                    "priority": priority,
                    "html": 1
                }
                
                async with session.post(PUSHOVER_API_URL, data=payload) as response:
                    if response.status == 200:
                        logger.info(f"Pushover notification sent: {title}")
                        return True
                    else:
                        resp_text = await response.text()
                        logger.error(f"Pushover failed ({response.status}): {resp_text}")
                        return False
                        
        except Exception as e:
            logger.error(f"Error sending Pushover notification: {e}")
            return False

    @staticmethod
    async def send_summary_report(results: list):
        """
        Send a formatted summary report of import jobs.
        """
        if not results:
            return

        lines = []
        overall_success = True
        
        for res in results:
            icon = "🟢" if res['success'] else "🔴"
            status = "Success" if res['success'] else "Failed"
            duration = f"{res.get('duration', 0):.1f}s"
            
            line = f"{icon} <b>{res['sport'].upper()}</b>: {status} ({duration})"
            if not res['success']:
                line += f"\n<i>Err: {res.get('error', 'Unknown')}</i>"
                overall_success = False
            else:
                line += f"\n<small>{res.get('rows', 0)} rows, {res.get('files', 0)} files</small>"
            
            lines.append(line)
            
        message = "\n\n".join(lines)
        title = "✅ Import Summary" if overall_success else "⚠️ Import Issues Detected"
        priority = 0 if overall_success else 1
        
        await NotificationService.send_pushover_notification(title, message, priority)
