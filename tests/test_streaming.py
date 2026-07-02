"""Integration tests for the streaming pipe via the shared SessionAdapter.

The streaming machinery lives in ``langstage_core.adapters.SessionAdapter`` — which
since core 1.0 (ADR 0003) streams every turn through the in-process AG-UI adapter,
so these use real compiled graphs (the demo stub + a boom graph), not a fake. These
guard the cowork-level wiring: that a real agent's events reach the session queue,
that the cwd/context injection survives to the agent, and that the core API contract
cowork depends on (``prepare_agent_input`` / ``create_resume_input``) hasn't drifted.
"""

import inspect

import pytest
from langgraph.graph import END, START, MessagesState, StateGraph

from langstage_core import load_agent_spec
from langstage_core.adapters import SessionAdapter

from langstage.server.routes_chat import context_parts

# The AG-UI runtime is a base dependency (core's [agui] extra); safety net so a
# stripped env degrades gracefully rather than erroring at collection time.
pytest.importorskip("ag_ui_langgraph")


def _stub():
    """The keyless demo echo agent — echoes the user's last message."""
    return load_agent_spec("langstage_core.demo.stub:graph")


def _boom_graph():
    """A compiled graph whose only node raises, to exercise error surfacing."""
    def boom(state):
        raise RuntimeError("synthetic model failure")

    b = StateGraph(MessagesState)
    b.add_node("boom", boom)
    b.add_edge(START, "boom")
    b.add_edge("boom", END)
    return b.compile()


def _drain(queue):
    out = []
    while not queue.empty():
        out.append(queue.get_nowait())
    return out


# --- Happy path --------------------------------------------------------------


async def test_stream_delivers_content_and_complete():
    adapter = SessionAdapter(graph=_stub())
    session = adapter.submit_message("s1", "say hi")
    await session.current_task

    types = [e.get("type") for e in _drain(session.event_queue)]
    assert "content" in types
    assert "complete" in types
    assert "error" not in types


async def test_message_and_cwd_reach_the_agent():
    """The user message + cwd context must survive prepare_agent_input to the agent.

    The stub echoes the human message it receives, so both the message and the
    injected cwd context appear in the streamed content.
    """
    adapter = SessionAdapter(graph=_stub())
    session = adapter.submit_message(
        "s-ctx", "the magic phrase",
        context_parts=context_parts(cwd="/tmp/test-workspace"),
    )
    await session.current_task

    content = "".join(
        e.get("content", "") for e in _drain(session.event_queue) if e.get("type") == "content"
    )
    assert "the magic phrase" in content
    assert "/tmp/test-workspace" in content


# --- Error path --------------------------------------------------------------


async def test_stream_surfaces_errors_as_events():
    adapter = SessionAdapter(graph=_boom_graph())
    session = adapter.submit_message("s-err", "hi")
    await session.current_task

    events = _drain(session.event_queue)
    types = [e.get("type") for e in events]
    assert "error" in types
    err = next(e for e in events if e.get("type") == "error")
    assert "synthetic model failure" in err.get("error", "")


# --- Library API contract (guards against core drift) ------------------------


def test_context_parts_includes_time_and_cwd():
    parts = context_parts(cwd="/work")
    assert any("Current time" in p for p in parts)
    assert any("/work" in p for p in parts)
    # Without cwd, only the time line is present.
    assert len(context_parts()) == 1


def test_prepare_agent_input_contract():
    from langstage_core import prepare_agent_input

    sig = inspect.signature(prepare_agent_input)
    assert "message" in sig.parameters
    assert "context_parts" in sig.parameters  # cowork relies on this
    assert prepare_agent_input(message="hi") is not None


def test_create_resume_input_contract():
    from langstage_core import create_resume_input

    sig = inspect.signature(create_resume_input)
    assert "decisions" in sig.parameters
    assert create_resume_input(decisions=[{"type": "approve"}]) is not None
