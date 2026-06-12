"""CLI: langstage run [OPTIONS]."""

import click

from langstage.app import CoworkApp
from langstage.config import AppConfig


# The keyless echo agent shipped with the shared core — see `--demo`.
DEMO_AGENT_SPEC = "langgraph_stream_parser.demo.stub:graph"


@click.group(invoke_without_command=True)
@click.option(
    "--show-config",
    is_flag=True,
    help="Print the resolved configuration (defaults < deepagents.toml < env < CLI) and exit.",
)
@click.pass_context
def main(ctx, show_config):
    """LangStage — every stage for your LangGraph agent (web)."""
    if show_config:
        click.echo(AppConfig.resolve().describe())
        ctx.exit(0)
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command()
@click.option("--agent", "-a", "agent_spec", default=None, help="Agent spec (e.g., my_agent.py:agent)")
@click.option("--demo", is_flag=True, default=False, help="Run with the built-in keyless demo agent — no API key needed")
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
    env var / deepagents.toml key that sets it."""
    overrides = {"workspace_root": workspace} if workspace else None
    click.echo(AppConfig.resolve(overrides=overrides).describe())


if __name__ == "__main__":
    main()
