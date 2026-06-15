"""Bring-your-own-agent integration: checkpointer auto-attach, the tool
bundle, and the `langstage check` doctor."""
from typing import TypedDict

from click.testing import CliRunner
from langgraph.graph import END, START, StateGraph

from langstage import LANGSTAGE_TOOLS
from langstage.app import CoworkApp
from langstage.cli import main


class _S(TypedDict):
    x: int


def _bare_graph(checkpointer=None):
    def node(state):
        return {"x": state.get("x", 0) + 1}

    g = StateGraph(_S)
    g.add_node("n", node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    return g.compile(checkpointer=checkpointer)


def test_checkpointer_auto_attached(tmp_path):
    graph = _bare_graph()
    assert graph.checkpointer is None  # BYO graph with no checkpointer
    app = CoworkApp(agent=graph, workspace=str(tmp_path))
    assert app.agent.checkpointer is not None  # LangStage attached one
    # marked as ours so the server can upgrade it to a durable SQLite saver
    assert getattr(app.agent, "_langstage_auto_checkpointer", False) is True


def test_user_checkpointer_is_preserved_and_unmarked(tmp_path):
    from langgraph.checkpoint.memory import InMemorySaver

    saver = InMemorySaver()
    graph = _bare_graph(checkpointer=saver)
    app = CoworkApp(agent=graph, workspace=str(tmp_path))
    assert app.agent.checkpointer is saver  # not replaced
    # not marked → the server will never swap it out
    assert getattr(app.agent, "_langstage_auto_checkpointer", False) is False


async def test_durable_checkpoint_persists_across_restart(tmp_path):
    """The whole point of the SQLite saver: a thread's state survives a 'restart'
    (a brand-new saver on the same db file can read the checkpoint)."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    db = str(tmp_path / "ckpt.db")
    cfg = {"configurable": {"thread_id": "t1"}}

    def inc(state):
        return {"x": state["x"] + 1}

    builder = StateGraph(_S)
    builder.add_node("inc", inc)
    builder.add_edge(START, "inc")
    builder.add_edge("inc", END)

    async with AsyncSqliteSaver.from_conn_string(db) as s1:
        await s1.setup()
        g1 = builder.compile(checkpointer=s1)
        out = await g1.ainvoke({"x": 0}, cfg)
        assert out["x"] == 1

    async with AsyncSqliteSaver.from_conn_string(db) as s2:  # "restart"
        g2 = builder.compile(checkpointer=s2)
        snap = await g2.aget_state(cfg)
        assert snap is not None and snap.values.get("x") == 1  # persisted


async def test_server_startup_upgrades_to_sqlite(tmp_path):
    """create_fastapi_app's startup swaps an auto-attached in-memory saver for a
    durable SQLite one (and shutdown closes it)."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from langstage.config import AppConfig
    from langstage.server.main import create_fastapi_app

    graph = _bare_graph()
    graph._langstage_auto_checkpointer = True  # as CoworkApp would mark it
    config = AppConfig.resolve(overrides={"workspace_root": tmp_path})
    app = create_fastapi_app(agent=graph, workspace=tmp_path, config=config)

    # Run the registered startup/shutdown handlers directly (portable across
    # Starlette versions — `router.startup()` isn't available everywhere).
    for handler in app.router.on_startup:
        await handler()
    try:
        assert isinstance(graph.checkpointer, AsyncSqliteSaver)
        assert (tmp_path / ".langstage" / "checkpoints.db").exists()
    finally:
        for handler in app.router.on_shutdown:
            await handler()


def test_langstage_tools_bundle():
    names = {getattr(t, "name", "") for t in LANGSTAGE_TOOLS}
    assert "schedule_run" in names                       # cron
    assert any(n.endswith("async_task") for n in names)  # delegation
    assert "start_async_task" in names


def test_check_doctor_runs_on_demo():
    result = CliRunner().invoke(main, ["check", "--demo"])
    assert result.exit_code == 0
    assert "loads" in result.output
    # demo agent ships no canvas / delegation tools → doctor should flag them
    assert "Canvas" in result.output


def test_check_doctor_requires_a_spec():
    result = CliRunner().invoke(main, ["check"])
    assert result.exit_code != 0  # UsageError without --agent/--demo
