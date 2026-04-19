"""Tests for tab visibility: show_canvas / show_files config + auto-detection."""

import os

import pytest

from cowork_dash.config import AppConfig, _parse_optional_bool
from cowork_dash.middleware import CanvasMiddleware, agent_uses_canvas_middleware


# --- _parse_optional_bool -----------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("", None),
        ("1", True),
        ("true", True),
        ("yes", True),
        ("TRUE", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("NO", False),
        ("garbage", None),
    ],
)
def test_parse_optional_bool(value, expected):
    assert _parse_optional_bool(value) is expected


# --- AppConfig: env + client_dict ---------------------------------------------


def test_appconfig_defaults_show_flags_are_none():
    cfg = AppConfig()
    assert cfg.show_canvas is None
    assert cfg.show_files is None


def test_appconfig_to_client_dict_converts_none_to_true():
    """Unresolved (None) flags should surface to the client as True."""
    cfg = AppConfig()
    d = cfg.to_client_dict()
    assert d["show_canvas"] is True
    assert d["show_files"] is True


def test_appconfig_to_client_dict_respects_explicit_values():
    cfg = AppConfig(show_canvas=False, show_files=False)
    d = cfg.to_client_dict()
    assert d["show_canvas"] is False
    assert d["show_files"] is False


def test_appconfig_from_env_reads_show_flags(monkeypatch):
    monkeypatch.setenv("DEEPAGENT_SHOW_CANVAS", "false")
    monkeypatch.setenv("DEEPAGENT_SHOW_FILES", "true")
    cfg = AppConfig.from_env()
    assert cfg.show_canvas is False
    assert cfg.show_files is True


def test_appconfig_from_env_missing_show_flags_are_none(monkeypatch):
    monkeypatch.delenv("DEEPAGENT_SHOW_CANVAS", raising=False)
    monkeypatch.delenv("DEEPAGENT_SHOW_FILES", raising=False)
    cfg = AppConfig.from_env()
    assert cfg.show_canvas is None
    assert cfg.show_files is None


def test_appconfig_merge_preserves_show_flags():
    base = AppConfig(show_canvas=True, show_files=False)
    merged = base.merge({"show_canvas": False})
    assert merged.show_canvas is False
    assert merged.show_files is False


def test_appconfig_merge_ignores_none_overrides():
    """None in the override dict should not clobber an explicit value."""
    base = AppConfig(show_canvas=True)
    merged = base.merge({"show_canvas": None})
    assert merged.show_canvas is True


# --- agent_uses_canvas_middleware ---------------------------------------------


class _FakeAgentWithCanvas:
    def __init__(self):
        self.middleware = [CanvasMiddleware()]


class _FakeAgentWithOtherMiddleware:
    def __init__(self):
        # Non-CanvasMiddleware objects should not trigger detection
        self.middleware = [object(), "not-middleware"]


class _FakeAgentNoMiddleware:
    pass


class _FakeAgentViaBuilder:
    class _Builder:
        def __init__(self):
            self.middleware = [CanvasMiddleware()]
    def __init__(self):
        self.builder = self._Builder()


def test_detect_canvas_middleware_direct_attribute():
    assert agent_uses_canvas_middleware(_FakeAgentWithCanvas()) is True


def test_detect_canvas_middleware_via_builder():
    assert agent_uses_canvas_middleware(_FakeAgentViaBuilder()) is True


def test_detect_no_canvas_middleware_when_absent():
    assert agent_uses_canvas_middleware(_FakeAgentNoMiddleware()) is False


def test_detect_no_canvas_middleware_when_other_middleware_present():
    assert agent_uses_canvas_middleware(_FakeAgentWithOtherMiddleware()) is False


def test_detect_handles_none_agent():
    # Should not crash on unexpected input
    assert agent_uses_canvas_middleware(None) is False
