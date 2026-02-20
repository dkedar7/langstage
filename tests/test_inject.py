"""Tests for session REST endpoints (inject + list)."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from httpx import AsyncClient, ASGITransport

from cowork_dash.config import AppConfig
from cowork_dash.server.main import create_fastapi_app
from cowork_dash.stream.session_manager import AgentSession


@pytest.fixture
def workspace(tmp_path):
    return tmp_path


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.checkpointer = MagicMock()
    return agent


@pytest.fixture
def app(workspace, mock_agent):
    config = AppConfig(workspace=workspace)
    return create_fastapi_app(agent=mock_agent, workspace=workspace, config=config)


@pytest.mark.asyncio
async def test_inject_session_not_found(app):
    """POST inject with nonexistent session returns 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post(
            "/api/session/nonexistent/inject",
            json={"content": "hello"},
        )
    assert resp.status_code == 404
    assert "Session not found" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_inject_no_browser_connected(app):
    """POST inject when session exists but no WS connected returns 409."""
    mgr = app.state.session_manager
    # Create session without linking a websocket
    session = AgentSession()
    mgr._sessions[session.thread_id] = session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post(
            f"/api/session/{session.thread_id}/inject",
            json={"content": "hello"},
        )
    assert resp.status_code == 409
    assert "No browser connected" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_inject_returns_202(app):
    """POST inject with valid session + connected WS returns 202."""
    mgr = app.state.session_manager
    session = AgentSession()
    ws_mock = AsyncMock()
    mgr._sessions[session.thread_id] = session
    mgr._session_to_ws[session.thread_id] = ws_mock

    with patch("cowork_dash.server.routes_session.run_injected_message", new_callable=AsyncMock):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/session/{session.thread_id}/inject",
                json={"content": "hello from outside"},
            )

    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["session_id"] == session.thread_id

    # Verify user_message was sent to the websocket
    ws_mock.send_json.assert_called_once_with({
        "type": "user_message",
        "content": "hello from outside",
    })


@pytest.mark.asyncio
async def test_inject_missing_content(app):
    """POST inject without content field returns 422."""
    mgr = app.state.session_manager
    session = AgentSession()
    ws_mock = AsyncMock()
    mgr._sessions[session.thread_id] = session
    mgr._session_to_ws[session.thread_id] = ws_mock

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post(
            f"/api/session/{session.thread_id}/inject",
            json={},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_sessions_empty(app):
    """GET /api/sessions with no sessions returns empty list."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/sessions")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_sessions_with_connected(app):
    """GET /api/sessions shows sessions with connection status."""
    mgr = app.state.session_manager
    session = AgentSession()
    ws_mock = AsyncMock()
    mgr._sessions[session.thread_id] = session
    mgr._session_to_ws[session.thread_id] = ws_mock

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["session_id"] == session.thread_id
    assert data[0]["connected"] is True


@pytest.mark.asyncio
async def test_list_sessions_disconnected(app):
    """GET /api/sessions shows disconnected sessions."""
    mgr = app.state.session_manager
    session = AgentSession()
    mgr._sessions[session.thread_id] = session
    # No entry in _session_to_ws → disconnected

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["session_id"] == session.thread_id
    assert data[0]["connected"] is False
