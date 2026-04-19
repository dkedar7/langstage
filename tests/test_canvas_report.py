"""Tests for Stage 1 canvas-as-report features: sections, reordering, middleware."""

from pathlib import Path

import pytest

from cowork_dash import tools as tools_mod
from cowork_dash.canvas import (
    export_canvas_to_markdown,
    load_canvas_from_markdown,
    parse_canvas_object,
)
from cowork_dash.middleware.canvas import CANVAS_PROMPT, CanvasMiddleware


@pytest.fixture
def tmp_workspace(tmp_path: Path, monkeypatch) -> Path:
    """Provide a temporary workspace and point tools.WORKSPACE_ROOT at it."""
    from cowork_dash import config as cfg

    monkeypatch.setattr(cfg, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(cfg, "VIRTUAL_FS", False)
    # tools.py captured WORKSPACE_ROOT at import; patch the local reference too.
    monkeypatch.setattr(tools_mod, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(tools_mod, "VIRTUAL_FS", False)
    return tmp_path


# --- Section item parsing/export -------------------------------------------------


def test_section_parsed_from_marker_dict(tmp_workspace: Path):
    """parse_canvas_object recognizes the section marker dict."""
    result = parse_canvas_object(
        {"__canvas_kind__": "section", "text": "Overview", "level": 2},
        workspace_root=tmp_workspace,
        item_id="sec_overview",
    )
    assert result["type"] == "section"
    assert result["data"] == "Overview"
    assert result["level"] == 2
    assert result["id"] == "sec_overview"


def test_section_roundtrip_through_markdown(tmp_workspace: Path):
    """Section exports to '# Title' and loads back with preserved level."""
    item = parse_canvas_object(
        {"__canvas_kind__": "section", "text": "Findings", "level": 2},
        workspace_root=tmp_workspace,
        item_id="findings",
    )
    export_canvas_to_markdown([item], tmp_workspace)
    loaded = load_canvas_from_markdown(tmp_workspace)
    assert len(loaded) == 1
    assert loaded[0]["type"] == "section"
    assert loaded[0]["data"] == "Findings"
    assert loaded[0]["level"] == 2
    assert loaded[0]["id"] == "findings"


def test_section_level_clamped_on_export(tmp_workspace: Path):
    """Level outside 1..6 clamps when exported as markdown hashes."""
    item = parse_canvas_object(
        {"__canvas_kind__": "section", "text": "Deep", "level": 9},
        workspace_root=tmp_workspace,
        item_id="deep",
    )
    # The parsed item keeps the requested level, but export clamps to <= 6.
    export_canvas_to_markdown([item], tmp_workspace)
    md = (tmp_workspace / ".canvas" / "canvas.md").read_text()
    assert "###### Deep" in md
    assert "####### Deep" not in md


# --- add_canvas_section + reorder_canvas tools ----------------------------------


def test_add_canvas_section_tool(tmp_workspace: Path):
    msg = tools_mod.add_canvas_section("Overview", level=1, item_id="overview")
    assert "Added" in msg
    items = load_canvas_from_markdown(tmp_workspace)
    assert len(items) == 1
    assert items[0]["type"] == "section"
    assert items[0]["id"] == "overview"
    assert items[0]["level"] == 1


def test_add_canvas_section_clamps_invalid_level(tmp_workspace: Path):
    tools_mod.add_canvas_section("Too Deep", level=42, item_id="td")
    items = load_canvas_from_markdown(tmp_workspace)
    assert items[0]["level"] == 6


def test_reorder_canvas_rewrites_file_in_new_order(tmp_workspace: Path):
    tools_mod.add_to_canvas("first", title=None, item_id="a")
    tools_mod.add_to_canvas("second", title=None, item_id="b")
    tools_mod.add_to_canvas("third", title=None, item_id="c")

    before = load_canvas_from_markdown(tmp_workspace)
    assert [i["id"] for i in before] == ["a", "b", "c"]

    result = tools_mod.reorder_canvas(["c", "a", "b"])
    assert "Reordered" in result

    after = load_canvas_from_markdown(tmp_workspace)
    assert [i["id"] for i in after] == ["c", "a", "b"]


def test_reorder_canvas_drops_ids_not_in_list(tmp_workspace: Path):
    tools_mod.add_to_canvas("keep", title=None, item_id="keep")
    tools_mod.add_to_canvas("drop", title=None, item_id="drop")

    tools_mod.reorder_canvas(["keep"])
    after = load_canvas_from_markdown(tmp_workspace)
    assert [i["id"] for i in after] == ["keep"]


def test_reorder_canvas_ignores_unknown_ids(tmp_workspace: Path):
    tools_mod.add_to_canvas("only", title=None, item_id="only")
    msg = tools_mod.reorder_canvas(["only", "does_not_exist"])
    assert "1 item" in msg
    after = load_canvas_from_markdown(tmp_workspace)
    assert [i["id"] for i in after] == ["only"]


def test_reorder_canvas_empty_result_is_noop(tmp_workspace: Path):
    tools_mod.add_to_canvas("kept", title=None, item_id="kept")
    msg = tools_mod.reorder_canvas(["nothing_matches"])
    assert "No matching" in msg
    after = load_canvas_from_markdown(tmp_workspace)
    assert [i["id"] for i in after] == ["kept"]


def test_mixed_sections_and_items_roundtrip(tmp_workspace: Path):
    """Report-shaped canvas: section → markdown → section → markdown."""
    tools_mod.add_canvas_section("Overview", level=1, item_id="s1")
    tools_mod.add_to_canvas("Intro text", item_id="m1")
    tools_mod.add_canvas_section("Findings", level=2, item_id="s2")
    tools_mod.add_to_canvas("Conclusion text", item_id="m2")

    items = load_canvas_from_markdown(tmp_workspace)
    types = [i["type"] for i in items]
    ids = [i["id"] for i in items]
    assert types == ["section", "markdown", "section", "markdown"]
    assert ids == ["s1", "m1", "s2", "m2"]


# --- Provenance (Stage 2) --------------------------------------------------------


@pytest.fixture
def fresh_notebook(monkeypatch):
    """Give each test a clean NotebookState so last_executed_cell is deterministic."""
    from cowork_dash.tools import NotebookState

    fresh = NotebookState()
    monkeypatch.setattr(tools_mod, "_notebook_state", fresh)
    return fresh


def test_provenance_auto_captured_after_execute_cell(tmp_workspace: Path, fresh_notebook):
    """add_to_canvas after execute_cell records source_cell + execution_count."""
    tools_mod.create_cell("x = 42")
    tools_mod.execute_cell(0)

    tools_mod.add_to_canvas("A finding", item_id="finding")
    items = load_canvas_from_markdown(tmp_workspace)
    item = next(i for i in items if i["id"] == "finding")
    assert item["source_cell"] == 0
    assert item["execution_count"] == 1


def test_provenance_survives_canvas_roundtrip(tmp_workspace: Path, fresh_notebook):
    """source_cell + execution_count persist through canvas.md reload."""
    tools_mod.create_cell("y = 1")
    tools_mod.execute_cell(0)
    tools_mod.add_to_canvas("text", item_id="m1")

    reloaded = load_canvas_from_markdown(tmp_workspace)
    item = next(i for i in reloaded if i["id"] == "m1")
    assert item.get("source_cell") == 0
    assert item.get("execution_count") == 1


def test_provenance_explicit_override(tmp_workspace: Path, fresh_notebook):
    """Explicit source_cell= overrides the last-executed-cell fallback."""
    tools_mod.create_cell("z = 1")
    tools_mod.execute_cell(0)

    tools_mod.add_to_canvas("text", item_id="override", source_cell=5)
    items = load_canvas_from_markdown(tmp_workspace)
    item = next(i for i in items if i["id"] == "override")
    assert item["source_cell"] == 5


def test_provenance_absent_before_any_cell_runs(tmp_workspace: Path, fresh_notebook):
    """With no executed cells, no source_cell is attached."""
    tools_mod.add_to_canvas("freeform", item_id="f1")
    items = load_canvas_from_markdown(tmp_workspace)
    item = next(i for i in items if i["id"] == "f1")
    assert "source_cell" not in item
    assert "execution_count" not in item


def test_provenance_updates_to_latest_cell(tmp_workspace: Path, fresh_notebook):
    """Re-running a different cell updates the fallback provenance."""
    tools_mod.create_cell("a = 1")
    tools_mod.create_cell("b = 2")
    tools_mod.execute_cell(0)
    tools_mod.add_to_canvas("first", item_id="first")

    tools_mod.execute_cell(1)
    tools_mod.add_to_canvas("second", item_id="second")

    items = {i["id"]: i for i in load_canvas_from_markdown(tmp_workspace)}
    assert items["first"]["source_cell"] == 0
    assert items["second"]["source_cell"] == 1
    assert items["second"]["execution_count"] == 2


def test_update_canvas_item_refreshes_provenance(tmp_workspace: Path, fresh_notebook):
    """When update_canvas_item is called after a different cell runs, provenance updates."""
    tools_mod.create_cell("a = 1")
    tools_mod.create_cell("b = 2")
    tools_mod.execute_cell(0)
    tools_mod.add_to_canvas("v1", item_id="chart")

    tools_mod.execute_cell(1)
    tools_mod.update_canvas_item("chart", "v2")

    items = load_canvas_from_markdown(tmp_workspace)
    item = next(i for i in items if i["id"] == "chart")
    assert item["source_cell"] == 1
    assert item["execution_count"] == 2


# --- CanvasMiddleware ------------------------------------------------------------


class _FakeRequest:
    """Minimal ModelRequest stand-in for unit-testing wrap_model_call."""

    def __init__(self, system_prompt: str = "", tools=None):
        self.system_prompt = system_prompt
        self.tools = list(tools or [])


def test_middleware_appends_prompt_and_injects_tools():
    mw = CanvasMiddleware()
    req = _FakeRequest(system_prompt="Base prompt")
    captured = {}

    def handler(r):
        captured["prompt"] = r.system_prompt
        captured["tools"] = list(r.tools)
        return "ok"

    assert mw.wrap_model_call(req, handler) == "ok"
    assert "Base prompt" in captured["prompt"]
    assert CANVAS_PROMPT in captured["prompt"]

    tool_names = {getattr(t, "name", getattr(t, "__name__", "")) for t in captured["tools"]}
    assert {
        "add_to_canvas",
        "update_canvas_item",
        "remove_canvas_item",
        "add_canvas_section",
        "reorder_canvas",
    }.issubset(tool_names)


def test_middleware_is_idempotent():
    """Calling the middleware twice doesn't duplicate prompt or tools."""
    mw = CanvasMiddleware()
    req = _FakeRequest()

    def handler(_):
        return None

    mw.wrap_model_call(req, handler)
    first_prompt = req.system_prompt
    first_tool_count = len(req.tools)

    mw.wrap_model_call(req, handler)
    assert req.system_prompt == first_prompt
    assert len(req.tools) == first_tool_count


def test_middleware_disabled_is_passthrough():
    mw = CanvasMiddleware(enabled=False)
    req = _FakeRequest(system_prompt="original")

    def handler(r):
        return ("p", r.system_prompt, list(r.tools))

    _, prompt, tools = mw.wrap_model_call(req, handler)
    assert prompt == "original"
    assert tools == []


def test_middleware_handles_empty_initial_prompt():
    mw = CanvasMiddleware()
    req = _FakeRequest(system_prompt="")

    def handler(_):
        return None

    mw.wrap_model_call(req, handler)
    assert req.system_prompt == CANVAS_PROMPT


async def test_middleware_async_variant_injects_prompt_and_tools():
    """awrap_model_call mirrors wrap_model_call for async agents (astream/ainvoke)."""
    mw = CanvasMiddleware()
    req = _FakeRequest(system_prompt="Base")
    captured = {}

    async def handler(r):
        captured["prompt"] = r.system_prompt
        captured["tools"] = list(r.tools)
        return "ok"

    result = await mw.awrap_model_call(req, handler)
    assert result == "ok"
    assert CANVAS_PROMPT in captured["prompt"]
    tool_names = {getattr(t, "name", getattr(t, "__name__", "")) for t in captured["tools"]}
    assert "add_to_canvas" in tool_names


async def test_middleware_async_disabled_is_passthrough():
    mw = CanvasMiddleware(enabled=False)
    req = _FakeRequest(system_prompt="orig")

    async def handler(r):
        return r.system_prompt

    result = await mw.awrap_model_call(req, handler)
    assert result == "orig"
