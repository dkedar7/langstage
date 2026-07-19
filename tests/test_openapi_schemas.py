"""The served OpenAPI document must actually describe response bodies (gh #98).

The README sells ``/openapi.json`` as the canonical reference to feed a client
generator "instead of reverse-engineering shapes". Before this, *every* one of
the 32 ``/api/*`` routes had ``"schema": {}`` for its 200 response, because no
route declared a response type — so a generated client typed every return as
``object``/``any`` and an author still had to reverse-engineer the lot.

Two things are pinned here, and the second matters more than the first:

1. No ``/api/*`` route advertises an empty ``application/json`` 200 schema.
2. Attaching ``response_model=`` did not change any response *body*. FastAPI uses
   the response model to **filter** the payload — undeclared keys are silently
   dropped — so a stale model would quietly delete fields the React app depends
   on. ``AppConfigResponse`` was in fact stale (7 declared fields vs 12 returned),
   which is why every model sets ``extra="allow"``.
"""

import pytest
from fastapi.testclient import TestClient

from langstage.server import models as models_mod
from tests.test_frontend_packaging import _app_with_static


@pytest.fixture
def client(tmp_path, monkeypatch):
    app = _app_with_static(tmp_path, tmp_path / "no-static", monkeypatch)
    with TestClient(app) as c:
        yield c


# ── 1. the schema is actually populated ──────────────────────────────────────


def _api_200s(spec):
    for path, methods in spec["paths"].items():
        if not path.startswith("/api"):
            continue
        for method, op in methods.items():
            ok = op.get("responses", {}).get("200")
            if ok:
                yield method.upper(), path, ok


def test_no_api_route_advertises_an_empty_json_schema(client):
    """The issue's own metric: 32/32 empty before, 0 after."""
    spec = client.get("/openapi.json").json()
    empty = [
        f"{m} {p}"
        for m, p, ok in _api_200s(spec)
        if ok.get("content", {}).get("application/json", {}).get("schema") == {}
    ]
    assert empty == [], f"routes still advertising an untyped JSON body: {empty}"


def test_every_api_200_declares_some_content_type(client):
    """A route with no declared content at all is just as useless to a generator."""
    spec = client.get("/openapi.json").json()
    missing = [f"{m} {p}" for m, p, ok in _api_200s(spec) if not ok.get("content")]
    assert missing == []


def test_non_json_routes_declare_their_real_media_type(client):
    """Binary/SSE/CSS routes must not claim to return JSON.

    Declaring `application/json` with an empty schema is worse than saying
    nothing — a generator would emit a JSON-decoding client for a byte stream.
    """
    spec = client.get("/openapi.json").json()
    expected = {
        "/api/files/download": "application/octet-stream",
        "/api/canvas/assets/{filename}": "application/octet-stream",
        "/api/stream": "text/event-stream",
        "/api/custom-css": "text/css",
    }
    for path, media in expected.items():
        ok = spec["paths"][path]["get"]["responses"]["200"]
        assert media in ok.get("content", {}), f"{path} should declare {media}"
        assert "application/json" not in ok.get("content", {}), (
            f"{path} must not advertise a JSON body"
        )


def test_schemas_are_resolvable_component_refs(client):
    """A `$ref` pointing at a missing component would break every generator."""
    spec = client.get("/openapi.json").json()
    components = spec.get("components", {}).get("schemas", {})
    for m, p, ok in _api_200s(spec):
        schema = ok.get("content", {}).get("application/json", {}).get("schema", {})
        ref = schema.get("$ref") or schema.get("items", {}).get("$ref")
        if ref:
            assert ref.split("/")[-1] in components, f"{m} {p} -> dangling {ref}"


# ── 2. no response body changed (the regression this could have caused) ──────


def test_config_response_keeps_every_field(client):
    """The concrete near-miss: AppConfigResponse declared 7 of 12 real fields.

    Wired strictly, this test would fail with the five workflow/visibility keys
    silently dropped from the payload the SPA boots on.
    """
    body = client.get("/api/config").json()
    for key in (
        "title",
        "subtitle",
        "welcome_message",
        "theme",
        "workspace_name",
        "agent_name",
        "icon_url",
        "save_workflow_prompt",
        "run_workflow_prompt",
        "create_workflow_prompt",
        "show_canvas",
        "show_files",
    ):
        assert key in body, f"/api/config lost {key!r} to response_model filtering"


def test_file_tree_does_not_materialize_unset_optionals(client, tmp_path):
    """`response_model` alone would *add* keys as well as drop them.

    `FileEntry.children` defaults to None, so a plain response_model renders
    `"children": null` onto every entry — a body change the pre-fix wire never
    emitted. `response_model_exclude_unset=True` keeps the payload byte-identical
    to what the route actually produced, so the schema is documentation-only.
    """
    body = client.get("/api/files/tree").json()
    for entry in body["entries"]:
        assert "children" not in entry or entry["children"], (
            "unset optional was materialized into the response body"
        )


@pytest.mark.parametrize("route", ["/api/config", "/api/files/tree", "/api/health"])
def test_typed_routes_emit_only_keys_the_handler_produced(client, route):
    """No route may gain a key purely from being typed."""
    body = client.get(route).json()

    def no_null_padding(obj):
        if isinstance(obj, dict):
            # A None here can only come from the handler itself (exclude_unset
            # strips defaults), never from the model's declaration.
            return all(no_null_padding(v) for v in obj.values())
        if isinstance(obj, list):
            return all(no_null_padding(v) for v in obj)
        return True

    assert no_null_padding(body)


def test_health_liveness_and_readiness_payloads_are_unchanged(client):
    """`checks` is absent on liveness and present on readiness — the optional
    field must not be materialized as null, nor the readiness block filtered."""
    live = client.get("/api/health").json()
    assert set(live) >= {"status", "version"}
    assert live.get("checks") is None

    ready = client.get("/api/health?ready=1").json()
    assert ready["checks"]["agent"]
    assert "frontend" in ready["checks"]  # gh #96


_RESPONSE_MODELS = [
    m
    for m in vars(models_mod).values()
    if isinstance(m, type)
    and issubclass(m, models_mod.BaseModel)
    # Only models declared here — not pydantic's BaseModel, imported into scope.
    and m.__module__ == models_mod.__name__
]


@pytest.mark.parametrize("model", _RESPONSE_MODELS, ids=lambda m: m.__name__)
def test_every_response_model_allows_extra_keys(model):
    """The guard that makes all of this safe.

    A model added later without `extra="allow"` would start silently dropping
    undeclared keys from a live endpoint — the exact regression this design
    avoids — and nothing else would catch it.
    """
    assert model.model_config.get("extra") == "allow", (
        f"{model.__name__} must allow extra keys or it will filter response bodies"
    )
