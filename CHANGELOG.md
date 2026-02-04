# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.2] - 2026-02-03

### Fixed
- **Sidebar collapse**: Sidebar now fully collapses with minimal expand button width
- **Chat panel expansion**: Chat panel expands to fill space when sidebar is hidden

### Changed
- **Tool call display**: Tool calls now show first 100 characters of arguments in header

## [0.2.1] - 2026-02-03

### Added
- **Collapsible sidebar**: New toggle button to collapse/expand the files/canvas panel
- **Download buttons**: Each display_inline asset now has a download button
- **Ordered content rendering**: AI messages, thinking blocks, and display_inline assets now appear in emission order
- **Fullscreen preview**: HTML and PDF files can be previewed in fullscreen modal

### Changed
- **Non-collapsible thinking blocks**: Thinking is always visible with purple left border styling
- **Reduced AI text spacing**: Tighter spacing between consecutive AI message blocks
- **add_to_canvas/display_inline**: Now agent-only tools (removed from notebook namespace injection)

### Fixed
- **display_inline file content**: Fixed reading file content when display_type is explicitly set
- **ctx undefined error**: Fixed NameError in fullscreen preview callback

## [0.2.0] - 2026-02-01

### Added
- **display_inline tool**: Rich inline content rendering for images, DataFrames, CSV, HTML, JSON, and PDF files
- **think_tool integration**: Agent reasoning is now visible in chat with collapsible thinking blocks
- **"Add to Canvas" button**: Display inline results can be added to canvas directly from chat
- **Sandboxed bash execution**: Virtual FS mode now supports safe bash commands using bubblewrap isolation (Linux only)
- **CSV/TSV file preview**: File modal now shows tabular data with pagination
- **Comprehensive test suite**: Added tests for CLI, run_app API, agent loading, config, and components

### Changed
- **Redesigned UI**: Minimal professional styling with improved visual hierarchy
- **Loading indicator**: Replaced verbose "AGENT" + "Thinking" header with clean DMC dots loader
- **Tool call rendering**: Simplified with CSS classes for better consistency

### Fixed
- **HITL interrupt handling**: Tool calls now correctly show status after human-in-the-loop approval
- **Duplicate tool calls**: Fixed issue where tool calls appeared twice after resuming from interrupt
- **Breadcrumb bar dark mode**: Fixed background color in dark theme
- **Expanded folders during execution**: Fixed folders showing "Loading..." during agent runs

### Platform
- **Virtual FS restricted to Linux**: `--virtual-fs` flag now only works on Linux (shows warning on other platforms)
- **CLI warning**: Added helpful message when `--virtual-fs` is used on non-Linux systems

## [0.1.9] - 2026-01-28

### Changed
- Updated lock file version reference

## [0.1.8] - 2026-01-27

### Fixed
- Catch AttributeError when importing pandas on partially initialized module (Linux compatibility)

## [0.1.7] - 2026-01-26

### Added
- Virtual filesystem mode (`--virtual-fs` flag) for multi-user session isolation
- VirtualFilesystem, VirtualPath, and SessionManager classes for in-memory storage
- VirtualFilesystemBackend implementing DeepAgents' BackendProtocol
- Session-aware agent factory creating per-session agents with isolated backends
- Comprehensive test suite with 184 tests covering virtual FS, backends, canvas, and file utilities
- Tool context system for session-aware file operations

### Changed
- File and canvas utilities now support both physical and virtual filesystems
- CLI updated with `--virtual-fs` flag for ephemeral session mode

### Removed
- Dead code cleanup: removed 156 lines of unused imports, functions, and debug methods
- Removed obsolete CLI_USAGE.md documentation

## [0.1.6] - 2026-01-25

### Fixed
- Duplicate agent response rendering issue
- Agent state now resets on page refresh for clean sessions
- Tool calls indicator disappearing during execution (race condition fix)
- Missing return value in interrupt handling callback
- Default agent workspace now uses environment variable or current directory

## [0.1.5] - 2026-01-24

### Added
- Stop button to halt agent execution mid-run
- Clear canvas confirmation modal with archive functionality
- Canvas item collapse/expand and delete features
- Folder selection and creation in file browser
- Double-click folders to change working directory
- Demo video and screenshots in README

