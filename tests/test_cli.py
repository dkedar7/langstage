"""CLI surface tests: --show-config, --demo, and flag wiring."""

from click.testing import CliRunner

from langstage import cli as cli_mod


class FakeApp:
    """Stands in for CoworkApp so CLI tests never start a server."""

    captured: dict = {}

    def __init__(self, **kwargs):
        FakeApp.captured = dict(kwargs)

    def run(self, open_browser=True):
        FakeApp.captured["open_browser"] = open_browser


def test_show_config_prints_resolved_config():
    result = CliRunner().invoke(cli_mod.main, ["--show-config"])
    assert result.exit_code == 0
    assert "DEEPAGENT_AGENT_SPEC" in result.output


def test_show_config_auth_username_default_is_admin():
    # gh #35: the effective default (and what the server enforces) is "admin";
    # --show-config must not show it as blank.
    from langstage.config import AppConfig

    assert AppConfig().auth_username == "admin"
    result = CliRunner().invoke(cli_mod.main, ["--show-config"])
    assert result.exit_code == 0
    import re

    assert re.search(r"auth_username\s*=\s*admin", result.output), result.output


def test_bare_invocation_prints_help():
    result = CliRunner().invoke(cli_mod.main, [])
    assert result.exit_code == 0
    assert "run" in result.output


def test_demo_routes_to_the_stub_spec(monkeypatch):
    monkeypatch.setattr(cli_mod, "CoworkApp", FakeApp)
    result = CliRunner().invoke(cli_mod.main, ["run", "--demo", "--no-browser"])
    assert result.exit_code == 0, result.output
    assert FakeApp.captured["agent_spec"] == cli_mod.DEMO_AGENT_SPEC
    assert FakeApp.captured["open_browser"] is False


def test_demo_and_agent_are_mutually_exclusive():
    result = CliRunner().invoke(cli_mod.main, ["run", "--demo", "--agent", "x.py:g"])
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output


def test_agent_short_flag(monkeypatch):
    monkeypatch.setattr(cli_mod, "CoworkApp", FakeApp)
    result = CliRunner().invoke(cli_mod.main, ["run", "-a", "my.py:g", "--no-browser"])
    assert result.exit_code == 0, result.output
    assert FakeApp.captured["agent_spec"] == "my.py:g"


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body)
    return p


# ── run: clean CLI error on a bad --agent spec, not a raw traceback (gh #90) ──


def _assert_clean_run_error(result):
    """A bad `run --agent` must exit non-zero with click's clean `Error: …` line —
    NOT let the loader's raw exception escape as an unhandled traceback."""
    assert result.exit_code != 0, result.output
    # The raw loader exception must not leak out unhandled (that's the traceback bug).
    assert not isinstance(
        result.exception, (FileNotFoundError, AttributeError, ValueError, ImportError)
    ), f"raw {type(result.exception).__name__} escaped instead of a clean ClickException"
    # click formats a ClickException as a one-line "Error: <message>".
    assert "Error:" in result.output, result.output


def test_run_bad_agent_path_is_clean_error(tmp_path):
    """CASE 1 — `--agent` points at a file that doesn't exist (a path typo)."""
    missing = tmp_path / "bad.py"  # never created
    result = CliRunner().invoke(
        cli_mod.main, ["run", "--agent", f"{missing}:graph", "--no-browser"]
    )
    _assert_clean_run_error(result)


def test_run_missing_attr_is_clean_error(tmp_path):
    """CASE 2 — file exists but has no such attribute (AttributeError)."""
    agent = _write(tmp_path, "mod.py", "x = 1\n")
    result = CliRunner().invoke(
        cli_mod.main, ["run", "--agent", f"{agent}:graph", "--no-browser"]
    )
    _assert_clean_run_error(result)


def test_run_malformed_spec_is_clean_error():
    """CASE 3 — malformed spec, missing the required ':attr' suffix (ValueError)."""
    result = CliRunner().invoke(
        cli_mod.main, ["run", "--agent", "mymodule", "--no-browser"]
    )
    _assert_clean_run_error(result)


