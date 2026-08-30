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


def test_default_agent_adds_todo_middleware_when_deepagents_stops_defaulting_it():
    from langstage.default_agent import _deepagents_has_builtin_todo_middleware

    assert _deepagents_has_builtin_todo_middleware("0.3.3") is True
    assert _deepagents_has_builtin_todo_middleware("0.7.11") is False


def test_default_agent_exposes_write_todos_for_plan():
    """The bundled default agent must keep the Plan tab's `write_todos` tool bound."""
    from langstage.cli import _agent_tool_names
    from langstage.default_agent import agent

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
    import langstage.default_agent as da
    from langstage_core.demo.agent import DEFAULT_MODEL

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
