"""Tests for custom CSS serving endpoint."""

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
    """Without custom CSS, /api/custom-css returns 404."""
    config = AppConfig(workspace_root=workspace)
    app = create_fastapi_app(
        agent=mock_agent,
        workspace=workspace,
        config=config,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/custom-css")
        assert resp.status_code == 404


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
