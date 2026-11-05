"""
Route registry tests.

Guards against the class of bug where the *same* (method, path) is registered
more than once — FastAPI serves the first match and silently shadows the rest.

These tests import the full FastAPI app and assert the registry is clean and
that the historically-shadowed endpoints resolve to the intended handlers.
"""
import collections
import importlib.util

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def app_module():
    """Load api/app.py as a module (same effect as `import api.app`)."""
    import api.app as mod  # noqa: F401  (conftest.py sets up sys.path)
    return mod


@pytest.fixture(scope="module")
def app(app_module):
    return app_module.app


def _routes(app):
    """Flatten app routes, handling both classic FastAPI and newer
    versions that store included routers lazily (_IncludedRouter)."""
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


def _endpoint_names(app):
    return {getattr(getattr(r, "endpoint", None), "__name__", "") for r in app.routes}


# ---------------------------------------------------------------------------
# Global invariants
# ---------------------------------------------------------------------------

def test_no_duplicate_registered_routes(app):
    """Every (methods, path) pair must be registered exactly once."""
    counts = collections.Counter(
        ("/".join(sorted(r.methods)), r.path) for r in _routes(app)
    )
    duplicates = {k: v for k, v in counts.items() if v > 1}
    assert not duplicates, f"Duplicate routes registered: {duplicates}"


# ---------------------------------------------------------------------------
# Regressions: previously shadowed endpoints
# ---------------------------------------------------------------------------

def test_predict_route_registered_once(app):
    matches = [r for r in _routes(app) if r.path == "/{sport}/predict/{task}" and "POST" in r.methods]
    assert len(matches) == 1, f"POST /{{sport}}/predict/{{task}} registered {len(matches)} times"


def test_predict_route_uses_model_endpoint(app):
    """/predict must be served by the model-backed handler, not the heuristic stub."""
    r = next(r for r in _routes(app) if r.path == "/{sport}/predict/{task}" and "POST" in r.methods)
    assert r.endpoint.__name__ == "predict"


def test_heuristic_predict_stub_is_gone(app):
    assert "make_prediction" not in _endpoint_names(app)


def test_nba_season_simulation_registered_once(app):
    matches = [r for r in _routes(app) if r.path == "/nba/simulation/season"]
    assert len(matches) == 1, f"/nba/simulation/season registered {len(matches)} times"
    assert matches[0].endpoint.__name__ == "run_nba_season_simulation"


def test_college_baseball_routes_registered_once(app):
    expected = {
        "/baseball/ncaa/teams": "list_teams",
        "/baseball/ncaa/import": "trigger_import",
        "/baseball/ncaa/stats/{team_id}": None,  # only assert uniqueness
        "/baseball/ncaa/schedule/{team_id}": None,
    }
    for path, expected_handler in expected.items():
        matches = [r for r in _routes(app) if r.path == path]
        assert len(matches) == 1, f"{path} registered {len(matches)} times"
        if expected_handler:
            assert matches[0].endpoint.__name__ == expected_handler


# ---------------------------------------------------------------------------
# /cache/analysis must accept the Blazor client's payload shape
# {sport, home_team, away_team, analysis}
# ---------------------------------------------------------------------------

class _FakeStorage:
    captured = []

    async def save_analysis(self, sport, home, away, analysis):
        _FakeStorage.captured.append((sport, home, away, analysis))
        return True


def test_cache_analysis_accepts_manual_payload(app, monkeypatch):
    import src.odds_storage as odds_storage

    def fake_get_odds_storage():
        return _FakeStorage()

    monkeypatch.setattr(odds_storage, "get_odds_storage", fake_get_odds_storage)
    _FakeStorage.captured.clear()

    client = TestClient(app)
    resp = client.post(
        "/cache/analysis",
        json={
            "sport": "nba",
            "home_team": "Celtics",
            "away_team": "Lakers",
            "analysis": {"pick": "home", "confidence": 0.62},
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True
    assert _FakeStorage.captured == [("nba", "Celtics", "Lakers", {"pick": "home", "confidence": 0.62})]


def test_cache_analysis_rejects_payload_without_identifiers(app):
    client = TestClient(app)
    resp = client.post("/cache/analysis", json={"analysis": {"x": 1}})
    assert resp.status_code == 400
