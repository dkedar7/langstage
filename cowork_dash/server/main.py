"""FastAPI application factory."""

from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from cowork_dash.config import AppConfig
from cowork_dash.server.middleware import add_middleware
from cowork_dash.server.routes_config import create_config_router
from cowork_dash.server.routes_files import create_files_router
from cowork_dash.server.routes_canvas import create_canvas_router
from cowork_dash.server.routes_session import create_session_router
from cowork_dash.server.websocket import chat_websocket
from cowork_dash.stream.session_manager import SessionManager
from cowork_dash.workspace.file_manager import FileManager
from cowork_dash.workspace.canvas_manager import CanvasManager


def create_fastapi_app(
    agent,
    workspace: Path,
    config: AppConfig,
    stream_parser_config: dict | None = None,
    icon_local_path: str | None = None,
) -> FastAPI:
    """Create a FastAPI app with WebSocket, REST, and static file serving."""
    app = FastAPI(title=config.title, version="2.0.0")

    # Middleware
    add_middleware(app, debug=config.debug)

    # Shared services
    session_manager = SessionManager()
    file_manager = FileManager(workspace)
    canvas_manager = CanvasManager(workspace)

    # REST API routes (mounted first — take precedence over static)
    app.include_router(create_config_router(config))
    app.include_router(create_files_router(file_manager))
    app.include_router(create_canvas_router(canvas_manager))
    app.include_router(create_session_router(session_manager))

    # Serve local icon file if configured
    if icon_local_path:
        @app.get("/api/icon")
        async def get_icon():
            return FileResponse(icon_local_path)

    # WebSocket endpoint
    @app.websocket("/ws/chat")
    async def ws_chat(websocket: WebSocket):
        await chat_websocket(
            websocket=websocket,
            agent=agent,
            session_manager=session_manager,
            file_manager=file_manager,
            stream_parser_config=stream_parser_config,
        )

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
                "message": "Cowork Dash v2 backend is running.",
                "websocket": "/ws/chat",
                "api": {
                    "config": "/api/config",
                    "files": "/api/files/tree",
                    "canvas": "/api/canvas/items",
                },
                "note": "Build the frontend with: cd frontend && npm run build",
            }

    return app
