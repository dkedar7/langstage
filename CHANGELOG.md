# Changelog

## 0.2.1 — 2026-02-08

Fix wheel build to include frontend static assets.

## 0.2.0 — 2026-02-06

Initial release of `cowork-dash`.

### Features

- Chat interface with real-time token streaming via WebSocket
- Tool call visualization with inline display of arguments, results, duration, and status
- Rich inline content rendering: HTML, Plotly charts, images, DataFrames, PDFs, JSON
- Canvas panel for persistent visualizations (Plotly, matplotlib, Mermaid diagrams, DataFrames, Markdown, images)
- File browser with syntax-highlighted viewer and live file change detection
- Task tracking sidebar with progress bar, synced with agent `write_todos` calls
- Human-in-the-loop interrupt dialog for reviewing and approving agent actions
- Token usage counter with per-turn breakdown chart
- Light, dark, and system-auto theming
- Customizable title, subtitle, welcome message, agent name, and icon
- CLI (`cowork-dash run`) and Python API (`CoworkApp`, `run_app`)
- Configuration via Python args, CLI flags, or environment variables
