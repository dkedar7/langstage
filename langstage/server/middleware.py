"""CORS and authentication middleware."""

import base64
import secrets

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send


class BasicAuthMiddleware:
    """ASGI middleware for HTTP Basic Authentication.

    Protects all HTTP and WebSocket endpoints. The browser shows its
    native login dialog on 401. WebSocket connections are authenticated
    on the upgrade request.
    """

    def __init__(self, app: ASGIApp, username: str, password: str) -> None:
        self.app = app
        self._username = username
        self._password = password

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode()

        if self._check_credentials(auth_header):
            await self.app(scope, receive, send)
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


def add_middleware(
    app: FastAPI,
    debug: bool = False,
    auth_username: str = "",
    auth_password: str = "",
) -> None:
    """Add middleware stack. CORS is always added; basic auth is conditional."""
    # CORS (added first so preflight OPTIONS work even with auth)
    origins = []
    if debug:
        origins = [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins if origins else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Basic auth (only when a password is configured)
    if auth_password:
        username = auth_username or "admin"
        app.add_middleware(BasicAuthMiddleware, username=username, password=auth_password)
