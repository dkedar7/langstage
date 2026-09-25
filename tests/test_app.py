"""Tests for the FastAPI app and REST endpoints."""

import pytest
from unittest.mock import MagicMock, AsyncMock
from pathlib import Path
from httpx import AsyncClient, ASGITransport

from langstage.app import _exposure_warning, _is_loopback_host
from langstage.config import AppConfig
from langstage.server.main import create_fastapi_app
from langstage.server.middleware import _resolve_cors


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
async def test_files_tree_on_a_file_returns_400_not_500(client):
    # gh #117: /tree on a FILE (not a directory) used to raise an uncaught
    # NotADirectoryError -> 500, the only files route that leaked a 500 for a
    # wrong node type. It must now return a clean 4xx, mirroring read/preview's
    # IsADirectoryError -> 400 for the inverse case.
    resp = await client.get("/api/files/tree?path=/hello.py")
    assert resp.status_code == 400, f"got {resp.status_code}: {resp.text}"
    assert "hello.py" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_files_tree_on_a_nested_file_returns_400_not_500(client):
    # Same defect for a nested file path (subdir/nested.txt exists in the fixture).
    resp = await client.get("/api/files/tree?path=subdir/nested.txt")
    assert resp.status_code == 400, f"got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_files_download_on_a_directory_returns_400_not_false_404(client):
    # gh #124: download of a DIRECTORY that exists (subdir/ in the fixture) used to
    # return a misleading 404 "File not found", telling a client an existing path does
    # not exist. It must now return a clean 400 "Path is a directory", matching
    # read/preview for the same node-type case (and the #117 tree-on-a-file fix).
    resp = await client.get("/api/files/download?path=subdir")
    assert resp.status_code == 400, f"got {resp.status_code}: {resp.text}"
    assert "directory" in resp.json()["detail"].lower()
    assert "subdir" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_files_download_missing_path_still_404(client):
    # A path that truly doesn't exist must STILL be a 404 — the fix distinguishes
    # is-a-directory from doesn't-exist, it doesn't collapse them the other way.
    resp = await client.get("/api/files/download?path=nope.txt")
    assert resp.status_code == 404, f"got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_files_download_serves_a_real_file(client):
    # The happy path is unaffected: an existing file downloads with 200.
    resp = await client.get("/api/files/download?path=hello.py")
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.text}"
    assert resp.text == "print('hello')"


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


@pytest.mark.asyncio
async def test_delete_session_frees_its_notebook(client):
    """Deleting a session drops its per-session notebook state (gh #157)."""
    from langstage import tools

    tools.get_notebook_state("doomed-session").add_cell("x = 1")
    assert "doomed-session" in tools._session_notebook_states
    resp = await client.delete("/api/session/doomed-session")
    assert resp.status_code == 200
    assert "doomed-session" not in tools._session_notebook_states


# ── CORS is loopback-only by default, not reflect-any-origin (gh #113) ────────
# The server used to attach CORSMiddleware with allow_origins=["*"] +
# allow_credentials=True, which Starlette turns into "reflect ANY origin + allow
# credentials" — so any website the user visited could make credentialed
# cross-origin requests to their local server and read the responses (read/write the
# workspace, drive the agent). CORS is now loopback-only by default, with an explicit
# LANGSTAGE_CORS_ORIGINS opt-in.


@pytest.mark.asyncio
async def test_cors_does_not_reflect_a_random_site_with_credentials(client):
    # The core of the fix: a drive-by origin must NOT be handed
    # access-control-allow-origin for itself (which, with credentials, would let it
    # read the response cross-origin).
    resp = await client.get("/api/config", headers={"Origin": "https://evil.example"})
    assert resp.status_code == 200  # the request itself still succeeds server-side...
    # ...but the browser gets no grant to read it cross-origin.
    assert resp.headers.get("access-control-allow-origin") != "https://evil.example"
    assert resp.headers.get("access-control-allow-origin") is None


@pytest.mark.asyncio
async def test_cors_does_not_reflect_the_null_origin(client):
    # The `null` origin (sandboxed iframe / file://) was reflected too — also closed.
    resp = await client.get("/api/config", headers={"Origin": "null"})
    assert resp.headers.get("access-control-allow-origin") is None


@pytest.mark.asyncio
async def test_cors_preflight_delete_from_random_site_is_not_granted(client):
    # A state-changing preflight (DELETE) from a hostile origin must not be allowed.
    resp = await client.options(
        "/api/files/delete",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "DELETE",
        },
    )
    assert resp.headers.get("access-control-allow-origin") != "https://evil.example"


