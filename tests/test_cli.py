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
