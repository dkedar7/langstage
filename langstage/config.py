"""Configuration for langstage.

`AppConfig` is a `HostConfig` subclass: it inherits the shared keys (agent_spec,
workspace_root, host, port, debug, title) and adds cowork's UI keys, all
resolved through the shared chain — defaults < deepagents.toml < DEEPAGENT_* env
< overrides (Python/CLI args). cowork gains `deepagents.toml` support this way.
"""
import os
import warnings
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, ClassVar, Optional

from langgraph_stream_parser.host import HostConfig


def _env_canonical_first(canonical: str, legacy: str) -> Optional[str]:
    """Read an env var by its canonical ``LANGSTAGE_*`` name, falling back to the
    deprecated ``DEEPAGENT_*`` name (with a warning). Canonical wins."""
    value = os.getenv(canonical)
    if value is not None:
        return value
    legacy_value = os.getenv(legacy)
    if legacy_value is not None:
        warnings.warn(
            f"{legacy} is deprecated; use {canonical}.",
            DeprecationWarning,
            stacklevel=2,
        )
        return legacy_value
    return None


def _parse_optional_bool(value: Optional[str]) -> Optional[bool]:
    """Parse an env-var string into an optional bool.

    True for '1'/'true'/'yes'/'on', False for '0'/'false'/'no'/'off', None for
    empty/unrecognized (auto-detect mode).
    """
    if value is None or value == "":
        return None
    lowered = str(value).strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    return None


# Module-level constants used by tools.py (bash cwd + file tools) and
# default_agent.py. Canonical LANGSTAGE_* first, deprecated DEEPAGENT_* fallback.
# Reading ONLY the legacy names here while default_agent.py honored the canonical
# LANGSTAGE_WORKSPACE_ROOT created a split-brain: the file browser used the
# canonical workspace but the agent's bash/file tools ran in cwd (gh #-dogfood).
# This is the single source — default_agent.py imports WORKSPACE_ROOT from here.
_ws = _env_canonical_first("LANGSTAGE_WORKSPACE_ROOT", "DEEPAGENT_WORKSPACE_ROOT")
WORKSPACE_ROOT = Path(_ws) if _ws else Path(os.getcwd())
_vfs = _env_canonical_first("LANGSTAGE_VIRTUAL_FS", "DEEPAGENT_VIRTUAL_FS")
VIRTUAL_FS = (_vfs or "").lower() in ("1", "true", "yes")

_SAVE_PROMPT = (
    "Please capture this conversation as a detailed workflow markdown file in "
    "the ./workflows/ directory. Include: a title, description of the goal, "
    "step-by-step instructions that could be followed to reproduce this "
    "workflow, any configuration or parameters needed, and expected outputs."
)
_RUN_PROMPT = (
    "Please read and follow the workflow defined in ./workflows/{filename}. "
    "Execute each step as described in the workflow file."
)
_CREATE_PROMPT = (
    "Please create a new workflow markdown file in the ./workflows/ directory. "
    "Include: a title, description of the goal, step-by-step instructions to "
    "execute the workflow, any configuration or parameters needed, and "
    "expected outputs."
)


@dataclass
class AppConfig(HostConfig):
    # Shared keys (agent_spec, workspace_root, host, port, debug) come from
    # HostConfig; cowork only overrides the title default and adds UI keys.
    title: str = "LangStage"
    subtitle: str = "AI-Powered Workspace"
    welcome_message: str = ""
    theme: str = "auto"  # "light" | "dark" | "auto"
    agent_name: str = "Agent"
    icon_url: str = ""
    # Default "admin" lives here (the resolved-config layer) so --show-config,
    # --help, the README, and the runtime all agree on the effective username.
    # Auth is inert unless auth_password is set, so this has no security effect.
    # (gh #35)
    auth_username: str = "admin"
    auth_password: str = ""
    save_workflow_prompt: str = _SAVE_PROMPT
    run_workflow_prompt: str = _RUN_PROMPT
    create_workflow_prompt: str = _CREATE_PROMPT
    custom_css: str = ""
    # None means auto-resolve (canvas auto-detects middleware; files defaults True).
    show_canvas: Optional[bool] = None
    show_files: Optional[bool] = None

    _ENV: ClassVar[dict] = {
        "subtitle": ("DEEPAGENT_SUBTITLE", str),
        "welcome_message": ("DEEPAGENT_WELCOME_MESSAGE", str),
        "theme": ("DEEPAGENT_THEME", str),
        "agent_name": ("DEEPAGENT_AGENT_NAME", str),
        "icon_url": ("DEEPAGENT_ICON_URL", str),
        "auth_username": ("DEEPAGENT_AUTH_USERNAME", str),
        "auth_password": ("DEEPAGENT_AUTH_PASSWORD", str),
        "save_workflow_prompt": ("DEEPAGENT_SAVE_WORKFLOW_PROMPT", str),
        "run_workflow_prompt": ("DEEPAGENT_RUN_WORKFLOW_PROMPT", str),
        "create_workflow_prompt": ("DEEPAGENT_CREATE_WORKFLOW_PROMPT", str),
        "custom_css": ("DEEPAGENT_CUSTOM_CSS", str),
        "show_canvas": ("DEEPAGENT_SHOW_CANVAS", _parse_optional_bool),
        "show_files": ("DEEPAGENT_SHOW_FILES", _parse_optional_bool),
    }
    _TOML: ClassVar[dict] = {
        "subtitle": "ui.subtitle",
        "welcome_message": "ui.welcome_message",
        "theme": "ui.theme",
        "agent_name": "ui.agent_name",
        "icon_url": "ui.icon_url",
        "auth_username": "auth.username",
        "auth_password": "auth.password",
        "save_workflow_prompt": "workflow.save_prompt",
        "run_workflow_prompt": "workflow.run_prompt",
        "create_workflow_prompt": "workflow.create_prompt",
        "custom_css": "ui.custom_css",
        "show_canvas": "ui.show_canvas",
        "show_files": "ui.show_files",
    }

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Env + defaults view (no TOML). Use resolve() for the full chain."""
        return cls.resolve(use_toml=False)

    def merge(self, overrides: dict) -> "AppConfig":
        """Return a copy with non-None overrides applied (dict-based)."""
        valid = {f.name for f in fields(self)}
        applied = {k: v for k, v in overrides.items() if v is not None and k in valid}
        return replace(self, **applied)

    def to_client_dict(self) -> dict:
        """Config values the frontend needs.

        Unresolved show_* flags (None) surface as True so the UI stays
        permissive — CoworkApp resolves None to a concrete bool before this
        reaches the client.
        """
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "welcome_message": self.welcome_message,
            "theme": self.theme,
            "workspace_name": self.workspace_root.name,
            "agent_name": self.agent_name,
            "icon_url": self.icon_url,
            "save_workflow_prompt": self.save_workflow_prompt,
            "run_workflow_prompt": self.run_workflow_prompt,
            "create_workflow_prompt": self.create_workflow_prompt,
            "show_canvas": True if self.show_canvas is None else self.show_canvas,
            "show_files": True if self.show_files is None else self.show_files,
        }
