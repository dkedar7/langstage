"""CLI: langstage run [OPTIONS]."""

import click

from langstage.app import CoworkApp
from langstage.config import AppConfig


# The keyless echo agent shipped with the shared core - see `--demo`.
DEMO_AGENT_SPEC = "langstage_core.demo.stub:graph"


@click.group(invoke_without_command=True)
@click.version_option(package_name="langstage", prog_name="langstage")
@click.option(
    "--show-config",
    is_flag=True,
    help="Print the resolved configuration (defaults < langstage.toml < env < CLI) and exit.",
)
@click.pass_context
def main(ctx, show_config):
    """LangStage - every stage for your LangGraph agent (web)."""
    if show_config:
        click.echo(AppConfig.resolve().describe())
        ctx.exit(0)
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command()
@click.option("--agent", "-a", "agent_spec", default=None, help="Agent spec (e.g., my_agent.py:agent)")
@click.option("--demo", is_flag=True, default=False, help="Run with the built-in keyless demo agent - no API key needed")
@click.option("--workspace", default=None, type=click.Path(), help="Workspace directory")
@click.option("--port", default=None, type=int, help="Server port (default: 8050)")
@click.option("--host", default=None, help="Server host (default: localhost)")
@click.option("--debug", is_flag=True, default=None, help="Enable debug mode")
@click.option("--title", default=None, help="App title in header bar")
@click.option("--subtitle", default=None, help="Subtitle below title")
@click.option("--welcome-message", default=None, help="Chat welcome message (Markdown)")
@click.option("--theme", default=None, type=click.Choice(["light", "dark", "auto"]), help="UI theme")
@click.option("--agent-name", default=None, help="Display name for the agent (default: agent's .name)")
@click.option("--icon-url", default=None, help="URL to a custom icon image for the header and welcome screen")
@click.option("--auth-username", default=None, help="Basic auth username (default: admin)")
@click.option("--auth-password", default=None, help="Basic auth password (enables auth when set)")
@click.option("--save-workflow-prompt", default=None, help="Custom prompt template for /save-workflow command")
@click.option("--run-workflow-prompt", default=None, help="Custom prompt template for /run-workflow command (use {filename} placeholder)")
@click.option("--create-workflow-prompt", default=None, help="Custom prompt template for /create-workflow command")
@click.option("--custom-css", default=None, type=click.Path(exists=True), help="Path to custom CSS file for theming")
@click.option("--show-canvas/--no-show-canvas", "show_canvas", default=None, help="Force-show or force-hide the Canvas tab (default: auto-detect from CanvasMiddleware)")
@click.option("--show-files/--no-show-files", "show_files", default=None, help="Show or hide the Files tab (default: shown)")
@click.option("--no-browser", is_flag=True, default=False, help="Don't auto-open browser")
def run(agent_spec, demo, workspace, port, host, debug, title, subtitle, welcome_message, theme, agent_name, icon_url, auth_username, auth_password, save_workflow_prompt, run_workflow_prompt, create_workflow_prompt, custom_css, show_canvas, show_files, no_browser):
    """Start the LangStage server."""
    if demo:
        if agent_spec:
            raise click.UsageError("--demo and --agent are mutually exclusive.")
        agent_spec = DEMO_AGENT_SPEC
    try:
        app = CoworkApp(
            agent_spec=agent_spec,
            workspace=workspace,
            port=port,
            host=host,
            debug=debug if debug else None,
            title=title,
            subtitle=subtitle,
            welcome_message=welcome_message,
            theme=theme,
            agent_name=agent_name,
            icon_url=icon_url,
            auth_username=auth_username,
            auth_password=auth_password,
            save_workflow_prompt=save_workflow_prompt,
            run_workflow_prompt=run_workflow_prompt,
            create_workflow_prompt=create_workflow_prompt,
            custom_css=custom_css,
            show_canvas=show_canvas,
            show_files=show_files,
        )
    except (RuntimeError, ValueError, FileNotFoundError, AttributeError, ImportError) as e:
        # Two distinct failure classes, both surfaced as a clean one-line CLI error
        # instead of a raw traceback:
        #  - RuntimeError: building the built-in default agent needs the `deepagents`
        #    extra + an LLM key; on a clean `pip install langstage` it isn't there.
        #    (gh #46)
        #  - ValueError / FileNotFoundError / AttributeError / ImportError: the common
        #    `--agent` typos — malformed spec, a path that doesn't exist, a missing
        #    attribute, an unimportable module — all raised by the shared loader. This
        #    mirrors how the sibling `check` command reports the identical failures as
        #    `[fail] failed to load: …` rather than dumping a traceback. (gh #90)
        # Fall back to the exception class name when its message is empty — e.g. a
        # module that raises `NotImplementedError()` (`str(e) == ""`), which would
        # otherwise surface as a bare `Error: ` with nothing after the colon. This
        # keeps `run` in sync with `check`'s identical fallback. (gh #92)
        raise click.ClickException(str(e) or type(e).__name__) from e
    app.run(open_browser=not no_browser)


