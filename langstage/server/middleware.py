"""CORS and authentication middleware."""

import base64
import ipaddress
import json
import re
import secrets
from urllib.parse import urlsplit

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

# The opt-in for specific cross-origin sites is the resolved ``cors_origins`` config
# field (LANGSTAGE_CORS_ORIGINS / ``[server] cors_origins``), passed in by the app
# factory, so `config` shows exactly what the server enforces (gh #141).


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


class CrossSiteRequestGuard:
    """Refuse state-changing requests a browser sent on behalf of another site.

    CORS only stops a foreign page *reading* a response. A plain HTML ``<form>``
    POST (query-string, urlencoded, multipart or text/plain body) is a CORS
    "simple request": the browser sends it with no preflight, and the route runs
    before any CORS decision matters -- so a drive-by page could delete, overwrite
    and create workspace files or start schedule runs (gh #206). This closes that
    for EVERY unsafe method (anything but GET/HEAD/OPTIONS) on every route, at one
    place, instead of route by route.

    A request is refused with 403 when a browser marks it as coming from somewhere
    the user didn't allow:

    * it carries an ``Origin`` that is neither the server's own origin (its
      ``host:port`` equals the ``Host`` header) nor allowed by the resolved CORS
      policy (:func:`_resolve_cors`: loopback origins by default, or exactly the
      ``cors_origins`` the user listed; ``*`` allows any). ``Origin: null``
      (sandboxed iframe, ``file://``) is never allowed.
    * it carries no ``Origin`` but ``Sec-Fetch-Site`` is ``cross-site`` or
      ``same-site`` -- the browser says it came from another site and gives no
      origin to check against the allow-list.

    ``Sec-Fetch-Site: same-origin`` / ``none`` is a browser attestation (pages
    can't forge ``Sec-Fetch-*``) and is let through even if ``Origin`` and ``Host``
    disagree, e.g. behind a reverse proxy that rewrites ``Host``. A request with
    neither header -- curl, scripts, the CLI, server-to-server -- isn't a browser
    acting for a web page, so it passes unchanged.

    It sits inside ``CORSMiddleware`` (preflights are answered before this) and
    outside Basic Auth, so it applies with auth on too: a browser replays cached
    Basic credentials on a cross-site form POST just as it does cookies.
    """

    _SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

    def __init__(self, app: ASGIApp, cors: dict) -> None:
        self.app = app
        self._any_origin = "*" in (cors.get("allow_origins") or ())
        self._origins = {o.lower().rstrip("/") for o in cors.get("allow_origins") or ()}
        regex = cors.get("allow_origin_regex")
        self._origin_regex = re.compile(regex) if regex else None

    def _origin_allowed(self, origin: str, host: str) -> bool:
        origin = origin.strip().lower().rstrip("/")
        if not origin or origin == "null":
            return False
        if self._any_origin or origin in self._origins:
            return True
        if self._origin_regex is not None and self._origin_regex.fullmatch(origin):
            return True
        try:
            netloc = urlsplit(origin).netloc
        except ValueError:
            return False
        return bool(host) and netloc == host.strip().lower()

    def _reject_reason(self, scope: Scope) -> str | None:
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        fetch_site = headers.get(b"sec-fetch-site", b"").decode("latin-1").strip().lower()
        if fetch_site in ("same-origin", "none"):
            return None
        origin = headers.get(b"origin")
        if origin is not None:
            host = headers.get(b"host", b"").decode("latin-1")
            if self._origin_allowed(origin.decode("latin-1"), host):
                return None
            return f"origin {origin.decode('latin-1').strip()!r} is not allowed"
        if fetch_site in ("cross-site", "same-site"):
            return f"Sec-Fetch-Site is {fetch_site!r} and no allowed Origin was sent"
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method", "GET").upper() in self._SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        reason = self._reject_reason(scope)
        if reason is None:
            await self.app(scope, receive, send)
            return
        body = json.dumps({
            "detail": (
                f"Cross-site request refused: {reason}. State-changing requests are only "
                "accepted from this server's own pages or an origin listed in "
                "LANGSTAGE_CORS_ORIGINS ([server] cors_origins)."
            ),
        })
        await Response(body, status_code=403, media_type="application/json")(scope, receive, send)


_LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


