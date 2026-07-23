"""`LANGSTAGE_TASK_CONCURRENCY` resolves through the unified config chain (gh #102).

Before this it was read with a bare ``os.getenv`` in ``server/main.py``, outside the
resolver every other ``LANGSTAGE_*`` option goes through — so it was invisible to
``--show-config`` and a bad value crashed ``run`` with an unhandled ``ValueError``
traceback (where the same misconfiguration of ``--port`` is reported as a clean
one-line ``Error:``). It is now a first-class ``AppConfig`` field.
"""
import re

from click.testing import CliRunner
from langgraph.graph import END, START, MessagesState, StateGraph

from langstage import cli as cli_mod
from langstage.config import AppConfig
from langstage.server.main import create_fastapi_app


def _graph():
    b = StateGraph(MessagesState)
    b.add_node("n", lambda s: {"messages": []})
    b.add_edge(START, "n")
    b.add_edge("n", END)
    return b.compile()


# ── resolution: default / env / legacy / toml ────────────────────────────────


def test_default_is_three():
    assert AppConfig().task_concurrency == 3


def test_resolves_from_canonical_env(monkeypatch):
    monkeypatch.setenv("LANGSTAGE_TASK_CONCURRENCY", "7")
    cfg = AppConfig.from_env()
    assert cfg.task_concurrency == 7
    assert cfg.sources["task_concurrency"] == "env:LANGSTAGE_TASK_CONCURRENCY"


def test_resolves_from_legacy_env(monkeypatch):
    # DEEPAGENT_* is the deprecated fallback, resolved like every other key.
    monkeypatch.setenv("DEEPAGENT_TASK_CONCURRENCY", "4")
    cfg = AppConfig.from_env()
    assert cfg.task_concurrency == 4


def test_resolves_from_toml(tmp_path, monkeypatch):
    # The whole point of the resolver: a langstage.toml key now works, which the raw
    # os.getenv ignored entirely.
    (tmp_path / "langstage.toml").write_text("[tasks]\nconcurrency = 9\n")
    monkeypatch.chdir(tmp_path)
    cfg = AppConfig.resolve()
    assert cfg.task_concurrency == 9
    assert "toml" in cfg.sources["task_concurrency"]


# ── visibility: it now shows up in --show-config ─────────────────────────────


def test_show_config_lists_task_concurrency():
    result = CliRunner().invoke(cli_mod.main, ["--show-config"])
    assert result.exit_code == 0, result.output
    assert re.search(r"task_concurrency\s*=\s*3", result.output), result.output
    # ...with its env-var hint, like every other resolved key.
    assert "LANGSTAGE_TASK_CONCURRENCY" in result.output


# ── graceful malformed-value handling (parity with every numeric key) ────────


def test_bad_value_degrades_to_the_default_with_a_note(monkeypatch, capsys):
    """A non-integer value no longer crashes with an unhandled ValueError traceback
    (the original #102 bug). Now that ``task_concurrency`` resolves through the
    unified resolver, it inherits langstage-core's graceful numeric-env handling
    (>= 1.0.23): the bad value is ignored, a one-line ``note:`` names it, and the
    field falls back to its default — parity with `--port` and every other numeric
    env var, which all degrade the same way rather than crashing.

    Deliberately does NOT drive the ``run`` command (which would start a real
    server and block); the config resolver is where the behaviour lives.
    """
    monkeypatch.setenv("LANGSTAGE_TASK_CONCURRENCY", "oops")
    cfg = AppConfig.from_env()  # must NOT raise

    assert cfg.task_concurrency == 3  # the default, not a crash
    assert cfg.sources["task_concurrency"] == "default"
    err = capsys.readouterr().err
    assert "ignoring malformed LANGSTAGE_TASK_CONCURRENCY" in err
    assert "invalid literal for int" in err


# ── the resolved value still bounds the TaskRunner exactly as before ─────────


def test_resolved_value_bounds_the_runner(tmp_path):
    app = create_fastapi_app(
        agent=_graph(), workspace=tmp_path, config=AppConfig(task_concurrency=6)
    )
    assert app.state.task_runner._concurrency == 6