@main.command()
@click.option("--workspace", default=None, type=click.Path(), help="Workspace directory")
@click.option("--json", "as_json", is_flag=True, default=False,
              help="Emit the resolved config as JSON (each field's value + source, plus the "
                   "TOML files read) so a deploy step can assert what a container resolved.")
def config(workspace, as_json):
    """Show the resolved configuration: each value, its source, and the
    env var / langstage.toml key that sets it."""
    from dataclasses import fields as _fields

    overrides = {"workspace_root": workspace} if workspace else None
    cfg = AppConfig.resolve(overrides=overrides)
    if not as_json:
        click.echo(cfg.describe())
        return

    import json as _json

    def _jsonable(v):
        # Config values are scalars or Paths; keep JSON-native types, stringify the rest.
        return v if isinstance(v, (str, int, float, bool, type(None))) else str(v)

    src = cfg.sources
    payload = {
        "config": {
            f.name: {"value": _jsonable(getattr(cfg, f.name)), "source": src.get(f.name, "default")}
            for f in _fields(cfg)
        },
        "toml_read_from": [str(p) for p in getattr(cfg, "_toml_paths", [])],
    }
    click.echo(_json.dumps(payload, indent=2))


@main.command()
@click.option("--path", "target", default="langstage.toml", type=click.Path(),
              help="Target file or directory (default: ./langstage.toml).")
