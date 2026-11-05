"""Tests for the /dashboard/data-health endpoint (filesystem freshness)."""
import api.app as app_module


def _routes():
    return [(list(r.methods)[0], r.path) for r in app_module.app.routes if getattr(r, "methods", None)]


def test_data_health_registered_once() -> None:
    assert _routes().count(("GET", "/dashboard/data-health")) == 1


def test_data_health_shape(monkeypatch) -> None:
    from api.dashboard_endpoints import router
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    api = FastAPI()
    api.include_router(router)
    client = TestClient(api)

    resp = client.get("/dashboard/data-health")
    assert resp.status_code == 200
    body = resp.json()

    assert "generated_at" in body
    assert isinstance(body["data"], list)
    assert isinstance(body["models"], list)
    s = body["summary"]
    assert isinstance(s["total_data_files"], int)
    assert "stale_sports" in s

    # Repo ships with baseball data on disk in CI? It is committed, so expect at
    # least one data directory with files when present locally.
    if body["summary"]["total_data_files"] > 0:
        assert body["summary"]["freshest_data_hours"] is not None
        for entry in body["data"]:
            assert entry["files"] >= 0
            assert "newest_file_age_hours" in entry
