"""Integration tests for sse_adapter — exercises the full streaming pipe with a fake agent.

Motivation: run_agent_stream composes langgraph-stream-parser + a live agent, which
is exactly where API drift between those libraries lands. This file deliberately
does *not* mock run_agent_stream — it calls it with a conformant fake agent and
asserts the session queue receives the expected sequence of events.

If someone changes langgraph-stream-parser's `prepare_agent_input` signature or
StreamParser's output shape, these tests break loudly instead of silently
passing while the UI hangs.
"""

from langchain_core.messages import AIMessageChunk

from cowork_dash.stream.session_manager import AgentSession, SessionManager
from cowork_dash.stream.sse_adapter import run_agent_stream, run_interrupt_response


class FakeStreamingAgent:
    """A minimal CompiledStateGraph-ish stand-in.

    Yields tuples matching LangGraph's dual stream_mode=["updates", "messages"]
    format: ("messages", (AIMessageChunk, metadata)) for content, and
    ("updates", {...}) for node state updates. StreamParser should turn these
    into ContentEvent + CompleteEvent.
    """

    def __init__(self, chunks: list[str] | None = None):
        self._chunks = chunks if chunks is not None else ["Hello", " world"]
        self.calls: list[dict] = []

    async def astream(self, input_data, config=None, stream_mode=None):
        self.calls.append({"input": input_data, "config": config, "stream_mode": stream_mode})
        # Emit content tokens as AIMessageChunk via the "messages" stream
        for text in self._chunks:
            yield ("messages", (AIMessageChunk(content=text), {"langgraph_node": "model"}))
        # A terminal update so StreamParser emits CompleteEvent
        yield ("updates", {"model": {"messages": [AIMessageChunk(content="")]}})


class FailingAgent:
    """Agent whose astream raises partway through — exercises error handling."""

    async def astream(self, input_data, config=None, stream_mode=None):
        yield ("messages", (AIMessageChunk(content="partial"), {"langgraph_node": "model"}))
        raise RuntimeError("synthetic model failure")


# --- Happy path --------------------------------------------------------------


async def test_run_agent_stream_delivers_content_and_complete():
    """Smoke test: fake agent streams two content chunks → session queue sees them."""
    session = AgentSession()
    agent = FakeStreamingAgent(chunks=["Hi", " there"])

    await run_agent_stream(agent=agent, session=session, content="say hi")

    events: list[dict] = []
    while not session.event_queue.empty():
        events.append(await session.event_queue.get())

    types = [e.get("type") for e in events]
    assert "content" in types, f"Expected content events, got {types}"
    assert "complete" in types, f"Expected complete event, got {types}"
    # The error type must NOT appear on a happy path
    assert "error" not in types, f"Unexpected error: {[e for e in events if e.get('type') == 'error']}"


async def test_run_agent_stream_passes_message_through_prepare_agent_input():
    """Guards against API drift in prepare_agent_input — the exact bug that shipped in 0.3.6.

    If prepare_agent_input's signature changes (or sse_adapter misuses it), this
    test fails immediately instead of the UI hanging silently.
    """
    session = AgentSession()
    agent = FakeStreamingAgent()

    await run_agent_stream(
        agent=agent,
        session=session,
        content="the magic phrase",
        cwd="/tmp/test-workspace",
    )

    assert agent.calls, "astream was never invoked"
    input_data = agent.calls[0]["input"]
    # The input must contain the user's message somewhere. Shape can vary
    # across langgraph-stream-parser versions, but the message must be present.
    serialized = str(input_data)
    assert "the magic phrase" in serialized, f"User message lost in transit: {input_data!r}"
    # Context annotation (cwd) should also be present
    assert "/tmp/test-workspace" in serialized, f"cwd context missing: {input_data!r}"


async def test_run_agent_stream_forwards_config_thread_id():
    """Each session's thread_id must be threaded into the agent config."""
    session = AgentSession()
    agent = FakeStreamingAgent()

    await run_agent_stream(agent=agent, session=session, content="hi")

    cfg = agent.calls[0]["config"]
    assert cfg is not None
    assert cfg.get("configurable", {}).get("thread_id") == session.thread_id


