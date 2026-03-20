import logging
import os
import socket
import time
import asyncio
from collections import deque
from typing import Any, Dict, List

import asyncpg
from src.config import DATABASE_URL
from src.notification_store import insert_notification


logger = logging.getLogger(__name__)


class OpsAlertService:
    _critical_paths = ("/odds", "/db/games", "/espn")
    _error_events: dict[str, deque[float]] = {p: deque() for p in _critical_paths}
    _last_threshold_alert: dict[str, float] = {}

    _window_seconds = int(os.getenv("OPS_CRITICAL_ENDPOINT_WINDOW_SECONDS", "300"))
    _threshold_count = int(os.getenv("OPS_CRITICAL_ENDPOINT_THRESHOLD", "5"))
    _alert_cooldown_seconds = int(os.getenv("OPS_ALERT_COOLDOWN_SECONDS", "600"))

    _quota_warn_threshold = int(os.getenv("OPS_ODDS_QUOTA_WARN_THRESHOLD", "100"))
    _quota_critical_threshold = int(os.getenv("OPS_ODDS_QUOTA_CRITICAL_THRESHOLD", "25"))

    _restart_window_minutes = int(os.getenv("OPS_RESTART_WINDOW_MINUTES", "15"))
    _restart_loop_threshold = int(os.getenv("OPS_RESTART_LOOP_THRESHOLD", "3"))

    @classmethod
    def _queue_notification(
        cls,
        *,
        severity: str,
        category: str,
        title: str,
        message: str,
        source: str,
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                insert_notification(
                    DATABASE_URL,
                    severity=severity,
                    category=category,
                    title=title,
                    message=message,
                    source=source,
                    metadata=metadata or {},
                )
            )
        except RuntimeError:
            # No running loop (e.g. script context). Skip DB notification write.
            pass

    @classmethod
    def _find_critical_path_key(cls, path: str) -> str | None:
        for prefix in cls._critical_paths:
            if path.startswith(prefix):
                return prefix
        return None

    @classmethod
    def record_response(cls, path: str, method: str, status_code: int) -> None:
        now = time.time()

        # Security/admin action monitoring for write operations.
        if path.startswith("/admin") and method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            if status_code >= 400:
                msg = f"Admin action failed: {method.upper()} {path} returned {status_code}"
                logger.error(
                    "Admin action failed: method=%s path=%s status=%s",
                    method.upper(),
                    path,
                    status_code,
                )
                cls._queue_notification(
                    severity="error",
                    category="security",
                    title="Admin Action Failed",
                    message=msg,
                    source="ops_alerts.record_response",
                    metadata={"path": path, "method": method.upper(), "status_code": status_code},
                )
            else:
                logger.info("Admin action succeeded: method=%s path=%s", method.upper(), path)

        # Critical endpoint failure-rate monitoring.
        critical_key = cls._find_critical_path_key(path)
        if not critical_key or status_code < 500:
            return

        bucket = cls._error_events[critical_key]
        bucket.append(now)
        cutoff = now - cls._window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.popleft()

        if len(bucket) < cls._threshold_count:
            return

        last_alert = cls._last_threshold_alert.get(critical_key, 0)
        if (now - last_alert) < cls._alert_cooldown_seconds:
            return

        cls._last_threshold_alert[critical_key] = now
        msg = f"{len(bucket)} failures in {cls._window_seconds}s for {critical_key}"
        logger.error(
            "Critical endpoint degradation detected: prefix=%s failures=%s window=%ss",
            critical_key,
            len(bucket),
            cls._window_seconds,
        )
        cls._queue_notification(
            severity="error",
            category="endpoint_health",
            title="Critical Endpoint Degradation",
            message=msg,
            source="ops_alerts.record_response",
            metadata={"prefix": critical_key, "failures": len(bucket), "window_seconds": cls._window_seconds},
        )

    @classmethod
    def maybe_alert_low_odds_quota(cls, source: str, odds_payload: Dict[str, Any] | None) -> None:
        if not isinstance(odds_payload, dict):
            return

        api_quota = odds_payload.get("api_quota")
        if not isinstance(api_quota, dict):
            return

        remaining = api_quota.get("requests_remaining")
        used = api_quota.get("requests_used")

        if remaining is None:
            return

        try:
            remaining_i = int(remaining)
            used_i = int(used) if used is not None else -1
        except (ValueError, TypeError):
            return

        if remaining_i <= cls._quota_critical_threshold:
            msg = f"Odds API quota critical for {source}: remaining={remaining_i}, used={used_i}"
            logger.error(
                "Odds API quota critical: source=%s remaining=%s used=%s",
                source,
                remaining_i,
                used_i,
            )
            cls._queue_notification(
                severity="error",
                category="quota",
                title="Odds API Quota Critical",
                message=msg,
                source="ops_alerts.maybe_alert_low_odds_quota",
                metadata={"source": source, "requests_remaining": remaining_i, "requests_used": used_i},
            )
        elif remaining_i <= cls._quota_warn_threshold:
            msg = f"Odds API quota low for {source}: remaining={remaining_i}, used={used_i}"
            logger.warning(
                "Odds API quota low: source=%s remaining=%s used=%s",
                source,
                remaining_i,
                used_i,
            )
            cls._queue_notification(
                severity="warning",
                category="quota",
                title="Odds API Quota Low",
                message=msg,
                source="ops_alerts.maybe_alert_low_odds_quota",
                metadata={"source": source, "requests_remaining": remaining_i, "requests_used": used_i},
            )

    @classmethod
    def report_import_failures(cls, results: List[Dict[str, Any]], trigger_source: str) -> None:
        failed = [r for r in results if not r.get("success")]
        if not failed:
            return
        failed_sports = ", ".join(str(r.get("sport", "unknown")) for r in failed)
        msg = f"Import pipeline failures ({trigger_source}): {failed_sports}"
        logger.error(
            "Import pipeline had failures: trigger=%s failed_sports=%s total_failed=%s",
            trigger_source,
            failed_sports,
            len(failed),
        )
        cls._queue_notification(
            severity="error",
            category="import",
            title="Import Pipeline Failed",
            message=msg,
            source="ops_alerts.report_import_failures",
            metadata={"trigger_source": trigger_source, "failed_sports": failed_sports, "total_failed": len(failed)},
        )

    @classmethod
    async def record_startup_and_check_loop(cls, database_url: str) -> None:
        """
        Track service restarts and alert if startup count exceeds threshold in a short window.
        This approximates container restart-loop detection at the app layer.
        """
        conn = None
        try:
            conn = await asyncpg.connect(database_url)
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS service_startup_events (
                    id SERIAL PRIMARY KEY,
                    hostname TEXT NOT NULL,
                    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_service_startup_events_started_at
                ON service_startup_events(started_at DESC);
                """
            )
            hostname = socket.gethostname()
            await conn.execute(
                "INSERT INTO service_startup_events (hostname, started_at) VALUES ($1, NOW())",
                hostname,
            )
            restart_count = await conn.fetchval(
                """
                SELECT COUNT(*)::int
                FROM service_startup_events
                WHERE hostname = $1
                  AND started_at >= NOW() - make_interval(mins => $2)
                """,
                hostname,
                cls._restart_window_minutes,
            )

            if restart_count >= cls._restart_loop_threshold:
                msg = (
                    f"Potential restart loop on {hostname}: "
                    f"{restart_count} restarts in {cls._restart_window_minutes} minutes"
                )
                logger.error(
                    "Potential restart loop detected: hostname=%s restarts=%s window_minutes=%s",
                    hostname,
                    restart_count,
                    cls._restart_window_minutes,
                )
                await insert_notification(
                    DATABASE_URL,
                    severity="error",
                    category="service_health",
                    title="Potential Restart Loop Detected",
                    message=msg,
                    source="ops_alerts.record_startup_and_check_loop",
                    metadata={
                        "hostname": hostname,
                        "restarts": restart_count,
                        "window_minutes": cls._restart_window_minutes,
                    },
                )
        except Exception as exc:
            logger.warning("Failed to record startup loop signal: %s", exc)
        finally:
            if conn:
                await conn.close()
