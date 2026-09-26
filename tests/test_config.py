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
    # parse time (usage exit 64, core ADR 0007, before the command body runs, so no server starts) --
    # only ambient config degrades. Guards that this fix left the CLI path alone.
    result = CliRunner().invoke(
        cli_mod.main, ["run", "--theme", "purple", "--demo", "--no-browser"]
    )
    assert result.exit_code == 64
    assert "Invalid value for '--theme'" in result.output


# ── per-file TOML source provenance (gh #119) ─────────────────────────────────
# When both a global (~/.langstage/config.toml) and a project langstage.toml
# contribute, each TOML-sourced field must be attributed to the file that actually
# supplied its value. A value set ONLY in the global file used to be mislabeled as
# coming from the project langstage.toml (the deep-merged dict lost per-key
# provenance), silently defeating the deploy-time "where did this value come from?"
# guardrail the source column exists for. Fixed at the core layer (langstage-core
# >= 1.0.32); these pin that the corrected source reaches langstage's config surface.


def _global_and_project(tmp_path, monkeypatch, global_toml: str, project_toml: str):
    """Write a global config.toml + a project langstage.toml, point the resolver at
    the global via LANGSTAGE_CONFIG_HOME (isolating any real ~/.langstage/config.toml),
    and chdir into the project. Returns the project dir."""
    gdir = tmp_path / "global"
    gdir.mkdir()
    (gdir / "config.toml").write_text(global_toml)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "langstage.toml").write_text(project_toml)
    monkeypatch.setenv("LANGSTAGE_CONFIG_HOME", str(gdir))
    monkeypatch.chdir(proj)
    return proj


def test_global_only_value_attributed_to_global_file_not_project(tmp_path, monkeypatch):
    _global_and_project(
        tmp_path,
        monkeypatch,
        global_toml='[ui]\nsubtitle = "i-am-from-GLOBAL"\n',   # global sets ONLY subtitle
        project_toml='[ui]\ntitle = "i-am-from-PROJECT"\n',    # project sets ONLY title
    )
    cfg = AppConfig.resolve()

    # Value resolution was always correct (global < project); the SOURCE column is
    # what #119 is about.
    assert cfg.subtitle == "i-am-from-GLOBAL"
    assert cfg.title == "i-am-from-PROJECT"
    # subtitle came only from the global config.toml -> it must name THAT file, not
    # the project langstage.toml.
    assert cfg.sources["subtitle"] == "toml (config.toml)"
    assert cfg.sources["title"] == "toml (langstage.toml)"


def test_show_config_attributes_global_value_to_global_file(tmp_path, monkeypatch):
    # The fix must reach the actual user surface (`--show-config`), not just resolve().
    _global_and_project(
        tmp_path,
        monkeypatch,
        global_toml='[ui]\nsubtitle = "i-am-from-GLOBAL"\n',
        project_toml='[ui]\ntitle = "i-am-from-PROJECT"\n',
    )
    result = CliRunner().invoke(cli_mod.main, ["--show-config"])

    assert result.exit_code == 0, result.output
    # subtitle labeled with the global file it came from...
    assert re.search(
        r"subtitle\s*=\s*i-am-from-GLOBAL\s+\[toml \(config\.toml\)\]", result.output
    ), result.output
    # ...and the project-only title with the project file.
    assert re.search(
        r"title\s*=\s*i-am-from-PROJECT\s+\[toml \(langstage\.toml\)\]", result.output
    ), result.output


# ── unknown / typo'd / misplaced TOML keys are surfaced (gh #120) ─────────────
# A typo'd key, a key in the wrong section, or an entirely unknown key in
# langstage.toml is silently dropped by the layered config -- the #1 hand-edit
# mistake, which `config` / `--show-config` (the "edit it, then verify" step)
# couldn't catch. Wired at the core layer (langstage-core >= 1.0.32) via
# HostConfig.unknown_toml_keys(), rendered by describe(); these pin that langstage's
# config surfaces it.


def _isolate_global(tmp_path, monkeypatch):
    """Point the resolver's global-config lookup at an EMPTY dir so a real
    ~/.langstage/config.toml can't perturb an exact unknown-keys assertion."""
    empty = tmp_path / "no-global"
    empty.mkdir()
    monkeypatch.setenv("LANGSTAGE_CONFIG_HOME", str(empty))


