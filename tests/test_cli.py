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
