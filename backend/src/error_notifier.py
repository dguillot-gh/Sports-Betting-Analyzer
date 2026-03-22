import logging
import os
import smtplib
import socket
import sys
import time
from dataclasses import dataclass
from email.message import EmailMessage
from typing import List


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ErrorEmailSettings:
    enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_use_tls: bool
    email_from: str
    email_to: List[str]
    subject_prefix: str
    cooldown_seconds: int
    app_env: str

    @staticmethod
    def from_env() -> "ErrorEmailSettings":
        def env_first(*names: str, default: str = "") -> str:
            for name in names:
                val = os.getenv(name)
                if val is not None and str(val).strip():
                    return str(val).strip()
            return default

        to_value = env_first("ERROR_EMAIL_TO", "REPORT_EMAIL_TO", default="")
        recipients = [x.strip() for x in to_value.split(",") if x.strip()]
        from_value = env_first("ERROR_EMAIL_FROM", "SMTP_USER", default="")
        smtp_host = env_first("ERROR_EMAIL_SMTP_HOST", "SMTP_HOST", default="smtp.gmail.com")
        smtp_port_raw = env_first("ERROR_EMAIL_SMTP_PORT", "SMTP_PORT", default="587")
        smtp_user = env_first("ERROR_EMAIL_SMTP_USERNAME", "SMTP_USER", default="")
        smtp_pass = env_first("ERROR_EMAIL_SMTP_PASSWORD", "SMTP_PASS", default="")

        return ErrorEmailSettings(
            enabled=_env_bool("ERROR_EMAIL_ENABLED", False) or _env_bool("EMAIL_ALERTS_ENABLED", False),
            smtp_host=smtp_host,
            smtp_port=int(smtp_port_raw),
            smtp_username=smtp_user,
            smtp_password=smtp_pass,
            smtp_use_tls=_env_bool("ERROR_EMAIL_SMTP_USE_TLS", True),
            email_from=from_value,
            email_to=recipients,
            subject_prefix=os.getenv("ERROR_EMAIL_SUBJECT_PREFIX", "[Sports API Error]"),
            cooldown_seconds=int(os.getenv("ERROR_EMAIL_COOLDOWN_SECONDS", "600")),
            app_env=os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "unknown")).strip() or "unknown",
        )


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


class ErrorEmailHandler(logging.Handler):
    def __init__(self, settings: ErrorEmailSettings) -> None:
        super().__init__(level=logging.ERROR)
        self.settings = settings
        self._hostname = socket.gethostname()
        self._limiter = _ErrorRateLimiter(settings.cooldown_seconds)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            signature = f"{record.name}|{record.levelname}|{record.getMessage()[:240]}"
            if not self._limiter.allow(signature):
                return

            formatted_line = self.format(record)
            message = EmailMessage()
            message["Subject"] = f"{self.settings.subject_prefix} {record.levelname} {record.name}"
            message["From"] = self.settings.email_from
            message["To"] = ", ".join(self.settings.email_to)

            body_parts = [
                f"Environment: {self.settings.app_env}",
                f"Host: {self._hostname}",
                f"Logger: {record.name}",
                f"Level: {record.levelname}",
                f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime(record.created))}",
                "",
                "Message:",
                formatted_line,
            ]

            if record.exc_info:
                body_parts.extend(
                    [
                        "",
                        "Traceback:",
                        "".join(logging.Formatter().formatException(record.exc_info)),
                    ]
                )

            message.set_content("\n".join(body_parts))
            self._send(message)

            # Also fire in-app + FCM + Web Push via insert_notification
            self._queue_app_notification(record, formatted_line)
        except Exception as exc:
            print(f"ErrorEmailHandler failed to send email: {exc}", file=sys.stderr)

    def _queue_app_notification(self, record: logging.LogRecord, formatted_line: str) -> None:
        """Fire insert_notification so errors also go to FCM, Web Push, and in-app bell."""
        import asyncio

        try:
            from src.config import DATABASE_URL
            from src.notification_store import insert_notification

            title = f"🔴 {record.name}"
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

    def _send(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=10) as smtp:
            if self.settings.smtp_use_tls:
                smtp.starttls()
            if self.settings.smtp_username and self.settings.smtp_password:
                smtp.login(self.settings.smtp_username, self.settings.smtp_password)
            smtp.send_message(message)


def install_error_email_handler() -> bool:
    settings = ErrorEmailSettings.from_env()
    if not settings.enabled:
        return False

    missing = []
    if not settings.smtp_host:
        missing.append("ERROR_EMAIL_SMTP_HOST")
    if not settings.email_from:
        missing.append("ERROR_EMAIL_FROM")
    if not settings.email_to:
        missing.append("ERROR_EMAIL_TO")

    if missing:
        logging.getLogger(__name__).warning(
            "Error email notifier disabled; missing required env vars: %s",
            ", ".join(missing),
        )
        return False

    root = logging.getLogger()
    if any(isinstance(handler, ErrorEmailHandler) for handler in root.handlers):
        return True

    handler = ErrorEmailHandler(settings)
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    root.addHandler(handler)

    logging.getLogger(__name__).info(
        "Error email notifier enabled; recipients=%d cooldown=%ss",
        len(settings.email_to),
        settings.cooldown_seconds,
    )
    return True
