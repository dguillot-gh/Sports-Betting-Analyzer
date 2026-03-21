"""
Unit tests for NotificationService.send_summary_report.

Validates:
  1. In-app notification is always inserted (via insert_notification).
  2. Email is sent ONLY when at least one import fails.
  3. Pushover fires for every run (success and failure).
"""

import asyncio
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from services.notifications import NotificationService


class TestSendSummaryReport(unittest.TestCase):
    """Tests for send_summary_report logic."""

    def _run(self, coro):
        """Helper to run an async coroutine in a sync test."""
        return asyncio.get_event_loop().run_until_complete(coro)

    # ---- fixtures ------------------------------------------------

    def _success_results(self):
        return [
            {"sport": "nascar", "success": True, "rows": 100, "duration": 2.5},
            {"sport": "nfl", "success": True, "rows": 250, "duration": 4.0},
        ]

    def _failure_results(self):
        return [
            {"sport": "nascar", "success": True, "rows": 100, "duration": 2.5},
            {"sport": "nfl", "success": False, "rows": 0, "duration": 0.3, "error": "timeout"},
        ]

    def _perf_summary(self):
        return {"nascar": {"rows": 100, "duration": 2.5}}

    # ---- tests ---------------------------------------------------

    @patch("services.notifications.insert_notification", new_callable=AsyncMock)
    @patch.object(NotificationService, "send_pushover_notification", new_callable=AsyncMock)
    @patch.object(NotificationService, "_send_failure_email")
    def test_all_success__no_email(self, mock_email, mock_pushover, mock_insert):
        """When all imports succeed, email should NOT be sent."""
        self._run(NotificationService.send_summary_report(
            self._success_results(), perf_summary=self._perf_summary()
        ))

        # Pushover always fires
        mock_pushover.assert_called_once()
        # In-app notification always inserted
        mock_insert.assert_called_once()
        # Email should NOT fire (all success)
        mock_email.assert_not_called()

        # Verify severity is "success"
        call_kwargs = mock_insert.call_args
        self.assertEqual(call_kwargs.kwargs.get("severity") or call_kwargs[1].get("severity", call_kwargs[0][1] if len(call_kwargs[0]) > 1 else None), "success")

    @patch("services.notifications.insert_notification", new_callable=AsyncMock)
    @patch.object(NotificationService, "send_pushover_notification", new_callable=AsyncMock)
    @patch.object(NotificationService, "_send_failure_email")
    def test_has_failure__sends_email(self, mock_email, mock_pushover, mock_insert):
        """When any import fails, email SHOULD be sent."""
        self._run(NotificationService.send_summary_report(
            self._failure_results(), perf_summary=self._perf_summary()
        ))

        # Pushover fires
        mock_pushover.assert_called_once()
        # In-app notification inserted
        mock_insert.assert_called_once()
        # Email SHOULD fire (has failure)
        mock_email.assert_called_once()

        # Verify severity is "warning"
        call_kwargs = mock_insert.call_args
        self.assertEqual(call_kwargs.kwargs.get("severity") or call_kwargs[1].get("severity", call_kwargs[0][1] if len(call_kwargs[0]) > 1 else None), "warning")

    @patch("services.notifications.insert_notification", new_callable=AsyncMock)
    @patch.object(NotificationService, "send_pushover_notification", new_callable=AsyncMock)
    @patch.object(NotificationService, "_send_failure_email")
    def test_metadata_contains_sports(self, mock_email, mock_pushover, mock_insert):
        """Metadata in the inserted notification should include per-sport breakdown."""
        self._run(NotificationService.send_summary_report(
            self._success_results(), perf_summary=self._perf_summary()
        ))

        call_kwargs = mock_insert.call_args
        metadata = call_kwargs.kwargs.get("metadata") or call_kwargs[1].get("metadata")
        self.assertIsNotNone(metadata)
        self.assertIn("sports", metadata)
        self.assertEqual(len(metadata["sports"]), 2)
        self.assertEqual(metadata["health_score"], 100)


if __name__ == "__main__":
    unittest.main()
