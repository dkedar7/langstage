"""Pydantic request/response schemas for REST endpoints.

Every model here is wired to a route as ``response_model=`` so the served
``/openapi.json`` actually describes response bodies. The README advertises that
document as the canonical reference to feed a client generator, but until gh #98
*none* of the 32 ``/api/*`` routes declared a response type, so every generated
client came out with an untyped ``object``/``any`` return — the exact
reverse-engineering the README promises you can skip.

Why every model sets ``extra="allow"``
--------------------------------------
FastAPI uses ``response_model`` to *filter* the response: any key the model does
not declare is **silently dropped** from the body. Attaching a strict model to a
live route is therefore a real regression risk, not a documentation-only change —
and these models had already drifted. ``AppConfigResponse`` declared 7 fields
while ``GET /api/config`` actually returns 12, so wiring it strictly would have
quietly removed ``save_workflow_prompt``, ``run_workflow_prompt``,
``create_workflow_prompt``, ``show_canvas`` and ``show_files`` from the payload
the React app consumes.

``extra="allow"`` keeps undeclared keys in the serialized body while still
emitting a full ``properties`` block (plus ``additionalProperties: true``) into
the schema. So a generator gets real types, and a route that grows a field before
anyone updates its model degrades to "documented fields plus extras" instead of
losing data. The shapes below were captured from a live ``--demo`` server rather
than inferred from the source.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict


class _Schema(BaseModel):
    """Base for every response model: never drop an undeclared key (gh #98)."""

    model_config = ConfigDict(extra="allow")


# ── generic acknowledgements ─────────────────────────────────────────────────


class OkResponse(_Schema):
    """``{"ok": true}`` — the mutation-accepted shape used across cron/tasks/session."""

    ok: bool


class SessionAck(_Schema):
    """``{"status": ..., "session_id": ...}`` — chat/inject acknowledgement."""

    status: str
    session_id: str


class StatusResponse(_Schema):
    """``{"status": "ok"}`` — the canvas mutation acknowledgement."""

    status: str


class CanvasExport(_Schema):
    """``/api/canvas/export`` — the canvas rendered as one markdown document."""

    content: str


# ── health / config ──────────────────────────────────────────────────────────


class HealthResponse(_Schema):
    """Liveness (default) or readiness (``?ready=1``).

    ``checks`` is absent from the liveness payload and present on readiness, so
    it is optional rather than required (gh #67, #96).
    """

    status: str
    version: str
    checks: dict[str, str] | None = None


class AppConfigResponse(_Schema):
    """UI configuration consumed by the SPA on boot."""

    title: str
    subtitle: str
    welcome_message: str
    theme: str
    workspace_name: str
    agent_name: str
    icon_url: str
    save_workflow_prompt: str
    run_workflow_prompt: str
    create_workflow_prompt: str
    show_canvas: bool
    show_files: bool


# ── files ────────────────────────────────────────────────────────────────────


class FileEntry(_Schema):
    name: str
    path: str
    is_dir: bool
    size: int | None = None
    children: list["FileEntry"] | None = None


class FileTree(_Schema):
    entries: list[FileEntry]
    root: str


class FileContent(_Schema):
    content: str
    language: str
    size: int
    path: str


class FilePreview(_Schema):
    """``/api/files/preview`` — richer than ``FileContent``: ``data`` carries the
    body and ``preview_type`` says how to render it."""

    path: str
    name: str
    size: int
    preview_type: str
    language: str | None = None
    data: Any | None = None


class FileOpResult(_Schema):
    """Result of a mutating file operation (upload / mkdir / delete)."""

    path: str
    name: str


# ── sessions ─────────────────────────────────────────────────────────────────


class SessionInfo(_Schema):
    session_id: str
    created_at: str
    connected: bool


# ── tasks ────────────────────────────────────────────────────────────────────


class Task(_Schema):
    """A task-board entry. Nullable fields fill in as the task progresses."""

    task_id: str
    parent_id: str | None = None
    title: str | None = None
    prompt: str | None = None
    agent_spec: str | None = None
    state: str
    thread_id: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    result: Any | None = None
    artifacts: Any | None = None
    error: str | None = None
    interrupt: Any | None = None


class TaskEvent(_Schema):
    """One streamed frame recorded against a task.

    Deliberately loose: this is the shared frame vocabulary (``content``,
    ``tool_start``, ``tool_end``, ``reasoning``, ``extraction``, ``interrupt``,
    ``complete``, ``error``), so which keys are present varies by ``type``. Only
    ``type`` is guaranteed; ``extra="allow"`` carries the rest through untouched
    rather than flattening a union into whichever variant happened to be
    modelled.
    """

    type: str


# ── cron ─────────────────────────────────────────────────────────────────────


class CronJob(_Schema):
    id: str
    name: str
    cron: str
    prompt: str
    created_at: str | None = None
    created_by: str | None = None
    enabled: bool = True
    next_run: str | None = None
    last_run: str | None = None
    last_status: str | None = None
    run_count: int = 0
    last_task_id: str | None = None
    session_id: str | None = None


# ── canvas ───────────────────────────────────────────────────────────────────


class CanvasItemResponse(_Schema):
    id: str
    type: str
    title: str
    data: dict
    created_at: str