# ── message-less load exceptions surface the class name, not a blank error (gh #92) ──
#
# A load failure whose `str(exc)` is empty — e.g. `NotImplementedError()`, which any
# model that doesn't support tool-calling raises from `bind_tools()` inside
# `create_react_agent(...)` — used to print a bare `Error: ` / `[fail] failed to load: `
# with nothing after the colon (a follow-on gap from the #90 broadening). Both surfaces
# must now fall back to the exception class name.

_EMPTY_MSG_AGENT = "raise NotImplementedError\n"  # str(NotImplementedError()) == ""


def test_run_message_less_load_error_falls_back_to_class_name(tmp_path):
    """`run`: a message-less load exception surfaces its class name, not `Error: ` (empty)."""
    agent = _write(tmp_path, "emptyerr.py", _EMPTY_MSG_AGENT)
    result = CliRunner().invoke(
        cli_mod.main, ["run", "--agent", f"{agent}:graph", "--no-browser"]
    )
    assert result.exit_code != 0, result.output
    # Fail-before/pass-after: pre-fix the whole message was empty (`Error: \n`).
    assert "Error: NotImplementedError" in result.output, result.output


def test_check_message_less_load_error_falls_back_to_class_name(tmp_path):
    """`check` human line: names the class instead of ending at `failed to load: `."""
    agent = _write(tmp_path, "emptyerr.py", _EMPTY_MSG_AGENT)
    result = CliRunner().invoke(cli_mod.main, ["check", "--agent", f"{agent}:graph"])
    assert result.exit_code == 1, result.output
    assert "failed to load: NotImplementedError" in result.output, result.output


def test_check_json_message_less_load_error_trims_trailing_colon(tmp_path):
    """`check --json`: the error is the bare class name, not `NotImplementedError: `
    with a dangling colon-space (the pre-fix `f"{type(e).__name__}: {e}"` on empty e)."""
    import json

    agent = _write(tmp_path, "emptyerr.py", _EMPTY_MSG_AGENT)
    result = CliRunner().invoke(
        cli_mod.main, ["check", "--agent", f"{agent}:graph", "--json"]
    )
    assert result.exit_code == 1, result.output
    report = json.loads(result.output)
    assert report["loads"] is False
    assert report["error"] == "NotImplementedError", report["error"]


def test_check_fails_on_uncompiled_stategraph(tmp_path):
    """Preflight must catch the #1 BYO mistake — exporting the builder, not the
    compiled graph — instead of a confident `[ ok ] loads` + exit 0. (gh #39)"""
    agent = _write(tmp_path, "uncompiled.py",
                   "from langgraph.graph import StateGraph, MessagesState\n"
                   "b = StateGraph(MessagesState)\n"
                   "b.add_node('respond', lambda s: {'messages': []})\n"
                   "b.set_entry_point('respond')\n"
                   "graph = b  # forgot .compile()\n")
    result = CliRunner().invoke(cli_mod.main, ["check", "--agent", f"{agent}:graph"])
    assert result.exit_code == 1, result.output
    assert "not runnable" in result.output
    assert "uncompiled" in result.output
    assert "[ ok ] loads" not in result.output


def test_check_fails_on_non_graph_object(tmp_path):
    """A dict / int / str is not a runnable graph; preflight must fail, not pass."""
    for body in ("graph = 42\n", "graph = {'x': 1}\n", "graph = 'my_agent'\n"):
        agent = _write(tmp_path, "obj.py", body)
        result = CliRunner().invoke(cli_mod.main, ["check", "--agent", f"{agent}:graph"])
        assert result.exit_code == 1, result.output
        assert "not runnable" in result.output
        assert "[ ok ] loads" not in result.output


def test_check_passes_for_demo_agent():
    """A real compiled graph still preflights green."""
    result = CliRunner().invoke(cli_mod.main, ["check", "--demo"])
    assert result.exit_code == 0, result.output
    assert "[ ok ] loads" in result.output


def test_check_static_default_runs_no_live_turn():
    """Default `check` stays static/fast/keyless — no live turn (backward-compat)."""
    result = CliRunner().invoke(cli_mod.main, ["check", "--demo"])
    assert result.exit_code == 0, result.output
    assert "live turn" not in result.output


def test_check_live_passes_for_demo_agent():
    """`--live` runs one real turn through core.verify; the keyless stub completes
    it, so the check is green and reports the live verdict. (ADR 0004)"""
    result = CliRunner().invoke(cli_mod.main, ["check", "--demo", "--live"])
    assert result.exit_code == 0, result.output
    assert "[ ok ] live turn" in result.output


