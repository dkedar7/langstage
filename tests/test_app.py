"""Tests for the FastAPI app and REST endpoints."""

import pytest
from unittest.mock import MagicMock, AsyncMock
from pathlib import Path
from httpx import AsyncClient, ASGITransport

from langstage.config import AppConfig
from langstage.server.main import create_fastapi_app


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
        workspace_root=workspace,
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
async def test_files_read_path_escape_returns_400_not_500(client):
    # A path that escapes the workspace must be rejected cleanly. The boundary
    # holds either way (no traversal), but the path-escape ValueError used to
    # propagate uncaught -> 500 instead of the 400 the sibling cases return.
    resp = await client.get("/api/files/read?path=/../../../../etc/passwd")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_files_tree_path_escape_returns_400_not_500(client):
    resp = await client.get("/api/files/tree?path=/../../../..")
    assert resp.status_code == 400


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
        workspace_root=workspace,
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
        workspace_root=workspace,
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


# ── /api/files/upload path semantics (gh #75) ───────────────────────────────


@pytest.mark.asyncio
async def test_upload_path_is_the_full_destination_and_round_trips(client):
    # gh #75: upload?path=P must store the file AT P (symmetric with read/download/delete),
    # so a `path`-symmetric client's upload->read round-trips. Previously `path` was treated
    # as a parent dir and the file landed at P/<filename>, silently creating a directory P.
    up = await client.post(
        "/api/files/upload?path=reports/q3.md",
        files={"file": ("rt.txt", b"roundtrip", "text/plain")},
    )
    assert up.status_code == 200, up.text
    assert up.json()["path"] == "reports/q3.md"  # stored AS the file, not reports/q3.md/rt.txt

    got = await client.get("/api/files/read?path=reports/q3.md")
    assert got.status_code == 200, got.text
    assert got.json()["content"] == "roundtrip"


@pytest.mark.asyncio
async def test_upload_into_an_existing_directory_appends_filename(client):
    # Backward-compat: the file-browser UI uploads into the directory being viewed (an
    # existing dir, no trailing slash). That must still drop the file INTO it.
    up = await client.post(
        "/api/files/upload?path=subdir",  # subdir exists in the workspace fixture
        files={"file": ("note.txt", b"hi", "text/plain")},
    )
    assert up.status_code == 200, up.text
    assert up.json()["path"] == "subdir/note.txt"

    got = await client.get("/api/files/read?path=subdir/note.txt")
    assert got.status_code == 200 and got.json()["content"] == "hi"


@pytest.mark.asyncio
async def test_upload_trailing_slash_forces_directory_drop(client):
    # A trailing '/' explicitly means "drop into this directory under the multipart
    # filename", even when the directory doesn't exist yet.
    up = await client.post(
        "/api/files/upload?path=fresh/",
        files={"file": ("a.txt", b"abc", "text/plain")},
    )
    assert up.status_code == 200, up.text
    assert up.json()["path"] == "fresh/a.txt"


@pytest.mark.asyncio
async def test_upload_path_escape_returns_400(client):
    # The workspace boundary still holds for uploads.
    up = await client.post(
        "/api/files/upload?path=../escapee.txt",
        files={"file": ("x.txt", b"x", "text/plain")},
    )
    assert up.status_code == 400


# ── /api/files/delete: path query param + DELETE verb (gh #81) ───────────────


@pytest.mark.asyncio
async def test_delete_query_param_round_trips_with_upload(client):
    # gh #81: the README promises delete?path=P round-trips with upload?path=P.
    up = await client.post(
        "/api/files/upload?path=del/a.txt",
        files={"file": ("a.txt", b"bye", "text/plain")},
    )
    assert up.status_code == 200, up.text
    # DELETE verb + query param — the natural REST shape the docs imply.
    d = await client.delete("/api/files/delete?path=del/a.txt")
    assert d.status_code == 200, d.text
    assert d.json()["path"] == "del/a.txt"
    assert (await client.get("/api/files/read?path=del/a.txt")).status_code == 404


@pytest.mark.asyncio
async def test_delete_post_with_query_param(client):
    # POST + query param (mirroring upload?path=) also works.
    await client.post(
        "/api/files/upload?path=del/b.txt",
        files={"file": ("b.txt", b"x", "text/plain")},
    )
    d = await client.post("/api/files/delete?path=del/b.txt")
    assert d.status_code == 200, d.text
    assert (await client.get("/api/files/read?path=del/b.txt")).status_code == 404


@pytest.mark.asyncio
async def test_delete_post_json_body_still_works(client):
    # Back-compat: the file-browser UI posts a JSON body {"path": ...}.
    await client.post(
        "/api/files/upload?path=del/c.txt",
        files={"file": ("c.txt", b"x", "text/plain")},
    )
    d = await client.post("/api/files/delete", json={"path": "del/c.txt"})
    assert d.status_code == 200, d.text
    assert (await client.get("/api/files/read?path=del/c.txt")).status_code == 404


@pytest.mark.asyncio
async def test_delete_without_path_returns_422(client):
    d = await client.post("/api/files/delete")
    assert d.status_code == 422


@pytest.mark.asyncio
async def test_delete_missing_file_returns_404(client):
    d = await client.delete("/api/files/delete?path=nope/missing.txt")
    assert d.status_code == 404
