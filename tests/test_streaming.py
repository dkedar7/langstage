"""Integration tests for the streaming pipe via the shared SessionAdapter.

The streaming machinery moved to ``langgraph_stream_parser.adapters.SessionAdapter``
(tested in the parser's own suite). These tests guard the cowork-level wiring:
that a conformant agent's events reach the session queue, that the cwd/context
injection survives, and that the langgraph-stream-parser API contract cowork
depends on (``prepare_agent_input`` / ``create_resume_input``) hasn't drifted —
the class of bug that shipped in 0.3.6.
"""

import inspect

from langchain_core.messages import AIMessageChunk
from langgraph_stream_parser.adapters import SessionAdapter

from cowork_dash.server.routes_chat import context_parts


class FakeStreamingAgent:
    """Minimal CompiledStateGraph-ish stand-in for dual stream_mode."""

    def __init__(self, chunks: list[str] | None = None):
        self._chunks = chunks if chunks is not None else ["Hello", " world"]
        self.calls: list[dict] = []

    async def astream(self, input_data, config=None, stream_mode=None):
        self.calls.append({"input": input_data, "config": config, "stream_mode": stream_mode})
        for text in self._chunks:
            yield ("messages", (AIMessageChunk(content=text), {"langgraph_node": "model"}))
        yield ("updates", {"model": {"messages": [AIMessageChunk(content="")]}})


class FailingAgent:
    async def astream(self, input_data, config=None, stream_mode=None):
        yield ("messages", (AIMessageChunk(content="partial"), {"langgraph_node": "model"}))
        raise RuntimeError("synthetic model failure")


def _drain(queue):
    out = []
    while not queue.empty():
        out.append(queue.get_nowait())
    return out


# --- Happy path --------------------------------------------------------------


async def test_stream_delivers_content_and_complete():
    adapter = SessionAdapter(graph=FakeStreamingAgent(chunks=["Hi", " there"]))
    session = adapter.submit_message("s1", "say hi")
    await session.current_task

    types = [e.get("type") for e in _drain(session.event_queue)]
    assert "content" in types
    assert "complete" in types
    assert "error" not in types


async def test_message_and_cwd_reach_the_agent():
    """The user message + cwd context must survive prepare_agent_input."""
    agent = FakeStreamingAgent()
    adapter = SessionAdapter(graph=agent)

    session = adapter.submit_message(
        "s-ctx", "the magic phrase",
        context_parts=context_parts(cwd="/tmp/test-workspace"),
    )
    await session.current_task

    serialized = str(agent.calls[0]["input"])
    assert "the magic phrase" in serialized
    assert "/tmp/test-workspace" in serialized


async def test_thread_id_forwarded_to_config():
    agent = FakeStreamingAgent()
    adapter = SessionAdapter(graph=agent)
    session = adapter.submit_message("s-thread", "hi")
    await session.current_task

    cfg = agent.calls[0]["config"]
    assert cfg["configurable"]["thread_id"] == "s-thread"


# --- Error path --------------------------------------------------------------


async def test_stream_surfaces_errors_as_events():
    adapter = SessionAdapter(graph=FailingAgent())
    session = adapter.submit_message("s-err", "hi")
    await session.current_task

    events = _drain(session.event_queue)
    types = [e.get("type") for e in events]
    assert "error" in types
    err = next(e for e in events if e.get("type") == "error")
    assert "synthetic model failure" in err.get("error", "")


# --- Library API contract (guards against langgraph-stream-parser drift) ------


def test_context_parts_includes_time_and_cwd():
    parts = context_parts(cwd="/work")
    assert any("Current time" in p for p in parts)
    assert any("/work" in p for p in parts)
    # Without cwd, only the time line is present.
    assert len(context_parts()) == 1


def test_prepare_agent_input_contract():
    from langgraph_stream_parser import prepare_agent_input

    sig = inspect.signature(prepare_agent_input)
    assert "message" in sig.parameters
    assert "context_parts" in sig.parameters  # cowork relies on this
    assert prepare_agent_input(message="hi") is not None


def test_create_resume_input_contract():
    from langgraph_stream_parser import create_resume_input

    sig = inspect.signature(create_resume_input)
    assert "decisions" in sig.parameters
    assert create_resume_input(decisions=[{"type": "approve"}]) is not None
