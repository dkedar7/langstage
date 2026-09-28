"""Shared test fixtures."""
import pytest


@pytest.fixture
def raw_demo_echo(monkeypatch):
    """Make the keyless demo agent echo its whole input, surface context included.

    Since langstage-core 1.0.39 (gh #192) the demo agents echo only what the user typed
    and drop the ``[Working directory: ...]``-style context lines a surface prepends.
    Tests that check that context reaches the agent need to see those lines, so they
    turn the stripping off. ``raising=False`` keeps this a no-op on older cores, which
    echo everything anyway.
    """
    monkeypatch.setattr(
        "langstage_core.demo.stub.user_text", lambda text: text, raising=False
    )
