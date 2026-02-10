"""Configuration resolution: Python args > CLI args > env vars > defaults."""

from dataclasses import dataclass, field
from pathlib import Path
import os

# Module-level constants used by tools.py and agent.py
WORKSPACE_ROOT = Path(os.getenv("DEEPAGENT_WORKSPACE_ROOT", os.getcwd()))
VIRTUAL_FS = os.getenv("DEEPAGENT_VIRTUAL_FS", "").lower() in ("1", "true", "yes")


@dataclass
class AppConfig:
    workspace: Path = field(default_factory=lambda: Path("."))
    agent_spec: str | None = None
    host: str = "localhost"
    port: int = 8050
    debug: bool = False
    title: str = "Cowork Dash"
    subtitle: str = "AI-Powered Workspace"
    welcome_message: str = ""
    theme: str = "auto"  # "light" | "dark" | "auto"
    agent_name: str = "Agent"
    icon_url: str = ""
    auth_username: str = ""
    auth_password: str = ""

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Build config from DEEPAGENT_* environment variables."""
        return cls(
            workspace=Path(os.getenv("DEEPAGENT_WORKSPACE_ROOT", ".")),
            agent_spec=os.getenv("DEEPAGENT_AGENT_SPEC"),
            host=os.getenv("DEEPAGENT_HOST", "localhost"),
            port=int(os.getenv("DEEPAGENT_PORT", "8050")),
            debug=os.getenv("DEEPAGENT_DEBUG", "").lower() in ("1", "true", "yes"),
            title=os.getenv("DEEPAGENT_TITLE", "Cowork Dash"),
            subtitle=os.getenv("DEEPAGENT_SUBTITLE", "AI-Powered Workspace"),
            welcome_message=os.getenv("DEEPAGENT_WELCOME_MESSAGE", ""),
            theme=os.getenv("DEEPAGENT_THEME", "auto"),
            agent_name=os.getenv("DEEPAGENT_AGENT_NAME", "Agent"),
            icon_url=os.getenv("DEEPAGENT_ICON_URL", ""),
            auth_username=os.getenv("DEEPAGENT_AUTH_USERNAME", ""),
            auth_password=os.getenv("DEEPAGENT_AUTH_PASSWORD", ""),
        )

    def merge(self, overrides: dict) -> "AppConfig":
        """Return new config with non-None overrides applied."""
        updates = {k: v for k, v in overrides.items() if v is not None}
        current = {
            "workspace": self.workspace,
            "agent_spec": self.agent_spec,
            "host": self.host,
            "port": self.port,
            "debug": self.debug,
            "title": self.title,
            "subtitle": self.subtitle,
            "welcome_message": self.welcome_message,
            "theme": self.theme,
            "agent_name": self.agent_name,
            "icon_url": self.icon_url,
            "auth_username": self.auth_username,
            "auth_password": self.auth_password,
        }
        current.update(updates)
        return AppConfig(**current)

    def to_client_dict(self) -> dict:
        """Return config values needed by the frontend."""
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "welcome_message": self.welcome_message,
            "theme": self.theme,
            "workspace_name": self.workspace.name,
            "agent_name": self.agent_name,
            "icon_url": self.icon_url,
        }
