"""Configuration for langstage.

`AppConfig` is a `HostConfig` subclass: it inherits the shared keys (agent_spec,
workspace_root, host, port, debug, title) and adds cowork's UI keys, all
resolved through the shared chain — defaults < deepagents.toml < DEEPAGENT_* env
< overrides (Python/CLI args). cowork gains `deepagents.toml` support this way.
"""
import os
import warnings
from dataclasses import dataclass, fields, replace
from typing import ClassVar, Optional

from langstage_core.host import HostConfig


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


# WORKSPACE_ROOT is read by tools.py (bash cwd + file tools) and default_agent.py.
# Since ADR 0005 it is a LIVE VIEW of the shared source of truth
# (core.workspace_root()), not a separate mutable constant: CoworkApp.__init__ calls
# core.apply_workspace(the resolved workspace), and every reader here — the file
# browser and the agent's bash/file/canvas tools — sees that one value. There is no
# mirror to hand-sync and drift, which was the #44 split-brain. Before apply_workspace
# runs, workspace_root() falls back to canonical LANGSTAGE_WORKSPACE_ROOT / legacy
# DEEPAGENT_WORKSPACE_ROOT / cwd — the same import-time default as before.
_vfs = _env_canonical_first("LANGSTAGE_VIRTUAL_FS", "DEEPAGENT_VIRTUAL_FS")
VIRTUAL_FS = (_vfs or "").lower() in ("1", "true", "yes")


def __getattr__(name: str):
    # PEP 562 module getattr: resolve WORKSPACE_ROOT dynamically to the single
    # source of truth so it can't diverge from what the agent's tools use.
    if name == "WORKSPACE_ROOT":
        from langstage_core import workspace_root

        return workspace_root()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

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
    # Empty by default — a generic "AI-Powered Workspace" tagline was filler that
    # cluttered the header. The UI hides the subtitle when unset; set one
    # (--subtitle / LANGSTAGE_SUBTITLE / [ui].subtitle) for a real label.
    subtitle: str = ""
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
    # Task-board worker-pool size (the async delegate/schedule concurrency cap).
    # A first-class resolved field — not a raw os.getenv in server/main.py — so it
    # shows up in --show-config with a value+source, gains a langstage.toml key, and
    # a malformed value is caught by the resolver and reported as a clean CLI error
    # (like --port), instead of an unhandled ValueError traceback at startup. The
    # TaskRunner still clamps it to >= 1, so the effective bound is unchanged. (gh #102)
    task_concurrency: int = 3

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
        # Canonical LANGSTAGE_TASK_CONCURRENCY wins; DEEPAGENT_TASK_CONCURRENCY is the
        # deprecated fallback (resolved by _env_pair, same as every other key). (gh #102)
        "task_concurrency": ("DEEPAGENT_TASK_CONCURRENCY", int),
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
        "task_concurrency": "tasks.concurrency",
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
