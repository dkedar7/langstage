"""AG-UI chat path for the web app — the SessionAdapter's only streaming path
since core 1.0 (ADR 0003).

The adapter streams every turn through the in-process AG-UI adapter, emitting the
same SSE frames the frontend already consumes. The frame mapping + outcome
tracking live in the core (langstage-core); here we verify one end-to-end stream.
"""

import pytest

# The AG-UI runtime is a base dependency (core's [agui] extra); importorskip is a
# safety net so a stripped env degrades gracefully rather than erroring at collect.
pytest.importorskip("ag_ui_langgraph")


@pytest.mark.asyncio
async def test_session_adapter_streams_agui_frames():
    from langstage_core import load_agent_spec
    from langstage_core.adapters import SessionAdapter

    adapter = SessionAdapter(
        graph=load_agent_spec("langstage_core.demo.stub:graph"),
        max_result_len=50_000,
    )
    session = adapter.submit_message("s1", "hello web agui")
    await session.current_task
    frames = []
    while not session.event_queue.empty():
        frames.append(session.event_queue.get_nowait())
    assert frames[-1]["type"] == "complete"
    assert session.outcome == "complete"
    assert "hello web agui" in "".join(f["content"] for f in frames if f["type"] == "content")
