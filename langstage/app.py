"""CoworkApp — main entry point for the application."""

import asyncio
import logging
import os
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from langstage_core import load_agent_spec
from langstage.config import AppConfig
from langstage.server.main import create_fastapi_app

# NOTE: langstage.default_agent and langstage.middleware are imported lazily
# (inside the methods below) because they pull in `langchain`/`deepagents`, which
# are optional. This keeps `import langstage` working on a base install.

logger = logging.getLogger(__name__)

#: How long run() waits for the background server to bind before giving up (gh #87).
_STARTUP_TIMEOUT = 20.0


def _in_running_event_loop() -> bool:
    """True when called from inside an already-running asyncio loop.

    That's exactly the Jupyter/IPython kernel case (and any async context):
    ``uvicorn.run()`` wraps ``asyncio.run()``, which raises
    ``RuntimeError: Cannot run the event loop while another loop is running``
    there — so ``run()`` must serve on a background thread instead (gh #87).
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


class BackgroundServer:
    """Handle for a LangStage server running on a background thread.

    Returned by :meth:`CoworkApp.run` when it's called from a notebook (or any
    running event loop), where blocking the caller would be useless — the kernel
    stays interactive and you get a handle to stop the server (gh #87).
    """

    def __init__(self, server: uvicorn.Server, thread: threading.Thread, url: str):
        self._server = server
        self._thread = thread
        self.url = url

    @property
    def running(self) -> bool:
        return self._thread.is_alive()

    def stop(self, timeout: float = 5.0) -> None:
        """Ask the server to shut down and wait for its thread to exit."""
        self._server.should_exit = True
        self._thread.join(timeout=timeout)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        state = "running" if self.running else "stopped"
        return f"<LangStage {state} at {self.url}>"

    def _repr_html_(self) -> str:  # pragma: no cover - notebook display hook
        return f'LangStage running at <a href="{self.url}" target="_blank">{self.url}</a>'


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

        # Unify the workspace across the WHOLE app on the RESOLVED value (Python
        # kwarg / CLI --workspace / langstage.toml / env) via the shared source of
        # truth (ADR 0005), BEFORE the agent + tools are built. apply_workspace
        # ensures the dir, publishes LANGSTAGE_WORKSPACE_ROOT (+ legacy) for agents
        # that read the env, and records the active workspace that config.WORKSPACE_ROOT
        # (the agent's bash/file/canvas tools) and the file browser both read — so
        # --workspace/toml/Python can't reach the browser while the agent runs in the
        # launch cwd (the #44 split-brain). No chdir: a server serves one workspace but
        # must not move the process cwd out from under anything else.
        from langstage_core import apply_workspace

        apply_workspace(self.config.workspace_root)

        self.agent = self._resolve_agent(agent)
        self.stream_parser_config = stream_parser_config or {}

        # Resolve show_canvas: explicit value wins; otherwise auto-detect from
        # the agent's middleware. show_files stays True unless explicitly off.
        if self.config.show_canvas is None:
            from langstage.middleware import agent_uses_canvas_middleware
            self.config.show_canvas = agent_uses_canvas_middleware(self.agent)
        if self.config.show_files is None:
            self.config.show_files = True

        # Default title and agent_name from the agent object's .name if not explicitly
        # set — but a bare CompiledStateGraph's default .name is "LangGraph" (and
        # "agent"/"graph" are just as generic), which reads as a confusing app title for
        # a BYO agent. Treat those as "no meaningful name" and keep the LangStage default.
        inferred_name = getattr(self.agent, "name", None)
        if inferred_name in ("LangGraph", "agent", "graph"):
            inferred_name = None
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

    def _enter_workspace(self) -> None:
        """Make the resolved workspace the process cwd (ADR 0006).

        So a bring-your-own agent's raw relative file ops
        (``Path("out.txt").write_text(...)``) land in the workspace — where the file
        browser shows them — instead of the server's launch cwd. Called from ``run()``
        *after* the agent spec is resolved and ``create_server()`` has wired the file
        browser at the **absolute** workspace, so neither is affected. The bundled
        agent (rooted via an absolute ``FilesystemBackend``) is unaffected either way.
        Done in ``run()`` (not ``__init__``) so embedding ``CoworkApp`` has no cwd side
        effect. Safe under the one-workspace-per-process model (ADR 0005).
        """
        from langstage_core import workspace_root

        os.chdir(workspace_root())

    def run(self, open_browser: bool = True):
        """Start the FastAPI server with uvicorn.

        **Scripts / CLI** (no running event loop): blocks, as always.

        **Notebooks** (a Jupyter kernel — or any already-running asyncio loop):
        serves on a background thread and returns a :class:`BackgroundServer`
        immediately, so ``app.run()`` just works with no extra code and the kernel
        stays interactive. Blocking would be useless there, and ``uvicorn.run()``
        can't start inside a running loop at all — it raised ``RuntimeError:
        Cannot run the event loop while another loop is running`` (gh #87).
        Call ``.stop()`` on the returned handle to shut it down.
        """
        app = self.create_server()
        self._enter_workspace()

        url = f"http://{self.config.host}:{self.config.port}"
        # Point power users at the built-in, always-in-sync REST API docs — the
        # FastAPI OpenAPI schema is served but was undocumented/undiscoverable (gh #71).
        print(f"LangStage: {url}  |  REST API docs: {url}/docs")

        if open_browser:
            # Open browser after a short delay (server needs to start first)
            threading.Timer(1.5, webbrowser.open, args=[url]).start()

        log_level = "debug" if self.config.debug else "info"
        if not _in_running_event_loop():
            uvicorn.run(app, host=self.config.host, port=self.config.port, log_level=log_level)
            return None

        return self._serve_in_background(app, url, log_level)

    def _serve_in_background(self, app, url: str, log_level: str) -> "BackgroundServer":
        """Serve on a daemon thread with its own event loop (notebook path, gh #87).

        The thread gets a fresh loop via ``Server.run()`` → ``asyncio.run()``, so it
        never touches the kernel's loop. We wait for the bind to land and raise a
        clean error on failure — otherwise a port clash just kills the thread
        silently (and, if served on the kernel's own loop, uvicorn's
        ``sys.exit(STARTUP_FAILURE)`` takes the whole kernel down with it).
        """
        config = uvicorn.Config(app, host=self.config.host, port=self.config.port,
                                log_level=log_level)
        server = uvicorn.Server(config)

        def _serve() -> None:
            try:
                server.run()  # own thread, own loop (asyncio.run) — never the kernel's
            except SystemExit:
                # uvicorn calls sys.exit(STARTUP_FAILURE) when the bind fails. Swallow
                # it so a notebook doesn't get an unhandled-thread traceback; the
                # started-check below turns it into a clean, actionable error.
                pass

        thread = threading.Thread(target=_serve, daemon=True, name="langstage-server")
        thread.start()

        deadline = time.monotonic() + _STARTUP_TIMEOUT
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        if not server.started:
            server.should_exit = True
            thread.join(timeout=2.0)
            raise RuntimeError(
                f"LangStage failed to start on {self.config.host}:{self.config.port} "
                "(is the port already in use?). Pass a different port=..."
            )
        return BackgroundServer(server, thread, url)

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
):
    """Shorthand: create CoworkApp and run it.

    Blocks in a script; in a notebook it serves on a background thread and returns
    a :class:`BackgroundServer` handle, like :meth:`CoworkApp.run` (gh #87).
    """
    app = CoworkApp(
        agent=agent,
        agent_spec=agent_spec,
        workspace=workspace,
        **kwargs,
    )
    return app.run()


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
