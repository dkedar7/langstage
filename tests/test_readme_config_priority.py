"""The README's config-priority chain must include ``langstage.toml`` (gh #100).

The Configuration section — the one section entirely about ``langstage.toml`` — used
to state the priority as *"Python args > CLI args > environment variables > defaults"*,
dropping the exact TOML layer it teaches the reader to create with ``langstage init``.
That contradicted both the ``init``-generated file header and the ``--show-config``
help, which both name the file. This pins the README to the real four-layer chain.
"""
from pathlib import Path

from langstage.cli import main as cli_main
from langstage.config_template import _HEADER

from click.testing import CliRunner

_README = Path(__file__).resolve().parent.parent / "README.md"


def test_priority_line_names_langstage_toml_between_env_and_defaults():
    text = _README.read_text(encoding="utf-8")
    # The corrected four-layer chain, TOML between env and defaults.
    assert "environment variables > `langstage.toml` > defaults" in text
    # And the old three-layer statement that silently dropped TOML is gone.
    assert "environment variables > defaults" not in text


def test_readme_agrees_with_init_header_and_show_config():
    """All three surfaces name the TOML layer, so they can't contradict each other."""
    readme = _README.read_text(encoding="utf-8")
    assert "langstage.toml" in readme.lower()

    # The init-generated header names "this file" (the langstage.toml) in the chain.
    assert "this file > defaults" in _HEADER

    # --show-config help spells the chain low-to-high and includes langstage.toml.
    help_out = CliRunner().invoke(cli_main, ["--help"]).output
    assert "langstage.toml" in help_out