@pytest.mark.asyncio
async def test_cors_allows_credentialed_access_from_loopback_spa(client):
    # The same-origin SPA / a local Vite dev server (http://localhost:<port>) is a
    # loopback origin and DOES get credentialed CORS, so the local UI keeps working.
    origin = "http://localhost:5173"
    resp = await client.get("/api/config", headers={"Origin": origin})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == origin
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_resolve_cors_default_is_loopback_regex_with_credentials():
    cfg = _resolve_cors(None)
    assert "allow_origin_regex" in cfg  # loopback-only, not a "*" allow-list
    assert cfg["allow_credentials"] is True
    assert cfg.get("allow_origins") != ["*"]


def test_resolve_cors_env_opt_in_honors_specific_origins_with_credentials():
    cfg = _resolve_cors("https://a.example, https://b.example")
    assert cfg["allow_origins"] == ["https://a.example", "https://b.example"]
    assert cfg["allow_credentials"] is True
    assert "allow_origin_regex" not in cfg


def test_resolve_cors_wildcard_opt_in_forces_credentials_off():
    # If a user opts into "*", it can only ship with credentials OFF (browser rule +
    # the reflect-any-origin anti-pattern this fix exists to prevent).
    cfg = _resolve_cors("*")
    assert cfg["allow_origins"] == ["*"]
    assert cfg["allow_credentials"] is False


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


# ── non-loopback host + no auth exposure warning (gh #89) ────────────────────


@pytest.mark.parametrize(
    "host",
    ["localhost", "127.0.0.1", "127.0.0.2", "::1", "[::1]", None, "",
     "LOCALHOST", "  localhost  "],
)
def test_is_loopback_host_true(host):
    assert _is_loopback_host(host) is True


@pytest.mark.parametrize(
    "host",
    ["0.0.0.0", "::", "192.168.1.10", "10.0.0.5", "myserver.internal", "example.com"],
)
def test_is_loopback_host_false(host):
    assert _is_loopback_host(host) is False


def test_exposure_warning_fires_for_non_loopback_without_auth():
    """The dangerous default: a network-reachable bind with no password. The
    warning must name the host and point at the fix."""
    msg = _exposure_warning("0.0.0.0", "")
    assert msg is not None
    assert "0.0.0.0" in msg
    assert "auth" in msg.lower()
    assert "--auth-password" in msg or "LANGSTAGE_AUTH_PASSWORD" in msg


def test_exposure_warning_silent_when_auth_set():
    """A password closes the hole — no warning even on 0.0.0.0."""
    assert _exposure_warning("0.0.0.0", "hunter2") is None


def test_exposure_warning_silent_on_loopback():
    """The safe, default case (localhost) never warns, with or without auth."""
    assert _exposure_warning("localhost", "") is None
    assert _exposure_warning("127.0.0.1", "") is None
    assert _exposure_warning(None, "") is None


