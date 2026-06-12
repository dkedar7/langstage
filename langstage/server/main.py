"""FastAPI application factory."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response

from langgraph_stream_parser.adapters import SessionAdapter

from langstage.config import AppConfig
from langstage.server.middleware import add_middleware
from langstage.server.routes_config import create_config_router
from langstage.server.routes_files import create_files_router
from langstage.server.routes_canvas import create_canvas_router
from langstage.server.routes_session import create_session_router
from langstage.server.routes_chat import create_chat_router
from langstage.server.routes_cron import create_cron_router
from langstage.scheduler import CronScheduler, set_scheduler
from langstage.workspace.file_manager import FileManager
from langstage.workspace.canvas_manager import CanvasManager


def create_fastapi_app(
    agent,
    workspace: Path,
    config: AppConfig,
    stream_parser_config: dict | None = None,
    icon_local_path: str | None = None,
    custom_css_content: str | None = None,
) -> FastAPI:
    """Create a FastAPI app with SSE streaming, REST, and static file serving."""
    app = FastAPI(title=config.title, version="2.0.0")

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
    # max_result_len is large so the UI can show full tool output, not a preview.
    adapter = SessionAdapter(
        graph=agent,
        stream_mode=["updates", "messages"],
        max_result_len=50_000,
        **(stream_parser_config or {}),
    )

    # REST API routes (mounted first — take precedence over static)
    app.include_router(create_config_router(config))
    app.include_router(create_files_router(file_manager))
    app.include_router(create_canvas_router(canvas_manager))
    app.include_router(create_session_router(adapter))
    app.include_router(create_chat_router(adapter, file_manager=file_manager))

    # In-memory cron scheduler — recurring agent runs while the app is alive.
    # Registered process-globally so the agent's schedule_run tool can reach it.
    scheduler = CronScheduler(adapter)
    set_scheduler(scheduler)
    app.include_router(create_cron_router(scheduler))

    @app.on_event("startup")
    async def _start_scheduler() -> None:
        scheduler.start()

    @app.on_event("shutdown")
    async def _stop_scheduler() -> None:
        scheduler.shutdown()
        set_scheduler(None)

    # Expose for testing
    app.state.session_adapter = adapter
    app.state.scheduler = scheduler

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
    static_dir = Path(__file__).parent.parent / "static"
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

        # Catch-all: serve index.html for client-side routing
        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
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
