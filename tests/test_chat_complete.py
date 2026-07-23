"""Headless one-turn chat: `POST /api/chat/complete` + the shared helper (gh #101).

The buffered endpoint is the synchronous, non-SSE sibling of the streaming chat
pair: one HTTP call, prompt in -> full reply out, with none of the SSE ceremony
(no persistent ``GET /api/stream`` to open first, no event parsing, no task row).
It drives the same ``SessionAdapter`` the streaming routes drive, so the reply is
identical — just buffered. These tests also pin that the streaming path is not
regressed.
"""
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langgraph.graph import END, START, MessagesState, StateGraph

from langstage_core import load_agent_spec
from langstage_core.adapters import SessionAdapter

from langstage.oneturn import OneTurnResult, complete_turn, run_turn_sync
from langstage.server.routes_chat import create_chat_router


def _stub():
    return load_agent_spec("langstage_core.demo.stub:graph")


def _boom_graph():
    def boom(state):
        raise RuntimeError("synthetic model failure")

    b = StateGraph(MessagesState)
    b.add_node("boom", boom)
    b.add_edge(START, "boom")
    b.add_edge("boom", END)
    return b.compile()


def _client(graph):
    app = FastAPI()
    app.include_router(create_chat_router(SessionAdapter(graph=graph)))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


# ── the endpoint ─────────────────────────────────────────────────────────────


async def test_complete_returns_reply_with_no_pre_opened_stream():
    """The whole point: a single POST returns the full reply, cold — no persistent
    GET /api/stream to create the session first (the SSE path's hidden ordering)."""
    async with _client(_stub()) as c:
        r = await c.post("/api/chat/complete", json={"content": "hello buffered"})
    assert r.status_code == 200
    body = r.json()
    assert "hello buffered" in body["content"]  # the demo echoes the user message
    assert body["session_id"]  # a session was created and returned
    assert body["tool_calls"] == []  # shape present (demo has no tools)


async def test_complete_reuses_a_provided_session_id():
    async with _client(_stub()) as c:
        r = await c.post(
            "/api/chat/complete", json={"content": "hi", "session_id": "sess-xyz"}
        )
    assert r.status_code == 200
    assert r.json()["session_id"] == "sess-xyz"


async def test_complete_surfaces_agent_error_as_500():
    async with _client(_boom_graph()) as c:
        r = await c.post("/api/chat/complete", json={"content": "hi"})
    assert r.status_code == 500
    assert "synthetic model failure" in r.json()["detail"]


async def test_streaming_chat_path_is_unchanged():
    """The SSE contract must not regress: a bare POST /api/chat still 404s without a
    session (which only the persistent stream creates) — the buffered path is
    additive, it doesn't loosen the streaming ordering."""
    async with _client(_stub()) as c:
        r = await c.post("/api/chat", json={"session_id": "never-opened", "content": "x"})
    assert r.status_code == 404


# ── the shared helper (one implementation behind CLI + endpoint) ─────────────


async def test_complete_turn_assembles_content_and_outcome():
    adapter = SessionAdapter(graph=_stub())
    result = await complete_turn(adapter, "ping the agent")
    assert isinstance(result, OneTurnResult)
    assert result.ok and result.outcome == "complete"
    assert "ping the agent" in result.content


async def test_complete_turn_reports_agent_error_without_raising():
    adapter = SessionAdapter(graph=_boom_graph())
    result = await complete_turn(adapter, "hi")
    assert not result.ok
    assert result.outcome == "error"
    assert "synthetic model failure" in (result.error or "")


def test_run_turn_sync_drives_one_turn_end_to_end():
    """The blocking entry point the CLI uses: wrap a graph, run one turn, return."""
    result = run_turn_sync(_stub(), "sync smoke")
    assert result.ok
    assert "sync smoke" in result.content
