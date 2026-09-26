"""Integration tests for default_agent composition.

Guards against silent degradation when `deepagents.create_deep_agent(...)` or
related library APIs drift. If the agent factory breaks or stops attaching
middleware, these tests fail loudly instead of the UI quietly losing features.

Skipped when the `deepagents` optional extra isn't installed.
"""

import tempfile
import warnings
from pathlib import Path

import pytest

pytest.importorskip("deepagents")


def test_default_agent_imports_and_exposes_middleware():
    """The global default agent must be importable and carry its middleware list.

    We rely on the `.middleware` attribute for runtime canvas-tab auto-detection
    ([app.py](langstage/app.py) -> `agent_uses_canvas_middleware`). If that
    attribute is lost, the UI silently defaults the Canvas tab off.
    """
    from langstage.default_agent import AGENT_MIDDLEWARE, create_default_agent
    from langstage.middleware import CanvasMiddleware, agent_uses_canvas_middleware

    agent = create_default_agent(Path(tempfile.mkdtemp()))

    # Graph is ready
    assert hasattr(agent, "astream"), "Default agent must expose astream()"
    assert hasattr(agent, "ainvoke"), "Default agent must expose ainvoke()"

    # Middleware pinned for detection (see default_agent.py post-compile assignment)
    assert hasattr(agent, "middleware"), (
        "Default agent must have .middleware attribute pinned for UI auto-detection"
    )
    assert any(isinstance(m, CanvasMiddleware) for m in AGENT_MIDDLEWARE)
    assert agent_uses_canvas_middleware(agent), (
        "agent_uses_canvas_middleware must detect CanvasMiddleware on the default agent"
    )


def test_default_agent_adds_todo_middleware_only_when_missing(monkeypatch):
    from langstage import default_agent

    class FakeTodoMiddleware:
        def __init__(self):
            self.tools = [type("Tool", (), {"name": "write_todos"})()]

    class FakeToolNode:
        def __init__(self):
            self.tools_by_name = {"write_todos": object()}

    class FakeAgent:
        def __init__(self, has_todos=False):
            self.nodes = {"tools": FakeToolNode()} if has_todos else {}

    built_middleware = []

    def fake_build_default_agent(**kwargs):
        built_middleware.append(kwargs["middleware"])
        return FakeAgent(has_todos=len(built_middleware) > 1)

    monkeypatch.setattr(default_agent, "_build_default_agent", fake_build_default_agent)
    monkeypatch.setattr(default_agent, "TodoListMiddleware", FakeTodoMiddleware)

    a = default_agent._make_default_agent("/tmp/langstage")

    assert len(built_middleware) == 2
    assert len(built_middleware[0]) + 1 == len(built_middleware[1])
    assert isinstance(a.middleware[-1], FakeTodoMiddleware)
    assert a._langstage_auto_checkpointer is True


def test_default_agent_does_not_duplicate_builtin_write_todos(monkeypatch):
    from langstage import default_agent

    class FakeToolNode:
        def __init__(self):
            self.tools_by_name = {"write_todos": object()}

    class FakeAgent:
        def __init__(self):
            self.nodes = {"tools": FakeToolNode()}

    built_middleware = []

    def fake_build_default_agent(**kwargs):
        built_middleware.append(kwargs["middleware"])
        return FakeAgent()

    monkeypatch.setattr(default_agent, "_build_default_agent", fake_build_default_agent)

    a = default_agent._make_default_agent("/tmp/langstage")

    assert built_middleware == [a.middleware]
    assert len(built_middleware) == 1


def test_default_agent_exposes_write_todos_for_plan(tmp_path):
    """The bundled default agent must keep the Plan tab's `write_todos` tool bound."""
    from langstage.cli import _agent_tool_names
    from langstage.default_agent import create_default_agent

    agent = create_default_agent(tmp_path)

    assert "write_todos" in (_agent_tool_names(agent) or set())


def test_agent_tools_exclude_canvas_tools():
    """Canvas tools should only be injected via CanvasMiddleware — never baked
    into the core tool list. Regression guard against accidental re-duplication.
    """
    from langstage.default_agent import AGENT_TOOLS

    tool_names = {getattr(t, "name", getattr(t, "__name__", "")) for t in AGENT_TOOLS}
    canvas_tool_names = {
        "add_to_canvas",
        "update_canvas_item",
        "remove_canvas_item",
        "add_canvas_section",
        "reorder_canvas",
    }
    overlap = tool_names & canvas_tool_names
    assert not overlap, (
        f"Canvas tools leaked into AGENT_TOOLS: {overlap}. "
        f"They must come only from CanvasMiddleware to avoid double-injection."
    )


def test_importing_the_module_builds_no_agent():
    """gh #169: the module used to build a throwaway agent at import time that
    nothing consumed, which doubled the startup cost and every build warning."""
    import langstage.default_agent as da

    assert not hasattr(da, "agent")


def test_default_agent_build_passes_an_explicit_model(monkeypatch, tmp_path):
    """gh #169: `model=None` is deprecated in deepagents and removed in 1.0. The
    build must name a model (core's DEFAULT_MODEL, which is what deepagents picked
    for None anyway) and so emit no model=None deprecation warning."""
    from langstage_core.demo.agent import DEFAULT_MODEL

    from langstage import default_agent as da

    seen = {}
    real = da._build_default_agent

    def spy(**kwargs):
        seen.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(da, "_build_default_agent", spy)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        da.create_default_agent(tmp_path)
    assert seen["model"] == DEFAULT_MODEL
    assert not [w for w in caught if "model=None" in str(w.message)]


def test_deepagents_is_capped_below_1_0():
    import tomllib

    root = Path(__file__).resolve().parents[1]
    extra = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    deps = extra["project"]["optional-dependencies"]["deepagents"]
    assert any(d.startswith("deepagents") and "<1.0" in d for d in deps), deps
