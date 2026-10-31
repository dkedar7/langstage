"""gh #223: the StatusBar "Token usage" counter needs a `usage` frame per turn.

Core doesn't emit one (langstage-core#155), so the web stage reads the model's
standard ``usage_metadata`` with a per-turn callback and sends the turn's totals.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

pytest.importorskip("ag_ui_langgraph")


class UsageModel(BaseChatModel):
    """Keyless model that reports usage the standard LangChain way (the issue's repro)."""

    @property
    def _llm_type(self) -> str:
        return "usage-fake"

    def bind_tools(self, tools: Any, **kw: Any):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kw):
        m = AIMessage(
            content="Hello from a model that reports usage.",
            usage_metadata={"input_tokens": 120, "output_tokens": 30, "total_tokens": 150},
        )
        return ChatResult(generations=[ChatGeneration(message=m)])



class StreamingUsageModel(UsageModel):
    """Streams its reply; usage arrives on the last chunk, as OpenAI-style providers do."""

    def _stream(self, messages, stop=None, run_manager=None, **kw):
        yield ChatGenerationChunk(message=AIMessageChunk(content="Hello "))
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content="streamed.",
                usage_metadata={"input_tokens": 40, "output_tokens": 10, "total_tokens": 50},
            )
        )


def _graph(model: BaseChatModel):
    from langchain.agents import create_agent
    from langgraph.checkpoint.memory import InMemorySaver

    return create_agent(model, tools=[], checkpointer=InMemorySaver())


async def _turn(adapter, session_id: str, text: str) -> list[dict]:
    session = adapter.submit_message(session_id, text)
    await session.current_task
    frames = []
    while not session.event_queue.empty():
        frames.append(session.event_queue.get_nowait())
    return frames


def _usage(frames: list[dict]) -> list[dict]:
    return [f for f in frames if f["type"] == "usage"]


@pytest.mark.asyncio
async def test_each_turn_ends_with_its_usage():
    from langstage.server.usage import UsageSessionAdapter

    adapter = UsageSessionAdapter(graph=_graph(UsageModel()), max_result_len=50_000)
    for _ in range(2):
        frames = await _turn(adapter, "s1", "hi")
        assert any(f["type"] == "complete" for f in frames)
        # Per turn, not cumulative: the frontend sums turns itself.
        assert _usage(frames) == [
            {"type": "usage", "input_tokens": 120, "output_tokens": 30, "total_tokens": 150, "node": None}
        ]


@pytest.mark.asyncio
async def test_streamed_usage_is_counted():
    from langstage.server.usage import UsageSessionAdapter

    adapter = UsageSessionAdapter(graph=_graph(StreamingUsageModel()), max_result_len=50_000)
    frames = await _turn(adapter, "s2", "hi")
    assert [(u["input_tokens"], u["output_tokens"], u["total_tokens"]) for u in _usage(frames)] == [(40, 10, 50)]


@pytest.mark.asyncio
async def test_no_usage_frame_without_usage():
    """A model that reports nothing (the demo stub) sends no frame, so the counter stays hidden."""
    from langstage_core import load_agent_spec

    from langstage.server.usage import UsageSessionAdapter

    adapter = UsageSessionAdapter(graph=load_agent_spec("langstage_core.demo.stub:graph"), max_result_len=50_000)
    frames = await _turn(adapter, "s3", "hello")
    assert frames[-1]["type"] == "complete"
    assert _usage(frames) == []


@pytest.mark.asyncio
async def test_sessions_do_not_share_counts():
    import asyncio

    from langstage.server.usage import UsageSessionAdapter

    adapter = UsageSessionAdapter(graph=_graph(UsageModel()), max_result_len=50_000)
    a = adapter.submit_message("a", "hi")
    b = adapter.submit_message("b", "hi")
    await asyncio.gather(a.current_task, b.current_task)
    for s in (a, b):
        frames = []
        while not s.event_queue.empty():
            frames.append(s.event_queue.get_nowait())
        assert [u["total_tokens"] for u in _usage(frames)] == [150]


def test_usage_frame_sums_calls_and_fills_total():
    from langstage.server.usage import usage_frame

    assert usage_frame([]) is None
    assert usage_frame([{"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}]) is None
    f = usage_frame([
        {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        {"input_tokens": 3, "output_tokens": 2},
    ])
    assert (f["input_tokens"], f["output_tokens"], f["total_tokens"]) == (13, 7, 20)


def test_one_hook_registered_not_one_per_turn():
    """langchain's get_usage_metadata_callback() adds a global hook per call; ours is registered once."""
    from langchain_core.tracers import context

    import langstage.server.usage  # noqa: F401

    names = [h[0].name for h in context._configure_hooks if hasattr(h[0], "name")]
    assert names.count("langstage_turn_usage") == 1


def test_server_uses_the_usage_adapter():
    from langstage.server import main

    assert "UsageSessionAdapter(" in open(main.__file__, encoding="utf-8").read()
