"""
Notification Service
Handles sending alerts via Pushover, in-app notifications, and HTML email reports.
"""

import logging
import aiohttp
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional, List, Dict, Any

from src.config import DATABASE_URL
from src.notification_store import insert_notification

logger = logging.getLogger(__name__)

# Pushover Config
PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

# Email Config (optional — skips if not set)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")       # e.g. yourname@gmail.com
SMTP_PASS = os.getenv("SMTP_PASS")       # App password (not regular password)
REPORT_EMAIL_TO = os.getenv("REPORT_EMAIL_TO")  # Where to send reports
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost")  # Base URL for mobile UI


class NotificationService:
    
    @staticmethod
    async def send_pushover_notification(title: str, message: str, priority: int = 0) -> bool:
        """
        Send a notification via Pushover.
        Priority: -1 (Low), 0 (Normal), 1 (High)
        """
        if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
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
    def send_email_report(subject: str, html_body: str) -> bool:
        """
        Send a detailed HTML email report via SMTP.
        Returns False silently if email is not configured.
        """
        if not SMTP_USER or not SMTP_PASS or not REPORT_EMAIL_TO:
            logger.debug("Email not configured — skipping email report.")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"Sports Betting Analyzer <{SMTP_USER}>"
            msg["To"] = REPORT_EMAIL_TO

            msg.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_USER, REPORT_EMAIL_TO, msg.as_string())

            logger.info(f"Email report sent to {REPORT_EMAIL_TO}: {subject}")
            return True

        except Exception as e:
            logger.error(f"Error sending email report: {e}")
            return False

    @staticmethod
    async def send_summary_report(results: list, perf_summary: dict = None):
        """
        Send BOTH:
        1. Short Pushover notification
        2. Premium HTML email report with Performance Metrics
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

        # 1. PUSHOVER - Legacy (will be removed once Web Push is validated)
        push_lines = [f"{'✅' if r.get('success') else '❌'} {sport_names.get(r['sport'], r['sport'].upper())}" for r in results]
        push_msg = "\n".join(push_lines) + f"\n\n⏱ {total_duration:.0f}s | Score: {health_score}%"
        push_title = f"{'✅' if overall_success else '⚠️'} Import Report"
        await NotificationService.send_pushover_notification(push_title, push_msg, 0 if overall_success else 1)

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

        # 3. PREMIUM EMAIL — only on failure
        if not overall_success:
            NotificationService._send_failure_email(results, health_score, health_color, perf_summary, sport_names)

    @staticmethod
    def _send_failure_email(results, health_score, health_color, perf_summary, sport_names):
        """Send the detailed HTML email report. Only called when imports fail."""
        success_count = sum(1 for r in results if r.get('success'))
        fail_count = len(results) - success_count
        total_rows = sum(r.get('rows', 0) for r in results)
        timestamp = datetime.now().strftime("%B %d, %Y")
        time_str = datetime.now().strftime("%I:%M %p %Z")
        
        # Performance section
        perf_html = ""
        if perf_summary and not perf_summary.get("error"):
            p = perf_summary
            perf_html = f"""
            <div style="background: #1e293b; color: white; padding: 25px; border-radius: 16px; margin-bottom: 30px; box-shadow: 0 4px 20px rgba(0,0,0,0.1);">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                    <span style="font-size: 14px; text-transform: uppercase; letter-spacing: 1px; color: #94a3b8;">Prediction Performance (Last 24h)</span>
                    <span style="background: {health_color}; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 700;">{health_score}% SYSTEM HEALTH</span>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px; text-align: center;">
                    <div>
                        <div style="font-size: 28px; font-weight: 800; color: #38bdf8;">{p['wins']}-{p['losses']}</div>
                        <div style="font-size: 11px; color: #94a3b8;">W/L COUNT</div>
                    </div>
                    <div>
                        <div style="font-size: 28px; font-weight: 800; color: {'#4ade80' if p['profit'] >= 0 else '#fb7185'};">{'+' if p['profit'] >= 0 else ''}{p['profit']:.2f}</div>
                        <div style="font-size: 11px; color: #94a3b8;">NET PROFIT (u)</div>
                    </div>
                    <div>
                        <div style="font-size: 28px; font-weight: 800; color: #818cf8;">{p['roi']}%</div>
                        <div style="font-size: 11px; color: #94a3b8;">ROI</div>
                    </div>
                </div>
            </div>
            """

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                @media only screen and (max-width: 600px) {{
                    .container {{ padding: 10px !important; }}
                    .summary-grid {{ grid-template-columns: 1fr !important; }}
                }}
            </style>
        </head>
        <body style="font-family: 'Inter', -apple-system, sans-serif; background-color: #f8fafc; margin: 0; padding: 40px 20px;">
            <div class="container" style="max-width: 650px; margin: 0 auto;">
                <!-- Header -->
                <div style="margin-bottom: 30px; text-align: center;">
                    <h1 style="margin: 0; color: #0f172a; font-size: 24px; font-weight: 800;">Morning Report</h1>
                    <p style="margin: 5px 0 0; color: #64748b; font-size: 14px;">{timestamp} • {time_str}</p>
                </div>

                {perf_html}

                <!-- Import Details -->
                <div style="background: white; border-radius: 16px; padding: 0; overflow: hidden; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
                    <div style="padding: 20px 25px; border-bottom: 1px solid #f1f5f9; background: #fcfdfe;">
                        <h2 style="margin: 0; font-size: 16px; color: #1e293b;">Data Import Status</h2>
                    </div>
                    
                    <table style="width: 100%; border-collapse: collapse;">
        """

        for res in results:
            display = sport_names.get(res.get('sport', ''), res.get('sport', '').upper())
            success = res.get('success', False)
            duration = f"{res.get('duration', 0):.0f}s"
            rows = f"{res.get('rows', 0):,}"
            icon = "✅" if success else "❌"
            row_bg = "white" if success else "#fff1f2"

            # Record Breakdown
            new_val = res.get('new', 0)
            updated_val = res.get('updated', 0)
            breakdown_html = ""
            if new_val > 0 or updated_val > 0:
                breakdown_html = f"""
                <div style="font-size: 10px; color: #64748b; margin-top: 2px;">
                    <span style="color: #16a34a;">+{new_val:,} New</span> • 
                    <span style="color: #2563eb;">{updated_val:,} Sync</span>
                </div>
                """

            html += f"""
                        <tr style="background: {row_bg}; border-bottom: 1px solid #f1f5f9;">
                            <td style="padding: 16px 25px;">
                                <div style="font-weight: 600; color: #334155; font-size: 14px;">{icon} {display}</div>
                                <div style="font-size: 12px; color: #94a3b8;">{duration} active sync</div>
                            </td>
                            <td style="padding: 16px 25px; text-align: right;">
                                <div style="font-weight: 700; color: {'#0f172a' if success else '#e11d48'}; font-size: 14px;">{rows if success else 'FAILED'}</div>
                                {breakdown_html}
                            </td>
                        </tr>
            """
            
            # Error Detail Row
            if not success:
                error_msg = res.get('error', 'Unknown error occurred')
                traceback_data = res.get('traceback', '')
                
                html += f"""
                        <tr>
                            <td colspan="2" style="padding: 0 25px 16px 25px; background: #fff1f2;">
                                <div style="border-left: 3px solid #ef4444; padding: 10px 15px; background: #fee2e2; border-radius: 4px;">
                                    <div style="font-size: 13px; color: #991b1b; font-weight: 700; margin-bottom: 4px;">Error: {error_msg}</div>
                                    <details style="cursor: pointer;">
                                        <summary style="font-size: 11px; color: #b91c1c; text-decoration: underline; margin-bottom: 8px;">View Full Debug Info</summary>
                                        <pre style="font-family: 'Courier New', monospace; font-size: 10px; color: #7f1d1d; white-space: pre-wrap; margin: 0; padding-top: 5px; border-top: 1px solid #fca5a5;">{traceback_data}</pre>
                                    </details>
                                </div>
                            </td>
                        </tr>
                """

        html += f"""
                    </table>
                </div>

                <!-- Footer / CTA -->
                <div style="margin-top: 30px; text-align: center;">
                    <a href="{PUBLIC_URL}/dashboard" style="display: inline-block; background: #2563eb; color: white; padding: 12px 30px; border-radius: 12px; font-weight: 600; text-decoration: none; font-size: 14px; margin-bottom: 20px;">Open Mobile Dashboard</a>
                    <div style="font-size: 12px; color: #94a3b8;">
                        Total Database Size: <strong>{perf_summary.get('db_total_rows', 0):,}</strong> records<br>
                        Sports Betting Analyzer • Automated System Reporting
                    </div>
                </div>
            </div>
        </body>
        </html>
        """

        email_subject = f"⚠️ Import Failure Report: {health_score}% Success"
        NotificationService.send_email_report(email_subject, html)
