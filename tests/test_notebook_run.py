"""`CoworkApp.run()` inside a running event loop — i.e. a Jupyter notebook (gh #87)."""
import asyncio
import os
import socket
import urllib.request

import pytest

from langstage import BackgroundServer, CoworkApp
from langstage.app import _in_running_event_loop

DEMO_SPEC = "langstage_core.demo.stub:graph"  # keyless stub agent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── loop detection ───────────────────────────────────────────────────


def test_in_running_event_loop_is_false_in_a_script():
    assert _in_running_event_loop() is False


async def test_in_running_event_loop_is_true_inside_a_loop():
    # A Jupyter kernel looks exactly like this to run().
    assert _in_running_event_loop() is True


# ── script / CLI path is unchanged ───────────────────────────────────


def test_run_delegates_to_blocking_uvicorn_run_in_a_script(monkeypatch, tmp_path):
    called = {}

    def fake_uvicorn_run(app, **kwargs):
        called.update(kwargs)

    monkeypatch.setattr("langstage.app.uvicorn.run", fake_uvicorn_run)
    cwd = os.getcwd()
    try:
        app = CoworkApp(agent_spec=DEMO_SPEC, workspace=tmp_path, port=_free_port())
        assert app.run(open_browser=False) is None  # blocking path returns None
    finally:
        os.chdir(cwd)
    assert "port" in called and "host" in called


# ── notebook path (gh #87) ───────────────────────────────────────────


async def test_run_in_a_notebook_serves_on_a_background_thread(tmp_path):
    # Before the fix this raised
    # "RuntimeError: Cannot run the event loop while another loop is running".
    port = _free_port()
    cwd = os.getcwd()
    handle = None
    try:
        app = CoworkApp(agent_spec=DEMO_SPEC, workspace=tmp_path, port=port)
        handle = app.run(open_browser=False)

        assert isinstance(handle, BackgroundServer)
        assert handle.running
        assert handle.url.endswith(f":{port}")

        # It genuinely serves. Probe OFF the loop: a blocking call from the loop
        # thread would stall the very loop a browser's request rides on.
        body = await asyncio.to_thread(
            lambda: urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/health", timeout=10
            ).read().decode()
        )
        assert '"status":"ok"' in body

        handle.stop()
        assert not handle.running
    finally:
        if handle is not None and handle.running:
            handle.stop()
        os.chdir(cwd)


async def test_run_in_a_notebook_raises_a_clean_error_when_the_port_is_taken(tmp_path):
    # Otherwise the thread dies silently (and, served on the kernel's own loop,
    # uvicorn's sys.exit(STARTUP_FAILURE) would take the whole kernel down).
    cwd = os.getcwd()
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        port = taken.getsockname()[1]
        try:
            app = CoworkApp(agent_spec=DEMO_SPEC, workspace=tmp_path, port=port)
            with pytest.raises(RuntimeError, match="failed to start"):
                app.run(open_browser=False)
        finally:
            os.chdir(cwd)
