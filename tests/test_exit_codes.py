"""The family exit-code scheme on the `langstage` CLI (langstage-core ADR 0007).

0 success / 1 failure / 2 paused on a HITL interrupt / 64 usage error. click exits 2 on
a usage error, which collides with "paused", so the CLI remaps usage errors to 64.
"""
import socket

import pytest
from click.testing import CliRunner

from langstage import cli as cli_mod

_STUB = "langstage_core.demo.stub:graph"
_TOOLS = "langstage_core.demo.tools:graph"


class _FakeApp:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def run(self, open_browser=True):
        return None


@pytest.fixture
def no_spec(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LANGSTAGE_AGENT_SPEC", raising=False)
    monkeypatch.delenv("DEEPAGENT_AGENT_SPEC", raising=False)
    monkeypatch.setenv("LANGSTAGE_CONFIG_HOME", str(tmp_path / "no-global"))


def _invoke(args):
    return CliRunner().invoke(cli_mod.main, args)


def test_constants():
    assert (cli_mod.EXIT_OK, cli_mod.EXIT_FAIL, cli_mod.EXIT_PAUSED, cli_mod.EXIT_USAGE) == (0, 1, 2, 64)


# ---- usage errors: 64 ----------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ["--bogus"],
        ["nosuchcommand"],
        ["run", "--theme", "purple", "--demo", "--no-browser"],
        ["run", "--port", "70000", "--demo", "--no-browser"],
        ["run", "--demo", "--agent", "x.py:g", "--no-browser"],
        ["chat", "--demo", "--agent", "x.py:g", "hi"],
        ["chat"],  # PROMPT is required
        ["check", "--bogus"],
        ["config", "--bogus"],
    ],
)
def test_usage_errors_exit_64(args):
    result = _invoke(args)
    assert result.exit_code == 64, result.output


# ---- not configured / load failure: 1 ------------------------------------------------


@pytest.mark.parametrize("args", [["check"], ["chat", "hi"]])
def test_no_spec_is_failure_1(args, no_spec):
    result = _invoke(args)
    assert result.exit_code == 1, result.output
    assert "LANGSTAGE_AGENT_SPEC" in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["check", "--agent", "/nope/x.py:graph"],
        ["chat", "--agent", "/nope/x.py:graph", "hi"],
        ["run", "--agent", "/nope/x.py:graph", "--no-browser"],
    ],
)
def test_load_failure_is_1(args):
    assert _invoke(args).exit_code == 1


def test_config_strict_failure_is_1(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LANGSTAGE_CONFIG_HOME", str(tmp_path / "no-global"))
    (tmp_path / "langstage.toml").write_text("[agent]\nnot_a_key = 1\n", encoding="utf-8")
    assert _invoke(["config", "--strict"]).exit_code == 1


# ---- success: 0 ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [["--show-config"], ["--version"], [], ["config"], ["check", "--demo"], ["chat", "--demo", "hi"]],
)
def test_success_is_0(args):
    result = _invoke(args)
    assert result.exit_code == 0, result.output


def test_run_ok_is_0(monkeypatch):
    monkeypatch.setattr(cli_mod, "CoworkApp", _FakeApp)
    monkeypatch.setattr(cli_mod, "_port_bind_error", lambda host, port: None)
    assert _invoke(["run", "--demo", "--no-browser"]).exit_code == 0


# ---- paused: 2 -----------------------------------------------------------------------


def test_chat_interrupt_is_paused_2(tmp_path):
    pytest.importorskip("ag_ui_langgraph")
    result = _invoke(["chat", "--agent", _TOOLS, "--workspace", str(tmp_path), "--no-context", "ask me first"])
    assert result.exit_code == 2, result.output


# ---- can't start: 1 ------------------------------------------------------------------


def test_run_busy_port_is_failure_1_before_banner(monkeypatch):
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    served = []
    monkeypatch.setattr(cli_mod.CoworkApp, "run", lambda self, open_browser=True: served.append(1))
    try:
        result = _invoke(["run", "--demo", "--host", "127.0.0.1", "--port", str(port), "--no-browser"])
    finally:
        holder.close()
    assert result.exit_code == 1, result.output
    assert "cannot serve" in result.output
    assert served == []


def test_run_uvicorn_startup_failure_maps_to_1(monkeypatch):
    class _App(_FakeApp):
        def run(self, open_browser=True):
            raise SystemExit(3)  # uvicorn's STARTUP_FAILURE

    monkeypatch.setattr(cli_mod, "CoworkApp", _App)
    monkeypatch.setattr(cli_mod, "_port_bind_error", lambda host, port: None)
    result = _invoke(["run", "--demo", "--no-browser"])
    assert result.exit_code == 1, result.output