def test_unknown_toml_keys_reported_at_resolve(tmp_path, monkeypatch):
    _isolate_global(tmp_path, monkeypatch)
    (tmp_path / "langstage.toml").write_text(
        '[ui]\ntitel = "My App"\n[server]\nprot = 9000\n'  # typos: title / port
    )
    monkeypatch.chdir(tmp_path)
    cfg = AppConfig.resolve()

    assert cfg.unknown_toml_keys() == ["server.prot", "ui.titel"]
    # The fields the typos were meant for stay at their defaults (the edit was dropped).
    assert cfg.title == "LangStage" and cfg.sources["title"] == "default"
    assert cfg.port == 8050 and cfg.sources["port"] == "default"


def test_config_command_reports_unknown_toml_keys(tmp_path, monkeypatch):
    _isolate_global(tmp_path, monkeypatch)
    (tmp_path / "langstage.toml").write_text(
        '[ui]\ntitel = "My App"\n[server]\nprot = 9000\n'
    )
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli_mod.main, ["config"])

    assert result.exit_code == 0, result.output
    assert "unknown TOML keys" in result.output
    assert "ui.titel" in result.output
    assert "server.prot" in result.output


def test_config_json_reports_unknown_toml_keys(tmp_path, monkeypatch):
    # The machine-readable surface a deploy step asserts on gets them too (gh #120).
    import json

    _isolate_global(tmp_path, monkeypatch)
    (tmp_path / "langstage.toml").write_text('[ui]\ntitel = "My App"\n')
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli_mod.main, ["config", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["unknown_toml_keys"] == ["ui.titel"]


def test_config_clean_toml_reports_no_unknown_keys(tmp_path, monkeypatch):
    # A correct file must NOT be flagged -- guards against false positives.
    _isolate_global(tmp_path, monkeypatch)
    (tmp_path / "langstage.toml").write_text('[ui]\ntitle = "My App"\n[server]\nport = 9000\n')
    monkeypatch.chdir(tmp_path)
    cfg = AppConfig.resolve()

    assert cfg.unknown_toml_keys() == []
    result = CliRunner().invoke(cli_mod.main, ["config"])
    assert "unknown TOML keys" not in result.output


# ── out-of-range port degrades / hard-errors, never a silent misbind (gh #123) ──
# An out-of-range integer port (70000) was type-valid so it sailed through the
# resolver, was advertised by --show-config and the startup banner, and then uvicorn
# silently masked it to 16 bits (70000 & 0xFFFF == 4464) — the server bound a
# DIFFERENT port than everything advertised, with no error. Fixed at the core layer
# (langstage-core >= 1.0.33: resolve()'s port-range validator degrades an out-of-range
# env/TOML/override value to the default + a note); the interactive --port flag adds a
# clean hard error via click.IntRange. These pin both halves reach langstage.


def _clear_invalid_port_note_dedupe():
    # The core "ignoring invalid port=..." note dedupes per (field, value) across a
    # process; clear it so each test observes its own note regardless of test order.
    from langstage_core.host import config as _core_cfg

    _core_cfg._warned_invalid_value.clear()


def test_out_of_range_env_port_degrades_to_default_with_note(monkeypatch, capsys):
    _clear_invalid_port_note_dedupe()
    monkeypatch.setenv("LANGSTAGE_PORT", "70000")
    cfg = AppConfig.from_env()  # must NOT raise

    assert cfg.port == 8050  # degraded to the default, not the masked 4464
    assert cfg.sources["port"] == "default"  # not credited to the rejected env var
    err = capsys.readouterr().err
    assert "ignoring invalid port=70000" in err
    assert "1-65535" in err  # names the valid range


def test_out_of_range_override_port_degrades_to_default(capsys):
    # The Python/CLI override path (CoworkApp(port=...) -> resolve(overrides=...)) also
    # degrades — an out-of-range value can never reach uvicorn to be masked.
    _clear_invalid_port_note_dedupe()
    cfg = AppConfig.resolve(overrides={"port": 99999})

    assert cfg.port == 8050
    assert cfg.sources["port"] == "default"
    assert "ignoring invalid port=99999" in capsys.readouterr().err


def test_show_config_reports_degraded_port_as_default(monkeypatch):
    # --show-config must never present the out-of-range port as a resolved value.
    _clear_invalid_port_note_dedupe()
    monkeypatch.setenv("LANGSTAGE_PORT", "70000")
    result = CliRunner().invoke(cli_mod.main, ["--show-config"])

    assert result.exit_code == 0, result.output
    assert re.search(r"port\s*=\s*8050\s+\[default\]", result.output), result.output
    # The rejected 70000 must never appear as a resolved value (a table line is
    # `port = <value> [source]`). The stderr note names 70000 as the ignored value —
    # `port=70000 (ValueError...)` — which is fine; only the resolved line must not
    # show it, so match the value-then-`[source]` shape the note never has.
    assert not re.search(r"port\s*=\s*70000\s+\[", result.output), result.output


def test_valid_env_port_still_resolves_with_source(monkeypatch):
    # An in-range value must resolve normally with correct source attribution.
    monkeypatch.setenv("LANGSTAGE_PORT", "9000")
    cfg = AppConfig.from_env()
    assert cfg.port == 9000
    assert cfg.sources["port"] == "env:LANGSTAGE_PORT"


def test_cli_port_flag_hard_rejects_out_of_range():
    # The interactive --port flag hard-errors at parse time (usage exit 64, before the command
    # body runs, so no server starts) via click.IntRange — the clean CLI error an
    # explicit flag deserves, mirroring --theme. Guards the silent-misbind is gone.
    result = CliRunner().invoke(
        cli_mod.main, ["run", "--port", "70000", "--demo", "--no-browser"]
    )
    assert result.exit_code == 64
    assert "Invalid value for '--port'" in result.output


# ── `langstage config --strict` is a CI gate on a typo'd/unknown TOML key (gh #125) ──
# `config` surfaces unknown keys but always exits 0, so CI can't gate on a config typo
# with an exit code. --strict exits 1 when there are unknown keys (0 when clean), so a
# deploy step can fail the build on a mistyped key. Default (no --strict) stays exit 0.


def test_config_strict_exits_nonzero_on_unknown_key(tmp_path, monkeypatch):
    _isolate_global(tmp_path, monkeypatch)
    # `prt` is a typo for `port` -> the server would silently bind :8050, not :9000.
    (tmp_path / "langstage.toml").write_text('[server]\nprt = 9000\nhost = "0.0.0.0"\n')
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli_mod.main, ["config", "--strict"])

    assert result.exit_code == 1, result.output
    # Still prints the human table + the unknown-keys line...
    assert "server.prt" in result.output
    # ...plus the strict error summary on stderr.
    assert "not clean" in result.stderr
    assert "server.prt" in result.stderr


