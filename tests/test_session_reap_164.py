"""Disconnected ``GET /api/stream`` sessions are reclaimed (gh #164).

Every stream connect with a new/absent ``session_id`` creates a ``Session`` in the
adapter. It used to stay there forever after the client left. Now, once the stream
closes, the session is dropped after a grace period, unless a client reconnected or
a turn is still running.
"""

import asyncio

import pytest

from langstage_core import load_agent_spec
from langstage_core.adapters import SessionAdapter

from langstage.server import routes_chat
from langstage.server.routes_chat import create_chat_router


def _stream_endpoint(adapter):
    router = create_chat_router(adapter)
    for route in router.routes:
        if route.path == "/api/stream":
            return route.endpoint
    raise AssertionError("no /api/stream route")


async def _connect_and_leave(endpoint, session_id=None):
    resp = await endpoint(request=None, session_id=session_id)
    it = resp.body_iterator
    first = await it.__anext__()  # session_init
    await it.aclose()  # the client goes away
    return first


async def _settle(n=20):
    for _ in range(n):
        await asyncio.sleep(0)


@pytest.fixture
def no_grace(monkeypatch):
    monkeypatch.setattr(routes_chat, "SESSION_REAP_GRACE_S", 0.0)


async def test_anonymous_connects_do_not_accumulate(no_grace):
    adapter = SessionAdapter(graph=load_agent_spec("langstage_core.demo.stub:graph"))
    endpoint = _stream_endpoint(adapter)
    for _ in range(10):
        await _connect_and_leave(endpoint)
    await _settle()
    assert adapter.list_sessions() == []


async def test_reconnected_session_is_kept(no_grace, monkeypatch):
    monkeypatch.setattr(routes_chat, "SESSION_REAP_GRACE_S", 0.05)
    adapter = SessionAdapter(graph=load_agent_spec("langstage_core.demo.stub:graph"))
    endpoint = _stream_endpoint(adapter)
    await _connect_and_leave(endpoint, "keep-me")
    # Reconnect inside the grace window and stay connected.
    resp = await endpoint(request=None, session_id="keep-me")
    it = resp.body_iterator
    await it.__anext__()
    await asyncio.sleep(0.15)
    assert adapter.get("keep-me") is not None
    await it.aclose()


async def test_session_with_running_turn_is_kept_until_it_finishes(no_grace):
    adapter = SessionAdapter(graph=load_agent_spec("langstage_core.demo.stub:graph"))
    endpoint = _stream_endpoint(adapter)
    release = asyncio.Event()
    session = adapter.get_or_create("busy")
    session.current_task = asyncio.create_task(release.wait())
    await _connect_and_leave(endpoint, "busy")
    await _settle()
    assert adapter.get("busy") is not None  # turn in flight: not reaped
    release.set()
    await session.current_task
    await asyncio.sleep(0.3)
    assert adapter.get("busy") is None  # reaped once the turn ended
