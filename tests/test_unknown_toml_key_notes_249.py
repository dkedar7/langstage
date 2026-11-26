"""gh #249: `run` / `check` / `chat` name an unknown or misplaced langstage.toml key.

`langstage config` already listed `agent.spce` as an unknown key, but the commands a
user actually runs said nothing: they fell back to the built-in default agent and
blamed the missing `deepagents` extra, and `check` claimed "nothing is configured".
"""

import json

import pytest
from click.testing import CliRunner

from langstage import cli as cli_mod
from langstage.cli import main

DEMO = "langstage_core.demo.tools:graph"


@pytest.fixture
def project(tmp_path, monkeypatch):
    """An empty project dir as cwd, with no global config and no LANGSTAGE_* env."""
    home = tmp_path / "home"
    home.mkdir()
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setenv("LANGSTAGE_CONFIG_HOME", str(home))
    for var in ("LANGSTAGE_AGENT_SPEC", "DEEPAGENT_AGENT_SPEC", "LANGSTAGE_WORKSPACE_ROOT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(proj)
    return proj


def _write(proj, text):
    (proj / "langstage.toml").write_text(text, encoding="utf-8")


@pytest.mark.parametrize(
    ("toml", "key"),
    [
        (f'[agent]\nspce = "{DEMO}"\n', "agent.spce"),
        (f'spec = "{DEMO}"\n', "spec"),
        (f'[agents]\nspec = "{DEMO}"\n', "agents.spec"),
    ],
)
def test_check_names_the_ignored_agent_key(project, toml, key):
    _write(project, toml)
    result = CliRunner().invoke(main, ["check"])
    note = f"note: unknown key {key} in ./langstage.toml ignored (did you mean agent.spec?)"
    assert note in result.stderr
    assert '[agent] spec = "path/to/agent.py:graph"' in result.stderr
    # Something IS configured, so check must not claim otherwise.
    assert "nothing is configured" not in result.output
    assert f"langstage.toml's {key} was ignored" in result.output


def test_check_json_lists_unknown_keys_and_keeps_stdout_json(project):
    _write(project, f'[agent]\nspce = "{DEMO}"\n')
    result = CliRunner().invoke(main, ["check", "--json"])
    payload = json.loads(result.stdout)
    assert payload["unknown_toml_keys"] == ["agent.spce"]
    assert "note: unknown key agent.spce" in result.stderr


def test_chat_and_run_note_the_key_before_failing(project, monkeypatch):
    _write(project, f'[agent]\nspce = "{DEMO}"\n')

    def no_app(*a, **k):  # never start a server or build the default agent
        raise RuntimeError("stub: no app")

    monkeypatch.setattr(cli_mod, "CoworkApp", no_app)
    for args in (["chat", "hi"], ["run", "--no-browser"]):
        result = CliRunner().invoke(main, args)
        assert "note: unknown key agent.spce in ./langstage.toml ignored" in result.stderr, args


def test_a_non_agent_typo_gets_a_plain_note(project):
    _write(project, '[ui]\nthemee = "dark"\n')
    result = CliRunner().invoke(main, ["check", "--demo"])
    assert "note: unknown key ui.themee in ./langstage.toml ignored (did you mean ui.theme?)" in result.stderr
    assert "[agent] spec" not in result.stderr
    assert result.exit_code == 0


def test_agent_key_with_a_working_spec_gets_no_agent_hint(project):
    # The spec resolved fine; a stray extra key under [agent] is only a typo note.
    _write(project, f'[agent]\nspec = "{DEMO}"\nspce = "x"\n')
    result = CliRunner().invoke(main, ["check"])
    assert "note: unknown key agent.spce" in result.stderr
    assert "[agent] spec = " not in result.stderr
    assert f"Checking agent: {DEMO}" in result.output


def test_clean_config_prints_no_note(project):
    _write(project, f'[agent]\nspec = "{DEMO}"\n')
    result = CliRunner().invoke(main, ["check"])
    assert "unknown key" not in result.stderr
    assert result.exit_code == 0


def test_misplaced_bare_key_is_left_to_cores_own_note(project):
    # `debug` under [server] parses as server.debug; core notes it at resolve time.
    _write(project, "[server]\ndebug = true\n")
    result = CliRunner().invoke(main, ["check", "--demo"])
    assert "note: unknown key server.debug" not in result.stderr


def test_note_never_breaks_the_command(project, monkeypatch):
    class Broken:
        def config_issues(self):
            raise RuntimeError("boom")

    assert cli_mod._note_unknown_toml_keys(Broken()) == []
