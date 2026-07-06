"""A real /api/health endpoint (gh #67).

Before this, `/health` (and every non-`/api/*` path) returned the SPA shell — HTTP 200
regardless of backend state, and 401 once auth was enabled — so an orchestrator / LB /
uptime probe had no usable liveness signal. `/api/health` is a dedicated JSON endpoint,
exempt from Basic Auth, with an optional readiness mode that reflects real backend state.
"""
from typing import TypedDict

from fastapi.testclient import TestClient
from langgraph.graph import END, START, StateGraph

from langstage.app import CoworkApp


class _S(TypedDict):
    x: int


def _graph():
    g = StateGraph(_S)
    g.add_node("n", lambda s: {"x": s.get("x", 0) + 1})
    g.add_edge(START, "n")
    g.add_edge("n", END)
    return g.compile()


def _client(tmp_path, **kwargs):
    app = CoworkApp(agent=_graph(), workspace=str(tmp_path), **kwargs).create_server()
    return TestClient(app)


def test_health_liveness_is_json_ok(tmp_path):
    r = _client(tmp_path).get("/api/health")
    assert r.status_code == 200
    assert "application/json" in r.headers.get("content-type", "")
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body  # a real version string, not the SPA shell


def test_health_readiness_reports_backend_checks(tmp_path):
    # With the app wired (agent loaded, task store created), readiness is 200 and
    # names the checks — reflecting real backend state, not the always-served shell.
    with _client(tmp_path) as c:  # `with` drives lifespan so the task store is set up
        r = c.get("/api/health?ready=1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["checks"]["agent"] == "ok"
    assert body["checks"]["task_store"] == "ok"


def test_health_is_exempt_from_basic_auth(tmp_path):
    # With auth ON, every other path 401s without credentials — but a liveness probe
    # can't carry credentials, so /api/health must still answer (gh #67).
    c = _client(tmp_path, auth_password="secret123")
    # a normal API path is protected...
    assert c.get("/api/config").status_code == 401
    # ...but health is reachable without credentials.
    r = c.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_is_not_the_spa_shell(tmp_path):
    # The old /health returned index.html (text/html). The new endpoint is JSON.
    r = _client(tmp_path).get("/api/health")
    assert "text/html" not in r.headers.get("content-type", "")
