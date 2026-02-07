"""Tests for agent loading from spec strings."""

import pytest
from cowork_dash.agent_loader import load_agent_from_spec


def test_invalid_spec_format():
    with pytest.raises(ValueError, match="Invalid agent spec"):
        load_agent_from_spec("no_colon_here")


def test_missing_file():
    with pytest.raises((FileNotFoundError, ImportError, ModuleNotFoundError)):
        load_agent_from_spec("nonexistent_module.py:agent")


def test_missing_attribute(tmp_path):
    agent_file = tmp_path / "my_agent.py"
    agent_file.write_text("x = 1\n")

    with pytest.raises(AttributeError, match="no attribute"):
        load_agent_from_spec(f"{agent_file}:missing_obj")


def test_load_from_file(tmp_path):
    agent_file = tmp_path / "my_agent.py"
    agent_file.write_text("agent = 'loaded!'\n")

    result = load_agent_from_spec(f"{agent_file}:agent")
    assert result == "loaded!"