def _make_run_app(workspace, mock_agent, monkeypatch, host):
    """Build a CoworkApp whose run() won't bind a socket or move the process cwd."""
    import langstage.app as app_mod
    from langstage.app import CoworkApp

    monkeypatch.setattr(app_mod.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(app_mod.CoworkApp, "_enter_workspace", lambda self: None)
    return CoworkApp(agent=mock_agent, workspace=workspace, host=host, port=8050,
                     title="T", agent_name="A", show_canvas=False, show_files=False)


def test_run_prints_exposure_warning_to_stderr(workspace, mock_agent, monkeypatch, capsys):
    """End-to-end: run() on 0.0.0.0 with no auth prints the warning (to stderr) and
    still starts the server (warn-but-start). uvicorn is stubbed so nothing binds."""
    app = _make_run_app(workspace, mock_agent, monkeypatch, host="0.0.0.0")
    app.run(open_browser=False)
    err = capsys.readouterr().err
    # Assert the exposure warning specifically. run() emits more than one kind of
    # startup WARNING since gh #96 (the missing-frontend notice is the other), so a
    # bare "WARNING" substring no longer identifies which one fired.
    assert "no authentication" in err
    assert "0.0.0.0" in err


def test_run_no_warning_on_localhost(workspace, mock_agent, monkeypatch, capsys):
    """The default localhost bind must not print the exposure warning."""
    app = _make_run_app(workspace, mock_agent, monkeypatch, host="localhost")
    app.run(open_browser=False)
    err = capsys.readouterr().err
    # Scoped to the exposure warning — the missing-frontend warning (gh #96) is a
    # separate condition with its own coverage in tests/test_frontend_visibility.py,
    # and legitimately fires here because a source checkout has no built SPA.
    assert "no authentication" not in err


# ── /api/files/read: faithful text, clean binary refusal (gh #144) ───────────


@pytest.mark.asyncio
async def test_files_read_preserves_crlf_and_byte_size(client, workspace):
    (workspace / "c.txt").write_bytes(b"line1\r\nline2\r\n")
    resp = await client.get("/api/files/read?path=c.txt")
    assert resp.status_code == 200
    body = resp.json()
    assert body["content"] == "line1\r\nline2\r\n"
    assert body["size"] == 14


@pytest.mark.asyncio
async def test_files_read_refuses_binary_with_415(client, workspace):
    (workspace / "t.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    resp = await client.get("/api/files/read?path=t.png")
    assert resp.status_code == 415
    detail = resp.json()["detail"]
    assert "preview" in detail and "download" in detail


# ── /api/canvas/items serves real canvas items (gh #158) ─────────────────────


@pytest.mark.asyncio
async def test_canvas_items_lists_items_written_by_the_real_tools(client, workspace, monkeypatch):
    from langstage import config as cfg, tools as tools_mod

    monkeypatch.setattr(cfg, "WORKSPACE_ROOT", workspace)
    monkeypatch.setattr(cfg, "VIRTUAL_FS", False)
    monkeypatch.setattr(tools_mod, "WORKSPACE_ROOT", workspace)
    monkeypatch.setattr(tools_mod, "VIRTUAL_FS", False)
    # CanvasMiddleware's prompt: open with a section + an overview markdown item.
    tools_mod.add_canvas_section("Overview")
    tools_mod.add_to_canvas("This report analyzes Q3 sales.")
    tools_mod.add_to_canvas("<b>bold html</b>")

    resp = await client.get("/api/canvas/items")
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert [i["type"] for i in items][:1] == ["section"]
    assert items[0]["data"] == "Overview" and items[0]["level"] == 1
    assert any(i["data"] == "This report analyzes Q3 sales." for i in items)
    # No title was given, so none is invented (and it isn't serialized as null).
    assert all("title" not in i for i in items)


def test_canvas_item_schema_matches_real_items():
    from langstage.server.models import CanvasItemResponse

    schema = CanvasItemResponse.model_json_schema()
    assert set(schema["required"]) == {"id", "type"}
    assert "type" not in schema["properties"]["data"]  # any JSON value
    assert "level" in schema["properties"]


# ── CORS preflight works with Basic auth on (gh #155) ────────────────────────


@pytest.mark.asyncio
async def test_cors_preflight_is_answered_under_auth(auth_client):
    origin = "http://localhost:5173"
    resp = await auth_client.options(
        "/api/config",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("access-control-allow-origin") == origin


@pytest.mark.asyncio
async def test_cors_preflight_under_auth_still_refuses_a_foreign_origin(auth_client):
    resp = await auth_client.options(
        "/api/config",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert resp.status_code != 200
    assert resp.headers.get("access-control-allow-origin") is None


@pytest.mark.asyncio
async def test_non_preflight_options_still_requires_auth(auth_client):
    # Only a real CORS preflight skips auth; a bare OPTIONS is authenticated.
    resp = await auth_client.options("/api/config")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_real_cross_origin_request_under_auth_still_needs_credentials(auth_client):
    origin = "http://localhost:5173"
    resp = await auth_client.get("/api/config", headers={"Origin": origin})
    assert resp.status_code == 401
    ok = await auth_client.get("/api/config", headers={"Origin": origin}, auth=("myuser", "mypass"))
    assert ok.status_code == 200
    assert ok.headers.get("access-control-allow-origin") == origin


def test_auth_covers_websocket_upgrades(auth_app):
    """The middleware's docstring promised WebSocket upgrades are authenticated, but
    every non-http scope was passed straight through. No WS route ships today; pin it
    with a throwaway one so a future route can't be reached without credentials."""
    import base64

    from starlette.testclient import TestClient
    from starlette.websockets import WebSocket, WebSocketDisconnect

    async def echo(ws: WebSocket):
        await ws.accept()
        await ws.send_text("hi")
        await ws.close()

    auth_app.add_api_websocket_route("/ws-probe", echo)
    client = TestClient(auth_app)
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect("/ws-probe") as ws:
            ws.receive_text()
    assert refused.value.code == 1008
    token = base64.b64encode(b"myuser:mypass").decode()
    with client.websocket_connect("/ws-probe", headers={"Authorization": f"Basic {token}"}) as ws:
        assert ws.receive_text() == "hi"


# ── gh #141: LANGSTAGE_CORS_ORIGINS goes through the config layer ────────────


def test_cors_origins_is_a_resolved_config_field(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LANGSTAGE_CORS_ORIGINS", "https://a.example")
    cfg = AppConfig.resolve()
    assert cfg.cors_origins == "https://a.example"
    assert "cors_origins" in cfg.describe()


def test_cors_origins_from_toml(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LANGSTAGE_CORS_ORIGINS", raising=False)
    (tmp_path / "langstage.toml").write_text('[server]\ncors_origins = "https://t.example"\n')
    assert AppConfig.resolve().cors_origins == "https://t.example"


@pytest.mark.asyncio
async def test_server_enforces_the_resolved_cors_origins(workspace, mock_agent, monkeypatch):
    # What the server grants is what the config says, not a side-channel env read.
    monkeypatch.delenv("LANGSTAGE_CORS_ORIGINS", raising=False)
    config = AppConfig(workspace_root=workspace, cors_origins="https://ok.example")
    app = create_fastapi_app(agent=mock_agent, workspace=workspace, config=config)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/config", headers={"Origin": "https://ok.example"})
        assert resp.headers.get("access-control-allow-origin") == "https://ok.example"


@pytest.mark.asyncio
async def test_raw_env_no_longer_bypasses_the_config(workspace, mock_agent, monkeypatch):
    # A config built without the origin (e.g. an explicit Python override) wins:
    # the middleware no longer re-reads os.environ behind the config's back.
    monkeypatch.setenv("LANGSTAGE_CORS_ORIGINS", "https://evil.example")
    config = AppConfig(workspace_root=workspace)
    app = create_fastapi_app(agent=mock_agent, workspace=workspace, config=config)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/config", headers={"Origin": "https://evil.example"})
        assert resp.headers.get("access-control-allow-origin") is None


def test_resolve_cors_accepts_a_toml_list():
    cfg = _resolve_cors(["https://a.example", "https://b.example"])
    assert cfg["allow_origins"] == ["https://a.example", "https://b.example"]


# ── gh #159: mkdir accepts ?path= as well as a JSON body ─────────────────────


@pytest.mark.asyncio
async def test_mkdir_accepts_query_path(client, workspace):
    resp = await client.post("/api/files/mkdir?path=reports")
    assert resp.status_code == 200, resp.text
    assert (workspace / "reports").is_dir()


@pytest.mark.asyncio
async def test_mkdir_still_accepts_json_body(client, workspace):
    resp = await client.post("/api/files/mkdir", json={"path": "bodydir"})
    assert resp.status_code == 200, resp.text
    assert (workspace / "bodydir").is_dir()


@pytest.mark.asyncio
async def test_mkdir_without_path_is_422(client):
    resp = await client.post("/api/files/mkdir")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_openapi_mkdir_documents_query_path(client):
    spec = (await client.get("/openapi.json")).json()
    op = spec["paths"]["/api/files/mkdir"]["post"]
    assert any(p["name"] == "path" and p["in"] == "query" for p in op.get("parameters", []))
    assert not op.get("requestBody", {}).get("required", False)


# ── gh #135 / #162: response schemas carry the runtime fields ────────────────


@pytest.mark.asyncio
async def test_openapi_cronjob_has_last_run_state(client):
    spec = (await client.get("/openapi.json")).json()
    assert "last_run_state" in spec["components"]["schemas"]["CronJob"]["properties"]


@pytest.mark.asyncio
async def test_openapi_filepreview_has_variant_fields(client):
    spec = (await client.get("/openapi.json")).json()
    props = spec["components"]["schemas"]["FilePreview"]["properties"]
    for key in ("headers", "rows", "download_url", "mime"):
        assert key in props, key


@pytest.mark.asyncio
async def test_csv_preview_body_unchanged_by_the_schema(client):
    body = (await client.get("/api/files/preview?path=data.csv")).json()
    assert body["headers"] == ["a", "b"]
    assert body["rows"] == [{"a": "1", "b": "2"}]
    assert "download_url" not in body and "mime" not in body  # unset optionals stay out
