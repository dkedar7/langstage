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


class ChatComplete(_Schema):
    """``POST /api/chat/complete`` — one buffered turn assembled into a single
    JSON body (the synchronous, non-SSE sibling of the streaming chat pair).

    ``content`` is the assistant's final text; ``tool_calls`` the calls it made;
    ``session_id`` the (possibly newly created) session the turn ran on, so a
    caller can continue the same thread over SSE afterwards if it wants. A turn
    that pauses on a human-review interrupt carries an extra ``outcome`` +
    ``interrupt`` (allowed by ``extra="allow"``); an errored turn is surfaced as
    an HTTP 500, not a 200 body (gh #101)."""

    session_id: str
    content: str
    tool_calls: list[dict[str, Any]] = []


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
    body and ``preview_type`` says how to render it.

    The variant fields are optional and present only for their ``preview_type``:
    ``headers`` + ``rows`` for ``csv``, ``download_url`` for ``pdf`` / ``binary``, and
    ``mime`` for ``image``. They were missing from the schema (the body always had
    them), so a generated client couldn't read a CSV's table or a binary's download
    link (gh #162)."""

    path: str
    name: str
    size: int
    preview_type: str
    language: str | None = None
    data: Any | None = None
    headers: list[str] | None = None
    rows: list[dict[str, Any]] | None = None
    download_url: str | None = None
    mime: str | None = None


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
    # Always null over REST: POST /api/tasks rejects a per-task spec (gh #165).
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
    # State of the task the last run enqueued (e.g. "review" when it awaits human
    # approval), or null. The README documents it and GET /api/cron always returns
    # it, but the schema left it out (gh #135).
    last_run_state: str | None = None
    session_id: str | None = None


# ── canvas ───────────────────────────────────────────────────────────────────


class CanvasItemResponse(_Schema):
    """One item as ``load_canvas_from_markdown`` returns it (gh #158).

    ``data`` is a string for markdown / html / mermaid / section items and structured
    JSON for charts and tables. ``title`` exists only when the tool was given one,
    and ``level`` only on sections. The old model required ``title`` and typed
    ``data`` as a dict, so a real canvas 500'd the list route.
    """

    id: str
    type: str
    title: str | None = None
    data: Any = None
    created_at: str | None = None
    level: int | None = None
    file: str | None = None
    source_cell: int | None = None
    execution_count: int | None = None
