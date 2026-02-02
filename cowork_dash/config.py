"""
Configuration file for Cowork Dash.

This file is OPTIONAL and provides sensible defaults. You typically don't need to edit it.

Configuration Priority (highest to lowest):
1. CLI arguments (--workspace, --port, etc.)
2. Environment variables (DEEPAGENT_*)
3. This config file defaults

For most use cases, prefer environment variables or CLI arguments:

  # Using environment variables (recommended for deployment)
  export DEEPAGENT_WORKSPACE_ROOT=/my/project
  export DEEPAGENT_PORT=9000
  cowork-dash run

  # Using CLI arguments (recommended for development)
  cowork-dash run --workspace /my/project --port 9000

Only edit this file if you want to set project-specific defaults that apply
when no environment variables or CLI arguments are provided.
"""

import os
import platform
from pathlib import Path


def is_linux() -> bool:
    """Check if running on Linux."""
    return platform.system() == "Linux"


def get_config(key: str, default=None, type_cast=None):
    """
    Get configuration value with priority:
    1. Environment variable DEEPAGENT_{KEY}
    2. Default value

    Args:
        key: Configuration key (will be uppercased for env var)
        default: Default value if env var not set
        type_cast: Optional function to cast env var value

    Returns:
        Configuration value
    """
    env_value = os.getenv(f"DEEPAGENT_{key.upper()}")
    if env_value is not None:
        return type_cast(env_value) if type_cast else env_value
    return default


# Workspace root directory
# Environment variable: DEEPAGENT_WORKSPACE_ROOT
# CLI argument: --workspace
# Default: current directory
_workspace_path = get_config("workspace_root", default="./")
WORKSPACE_ROOT = Path(_workspace_path).resolve() if _workspace_path else Path("./").resolve()

# Agent specification - supports two formats (both use colon separator):
#   1. File path: "path/to/file.py:object_name"
#   2. Module path: "mypackage.module:object_name"
# Environment variable: DEEPAGENT_SPEC (or DEEPAGENT_AGENT_SPEC for backwards compatibility)
# CLI argument: --agent
# Default: package's built-in agent
# Examples:
#   - "my_agents.py:agent" (file in current directory)
#   - "/path/to/agent.py:my_agent" (absolute path)
#   - "mypackage.agents:my_agent" (installed Python module)
_default_agent = str(Path(__file__).parent / "agent.py") + ":agent"
AGENT_SPEC = get_config("spec", default=None) or get_config("agent_spec", default=None) or _default_agent

# Application title
# Environment variable: DEEPAGENT_APP_TITLE
# CLI argument: --title
APP_TITLE = get_config("app_title", default="Cowork Dash")

# Application subtitle
# Environment variable: DEEPAGENT_APP_SUBTITLE
# CLI argument: --subtitle
APP_SUBTITLE = get_config("app_subtitle", default="AI-Powered Workspace")

# Server port
# Environment variable: DEEPAGENT_PORT
# CLI argument: --port
PORT = get_config("port", default=8050, type_cast=int)

# Server host (use "0.0.0.0" to allow external connections)
# Environment variable: DEEPAGENT_HOST
# CLI argument: --host
HOST = get_config("host", default="localhost")

# Debug mode (set to True for development, False for production)
# Environment variable: DEEPAGENT_DEBUG (accepts: true/1/yes)
# CLI argument: --debug
DEBUG = get_config(
    "debug",
    default=False,
    type_cast=lambda x: str(x).lower() in ("true", "1", "yes")
)

# Welcome message shown when the app starts
# Environment variable: DEEPAGENT_WELCOME_MESSAGE
# Supports markdown formatting
_default_welcome = """This is your AI-powered workspace. I can help you write code, analyze files, create visualizations, and more.

**Getting Started:**
- Type a message below to chat with me
- Browse files on the right (click to view, ↓ to download)
- Switch to **Canvas** tab to see charts and diagrams I create

Let's get started!"""
WELCOME_MESSAGE = get_config("welcome_message", default=_default_welcome)

# Virtual filesystem mode (for multi-user deployments)
# Environment variable: DEEPAGENT_VIRTUAL_FS
# Accepts: true/1/yes to enable
# IMPORTANT: Only available on Linux due to sandboxing requirements
# When enabled:
#   - Each browser session gets isolated in-memory file storage
#   - Files, canvas, and uploads are not shared between sessions
#   - All data is ephemeral (cleared when session ends)
#   - Bash commands run in bubblewrap sandbox for security
# When disabled (default):
#   - All sessions share the same workspace directory on disk
#   - Files persist on disk
_virtual_fs_requested = get_config(
    "virtual_fs",
    default=False,
    type_cast=lambda x: str(x).lower() in ("true", "1", "yes")
)
# Virtual FS is only supported on Linux (requires bubblewrap for bash sandboxing)
VIRTUAL_FS = _virtual_fs_requested and is_linux()
VIRTUAL_FS_UNAVAILABLE_REASON = None if is_linux() else "Virtual filesystem mode requires Linux (uses bubblewrap for bash sandboxing)"

# Session timeout in seconds (only used when VIRTUAL_FS is True)
# Environment variable: DEEPAGENT_SESSION_TIMEOUT
# Default: 3600 (1 hour)
SESSION_TIMEOUT = get_config("session_timeout", default=3600, type_cast=int)
