"""
Notification Service
Handles sending alerts via in-app notifications, push (FCM/Web Push),
and SMTP email with CSV attachment of detailed import records.
"""

import csv
import io
import zipfile
import logging
import smtplib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, List, Dict, Any

CST = ZoneInfo("America/Chicago")

from src.config import DATABASE_URL, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, REPORT_EMAIL_TO
from src.notification_store import insert_notification

logger = logging.getLogger(__name__)

# Sport display name mapping (shared across methods)
_SPORT_NAMES = {
    "ncaab": "College Basketball",
    "nba": "NBA",
    "nba_backtest": "NBA Backtest",
    "nfl": "NFL",
    "nascar": "NASCAR",
    "baseball": "College Baseball",
    "nhl": "NHL",
    "baseball_results": "Live Score Scraper",
    "baseball_training": "XGBoost Trainer",
    "cfb": "College Football",
    "mlb_stats": "MLB Stats",
    "mlb_results": "MLB Results",
    "mlb_training": "MLB Training",
    "nascar_supplemental": "NASCAR Supplemental",
}


class NotificationService:

    @staticmethod
    async def send_summary_report(
        results: list,
        perf_summary: dict = None,
        import_records: list = None,
    ):
        """
        Send import report via:
          1. In-app notification (DB + push)
          2. SMTP email with HTML summary + CSV attachment
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

        # Build rich notification message matching email detail level
        push_lines = [f"{'✅' if r.get('success') else '❌'} {_SPORT_NAMES.get(r['sport'], r['sport'].upper())}: {r.get('rows', 0):,} rows ({r.get('duration', 0):.0f}s)" for r in results]
        push_msg = "\n".join(push_lines) + f"\n\n📊 Health: {health_score}% | ⏱ {total_duration:.0f}s | 📦 {total_rows:,} total rows"
        push_title = f"{'✅' if overall_success else '⚠️'} Import Report — {success_count}/{len(results)} Passed"

        # 1. IN-APP NOTIFICATION — always write to app_notifications DB
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

        # 2. SMTP EMAIL — only send when something needs attention
        #    (failures, stale data sources, or errors)
        stale_sports = [
            r for r in results
            if r.get('success') and r.get('rows', 0) > 0 and r.get('new', 0) == 0
        ]
        has_problems = fail_count > 0 or len(stale_sports) > 0

        if has_problems:
            logger.info(
                f"Email triggered: {fail_count} failures, {len(stale_sports)} stale. Sending report."
            )
            await NotificationService._send_email_report(
                results, perf_summary, import_records or [], health_score, total_duration, total_rows
            )
        else:
            logger.info(
                f"All {success_count} imports healthy — skipping email. "
                f"Check Data Health page or in-app notifications for details."
            )

    # ------------------------------------------------------------------
    # Email helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _send_email_report(
        results: list,
        perf_summary: dict,
        import_records: list,
        health_score: int,
        total_duration: float,
        total_rows: int,
    ):
        """Build and send the HTML email with CSV attachment via SMTP."""
        if not SMTP_USER or not SMTP_PASS or not REPORT_EMAIL_TO:
            logger.info("SMTP not configured — skipping email report.")
            return

        try:
            now_str = datetime.now(CST).strftime("%Y-%m-%d %I:%M %p CST")
            subject = f"Sports Betting Analyzer — Import Report {now_str}"

            html_body = NotificationService._build_html_body(
                results, perf_summary, health_score, total_duration, total_rows, now_str, len(import_records)
            )

            msg = MIMEMultipart("mixed")
            msg["From"] = SMTP_USER
            msg["To"] = REPORT_EMAIL_TO
            msg["Subject"] = subject

            # HTML body
            msg.attach(MIMEText(html_body, "html", "utf-8"))

            # Zip attachment (CSV + TXT compressed to stay under Gmail 25MB limit)
            if import_records:
                ts = datetime.now(CST).strftime('%Y%m%d_%H%M')
                csv_bytes = NotificationService._build_csv(import_records)
                txt_bytes = NotificationService._build_txt(import_records)
                summary_bytes = NotificationService._build_summary_csv(results)

                zip_buf = io.BytesIO()
                with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr(f"summary_{ts}.csv", summary_bytes)
                    zf.writestr(f"import_records_{ts}.csv", csv_bytes)
                    zf.writestr(f"import_records_{ts}.txt", txt_bytes)
                zip_bytes = zip_buf.getvalue()

                # Gmail hard-limit is 25MB; stay safely under it
                MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 20 MB
                if len(zip_bytes) < MAX_ATTACHMENT_BYTES:
                    attachment = MIMEApplication(zip_bytes, _subtype="zip")
                    attachment.add_header(
                        "Content-Disposition", "attachment",
                        filename=f"import_report_{ts}.zip",
                    )
                    msg.attach(attachment)
                else:
                    logger.warning(
                        f"Zip attachment too large ({len(zip_bytes)/1024/1024:.1f} MB) — "
                        f"skipping attachment to avoid Gmail rejection."
                    )
            else:
                # No detailed records — still attach the per-sport summary
                ts = datetime.now(CST).strftime('%Y%m%d_%H%M')
                summary_bytes = NotificationService._build_summary_csv(results)
                zip_buf = io.BytesIO()
                with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr(f"summary_{ts}.csv", summary_bytes)
                zip_bytes = zip_buf.getvalue()
                attachment = MIMEApplication(zip_bytes, _subtype="zip")
                attachment.add_header(
                    "Content-Disposition", "attachment",
                    filename=f"import_report_{ts}.zip",
                )
                msg.attach(attachment)

            # Send via SMTP (run in thread to avoid blocking the event loop)
            import asyncio
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, NotificationService._smtp_send, msg)

            logger.info(f"Email report sent to {REPORT_EMAIL_TO} ({len(import_records)} records attached).")
        except Exception as e:
            logger.error(f"Failed to send email report: {e}", exc_info=True)

    @staticmethod
    def _smtp_send(msg: MIMEMultipart):
        """Blocking SMTP send — called via run_in_executor."""
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)

    @staticmethod
    def _build_csv(records: list) -> bytes:
        """Generate CSV bytes from import record dicts."""
        buf = io.StringIO()
        fieldnames = ["sport", "action", "season", "series", "entity", "track", "detail"]
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            writer.writerow(rec)
        return buf.getvalue().encode("utf-8")

    @staticmethod
    def _build_txt(records: list) -> bytes:
        """Generate a plain-text formatted log from import records."""
        lines = [f"{'Sport':<20} {'Action':<10} {'Season':<8} {'Series':<12} {'Entity':<30} {'Track':<25} {'Detail'}"]
        lines.append("-" * 130)
        for rec in records:
            lines.append(
                f"{rec.get('sport',''):<20} {rec.get('action',''):<10} "
                f"{str(rec.get('season','')):<8} {rec.get('series',''):<12} "
                f"{str(rec.get('entity',''))[:28]:<30} {str(rec.get('track',''))[:23]:<25} "
                f"{rec.get('detail','')}"
            )
        return "\n".join(lines).encode("utf-8")

    @staticmethod
    def _build_summary_csv(results: list) -> bytes:
        """Generate a per-sport summary CSV showing freshness status."""
        buf = io.StringIO()
        fieldnames = ["sport", "status", "rows", "new", "updated", "duration_s", "error"]
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            name = _SPORT_NAMES.get(r.get("sport", ""), r.get("sport", "").upper())
            rows = r.get("rows", 0)
            new = r.get("new", 0)
            err = r.get("error", "")
            if err:
                status = "ERROR"
            elif new > 0:
                status = "FRESH"
            elif rows > 0:
                status = "STALE"
            else:
                status = "EMPTY"
            writer.writerow({
                "sport": name,
                "status": status,
                "rows": rows,
                "new": new,
                "updated": r.get("updated", 0),
                "duration_s": round(r.get("duration", 0), 1),
                "error": err[:200] if err else "",
            })
        return buf.getvalue().encode("utf-8")

    @staticmethod
    def _build_html_body(
        results: list,
        perf_summary: dict,
        health_score: int,
        total_duration: float,
        total_rows: int,
        now_str: str,
        record_count: int,
    ) -> str:
        """Build a clean HTML email body with summary table and freshness badges."""
        success_count = sum(1 for r in results if r.get("success"))
        fail_count = len(results) - success_count
        health_color = "#22c55e" if health_score >= 90 else "#f59e0b" if health_score >= 70 else "#ef4444"

        # Freshness counters
        fresh_count = 0
        stale_count = 0

        # Sport rows
        sport_rows = ""
        for r in results:
            icon = "✅" if r.get("success") else "❌"
            name = _SPORT_NAMES.get(r["sport"], r["sport"].upper())
            rows = r.get("rows", 0)
            new = r.get("new", 0)
            updated = r.get("updated", 0)
            dur = r.get("duration", 0)
            err = r.get("error", "")
            bg = "#0d1117" if r.get("success") else "#1c1014"

            # Freshness badge
            if err:
                badge = '<span style="background:#7f1d1d;color:#fca5a5;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">ERROR</span>'
            elif new > 0:
                badge = '<span style="background:#064e3b;color:#6ee7b7;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">FRESH</span>'
                fresh_count += 1
            elif rows > 0 and r.get("success"):
                badge = '<span style="background:#78350f;color:#fcd34d;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">STALE</span>'
                stale_count += 1
            else:
                badge = '<span style="color:#484f58;font-size:11px;">—</span>'
                if r.get("success"):
                    fresh_count += 1  # empty but successful (e.g. training tasks)

            sport_rows += f"""
            <tr style="background:{bg};">
                <td style="padding:6px 12px;border-bottom:1px solid #21262d;">{icon} {name}</td>
                <td style="padding:6px 12px;border-bottom:1px solid #21262d;text-align:center;">{badge}</td>
                <td style="padding:6px 12px;border-bottom:1px solid #21262d;text-align:right;">{rows:,}</td>
                <td style="padding:6px 12px;border-bottom:1px solid #21262d;text-align:right;">{new:,}</td>
                <td style="padding:6px 12px;border-bottom:1px solid #21262d;text-align:right;">{updated:,}</td>
                <td style="padding:6px 12px;border-bottom:1px solid #21262d;text-align:right;">{dur:.1f}s</td>
                <td style="padding:6px 12px;border-bottom:1px solid #21262d;color:#f87171;font-size:12px;">{err[:60] if err else ''}</td>
            </tr>"""

        # Freshness summary callout
        if stale_count > 0:
            freshness_html = f"""
            <div style="margin-top:16px;padding:12px;background:#1c1814;border:1px solid #78350f;border-radius:8px;">
                <span style="color:#fcd34d;font-weight:600;">⚠️ {stale_count} sport{'s' if stale_count != 1 else ''} returned stale data</span>
                <span style="color:#8b949e;font-size:12px;"> — rows processed but 0 new records. Data source may be down or unchanged.</span>
            </div>"""
        else:
            freshness_html = ""

        # Performance section
        perf_html = ""
        if perf_summary and not perf_summary.get("error"):
            roi = perf_summary.get("roi", 0)
            roi_color = "#22c55e" if roi >= 0 else "#ef4444"
            perf_html = f"""
            <div style="margin-top:20px;padding:12px;background:#161b22;border:1px solid #21262d;border-radius:8px;">
                <h3 style="margin:0 0 8px;color:#c9d1d9;">24h Betting Performance</h3>
                <span style="color:#8b949e;">Graded: {perf_summary.get('total',0)}</span> &nbsp;|&nbsp;
                <span style="color:#22c55e;">W: {perf_summary.get('wins',0)}</span> &nbsp;|&nbsp;
                <span style="color:#ef4444;">L: {perf_summary.get('losses',0)}</span> &nbsp;|&nbsp;
                <span style="color:{roi_color};">ROI: {roi:.1f}%</span> &nbsp;|&nbsp;
                <span style="color:#8b949e;">DB Rows: {perf_summary.get('db_total_rows',0):,}</span>
            </div>"""

        return f"""
        <html>
        <body style="margin:0;padding:20px;background:#0d1117;color:#c9d1d9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
            <div style="max-width:750px;margin:0 auto;">
                <h1 style="color:#f0f6fc;margin-bottom:4px;">Sports Betting Analyzer</h1>
                <p style="color:#8b949e;margin-top:0;">Import Pipeline Report — {now_str}</p>

                <div style="display:flex;gap:16px;margin:16px 0;flex-wrap:wrap;">
                    <div style="background:#161b22;border:1px solid #21262d;border-radius:8px;padding:12px 20px;text-align:center;">
                        <div style="font-size:28px;font-weight:bold;color:{health_color};">{health_score}%</div>
                        <div style="color:#8b949e;font-size:12px;">Health</div>
                    </div>
                    <div style="background:#161b22;border:1px solid #21262d;border-radius:8px;padding:12px 20px;text-align:center;">
                        <div style="font-size:28px;font-weight:bold;color:#58a6ff;">{total_rows:,}</div>
                        <div style="color:#8b949e;font-size:12px;">Total Rows</div>
                    </div>
                    <div style="background:#161b22;border:1px solid #21262d;border-radius:8px;padding:12px 20px;text-align:center;">
                        <div style="font-size:28px;font-weight:bold;color:#6ee7b7;">{fresh_count}</div>
                        <div style="color:#8b949e;font-size:12px;">Fresh</div>
                    </div>
                    <div style="background:#161b22;border:1px solid #21262d;border-radius:8px;padding:12px 20px;text-align:center;">
                        <div style="font-size:28px;font-weight:bold;color:{'#fcd34d' if stale_count > 0 else '#c9d1d9'};">{stale_count}</div>
                        <div style="color:#8b949e;font-size:12px;">Stale</div>
                    </div>
                    <div style="background:#161b22;border:1px solid #21262d;border-radius:8px;padding:12px 20px;text-align:center;">
                        <div style="font-size:28px;font-weight:bold;color:#c9d1d9;">{total_duration:.0f}s</div>
                        <div style="color:#8b949e;font-size:12px;">Duration</div>
                    </div>
                </div>

                <table style="width:100%;border-collapse:collapse;background:#0d1117;border:1px solid #21262d;border-radius:8px;overflow:hidden;">
                    <thead>
                        <tr style="background:#161b22;">
                            <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #21262d;color:#f0f6fc;">Sport</th>
                            <th style="padding:8px 12px;text-align:center;border-bottom:2px solid #21262d;color:#f0f6fc;">Status</th>
                            <th style="padding:8px 12px;text-align:right;border-bottom:2px solid #21262d;color:#f0f6fc;">Rows</th>
                            <th style="padding:8px 12px;text-align:right;border-bottom:2px solid #21262d;color:#f0f6fc;">New</th>
                            <th style="padding:8px 12px;text-align:right;border-bottom:2px solid #21262d;color:#f0f6fc;">Updated</th>
                            <th style="padding:8px 12px;text-align:right;border-bottom:2px solid #21262d;color:#f0f6fc;">Time</th>
                            <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #21262d;color:#f0f6fc;">Error</th>
                        </tr>
                    </thead>
                    <tbody>
                        {sport_rows}
                    </tbody>
                </table>

                {freshness_html}
                {perf_html}

                <p style="margin-top:16px;color:#8b949e;font-size:12px;">
                    {'📎 Attached: import_report.zip — contains per-sport summary CSV' + (' and ' + str(record_count) + ' detailed import records (new/changed only).' if record_count > 0 else '.') }
                </p>
                <p style="margin-top:4px;color:#484f58;font-size:11px;">
                    Passed: {success_count} | Failed: {fail_count} | Fresh: {fresh_count} | Stale: {stale_count}
                </p>
            </div>
        </body>
        </html>"""
