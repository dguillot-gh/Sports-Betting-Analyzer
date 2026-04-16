import logging
import os
import socket
import sys
import time
from typing import List


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class _ErrorRateLimiter:
    def __init__(self, cooldown_seconds: int) -> None:
        self._cooldown = max(1, cooldown_seconds)
        self._last_sent: dict[str, float] = {}

    def allow(self, key: str) -> bool:
        now = time.time()
        last = self._last_sent.get(key)
        if last and (now - last) < self._cooldown:
            return False
        self._last_sent[key] = now
        return True


# Loggers whose ERROR messages should never generate push notifications.
# They still get logged normally — just suppressed from the notification bell.
_SUPPRESSED_LOGGERS = frozenset({
    "asyncio",           # "Future exception was never retrieved" — transient connection churn
    "pywebpush",         # Transient web-push delivery errors
})

# Substrings in the message that mark known-noisy errors to suppress.
_SUPPRESSED_MESSAGES = (
    "Future exception was never retrieved",
    "unexpected connection_lost",
)


class ErrorPushHandler(logging.Handler):
    """Logging handler that routes ERROR+ logs to in-app + FCM + Web Push notifications.
    No emails are sent — all alerts go through push channels only."""

    def __init__(self, cooldown_seconds: int = 600) -> None:
        super().__init__(level=logging.ERROR)
        self._hostname = socket.gethostname()
        self._limiter = _ErrorRateLimiter(cooldown_seconds)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # Skip known-noisy loggers and messages
            if record.name in _SUPPRESSED_LOGGERS:
                return
            msg_text = record.getMessage()
            if any(substr in msg_text for substr in _SUPPRESSED_MESSAGES):
                return

            signature = self._make_signature(record.name, record.levelname, msg_text)
            if not self._limiter.allow(signature):
                return

            self._queue_app_notification(record)
        except Exception as exc:
            print(f"ErrorPushHandler failed: {exc}", file=sys.stderr)

    @staticmethod
    def _make_signature(logger_name: str, level: str, msg: str) -> str:
        """Build a dedup key that collapses repetitive per-item errors.

        Many loops log `"Failed to <verb> <item>: <reason>"`.  The item
        (e.g. team names) changes every iteration while the logger, verb,
        and reason stay the same.  We keep the first token before ':'
        (the verb/prefix) and the last token after ':' (the reason/type)
        but strip the variable middle part so 20 NBA games map to one key.
        """
        short = msg[:240]
        if ": " in short:
            parts = short.split(": ", 1)
            prefix = parts[0].split(" ")[0:4]  # first 4 words
            suffix = parts[-1][:80]
            short = " ".join(prefix) + ": " + suffix
        return f"{logger_name}|{level}|{short}"

    def _queue_app_notification(self, record: logging.LogRecord) -> None:
        """Fire insert_notification so errors go to FCM, Web Push, and in-app bell."""
        import asyncio

        try:
            from src.config import DATABASE_URL
            from src.notification_store import insert_notification

            title = f"\U0001f534 {record.name}"
            msg = record.getMessage()[:500]

            async def _insert():
                try:
                    await insert_notification(
                        DATABASE_URL,
                        severity="error",
                        category="system_error",
                        title=title,
                        message=msg,
                        source=f"error_notifier.{record.name}",
                        metadata={
                            "logger": record.name,
                            "level": record.levelname,
                            "hostname": self._hostname,
                        },
                    )
                except Exception:
                    pass  # Don't recurse into error logging

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_insert())
            except RuntimeError:
                # No running loop — run synchronously in a new loop
                try:
                    asyncio.run(_insert())
                except Exception:
                    pass
        except Exception:
            pass  # Never let notification failures break error logging


# Keep old name as alias for backward compat
ErrorEmailHandler = ErrorPushHandler


def install_error_push_handler() -> bool:
    """Install a global logging handler that routes ERROR+ logs to push notifications."""
    cooldown = int(os.getenv("ERROR_NOTIFICATION_COOLDOWN_SECONDS",
                             os.getenv("ERROR_EMAIL_COOLDOWN_SECONDS", "600")))

    root = logging.getLogger()
    if any(isinstance(handler, ErrorPushHandler) for handler in root.handlers):
        return True

    handler = ErrorPushHandler(cooldown_seconds=cooldown)
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    root.addHandler(handler)

    logging.getLogger(__name__).info(
        "Error push handler installed (FCM + Web Push + in-app); cooldown=%ss",
        cooldown,
    )
    return True


# Backward-compatible alias
def install_error_email_handler() -> bool:
    return install_error_push_handler()
