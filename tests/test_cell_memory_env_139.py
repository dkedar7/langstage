"""The execute_python memory limit reads the canonical LANGSTAGE_* env name (gh #139).

It used to be settable only as the pre-legacy COWORK_CELL_MEMORY_LIMIT_MB, and a
malformed value raised on import.
"""

import pytest

from langstage.tools import _cell_memory_limit_mb


def _clear(monkeypatch):
    for name in ("LANGSTAGE_CELL_MEMORY_LIMIT_MB", "DEEPAGENT_CELL_MEMORY_LIMIT_MB",
                 "COWORK_CELL_MEMORY_LIMIT_MB"):
        monkeypatch.delenv(name, raising=False)


def test_default_is_512(monkeypatch):
    _clear(monkeypatch)
    assert _cell_memory_limit_mb() == 512


def test_canonical_name_is_honored_and_wins(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("LANGSTAGE_CELL_MEMORY_LIMIT_MB", "99")
    monkeypatch.setenv("COWORK_CELL_MEMORY_LIMIT_MB", "77")
    assert _cell_memory_limit_mb() == 99


@pytest.mark.parametrize("legacy", ["DEEPAGENT_CELL_MEMORY_LIMIT_MB", "COWORK_CELL_MEMORY_LIMIT_MB"])
def test_legacy_names_still_work_with_a_notice(monkeypatch, legacy):
    _clear(monkeypatch)
    monkeypatch.setenv(legacy, "77")
    with pytest.warns(DeprecationWarning):
        assert _cell_memory_limit_mb() == 77


@pytest.mark.parametrize("bad", ["notanint", "0", "-5"])
def test_malformed_value_falls_back_to_default(monkeypatch, bad):
    _clear(monkeypatch)
    monkeypatch.setenv("LANGSTAGE_CELL_MEMORY_LIMIT_MB", bad)
    assert _cell_memory_limit_mb() == 512
