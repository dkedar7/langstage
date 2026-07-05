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
