"""Tests for the FastAPI app and REST endpoints."""

import pytest
from unittest.mock import MagicMock, AsyncMock
from pathlib import Path
from httpx import AsyncClient, ASGITransport

from cowork_dash.config import AppConfig
from cowork_dash.server.main import create_fastapi_app


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "hello.py").write_text("print('hello')")
    (tmp_path / "data.csv").write_text("a,b\n1,2\n")
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "nested.txt").write_text("nested content")
    return tmp_path


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.checkpointer = MagicMock()
    return agent


@pytest.fixture
def app(workspace, mock_agent):
    config = AppConfig(
        workspace=workspace,
        title="Test App",
        subtitle="Test Sub",
        welcome_message="Welcome!",
        theme="dark",
    )
    return create_fastapi_app(
        agent=mock_agent,
        workspace=workspace,
        config=config,
    )


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_config_endpoint(client):
    resp = await client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Test App"
    assert data["subtitle"] == "Test Sub"
    assert data["welcome_message"] == "Welcome!"
    assert data["theme"] == "dark"


@pytest.mark.asyncio
async def test_files_tree(client):
    resp = await client.get("/api/files/tree")
    assert resp.status_code == 200
    data = resp.json()
    names = [e["name"] for e in data["entries"]]
    assert "hello.py" in names


@pytest.mark.asyncio
async def test_files_read(client):
    resp = await client.get("/api/files/read?path=/hello.py")
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "print('hello')"
    assert data["language"] == "python"


@pytest.mark.asyncio
async def test_files_read_not_found(client):
    resp = await client.get("/api/files/read?path=/nope.txt")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_canvas_empty(client):
    resp = await client.get("/api/canvas/items")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_canvas_export_empty(client):
    resp = await client.get("/api/canvas/export")
    assert resp.status_code == 200
    assert resp.json()["content"] == ""


@pytest.mark.asyncio
async def test_delete_session_endpoint(client):
    """DELETE /api/session/{id} returns ok even for nonexistent sessions."""
    resp = await client.delete("/api/session/fake-session-id")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


# --- Basic Auth tests ---

@pytest.fixture
def auth_app(workspace, mock_agent):
    config = AppConfig(
        workspace=workspace,
        title="Auth App",
        auth_username="myuser",
        auth_password="mypass",
    )
    return create_fastapi_app(
        agent=mock_agent,
        workspace=workspace,
        config=config,
    )


@pytest.fixture
async def auth_client(auth_app):
    transport = ASGITransport(app=auth_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_auth_rejects_unauthenticated(auth_client):
    """Requests without credentials get 401."""
    resp = await auth_client.get("/api/config")
    assert resp.status_code == 401
    assert "Basic" in resp.headers.get("www-authenticate", "")


@pytest.mark.asyncio
async def test_auth_accepts_correct_credentials(auth_client):
    """Requests with valid credentials pass through."""
    resp = await auth_client.get(
        "/api/config", auth=("myuser", "mypass")
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Auth App"


@pytest.mark.asyncio
async def test_auth_rejects_wrong_credentials(auth_client):
    """Requests with bad credentials get 401."""
    resp = await auth_client.get(
        "/api/config", auth=("myuser", "wrong")
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_no_auth_still_works(client):
    """When auth is not configured, requests pass without credentials."""
    resp = await client.get("/api/config")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_auth_default_username(workspace, mock_agent):
    """When only password is set, username defaults to 'admin'."""
    config = AppConfig(
        workspace=workspace,
        auth_password="secret",
    )
    app = create_fastapi_app(
        agent=mock_agent,
        workspace=workspace,
        config=config,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # admin/secret should work
        resp = await c.get("/api/config", auth=("admin", "secret"))
        assert resp.status_code == 200
        # wrong username should fail
        resp = await c.get("/api/config", auth=("user", "secret"))
        assert resp.status_code == 401
