"""Notebook tools keep one state per session, not one per process (gh #157).

The cell/variable tools all used a single module-global ``NotebookState``, so a
background task or scheduled run (a "background copy of your agent") read and
clobbered the interactive chat's cells and variables. State is now keyed by the
session's ``thread_id`` — the same id the SessionAdapter and the checkpointer use
(chat session id, ``task-<id>`` for board/scheduled runs).
"""
import pytest
from langchain_core.runnables import RunnableLambda

from langstage import tools


@pytest.fixture(autouse=True)
def _isolated_states(monkeypatch):
    monkeypatch.setattr(tools, "_session_notebook_states", type(tools._session_notebook_states)())
    monkeypatch.setattr(tools, "_notebook_state", tools.NotebookState())
    yield
    tools.clear_tool_session_context()


def test_issue_repro_task_cannot_see_or_reset_the_chat_notebook():
    tools.set_tool_session_context("chat")
    tools.create_cell("import math; radius = 10")
    tools.execute_cell(0)
    assert tools.get_script()["cell_count"] == 1

    tools.set_tool_session_context("task-42")
    assert "radius" not in tools.get_variables()
    assert tools.get_script()["cell_count"] == 0
    tools.reset_notebook()

    tools.set_tool_session_context("chat")
    assert tools.get_script()["cell_count"] == 1
    assert "radius" in tools.get_variables()


def test_every_cell_tool_is_session_scoped():
    tools.set_tool_session_context("a")
    tools.create_cell("x = 1")
    tools.insert_cell(0, "y = 2")
    tools.modify_cell(1, "x = 3")
    tools.execute_all_cells()
    tools.create_cell("z = 4")
    tools.delete_cell(2)

    tools.set_tool_session_context("b")
    tools.create_cell("only_b = True")
    assert tools.execute_cell(0)["status"] == "success"
    assert set(tools.get_variables()) == {"only_b"} | _baseline_vars()

    tools.set_tool_session_context("a")
    script = tools.get_script()
    assert script["cell_count"] == 2
    assert script["script"] == "y = 2\n\nx = 3"
    assert {"x", "y"} <= set(tools.get_variables())
    assert "only_b" not in tools.get_variables()


def _baseline_vars():
    return set(tools.NotebookState().get_variables())


def test_session_comes_from_the_running_agent_thread_id():
    """Inside an agent run no one calls set_tool_session_context: the tools read
    the LangGraph run's ``configurable.thread_id`` instead."""
    def turn(code):
        tools.create_cell(code)
        tools.execute_cell(len(tools.get_script()["cells"]) - 1)
        return tools.get_variables()

    run = RunnableLambda(turn)
    run.invoke("chat_var = 1", config={"configurable": {"thread_id": "chat-session"}})
    seen = run.invoke("task_var = 2", config={"configurable": {"thread_id": "task-abc"}})
    assert "task_var" in seen and "chat_var" not in seen
    again = run.invoke("more = 3", config={"configurable": {"thread_id": "chat-session"}})
    assert {"chat_var", "more"} <= set(again) and "task_var" not in again


def test_no_session_falls_back_to_the_shared_default_state():
    # Direct (non-agent) callers with no session keep the old single notebook.
    tools.create_cell("v = 1")
    assert tools.get_notebook_state() is tools._notebook_state
    assert tools._notebook_state.cells[0]["source"] == "v = 1"


def test_release_and_bounded_retention():
    tools.set_tool_session_context("gone")
    tools.create_cell("a = 1")
    tools.release_notebook_state("gone")
    assert tools.get_script()["cell_count"] == 0

    # Idle states are evicted least-recently-used beyond the cap, so a long-running
    # server with many background runs doesn't hold every namespace forever.
    for i in range(tools._MAX_SESSION_NOTEBOOKS + 5):
        tools.get_notebook_state(f"s{i}")
    assert len(tools._session_notebook_states) == tools._MAX_SESSION_NOTEBOOKS
    assert "s0" not in tools._session_notebook_states


def test_scoping_holds_through_the_tool_wrapper_the_agent_uses():
    """The agent calls these as LangChain tools (StructuredTool.from_function, as
    deepagents wraps plain functions); the thread_id must reach them there too."""
    from langchain_core.tools import StructuredTool

    create = StructuredTool.from_function(tools.create_cell)
    script = StructuredTool.from_function(tools.get_script)
    create.invoke({"code": "a = 1"}, config={"configurable": {"thread_id": "chat"}})
    create.invoke({"code": "b = 2"}, config={"configurable": {"thread_id": "task-1"}})
    chat = script.invoke({}, config={"configurable": {"thread_id": "chat"}})
    assert [c["source"] for c in chat["cells"]] == ["a = 1"]
