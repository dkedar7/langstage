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
@click.option("--no-browser", is_flag=True, default=False, help="Don't auto-open browser")
def run(agent_spec, workspace, port, host, debug, title, subtitle, welcome_message, theme, no_browser):
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
    )
    app.run(open_browser=not no_browser)


if __name__ == "__main__":
    main()
