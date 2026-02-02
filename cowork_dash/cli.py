#!/usr/bin/env python3
"""Command-line interface for Cowork Dash (formerly DeepAgent Dash)."""

import sys
import shutil
from pathlib import Path
import argparse


def init_project(name: str, template: str = "default"):
    """Initialize a new Cowork Dash project."""
    project_dir = Path(name).resolve()

    if project_dir.exists():
        print(f"❌ Error: Directory '{name}' already exists")
        return 1

    print(f"📦 Creating project: {project_dir}")

    # Create project structure
    project_dir.mkdir(parents=True)
    workspace_dir = project_dir / "workspace"
    workspace_dir.mkdir()

    # Copy config template
    import cowork_dash
    package_dir = Path(cowork_dash.__file__).parent
    template_file = package_dir / "config.py"

    if not template_file.exists():
        print(f"❌ Error: Template not found at {template_file}")
        return 1

    shutil.copy(template_file, project_dir / "config.py")

    # Create .env template
    env_template = """# Cowork Dash Environment Variables

# API Keys
ANTHROPIC_API_KEY=your_api_key_here

# Optional: Override config.py settings (uses DEEPAGENT_* prefix for compatibility)
# DEEPAGENT_WORKSPACE_ROOT=./workspace
# DEEPAGENT_PORT=8050
# DEEPAGENT_HOST=localhost
# DEEPAGENT_DEBUG=False
"""
    (project_dir / ".env.example").write_text(env_template)

    # Create .gitignore
    gitignore = """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
ENV/

# Cowork Dash
.env
workspace/
canvas.md
.canvas/
*.log

# IDE
.vscode/
.idea/
*.swp
*.swo
"""
    (project_dir / ".gitignore").write_text(gitignore)

    # Create README
    readme = f"""# {name}

A Cowork Dash project.

## Setup

1. **Configure your API key** (if using DeepAgents):
   ```bash
   cp .env.example .env
   # Edit .env and add your ANTHROPIC_API_KEY
   ```

2. **Edit config.py** to customize your agent and settings

3. **Run the application**:
   ```bash
   cowork-dash run
   ```

## Usage

```bash
# Run with defaults from config.py
cowork-dash run

# Override settings
cowork-dash run --port 8080 --debug

# Use custom agent
cowork-dash run --agent my_agent.py:agent

# See all options
cowork-dash run --help
```

## Project Structure

```
{name}/
├── config.py          # Main configuration (edit this)
├── workspace/         # Your agent's workspace
├── .env.example       # Environment variables template
└── .gitignore         # Git ignore patterns
```

## Documentation

- [Cowork Dash Documentation](https://github.com/dkedar7/cowork-dash)
- [CLI Usage Guide](https://github.com/dkedar7/cowork-dash/blob/main/docs/CLI_USAGE.md)
"""
    (project_dir / "README.md").write_text(readme)

    print("✓ Created project structure")
    print("✓ Created config.py")
    print("✓ Created workspace/")
    print("✓ Created .env.example")
    print("✓ Created .gitignore")
    print("✓ Created README.md")
    print(f"\n{'='*50}")
    print(f"🎉 Project '{name}' created successfully!")
    print(f"{'='*50}\n")
    print("Next steps:")
    print(f"  1. cd {name}")
    print("  2. cp .env.example .env  # If using DeepAgents")
    print("  3. Edit .env and add your ANTHROPIC_API_KEY")
    print("  4. Edit config.py to customize your agent")
    print("  5. cowork-dash run")
    print()

    return 0


def run_app_cli(args):
    """Run the application with CLI arguments."""
    import platform

    # Import here to avoid loading Dash when just running init
    from .app import run_app

    # Only pass virtual_fs if explicitly set via --virtual-fs flag
    # Otherwise pass None to let env var / config take precedence
    virtual_fs = True if args.virtual_fs else None

    # Warn if --virtual-fs requested on non-Linux
    if args.virtual_fs and platform.system() != "Linux":
        print("⚠️  Warning: --virtual-fs is only supported on Linux")
        print("   Virtual filesystem mode requires Linux for secure bash sandboxing (bubblewrap).")
        print("   Running in physical filesystem mode instead.\n")
        virtual_fs = None  # Let config handle it (will be False)

    return run_app(
        workspace=args.workspace,
        agent_spec=args.agent,
        port=args.port,
        host=args.host,
        debug=args.debug,
        title=args.title,
        welcome_message=args.welcome_message,
        config_file=args.config,
        virtual_fs=virtual_fs
    )


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="cowork-dash",
        description="Cowork Dash - AI Agent Web Interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Initialize a new project
  cowork-dash init my-agent-project

  # Run with defaults from config.py
  cowork-dash run

  # Run with custom settings
  cowork-dash run --workspace ~/projects --port 8080

  # Run with custom agent
  cowork-dash run --agent my_agent.py:agent

  # Debug mode
  cowork-dash run --debug

For more help: https://github.com/dkedar7/cowork-dash
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # cowork-dash init
    init_parser = subparsers.add_parser(
        "init",
        help="Initialize a new project",
        description="Create a new Cowork Dash project with config template"
    )
    init_parser.add_argument("name", help="Project name/directory")
    init_parser.add_argument(
        "--template",
        default="default",
        help="Template to use (default: default)"
    )

    # cowork-dash run
    run_parser = subparsers.add_parser(
        "run",
        help="Run the application",
        description="Run Cowork Dash with optional configuration overrides"
    )
    run_parser.add_argument(
        "--workspace",
        type=str,
        help="Workspace directory path (overrides config.py)"
    )
    run_parser.add_argument(
        "--agent",
        type=str,
        metavar="PATH:OBJECT",
        help='Agent specification as "path/to/file.py:object_name"'
    )
    run_parser.add_argument(
        "--port",
        type=int,
        help="Port to run on (overrides config.py)"
    )
    run_parser.add_argument(
        "--host",
        type=str,
        help="Host to bind to (overrides config.py)"
    )
    run_parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode"
    )
    run_parser.add_argument(
        "--no-debug",
        action="store_true",
        help="Disable debug mode"
    )
    run_parser.add_argument(
        "--title",
        type=str,
        help="Application title (overrides config.py)"
    )
    run_parser.add_argument(
        "--config",
        type=str,
        default="./config.py",
        help="Config file path (default: ./config.py)"
    )
    run_parser.add_argument(
        "--welcome-message",
        type=str,
        dest="welcome_message",
        help="Welcome message shown on startup (supports markdown)"
    )
    run_parser.add_argument(
        "--virtual-fs",
        action="store_true",
        dest="virtual_fs",
        help="Use in-memory virtual filesystem (ephemeral, for multi-user isolation)"
    )

    # Parse arguments
    args = parser.parse_args()

    # Handle commands
    if args.command == "init":
        return init_project(args.name, args.template)

    elif args.command == "run":
        return run_app_cli(args)

    else:
        # No command provided - show help
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