# --- Error path --------------------------------------------------------------


async def test_run_agent_stream_surfaces_errors_as_events():
    """When the agent raises, the UI must see an error event — not silent hang."""
    session = AgentSession()
    agent = FailingAgent()

    await run_agent_stream(agent=agent, session=session, content="hi")

    events: list[dict] = []
    while not session.event_queue.empty():
        events.append(await session.event_queue.get())

    types = [e.get("type") for e in events]
    assert "error" in types, f"Expected error event, got {types}"
    error_event = next(e for e in events if e.get("type") == "error")
    assert "synthetic model failure" in error_event.get("error", "")


async def test_run_agent_stream_bad_kwargs_surface_as_error(monkeypatch):
    """If sse_adapter ever calls a library with a bad kwarg (the 0.3.6 bug),
    the try/except must convert it to an error event reaching the UI."""
    session = AgentSession()
    agent = FakeStreamingAgent()

    # Simulate the exact class of bug: prepare_agent_input raising TypeError
    def broken(*args, **kwargs):
        raise TypeError("prepare_agent_input() got unexpected kwarg 'context_parts'")

    monkeypatch.setattr("cowork_dash.stream.sse_adapter.prepare_agent_input", broken)

    await run_agent_stream(agent=agent, session=session, content="hi")

    events = []
    while not session.event_queue.empty():
        events.append(await session.event_queue.get())
    types = [e.get("type") for e in events]
    assert "error" in types, f"TypeError leaked instead of becoming error event: {types}"


# --- Interrupt path ----------------------------------------------------------


async def test_run_interrupt_response_delivers_events():
    """Resuming from an interrupt must follow the same event pipe."""
    session = AgentSession()
    agent = FakeStreamingAgent(chunks=["resumed"])

    await run_interrupt_response(agent=agent, session=session, decisions=[{"type": "approve"}])

    events = []
    while not session.event_queue.empty():
        events.append(await session.event_queue.get())
    types = [e.get("type") for e in events]
    assert "error" not in types
    assert "content" in types or "complete" in types, f"No stream events: {types}"


# --- SessionManager glue -----------------------------------------------------


def test_session_manager_get_or_create_reuses_existing():
    sm = SessionManager()
    a = sm.get_or_create()
    b = sm.get_or_create(session_id=a.thread_id)
    assert a is b


def test_session_manager_get_or_create_new_when_unknown_id():
    sm = SessionManager()
    a = sm.get_or_create(session_id="never-seen")
    assert a.thread_id != "never-seen"  # A fresh session was made


def test_session_manager_delete_cancels_and_removes():
    sm = SessionManager()
    s = sm.get_or_create()
    assert sm.delete_session(s.thread_id) is True
    assert sm.get_session_by_id(s.thread_id) is None
    assert sm.delete_session(s.thread_id) is False


# --- Library API contract (guards against langgraph-stream-parser drift) ------


def test_prepare_agent_input_contract():
    """Regression guard for the 0.3.6 bug: prepare_agent_input's signature.

    If langgraph-stream-parser renames/removes 'message', or sse_adapter starts
    passing an unsupported kwarg, this fails fast instead of hanging the UI.
    """
    import inspect

    from langgraph_stream_parser import prepare_agent_input

    sig = inspect.signature(prepare_agent_input)
    assert "message" in sig.parameters, (
        f"prepare_agent_input must accept 'message' kwarg; sse_adapter depends on it. "
        f"Got: {list(sig.parameters.keys())}"
    )
    # Smoke-call with the exact kwarg shape sse_adapter uses
    result = prepare_agent_input(message="hi")
    assert result is not None


def test_create_resume_input_contract():
    """Regression guard for the resume/interrupt path: create_resume_input signature."""
    import inspect

    from langgraph_stream_parser import create_resume_input

    sig = inspect.signature(create_resume_input)
    assert "decisions" in sig.parameters, (
        f"create_resume_input must accept 'decisions' kwarg. Got: {list(sig.parameters.keys())}"
    )
    result = create_resume_input(decisions=[{"type": "approve"}])
    assert result is not None
