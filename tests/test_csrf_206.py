"""gh #206: a cross-site HTML form POST must not change the workspace.

CORS only stops a foreign page reading the response. A ``<form>`` POST with a
query-string, urlencoded, multipart or text/plain body is a CORS "simple
request" -- no preflight -- so the route used to run before CORS mattered. The
server now refuses every unsafe-method request a browser marks as coming from a
site the user didn't allow, and lets same-origin pages, allowed CORS origins and
header-less clients (curl, scripts, the CLI) through.
"""

import base64

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import MagicMock

from langstage.config import AppConfig
from langstage.server.main import create_fastapi_app

EVIL = {"Origin": "http://evil.example"}
EVIL_FETCH = {"Origin": "http://evil.example", "Sec-Fetch-Site": "cross-site"}
FORM = {"Content-Type": "application/x-www-form-urlencoded"}


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "notes.md").write_text("important")
    deep = tmp_path / "sub" / "deep"
    deep.mkdir(parents=True)
    (deep / "a.txt").write_text("a")
    return tmp_path


def _app(workspace, **cfg):
    agent = MagicMock()
    agent.checkpointer = MagicMock()
    config = AppConfig(workspace_root=workspace, **cfg)
    return create_fastapi_app(agent=agent, workspace=workspace, config=config)


async def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:18711")


# ── the issue's repros: refused, nothing changes ─────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [EVIL, EVIL_FETCH, {"Sec-Fetch-Site": "cross-site"}])
async def test_cross_site_form_delete_is_refused_and_file_survives(workspace, headers):
    async with await _client(_app(workspace)) as c:
        resp = await c.post("/api/files/delete?path=notes.md", headers={**headers, **FORM})
    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith("application/json")
    assert "Cross-site request refused" in resp.json()["detail"]
    assert (workspace / "notes.md").read_text() == "important"


@pytest.mark.asyncio
async def test_cross_site_recursive_delete_is_refused(workspace):
    async with await _client(_app(workspace)) as c:
        resp = await c.post("/api/files/delete?path=sub", headers=EVIL)
    assert resp.status_code == 403
    assert (workspace / "sub" / "deep" / "a.txt").exists()


@pytest.mark.asyncio
async def test_cross_site_multipart_upload_cannot_overwrite(workspace):
    async with await _client(_app(workspace)) as c:
        resp = await c.post(
            "/api/files/upload?path=notes.md",
            headers=EVIL_FETCH,
            files={"file": ("p.txt", b"overwritten")},
        )
    assert resp.status_code == 403
    assert (workspace / "notes.md").read_text() == "important"


@pytest.mark.asyncio
async def test_cross_site_text_plain_mkdir_is_refused(workspace):
    async with await _client(_app(workspace)) as c:
        resp = await c.post(
            "/api/files/mkdir?path=evil_dir",
            headers={**EVIL, "Content-Type": "text/plain"},
        )
    assert resp.status_code == 403
    assert not (workspace / "evil_dir").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,url",
    [
        ("POST", "/api/files/upload?path=x.txt"),
        ("POST", "/api/files/delete?path=notes.md"),
        ("DELETE", "/api/files/delete?path=notes.md"),
        ("POST", "/api/files/mkdir?path=d"),
        ("DELETE", "/api/canvas/items/abc"),
        ("DELETE", "/api/canvas/items"),
        ("POST", "/api/chat"),
        ("POST", "/api/chat/interrupt"),
        ("POST", "/api/chat/cancel"),
        ("DELETE", "/api/session/s1"),
        ("POST", "/api/session/s1/inject"),
        ("POST", "/api/tasks"),
        ("POST", "/api/tasks/t1/cancel"),
        ("POST", "/api/tasks/t1/retry"),
        ("POST", "/api/tasks/t1/resume"),
        ("POST", "/api/tasks/t1/message"),
        ("POST", "/api/cron"),
        ("DELETE", "/api/cron/j1"),
        ("POST", "/api/cron/j1/run"),
        ("PUT", "/api/files/delete?path=notes.md"),
        ("PATCH", "/api/files/delete?path=notes.md"),
    ],
)
async def test_every_unsafe_route_refuses_a_cross_site_request(workspace, method, url):
    # Not route by route: the guard runs before routing, so every state-changing
    # route (and any added later) gets a 403 rather than its own 2xx/404/405/422.
    async with await _client(_app(workspace)) as c:
        resp = await c.request(method, url, headers={**EVIL_FETCH, "Content-Type": "text/plain"})
    assert resp.status_code == 403, (method, url, resp.status_code)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin", ["null", "http://localhost.evil.example", "http://evil.example:18711"]
)
async def test_lookalike_and_null_origins_are_refused(workspace, origin):
    async with await _client(_app(workspace)) as c:
        resp = await c.post("/api/files/delete?path=notes.md", headers={"Origin": origin})
    assert resp.status_code == 403
    assert (workspace / "notes.md").exists()