@click.option("--force", is_flag=True, default=False, help="Overwrite an existing file.")
def init(target, force):
    """Scaffold a commented langstage.toml (the inverse of `config`).

    Writes a starter config with every option present but commented out, grouped
    into its TOML section and annotated with its env-var equivalent - generated
    from the same metadata `config` reads, so the two never drift.
    """
    from pathlib import Path

    from langstage.config_template import render_langstage_toml

    dest = Path(target)
    # A directory target (existing dir, or a path ending in a separator) → drop
    # langstage.toml inside it; otherwise `target` is the file to write.
    if dest.is_dir() or str(target).endswith(("/", "\\")):
        dest = dest / "langstage.toml"
    if dest.exists() and not force:
        raise click.ClickException(f"{dest} already exists. Use --force to overwrite.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_langstage_toml(), encoding="utf-8")
    click.echo(f"Wrote {dest}  -  edit it, then `langstage config` to verify.")


def _load_error_detail(e: BaseException) -> str:
    """Format a load-time exception as one actionable line, prefixed with its class.

    Falls back to the bare class name when ``str(e)`` is empty — e.g.
    ``NotImplementedError()``, which any model that doesn't support tool-calling
    raises from ``bind_tools()`` inside ``create_react_agent(...)``. Without the
    fallback the human `check` line and the `--json` error would end in a bare
    `: ` with nothing after it. Shared by both so they can't drift. (gh #92)
    """
    return f"{type(e).__name__}: {e}" if str(e) else type(e).__name__


def _agent_tool_names(agent) -> set[str] | None:
    """Best-effort: pull bound tool names out of a compiled graph. Returns None
    if the graph can't be introspected (capabilities may still work)."""
    try:
        names: set[str] = set()
        nodes = getattr(agent, "nodes", None) or {}
        for node in nodes.values():
            target = getattr(node, "bound", node)
            tbn = getattr(target, "tools_by_name", None)
            if isinstance(tbn, dict):
                names.update(tbn.keys())
        return names or None
    except Exception:  # noqa: BLE001 - introspection is inherently best-effort
        return None


@main.command()
@click.option("--agent", "-a", "agent_spec", default=None, help="Agent spec to check (e.g., my_agent.py:agent)")
@click.option("--demo", is_flag=True, default=False, help="Check the built-in demo agent instead")
@click.option("--live", is_flag=True, default=False,
              help="Also run ONE real turn through the agent (needs a working "
                   "model/key) and fail if it errors — a true readiness gate, "
                   "beyond the static checks. Uses the shared langstage-core preflight.")
@click.option("--json", "as_json", is_flag=True, default=False,
              help="Emit the result as a stable JSON object (loads, agent_name, per-check "
                   "ok/detail, live) instead of human lines, preserving the exit-code "
                   "contract — so CI can gate on individual findings (e.g. "
                   "`... --json | jq -e '.loads and .checks.canvas.ok'`).")
def check(agent_spec, demo, live, as_json):
    """Preflight a bring-your-own agent: load it and report which LangStage
    features will light up (and which need a convention or tool to unlock).

    The static checks are fast and need no API key. Add ``--live`` to also run one
    real turn and fail if the agent errors — the same readiness a first chat would
    prove, so a runnable-but-broken agent (bad key, tool that fails at runtime)
    doesn't pass here and die at chat time.

    Add ``--json`` for a machine-readable object (same exit codes) so a pipeline can
    gate on any individual check, not just the coarse pass/fail."""
    import json as _json

    from langstage_core import load_agent_spec
    from langstage.middleware import agent_uses_canvas_middleware

    spec = DEMO_AGENT_SPEC if demo else agent_spec
    if not spec:
        raise click.UsageError("Provide --agent <spec> (or --demo).")

    ok = click.style("[ ok ]", fg="green")
    warn = click.style("[warn]", fg="yellow")
    fail = click.style("[fail]", fg="red")

    # The structured result is built alongside the human lines so the two can't
    # diverge; `--json` prints it and suppresses the human output (gh #73).
    report = {
        "spec": spec,
        "loads": False,
        "agent_name": None,
        "checks": {},
        "live": {"ran": False},
        "ok": False,
    }

    def say(msg):
        if not as_json:
            click.echo(msg)

    def finish(code):
        # Single exit point: stamp overall ok, emit JSON in --json mode, preserve the
        # exit-code contract (1 = load failure / not runnable / --live error; else 0).
        report["ok"] = code == 0
        if as_json:
            click.echo(_json.dumps(report, indent=2))
        raise SystemExit(code)

    say(f"Checking agent: {spec}\n")
    try:
        agent = load_agent_spec(spec)
    except Exception as e:  # noqa: BLE001 - report load failure cleanly
        detail = _load_error_detail(e)  # falls back to the class name for a message-less exc (gh #92)
        report["error"] = detail
        say(f"{fail} failed to load: {detail}")
        finish(1)

    # Loading the object is not enough — the server drives the agent via
    # astream(), so a non-runnable object (an uncompiled StateGraph, a dict, an
    # int) starts fine and then dies mid-stream with "'X' object has no attribute
    # 'astream'". Preflight exists to catch exactly that, so gate the all-clear
    # on runnability instead of reporting `[ ok ] loads` for any object. (gh #39)
    if not callable(getattr(agent, "astream", None)):
        if callable(getattr(agent, "compile", None)):
            # The single most common BYO mistake: exported the builder, not the
            # compiled graph (forgot `.compile()`).
            detail = (f"not runnable: this is an uncompiled {type(agent).__name__} - "
                      "call .compile() and export the result")
        else:
            detail = (f"not runnable: loaded a {type(agent).__name__}, which is not a LangGraph "
                      "graph (no astream()). Export a compiled graph (module:attr or file.py:attr).")
        report["error"] = detail
        say(f"{fail} {detail}")
        finish(1)

    report["loads"] = True
    say(f"{ok} loads")
    name = getattr(agent, "name", None)
    report["agent_name"] = name
    if name:
        say(f"{ok} agent name: {name}")

    # Checkpointer - LangStage auto-attaches an in-memory one if absent.
    has_ckpt = getattr(agent, "checkpointer", None) is not None
    report["checks"]["checkpointer"] = {
        "ok": has_ckpt,
        "detail": "present (memory + interrupts + review gate)" if has_ckpt
        else "none - in-memory attached (supply your own for durability)",
    }
    say(f"{ok} checkpointer present (memory + interrupts + review gate)" if has_ckpt
        else f"{warn} no checkpointer - LangStage will attach an in-memory one "
             "(supply your own for durability across restarts)")

    # Canvas
    has_canvas = agent_uses_canvas_middleware(agent)
    report["checks"]["canvas"] = {
        "ok": has_canvas,
        "detail": "CanvasMiddleware detected" if has_canvas else "no CanvasMiddleware",
    }
    say(f"{ok} CanvasMiddleware detected - Canvas tab will show" if has_canvas
        else f"{warn} no CanvasMiddleware - Canvas hidden (attach it to enable)")

    # Capability tools (best-effort introspection)
    tools = _agent_tool_names(agent)
    introspected = tools is not None
    if not introspected:
        say(f"{warn} could not introspect tools - the checks below are best-effort")
        tools = set()
    has_task = any(t.endswith("async_task") or t.endswith("async_tasks") for t in tools)
    has_cron = "schedule_run" in tools
    has_todos = "write_todos" in tools

    def _detail(present, absent_msg):
        if present:
            return "present"
        return absent_msg if introspected else f"{absent_msg} (tools not introspectable)"

    report["checks"]["write_todos"] = {"ok": has_todos, "detail": _detail(has_todos, "not found")}
    report["checks"]["async_tasks"] = {"ok": has_task, "detail": _detail(has_task, "not found")}
    report["checks"]["schedules"] = {"ok": has_cron, "detail": _detail(has_cron, "not found")}
    say(f"{ok if has_todos else warn} write_todos "
        + ("present - Plan tab will populate" if has_todos else "not found - Plan tab may stay empty"))
    say(f"{ok if has_task else warn} async task tools "
        + ("present - agent can self-delegate" if has_task
           else "not found - add `from langstage import LANGSTAGE_TOOLS` to your agent's tools"))
    say(f"{ok if has_cron else warn} schedule tools "
        + ("present - agent can create schedules" if has_cron else "not found (LANGSTAGE_TOOLS adds these too)"))

    # --live: the static checks above prove the agent is a runnable graph, not that
    # it can actually complete a turn (a bad key / a tool that fails at runtime / a
    # broken state schema all pass static and die at first chat). Run one real turn
    # through the shared langstage-core preflight and fail the check if it errors —
    # so a green `check --live` is a true readiness gate. (ADR 0004)
    if live:
        from langstage_core.agui import verify as _core_verify

        say("")
        result = _core_verify(agent)
        report["live"] = {"ran": True, "ok": bool(result.ok)}
        if result.ok:
            say(f"{ok} live turn: {result.reason}")
        else:
            report["live"]["error"] = result.reason
            say(f"{fail} live turn failed: {result.reason}")
            finish(1)

    # Everything above preflights the *agent*. This one preflights the *install*:
    # a wheel that shipped without the SPA serves a JSON placeholder at `/` and
    # gives no other signal, so a CI gate could pass a deploy whose entire UI is
    # missing. Reported as a warning, not a failure — the REST/WS API works fine
    # without it and a backend-only install is supported — so the exit-code
    # contract is unchanged. (gh #96)
    from langstage.server.main import frontend_bundled

    has_frontend = frontend_bundled()
    report["checks"]["frontend"] = {
        "ok": has_frontend,
        "detail": "bundled SPA present" if has_frontend
        else "bundled frontend missing - web UI unavailable (JSON placeholder only)",
    }
    say(f"{ok} bundled frontend present - web UI will serve" if has_frontend
        else f"{warn} bundled frontend missing - web UI unavailable "
             "(JSON placeholder only); reinstall or `cd frontend && npm run build`")

    say("\nAlways available from the UI regardless of the agent: chat, "
        "tool-call view, file browser, the task board (delegate), and schedules.")
    finish(0)


if __name__ == "__main__":
    main()