def test_check_live_fails_on_runnable_but_broken_agent(tmp_path):
    """The gap #39 left open: a runnable graph that errors at turn time passes the
    static checks but must FAIL `--live` (exit 1) — the readiness a first chat proves."""
    agent = _write(tmp_path, "broken.py",
                   "from langgraph.graph import StateGraph, START, END, MessagesState\n"
                   "def boom(s):\n"
                   "    raise RuntimeError('tool exploded')\n"
                   "b = StateGraph(MessagesState)\n"
                   "b.add_node('boom', boom)\n"
                   "b.add_edge(START, 'boom')\n"
                   "b.add_edge('boom', END)\n"
                   "graph = b.compile()\n")
    result = CliRunner().invoke(cli_mod.main, ["check", "--agent", f"{agent}:graph", "--live"])
    assert result.exit_code == 1, result.output
    assert "[ ok ] loads" in result.output  # static gates passed...
    assert "live turn failed" in result.output  # ...but the real turn caught it


# ── check --json / config --json (gh #73: machine-readable CI gate) ──────────


def test_check_json_emits_structured_report_for_demo():
    """gh #73: `check --json` emits a stable object CI can gate on — not human lines."""
    import json

    result = CliRunner().invoke(cli_mod.main, ["check", "--demo", "--json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)  # the WHOLE output is JSON (no human lines mixed in)
    assert report["spec"] == "langstage_core.demo.stub:graph"
    assert report["loads"] is True
    assert report["ok"] is True
    # every advertised check key is present with an ok/detail shape
    for key in ("checkpointer", "canvas", "write_todos", "async_tasks", "schedules"):
        assert set(report["checks"][key]) == {"ok", "detail"}
    assert report["live"] == {"ran": False}
    # no ANSI/human markers leaked into the JSON stream
    assert "[ ok ]" not in result.output and "[warn]" not in result.output


def test_check_json_load_failure_still_json_and_exit_1():
    """A load failure preserves exit 1 AND still emits JSON (loads:false, ok:false, error)."""
    import json

    result = CliRunner().invoke(cli_mod.main, ["check", "--agent", "nope.py:missing", "--json"])
    assert result.exit_code == 1, result.output
    report = json.loads(result.output)
    assert report["loads"] is False
    assert report["ok"] is False
    assert "error" in report


def test_check_json_gate_example_from_the_readme(tmp_path):
    """The advertised gate `.loads and .checks.canvas.ok` is False for a canvas-less agent."""
    import json

    result = CliRunner().invoke(cli_mod.main, ["check", "--demo", "--json"])
    report = json.loads(result.output)
    assert (report["loads"] and report["checks"]["canvas"]["ok"]) is False


def test_check_json_live_failure_records_error_and_exits_1(tmp_path):
    """`--live --json` on a runnable-but-broken agent → exit 1 with live.ok false + error."""
    import json

    agent = _write(tmp_path, "broken.py",
                   "from langgraph.graph import StateGraph, START, END, MessagesState\n"
                   "def boom(s):\n"
                   "    raise RuntimeError('tool exploded')\n"
                   "b = StateGraph(MessagesState)\n"
                   "b.add_node('boom', boom)\n"
                   "b.add_edge(START, 'boom')\n"
                   "b.add_edge('boom', END)\n"
                   "graph = b.compile()\n")
    result = CliRunner().invoke(cli_mod.main, ["check", "--agent", f"{agent}:graph", "--live", "--json"])
    assert result.exit_code == 1, result.output
    report = json.loads(result.output)
    assert report["loads"] is True  # static gates passed
    assert report["live"]["ran"] is True and report["live"]["ok"] is False
    assert "error" in report["live"]


def test_config_json_emits_value_and_source_per_field():
    """gh #73: `config --json` lets automation read the resolved config structurally."""
    import json

    result = CliRunner().invoke(cli_mod.main, ["config", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "config" in payload and "toml_read_from" in payload
    # a representative field carries both its value and its source
    assert set(payload["config"]["port"]) == {"value", "source"}
    assert payload["config"]["port"]["value"] == 8050
