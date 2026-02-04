"""
Core functionality tests for Cowork Dash.

Tests the main entry points:
- CLI argument parsing (7 tests)
- run_app() Python API (7 tests)
- Agent loading (5 tests)
- Config/platform behavior (4 tests)
- Components rendering (6 tests)
- Ordered content items (5 tests)
- Display inline results (5 tests)
- Format AI text (2 tests)

Total: 41 tests
"""

import os
import json
from unittest.mock import patch, MagicMock

import pytest

from cowork_dash.app import run_app, load_agent_from_spec
from cowork_dash.cli import main
from cowork_dash.components import (
    format_message,
    format_loading,
    format_thinking,
    format_ai_text,
    format_todos_inline,
    format_tool_calls_inline,
    extract_thinking_from_tool_calls,
    extract_display_inline_results,
    render_ordered_content_items,
    render_display_inline_result,
)


# =============================================================================
# CLI TESTS (7 tests)
# =============================================================================


def test_cli_workspace_argument(monkeypatch, tmp_path):
    """Test CLI --workspace argument is parsed correctly."""
    workspace = tmp_path / "test_ws"
    workspace.mkdir()

    test_args = ["cowork-dash", "run", "--workspace", str(workspace)]
    monkeypatch.setattr("sys.argv", test_args)

    with patch("cowork_dash.app.run_app") as mock_run:
        main()
        assert mock_run.call_args[1]["workspace"] == str(workspace)


def test_cli_port_argument(monkeypatch):
    """Test CLI --port argument is parsed as integer."""
    test_args = ["cowork-dash", "run", "--port", "9999"]
    monkeypatch.setattr("sys.argv", test_args)

    with patch("cowork_dash.app.run_app") as mock_run:
        main()
        assert mock_run.call_args[1]["port"] == 9999


def test_cli_agent_argument(monkeypatch):
    """Test CLI --agent argument is passed through."""
    test_args = ["cowork-dash", "run", "--agent", "my_agent.py:agent"]
    monkeypatch.setattr("sys.argv", test_args)

    with patch("cowork_dash.app.run_app") as mock_run:
        main()
        assert mock_run.call_args[1]["agent_spec"] == "my_agent.py:agent"


def test_cli_debug_flag(monkeypatch):
    """Test CLI --debug flag sets debug=True."""
    test_args = ["cowork-dash", "run", "--debug"]
    monkeypatch.setattr("sys.argv", test_args)

    with patch("cowork_dash.app.run_app") as mock_run:
        main()
        assert mock_run.call_args[1]["debug"] is True


def test_cli_title_argument(monkeypatch):
    """Test CLI --title argument."""
    test_args = ["cowork-dash", "run", "--title", "My App"]
    monkeypatch.setattr("sys.argv", test_args)

    with patch("cowork_dash.app.run_app") as mock_run:
        main()
        assert mock_run.call_args[1]["title"] == "My App"


def test_cli_virtual_fs_flag_on_linux(monkeypatch):
    """Test CLI --virtual-fs flag is passed through on Linux."""
    test_args = ["cowork-dash", "run", "--virtual-fs"]
    monkeypatch.setattr("sys.argv", test_args)

    with patch("cowork_dash.app.run_app") as mock_run:
        with patch("platform.system") as mock_platform:
            mock_platform.return_value = "Linux"
            main()
            assert mock_run.call_args[1]["virtual_fs"] is True


def test_cli_virtual_fs_warning_on_non_linux(monkeypatch, capsys):
    """Test CLI --virtual-fs shows warning on non-Linux systems."""
    test_args = ["cowork-dash", "run", "--virtual-fs"]
    monkeypatch.setattr("sys.argv", test_args)

    with patch("cowork_dash.app.run_app") as mock_run:
        with patch("platform.system") as mock_platform:
            mock_platform.return_value = "Darwin"
            main()
            # Should set virtual_fs to None (fallback to config)
            assert mock_run.call_args[1]["virtual_fs"] is None
            captured = capsys.readouterr()
            assert "warning" in captured.out.lower()


# =============================================================================
# RUN_APP API TESTS (7 tests)
# =============================================================================


def test_api_agent_instance(tmp_path, sample_agent):
    """Test run_app() accepts agent instance as first parameter."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with patch("cowork_dash.app.app.run"):
        run_app(sample_agent, workspace=str(workspace))

        from cowork_dash.app import agent
        assert agent is sample_agent


def test_api_agent_spec_priority(tmp_path, sample_agent):
    """Test agent_spec parameter overrides agent_instance."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    agent_file = tmp_path / "test_agent.py"
    agent_file.write_text("class Agent:\n    pass\nmy_agent = Agent()\n")

    with patch("cowork_dash.app.app.run"):
        run_app(
            sample_agent,
            workspace=str(workspace),
            agent_spec=f"{agent_file}:my_agent"
        )

        from cowork_dash.app import agent
        assert agent.__class__.__name__ == "Agent"


