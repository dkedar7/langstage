"""gh #208: a loopback-bound server refuses requests whose Host isn't a local name.

DNS rebinding points a hostile site's name at 127.0.0.1: the browser then treats the
local server as same-origin with that site, so the #206 cross-site guard can't tell,
and the page can read responses too. The Host header still carries the hostile name.
"""

import socket
import threading
import time
from unittest.mock import MagicMock

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from langstage.config import AppConfig
from langstage.server.main import create_fastapi_app
from langstage.server.middleware import add_middleware, is_loopback_host


def _guarded(bind_host="127.0.0.1", allowed_hosts=""):
    app = FastAPI()

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    @app.post("/api/write")
    def write():
        return {"ok": True}

    add_middleware(app, bind_host=bind_host, allowed_hosts=allowed_hosts)
    return app


async def _status(app, host, server=("127.0.0.1", 8050), method="GET", path="/api/ping"):
    """One request through the ASGI app with an exact Host header and socket address."""
    headers = [] if host is None else [(b"host", host.encode())]
    scope = {"type": "http", "method": method, "path": path, "raw_path": path.encode(),
             "query_string": b"", "headers": headers, "server": server, "client": ("127.0.0.1", 1),
             "scheme": "http", "http_version": "1.1", "root_path": ""}
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        sent.append(msg)

    await app(scope, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, body.decode()


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["localhost:8050", "127.0.0.1:8050", "[::1]:8050", "LOCALHOST",
                                  "app.localhost:8050", "127.0.0.2"])
async def test_local_names_pass(host):
    assert (await _status(_guarded(), host))[0] == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", [("GET", "/api/ping"), ("POST", "/api/write")])
async def test_rebound_host_is_refused_for_every_method(method, path):
    status, body = await _status(_guarded(), "evil.example:8050", method=method, path=path)
    assert status == 403
    assert "evil.example" in body and "allowed_hosts" in body and "LANGSTAGE_ALLOWED_HOSTS" in body


@pytest.mark.asyncio
async def test_allowed_hosts_and_star():
    app = _guarded(allowed_hosts="docs.example.org, Other.Example")
    assert (await _status(app, "docs.example.org"))[0] == 200
    assert (await _status(app, "other.example:443"))[0] == 200
    assert (await _status(app, "evil.example"))[0] == 403
    assert (await _status(_guarded(allowed_hosts=["docs.example.org"]), "docs.example.org"))[0] == 200
    assert (await _status(_guarded(allowed_hosts="*"), "evil.example"))[0] == 200


@pytest.mark.asyncio
async def test_wildcard_matches_subdomains_like_codraft():
    """One langstage.toml serves both stages, so `*.example.org` means the same in each."""
    app = _guarded(allowed_hosts=["*.example.org"])
    assert (await _status(app, "docs.example.org:443"))[0] == 200
    assert (await _status(app, "a.b.example.org"))[0] == 200
    assert (await _status(app, "example.org"))[0] == 403
    assert (await _status(app, "evilexample.org"))[0] == 403


@pytest.mark.asyncio
async def test_only_loopback_binds_and_connections_are_checked():
    # A public bind is unchanged (it is documented as needing auth).
    assert (await _status(_guarded(bind_host="0.0.0.0"), "evil.example"))[0] == 200
    # The bind host itself is always allowed.
    assert (await _status(_guarded(bind_host="127.0.0.1"), "127.0.0.1:9000"))[0] == 200
    # No loopback socket (an in-process test client) or no Host header: nothing to check.
    assert (await _status(_guarded(), "evil.example", server=None))[0] == 200
    assert (await _status(_guarded(), "evil.example", server=("testserver", 80)))[0] == 200
    assert (await _status(_guarded(), None))[0] == 200


def test_is_loopback_host():
    for h in ("localhost", "127.0.0.1", "::1", "[::1]", "127.1.2.3", "x.localhost"):
        assert is_loopback_host(h), h
    for h in ("0.0.0.0", "192.168.1.5", "example.org", "", "testserver"):
        assert not is_loopback_host(h), h


def test_allowed_hosts_resolves_from_env_and_toml(tmp_path, monkeypatch):
    monkeypatch.setenv("LANGSTAGE_ALLOWED_HOSTS", "a.example,b.example")
    cfg = AppConfig.resolve(use_toml=False)
    assert cfg.allowed_hosts == "a.example,b.example"
    assert cfg.sources["allowed_hosts"].startswith("env")
    monkeypatch.delenv("LANGSTAGE_ALLOWED_HOSTS")
    (tmp_path / "langstage.toml").write_text('[server]\nallowed_hosts = "docs.example.org"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    cfg = AppConfig.resolve()
    assert cfg.allowed_hosts == "docs.example.org"
    assert "allowed_hosts" in cfg.describe()


@pytest.mark.asyncio
async def test_the_app_refuses_a_rebound_host(tmp_path):
    """The real app factory wires the guard from the resolved config."""
    agent = MagicMock()
    agent.checkpointer = MagicMock()
    config = AppConfig(workspace_root=tmp_path, host="localhost", allowed_hosts="docs.example.org")
    app = create_fastapi_app(agent=agent, workspace=tmp_path, config=config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:8050") as c:
        r = await c.get("/api/files/tree", headers={"Host": "evil.example:8050"})
        assert r.status_code == 403 and "allowed_hosts" in r.json()["detail"]
        assert (await c.get("/api/health")).status_code == 200
        assert (await c.get("/api/health", headers={"Host": "docs.example.org"})).status_code == 200


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_live_loopback_socket():
    """On a real loopback socket, uvicorn's scope["server"] is loopback, so the check runs."""
    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(_guarded(), host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                httpx.get(base + "/api/ping", timeout=1)
                break
            except httpx.HTTPError:
                time.sleep(0.1)
        assert httpx.get(base + "/api/ping").status_code == 200
        assert httpx.get(base + "/api/ping", headers={"Host": f"evil.example:{port}"}).status_code == 403
    finally:
        srv.should_exit = True
        t.join(timeout=10)
