"""CoworkApp — main entry point for the application."""

import logging
import webbrowser
from pathlib import Path

import uvicorn

from cowork_dash.agent_loader import load_agent_from_spec
from cowork_dash.config import AppConfig
from cowork_dash.default_agent import create_default_agent
from cowork_dash.middleware import agent_uses_canvas_middleware
from cowork_dash.server.main import create_fastapi_app

logger = logging.getLogger(__name__)


class CoworkApp:
    """Main entry point. Wraps a LangGraph agent with a web UI.

    Configuration priority: Python args > CLI args > env vars > defaults.
    """

    def __init__(
        self,
        agent=None,
        *,
        agent_spec: str | None = None,
        workspace: str | Path | None = None,
        title: str | None = None,
        subtitle: str | None = None,
        welcome_message: str | None = None,
        host: str | None = None,
        port: int | None = None,
        debug: bool | None = None,
        theme: str | None = None,
        agent_name: str | None = None,
        icon_url: str | None = None,
        auth_username: str | None = None,
        auth_password: str | None = None,
        save_workflow_prompt: str | None = None,
        run_workflow_prompt: str | None = None,
        create_workflow_prompt: str | None = None,
        custom_css: str | None = None,
        show_canvas: bool | None = None,
        show_files: bool | None = None,
        stream_parser_config: dict | None = None,
    ):
        self.config = AppConfig.from_env().merge({
            "workspace": Path(workspace) if workspace else None,
            "agent_spec": agent_spec,
            "host": host,
            "port": port,
            "debug": debug,
            "title": title,
            "subtitle": subtitle,
            "welcome_message": welcome_message,
            "theme": theme,
            "agent_name": agent_name,
            "icon_url": icon_url,
            "auth_username": auth_username,
            "auth_password": auth_password,
            "save_workflow_prompt": save_workflow_prompt,
            "run_workflow_prompt": run_workflow_prompt,
            "create_workflow_prompt": create_workflow_prompt,
            "custom_css": custom_css,
            "show_canvas": show_canvas,
            "show_files": show_files,
        })

        # Ensure workspace directory exists
        self.config.workspace.mkdir(parents=True, exist_ok=True)

        self.agent = self._resolve_agent(agent)
        self.stream_parser_config = stream_parser_config or {}

        # Resolve show_canvas: explicit value wins; otherwise auto-detect from
        # the agent's middleware. show_files stays True unless explicitly off.
        if self.config.show_canvas is None:
            self.config.show_canvas = agent_uses_canvas_middleware(self.agent)
        if self.config.show_files is None:
            self.config.show_files = True

        # Default title and agent_name from the agent object's .name if not explicitly set
        inferred_name = getattr(self.agent, "name", None)
        if inferred_name:
            if self.config.title == "Cowork Dash":
                self.config.title = inferred_name
            if self.config.agent_name == "Agent":
                self.config.agent_name = inferred_name

        # Resolve local icon_url to a serveable path
        self._icon_local_path: str | None = None
        if self.config.icon_url and not self.config.icon_url.startswith(("http://", "https://", "data:")):
            self._icon_local_path, self.config.icon_url = _resolve_local_icon(
                self.config.icon_url
            )

        # Read custom CSS file content if configured
        self._custom_css_content: str | None = None
        if self.config.custom_css:
            css_path = Path(self.config.custom_css).resolve()
            if css_path.is_file():
                self._custom_css_content = css_path.read_text()
            else:
                logger.warning("custom_css file not found: %s", css_path)

        # Check for checkpointer
        if not _has_checkpointer(self.agent):
            logger.warning(
                "Agent has no checkpointer. Human-in-the-loop interrupts and "
                "conversation persistence will not work. Pass "
                "checkpointer=MemorySaver() to enable these features."
            )

    def _resolve_agent(self, agent):
        """Resolve agent from argument, spec, env var, or create default."""
        if agent is not None:
            return agent
        spec = self.config.agent_spec
        if spec:
            return load_agent_from_spec(spec)
        return create_default_agent(self.config.workspace)

    def run(self, open_browser: bool = True) -> None:
        """Start the FastAPI server with uvicorn. Blocks."""
        app = self.create_server()

        if open_browser:
            url = f"http://{self.config.host}:{self.config.port}"
            # Open browser after a short delay (server needs to start first)
            import threading
            threading.Timer(1.5, webbrowser.open, args=[url]).start()

        uvicorn.run(
            app,
            host=self.config.host,
            port=self.config.port,
            log_level="debug" if self.config.debug else "info",
        )

    def create_server(self):
        """Return the FastAPI app without starting it.

        Useful for mounting in an existing ASGI app or for testing.
        """
        return create_fastapi_app(
            agent=self.agent,
            workspace=self.config.workspace.resolve(),
            config=self.config,
            stream_parser_config=self.stream_parser_config,
            icon_local_path=self._icon_local_path,
            custom_css_content=self._custom_css_content,
        )


def run_app(
    agent=None,
    *,
    agent_spec: str | None = None,
    workspace: str | Path = ".",
    **kwargs,
) -> None:
    """Shorthand: create CoworkApp and run it."""
    app = CoworkApp(
        agent=agent,
        agent_spec=agent_spec,
        workspace=workspace,
        **kwargs,
    )
    app.run()


def _has_checkpointer(agent) -> bool:
    """Check if an agent has a checkpointer configured."""
    return getattr(agent, "checkpointer", None) is not None


def _resolve_local_icon(icon_path: str) -> tuple[str, str]:
    """Resolve a local file path to an absolute path and a serveable URL.

    Relative paths are resolved against the current working directory (where
    the app is launched from), not the workspace directory. The icon is an
    app-level config, not a workspace artifact.

    Returns (absolute_path, url). The absolute path is stored so the server
    can serve the file via /api/icon. Returns ("", "") if the file is not found.
    """
    p = Path(icon_path)
    abs_path = p.resolve()

    if not abs_path.is_file():
        logger.warning("icon_url file not found: %s", abs_path)
        return "", ""

    return str(abs_path), "/api/icon"
