"""Unknown /api/* paths must be a JSON 404, not 200 + the SPA HTML shell
(gh #-dogfood). The SPA catch-all used to swallow the whole /api namespace, so a
typo'd or missing API path returned 200 text/html and broke programmatic clients.
"""
from typing import TypedDict

import pytest
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


def _client(tmp_path):
    return TestClient(CoworkApp(agent=_graph(), workspace=str(tmp_path)).create_server())


def test_unknown_api_path_is_404(tmp_path):
    r = _client(tmp_path).get("/api/totally-bogus-endpoint")
    assert r.status_code == 404, f"got {r.status_code} {r.headers.get('content-type')}"
    assert "text/html" not in r.headers.get("content-type", "")


def test_spa_route_still_serves_html(tmp_path):
    """A non-API client route still falls through to the SPA shell — when a
    pre-built frontend is present (it isn't in the source-only test env, where
    the SPA catch-all isn't registered at all)."""
    r = _client(tmp_path).get("/some/client/side/route")
    if r.status_code == 404:
        pytest.skip("no pre-built SPA in this environment (catch-all not registered)")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
