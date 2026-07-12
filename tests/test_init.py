"""Tests for `langstage init` and the config template generator (gh #77)."""
import re
import tomllib

from click.testing import CliRunner

from langstage.cli import main
from langstage.config import AppConfig
from langstage.config_template import render_langstage_toml


# ── generator ────────────────────────────────────────────────────────


def test_template_is_valid_toml_and_ascii():
    txt = render_langstage_toml()
    tomllib.loads(txt)                 # all keys commented → valid (empty tables)
    assert txt.isascii(), "template must be ASCII (cp1252-safe)"


def test_template_uncommented_round_trips_to_defaults():
    txt = render_langstage_toml()
    live = "\n".join(re.sub(r"^# (\w+ = )", r"\1", ln) for ln in txt.splitlines())
    data = tomllib.loads(live)
    assert data["server"]["port"] == 8050
    assert data["server"]["host"] == "localhost"
    assert data["ui"]["title"] == "LangStage"
    assert data["ui"]["theme"] == "auto"
    assert data["auth"]["username"] == "admin"
    # A top-level key must resolve at the document root, not under the last table.
    assert data["debug"] is False


def test_template_covers_every_configurable_key():
    """Lockstep with `config`: every field `config` can read has a line here."""
    txt = render_langstage_toml()
    for tkey in AppConfig._toml_map().values():
        leaf = tkey.split(".")[-1]
        assert re.search(rf"^# {re.escape(leaf)} = ", txt, re.M), f"missing {tkey}"


def test_template_uses_canonical_env_names():
    txt = render_langstage_toml()
    assert "LANGSTAGE_TITLE" in txt
    assert "DEEPAGENT_" not in txt, "must show canonical LANGSTAGE_* env names"


def test_template_groups_into_sections():
    txt = render_langstage_toml()
    for section in ("[agent]", "[workspace]", "[server]", "[ui]", "[auth]"):
        assert section in txt


# ── CLI ──────────────────────────────────────────────────────────────


def test_init_writes_file():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 0, result.output
        from pathlib import Path

        written = Path("langstage.toml")
        assert written.exists()
        tomllib.loads(written.read_text())


def test_init_refuses_existing_without_force():
    runner = CliRunner()
    with runner.isolated_filesystem():
        from pathlib import Path

        Path("langstage.toml").write_text("# pre-existing\n")
        result = runner.invoke(main, ["init"])
        assert result.exit_code != 0
        assert "already exists" in result.output
        assert Path("langstage.toml").read_text() == "# pre-existing\n"  # untouched


def test_init_force_overwrites():
    runner = CliRunner()
    with runner.isolated_filesystem():
        from pathlib import Path

        Path("langstage.toml").write_text("# old\n")
        result = runner.invoke(main, ["init", "--force"])
        assert result.exit_code == 0, result.output
        assert "[server]" in Path("langstage.toml").read_text()


def test_init_path_directory_drops_file_inside():
    runner = CliRunner()
    with runner.isolated_filesystem():
        from pathlib import Path

        result = runner.invoke(main, ["init", "--path", "cfg/"])
        assert result.exit_code == 0, result.output
        assert Path("cfg/langstage.toml").exists()
