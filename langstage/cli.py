"""CLI: langstage run [OPTIONS]."""

import click

from langstage.app import CoworkApp
from langstage.config import AppConfig


# The keyless echo agent shipped with the shared core - see `--demo`.
DEMO_AGENT_SPEC = "langgraph_stream_parser.demo.stub:graph"


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
    app.run(open_browser=not no_browser)


@main.command()
@click.option("--workspace", default=None, type=click.Path(), help="Workspace directory")
def config(workspace):
    """Show the resolved configuration: each value, its source, and the
    env var / langstage.toml key that sets it."""
    overrides = {"workspace_root": workspace} if workspace else None
    click.echo(AppConfig.resolve(overrides=overrides).describe())


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
def check(agent_spec, demo):
    """Preflight a bring-your-own agent: load it and report which LangStage
    features will light up (and which need a convention or tool to unlock)."""
    from langgraph_stream_parser import load_agent_spec
    from langstage.middleware import agent_uses_canvas_middleware

    spec = DEMO_AGENT_SPEC if demo else agent_spec
    if not spec:
        raise click.UsageError("Provide --agent <spec> (or --demo).")

    ok = click.style("[ ok ]", fg="green")
    warn = click.style("[warn]", fg="yellow")

    click.echo(f"Checking agent: {spec}\n")
    try:
        agent = load_agent_spec(spec)
    except Exception as e:  # noqa: BLE001 - report load failure cleanly
        click.echo(f"{click.style('[fail]', fg='red')} failed to load: {e}")
        raise SystemExit(1)
    click.echo(f"{ok} loads")
    name = getattr(agent, "name", None)
    if name:
        click.echo(f"{ok} agent name: {name}")

    # Checkpointer - LangStage auto-attaches an in-memory one if absent.
    if getattr(agent, "checkpointer", None) is not None:
        click.echo(f"{ok} checkpointer present (memory + interrupts + review gate)")
    else:
        click.echo(f"{warn} no checkpointer - LangStage will attach an in-memory one "
                   "(supply your own for durability across restarts)")

    # Canvas
    if agent_uses_canvas_middleware(agent):
        click.echo(f"{ok} CanvasMiddleware detected - Canvas tab will show")
    else:
        click.echo(f"{warn} no CanvasMiddleware - Canvas hidden (attach it to enable)")

    # Capability tools (best-effort introspection)
    tools = _agent_tool_names(agent)
    if tools is None:
        click.echo(f"{warn} could not introspect tools - the checks below are best-effort")
        tools = set()
    has_task = any(t.endswith("async_task") or t.endswith("async_tasks") for t in tools)
    has_cron = "schedule_run" in tools
    has_todos = "write_todos" in tools
    click.echo(f"{ok if has_todos else warn} write_todos "
               + ("present - Plan tab will populate" if has_todos else "not found - Plan tab may stay empty"))
    click.echo(f"{ok if has_task else warn} async task tools "
               + ("present - agent can self-delegate" if has_task
                  else "not found - add `from langstage import LANGSTAGE_TOOLS` to your agent's tools"))
    click.echo(f"{ok if has_cron else warn} schedule tools "
               + ("present - agent can create schedules" if has_cron else "not found (LANGSTAGE_TOOLS adds these too)"))

    click.echo("\nAlways available from the UI regardless of the agent: chat, "
               "tool-call view, file browser, the task board (delegate), and schedules.")


if __name__ == "__main__":
    main()
