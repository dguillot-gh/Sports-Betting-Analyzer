"""
Tests for model governance (kill-switch, backup, rollback).

All filesystem-based (no DB) so they run in CI.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="module")
def app_module():
    import api.app as mod
    return mod


@pytest.fixture(scope="module")
def app(app_module):
    return app_module.app


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


def test_governance_routes_registered_once(app):
    routes = _routes(app)
    for method, path in [
        ("GET", "/governance/models"),
        ("POST", "/governance/models/{sport}/disable"),
        ("POST", "/governance/models/{sport}/enable"),
        ("POST", "/governance/models/{sport}/rollback"),
    ]:
        matches = [r for r in routes if r.path == path and method in r.methods]
        assert len(matches) == 1, f"{method} {path} registered {len(matches)} times"


@pytest.fixture()
def clean_override(monkeypatch):
    """Point overrides file at a temp location so tests don't clobber real config."""
    import tempfile
    import src.model_governance as gov

    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.write(b"{}")
    tmp.close()

    monkeypatch.setattr(gov, "OVERRIDES_PATH", type(gov.OVERRIDES_PATH)(tmp.name))
    yield tmp.name
    os.unlink(tmp.name)


def test_disable_enable_toggle(clean_override):
    import src.model_governance as gov

    assert gov.is_disabled("nba") is False
    gov.set_enabled("nba", False)
    assert gov.is_disabled("nba") is True
    gov.set_enabled("nba", True)
    assert gov.is_disabled("nBA") is False  # case-insensitive


def _fake_model_root(tmp_path, monkeypatch):
    import src.model_governance as gov

    models = tmp_path / "models"
    nba = models / "nba"
    (nba / "cup").mkdir(parents=True)
    (nba / "cup" / "classification_model.joblib").write_bytes(b"current")
    monkeypatch.setattr(gov, "MODELS_DIR", models)
    return models


def test_backup_and_rollback_flow(clean_override, tmp_path, monkeypatch):
    import src.model_governance as gov

    models = _fake_model_root(tmp_path, monkeypatch)
    model_file = models / "nba" / "cup" / "classification_model.joblib"

    # backup creates .previous
    n = gov.back_up_models("nba")
    assert n == 1
    assert model_file.with_suffix(".joblib.previous").exists()

    # simulate retrain overwriting the model
    model_file.write_bytes(b"new-model")

    # rollback restores previous, keeps current as .rollback
    result = gov.rollback("nba")
    assert result["success"] is True
    assert model_file.read_bytes() == b"current"
    assert model_file.with_suffix(".joblib.rollback").read_bytes() == b"new-model"

    # inventory reflects state
    inv = gov.list_models()
    assert inv["nba"]["modelCount"] == 1
    assert inv["nba"]["models"][0]["path"].endswith("classification_model.joblib")


def test_kill_switch_blocks_predict(clean_override, app):
    """While disabled, /predict returns 503 with a clear operator message."""
    import src.model_governance as gov

    gov.set_enabled("nhl", False)
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.post("/nhl/predict/classification", json={})
    assert resp.status_code == 503
    assert "disabled by operator" in resp.json()["detail"]

    # re-enable → kill-switch no longer triggers (normal flow resumes)
    gov.set_enabled("nhl", True)
    resp2 = client.post("/nhl/predict/classification", json={})
    assert resp2.status_code != 503
