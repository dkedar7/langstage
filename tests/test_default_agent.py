"""Integration tests for default_agent composition.

Guards against silent degradation when `deepagents.create_deep_agent(...)` or
related library APIs drift. If the agent factory breaks or stops attaching
middleware, these tests fail loudly instead of the UI quietly losing features.

Skipped when the `deepagents` optional extra isn't installed.
"""

import pytest

pytest.importorskip("deepagents")


def test_default_agent_imports_and_exposes_middleware():
    """The global default agent must be importable and carry its middleware list.

    We rely on the `.middleware` attribute for runtime canvas-tab auto-detection
    ([app.py](langstage/app.py) -> `agent_uses_canvas_middleware`). If that
    attribute is lost, the UI silently defaults the Canvas tab off.
    """
    from langstage.default_agent import agent, AGENT_MIDDLEWARE
    from langstage.middleware import CanvasMiddleware, agent_uses_canvas_middleware

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
