"""FastAPI application factory."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response

from langstage_core.adapters import SessionAdapter
from langstage_core.tasks import TaskRunner, set_runner

from langstage.config import AppConfig
from langstage.server.middleware import add_middleware
from langstage.server.routes_config import create_config_router
from langstage.server.routes_files import create_files_router
from langstage.server.routes_canvas import create_canvas_router
from langstage.server.routes_session import create_session_router
from langstage.server.routes_chat import create_chat_router
from langstage.server.routes_cron import create_cron_router
from langstage.server.routes_tasks import create_tasks_router
from langstage.scheduler import CronScheduler, set_scheduler
from langstage.tasks import SqliteTaskStore
from langstage.workspace.file_manager import FileManager
from langstage.workspace.canvas_manager import CanvasManager


def _app_version() -> str:
    """The installed ``langstage`` version, for the health payload (gh #67)."""
    try:
        from langstage import __version__

        return __version__
    except Exception:  # noqa: BLE001 - never let the health probe fail on this
        return "0.0.0+unknown"


def _static_dir() -> Path:
    """Directory holding the pre-built React SPA (``langstage/static``).

    Populated at packaging time by the ``hatch_build.py`` build hook (gh #94), so a
    wheel installed from PyPI serves the real UI. A single source of truth for the
    path — also the seam the packaging/serving tests patch (see
    ``tests/test_frontend_packaging.py``)."""
    return Path(__file__).parent.parent / "static"


def create_fastapi_app(
    agent,
    workspace: Path,
    config: AppConfig,
    stream_parser_config: dict | None = None,
    icon_local_path: str | None = None,
    custom_css_content: str | None = None,
) -> FastAPI:
    """Create a FastAPI app with SSE streaming, REST, and static file serving."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await task_store.setup()
        # Upgrade an auto-attached in-memory checkpointer to a durable SQLite
        # one so conversation/interrupt state + the task review gate survive a
        # restart (and orphaned tasks resume from their last checkpoint). Only
        # touches checkpointers LangStage attached (the sentinel) — never a
        # user-supplied one.
        if getattr(agent, "_langstage_auto_checkpointer", False) is True:
            try:
                from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

                ckpt_db = workspace / ".langstage" / "checkpoints.db"
                ckpt_db.parent.mkdir(parents=True, exist_ok=True)
                ckpt_cm = AsyncSqliteSaver.from_conn_string(str(ckpt_db))
                saver = await ckpt_cm.__aenter__()
                await saver.setup()
                agent.checkpointer = saver
                app.state._ckpt_cm = ckpt_cm
            except Exception:  # noqa: BLE001 - keep the in-memory saver on failure
                import logging
                logging.getLogger(__name__).warning(
                    "Durable checkpointer unavailable; keeping in-memory.",
                    exc_info=True,
                )
        await runner.start()
        scheduler.start()

        try:
            yield
        finally:
            # Mirrors the old @app.on_event("shutdown") semantics: these run
            # unconditionally on shutdown, not just on a clean exit.
            scheduler.shutdown()
            await runner.shutdown()
            await task_store.close()
            ckpt_cm = getattr(app.state, "_ckpt_cm", None)
            if ckpt_cm is not None:
                try:
                    await ckpt_cm.__aexit__(None, None, None)
                except Exception:  # noqa: BLE001
                    pass
            set_scheduler(None)
            set_runner(None)

    # Real package version (not a hardcoded "2.0.0") so the built-in OpenAPI schema
    # (/openapi.json, /docs, /redoc) reports the version users actually run (gh #71).
    app = FastAPI(
        title=f"{config.title} REST API",
        version=_app_version(),
        description=(
            "The LangStage web-stage REST API — chat (SSE), files, canvas, cron, and the "
            "task board. Interactive docs at /docs and /redoc; schema at /openapi.json. "
            "All endpoints require Basic Auth when --auth-password is set, except /api/health."
        ),
        lifespan=lifespan,
    )

    # Middleware
    add_middleware(
        app,
        debug=config.debug,
        auth_username=config.auth_username,
        auth_password=config.auth_password,
    )

    # Shared services
    file_manager = FileManager(workspace)
    canvas_manager = CanvasManager(workspace)

    # One session-scoped streaming adapter owns agent execution + the SSE pipe.
    # Since core 1.0 (ADR 0003) it streams every turn through the in-process AG-UI
    # adapter — the only path — emitting the same SSE frames, so the frontend is
    # unchanged. max_result_len is large so the UI shows full tool output.
    adapter = SessionAdapter(
        graph=agent,
        max_result_len=50_000,
        **(stream_parser_config or {}),
    )

    # REST API routes (mounted first — take precedence over static)
    app.include_router(create_config_router(config))
    app.include_router(create_files_router(file_manager))
    app.include_router(create_canvas_router(canvas_manager))
    app.include_router(create_session_router(adapter))
    app.include_router(create_chat_router(adapter, file_manager=file_manager))

    # Durable task board: a SQLite-backed store + the shared TaskRunner worker
    # pool. The runner owns async task execution (queued → ongoing → done);
    # registered process-globally so agent tools can reach it later.
    task_db = workspace / ".langstage" / "tasks.db"
    task_db.parent.mkdir(parents=True, exist_ok=True)
    task_store = SqliteTaskStore(task_db)
    task_concurrency = int(os.getenv("LANGSTAGE_TASK_CONCURRENCY", "3"))
    runner = TaskRunner(adapter, task_store, concurrency=task_concurrency)
    set_runner(runner)
    app.include_router(create_tasks_router(runner, task_store))

    # In-memory cron schedules — now a *producer* that enqueues onto the runner.
    # Registered process-globally so the agent's schedule_run tool can reach it.
    scheduler = CronScheduler(runner)
    set_scheduler(scheduler)
    app.include_router(create_cron_router(scheduler))

    # Dedicated health/readiness endpoint under /api/* (so it never collides with the
    # SPA catch-all) and exempt from Basic Auth in the middleware, so a reverse proxy /
    # k8s / uptime probe always has an endpoint — even with auth on (gh #67).
    @app.get("/api/health")
    async def health(ready: int = 0) -> Response:
        """Liveness (default) or readiness (`?ready=1`).

        Liveness just proves the process is up. Readiness reflects real backend state:
        200 only if the agent object loaded AND the task store is reachable, else 503 —
        fixing the false-positive where the always-served SPA shell made ``/health``
        report healthy regardless of backend state.
        """
        payload = {"status": "ok", "version": _app_version()}
        if not ready:
            return JSONResponse(payload)

        # "loaded" (`is not None`) is vacuous — a failed load aborts startup, so a
        # serving process always has a non-None agent. And "loaded" ≠ "runnable": an
        # uncompiled StateGraph (the common BYO slip) loads fine but dies every turn
        # with no `astream`. Gate readiness on runnability — the exact check
        # `langstage check` uses (gh #39) — so a probe can't mark an unrunnable server
        # Ready (gh #69).
        agent_runnable = callable(getattr(agent, "astream", None))
        checks = {"agent": "ok" if agent_runnable else "not_runnable"}
        try:
            # A bounded query (filtered to a sentinel parent → empty) that still
            # exercises the DB connection, without loading the whole task table.
            await task_store.list(parent_id="__health_probe__")
            checks["task_store"] = "ok"
        except Exception as exc:  # noqa: BLE001 - any failure means not ready
            checks["task_store"] = f"unreachable: {type(exc).__name__}"

        ok = all(v == "ok" for v in checks.values())
        return JSONResponse(
            {"status": "ok" if ok else "degraded", "version": _app_version(), "checks": checks},
            status_code=200 if ok else 503,
        )

    # Expose for testing
    app.state.session_adapter = adapter
    app.state.scheduler = scheduler
    app.state.task_runner = runner
    app.state.task_store = task_store

    # Serve custom CSS (always register so it returns 404 instead of SPA catch-all)
    @app.get("/api/custom-css")
    async def get_custom_css():
        if not custom_css_content:
            return Response(status_code=404)
        return Response(content=custom_css_content, media_type="text/css")

    # Serve local icon file if configured
    if icon_local_path:
        @app.get("/api/icon")
        async def get_icon():
            return FileResponse(icon_local_path)

    # Static file serving (pre-built React app)
    static_dir = _static_dir()
    if static_dir.exists() and (static_dir / "index.html").exists():
        # Serve static assets
        assets_dir = static_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        # Favicon
        favicon = static_dir / "favicon.ico"
        if favicon.exists():
            @app.get("/favicon.ico")
            async def get_favicon():
                return FileResponse(str(favicon))

        # Catch-all: serve index.html for client-side routing. But NOT for the
        # API/WS namespaces — an unknown /api/* path must be a JSON 404, not a
        # 200 + the SPA HTML shell (which silently breaks programmatic clients
        # doing content-negotiation / error handling) (gh #-dogfood).
        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            if full_path == "api" or full_path.startswith(("api/", "ws/")):
                raise HTTPException(status_code=404, detail="Not Found")
            return FileResponse(str(static_dir / "index.html"))
    else:
        # No pre-built frontend — serve a placeholder
        @app.get("/")
        async def placeholder():
            return {
                "message": "LangStage backend is running.",
                "sse": "/api/stream?session_id=...",
                "api": {
                    "config": "/api/config",
                    "chat": "/api/chat",
                    "files": "/api/files/tree",
                    "canvas": "/api/canvas/items",
                },
                "note": "Build the frontend with: cd frontend && npm run build",
            }

    return app
