"""The missing-frontend condition must be visible, not browser-only (gh #96).

A wheel can ship without the SPA (that is exactly what 0.13.20-0.13.23 did, gh #94)
and every signal a human or a machine looks at stayed green: the startup banner
printed a happy URL, uvicorn logged "Application startup complete", `/api/health`
returned ok, and `langstage check` passed. The only way to find out was to open a
browser and see raw JSON.

These tests pin the three touch-points that now surface it, in both directions —
present and missing — so the condition cannot silently go quiet again.
"""

import json

import pytest
from fastapi.testclient import TestClient

from langstage import app as app_mod
from langstage.server import main as main_mod


@pytest.fixture
def bundled(monkeypatch):
    """Patch the single frontend predicate's underlying path (the existing seam)."""

    def _set(present: bool, tmp_path):
        static = tmp_path / "static"
        static.mkdir(exist_ok=True)
        if present:
            (static / "index.html").write_text("<!doctype html><div id=root></div>")
        monkeypatch.setattr(main_mod, "_static_dir", lambda: static)
        return static

    return _set


# --------------------------------------------------------------------------
# 1. Startup warning
# --------------------------------------------------------------------------

def test_startup_warning_when_frontend_missing(bundled, tmp_path):
    bundled(False, tmp_path)
    warning = app_mod._frontend_warning()
    assert warning is not None
    # Must name the concrete missing artifact and the user-visible consequence —
    # a bare "frontend missing" leaves the reader unable to act on it.
    assert "langstage/static/index.html" in warning
    assert "JSON placeholder" in warning
    assert warning.startswith("WARNING:")


def test_no_startup_warning_when_frontend_present(bundled, tmp_path):
    bundled(True, tmp_path)
    assert app_mod._frontend_warning() is None


# --------------------------------------------------------------------------
# 2. /api/health readiness payload
# --------------------------------------------------------------------------

def _client(tmp_path, monkeypatch):
    from tests.test_frontend_packaging import _app_with_static  # reuse the app builder

    return TestClient(_app_with_static(tmp_path, main_mod._static_dir(), monkeypatch))


def test_health_reports_frontend_missing(bundled, tmp_path, monkeypatch):
    bundled(False, tmp_path)
    with _client(tmp_path, monkeypatch) as client:
        body = client.get("/api/health?ready=1").json()
    assert body["checks"]["frontend"] == "missing"


def test_health_reports_frontend_ok(bundled, tmp_path, monkeypatch):
    bundled(True, tmp_path)
    with _client(tmp_path, monkeypatch) as client:
        body = client.get("/api/health?ready=1").json()
    assert body["checks"]["frontend"] == "ok"


def test_missing_frontend_does_not_fail_readiness(bundled, tmp_path, monkeypatch):
    """A missing SPA is reported, never gating.

    The REST/WS surface is fully functional without it and a backend-only install
    is supported (the packaging hook honours LANGSTAGE_SKIP_FRONTEND_BUILD=1).
    Returning 503 here would mark those deployments permanently un-Ready and pull
    a working API out of a load balancer.
    """
    bundled(False, tmp_path)
    with _client(tmp_path, monkeypatch) as client:
        resp = client.get("/api/health?ready=1")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_liveness_payload_is_unchanged(bundled, tmp_path, monkeypatch):
    """Plain /api/health stays a minimal liveness probe — no checks block."""
    bundled(False, tmp_path)
    with _client(tmp_path, monkeypatch) as client:
        body = client.get("/api/health").json()
    assert "checks" not in body


# --------------------------------------------------------------------------
# 3. langstage check
# --------------------------------------------------------------------------

def _run_check(monkeypatch, extra_args=()):
    from click.testing import CliRunner

    from langstage.cli import main

    return CliRunner().invoke(main, ["check", "--demo", *extra_args])


def test_check_warns_when_frontend_missing(bundled, tmp_path, monkeypatch):
    bundled(False, tmp_path)
    result = _run_check(monkeypatch)
    assert "bundled frontend missing" in result.stdout
    # Warning only — the exit-code contract must not change (0 = agent is fine).
    assert result.exit_code == 0


def test_check_json_exposes_frontend_field(bundled, tmp_path, monkeypatch):
    """The machine-readable hook a CI gate asserts on."""
    bundled(False, tmp_path)
    result = _run_check(monkeypatch, ["--json"])
    report = json.loads(result.stdout)
    assert report["checks"]["frontend"]["ok"] is False
    assert "web UI unavailable" in report["checks"]["frontend"]["detail"]


def test_check_json_reports_frontend_ok_when_present(bundled, tmp_path, monkeypatch):
    bundled(True, tmp_path)
    result = _run_check(monkeypatch, ["--json"])
    report = json.loads(result.stdout)
    assert report["checks"]["frontend"]["ok"] is True


# --------------------------------------------------------------------------
# The three surfaces must agree — that disagreement *was* the bug
# --------------------------------------------------------------------------

@pytest.mark.parametrize("present", [True, False])
def test_all_three_surfaces_agree(bundled, tmp_path, monkeypatch, present):
    bundled(present, tmp_path)

    warned = app_mod._frontend_warning() is not None
    with _client(tmp_path, monkeypatch) as client:
        health_missing = client.get("/api/health?ready=1").json()["checks"]["frontend"] == "missing"
    report = json.loads(_run_check(monkeypatch, ["--json"]).stdout)
    check_missing = not report["checks"]["frontend"]["ok"]

    assert warned == health_missing == check_missing == (not present)