def test_api_workspace_env_var(tmp_path):
    """Test run_app() sets DEEPAGENT_WORKSPACE_ROOT environment variable."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with patch("cowork_dash.app.app.run"):
        run_app(workspace=str(workspace), virtual_fs=False)
        assert os.environ["DEEPAGENT_WORKSPACE_ROOT"] == str(workspace.resolve())


def test_api_port_config(tmp_path):
    """Test run_app() port parameter."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with patch("cowork_dash.app.app.run"):
        run_app(workspace=str(workspace), port=9000)

        from cowork_dash.app import PORT
        assert PORT == 9000


def test_api_host_config(tmp_path):
    """Test run_app() host parameter."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with patch("cowork_dash.app.app.run"):
        run_app(workspace=str(workspace), host="0.0.0.0")

        from cowork_dash.app import HOST
        assert HOST == "0.0.0.0"


def test_api_debug_config(tmp_path):
    """Test run_app() debug parameter."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with patch("cowork_dash.app.app.run"):
        run_app(workspace=str(workspace), debug=True)

        from cowork_dash.app import DEBUG
        assert DEBUG is True


def test_api_title_subtitle_config(tmp_path):
    """Test run_app() title and subtitle parameters."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with patch("cowork_dash.app.app.run"):
        run_app(
            workspace=str(workspace),
            title="Custom",
            subtitle="Subtitle"
        )

        from cowork_dash.app import APP_TITLE, APP_SUBTITLE
        assert APP_TITLE == "Custom"
        assert APP_SUBTITLE == "Subtitle"


# =============================================================================
# AGENT LOADING TESTS (5 tests)
# =============================================================================


def test_load_agent_invalid_file():
    """Test loading agent from nonexistent file returns error."""
    agent, error = load_agent_from_spec("missing.py:agent")

    assert agent is None
    assert error is not None
    assert "not found" in error.lower()


def test_load_agent_missing_object(tmp_path):
    """Test loading nonexistent object from file returns error."""
    agent_file = tmp_path / "test.py"
    agent_file.write_text("x = 1\n")

    agent, error = load_agent_from_spec(f"{agent_file}:missing")

    assert agent is None
    assert "not found" in error.lower()


def test_load_agent_success(tmp_path):
    """Test successfully loading agent from spec."""
    agent_file = tmp_path / "agent.py"
    agent_file.write_text("""
class MyAgent:
    def stream(self, input, stream_mode="updates"):
        yield {"response": "test"}

agent = MyAgent()
""")

    loaded_agent, error = load_agent_from_spec(f"{agent_file}:agent")

    assert loaded_agent is not None
    assert error is None
    assert hasattr(loaded_agent, 'stream')


def test_load_agent_invalid_spec_format():
    """Test loading agent with invalid spec format returns error."""
    agent, error = load_agent_from_spec("invalid_spec_no_colon")

    assert agent is None
    assert error is not None
    assert "Invalid agent spec" in error


def test_load_agent_module_format(tmp_path, monkeypatch):
    """Test loading agent from module format works."""
    # Create a simple module
    module_dir = tmp_path / "mypackage"
    module_dir.mkdir()
    (module_dir / "__init__.py").write_text("")
    (module_dir / "agents.py").write_text("""
class TestAgent:
    def stream(self, input, stream_mode="updates"):
        yield {"response": "test"}

