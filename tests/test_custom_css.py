"""Tests for custom CSS serving endpoint."""

from pathlib import Path

import pytest
from unittest.mock import MagicMock
from httpx import AsyncClient, ASGITransport

from langstage.config import AppConfig
from langstage.server.main import create_fastapi_app


@pytest.fixture
def workspace(tmp_path):
    return tmp_path


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.checkpointer = MagicMock()
    return agent


@pytest.mark.asyncio
async def test_custom_css_not_configured(workspace, mock_agent):
    """Without custom CSS, /api/custom-css returns 204 No Content, not 404: the
    frontend fetches it on every load, and the 404 logged a console error (gh #193)."""
    config = AppConfig(workspace_root=workspace)
    app = create_fastapi_app(
        agent=mock_agent,
        workspace=workspace,
        config=config,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/custom-css")
        assert resp.status_code == 204
        assert resp.content == b""


@pytest.mark.asyncio
async def test_custom_css_served(workspace, mock_agent):
    """With custom CSS content, /api/custom-css returns it with text/css type."""
    css_content = ":root { --color-primary: #ff0000; }"
    config = AppConfig(workspace_root=workspace)
    app = create_fastapi_app(
        agent=mock_agent,
        workspace=workspace,
        config=config,
        custom_css_content=css_content,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/custom-css")
        assert resp.status_code == 200
        assert "text/css" in resp.headers["content-type"]
        assert resp.text == css_content


@pytest.mark.asyncio
async def test_custom_css_content_matches(workspace, mock_agent):
    """CSS endpoint returns the exact content that was configured."""
    css_content = """:root {
  --color-primary: #0077b6;
  --color-surface: #f8fbff;
}

.dark {
  --color-surface: #0a1628;
}"""
    config = AppConfig(workspace_root=workspace)
    app = create_fastapi_app(
        agent=mock_agent,
        workspace=workspace,
        config=config,
        custom_css_content=css_content,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/custom-css")
        assert resp.status_code == 200
        assert resp.text == css_content


# ---- [ui] custom_css path resolution (gh #209) ----

def _project(tmp_path, value):
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    (proj / "theme.css").write_text(":root { --color-primary: #ff0000; }", encoding="utf-8")
    (proj / "langstage.toml").write_text(f'[ui]\ncustom_css = "{value}"\n', encoding="utf-8")
    return proj


def _resolve(start, env=None):
    env = {"LANGSTAGE_CONFIG_HOME": str(start / "_nohome"), **(env or {})}
    return AppConfig.resolve(toml_start=start, env=env)


def test_relative_custom_css_resolves_against_the_toml_not_the_cwd(tmp_path, monkeypatch):
    """Run from a subdirectory: the theme still points at the toml's sibling file."""
    proj = _project(tmp_path, "theme.css")
    monkeypatch.chdir(proj / "src")
    cfg = _resolve(proj / "src")
    assert isinstance(cfg.custom_css, str)
    assert cfg.custom_css == str(proj / "theme.css")
    assert cfg.sources["custom_css"].startswith("toml")


def test_absolute_custom_css_is_kept(tmp_path):
    css = tmp_path / "abs.css"
    css.write_text("x", encoding="utf-8")
    proj = _project(tmp_path, css.as_posix())
    cfg = _resolve(proj / "src")
    assert Path(cfg.custom_css) == css


def test_blank_custom_css_in_toml_means_no_theme(tmp_path):
    proj = _project(tmp_path, "")
    assert _resolve(proj / "src").custom_css == ""


def test_env_custom_css_expands_home_and_stays_cwd_relative(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    proj = _project(tmp_path, "theme.css")
    cfg = _resolve(proj / "src", {"LANGSTAGE_CUSTOM_CSS": "~/home-theme.css"})
    assert cfg.custom_css == str(home / "home-theme.css")
    cfg = _resolve(proj / "src", {"LANGSTAGE_CUSTOM_CSS": "rel.css"})
    assert cfg.custom_css == "rel.css"
