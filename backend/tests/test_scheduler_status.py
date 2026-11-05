"""
Tests for GET /admin/scheduler/status (scheduler health dashboard endpoint).

No DB is available in CI: the endpoint must degrade to a 503 with a clear
message instead of a 500. When a DB is present it returns the full shape.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _routes(app):
    out = []

    def walk(routes):
        for r in routes:
            included = getattr(r, "original_router", None)
            if included is not None:
                walk(included.routes)
                continue
            if getattr(r, "methods", None):
                out.append(r)

    walk(app.routes)
    return out


@pytest.fixture(scope="module")
def app_module():
    import api.app as mod
    return mod


@pytest.fixture(scope="module")
def app(app_module):
    return app_module.app


def test_scheduler_status_registered_once(app):
    matches = [r for r in _routes(app) if r.path == "/admin/scheduler/status" and "GET" in r.methods]
    assert len(matches) == 1, f"/admin/scheduler/status registered {len(matches)} times"


def test_scheduler_status_degrades_gracefully(app):
    """Without a DB: 503 + clear detail. With a DB: 200 + full shape."""
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/admin/scheduler/status")
    assert resp.status_code in (200, 503), f"unexpected status {resp.status_code}: {resp.text}"

    if resp.status_code == 200:
        body = resp.json()
        assert "summary" in body and "sports" in body and "recentRuns" in body
        for s in body["sports"]:
            assert s["health"] in ("healthy", "degraded", "down", "never_run")
            assert isinstance(s["consecutiveFailures"], int)
    else:
        assert "unavailable" in resp.json()["detail"]
