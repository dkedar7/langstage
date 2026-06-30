"""CoworkApp — main entry point for the application."""

import logging
import os
import webbrowser
from pathlib import Path

import uvicorn

from langgraph_stream_parser import load_agent_spec
from langstage.config import AppConfig
from langstage.server.main import create_fastapi_app

# NOTE: langstage.default_agent and langstage.middleware are imported lazily
# (inside the methods below) because they pull in `langchain`/`deepagents`, which
# are optional. This keeps `import langstage` working on a base install.

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
        # Resolve through the shared chain: defaults < deepagents.toml <
        # DEEPAGENT_* env < these Python/CLI overrides (None values ignored).
        self.config = AppConfig.resolve(overrides={
            "workspace_root": Path(workspace) if workspace else None,
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
        self.config.workspace_root.mkdir(parents=True, exist_ok=True)

        # Unify the workspace across the WHOLE app on the RESOLVED value (Python
        # kwarg / CLI --workspace / langstage.toml / env), not just the env var.
        # The agent's bash/file/canvas tools read langstage.config.WORKSPACE_ROOT
        # (and some agents read the env var), so set both from the resolved config
        # BEFORE the agent + tools are built. Otherwise --workspace/toml/Python
        # reach the file browser but the agent's tools keep running in the launch
        # cwd — a split-brain where only the env var (lowest documented priority)
        # actually reached the agent. (gh #44)
        from langstage import config as _config

        _resolved_ws = self.config.workspace_root.resolve()
        _config.WORKSPACE_ROOT = _resolved_ws
        os.environ["LANGSTAGE_WORKSPACE_ROOT"] = str(_resolved_ws)
        os.environ["DEEPAGENT_WORKSPACE_ROOT"] = str(_resolved_ws)

        self.agent = self._resolve_agent(agent)
        self.stream_parser_config = stream_parser_config or {}

        # Resolve show_canvas: explicit value wins; otherwise auto-detect from
        # the agent's middleware. show_files stays True unless explicitly off.
        if self.config.show_canvas is None:
            from langstage.middleware import agent_uses_canvas_middleware
            self.config.show_canvas = agent_uses_canvas_middleware(self.agent)
        if self.config.show_files is None:
            self.config.show_files = True

        # Default title and agent_name from the agent object's .name if not explicitly set
        inferred_name = getattr(self.agent, "name", None)
        if inferred_name:
            if self.config.title == "LangStage":
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

        # Ensure a checkpointer. Conversation memory, human-in-the-loop
        # interrupts, and the task board's review gate all need threaded state.
        # Many bring-your-own graphs are compiled without one, so auto-attach an
        # in-memory default (same approach as the AG-UI bridge) instead of
        # silently degrading. The user can still supply their own (durable) one.
        if not _has_checkpointer(self.agent):
            try:
                from langgraph.checkpoint.memory import InMemorySaver

                self.agent.checkpointer = InMemorySaver()
                # Mark it as ours so the server can upgrade it to a durable
                # SQLite saver at startup (which needs the event loop). A
                # user-supplied checkpointer is never marked, so it's never
                # replaced.
                self.agent._langstage_auto_checkpointer = True
                logger.info(
                    "Agent had no checkpointer; attached an in-memory one "
                    "(enables conversation memory + interrupts). Pass your own "
                    "checkpointer for durability across restarts."
                )
            except Exception:  # noqa: BLE001 - best effort; warn if it won't attach
                logger.warning(
                    "Agent has no checkpointer and one could not be attached. "
                    "Human-in-the-loop interrupts and conversation persistence "
                    "will not work. Compile your graph with a checkpointer."
                )

    def _resolve_agent(self, agent):
        """Resolve agent from argument, spec, env var, or create default."""
        if agent is not None:
            return agent
        spec = self.config.agent_spec
        if spec:
            return load_agent_spec(spec)
        from langstage.default_agent import create_default_agent
        return create_default_agent(self.config.workspace_root)

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
            workspace=self.config.workspace_root.resolve(),
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
