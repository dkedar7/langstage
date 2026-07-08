"""The built-in OpenAPI/Swagger docs are served + correct (gh #71).

FastAPI serves a complete, always-in-sync schema at /openapi.json, /docs, and /redoc.
It was undocumented; these tests pin that it's reachable, reports the real package version
(not a hardcoded "2.0.0"), and honors auth (401 under --auth-password, while /api/health
stays exempt).
"""
from typing import TypedDict

from fastapi.testclient import TestClient
from langgraph.graph import END, START, StateGraph

from langstage import __version__
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
    return TestClient(CoworkApp(agent=_graph(), workspace=str(tmp_path), **kwargs).create_server())


def test_openapi_and_docs_are_served(tmp_path):
    c = _client(tmp_path)
    assert c.get("/docs").status_code == 200
    assert c.get("/redoc").status_code == 200
    doc = c.get("/openapi.json")
    assert doc.status_code == 200
    assert "application/json" in doc.headers.get("content-type", "")


def test_openapi_reports_the_real_version_and_enumerates_the_api(tmp_path):
    doc = _client(tmp_path).get("/openapi.json").json()
    # the real package version, not the old hardcoded "2.0.0"
    assert doc["info"]["version"] == __version__
    assert doc["info"]["version"] != "2.0.0"
    # the schema actually enumerates the REST surface
    paths = set(doc["paths"])
    assert {"/api/chat", "/api/health", "/api/tasks"} <= paths


def test_docs_honor_auth_but_health_stays_exempt(tmp_path):
    c = _client(tmp_path, auth_password="secret123")
    # the docs are behind auth like every other route...
    assert c.get("/docs").status_code == 401
    assert c.get("/openapi.json").status_code == 401
    # ...except the liveness probe.
    assert c.get("/api/health").status_code == 200
