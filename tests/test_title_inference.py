"""The app title/agent-name inferred from the agent's .name (dogfood F3).

A bare CompiledStateGraph's default .name is "LangGraph" — a confusing app title for
a BYO agent — so it must NOT become the title; a real name still does.
"""

from langgraph.graph import END, START, MessagesState, StateGraph

from langstage import CoworkApp


def _graph(name=None):
    b = StateGraph(MessagesState)
    b.add_node("n", lambda s: {"messages": []})
    b.add_edge(START, "n")
    b.add_edge("n", END)
    g = b.compile()
    if name:
        g.name = name
    return g


def test_generic_graph_name_is_not_used_as_title(tmp_path):
    g = _graph()
    assert g.name == "LangGraph"  # the default a bare compile gives
    app = CoworkApp(agent=g, workspace=str(tmp_path))
    assert app.config.title == "LangStage"  # kept the default, not "LangGraph"
    assert app.config.agent_name == "Agent"


def test_real_graph_name_becomes_title(tmp_path):
    app = CoworkApp(agent=_graph("Research Assistant"), workspace=str(tmp_path))
    assert app.config.title == "Research Assistant"
    assert app.config.agent_name == "Research Assistant"


def test_check_reports_no_name_for_a_generic_graph_name(tmp_path):
    """`check` must not advertise "LangGraph" as the agent name: `run` discards
    that placeholder and shows the defaults (gh #153)."""
    import json

    from click.testing import CliRunner

    from langstage import cli as cli_mod

    agent = tmp_path / "my_agent.py"
    agent.write_text(
        "from langgraph.graph import END, START, MessagesState, StateGraph\n"
        "b = StateGraph(MessagesState)\n"
        "b.add_node('n', lambda s: {'messages': []})\n"
        "b.add_edge(START, 'n'); b.add_edge('n', END)\n"
        "graph = b.compile()\n"
    )
    human = CliRunner().invoke(cli_mod.main, ["check", "--agent", f"{agent}:graph"])
    assert "agent name: LangGraph" not in human.output
    as_json = CliRunner().invoke(
        cli_mod.main, ["check", "--agent", f"{agent}:graph", "--json"]
    )
    assert json.loads(as_json.output)["agent_name"] is None


def test_workspace_name_is_the_resolved_folder_for_a_relative_workspace(
    tmp_path, monkeypatch
):
    """The default workspace "." used to report workspace_name "" (gh #145)."""
    proj = tmp_path / "my-cool-project"
    proj.mkdir()
    monkeypatch.chdir(proj)
    monkeypatch.setattr("langstage_core.host.workspace._ACTIVE", None)
    app = CoworkApp(agent=_graph(), workspace=".")
    assert app.config.to_client_dict()["workspace_name"] == "my-cool-project"