def test_config_strict_exits_zero_on_clean_config(tmp_path, monkeypatch):
    _isolate_global(tmp_path, monkeypatch)
    (tmp_path / "langstage.toml").write_text('[server]\nport = 9000\nhost = "0.0.0.0"\n')
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli_mod.main, ["config", "--strict"])

    assert result.exit_code == 0, result.output
    assert "not clean" not in result.output


def test_config_without_strict_exits_zero_even_with_unknown_key(tmp_path, monkeypatch):
    # The default (no --strict) keeps the "degrade, don't crash" contract: exit 0 even
    # with a typo, only surfacing it in the output.
    _isolate_global(tmp_path, monkeypatch)
    (tmp_path / "langstage.toml").write_text('[server]\nprt = 9000\n')
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli_mod.main, ["config"])

    assert result.exit_code == 0, result.output
    assert "server.prt" in result.output


def test_config_strict_composes_with_json(tmp_path, monkeypatch):
    # --strict composes with --json: same exit-code contract, JSON still on stdout so a
    # pipeline can gate coarsely on the exit code or finely on the JSON.
    import json

    _isolate_global(tmp_path, monkeypatch)
    (tmp_path / "langstage.toml").write_text('[ui]\ntitel = "My App"\n')
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli_mod.main, ["config", "--json", "--strict"])

    assert result.exit_code == 1, result.output
    # The JSON payload is still emitted (with the unknown key) on stdout; the strict
    # error summary goes to stderr, so the two don't collide.
    payload = json.loads(result.stdout[: result.stdout.index("error:")] if "error:" in result.stdout else result.stdout)
    assert payload["unknown_toml_keys"] == ["ui.titel"]
    assert "not clean" in result.stderr
