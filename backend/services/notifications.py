"""
Notification Service
Handles sending alerts via Pushover and detailed HTML email reports.
"""

import logging
import aiohttp
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional, List, Dict, Any

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
    async def send_summary_report(results: list):
        """
        Send BOTH:
        1. Short Pushover notification (counts + status)
        2. Detailed HTML email report (per-sport breakdowns)
        """
        if not results:
            return

        total_duration = sum(r.get('duration', 0) for r in results)
        success_count = sum(1 for r in results if r.get('success'))
        fail_count = len(results) - success_count
        overall_success = fail_count == 0
        total_rows = sum(r.get('rows', 0) for r in results)

        # Sport display name mapping
        sport_names = {
            "ncaab": "College Basketball",
            "nba": "NBA",
            "nfl": "NFL",
            "nascar": "NASCAR",
            "baseball": "College Baseball Stats",
            "nhl": "NHL",
            "baseball_results": "Baseball Results (ESPN)",
            "baseball_training": "Baseball Model Training",
        }

        # =============================================
        # 1. PUSHOVER — Short & sweet
        # =============================================
        push_lines = []
        for res in results:
            display = sport_names.get(res.get('sport', ''), res.get('sport', '').upper())
            icon = "✅" if res.get('success') else "❌"
            rows = res.get('rows', 0)
            extra = ""
            if res.get('games_inserted'):
                extra = f" ({res['games_inserted']} games)"
            elif res.get('detail'):
                extra = f" ({res['detail']})"
            elif rows > 0:
                extra = f" ({rows:,} rows)"
            push_lines.append(f"{icon} {display}{extra}")

        push_msg = "\n".join(push_lines)
        push_msg += f"\n\n⏱ {total_duration:.0f}s total"

        if overall_success:
            push_title = f"✅ Import Complete ({success_count}/{len(results)})"
            push_priority = 0
        else:
            push_title = f"⚠️ Import Issues ({fail_count} failed)"
            push_priority = 1

        await NotificationService.send_pushover_notification(push_title, push_msg, push_priority)

        # =============================================
        # 2. EMAIL — Detailed HTML report
        # =============================================
        timestamp = datetime.now().strftime("%B %d, %Y at %I:%M %p")
        
        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
                .container {{ max-width: 650px; margin: 0 auto; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
                .header {{ background: {'#22c55e' if overall_success else '#ef4444'}; color: white; padding: 24px 30px; }}
                .header h1 {{ margin: 0; font-size: 22px; }}
                .header p {{ margin: 5px 0 0; opacity: 0.9; font-size: 14px; }}
                .body {{ padding: 20px 30px; }}
                .summary-bar {{ display: flex; gap: 20px; margin-bottom: 20px; padding: 15px; background: #f8f9fa; border-radius: 8px; }}
                .summary-item {{ text-align: center; }}
                .summary-item .value {{ font-size: 24px; font-weight: bold; color: #1a1a1a; }}
                .summary-item .label {{ font-size: 12px; color: #666; text-transform: uppercase; }}
                .sport-card {{ border: 1px solid #e5e7eb; border-radius: 8px; margin-bottom: 12px; overflow: hidden; }}
                .sport-header {{ padding: 12px 16px; font-weight: 600; display: flex; justify-content: space-between; align-items: center; }}
                .sport-header.success {{ background: #f0fdf4; border-left: 4px solid #22c55e; }}
                .sport-header.failed {{ background: #fef2f2; border-left: 4px solid #ef4444; }}
                .sport-details {{ padding: 8px 16px 12px; font-size: 13px; color: #555; }}
                .sport-details .detail-row {{ padding: 3px 0; }}
                .error-text {{ color: #dc2626; font-style: italic; }}
                .game-list {{ font-size: 12px; color: #666; font-family: monospace; }}
                .footer {{ padding: 16px 30px; background: #f8f9fa; font-size: 12px; color: #888; text-align: center; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>{'✅' if overall_success else '⚠️'} Nightly Import Report</h1>
                    <p>{timestamp}</p>
                </div>
                <div class="body">
                    <div class="summary-bar">
                        <div class="summary-item">
                            <div class="value">{success_count}/{len(results)}</div>
                            <div class="label">Succeeded</div>
                        </div>
                        <div class="summary-item">
                            <div class="value">{total_rows:,}</div>
                            <div class="label">Total Rows</div>
                        </div>
                        <div class="summary-item">
                            <div class="value">{total_duration:.0f}s</div>
                            <div class="label">Duration</div>
                        </div>
                    </div>
        """

        for res in results:
            display = sport_names.get(res.get('sport', ''), res.get('sport', '').upper())
            success = res.get('success', False)
            duration = f"{res.get('duration', 0):.1f}s"
            rows = res.get('rows', 0)
            css_class = "success" if success else "failed"
            icon = "✅" if success else "❌"

            html += f"""
                    <div class="sport-card">
                        <div class="sport-header {css_class}">
                            <span>{icon} {display}</span>
                            <span style="font-size:13px;color:#888;">{duration}</span>
                        </div>
                        <div class="sport-details">
            """

            if success:
                if rows > 0:
                    html += f'<div class="detail-row">📊 <strong>{rows:,}</strong> rows imported</div>'
                
                # Sport-specific details
                if res.get('games_fetched'):
                    html += f'<div class="detail-row">🏟️ {res["games_fetched"]} games fetched, <strong>{res.get("games_inserted", 0)}</strong> new games stored</div>'
                if res.get('detail'):
                    html += f'<div class="detail-row">🤖 {res["detail"]}</div>'
                
                # Show game results if available
                if res.get('game_details'):
                    html += '<div class="detail-row" style="margin-top:8px;"><strong>Game Results:</strong></div>'
                    html += '<div class="game-list">'
                    for game in res['game_details'][:15]:
                        home = game.get('home_team', '?')
                        away = game.get('away_team', '?')
                        hs = game.get('home_score', 0)
                        aws = game.get('away_score', 0)
                        html += f'<div>{home} {hs} - {aws} {away}</div>'
                    if len(res.get('game_details', [])) > 15:
                        html += f'<div style="color:#999;">...and {len(res["game_details"]) - 15} more</div>'
                    html += '</div>'
                
                if not rows and not res.get('games_fetched') and not res.get('detail'):
                    html += '<div class="detail-row">✓ Completed successfully</div>'
            else:
                error = res.get('error', 'Unknown error')
                html += f'<div class="detail-row error-text">{error}</div>'

            html += """
                        </div>
                    </div>
            """

        html += f"""
                </div>
                <div class="footer">
                    Sports Betting Analyzer • Automated Import Report
                </div>
            </div>
        </body>
        </html>
        """

        email_subject = f"{'✅' if overall_success else '⚠️'} Import Report — {timestamp}"
        NotificationService.send_email_report(email_subject, html)