### Changed
- Default agent workspace root changed to "/" for full virtual filesystem access
- Simplified README with concise installation instructions
- Mermaid diagrams now respect light/dark theme changes

### Removed
- requirements.txt (dependencies managed via pyproject.toml)

## [0.1.4] - 2026-01-20

### Added
- App title and subtitle can be set dynamically from agent `name` and `description` attributes

### Fixed
- Tool call error detection now uses precise patterns to avoid false positives (e.g., reading files about errors no longer marks tool as failed)

## [0.1.3] - 2026-01-20

### Added
- Support for Python module format in agent spec (e.g., `mypackage.module.agent`)
- Agent spec now accepts both file path (`file.py:object`) and module path formats

### Fixed
- Header layout on large screens - components now stay at edges instead of centering

## [0.1.2] - 2026-01-19

### Added
- Auto-scroll chat messages to bottom when new content is added
- SVG favicon support with custom logo
- Response time display for agent messages (e.g., "23s" or "1m 43s")
- Persistent todos in chat history (todos now stick like tool calls)
- dash-iconify as a required dependency

### Changed
- Eliminated index.html template - all styles now in styles.css
- Simplified app configuration with inline index string for favicon only
- Improved todo rendering to support list format from agent output
- Default agent spec now points to package's agent.py

### Fixed
- Terminal and refresh button icons not visible (switched to mdi icons)
- dangerously_allow_html incorrectly passed to html.Div instead of dcc.Markdown
- Todo items not rendering (format_todos now handles both list and dict formats)

### UI/UX
- Added Google Fonts import directly in CSS
- Consolidated all animations and styles in styles.css
- Dark mode support for all new components

## [0.1.1] - 2025-11-29

### Added
- Environment variable configuration support for all settings with `DEEPAGENT_*` prefix
- Configuration priority system: CLI args > Environment variables > config.py defaults
- Enhanced Python API: `run_app()` now accepts agent instance as first parameter
- Comprehensive test suite with 15 core functionality tests (CLI, Python API, agent loading)
- `uvx` compatibility for running without installation
- Python API examples demonstrating three usage patterns
- Environment variable `DEEPAGENT_WORKSPACE_ROOT` automatically set for agents

### Changed
- **BREAKING**: `run_app()` signature updated - `agent_instance` is now the first parameter (optional)
- README reduced by 56% for better clarity while maintaining all essential information
- Configuration documentation enhanced with clear priority hierarchy
- Agent priority in `run_app()`: agent_spec > agent_instance > config file
- Made all configuration settings clearly marked as optional in documentation

### Fixed
- Path conversion issue in config.py when using environment variables
- Test suite patch targets for proper CLI testing

### Documentation
- Added comprehensive environment variables documentation
- Added `uvx` installation and usage examples
- Updated Python API examples to show new agent instance pattern
- Clarified configuration priority in all documentation
- Added example agent setup with DeepAgents integration

## [0.1.0] - 2025-11-26

### Added
- Initial release
- AI Agent Chat with real-time streaming
- File Browser with interactive file tree and lazy loading
- Canvas for visualizing DataFrames, Plotly/Matplotlib charts, Mermaid diagrams, images
- Flexible configuration via config.py
- CLI interface with `cowork-dash` command
- Python API with `run_app()` function
- Support for custom agents via agent specification
- Manual mode (file browser only, no agent)
- Resizable split-pane interface
- Upload/download functionality for files

[0.2.2]: https://github.com/dkedar7/cowork-dash/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/dkedar7/cowork-dash/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/dkedar7/cowork-dash/compare/v0.1.9...v0.2.0
[0.1.9]: https://github.com/dkedar7/cowork-dash/compare/v0.1.8...v0.1.9
[0.1.8]: https://github.com/dkedar7/cowork-dash/compare/v0.1.7...v0.1.8
[0.1.7]: https://github.com/dkedar7/cowork-dash/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/dkedar7/cowork-dash/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/dkedar7/cowork-dash/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/dkedar7/cowork-dash/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/dkedar7/cowork-dash/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/dkedar7/cowork-dash/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/dkedar7/cowork-dash/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/dkedar7/cowork-dash/releases/tag/v0.1.0
