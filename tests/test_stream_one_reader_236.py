"""One connection reads a session's event stream at a time (gh #236).

A session has one event queue. Two ``GET /api/stream`` connections on the same
session (a second tab restoring the session id from localStorage, a second ``curl``)
each took whichever frame came next, so a reply was split between them word by word:
``tool_start`` in one window, ``tool_end`` in the other, ``complete`` in whichever got
it. History's "one window at a time" guard only covered the History menu.

Now the stream itself refuses a second reader (409), a window that reconnects takes
its own place without losing a frame, and "Continue here" can take a conversation
over from the window that has it once no turn is running.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import urllib.error
import urllib.request

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from langstage_core import load_agent_spec
from langstage_core.adapters import SessionAdapter

from langstage import CoworkApp
from langstage.server import routes_chat
from langstage.server.routes_chat import create_chat_router
from langstage.server.shutdown import until_shutdown
from langstage.server.stream_consumers import StreamConsumers

STUB = "langstage_core.demo.stub:graph"  # keyless
TOOLS = "langstage_core.demo.tools:graph"  # keyless, calls one tool then answers


def _find(routes, path):
    for route in routes:
        if getattr(route, "path", None) == path:
            return route.endpoint
        # Newer FastAPI keeps an included router as one entry instead of its routes.
        inner = getattr(route, "original_router", None)
        found = _find(inner.routes, path) if inner is not None else None
        if found is not None:
            return found
    return None


def _endpoint(router_or_app, path="/api/stream"):
    found = _find(router_or_app.routes, path)
    assert found is not None, f"no {path} route"
    return found


class _Rig:
    """The chat router on a bare adapter, with the stream endpoint called directly so
    a test decides exactly when each reader reads."""

    def __init__(self, spec=STUB):
        self.adapter = SessionAdapter(graph=load_agent_spec(spec))
        self.consumers = StreamConsumers()
        self.router = create_chat_router(self.adapter, consumers=self.consumers)
        self.stream = _endpoint(self.router)

    async def attach(self, session_id="s1", client=None):
        """Open a stream and read its ``session_init``."""
        resp = await self.stream(request=None, session_id=session_id, client=client)
        it = resp.body_iterator
        first = _event(await it.__anext__())
        assert first == {"type": "session_init", "session_id": session_id}
        return it


def _event(frame: str) -> dict:
    assert frame.startswith("data: "), frame
    return json.loads(frame[len("data: "):])


async def _rest(it) -> list[dict]:
    """Every remaining event of a stream that ends."""
    return [_event(f) async for f in it]


async def _settle(n=20):
    for _ in range(n):
        await asyncio.sleep(0)


def _say(session, *words):
    for word in words:
        session.push({"type": "content", "content": word})


# ── a second reader is refused ───────────────────────────────────────────────


async def test_a_second_reader_is_refused_and_the_first_gets_the_whole_turn():
    rig = _Rig(TOOLS)
    a = await rig.attach()
    for client in (None, "tab-b"):
        with pytest.raises(HTTPException) as refused:
            await rig.stream(request=None, session_id="s1", client=client)
        assert refused.value.status_code == 409
        assert refused.value.detail == {
            "message": "this conversation is open in another window", "running": False, "connected": True}

    rig.adapter.submit_message("s1", "use a tool please")
    events = []
    async with asyncio.timeout(20):
        while not events or events[-1]["type"] != "complete":
            events.append(_event(await a.__anext__()))
    kinds = [e["type"] for e in events]
    assert kinds.index("tool_start") < kinds.index("tool_end") < kinds.index("complete")
    assert kinds.count("complete") == 1
    text = "".join(e["content"] for e in events if e["type"] == "content")
    assert text.startswith("The demo tool returned") and text.rstrip().endswith("flow.")
    await a.aclose()


async def test_a_refusal_mid_turn_says_a_turn_is_running():
    rig = _Rig()
    a = await rig.attach()
    session = rig.adapter.get("s1")
    release = asyncio.Event()
    session.current_task = asyncio.create_task(release.wait())
    with pytest.raises(HTTPException) as refused:
        await rig.stream(request=None, session_id="s1", client="tab-b")
    assert refused.value.detail["running"] is True
    release.set()
    await session.current_task
    await a.aclose()


async def test_two_connections_arriving_together_cannot_both_read():
    """Both pass the 409 check before either has started reading; only one may."""
    rig = _Rig()
    first = await rig.stream(request=None, session_id="s1", client="tab-a")
    second = await rig.stream(request=None, session_id="s1", client="tab-b")
    a, b = first.body_iterator, second.body_iterator
    assert _event(await a.__anext__())["type"] == "session_init"
    assert await _rest(b) == []  # ended without a frame; a retry gets the 409
    _say(rig.adapter.get("s1"), "one")
    assert _event(await a.__anext__())["content"] == "one"
    await a.aclose()


async def test_a_reader_that_left_makes_room_for_the_next():
    rig = _Rig()
    a = await rig.attach(client="tab-a")
    await a.aclose()
    assert not rig.consumers.attached("s1")
    b = await rig.attach(client="tab-b")
    await b.aclose()


# ── the same window coming back ──────────────────────────────────────────────


async def test_the_same_window_reconnecting_mid_turn_loses_and_repeats_nothing():
    rig = _Rig()
    a = await rig.attach(client="tab-a")
    session = rig.adapter.get("s1")
    _say(session, "one ", "two ", "three")
    assert _event(await a.__anext__())["content"] == "one "

    # The page reloads before the server has seen the old connection go.
    b = await rig.attach(client="tab-a")
    assert await _rest(a) == [{"type": "superseded", "reason": "reconnected"}]
    assert [_event(await b.__anext__())["content"] for _ in range(2)] == ["two ", "three"]
    assert rig.consumers.current("s1").client == "tab-a" and session.sse_connected
    await b.aclose()
    assert not rig.consumers.attached("s1") and not session.sse_connected


async def test_a_reconnect_while_the_old_connection_waits_for_a_frame():
    rig = _Rig()
    a = await rig.attach(client="tab-a")
    session = rig.adapter.get("s1")
    waiting = asyncio.create_task(a.__anext__())  # parked on an empty queue
    await _settle()
    b = await rig.attach(client="tab-a")
    assert _event(await waiting) == {"type": "superseded", "reason": "reconnected"}
    _say(session, "after")
    assert _event(await b.__anext__())["content"] == "after"
    assert session.sse_connected
    await a.aclose()
    assert session.sse_connected  # the old connection closing doesn't say "nobody here"
    await b.aclose()


async def test_a_frame_read_as_the_takeover_lands_goes_to_the_new_reader():
    """The old connection had already taken the frame off the queue. It is not written
    to the connection that is being replaced, and it is not lost."""
    rig = _Rig()
    a = await rig.attach(client="tab-a")
    session = rig.adapter.get("s1")
    waiting = asyncio.create_task(a.__anext__())
    await _settle()
    # In one step of the event loop: a frame arrives and the reader is told to stop.
    _say(session, "in flight ")
    rig.consumers.current("s1").evict("reconnected")
    assert _event(await waiting) == {"type": "superseded", "reason": "reconnected"}
    await _settle()
    _say(session, "next")
    b = await rig.attach(client="tab-a")
    assert [_event(await b.__anext__())["content"] for _ in range(2)] == ["in flight ", "next"]
    await a.aclose()
    await b.aclose()


async def test_a_frame_read_as_the_client_disconnects_is_kept_for_the_next_reader():
    """``until_shutdown`` reads in a helper task. A frame that task had taken when the
    caller was cancelled used to be dropped on the floor."""
    arrived = asyncio.Event()

    async def frames():
        await arrived.wait()
        yield "taken"
        await asyncio.Event().wait()

    unsent: list[str] = []
    source = frames()

    async def consume():
        async for _ in until_shutdown(source, asyncio.Event(), unsent=unsent):
            raise AssertionError("the frame must not be yielded to a cancelled caller")

    task = asyncio.create_task(consume())
    await _settle()
    arrived.set()  # the read completes ...
    task.cancel()  # ... in the same step the caller is cancelled
    with pytest.raises(asyncio.CancelledError):
        await task
    assert unsent == ["taken"]
    await source.aclose()


async def test_a_stop_is_honoured_even_when_frames_keep_coming():
    """A stop used to be noticed only once the queue was empty for a moment."""
    stop = asyncio.Event()

    async def endless():
        n = 0
        while True:
            yield n
            n += 1

    seen = []
    async for frame in until_shutdown(endless(), stop):
        seen.append(frame)
        if frame == 2:
            stop.set()
    assert seen == [0, 1, 2]


async def test_a_bad_client_id_is_a_422(tmp_path):
    app = CoworkApp(agent_spec=STUB, workspace=str(tmp_path)).create_server()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as http:
        bad = await http.get("/api/stream", params={"session_id": "s1", "client": "no spaces/slashes"})
        assert bad.status_code == 422
        long = await http.get("/api/stream", params={"session_id": "s1", "client": "x" * 65})
        assert long.status_code == 422


# ── "Continue here": taking a conversation over ──────────────────────────────


class _Served:
    """A running app (lifespan entered), an HTTP client on it, and its stream route."""

    def __init__(self, workspace, spec=STUB):
        self.app = CoworkApp(agent_spec=spec, workspace=str(workspace)).create_server()
        self.client = AsyncClient(transport=ASGITransport(app=self.app), base_url="http://localhost")
        self.stream = _endpoint(self.app)

    async def __aenter__(self):
        self._lifespan = self.app.router.lifespan_context(self.app)
        await self._lifespan.__aenter__()
        return self

    async def __aexit__(self, *exc):
        await self.client.aclose()
        await self._lifespan.__aexit__(None, None, None)

    @property
    def adapter(self):
        return self.app.state.session_adapter

    @property
    def consumers(self):
        return self.app.state.stream_consumers

    async def turn(self, text: str, session_id: str | None = None) -> str:
        body = {"content": text}
        if session_id:
            body["session_id"] = session_id
        resp = await self.client.post("/api/chat/complete", json=body)
        assert resp.status_code == 200, resp.text
        return resp.json()["session_id"]

    async def attach(self, session_id, client=None):
        resp = await self.stream(request=None, session_id=session_id, client=client)
        it = resp.body_iterator
        assert _event(await it.__anext__())["type"] == "session_init"
        return it


async def test_continue_here_takes_an_idle_conversation_from_the_window_that_has_it(tmp_path):
    async with _Served(tmp_path) as s:
        sid = await s.turn("hello")
        a = await s.attach(sid, client="tab-a")
        waiting = asyncio.create_task(a.__anext__())
        await _settle()

        # Read-only is still the default answer for a second window.
        seen = (await s.client.get(f"/api/conversations/{sid}")).json()
        assert seen["connected"] is True and seen["running"] is False
        busy = await s.client.post(f"/api/conversations/{sid}/open")
        assert busy.status_code == 409 and busy.json()["detail"]["connected"] is True
        assert not waiting.done()

        # Asked to, the first window lets go, and the second can attach.
        taken = await s.client.post(f"/api/conversations/{sid}/open", params={"takeover": "true"})
        assert taken.status_code == 200, taken.text
        assert taken.json()["connected"] is False and taken.json()["messages"]
        assert _event(await waiting) == {"type": "superseded", "reason": "taken_over"}
        assert await _rest(a) == []
        b = await s.attach(sid, client="tab-b")
        with pytest.raises(HTTPException):  # and now the first window is the second one
            await s.stream(request=None, session_id=sid, client="tab-a")
        await b.aclose()


async def test_a_running_turn_is_never_taken_over(tmp_path):
    async with _Served(tmp_path) as s:
        sid = await s.turn("hello")
        a = await s.attach(sid, client="tab-a")
        session = s.adapter.get(sid)
        release = asyncio.Event()
        session.current_task = asyncio.create_task(release.wait())
        refused = await s.client.post(f"/api/conversations/{sid}/open", params={"takeover": "true"})
        assert refused.status_code == 409 and refused.json()["detail"]["running"] is True
        assert s.consumers.current(sid).client == "tab-a"  # still the first window's
        _say(session, "still mine")
        assert _event(await a.__anext__())["content"] == "still mine"
        release.set()
        await session.current_task
        await a.aclose()


async def test_a_reader_stuck_writing_to_a_dead_connection_does_not_block_a_takeover(tmp_path):
    """A connection that died without the server noticing sits in a write, not in a
    read. Taking over must not wait for it, and it must never read again."""
    async with _Served(tmp_path) as s:
        sid = await s.turn("hello")
        stale = await s.attach(sid, client="gone")  # suspended in its last write from here on
        async with asyncio.timeout(2):
            taken = await s.client.post(f"/api/conversations/{sid}/open", params={"takeover": "true"})
        assert taken.status_code == 200
        b = await s.attach(sid, client="tab-b")
        session = s.adapter.get(sid)
        _say(session, "for the new window")
        assert _event(await b.__anext__())["content"] == "for the new window"
        # Whenever the dead connection's write finally returns, it reads nothing.
        _say(session, "also for the new window")
        assert await _rest(stale) == [{"type": "superseded", "reason": "taken_over"}]
        assert _event(await b.__anext__())["content"] == "also for the new window"
        assert session.sse_connected and s.consumers.current(sid).client == "tab-b"
        await b.aclose()


async def test_reopening_a_conversation_drops_a_frame_no_reader_wrote(tmp_path):
    """Opening from History hands back the saved transcript, which already holds what
    any leftover frame said: a frame a reader took but never wrote is not replayed."""
    async with _Served(tmp_path) as s:
        sid = await s.turn("hello")
        a = await s.attach(sid, client="tab-a")
        session = s.adapter.get(sid)
        waiting = asyncio.create_task(a.__anext__())
        await _settle()
        _say(session, "stale")
        s.consumers.current(sid).evict("taken_over")  # the frame is read as the reader stops
        assert _event(await waiting)["type"] == "superseded"
        await a.aclose()
        assert (await s.client.post(f"/api/conversations/{sid}/open")).status_code == 200
        b = await s.attach(sid, client="tab-b")
        _say(session, "fresh")
        assert _event(await b.__anext__())["content"] == "fresh"
        await b.aclose()


# ── other readers of the queue ───────────────────────────────────────────────


async def test_the_buffered_turn_and_a_stream_do_not_share_a_session(tmp_path):
    async with _Served(tmp_path) as s:
        sid = await s.turn("hello")
        a = await s.attach(sid, client="tab-a")
        # A stream is attached: a buffered turn on that session would take its frames.
        refused = await s.client.post("/api/chat/complete", json={"content": "again", "session_id": sid})
        assert refused.status_code == 409 and "open event stream" in refused.json()["detail"]
        await a.aclose()
        assert await s.turn("again", sid) == sid  # fine once the stream is gone
        assert not s.consumers.attached(sid)  # and the buffered turn let go afterwards

        # While a buffered turn reads the queue, a stream can't attach.
        hold = s.consumers.hold(sid)
        with pytest.raises(HTTPException) as busy:
            await s.stream(request=None, session_id=sid, client="tab-a")
        assert busy.value.status_code == 409
        s.consumers.release(hold)


async def test_a_session_with_a_reader_is_not_reaped(monkeypatch):
    monkeypatch.setattr(routes_chat, "SESSION_REAP_GRACE_S", 0.01)
    rig = _Rig()
    a = await rig.attach(client="tab-a")
    session = rig.adapter.get("s1")
    session.sse_connected = False  # as a replaced connection closing late would leave it
    await routes_chat._reap_when_idle(rig.adapter, "s1", rig.consumers)
    assert rig.adapter.get("s1") is session
    await a.aclose()


# ── through a real server: the issue's repro ─────────────────────────────────


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_two_http_clients_on_one_session_do_not_split_the_reply(tmp_path):
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    cwd = os.getcwd()
    handle = None
    got: dict[str, list[dict]] = {"a": [], "b": []}
    status: dict[str, int] = {}
    opened = {name: threading.Event() for name in got}
    stop = threading.Event()

    def consume(name: str) -> None:
        try:
            with urllib.request.urlopen(f"{base}/api/stream?session_id=s1", timeout=30) as resp:
                status[name] = resp.status
                opened[name].set()
                for raw in resp:
                    line = raw.decode().strip()
                    if line.startswith("data:"):
                        got[name].append(json.loads(line[5:]))
                        if got[name][-1]["type"] == "complete" or stop.is_set():
                            return
        except urllib.error.HTTPError as exc:
            status[name] = exc.code
        except Exception:  # noqa: BLE001 - the server closing the stream at the end
            pass
        finally:
            opened[name].set()

    try:
        handle = CoworkApp(agent_spec=TOOLS, workspace=tmp_path, port=port).run(open_browser=False)
        first = threading.Thread(target=consume, args=("a",), daemon=True)
        first.start()
        assert await asyncio.to_thread(opened["a"].wait, 15)
        second = threading.Thread(target=consume, args=("b",), daemon=True)
        second.start()
        assert await asyncio.to_thread(opened["b"].wait, 15)

        def chat() -> int:
            req = urllib.request.Request(
                f"{base}/api/chat",
                data=json.dumps({"session_id": "s1", "content": "use a tool please"}).encode(),
                headers={"content-type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status

        assert await asyncio.to_thread(chat) == 200
        await asyncio.to_thread(first.join, 30)
        assert status == {"a": 200, "b": 409}
        assert got["b"] == []
        kinds = [e["type"] for e in got["a"]]
        assert kinds[0] == "session_init" and kinds[-1] == "complete"
        assert kinds.index("tool_start") < kinds.index("tool_end")
        text = "".join(e["content"] for e in got["a"] if e["type"] == "content")
        assert text.startswith("The demo tool returned") and text.rstrip().endswith("flow.")
    finally:
        stop.set()
        if handle is not None and handle.running:
            await asyncio.to_thread(handle.stop, 10.0)
        os.chdir(cwd)