@pytest.mark.asyncio
async def test_same_site_without_an_allowed_origin_is_refused(workspace):
    # e.g. another app on a sibling subdomain / port: same-site is not same-origin.
    async with await _client(_app(workspace)) as c:
        resp = await c.post("/api/files/delete?path=notes.md", headers={"Sec-Fetch-Site": "same-site"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cross_site_is_refused_under_basic_auth_even_with_credentials(workspace):
    # A browser replays cached Basic credentials on a cross-site form POST.
    app = _app(workspace, auth_username="u", auth_password="p")
    token = base64.b64encode(b"u:p").decode()
    async with await _client(app) as c:
        resp = await c.post(
            "/api/files/delete?path=notes.md",
            headers={**EVIL_FETCH, "Authorization": f"Basic {token}"},
        )
        assert resp.status_code == 403
        assert (workspace / "notes.md").exists()
        ok = await c.post(
            "/api/files/delete?path=notes.md", headers={"Authorization": f"Basic {token}"}
        )
        assert ok.status_code == 200


# ── what must keep working ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_header_less_clients_still_work(workspace):
    # curl / scripts / the CLI send neither Origin nor Sec-Fetch-Site.
    async with await _client(_app(workspace)) as c:
        assert (await c.post("/api/files/mkdir?path=made")).status_code == 200
        up = await c.post("/api/files/upload?path=up.txt", files={"file": ("up.txt", b"x")})
        assert up.status_code == 200
        assert (await c.post("/api/files/delete?path=notes.md")).status_code == 200
    assert (workspace / "made").is_dir()
    assert (workspace / "up.txt").read_text() == "x"
    assert not (workspace / "notes.md").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        # The SPA served by this server: Origin matches Host.
        {"Origin": "http://localhost:18711", "Sec-Fetch-Site": "same-origin"},
        {"Origin": "http://localhost:18711"},
        # Same-origin attested by the browser, Host rewritten by a reverse proxy.
        {"Origin": "https://lang.example", "Sec-Fetch-Site": "same-origin"},
        # Loopback origins are allowed by the default CORS policy (Vite dev server).
        {"Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-site"},
        {"Origin": "http://127.0.0.1:18711", "Sec-Fetch-Site": "cross-site"},
    ],
)
async def test_same_origin_and_loopback_requests_still_work(workspace, headers):
    async with await _client(_app(workspace)) as c:
        resp = await c.post("/api/files/delete?path=notes.md", headers=headers)
    assert resp.status_code == 200
    assert not (workspace / "notes.md").exists()


@pytest.mark.asyncio
async def test_explicitly_allowed_cors_origin_still_works(workspace):
    app = _app(workspace, cors_origins="https://ok.example")
    async with await _client(app) as c:
        ok = await c.post(
            "/api/files/delete?path=notes.md",
            headers={"Origin": "https://ok.example", "Sec-Fetch-Site": "cross-site"},
        )
        assert ok.status_code == 200
        assert ok.headers.get("access-control-allow-origin") == "https://ok.example"
        # Only the listed origin: another site is still refused.
        bad = await c.post("/api/files/mkdir?path=d", headers=EVIL_FETCH)
        assert bad.status_code == 403


@pytest.mark.asyncio
async def test_wildcard_cors_opt_in_allows_any_origin(workspace):
    # `*` already lets any site fetch() any route (no auth by default), so the
    # guard honors the same explicit opt-in rather than contradicting it.
    app = _app(workspace, cors_origins="*")
    async with await _client(app) as c:
        resp = await c.post("/api/files/delete?path=notes.md", headers=EVIL_FETCH)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_safe_methods_are_unaffected_cross_site(workspace):
    async with await _client(_app(workspace)) as c:
        tree = await c.get("/api/files/tree", headers=EVIL_FETCH)
        assert tree.status_code == 200
        assert tree.headers.get("access-control-allow-origin") is None  # #113 holds
        assert (await c.get("/api/health", headers=EVIL_FETCH)).status_code == 200
        pre = await c.options(
            "/api/files/delete",
            headers={**EVIL, "Access-Control-Request-Method": "POST"},
        )
        # Preflights are still answered by CORS (and still refuse the foreign site).
        assert pre.headers.get("access-control-allow-origin") != "http://evil.example"
