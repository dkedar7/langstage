"""Configuration resolution: Python args > CLI args > env vars > defaults."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import os


def _parse_optional_bool(value: Optional[str]) -> Optional[bool]:
    """Parse an env-var string into an optional bool.

    Returns True for '1'/'true'/'yes', False for '0'/'false'/'no', and
    None for empty/unset (auto-detect mode).
    """
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered in ("1", "true", "yes"):
        return True
    if lowered in ("0", "false", "no"):
        return False
    return None

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
    save_workflow_prompt: str = "Please capture this conversation as a detailed workflow markdown file in the ./workflows/ directory. Include: a title, description of the goal, step-by-step instructions that could be followed to reproduce this workflow, any configuration or parameters needed, and expected outputs."
    run_workflow_prompt: str = "Please read and follow the workflow defined in ./workflows/{filename}. Execute each step as described in the workflow file."
    create_workflow_prompt: str = "Please create a new workflow markdown file in the ./workflows/ directory. Include: a title, description of the goal, step-by-step instructions to execute the workflow, any configuration or parameters needed, and expected outputs."
    custom_css: str = ""
    # Tab visibility — None means auto-resolve (canvas auto-detects middleware;
    # files defaults to True). Explicit True/False overrides auto-detection.
    show_canvas: Optional[bool] = None
    show_files: Optional[bool] = None

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
            save_workflow_prompt=os.getenv("DEEPAGENT_SAVE_WORKFLOW_PROMPT", AppConfig.save_workflow_prompt),
            run_workflow_prompt=os.getenv("DEEPAGENT_RUN_WORKFLOW_PROMPT", AppConfig.run_workflow_prompt),
            create_workflow_prompt=os.getenv("DEEPAGENT_CREATE_WORKFLOW_PROMPT", AppConfig.create_workflow_prompt),
            custom_css=os.getenv("DEEPAGENT_CUSTOM_CSS", ""),
            show_canvas=_parse_optional_bool(os.getenv("DEEPAGENT_SHOW_CANVAS")),
            show_files=_parse_optional_bool(os.getenv("DEEPAGENT_SHOW_FILES")),
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
            "save_workflow_prompt": self.save_workflow_prompt,
            "run_workflow_prompt": self.run_workflow_prompt,
            "create_workflow_prompt": self.create_workflow_prompt,
            "custom_css": self.custom_css,
            "show_canvas": self.show_canvas,
            "show_files": self.show_files,
        }
        current.update(updates)
        return AppConfig(**current)

    def to_client_dict(self) -> dict:
        """Return config values needed by the frontend.

        Unresolved show_* flags (None) are surfaced as True so the UI stays
        permissive — the resolver in CoworkApp is responsible for turning
        None into a concrete bool before the config reaches the client.
        """
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "welcome_message": self.welcome_message,
            "theme": self.theme,
            "workspace_name": self.workspace.name,
            "agent_name": self.agent_name,
            "icon_url": self.icon_url,
            "save_workflow_prompt": self.save_workflow_prompt,
            "run_workflow_prompt": self.run_workflow_prompt,
            "create_workflow_prompt": self.create_workflow_prompt,
            "show_canvas": True if self.show_canvas is None else self.show_canvas,
            "show_files": True if self.show_files is None else self.show_files,
        }
