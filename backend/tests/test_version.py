"""Unit tests for src.version env-var driven version resolution."""
import importlib

import pytest


@pytest.fixture
def version_mod(monkeypatch):
    """Reload src.version with controlled env, restoring it afterwards."""
    monkeypatch.setenv("APP_VERSION", "9.8.7")
    monkeypatch.setenv("GIT_SHA", "deadbee")
    monkeypatch.setenv("GIT_BRANCH", "test-branch")
    monkeypatch.setenv("ENVIRONMENT", "testing")
    monkeypatch.setenv("BUILD_TIME", "2025-01-01T00:00:00Z")
    mod = importlib.import_module("version")
    importlib.reload(mod)
    yield mod
    importlib.reload(mod)  # restore original env resolution


def test_get_version_uses_env(version_mod):
    assert version_mod.get_version() == "9.8.7"


def test_version_info_shape(version_mod):
    info = version_mod.get_version_info()
    assert info == {
        "version": "9.8.7",
        "git_sha": "deadbee",
        "git_branch": "test-branch",
        "environment": "testing",
        "build_time": "2025-01-01T00:00:00Z",
    }


def test_module_constants_match_env(version_mod):
    assert version_mod.ENVIRONMENT == "testing"
    assert version_mod.GIT_SHA == "deadbee"
