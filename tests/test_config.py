"""Tests for configuration resolution."""

import re

from click.testing import CliRunner

from langstage import cli as cli_mod
from langstage import config as config_mod
from langstage.config import AppConfig


def test_defaults():
    cfg = AppConfig()
    assert cfg.host == "localhost"
    assert cfg.port == 8050
    assert cfg.debug is False
    assert cfg.title == "LangStage"
    assert cfg.subtitle == ""  # empty by default (no generic filler); user-settable
    assert cfg.theme == "auto"
    assert cfg.welcome_message == ""
    assert cfg.agent_spec is None


def test_from_env(monkeypatch):
    monkeypatch.setenv("DEEPAGENT_TITLE", "My Agent")
    monkeypatch.setenv("DEEPAGENT_PORT", "9000")
    monkeypatch.setenv("DEEPAGENT_DEBUG", "true")
    monkeypatch.setenv("DEEPAGENT_THEME", "dark")

    cfg = AppConfig.from_env()
    assert cfg.title == "My Agent"
    assert cfg.port == 9000
    assert cfg.debug is True
    assert cfg.theme == "dark"


def test_merge():
    cfg = AppConfig(title="Original", port=8050)
    merged = cfg.merge({"title": "Overridden", "port": None})
    assert merged.title == "Overridden"
    assert merged.port == 8050  # None is skipped


def test_to_client_dict():
    cfg = AppConfig(title="Test", subtitle="Sub", welcome_message="Hi", theme="dark")
    d = cfg.to_client_dict()
    assert d["title"] == "Test"
    assert d["subtitle"] == "Sub"
    assert d["welcome_message"] == "Hi"
    assert d["theme"] == "dark"
    assert "workspace_name" in d


def test_custom_css_default():
    cfg = AppConfig()
    assert cfg.custom_css == ""


def test_custom_css_from_env(monkeypatch):
    monkeypatch.setenv("DEEPAGENT_CUSTOM_CSS", "/path/to/theme.css")
    cfg = AppConfig.from_env()
    assert cfg.custom_css == "/path/to/theme.css"


def test_custom_css_merge():
    cfg = AppConfig()
    merged = cfg.merge({"custom_css": "my-theme.css"})
    assert merged.custom_css == "my-theme.css"


def test_custom_css_not_in_client_dict():
    cfg = AppConfig(custom_css="theme.css")
    d = cfg.to_client_dict()
    assert "custom_css" not in d


# ── theme enum enforced on the non-CLI paths (env / TOML / Python-API) ────────
# gh #104: the documented three-value theme enum was enforced on ONLY the --theme
# CLI flag (a click.Choice). env (LANGSTAGE_THEME), TOML (ui.theme), and the
# Python-API AppConfig(theme=...) accepted any string silently, so an invalid
# value was reported by --show-config as legitimately resolved and shipped to the
# client (GET /api/config), where the UI silently ignored it. Those ambient paths
# now DEGRADE an invalid value to the default "auto" with a one-line stderr note
# -- crashing an entrypoint on ambient config is worse than degrading, matching
# langstage-core's graceful malformed-numeric handling (>= 1.0.23). The --theme
# CLI flag keeps its immediate hard click.Choice rejection.
#
# These drive the config resolver and --show-config only, never the server-
# starting `run` command: the graceful degrade means `run` would get a valid
# config, start the server, and hang the test.


def _clear_theme_note_dedupe():
    # The note dedupes per bad value across a process; clear it so each test can
    # observe its own note regardless of test order.
    config_mod._warned_invalid_theme.clear()


def test_invalid_env_theme_degrades_to_default_with_note(monkeypatch, capsys):
    _clear_theme_note_dedupe()
    monkeypatch.setenv("LANGSTAGE_THEME", "purple")
    cfg = AppConfig.from_env()  # must NOT raise

    assert cfg.theme == "auto"  # degraded to the default, not "purple"
    assert cfg.sources["theme"] == "default"  # not credited to the rejected env var
    err = capsys.readouterr().err
    assert "ignoring invalid theme 'purple'" in err
    assert "light, dark, auto" in err  # names the accepted set


def test_invalid_toml_theme_degrades_to_default_with_note(
    tmp_path, monkeypatch, capsys
):
    _clear_theme_note_dedupe()
    (tmp_path / "langstage.toml").write_text('[ui]\ntheme = "banana"\n')
    monkeypatch.chdir(tmp_path)
    cfg = AppConfig.resolve()  # must NOT raise

    assert cfg.theme == "auto"
    assert cfg.sources["theme"] == "default"  # not "toml (langstage.toml)"
    err = capsys.readouterr().err
    assert "ignoring invalid theme 'banana'" in err


def test_invalid_python_api_theme_degrades_to_default(capsys):
    _clear_theme_note_dedupe()
    cfg = AppConfig(theme="chartreuse")  # direct constructor -- never touches resolve()

    assert cfg.theme == "auto"
    assert "ignoring invalid theme 'chartreuse'" in capsys.readouterr().err
    # ...and so the invalid value can never reach the client via GET /api/config.
    assert cfg.to_client_dict()["theme"] == "auto"


def test_show_config_reports_degraded_theme_as_default(tmp_path, monkeypatch):
    # --show-config must never present an un-honorable theme as a resolved value.
    _clear_theme_note_dedupe()
    (tmp_path / "langstage.toml").write_text('[ui]\ntheme = "fuchsia"\n')
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli_mod.main, ["--show-config"])

    assert result.exit_code == 0, result.output
    # theme resolves to auto, attributed to [default] -- never presented as the
    # "fuchsia" it read (the note may still name fuchsia as the ignored value;
    # what matters is it is never shown as a resolved value).
    assert re.search(r"theme\s*=\s*auto\s+\[default\]", result.output), result.output
    assert not re.search(r"theme\s*=\s*fuchsia", result.output), result.output


def test_valid_env_theme_still_resolves_with_source(monkeypatch):
    # A VALID value must resolve normally with correct source attribution.
    monkeypatch.setenv("LANGSTAGE_THEME", "dark")
    cfg = AppConfig.from_env()
    assert cfg.theme == "dark"
    assert cfg.sources["theme"] == "env:LANGSTAGE_THEME"


def test_valid_toml_theme_still_resolves_with_source(tmp_path, monkeypatch):
    (tmp_path / "langstage.toml").write_text('[ui]\ntheme = "light"\n')
    monkeypatch.chdir(tmp_path)
    cfg = AppConfig.resolve()
    assert cfg.theme == "light"
    assert "toml" in cfg.sources["theme"]


def test_theme_enum_is_case_sensitive_like_the_cli(monkeypatch, capsys):
    # The --theme flag's click.Choice(["light","dark","auto"]) is case-sensitive;
    # the ambient paths match it, so the accepted set is identical across all four
    # sources. "Dark" is therefore invalid and degrades.
    _clear_theme_note_dedupe()
    monkeypatch.setenv("LANGSTAGE_THEME", "Dark")
    cfg = AppConfig.from_env()
    assert cfg.theme == "auto"
    assert "ignoring invalid theme 'Dark'" in capsys.readouterr().err


def test_cli_theme_flag_still_hard_rejects():
    # The interactive --theme flag keeps its immediate click.Choice rejection at
    # parse time (exit 2, before the command body runs, so no server starts) --
    # only ambient config degrades. Guards that this fix left the CLI path alone.
    result = CliRunner().invoke(
        cli_mod.main, ["run", "--theme", "purple", "--demo", "--no-browser"]
    )
    assert result.exit_code == 2
    assert "Invalid value for '--theme'" in result.output
