"""CORS and authentication middleware."""

import base64
import os
import secrets

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocketClose


# Credentialed cross-origin access is granted ONLY to loopback origins by default:
# localhost / 127.0.0.1 / [::1], http or https, any port. That's everything the
# same-origin SPA and a local Vite dev server (http://localhost:5173) need, while a
# drive-by website's Origin (https://evil.example, http://attacker.test, or the
# `null` origin of a sandboxed iframe / file://) does NOT match -- so the browser is
# never handed `access-control-allow-origin: <that site>` with credentials, closing
# the reflect-any-origin hole that let any page read/write the workspace and drive
# the agent on the default local server. (gh #113)
_LOOPBACK_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"

# Env opt-in for a user who genuinely needs to allow specific cross-origin sites.
_CORS_ORIGINS_ENV = "LANGSTAGE_CORS_ORIGINS"


class BasicAuthMiddleware:
    """ASGI middleware for HTTP Basic Authentication.

    Protects all HTTP and WebSocket endpoints. The browser shows its
    native login dialog on 401. WebSocket connections are authenticated
    on the upgrade request (closed with 1008 before accept, which the server
    turns into an HTTP 403). Other scopes (``lifespan``) pass through.

    CORS preflights never reach this layer: ``CORSMiddleware`` sits outside it and
    answers them itself (gh #155).
    """

    # Paths served without auth so an orchestrator / load-balancer liveness probe
    # (which can't carry credentials) always has an endpoint to hit (gh #67).
    _AUTH_EXEMPT = frozenset({"/api/health"})

    def __init__(self, app: ASGIApp, username: str, password: str) -> None:
        self.app = app
        self._username = username
        self._password = password

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Only lifespan is exempt. This used to be `!= "http"`, which passed every
        # WebSocket upgrade through unauthenticated, despite the docstring.
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        if scope.get("path", "") in self._AUTH_EXEMPT:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode("latin-1")

        if self._check_credentials(auth_header):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await WebSocketClose(code=1008)(scope, receive, send)
            return

        # HTTP: send 401 to trigger browser login prompt
        response = Response(
            "Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="langstage"'},
        )
        await response(scope, receive, send)

    def _check_credentials(self, auth_header: str) -> bool:
        if not auth_header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        except Exception:
            return False
        if ":" not in decoded:
            return False
        username, password = decoded.split(":", 1)
        return (
            secrets.compare_digest(username, self._username)
            and secrets.compare_digest(password, self._password)
        )


def _resolve_cors(env_origins: str | None) -> dict:
    """Compute safe CORS kwargs for ``CORSMiddleware``.

    Default: credentialed access is granted only to loopback origins via
    ``allow_origin_regex`` (:data:`_LOOPBACK_ORIGIN_REGEX`) -- enough for the
    same-origin SPA and a local dev server, but a drive-by website is never
    reflected, so it can't read/write the workspace or drive the agent (gh #113).

    Opt-in: ``LANGSTAGE_CORS_ORIGINS`` is a comma-separated list of origins a user
    genuinely needs to allow. Those are matched exactly, with credentials. A literal
    ``*`` is honored but FORCES ``allow_credentials=False`` -- the browser forbids
    ``*`` together with credentials, and shipping the reflect-any-origin combination
    is exactly the anti-pattern this closes.
    """
    common = {"allow_methods": ["*"], "allow_headers": ["*"]}
    entries = [o.strip() for o in (env_origins or "").split(",") if o.strip()]
    if entries:
        if "*" in entries:
            # `*` can never be combined with credentials (browser rule + gh #113).
            return {"allow_origins": ["*"], "allow_credentials": False, **common}
        return {"allow_origins": entries, "allow_credentials": True, **common}
    # Safe default: loopback-only, credentialed (covers the Vite dev server too, so
    # debug needs no special-casing anymore).
    return {"allow_origin_regex": _LOOPBACK_ORIGIN_REGEX, "allow_credentials": True, **common}


def add_middleware(
    app: FastAPI,
    debug: bool = False,
    auth_username: str = "admin",
    auth_password: str = "",
) -> None:
    """Add middleware stack. CORS is always added; basic auth is conditional.

    ``add_middleware`` prepends, so the LAST one added is the OUTERMOST. Auth is
    added first and CORS last, which puts CORS outside auth.
    """
    # Basic auth (only when a password is configured). The "admin" default now
    # lives in the config layer, so use the resolved value directly — what
    # --show-config displays is exactly what the server enforces. (gh #35)
    if auth_password:
        app.add_middleware(BasicAuthMiddleware, username=auth_username or "admin", password=auth_password)

    # CORS, outermost, so it answers a preflight OPTIONS itself before auth sees it.
    # Browsers send preflights without credentials, so auth used to 401 them and
    # break every cross-origin client once a password was set. A preflight only
    # returns the CORS policy; the real request that follows is still
    # authenticated. Loopback-only by default; LANGSTAGE_CORS_ORIGINS opts specific
    # sites in. (gh #113, gh #155)
    app.add_middleware(CORSMiddleware, **_resolve_cors(os.getenv(_CORS_ORIGINS_ENV)))
