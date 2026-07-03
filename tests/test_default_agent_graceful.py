"""gh #46: `langstage run` must not crash on a clean `pip install langstage`.

The default agent needs the `deepagents` extra; building it at import time crashed
every entrypoint, and the remediation named the wrong package (`langstage-core[demo]`
instead of `langstage[deepagents]`). These run WITHOUT deepagents installed — they
mock the factory failure, so no `importorskip`.
"""

from pathlib import Path

import pytest


def test_create_default_agent_remessages_missing_deepagents(monkeypatch):
    # The shared core's factory raises naming `langstage-core[demo]`; the web must
    # re-message with the package a `langstage` user actually installs.
    import langstage.default_agent as da

    def _boom(*args, **kwargs):
        raise RuntimeError(
            "create_default_agent requires the 'deepagents' extra. "
            "Install it with: pip install langstage-core[demo]"
        )

    monkeypatch.setattr(da, "_build_default_agent", _boom)
    with pytest.raises(RuntimeError, match=r"langstage\[deepagents\]") as exc:
        da.create_default_agent(Path("."))
    # ASCII-only (must encode on a cp1252 Windows console).
    str(exc.value).encode("cp1252")


def test_non_deepagents_runtime_error_is_not_swallowed(monkeypatch):
    # A RuntimeError unrelated to the missing extra must propagate unchanged, not be
    # re-messaged as a deepagents problem.
    import langstage.default_agent as da

    def _boom(*args, **kwargs):
        raise RuntimeError("some other failure")

    monkeypatch.setattr(da, "_build_default_agent", _boom)
    with pytest.raises(RuntimeError, match="some other failure"):
        da.create_default_agent(Path("."))
