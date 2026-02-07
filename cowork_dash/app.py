"""CoworkApp — main entry point for the application."""

import logging
import webbrowser
from pathlib import Path

import uvicorn

from cowork_dash.agent_loader import load_agent_from_spec
from cowork_dash.config import AppConfig
from cowork_dash.default_agent import create_default_agent
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
        })

        # Ensure workspace directory exists
        self.config.workspace.mkdir(parents=True, exist_ok=True)

        self.agent = self._resolve_agent(agent)
        self.stream_parser_config = stream_parser_config or {}

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
