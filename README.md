# Cowork Dash

Web UI for [LangGraph](https://github.com/langchain-ai/langgraph) and [deepagents](https://github.com/dkedar7/deepagents) agents. Provides a chat interface with real-time streaming, a workspace file browser, and a canvas for visualizations.

<p align="center">
  <img src="assets/cover.png" alt="Cowork Dash" style="border: 1px solid #d0d7de; border-radius: 6px;" />
</p>

**Stack**: Python (FastAPI + WebSocket) backend, React (TypeScript + Vite) frontend.

## Features

- **Chat** with real-time token streaming via WebSocket
- **Tool call visualization** — inline display of arguments, results, duration, and status
- **Rich inline content** — HTML, Plotly charts, images, DataFrames, PDFs, and JSON rendered directly in the chat
- **Canvas panel** — persistent visualizations (Plotly, matplotlib, Mermaid diagrams, DataFrames, Markdown, images)
- **File browser** — workspace file tree with syntax-highlighted viewer and live file change detection
- **Task tracking** — sidebar todo list with progress bar, synced with agent `write_todos` calls
- **Human-in-the-loop** — interrupt dialog for reviewing and approving agent actions
- **Token usage** — cumulative counter with per-turn breakdown chart
- **Theming** — light, dark, and system-auto modes
- **Customization** — title, subtitle, welcome message, agent name, and custom icon

## Installation

```bash
pip install cowork-dash
```

## Quick Start

### From Python

```python
from cowork_dash import CoworkApp

app = CoworkApp(
    agent=your_langgraph_agent,  # Any LangGraph CompiledGraph
    workspace="./workspace",
    title="My Agent",
)
app.run()
```

### From CLI

```bash
# Point to a Python file exporting a LangGraph agent
cowork-dash run --agent my_agent.py:agent --workspace ./workspace

# With options
cowork-dash run --agent my_agent.py:agent --port 8080 --theme dark --title "My Agent"
```

### Shorthand

```python
from cowork_dash import run_app

run_app(agent=your_agent, workspace="./workspace")
```

## Configuration

Configuration priority: **Python args > CLI args > environment variables > defaults**.

| Option | CLI Flag | Env Var | Default |
|--------|----------|---------|---------|
| Agent spec | `--agent` | `DEEPAGENT_AGENT_SPEC` | Built-in default agent |
| Workspace | `--workspace` | `DEEPAGENT_WORKSPACE_ROOT` | `.` |
| Host | `--host` | `DEEPAGENT_HOST` | `localhost` |
| Port | `--port` | `DEEPAGENT_PORT` | `8050` |
| Debug | `--debug` | `DEEPAGENT_DEBUG` | `false` |
| Title | `--title` | `DEEPAGENT_TITLE` | Agent's `.name` or `"Cowork Dash"` |
| Subtitle | `--subtitle` | `DEEPAGENT_SUBTITLE` | `"AI-Powered Workspace"` |
| Welcome message | `--welcome-message` | `DEEPAGENT_WELCOME_MESSAGE` | _(empty)_ |
| Theme | `--theme` | `DEEPAGENT_THEME` | `auto` |
| Agent name | `--agent-name` | `DEEPAGENT_AGENT_NAME` | Agent's `.name` or `"Agent"` |
| Icon URL | `--icon-url` | `DEEPAGENT_ICON_URL` | _(none)_ |

## Stream Parser Config

Control how agent events are parsed by passing `stream_parser_config` to `CoworkApp`:

```python
app = CoworkApp(
    agent=agent,
    stream_parser_config={
        "extractors": [...],  # Custom tool extractors
    },
)
```

See [langgraph-stream-parser](https://github.com/dkedar7/langgraph-stream-parser) for details.

## Architecture

```
Browser  <--WebSocket-->  FastAPI  <--astream_events-->  LangGraph Agent
            /ws/chat         |
                        REST APIs:
                          /api/config
                          /api/files/tree
                          /api/files/{path}
                          /api/canvas/items
```

The frontend is pre-built and bundled into the Python package as static files. No Node.js required at runtime.

## Development

```bash
# Backend
pip install -e ".[dev]"
pytest tests/

# Frontend
cd frontend
npm install
npm run build    # outputs to cowork_dash/static/
npm run dev      # dev server with hot reload (proxy to backend on :8050)
```

## License

MIT
