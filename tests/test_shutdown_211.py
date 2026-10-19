"""One Ctrl+C / SIGTERM / stop() ends the server even with the UI's SSE stream open (gh #211)."""
import asyncio
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import pytest

from langstage import CoworkApp
from langstage.server.shutdown import until_shutdown

DEMO_SPEC = "langstage_core.demo.stub:graph"  # keyless stub agent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _open_stream(port: int, opened: threading.Event) -> threading.Thread:
    """An open browser tab: a GET /api/stream that's read until the server ends it."""

    def _read() -> None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/stream?session_id=tab", timeout=60) as r:
                opened.set()
                while r.read(1):
                    pass
        except Exception:  # noqa: BLE001 - the server closing the stream is the point
            opened.set()

    t = threading.Thread(target=_read, daemon=True)
    t.start()
    return t


async def test_until_shutdown_ends_a_stream_that_never_ends():
    stop = asyncio.Event()
    closed = []

    async def forever():
        try:
            yield "first"
            await asyncio.Event().wait()
        finally:
            closed.append(True)

    frames = forever()
    got = []

    async def consume():
        async for f in until_shutdown(frames, stop):
            got.append(f)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=2)
    assert got == ["first"] and closed == [True]


async def test_until_shutdown_passes_a_finite_stream_through():
    async def three():
        for i in range(3):
            yield i

    assert [f async for f in until_shutdown(three(), asyncio.Event())] == [0, 1, 2]


async def test_notebook_stop_ends_with_a_tab_open(tmp_path):
    port = _free_port()
    cwd = os.getcwd()
    handle = None
    try:
        handle = CoworkApp(agent_spec=DEMO_SPEC, workspace=tmp_path, port=port).run(open_browser=False)
        opened = threading.Event()
        reader = _open_stream(port, opened)
        assert await asyncio.to_thread(opened.wait, 10)
        await asyncio.sleep(0.3)
        t0 = time.monotonic()
        await asyncio.to_thread(handle.stop, 10.0)
        assert not handle.running, "server thread still alive with an SSE client connected"
        assert time.monotonic() - t0 < 4  # not the graceful-shutdown backstop
        await asyncio.to_thread(reader.join, 5)
        assert not reader.is_alive()
    finally:
        if handle is not None and handle.running:
            handle.stop()
        os.chdir(cwd)


@pytest.mark.skipif(sys.platform == "win32", reason="SIGINT to a child process is POSIX-only")
def test_cli_sigint_exits_with_a_tab_open(tmp_path):
    import signal

    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "langstage", "run", "--demo", "--no-browser", "--port", str(port)],
        cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1)
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        opened = threading.Event()
        _open_stream(port, opened)
        assert opened.wait(10)
        time.sleep(0.3)
        proc.send_signal(signal.SIGINT)
        out, _ = proc.communicate(timeout=15)
        text = out.decode("utf-8", "replace")
        assert "Application shutdown complete" in text, text[-2000:]
        assert "Traceback" not in text, text[-2000:]
    finally:
        if proc.poll() is None:
            proc.kill()
