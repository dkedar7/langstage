"""Tests for configuration resolution."""

import os
import pytest
from langstage.config import AppConfig


def test_defaults():
    cfg = AppConfig()
    assert cfg.host == "localhost"
    assert cfg.port == 8050
    assert cfg.debug is False
    assert cfg.title == "LangStage"
    assert cfg.subtitle == "AI-Powered Workspace"
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
