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


def test_user_checkpointer_is_preserved(tmp_path):
    from langgraph.checkpoint.memory import InMemorySaver

    saver = InMemorySaver()
    graph = _bare_graph(checkpointer=saver)
    app = CoworkApp(agent=graph, workspace=str(tmp_path))
    assert app.agent.checkpointer is saver  # not replaced


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
