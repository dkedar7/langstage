"""gh #173: SSE ``node`` attribution on a multi-node graph with a non-streamed tool call.

The issue's graph returns complete messages from three nodes: ``agent`` makes the tool
call, ``tools`` answers it, ``final`` writes the reply. On the web app's SQLite
checkpointer (the ``AsyncSqliteSaver`` the server lifespan swaps in), ``tool_start``
came out labeled ``final`` and the reply ``agent``. Core 1.0.37 (#188) records each
message's node from the step's own update, so the labels no longer depend on when the
checkpoint write lands. These tests drive the same ``SessionAdapter`` path that feeds
``/api/stream``, under the real lifespan's saver and under a saver whose writes land
late (the deterministic form of the race).
"""
import asyncio
import textwrap

import pytest
from langstage_core.adapters import SessionAdapter

from langstage.app import CoworkApp
from langstage.config import AppConfig
from langstage.server.main import create_fastapi_app

pytest.importorskip("ag_ui_langgraph")
pytest.importorskip("langgraph.checkpoint.sqlite.aio")

_AGENT = """
    from langgraph.graph import StateGraph, START, END, MessagesState
    from langchain_core.messages import AIMessage, ToolMessage

    def agent(state: MessagesState):
        return {"messages": [AIMessage(content="", tool_calls=[
            {"name": "get_weather", "args": {"city": "Paris"}, "id": "call_1"}])]}
    def tools(state: MessagesState):
        return {"messages": [ToolMessage(content="Sunny, 21C", tool_call_id="call_1",
                                         name="get_weather")]}
    def final(state: MessagesState):
        return {"messages": [AIMessage(content="The weather in Paris is sunny, 21C.")]}

    _b = StateGraph(MessagesState)
    _b.add_node("agent", agent); _b.add_node("tools", tools); _b.add_node("final", final)
    _b.add_edge(START, "agent"); _b.add_edge("agent", "tools")
    _b.add_edge("tools", "final"); _b.add_edge("final", END)
    graph = _b.compile()
"""


def _agent_file(tmp_path):
    path = tmp_path / "react3_agent.py"
    path.write_text(textwrap.dedent(_AGENT), encoding="utf-8")
    return f"{path}:graph"


async def _turn(graph, session_id):
    adapter = SessionAdapter(graph=graph)
    session = adapter.submit_message(session_id, "weather?")
    await session.current_task
    frames = []
    while not session.event_queue.empty():
        frames.append(session.event_queue.get_nowait())
    return frames


def _assert_attribution(frames):
    starts = [f for f in frames if f.get("type") == "tool_start"]
    content = [f for f in frames if f.get("type") == "content" and f.get("content")]
    assert [f["name"] for f in starts] == ["get_weather"], frames
    assert starts[0]["node"] == "agent", frames  # the node that made the tool call
    assert content, frames
    assert {f["node"] for f in content} == {"final"}, frames  # the node that answered
    assert "".join(f["content"] for f in content) == "The weather in Paris is sunny, 21C."


async def test_173_node_attribution_on_the_web_apps_sqlite_checkpointer(tmp_path):
    """The issue's repro under the server's own durable saver, over several turns
    (the mislabel was timing-dependent on a real AsyncSqliteSaver)."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    ws = tmp_path / "ws"
    app = CoworkApp(agent_spec=_agent_file(tmp_path), workspace=ws)
    graph = app.agent
    assert getattr(graph, "_langstage_auto_checkpointer", False) is True
    config = AppConfig.resolve(overrides={"workspace_root": ws})
    server = create_fastapi_app(agent=graph, workspace=ws, config=config)

    async with server.router.lifespan_context(server):
        assert isinstance(graph.checkpointer, AsyncSqliteSaver)
        for i in range(5):
            _assert_attribution(await _turn(graph, f"s{i}"))


async def test_173_node_attribution_when_checkpoint_writes_land_late(tmp_path):
    """Deterministic form of the race: every checkpoint write lands 50 ms late, so the
    snapshot is built before the step's checkpoint exists. Before core 1.0.37 this
    labeled ``tool_start`` with the run's last node."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    class SlowSaver(AsyncSqliteSaver):
        async def aput(self, *args, **kwargs):
            await asyncio.sleep(0.05)
            return await super().aput(*args, **kwargs)

        async def aput_writes(self, *args, **kwargs):
            await asyncio.sleep(0.05)
            return await super().aput_writes(*args, **kwargs)

    app = CoworkApp(agent_spec=_agent_file(tmp_path), workspace=tmp_path / "ws")
    graph = app.agent
    async with SlowSaver.from_conn_string(str(tmp_path / "slow.db")) as saver:
        await saver.setup()
        graph.checkpointer = saver
        _assert_attribution(await _turn(graph, "slow"))
