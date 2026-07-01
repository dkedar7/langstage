"""Experimental AG-UI chat path for the web app (ADR 0002).

The config toggle (LANGSTAGE_AGUI) flips SessionAdapter into its in-process AG-UI
mode, which emits the same SSE frames — so the frontend is unchanged. The frame
mapping + outcome tracking live in the core (langgraph-stream-parser); here we
verify the web's toggle wiring and one end-to-end stream.
"""

import pytest

from langstage.config import AppConfig


def test_agui_toggle_defaults_off():
    assert AppConfig().agui is None
    assert bool(AppConfig().agui) is False  # coerced off when unset (as main.py does)


def test_agui_toggle_from_env(monkeypatch):
    monkeypatch.setenv("LANGSTAGE_AGUI", "1")
    assert AppConfig.from_env().agui is True


def test_agui_toggle_legacy_env(monkeypatch):
    monkeypatch.delenv("LANGSTAGE_AGUI", raising=False)
    monkeypatch.setenv("DEEPAGENT_AGUI", "true")
    assert AppConfig.from_env().agui is True


# ── end-to-end (requires the agui extra) ─────────────────────────────

pytest.importorskip("ag_ui_langgraph")


@pytest.mark.asyncio
async def test_session_adapter_agui_streams_via_web_dep():
    from langgraph_stream_parser import load_agent_spec
    from langgraph_stream_parser.adapters import SessionAdapter

    adapter = SessionAdapter(
        graph=load_agent_spec("langgraph_stream_parser.demo.stub:graph"),
        max_result_len=50_000,
        agui=True,
    )
    session = adapter.submit_message("s1", "hello web agui")
    await session.current_task
    frames = []
    while not session.event_queue.empty():
        frames.append(session.event_queue.get_nowait())
    assert frames[-1]["type"] == "complete"
    assert session.outcome == "complete"
    assert "hello web agui" in "".join(f["content"] for f in frames if f["type"] == "content")