def _split_hosts(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """``allowed_hosts`` as a list: a TOML array, or a comma-separated string."""
    raw = [str(v) for v in value] if isinstance(value, (list, tuple)) else (value or "").split(",")
    return [h.strip().lower() for h in raw if h.strip()]


def _hostname(host_header: str) -> str:
    """The name part of a ``Host`` header, lowercased: port and IPv6 brackets dropped."""
    h = host_header.strip().lower()
    if h.startswith("["):
        return h[1:].split("]", 1)[0]
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def is_loopback_host(host: str) -> bool:
    """Whether a bind host, socket address or Host name is loopback.

    ``localhost``, ``*.localhost`` (browsers resolve it to loopback themselves), or an IP
    literal in 127.0.0.0/8 or ``::1`` (IPv4-mapped included). A Host header is a name the
    caller picks, so ``127.attacker.example`` is a DNS name, not loopback (gh #221).
    """
    h = (_hostname(host) if host.startswith("[") else host.strip().lower()).rstrip(".")
    if h in _LOOPBACK_NAMES or h.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return (mapped or ip).is_loopback


class HostHeaderGuard:
    """Refuse requests whose ``Host`` isn't a name this local server answers to (gh #208).

    DNS rebinding: a page at ``http://evil.example:8050`` re-points its DNS at
    127.0.0.1. To the browser it is still same-origin with itself, so the cross-site
    guard (#206) lets its requests through, and it can READ the responses too. The
    ``Host`` header still says ``evil.example``, so on a loopback server any request
    whose ``Host`` isn't a loopback name (``localhost``, ``127.0.0.1``, ``[::1]``,
    ``*.localhost``), the bind host, or an ``allowed_hosts`` entry is refused with 403,
    every method, WebSocket included. ``*.example.org`` in ``allowed_hosts`` matches its
subdomains (as in langstage-codraft); ``*`` turns the check off.

    It applies only when the server is bound to a loopback address AND the connection
    arrived on one (``scope["server"]``); a public bind is unchanged (it is documented
    as needing auth), and so is an in-process client with no socket. A request with no
    ``Host`` header passes (HTTP/1.0 tools).
    """

    def __init__(self, app: ASGIApp, bind_host: str, allowed_hosts: str | list[str] | None = "") -> None:
        self.app = app
        entries = _split_hosts(allowed_hosts)
        self._off = "*" in entries or not is_loopback_host(bind_host or "")
        self._allowed = {_hostname(e) for e in entries if not e.startswith("*.")} | {_hostname(bind_host or "")}
        self._suffixes = tuple(e[1:].rstrip(".") for e in entries if e.startswith("*."))

    def _host_allowed(self, host: str) -> bool:
        name = _hostname(host).rstrip(".")
        if name in self._allowed or is_loopback_host(name):
            return True
        return bool(self._suffixes) and name.endswith(self._suffixes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._off or scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        server = scope.get("server") or (None, None)
        if not (isinstance(server[0], str) and is_loopback_host(server[0])):
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        raw = headers.get(b"host")
        if raw is None or self._host_allowed(raw.decode("latin-1")):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await WebSocketClose(code=1008)(scope, receive, send)
            return
        host = raw.decode("latin-1").strip()
        body = json.dumps({
            "detail": (
                f"Host {host!r} is not allowed. This server is bound to a loopback address and "
                "only answers to localhost names, to protect it from DNS rebinding. If you reach "
                f"it through a proxy or another name, add {_hostname(host)!r} to [server] "
                "allowed_hosts in langstage.toml or LANGSTAGE_ALLOWED_HOSTS "
                "(comma-separated; \"*\" turns the check off)."
            )
        })
        await Response(body, status_code=403, media_type="application/json")(scope, receive, send)


def _resolve_cors(origins: str | list[str] | None) -> dict:
    """Compute safe CORS kwargs for ``CORSMiddleware``.

    Default: credentialed access is granted only to loopback origins via
    ``allow_origin_regex`` (:data:`_LOOPBACK_ORIGIN_REGEX`) -- enough for the
    same-origin SPA and a local dev server, but a drive-by website is never
    reflected, so it can't read/write the workspace or drive the agent (gh #113).

    Opt-in: ``cors_origins`` (``LANGSTAGE_CORS_ORIGINS`` / ``[server] cors_origins``)
    is a comma-separated list of origins a user genuinely needs to allow (a TOML
    array works too). Those are matched exactly, with credentials. A literal
    ``*`` is honored but FORCES ``allow_credentials=False`` -- the browser forbids
    ``*`` together with credentials, and shipping the reflect-any-origin combination
    is exactly the anti-pattern this closes.
    """
    common = {"allow_methods": ["*"], "allow_headers": ["*"]}
    if isinstance(origins, (list, tuple)):
        raw = [str(o) for o in origins]
    else:
        raw = (origins or "").split(",")
    entries = [o.strip() for o in raw if o.strip()]
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
    cors_origins: str | list[str] | None = "",
    bind_host: str = "",
    allowed_hosts: str | list[str] | None = "",
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

    # Cross-site request guard, between auth and CORS: a browser form POST from
    # another site is refused before any route (or auth) runs, with or without a
    # password; same-origin pages, allowed origins and header-less clients
    # (curl, scripts) pass. Shares the CORS allow-list. (gh #206)
    cors = _resolve_cors(cors_origins)
    app.add_middleware(CrossSiteRequestGuard, cors=cors)

    # CORS, outermost, so it answers a preflight OPTIONS itself before auth sees it.
    # Browsers send preflights without credentials, so auth used to 401 them and
    # break every cross-origin client once a password was set. A preflight only
    # returns the CORS policy; the real request that follows is still
    # authenticated. Loopback-only by default; the resolved cors_origins
    # (LANGSTAGE_CORS_ORIGINS / [server] cors_origins) opts specific sites in.
    # (gh #113, gh #155, gh #141)
    app.add_middleware(CORSMiddleware, **cors)

    # DNS-rebinding guard, outermost: a request to a loopback server whose Host is a
    # name the user never allowed is refused before CORS, auth or any route. (gh #208)
    app.add_middleware(HostHeaderGuard, bind_host=bind_host, allowed_hosts=allowed_hosts)
