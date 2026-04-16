"""
Notification Service
Handles sending alerts via in-app notifications and push (FCM/Web Push).
Email reports have been removed — all alerts go through push channels only.
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from src.config import DATABASE_URL
from src.notification_store import insert_notification

logger = logging.getLogger(__name__)


class NotificationService:

    @staticmethod
    async def send_summary_report(results: list, perf_summary: dict = None):
        """
        Send import report via in-app notification (DB + push via FCM/Web Push).
        """
        if not results:
            return

        total_duration = sum(r.get('duration', 0) for r in results)
        success_count = sum(1 for r in results if r.get('success'))
        fail_count = len(results) - success_count
        overall_success = fail_count == 0
        total_rows = sum(r.get('rows', 0) for r in results)
        
        # Calculate Health Score
        health_score = int((success_count / len(results)) * 100) if results else 0
        health_color = "#22c55e" if health_score >= 90 else "#f59e0b" if health_score >= 70 else "#ef4444"

        # Sport display name mapping
        sport_names = {
            "ncaab": "College Basketball",
            "nba": "NBA",
            "nfl": "NFL",
            "nascar": "NASCAR",
            "baseball": "College Baseball",
            "nhl": "NHL",
            "baseball_results": "Live Score Scraper",
            "baseball_training": "XGBoost Trainer",
            "cfb": "College Football",
        }

        # Build rich notification message matching email detail level
        push_lines = [f"{'✅' if r.get('success') else '❌'} {sport_names.get(r['sport'], r['sport'].upper())}: {r.get('rows', 0):,} rows ({r.get('duration', 0):.0f}s)" for r in results]
        push_msg = "\n".join(push_lines) + f"\n\n📊 Health: {health_score}% | ⏱ {total_duration:.0f}s | 📦 {total_rows:,} total rows"
        push_title = f"{'✅' if overall_success else '⚠️'} Import Report — {success_count}/{len(results)} Passed"

        # 2. IN-APP NOTIFICATION — always write to app_notifications DB
        await insert_notification(
            DATABASE_URL,
            severity="success" if overall_success else "warning",
            category="import",
            title=push_title,
            message=push_msg,
            source="scheduler.send_summary_report",
            metadata={
                "health_score": health_score,
                "total_duration": round(total_duration, 1),
                "total_rows": total_rows,
                "success_count": success_count,
                "fail_count": fail_count,
                "sports": [
                    {
                        "sport": r.get("sport"),
                        "success": r.get("success"),
                        "rows": r.get("rows", 0),
                        "duration": round(r.get("duration", 0), 1),
                    }
                    for r in results
                ],
            },
        )

        # Email sending removed — all alerts go through push channels only