test_agent = TestAgent()
""")

    # Add to sys.path temporarily
    monkeypatch.syspath_prepend(str(tmp_path))

    loaded_agent, error = load_agent_from_spec("mypackage.agents:test_agent")

    assert loaded_agent is not None
    assert error is None
    assert hasattr(loaded_agent, 'stream')


# =============================================================================
# CONFIG TESTS (4 tests)
# =============================================================================


def test_config_is_linux_function():
    """Test is_linux() function returns correct value."""
    from cowork_dash.config import is_linux
    import platform

    expected = platform.system() == "Linux"
    assert is_linux() == expected


def test_config_virtual_fs_disabled_on_non_linux():
    """Test VIRTUAL_FS is False on non-Linux even when requested."""
    import importlib
    from unittest.mock import patch

    with patch("platform.system") as mock_platform:
        mock_platform.return_value = "Darwin"

        with patch.dict(os.environ, {"DEEPAGENT_VIRTUAL_FS": "true"}):
            import cowork_dash.config as config_module
            importlib.reload(config_module)

            assert config_module.VIRTUAL_FS is False
            assert config_module.VIRTUAL_FS_UNAVAILABLE_REASON is not None
            assert "Linux" in config_module.VIRTUAL_FS_UNAVAILABLE_REASON


def test_config_virtual_fs_enabled_on_linux():
    """Test VIRTUAL_FS can be enabled on Linux."""
    import importlib
    from unittest.mock import patch

    with patch("platform.system") as mock_platform:
        mock_platform.return_value = "Linux"

        with patch.dict(os.environ, {"DEEPAGENT_VIRTUAL_FS": "true"}):
            import cowork_dash.config as config_module
            importlib.reload(config_module)

            assert config_module.VIRTUAL_FS is True
            assert config_module.VIRTUAL_FS_UNAVAILABLE_REASON is None


def test_config_virtual_fs_default_false():
    """Test VIRTUAL_FS defaults to False."""
    import importlib
    from unittest.mock import patch

    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("DEEPAGENT_VIRTUAL_FS", None)

        import cowork_dash.config as config_module
        importlib.reload(config_module)

        assert config_module.VIRTUAL_FS is False


# =============================================================================
# COMPONENTS TESTS (6 tests)
# =============================================================================


@pytest.fixture
def test_colors():
    """Return test color scheme."""
    return {
        "bg_primary": "#ffffff",
        "bg_secondary": "#f8f9fa",
        "text_primary": "#202124",
        "text_secondary": "#5f6368",
        "text_muted": "#80868b",
        "accent": "#1a73e8",
        "success": "#1e8e3e",
        "warning": "#f9ab00",
        "error": "#d93025",
        "todo": "#0891b2",
    }


@pytest.fixture
def test_styles():
    """Return test styles."""
    return {
        "font_size": "14px",
        "border_radius": "8px",
    }


def test_format_message_user(test_colors, test_styles):
    """Test format_message renders user messages correctly."""
    result = format_message("user", "Hello world", test_colors, test_styles)

    assert result is not None
    assert "chat-message-user" in result.className


def test_format_message_assistant(test_colors, test_styles):
    """Test format_message renders assistant messages correctly."""
    result = format_message("assistant", "Hi there!", test_colors, test_styles)

    assert result is not None
    assert "chat-message-agent" in result.className


def test_format_loading(test_colors):
    """Test format_loading renders dots loader."""
    result = format_loading(test_colors)

    assert result is not None
    assert "chat-message-loading" in result.className
    # Check that it contains a loader component
    assert len(result.children) > 0


def test_format_thinking(test_colors):
    """Test format_thinking renders thinking block."""
    result = format_thinking("Let me think about this...", test_colors)

    assert result is not None
    # Should be a Div element (non-collapsible)
    assert hasattr(result, 'children')
    # Should have children (header and content)
    assert len(result.children) >= 1


def test_format_thinking_empty(test_colors):
    """Test format_thinking returns None for empty text."""
    result = format_thinking("", test_colors)
    assert result is None

    result = format_thinking(None, test_colors)
    assert result is None


def test_extract_thinking_from_tool_calls(test_colors):
    """Test extracting think_tool results from tool calls."""
    tool_calls = [
        {
            "name": "think_tool",
            "status": "success",
            "result": "I need to analyze this problem carefully."
        },
        {
            "name": "bash",
            "status": "success",
            "result": "command output"
        },
        {
            "name": "think_tool",
            "status": "success",
            "result": {"reflection": "Second thought here."}
        }
    ]

    results = extract_thinking_from_tool_calls(tool_calls, test_colors)

    # Should extract 2 thinking blocks
    assert len(results) == 2


def test_format_tool_calls_inline_excludes_think_tool(test_colors):
    """Test that format_tool_calls_inline excludes think_tool calls."""
    tool_calls = [
        {
            "name": "think_tool",
            "status": "success",
            "result": "thinking...",
            "args": {}
        },
        {
            "name": "bash",
            "status": "success",
            "result": "output",
            "args": {"command": "ls"}
        }
    ]

    result = format_tool_calls_inline(tool_calls, test_colors)

    # Should only show 1 tool (bash), not think_tool
    # The summary should say "Tools (1 done)"
    assert result is not None
    summary = result.children[0]  # First child is Summary
    assert "1 done" in summary.children


def test_format_tool_calls_inline_empty_after_filtering(test_colors):
    """Test format_tool_calls_inline returns None if only think_tool calls."""
    tool_calls = [
        {
            "name": "think_tool",
            "status": "success",
            "result": "thinking..."
        }
    ]

    result = format_tool_calls_inline(tool_calls, test_colors)

    # Should return None since all calls are think_tool
    assert result is None


def test_format_todos_inline(test_colors):
    """Test format_todos_inline renders todo list."""
    todos = [
        {"content": "Task 1", "status": "completed"},
        {"content": "Task 2", "status": "in_progress"},
        {"content": "Task 3", "status": "pending"},
    ]

    result = format_todos_inline(todos, test_colors)

    assert result is not None
    # Should be a Details element
    assert hasattr(result, 'children')


# =============================================================================
# ORDERED CONTENT ITEMS TESTS (4 tests)
# =============================================================================


def test_render_ordered_content_items_text(test_colors, test_styles):
    """Test render_ordered_content_items handles text items."""
    content_items = [
        {"type": "text", "content": "Hello world"},
    ]

    result = render_ordered_content_items(content_items, test_colors, test_styles)

    assert result is not None
    assert len(result) == 1


def test_render_ordered_content_items_thinking(test_colors, test_styles):
    """Test render_ordered_content_items handles thinking items."""
    content_items = [
        {"type": "thinking", "content": "Let me think..."},
    ]

    result = render_ordered_content_items(content_items, test_colors, test_styles)

    assert result is not None
    assert len(result) == 1


def test_render_ordered_content_items_mixed(test_colors, test_styles):
    """Test render_ordered_content_items maintains order of mixed content."""
    content_items = [
        {"type": "thinking", "content": "First thinking"},
        {"type": "text", "content": "First text"},
        {"type": "thinking", "content": "Second thinking"},
        {"type": "text", "content": "Second text"},
    ]

    result = render_ordered_content_items(content_items, test_colors, test_styles)

    assert result is not None
    assert len(result) == 4


def test_render_ordered_content_items_empty(test_colors, test_styles):
    """Test render_ordered_content_items handles empty list."""
    result = render_ordered_content_items([], test_colors, test_styles)

    assert result is not None
    assert len(result) == 0


def test_render_ordered_content_items_with_display_inline(test_colors, test_styles):
    """Test render_ordered_content_items handles display_inline items."""
    content_items = [
        {"type": "text", "content": "Here's an image:"},
        {
            "type": "display_inline",
            "content": {
                "display_type": "text",
                "data": "Sample text content",
                "title": "Test",
            }
        },
        {"type": "text", "content": "End of content"},
    ]

    result = render_ordered_content_items(content_items, test_colors, test_styles)

    assert result is not None
    assert len(result) == 3


# =============================================================================
# DISPLAY INLINE RESULT TESTS (5 tests)
# =============================================================================


def test_render_display_inline_result_text(test_colors):
    """Test render_display_inline_result handles text content."""
    result_data = {
        "display_type": "text",
        "data": "Sample text content",
        "title": "Test Text",
    }

    result = render_display_inline_result(result_data, test_colors)

    assert result is not None
    assert "display-inline-container" in result.className


def test_render_display_inline_result_json(test_colors):
    """Test render_display_inline_result handles JSON content."""
    result_data = {
        "display_type": "json",
        "data": {"key": "value", "number": 42},
        "title": "Test JSON",
    }

    result = render_display_inline_result(result_data, test_colors)

    assert result is not None
    assert "display-inline-container" in result.className


def test_render_display_inline_result_image(test_colors):
    """Test render_display_inline_result handles image content."""
    # Minimal base64 PNG (1x1 transparent pixel)
    import base64
    pixel_data = base64.b64encode(b'\x89PNG\r\n\x1a\n').decode('utf-8')

    result_data = {
        "display_type": "image",
        "data": pixel_data,
        "mime_type": "image/png",
        "title": "Test Image",
    }

    result = render_display_inline_result(result_data, test_colors)

    assert result is not None
    assert "display-inline-container" in result.className


def test_render_display_inline_result_dataframe(test_colors):
    """Test render_display_inline_result handles dataframe content."""
    result_data = {
        "display_type": "dataframe",
        "data": "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>",
        "title": "Test DataFrame",
    }

    result = render_display_inline_result(result_data, test_colors)

    assert result is not None
    assert "display-inline-container" in result.className


def test_render_display_inline_result_error(test_colors):
    """Test render_display_inline_result handles error content."""
    result_data = {
        "display_type": "error",
        "error": "Something went wrong",
        "data": "",
        "title": "Error",
    }

    result = render_display_inline_result(result_data, test_colors)

    assert result is not None
    assert "display-inline-container" in result.className


# =============================================================================
# FORMAT AI TEXT TESTS (2 tests)
# =============================================================================


def test_format_ai_text(test_colors):
    """Test format_ai_text renders markdown text."""
    result = format_ai_text("Hello **world**", test_colors)

    assert result is not None
    assert "ai-text-block" in result.className


def test_format_ai_text_empty(test_colors):
    """Test format_ai_text returns None for empty text."""
    result = format_ai_text("", test_colors)
    assert result is None

    result = format_ai_text(None, test_colors)
    assert result is None
