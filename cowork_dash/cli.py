"""CLI: cowork-dash run [OPTIONS]."""

import click

from cowork_dash.app import CoworkApp
from cowork_dash.config import AppConfig


@click.group()
def main():
    """Cowork Dash — Web UI for LangGraph agents."""
    pass


@main.command()
@click.option("--agent", "agent_spec", default=None, help="Agent spec (e.g., my_agent.py:agent)")
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
@click.option("--no-browser", is_flag=True, default=False, help="Don't auto-open browser")
def run(agent_spec, workspace, port, host, debug, title, subtitle, welcome_message, theme, agent_name, icon_url, auth_username, auth_password, save_workflow_prompt, run_workflow_prompt, create_workflow_prompt, custom_css, no_browser):
    """Start the Cowork Dash server."""
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
    )
    app.run(open_browser=not no_browser)


if __name__ == "__main__":
    main()
