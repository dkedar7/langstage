"""A client leaving /api/stream is silent and its session is still reaped (gh #216).

0.13.55's shutdown wrapper (gh #211) read the session stream in a separate task. When
a client disconnected, that task was left running inside the stream, so closing the
stream raised "aclose(): asynchronous generator is already running": every tab close
logged a traceback, and the session was never marked disconnected or reaped (#164).
"""
import asyncio
import json
import logging
import os
import socket
import threading
import time
import urllib.request

import pytest

from langstage import CoworkApp
from langstage.server import routes_chat
from langstage.server.shutdown import until_shutdown

DEMO_SPEC = "langstage_core.demo.stub:graph"  # keyless stub agent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_cancelled_reader_leaves_the_stream_closable():
    """Cancelling a consumer mid-wait must not leave the inner stream running."""
    closed = []

    async def frames_forever():
        try:
            yield "first"
            await asyncio.Event().wait()
        finally:
            closed.append(True)

    frames = frames_forever()

    async def consume():
        async for _ in until_shutdown(frames, asyncio.Event()):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)  # now parked waiting for the second frame
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await frames.aclose()  # raised "already running" before the fix
    assert closed == [True]


class _Errors(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def _sessions(port: int) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/sessions", timeout=5) as r:
        return {s["session_id"]: s for s in json.load(r)}


async def test_disconnect_through_the_server_is_silent_and_reaped(tmp_path, monkeypatch):
    """A real HTTP client opens the stream and leaves: no ASGI error, the session goes
    disconnected and is reaped (#164), and Ctrl+C handling (#211) still works after."""
    monkeypatch.setattr(routes_chat, "SESSION_REAP_GRACE_S", 0.2)
    errors = _Errors()
    loggers = [logging.getLogger(n) for n in ("uvicorn.error", "uvicorn", "")]
    for lg in loggers:
        lg.addHandler(errors)
    port = _free_port()
    cwd = os.getcwd()
    handle = None
    try:
        handle = CoworkApp(agent_spec=DEMO_SPEC, workspace=tmp_path, port=port).run(open_browser=False)
        for sid in ("leak1", "leak2"):
            def _visit(sid=sid):
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/stream?session_id={sid}",
                                            timeout=10) as r:
                    r.read(1)  # connected; then the "tab" closes
            await asyncio.to_thread(_visit)
        deadline = time.monotonic() + 10
        left = set()
        while time.monotonic() < deadline:
            left = {"leak1", "leak2"} & set(await asyncio.to_thread(_sessions, port))
            if not left:
                break
            await asyncio.sleep(0.2)
        assert not left, f"sessions never reaped: {left}"
        assert not [m for m in errors.messages if "ASGI" in m or "already running" in m], errors.messages

        # #211 still holds: stop() with a tab open ends promptly.
        opened = threading.Event()

        def _tab():
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/stream?session_id=tab",
                                            timeout=30) as r:
                    opened.set()
                    while r.read(1):
                        pass
            except Exception:  # noqa: BLE001 - the server closing the stream is the point
                opened.set()

        reader = threading.Thread(target=_tab, daemon=True)
        reader.start()
        assert await asyncio.to_thread(opened.wait, 10)
        t0 = time.monotonic()
        await asyncio.to_thread(handle.stop, 10.0)
        assert not handle.running and time.monotonic() - t0 < 4
        assert not [m for m in errors.messages if "ASGI" in m or "already running" in m], errors.messages
    finally:
        for lg in loggers:
            lg.removeHandler(errors)
        if handle is not None and handle.running:
            handle.stop()
        os.chdir(cwd)
