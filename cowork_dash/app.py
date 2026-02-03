import os
import uuid
import sys
import json
import base64
import re
import copy
import shutil
import platform
import subprocess
import threading
import time
import importlib.util
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv
load_dotenv()

# Early pandas import to prevent circular import issues with Plotly's JSON serializer.
# Plotly lazily imports pandas and checks `obj is pd.NaT` which fails if pandas
# is partially initialized due to concurrent imports.
try:
    import pandas
except (ImportError, AttributeError):
    pass

from dash import Dash, html, dcc, Input, Output, State, callback_context, no_update, ALL
from dash.exceptions import PreventUpdate
import dash_mantine_components as dmc
from dash_iconify import DashIconify

# Import custom modules
from .canvas import export_canvas_to_markdown, load_canvas_from_markdown
from .file_utils import build_file_tree, render_file_tree, read_file_content, get_file_download_data, load_folder_contents
from .components import (
    format_message, format_loading, format_thinking, format_todos_inline, render_canvas_items, format_tool_calls_inline,
    format_interrupt, extract_display_inline_results, render_display_inline_result, extract_thinking_from_tool_calls
)
from .layout import create_layout as create_layout_component
from .virtual_fs import get_session_manager

# Import configuration defaults
from . import config

# Generate thread ID
thread_id = str(uuid.uuid4())

def load_agent_from_spec(agent_spec: str):
    """
    Load agent from specification string.

    Supports two formats (both use colon separator):
    1. File path format: "path/to/file.py:object_name"
    2. Module format: "mypackage.module.submodule:object_name"

    Args:
        agent_spec: String like "agent.py:agent", "my_agents.py:custom_agent",
                   or "mypackage.agents:my_agent"

    Returns:
        tuple: (agent_object, error_message)
    """
    try:
        # Both formats use colon separator
        if ":" not in agent_spec:
            return None, f"Invalid agent spec '{agent_spec}'. Expected format: 'path/to/file.py:object' or 'module.path:object'"

        left_part, object_name = agent_spec.rsplit(":", 1)

        # Determine if it's a file path or module path
        # File paths end with .py or contain path separators
        if left_part.endswith(".py") or "/" in left_part or "\\" in left_part:
            return _load_agent_from_file(left_part, object_name)
        else:
            return _load_agent_from_module(left_part, object_name)

    except Exception as e:
        return None, f"Failed to load agent from {agent_spec}: {e}"


def _load_agent_from_file(file_path_str: str, object_name: str):
    """Load agent from file path format: 'path/to/file.py:object_name'"""
    file_path = Path(file_path_str).resolve()

    if not file_path.exists():
        return None, f"Agent file not found: {file_path}"

    # Load the module
    spec = importlib.util.spec_from_file_location("custom_agent_module", file_path)
    if spec is None or spec.loader is None:
        return None, f"Failed to load module from {file_path}"

    module = importlib.util.module_from_spec(spec)
    sys.modules["custom_agent_module"] = module
    spec.loader.exec_module(module)

    # Get the object
    if not hasattr(module, object_name):
        return None, f"Object '{object_name}' not found in {file_path}"

    agent = getattr(module, object_name)
    return agent, None


def _load_agent_from_module(module_path: str, object_name: str):
    """Load agent from module format: 'mypackage.module:object_name'"""
    try:
        # Import the module
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as e:
        return None, f"Module '{module_path}' not found: {e}"
    except ImportError as e:
        return None, f"Failed to import module '{module_path}': {e}"

    # Get the object
    if not hasattr(module, object_name):
        return None, f"Object '{object_name}' not found in module '{module_path}'"

    agent = getattr(module, object_name)
    return agent, None

# Module-level configuration (uses config defaults)
WORKSPACE_ROOT = config.WORKSPACE_ROOT
APP_TITLE = config.APP_TITLE
APP_SUBTITLE = config.APP_SUBTITLE
PORT = config.PORT
HOST = config.HOST
DEBUG = config.DEBUG
WELCOME_MESSAGE = config.WELCOME_MESSAGE
USE_VIRTUAL_FS = config.VIRTUAL_FS  # Can be overridden by --virtual-fs CLI arg

# Ensure workspace exists (only for physical filesystem mode)
if not USE_VIRTUAL_FS:
    WORKSPACE_ROOT.mkdir(exist_ok=True, parents=True)

# Initialize agent from config
agent, AGENT_ERROR = load_agent_from_spec(config.AGENT_SPEC)


def get_workspace_for_session(session_id: Optional[str] = None):
    """Get the workspace root for a session.

    In virtual filesystem mode, returns a VirtualFilesystem for the session.
    In physical mode, returns the WORKSPACE_ROOT Path.

    Args:
        session_id: Session ID (required for virtual FS mode, ignored otherwise)

    Returns:
        Path or VirtualFilesystem depending on USE_VIRTUAL_FS setting
    """
    if USE_VIRTUAL_FS:
        if not session_id:
            # Generate a new session if none provided
            session_id = get_session_manager().create_session()
        else:
            # Get or create session
            session_id = get_session_manager().get_or_create_session(session_id)
        return get_session_manager().get_filesystem(session_id)
    else:
        return WORKSPACE_ROOT


def get_or_create_session_id(existing_id: Optional[str] = None) -> str:
    """Get existing session ID or create a new one.

    Args:
        existing_id: Existing session ID from cookie/store

    Returns:
        Valid session ID
    """
    if USE_VIRTUAL_FS:
        return get_session_manager().get_or_create_session(existing_id)
    else:
        # In physical mode, still track session IDs but they all share the same workspace
        return existing_id or str(uuid.uuid4())


# =============================================================================
# STYLING
# =============================================================================

COLORS_LIGHT = {
    "bg_primary": "#ffffff",
    "bg_secondary": "#f8f9fa",
    "bg_tertiary": "#f1f3f4",
    "bg_hover": "#e8eaed",
    "accent": "#1a73e8",
    "accent_light": "#e8f0fe",
    "accent_dark": "#1557b0",
    "text_primary": "#202124",
    "text_secondary": "#5f6368",
    "text_muted": "#80868b",
    "border": "#dadce0",
    "border_light": "#e8eaed",
    "success": "#1e8e3e",
    "warning": "#f9ab00",
    "error": "#d93025",
    "thinking": "#7c4dff",
    "todo": "#00897b",
    "canvas_bg": "#ffffff",
    "interrupt_bg": "#fffbeb",
}

COLORS_DARK = {
    "bg_primary": "#1e1e1e",
    "bg_secondary": "#252526",
    "bg_tertiary": "#2d2d2d",
    "bg_hover": "#3c3c3c",
    "accent": "#4fc3f7",
    "accent_light": "#1e3a5f",
    "accent_dark": "#81d4fa",
    "text_primary": "#e0e0e0",
    "text_secondary": "#b0b0b0",
    "text_muted": "#808080",
    "border": "#404040",
    "border_light": "#333333",
    "success": "#4caf50",
    "warning": "#ffb74d",
    "error": "#ef5350",
    "thinking": "#b388ff",
    "todo": "#26a69a",
    "canvas_bg": "#2d2d2d",
    "interrupt_bg": "#3d3520",
}

# Default to light theme
COLORS = COLORS_LIGHT.copy()

STYLES = {
    "shadow": "0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.08)",
    "transition": "all 0.15s ease",
}

def get_colors(theme: str = "light") -> dict:
    """Get color scheme based on theme."""
    return COLORS_DARK if theme == "dark" else COLORS_LIGHT

# Note: File utilities imported from file_utils module
# No local wrappers needed - file_utils functions will be called with WORKSPACE_ROOT

# =============================================================================
# AGENT INTERACTION - WITH REAL-TIME STREAMING
# =============================================================================

# Global state for streaming updates (used in physical FS mode)
_agent_state = {
    "running": False,
    "thinking": "",
    "todos": [],
    "tool_calls": [],  # Current turn's tool calls (reset each turn)
    "display_inline_items": [],  # Items pushed by display_inline tool (bypasses LangGraph)
    "canvas": load_canvas_from_markdown(WORKSPACE_ROOT) if not USE_VIRTUAL_FS else [],  # Load from canvas.md if exists (physical FS only)
    "response": "",
    "error": None,
    "interrupt": None,  # Track interrupt requests for human-in-the-loop
    "last_update": time.time(),
    "start_time": None,  # Track when agent started for response time calculation
    "stop_requested": False,  # Flag to request agent stop
    "stop_event": None,  # Threading event for immediate stop signaling
}
_agent_state_lock = threading.Lock()

# Session-aware state for virtual FS mode
# Each session gets its own agent instance and state
_session_agents: Dict[str, Any] = {}
_session_agent_states: Dict[str, Dict[str, Any]] = {}
_session_agents_lock = threading.Lock()


def _get_default_agent_state() -> Dict[str, Any]:
    """Return a fresh default agent state dict."""
    return {
        "running": False,
        "thinking": "",
        "todos": [],
        "tool_calls": [],
        "display_inline_items": [],  # Items pushed by display_inline tool (bypasses LangGraph)
        "canvas": [],
        "response": "",
        "error": None,
        "interrupt": None,
        "last_update": time.time(),
        "stop_event": None,  # Threading event for immediate stop signaling
        "start_time": None,
        "stop_requested": False,
    }


def _get_session_agent(session_id: str):
    """Get or create agent for a session (virtual FS mode only).

    Args:
        session_id: The session ID.

    Returns:
        The agent instance for this session.
    """
    from .agent import create_session_agent

    with _session_agents_lock:
        if session_id not in _session_agents:
            _session_agents[session_id] = create_session_agent(session_id)
        return _session_agents[session_id]


def _get_session_state(session_id: str) -> Dict[str, Any]:
    """Get or create agent state for a session (virtual FS mode only).

    Args:
        session_id: The session ID.

    Returns:
        The agent state dict for this session.
    """
    with _session_agents_lock:
        if session_id not in _session_agent_states:
            _session_agent_states[session_id] = _get_default_agent_state()
        return _session_agent_states[session_id]


def _get_session_state_lock() -> threading.Lock:
    """Get the lock for session state access."""
    return _session_agents_lock


def request_agent_stop(session_id: Optional[str] = None):
    """Request the agent to stop execution immediately.

    Sets the stop_requested flag and signals the stop_event for immediate interruption.

    Args:
        session_id: Session ID for virtual FS mode, None for physical FS mode.
    """
    if USE_VIRTUAL_FS and session_id:
        state = _get_session_state(session_id)
        with _session_agents_lock:
            state["stop_requested"] = True
            state["last_update"] = time.time()
            # Signal the stop event for immediate interruption
            if state.get("stop_event"):
                state["stop_event"].set()
    else:
        with _agent_state_lock:
            _agent_state["stop_requested"] = True
            _agent_state["last_update"] = time.time()
            # Signal the stop event for immediate interruption
            if _agent_state.get("stop_event"):
                _agent_state["stop_event"].set()


def _run_agent_stream(message: str, resume_data: Dict = None, workspace_path: str = None, session_id: Optional[str] = None):
    """Run agent in background thread and update state in real-time.

    Args:
        message: User message to send to agent
        resume_data: Optional dict with 'decisions' to resume from interrupt
        workspace_path: Current workspace directory path to inject into agent context
        session_id: Session ID for virtual FS mode (determines which agent and state to use)
    """
    # Determine which agent and state to use based on mode
    if USE_VIRTUAL_FS and session_id:
        current_agent = _get_session_agent(session_id)
        current_state = _get_session_state(session_id)
        state_lock = _session_agents_lock
        # Use session_id as thread_id for LangGraph checkpointing
        current_thread_id = session_id
    else:
        current_agent = agent
        current_state = _agent_state
        state_lock = _agent_state_lock
        current_thread_id = thread_id

    if not current_agent:
        with state_lock:
            current_state["response"] = f"⚠️ {current_state.get('error', 'No agent available')}\n\nPlease check your setup and try again."
            current_state["running"] = False
        return

    # Create a stop event for immediate interruption
    stop_event = threading.Event()
    with state_lock:
        current_state["stop_event"] = stop_event
        current_state["stop_requested"] = False  # Reset stop flag

    # Track tool calls by their ID for updating status
    tool_call_map = {}

    def _serialize_tool_call(tc) -> Dict:
        """Serialize a tool call to a dictionary."""
        if isinstance(tc, dict):
            return {
                "id": tc.get("id"),
                "name": tc.get("name"),
                "args": tc.get("args", {}),
                "status": "running",
                "result": None
            }
        else:
            return {
                "id": getattr(tc, 'id', None),
                "name": getattr(tc, 'name', None),
                "args": getattr(tc, 'args', {}),
                "status": "running",
                "result": None
            }

    def _update_tool_call_result(tool_call_id: str, result: Any, status: str = "success"):
        """Update a tool call with its result."""
        with state_lock:
            for tc in current_state["tool_calls"]:
                if tc.get("id") == tool_call_id:
                    tc["result"] = result
                    tc["status"] = status
                    break
            current_state["last_update"] = time.time()

    # Set tool session context for virtual FS mode
    # This allows tools like add_to_canvas to access the session's VirtualFilesystem
    from .tools import set_tool_session_context, clear_tool_session_context
    if USE_VIRTUAL_FS and session_id:
        set_tool_session_context(session_id)

    try:
        # Prepare input based on whether we're resuming or starting fresh
        stream_config = dict(configurable=dict(thread_id=current_thread_id))

        if message == "__RESUME__":
            # Resume from interrupt
            from langgraph.types import Command
            agent_input = Command(resume=resume_data)

            # Rebuild tool_call_map from existing tool calls and mark pending ones as running
            with state_lock:
                for tc in current_state.get("tool_calls", []):
                    tc_id = tc.get("id")
                    if tc_id:
                        tool_call_map[tc_id] = tc
                        # Mark pending tool calls back to running since we're resuming
                        if tc.get("status") == "pending":
                            tc["status"] = "running"
                current_state["last_update"] = time.time()
        else:
            # Inject workspace context into the message if available
            if workspace_path:
                context_prefix = f"[Current working directory: {workspace_path}]\n\n"
                message_with_context = context_prefix + message
            else:
                message_with_context = message
            agent_input = {"messages": [{"role": "user", "content": message_with_context}]}

        for update in current_agent.stream(agent_input, stream_mode="updates", config=stream_config):
            # Check if stop was requested (via flag or event)
            if stop_event.is_set() or current_state.get("stop_requested"):
                with state_lock:
                    current_state["response"] = current_state.get("response", "") + "\n\n⏹️ Agent stopped by user."
                    current_state["running"] = False
                    current_state["stop_requested"] = False
                    current_state["stop_event"] = None
                    current_state["last_update"] = time.time()
                return

            # Check for interrupt
            if isinstance(update, dict) and "__interrupt__" in update:
                interrupt_value = update["__interrupt__"]
                interrupt_data = _process_interrupt(interrupt_value)
                with state_lock:
                    current_state["interrupt"] = interrupt_data
                    current_state["running"] = False  # Pause until user responds
                    # Mark any "running" tool calls as "pending" since we're waiting for user approval
                    for tc in current_state["tool_calls"]:
                        if tc.get("status") == "running":
                            tc["status"] = "pending"
                    current_state["last_update"] = time.time()
                return  # Exit stream, wait for user to resume

            if isinstance(update, dict):
                for _, state_data in update.items():
                    if isinstance(state_data, dict) and "messages" in state_data:
                        msgs = state_data["messages"]
                        if msgs:
                            last_msg = msgs[-1] if isinstance(msgs, list) else msgs
                            msg_type = last_msg.__class__.__name__ if hasattr(last_msg, '__class__') else None

                            # Capture AIMessage tool_calls
                            if msg_type == 'AIMessage' and hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
                                with state_lock:
                                    # Get existing tool call IDs to avoid duplicates
                                    existing_ids = {tc.get("id") for tc in current_state["tool_calls"]}

                                    for tc in last_msg.tool_calls:
                                        serialized = _serialize_tool_call(tc)
                                        tc_id = serialized["id"]

                                        # Only add if not already in the list (avoid duplicates on resume)
                                        if tc_id not in existing_ids:
                                            tool_call_map[tc_id] = serialized
                                            current_state["tool_calls"].append(serialized)
                                            existing_ids.add(tc_id)
                                        else:
                                            # Update the map to reference the existing tool call
                                            for existing_tc in current_state["tool_calls"]:
                                                if existing_tc.get("id") == tc_id:
                                                    tool_call_map[tc_id] = existing_tc
                                                    break

                                    current_state["last_update"] = time.time()

                            elif msg_type == 'ToolMessage' and hasattr(last_msg, 'name'):
                                # Update tool call status when we get the result
                                tool_call_id = getattr(last_msg, 'tool_call_id', None)
                                if tool_call_id:
                                    # Determine status - check message status attribute first
                                    content = last_msg.content
                                    status = "success"

                                    # Check if ToolMessage has explicit status (e.g., from LangGraph)
                                    msg_status = getattr(last_msg, 'status', None)
                                    if msg_status == 'error':
                                        status = "error"
                                    # Check for dict with explicit error field
                                    elif isinstance(content, dict) and content.get("error"):
                                        status = "error"
                                    # Check for common error patterns at the START of the message
                                    # (not just anywhere, to avoid false positives)
                                    elif isinstance(content, str):
                                        content_lower = content.lower().strip()
                                        # Only mark as error if it starts with error indicators
                                        if (content_lower.startswith("error:") or
                                            content_lower.startswith("failed:") or
                                            content_lower.startswith("exception:") or
                                            content_lower.startswith("traceback")):
                                            status = "error"

                                    # display_inline now pushes rich content directly to queue
                                    # and returns a simple confirmation message, so no special handling needed
                                    if isinstance(content, str):
                                        # Truncate result for display
                                        result_display = content[:1000] + "..." if len(content) > 1000 else content
                                    else:
                                        # Convert other types to string and truncate
                                        result_display = str(content)
                                        if len(result_display) > 1000:
                                            result_display = result_display[:1000] + "..."

                                    _update_tool_call_result(tool_call_id, result_display, status)

                                # Handle specific tool messages
                                if last_msg.name == 'think_tool':
                                    content = last_msg.content
                                    thinking_text = ""
                                    if isinstance(content, str):
                                        try:
                                            parsed = json.loads(content)
                                            thinking_text = parsed.get('reflection', content)
                                        except:
                                            thinking_text = content
                                    elif isinstance(content, dict):
                                        thinking_text = content.get('reflection', str(content))

                                    # Update state immediately
                                    with state_lock:
                                        current_state["thinking"] = thinking_text
                                        current_state["last_update"] = time.time()

                                elif last_msg.name == 'write_todos':
                                    content = last_msg.content
                                    todos = []
                                    if isinstance(content, str):
                                        import ast
                                        match = re.search(r'\[.*\]', content, re.DOTALL)
                                        if match:
                                            try:
                                                todos = ast.literal_eval(match.group(0))
                                            except:
                                                try:
                                                    todos = json.loads(match.group(0))
                                                except:
                                                    pass
                                    elif isinstance(content, list):
                                        todos = content

                                    # Update state immediately
                                    with state_lock:
                                        current_state["todos"] = todos
                                        current_state["last_update"] = time.time()

                                elif last_msg.name == 'add_to_canvas':
                                    content = last_msg.content
                                    # Canvas tool returns the parsed canvas object
                                    if isinstance(content, str):
                                        try:
                                            parsed = json.loads(content)
                                            canvas_item = parsed
                                        except:
                                            # If not JSON, treat as markdown
                                            canvas_item = {"type": "markdown", "data": content}
                                    elif isinstance(content, dict):
                                        canvas_item = content
                                    else:
                                        canvas_item = {"type": "markdown", "data": str(content)}

                                    # Update state immediately - append to canvas
                                    with state_lock:
                                        current_state["canvas"].append(canvas_item)
                                        current_state["last_update"] = time.time()

                                        # Also export to markdown file (physical FS only)
                                        if not USE_VIRTUAL_FS:
                                            try:
                                                export_canvas_to_markdown(current_state["canvas"], WORKSPACE_ROOT)
                                            except Exception as e:
                                                print(f"Failed to export canvas: {e}")

                                elif last_msg.name == 'update_canvas_item':
                                    content = last_msg.content
                                    # Parse the canvas item to update
                                    if isinstance(content, str):
                                        try:
                                            canvas_item = json.loads(content)
                                        except:
                                            canvas_item = {"type": "markdown", "data": content}
                                    elif isinstance(content, dict):
                                        canvas_item = content
                                    else:
                                        canvas_item = {"type": "markdown", "data": str(content)}

                                    item_id = canvas_item.get("id")
                                    if item_id:
                                        with state_lock:
                                            # Find and replace the item with matching ID
                                            for i, existing in enumerate(current_state["canvas"]):
                                                if existing.get("id") == item_id:
                                                    current_state["canvas"][i] = canvas_item
                                                    break
                                            else:
                                                # If not found, append as new item
                                                current_state["canvas"].append(canvas_item)
                                            current_state["last_update"] = time.time()

                                            # Export to markdown file (physical FS only)
                                            if not USE_VIRTUAL_FS:
                                                try:
                                                    export_canvas_to_markdown(current_state["canvas"], WORKSPACE_ROOT)
                                                except Exception as e:
                                                    print(f"Failed to export canvas: {e}")

                                elif last_msg.name == 'remove_canvas_item':
                                    content = last_msg.content
                                    # Parse to get the item ID to remove
                                    if isinstance(content, str):
                                        try:
                                            parsed = json.loads(content)
                                            item_id = parsed.get("id")
                                        except:
                                            item_id = content  # Assume string is the ID
                                    elif isinstance(content, dict):
                                        item_id = content.get("id")
                                    else:
                                        item_id = None

                                    if item_id:
                                        with state_lock:
                                            current_state["canvas"] = [
                                                item for item in current_state["canvas"]
                                                if item.get("id") != item_id
                                            ]
                                            current_state["last_update"] = time.time()

                                            # Export to markdown file (physical FS only)
                                            if not USE_VIRTUAL_FS:
                                                try:
                                                    export_canvas_to_markdown(current_state["canvas"], WORKSPACE_ROOT)
                                                except Exception as e:
                                                    print(f"Failed to export canvas: {e}")

                                elif last_msg.name in ('execute_cell', 'execute_all_cells'):
                                    # Extract canvas_items from cell execution results
                                    content = last_msg.content
                                    canvas_items_to_add = []

                                    if isinstance(content, str):
                                        try:
                                            parsed = json.loads(content)
                                            # execute_cell returns a dict, execute_all_cells returns a list
                                            if isinstance(parsed, dict):
                                                canvas_items_to_add = parsed.get('canvas_items', [])
                                            elif isinstance(parsed, list):
                                                # execute_all_cells returns list of results
                                                for result in parsed:
                                                    if isinstance(result, dict):
                                                        canvas_items_to_add.extend(result.get('canvas_items', []))
                                        except:
                                            pass
                                    elif isinstance(content, dict):
                                        canvas_items_to_add = content.get('canvas_items', [])
                                    elif isinstance(content, list):
                                        for result in content:
                                            if isinstance(result, dict):
                                                canvas_items_to_add.extend(result.get('canvas_items', []))

                                    # Add any canvas items found
                                    if canvas_items_to_add:
                                        with state_lock:
                                            for item in canvas_items_to_add:
                                                if isinstance(item, dict) and item.get('type'):
                                                    current_state["canvas"].append(item)
                                            current_state["last_update"] = time.time()

                                            # Export to markdown file (physical FS only)
                                            if not USE_VIRTUAL_FS:
                                                try:
                                                    export_canvas_to_markdown(current_state["canvas"], WORKSPACE_ROOT)
                                                except Exception as e:
                                                    print(f"Failed to export canvas: {e}")

                            elif hasattr(last_msg, 'content'):
                                content = last_msg.content
                                response_text = ""
                                if isinstance(content, str):
                                    response_text = re.sub(
                                        r"\{'id':\s*'[^']+',\s*'input':\s*\{.*?\},\s*'name':\s*'[^']+',\s*'type':\s*'tool_use'\}",
                                        '', content, flags=re.DOTALL
                                    ).strip()
                                elif isinstance(content, list):
                                    text_parts = [
                                        block.get("text", "") if isinstance(block, dict) else str(block)
                                        for block in content
                                    ]
                                    response_text = " ".join(text_parts).strip()

                                if response_text:
                                    with state_lock:
                                        current_state["response"] = response_text
                                        current_state["last_update"] = time.time()

    except Exception as e:
        with state_lock:
            current_state["error"] = str(e)
            current_state["response"] = f"Error: {str(e)}"

    finally:
        # Clear tool session context
        if USE_VIRTUAL_FS and session_id:
            clear_tool_session_context()

        with state_lock:
            current_state["running"] = False
            current_state["stop_event"] = None  # Clean up stop event
            current_state["last_update"] = time.time()


def _process_interrupt(interrupt_value: Any) -> Dict[str, Any]:
    """Process a LangGraph interrupt value and convert to serializable format.

    Args:
        interrupt_value: The interrupt value from LangGraph

    Returns:
        Dict with 'message' and 'action_requests' for UI display
    """
    interrupt_data = {
        "message": "The agent needs your input to continue.",
        "action_requests": [],
        "raw": None
    }

    # Handle different interrupt formats
    if isinstance(interrupt_value, (list, tuple)) and len(interrupt_value) > 0:
        first_item = interrupt_value[0]

        # Check if it's an Interrupt object (from deepagents interrupt_on)
        if hasattr(first_item, 'value'):
            # This is a LangGraph Interrupt object
            for item in interrupt_value:
                value = getattr(item, 'value', None)

                # deepagents interrupt_on stores tool call info in a specific format:
                # {'action_requests': [{'name': 'bash', 'args': {...}, 'description': '...'}], 'review_configs': [...]}
                if value is not None and isinstance(value, dict):
                    # Check for deepagents format with action_requests
                    action_requests = value.get('action_requests', [])
                    if action_requests:
                        for action_req in action_requests:
                            tool_name = action_req.get('name', 'unknown')
                            tool_args = action_req.get('args', {})
                            interrupt_data["action_requests"].append({
                                "type": "tool_call",
                                "tool": tool_name,
                                "args": tool_args,
                            })
                            interrupt_data["message"] = f"The agent wants to execute: {tool_name}"
                    else:
                        # Fallback: direct tool call format
                        tool_name = value.get('name', value.get('tool', 'unknown'))
                        tool_args = value.get('args', value.get('arguments', {}))
                        if tool_name != 'unknown':
                            interrupt_data["action_requests"].append({
                                "type": "tool_call",
                                "tool": tool_name,
                                "args": tool_args,
                            })
                            interrupt_data["message"] = f"The agent wants to execute: {tool_name}"
                        else:
                            interrupt_data["message"] = str(value)
                elif value is not None:
                    interrupt_data["message"] = str(value)

        # Check if it's an ActionRequest or similar
        elif hasattr(first_item, 'action'):
            for item in interrupt_value:
                action = getattr(item, 'action', None)
                if action:
                    interrupt_data["action_requests"].append({
                        "type": getattr(action, 'type', 'unknown'),
                        "tool": getattr(action, 'name', getattr(action, 'tool', '')),
                        "args": getattr(action, 'args', {}),
                    })
        elif isinstance(first_item, dict):
            # Check if it's a tool call dict
            if 'name' in first_item or 'tool' in first_item:
                for item in interrupt_value:
                    tool_name = item.get('name', item.get('tool', 'unknown'))
                    tool_args = item.get('args', item.get('arguments', {}))
                    interrupt_data["action_requests"].append({
                        "type": "tool_call",
                        "tool": tool_name,
                        "args": tool_args,
                    })
                    interrupt_data["message"] = f"The agent wants to execute: {tool_name}"
            else:
                interrupt_data["action_requests"] = list(interrupt_value)
        else:
            interrupt_data["message"] = str(first_item)
    elif isinstance(interrupt_value, str):
        interrupt_data["message"] = interrupt_value
    elif isinstance(interrupt_value, dict):
        interrupt_data["message"] = interrupt_value.get("message", str(interrupt_value))
        interrupt_data["action_requests"] = interrupt_value.get("action_requests", [])

    # Store raw value for resume
    try:
        interrupt_data["raw"] = interrupt_value
    except:
        pass

    return interrupt_data

def call_agent(message: str, resume_data: Dict = None, workspace_path: str = None, session_id: Optional[str] = None):
    """Start agent execution in background thread.

    Args:
        message: User message to send to agent
        resume_data: Optional dict with decisions to resume from interrupt
        workspace_path: Current workspace directory path to inject into agent context
        session_id: Session ID for virtual FS mode
    """
    # Determine which state to use
    if USE_VIRTUAL_FS and session_id:
        current_state = _get_session_state(session_id)
        state_lock = _session_agents_lock
    else:
        current_state = _agent_state
        state_lock = _agent_state_lock

    # Reset state but preserve canvas - do it all atomically
    with state_lock:
        existing_canvas = current_state.get("canvas", []).copy()

        current_state.clear()
        current_state.update({
            "running": True,
            "thinking": "",
            "todos": [],
            "tool_calls": [],  # Reset tool calls for this turn
            "canvas": existing_canvas,  # Preserve existing canvas
            "response": "",
            "error": None,
            "interrupt": None,  # Clear any previous interrupt
            "last_update": time.time(),
            "start_time": time.time(),  # Track when agent started
            "stop_requested": False,  # Reset stop flag
        })

    # Start background thread
    thread = threading.Thread(target=_run_agent_stream, args=(message, resume_data, workspace_path, session_id))
    thread.daemon = True
    thread.start()


def resume_agent_from_interrupt(decision: str, action: str = "approve", action_requests: List[Dict] = None, session_id: Optional[str] = None):
    """Resume agent from an interrupt with the user's decision.

    Args:
        decision: User's response/decision text
        action: One of 'approve', 'reject', 'edit'
        action_requests: List of action requests from the interrupt (for edit mode)
        session_id: Session ID for virtual FS mode
    """
    # Determine which state to use
    if USE_VIRTUAL_FS and session_id:
        current_state = _get_session_state(session_id)
        state_lock = _session_agents_lock
    else:
        current_state = _agent_state
        state_lock = _agent_state_lock

    with state_lock:
        interrupt_data = current_state.get("interrupt")
        if not interrupt_data:
            return

        # Get action requests from interrupt data if not provided
        if action_requests is None:
            action_requests = interrupt_data.get("action_requests", [])

        # Clear interrupt and set running, but preserve tool_calls and canvas
        existing_tool_calls = current_state.get("tool_calls", []).copy()
        existing_canvas = current_state.get("canvas", []).copy()

        current_state["interrupt"] = None
        current_state["running"] = True
        current_state["response"] = ""  # Clear any previous response
        current_state["error"] = None  # Clear any previous error
        current_state["tool_calls"] = existing_tool_calls  # Keep existing tool calls
        current_state["canvas"] = existing_canvas  # Keep canvas
        current_state["last_update"] = time.time()

    # Build decisions list in the format expected by deepagents HITL middleware
    # Format: {"decisions": [{"type": "approve"}, {"type": "reject", "message": "..."}, ...]}
    decisions = []

    if action == "approve":
        # Approve all action requests
        for _ in action_requests:
            decisions.append({"type": "approve"})
        # If no action requests, still add one approve decision
        if not decisions:
            decisions.append({"type": "approve"})
    elif action == "reject":
        # When user rejects, stop the agent immediately instead of resuming
        # Set the response to indicate the action was rejected
        reject_message = decision or "User rejected the action"

        # Get tool info for the rejection message
        tool_info = ""
        if action_requests:
            tool_names = [ar.get("tool", "unknown") for ar in action_requests]
            tool_info = f" ({', '.join(tool_names)})"

        with state_lock:
            current_state["running"] = False
            current_state["stop_event"] = None  # Clean up stop event
            current_state["response"] = f"Action rejected{tool_info}: {reject_message}"
            current_state["last_update"] = time.time()

        return  # Don't resume the agent
    else:  # edit - provide edited action
        # For edit, we need to provide the edited tool call
        # The decision text should contain the edited command/args
        for action_req in action_requests:
            tool_name = action_req.get("tool", "")

            # If this is a bash command and user provided new command text
            if tool_name == "bash" and decision:
                decisions.append({
                    "type": "edit",
                    "edited_action": {
                        "name": tool_name,
                        "args": {"command": decision}
                    }
                })
            else:
                # For other tools or no input, just approve
                decisions.append({"type": "approve"})

        if not decisions:
            decisions.append({"type": "approve"})

    # Resume value in deepagents format
    resume_value = {"decisions": decisions}

    # Start background thread with resume value
    # Pass a special marker to indicate this is a resume operation
    thread = threading.Thread(target=_run_agent_stream, args=("__RESUME__", resume_value, None, session_id))
    thread.daemon = True
    thread.start()

def get_agent_state(session_id: Optional[str] = None) -> Dict[str, Any]:
    """Get current agent state (thread-safe).

    Args:
        session_id: Session ID for virtual FS mode, None for physical FS mode.

    Returns a deep copy of mutable collections to prevent race conditions.
    """
    if USE_VIRTUAL_FS and session_id:
        current_state = _get_session_state(session_id)
        state_lock = _session_agents_lock
    else:
        current_state = _agent_state
        state_lock = _agent_state_lock

    with state_lock:
        state = current_state.copy()
        # Deep copy mutable collections to prevent race conditions during rendering
        state["tool_calls"] = copy.deepcopy(current_state["tool_calls"])
        state["todos"] = copy.deepcopy(current_state["todos"])
        state["canvas"] = copy.deepcopy(current_state["canvas"])
        state["display_inline_items"] = copy.deepcopy(current_state.get("display_inline_items", []))
        return state


def push_display_inline_item(item: Dict[str, Any], session_id: Optional[str] = None):
    """Push a display_inline item to the agent state (thread-safe).

    This is called by the display_inline tool to store rich content
    that bypasses LangGraph serialization.

    Args:
        item: The display result dict with type, display_type, data, etc.
        session_id: Session ID for virtual FS mode, None for physical FS mode.
    """
    if USE_VIRTUAL_FS and session_id:
        current_state = _get_session_state(session_id)
        state_lock = _session_agents_lock
    else:
        current_state = _agent_state
        state_lock = _agent_state_lock

    with state_lock:
        if "display_inline_items" not in current_state:
            current_state["display_inline_items"] = []
        current_state["display_inline_items"].append(item)
        current_state["last_update"] = time.time()


def reset_agent_state(session_id: Optional[str] = None):
    """Reset agent state for a fresh session (thread-safe).

    Called on page load to ensure clean state after browser refresh.
    Preserves canvas items loaded from canvas.md (physical FS only).

    Args:
        session_id: Session ID for virtual FS mode, None for physical FS mode.
    """
    if USE_VIRTUAL_FS and session_id:
        current_state = _get_session_state(session_id)
        state_lock = _session_agents_lock
    else:
        current_state = _agent_state
        state_lock = _agent_state_lock

    with state_lock:
        current_state["running"] = False
        current_state["thinking"] = ""
        current_state["todos"] = []
        current_state["tool_calls"] = []
        current_state["display_inline_items"] = []
        current_state["response"] = ""
        current_state["error"] = None
        current_state["stop_event"] = None
        current_state["stop_requested"] = False
        current_state["interrupt"] = None
        current_state["start_time"] = None
        current_state["stop_requested"] = False
        current_state["last_update"] = time.time()
        # Note: canvas is preserved - it's loaded from canvas.md on startup (physical FS only)

# =============================================================================
# DASH APP
# =============================================================================

app = Dash(
    __name__,
    suppress_callback_exceptions=True,
    title=APP_TITLE,
    external_stylesheets=dmc.styles.ALL,
    external_scripts=[
        "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js",
    ],
    assets_folder=str(Path(__file__).parent / "assets"),
)

# Custom index string for SVG favicon support
app.index_string = '''<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        <link rel="icon" type="image/svg+xml" href="/assets/favicon.ico">
        {%css%}
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>'''


# =============================================================================
# LAYOUT
# =============================================================================

def create_layout():
    """Create the app layout with current configuration."""
    # Use agent's name/description if available, otherwise fall back to config
    title = getattr(agent, 'name', None) or APP_TITLE
    subtitle = getattr(agent, 'description', None) or APP_SUBTITLE

    # In virtual FS mode, pass None for workspace_root to show empty tree initially
    # The file tree will be populated per-session via callbacks
    workspace_for_layout = None if USE_VIRTUAL_FS else WORKSPACE_ROOT

    return create_layout_component(
        workspace_root=workspace_for_layout,
        app_title=title,
        app_subtitle=subtitle,
        colors=COLORS,
        styles=STYLES,
        agent=agent,
        welcome_message=WELCOME_MESSAGE
    )

# Set layout as a function so it uses current WORKSPACE_ROOT
app.layout = create_layout

# Note: Component rendering functions imported from components module
# These are used in callbacks below with COLORS and STYLES passed as parameters

# =============================================================================
# CALLBACKS
# =============================================================================

# Initial message display
@app.callback(
    [Output("chat-messages", "children"),
     Output("skip-history-render", "data", allow_duplicate=True),
     Output("session-initialized", "data", allow_duplicate=True),
     Output("session-id", "data", allow_duplicate=True)],
    [Input("chat-history", "data")],
    [State("theme-store", "data"),
     State("skip-history-render", "data"),
     State("session-initialized", "data"),
     State("session-id", "data")],
    prevent_initial_call='initial_duplicate'
)
def display_initial_messages(history, theme, skip_render, session_initialized, session_id):
    """Display initial welcome message or chat history.

    On first call (page load), resets agent state for a fresh session.
    Skip rendering if skip_render flag is set - this prevents duplicate renders
    when poll_agent_updates already handles the rendering.
    """
    # Initialize session on page load (first callback trigger)
    new_session_id = session_id
    if not session_initialized:
        # Create or validate session ID for virtual FS mode
        new_session_id = get_or_create_session_id(session_id)
        reset_agent_state(new_session_id)

    # Skip if flag is set (poll_agent_updates already rendered)
    if skip_render:
        return no_update, False, True, new_session_id  # Reset skip flag, mark session initialized

    if not history:
        return [], False, True, new_session_id

    colors = get_colors(theme or "light")
    messages = []
    for msg in history:
        msg_response_time = msg.get("response_time") if msg["role"] == "assistant" else None
        messages.append(format_message(msg["role"], msg["content"], colors, STYLES, is_new=False, response_time=msg_response_time))
        # Order: tool calls -> todos -> thinking -> display inline items
        # Render tool calls stored with this message
        if msg.get("tool_calls"):
            # Show collapsed tool calls section first
            tool_calls_block = format_tool_calls_inline(msg["tool_calls"], colors)
            if tool_calls_block:
                messages.append(tool_calls_block)
        # Render todos stored with this message
        if msg.get("todos"):
            todos_block = format_todos_inline(msg["todos"], colors)
            if todos_block:
                messages.append(todos_block)
        # Extract and show thinking from tool calls
        if msg.get("tool_calls"):
            thinking_blocks = extract_thinking_from_tool_calls(msg["tool_calls"], colors)
            messages.extend(thinking_blocks)
            # Extract and show display_inline results prominently
            inline_results = extract_display_inline_results(msg["tool_calls"], colors)
            messages.extend(inline_results)
        # Render display_inline items stored with this message
        if msg.get("display_inline_items"):
            for item in msg["display_inline_items"]:
                rendered = render_display_inline_result(item, colors)
                messages.append(rendered)
    return messages, False, True, new_session_id


# Initialize file tree for virtual FS sessions
@app.callback(
    Output("file-tree", "children", allow_duplicate=True),
    Input("session-initialized", "data"),
    [State("session-id", "data"),
     State("current-workspace-path", "data"),
     State("theme-store", "data")],
    prevent_initial_call=True
)
def initialize_file_tree_for_session(session_initialized, session_id, current_workspace, theme):
    """Initialize file tree when a new session is created (virtual FS mode).

    In virtual FS mode, the file tree starts empty. This callback populates it
    when the session is initialized, showing the default workspace structure.
    """
    if not USE_VIRTUAL_FS:
        raise PreventUpdate

    if not session_initialized or not session_id:
        raise PreventUpdate

    colors = get_colors(theme or "light")

    # Get workspace for this session
    workspace_root = get_workspace_for_session(session_id)

    # Calculate current workspace directory
    current_workspace_dir = workspace_root.path(current_workspace) if current_workspace else workspace_root.root

    # Build and render file tree
    return render_file_tree(build_file_tree(current_workspace_dir, current_workspace_dir), colors, STYLES, workspace_root=workspace_root)


# Chat callbacks
@app.callback(
    [Output("chat-messages", "children", allow_duplicate=True),
     Output("chat-history", "data", allow_duplicate=True),
     Output("chat-input", "value"),
     Output("pending-message", "data"),
     Output("poll-interval", "disabled")],
    [Input("send-btn", "n_clicks"),
     Input("chat-input", "n_submit")],
    [State("chat-input", "value"),
     State("chat-history", "data"),
     State("theme-store", "data"),
     State("current-workspace-path", "data"),
     State("session-id", "data")],
    prevent_initial_call=True
)
def handle_send_immediate(n_clicks, n_submit, message, history, theme, current_workspace_path, session_id):
    """Phase 1: Immediately show user message and start agent."""
    if not message or not message.strip():
        raise PreventUpdate

    colors = get_colors(theme or "light")
    message = message.strip()
    history = history or []
    history.append({"role": "user", "content": message})

    # Render all history messages including tool calls and todos
    messages = []
    for i, m in enumerate(history):
        is_new = (i == len(history) - 1)
        msg_response_time = m.get("response_time") if m["role"] == "assistant" else None
        messages.append(format_message(m["role"], m["content"], colors, STYLES, is_new=is_new, response_time=msg_response_time))
        # Order: tool calls -> todos -> thinking -> display inline items
        if m.get("tool_calls"):
            # Show collapsed tool calls section first
            tool_calls_block = format_tool_calls_inline(m["tool_calls"], colors)
            if tool_calls_block:
                messages.append(tool_calls_block)
        # Render todos stored with this message
        if m.get("todos"):
            todos_block = format_todos_inline(m["todos"], colors)
            if todos_block:
                messages.append(todos_block)
        # Extract and show thinking from tool calls
        if m.get("tool_calls"):
            thinking_blocks = extract_thinking_from_tool_calls(m["tool_calls"], colors)
            messages.extend(thinking_blocks)
            # Extract and show display_inline results prominently
            inline_results = extract_display_inline_results(m["tool_calls"], colors)
            messages.extend(inline_results)

    messages.append(format_loading(colors))

    # Calculate workspace path for agent context
    # In virtual FS mode, use virtual paths (e.g., /workspace/subdir)
    # In physical FS mode, use actual filesystem paths
    if USE_VIRTUAL_FS:
        # Virtual FS mode: use the virtual path directly
        # The VirtualFilesystem root is /workspace, so paths are like /workspace or /workspace/subdir
        workspace_full_path = f"/workspace/{current_workspace_path}" if current_workspace_path else "/workspace"
    else:
        # Physical FS mode: use actual filesystem path
        workspace_full_path = str(WORKSPACE_ROOT / current_workspace_path if current_workspace_path else WORKSPACE_ROOT)

    # Start agent in background with workspace context
    call_agent(message, workspace_path=workspace_full_path, session_id=session_id)

    # Enable polling
    return messages, history, "", message, False


@app.callback(
    [Output("chat-messages", "children", allow_duplicate=True),
     Output("chat-history", "data", allow_duplicate=True),
     Output("poll-interval", "disabled", allow_duplicate=True),
     Output("skip-history-render", "data", allow_duplicate=True)],
    Input("poll-interval", "n_intervals"),
    [State("chat-history", "data"),
     State("pending-message", "data"),
     State("theme-store", "data"),
     State("session-id", "data")],
    prevent_initial_call=True
)
def poll_agent_updates(n_intervals, history, pending_message, theme, session_id):
    """Poll for agent updates and display them in real-time.

    Tool calls are stored in history and persist across turns.
    History items can be:
    - {"role": "user", "content": "..."} - user message
    - {"role": "assistant", "content": "...", "tool_calls": [...]} - assistant message with tool calls
    """
    state = get_agent_state(session_id)
    history = history or []
    colors = get_colors(theme or "light")

    # Get display_inline items from agent state (bypasses LangGraph serialization)
    display_inline_items = state.get("display_inline_items", [])

    def render_history_messages(history_items):
        """Render all history items including tool calls, display_inline items, and todos."""
        messages = []
        for msg in history_items:
            msg_response_time = msg.get("response_time") if msg["role"] == "assistant" else None
            messages.append(format_message(msg["role"], msg["content"], colors, STYLES, response_time=msg_response_time))
            # Order: tool calls -> todos -> thinking -> display inline items
            if msg.get("tool_calls"):
                # Show collapsed tool calls section first
                tool_calls_block = format_tool_calls_inline(msg["tool_calls"], colors)
                if tool_calls_block:
                    messages.append(tool_calls_block)
            # Render todos stored with this message
            if msg.get("todos"):
                todos_block = format_todos_inline(msg["todos"], colors)
                if todos_block:
                    messages.append(todos_block)
            # Extract and show thinking from tool calls
            if msg.get("tool_calls"):
                thinking_blocks = extract_thinking_from_tool_calls(msg["tool_calls"], colors)
                messages.extend(thinking_blocks)
                # Extract and show display_inline results prominently
                inline_results = extract_display_inline_results(msg["tool_calls"], colors)
                messages.extend(inline_results)
            # Render display_inline items stored with this message
            if msg.get("display_inline_items"):
                for item in msg["display_inline_items"]:
                    rendered = render_display_inline_result(item, colors)
                    messages.append(rendered)
        return messages

    # Check for interrupt (human-in-the-loop)
    if state.get("interrupt"):
        # Agent is paused waiting for user input
        messages = render_history_messages(history)

        # Order: tool calls -> todos -> thinking -> display inline items
        if state.get("tool_calls"):
            # Show collapsed tool calls section first
            tool_calls_block = format_tool_calls_inline(state["tool_calls"], colors)
            if tool_calls_block:
                messages.append(tool_calls_block)

        if state["todos"]:
            todos_block = format_todos_inline(state["todos"], colors)
            if todos_block:
                messages.append(todos_block)

        if state.get("tool_calls"):
            # Extract and show thinking from tool calls
            thinking_blocks = extract_thinking_from_tool_calls(state["tool_calls"], colors)
            messages.extend(thinking_blocks)
            # Extract and show display_inline results prominently
            inline_results = extract_display_inline_results(state["tool_calls"], colors)
            messages.extend(inline_results)

        # Render any queued display_inline items (bypasses LangGraph serialization)
        for item in display_inline_items:
            rendered = render_display_inline_result(item, colors)
            messages.append(rendered)

        # Add interrupt UI
        interrupt_block = format_interrupt(state["interrupt"], colors)
        if interrupt_block:
            messages.append(interrupt_block)

        # Disable polling - wait for user to respond to interrupt
        return messages, no_update, True, no_update

    # Check if agent is done
    if not state["running"]:
        # Calculate response time
        response_time = None
        if state.get("start_time"):
            response_time = time.time() - state["start_time"]

        # Agent finished - store tool calls, todos, and display_inline items with the USER message
        # (they appear after user msg in the UI)
        saved_display_inline_items = False
        if history:
            # Find the last user message and attach tool calls, todos, and display_inline items to it
            for i in range(len(history) - 1, -1, -1):
                if history[i]["role"] == "user":
                    if state.get("tool_calls"):
                        history[i]["tool_calls"] = state["tool_calls"]
                    if state.get("todos"):
                        history[i]["todos"] = state["todos"]
                    if display_inline_items:
                        history[i]["display_inline_items"] = display_inline_items
                        saved_display_inline_items = True
                    break

        # Add assistant response to history (with response time)
        assistant_msg = {
            "role": "assistant",
            "content": state["response"] if state["response"] else f"Error: {state['error']}",
            "response_time": response_time,
        }

        history.append(assistant_msg)

        # Render all history (tool calls and todos are now part of history)
        # Order: tool calls -> todos -> thinking -> display inline items
        final_messages = []
        for i, msg in enumerate(history):
            is_new = (i >= len(history) - 1)
            msg_response_time = msg.get("response_time") if msg["role"] == "assistant" else None
            final_messages.append(format_message(msg["role"], msg["content"], colors, STYLES, is_new=is_new, response_time=msg_response_time))
            # Show collapsed tool calls section first
            if msg.get("tool_calls"):
                tool_calls_block = format_tool_calls_inline(msg["tool_calls"], colors)
                if tool_calls_block:
                    final_messages.append(tool_calls_block)
            # Render todos stored with this message
            if msg.get("todos"):
                todos_block = format_todos_inline(msg["todos"], colors)
                if todos_block:
                    final_messages.append(todos_block)
            # Extract and show thinking from tool calls
            if msg.get("tool_calls"):
                thinking_blocks = extract_thinking_from_tool_calls(msg["tool_calls"], colors)
                final_messages.extend(thinking_blocks)
                # Extract and show display_inline results prominently
                inline_results = extract_display_inline_results(msg["tool_calls"], colors)
                final_messages.extend(inline_results)
            # Render display_inline items stored with this message
            if msg.get("display_inline_items"):
                for item in msg["display_inline_items"]:
                    rendered = render_display_inline_result(item, colors)
                    final_messages.append(rendered)

        # Render any NEW queued display_inline items only if not already saved to history
        # (avoids duplicate rendering)
        if not saved_display_inline_items:
            for item in display_inline_items:
                rendered = render_display_inline_result(item, colors)
                final_messages.append(rendered)

        # Disable polling, set skip flag to prevent display_initial_messages from re-rendering
        return final_messages, history, True, True
    else:
        # Agent still running - show loading with current tool_calls/todos/thinking
        messages = render_history_messages(history)

        # Order: tool calls -> todos -> thinking -> display inline items
        if state.get("tool_calls"):
            # Show collapsed tool calls section first
            tool_calls_block = format_tool_calls_inline(state["tool_calls"], colors)
            if tool_calls_block:
                messages.append(tool_calls_block)

        # Add current todos if available
        if state["todos"]:
            todos_block = format_todos_inline(state["todos"], colors)
            if todos_block:
                messages.append(todos_block)

        if state.get("tool_calls"):
            # Extract and show thinking from tool calls
            thinking_blocks = extract_thinking_from_tool_calls(state["tool_calls"], colors)
            messages.extend(thinking_blocks)
            # Extract and show display_inline results prominently
            inline_results = extract_display_inline_results(state["tool_calls"], colors)
            messages.extend(inline_results)

        # Render any queued display_inline items (bypasses LangGraph serialization)
        for item in display_inline_items:
            rendered = render_display_inline_result(item, colors)
            messages.append(rendered)

        # Add loading indicator
        messages.append(format_loading(colors))

        # Continue polling, no skip flag needed
        return messages, no_update, False, no_update


# Stop button visibility - show when agent is running
@app.callback(
    Output("stop-btn", "style"),
    Input("poll-interval", "n_intervals"),
    State("session-id", "data"),
    prevent_initial_call=True
)
def update_stop_button_visibility(n_intervals, session_id):
    """Show stop button when agent is running, hide otherwise."""
    state = get_agent_state(session_id)
    if state.get("running"):
        return {}  # Show button (remove display:none)
    else:
        return {"display": "none"}  # Hide button


# Stop button click handler
@app.callback(
    [Output("chat-messages", "children", allow_duplicate=True),
     Output("poll-interval", "disabled", allow_duplicate=True)],
    Input("stop-btn", "n_clicks"),
    [State("chat-history", "data"),
     State("theme-store", "data"),
     State("session-id", "data")],
    prevent_initial_call=True
)
def handle_stop_button(n_clicks, history, theme, session_id):
    """Handle stop button click to stop agent execution."""
    if not n_clicks:
        raise PreventUpdate

    colors = get_colors(theme or "light")
    history = history or []

    # Request the agent to stop
    request_agent_stop(session_id)

    # Render current messages with a stopping indicator
    # Order: tool calls -> todos -> thinking -> display inline items
    def render_history_messages(history):
        messages = []
        for i, msg in enumerate(history):
            msg_response_time = msg.get("response_time") if msg["role"] == "assistant" else None
            messages.append(format_message(msg["role"], msg["content"], colors, STYLES, is_new=False, response_time=msg_response_time))
            if msg.get("tool_calls"):
                # Show collapsed tool calls section first
                tool_calls_block = format_tool_calls_inline(msg["tool_calls"], colors)
                if tool_calls_block:
                    messages.append(tool_calls_block)
            if msg.get("todos"):
                todos_block = format_todos_inline(msg["todos"], colors)
                if todos_block:
                    messages.append(todos_block)
            if msg.get("tool_calls"):
                # Extract and show thinking from tool calls
                thinking_blocks = extract_thinking_from_tool_calls(msg["tool_calls"], colors)
                messages.extend(thinking_blocks)
                # Extract and show display_inline results prominently
                inline_results = extract_display_inline_results(msg["tool_calls"], colors)
                messages.extend(inline_results)
            # Render display_inline items stored with this message
            if msg.get("display_inline_items"):
                for item in msg["display_inline_items"]:
                    rendered = render_display_inline_result(item, colors)
                    messages.append(rendered)
        return messages

    messages = render_history_messages(history)

    # Add stopping message
    messages.append(html.Div([
        html.Span("Stopping...", style={
            "fontSize": "15px",
            "fontWeight": "500",
            "color": colors["warning"],
        })
    ], className="chat-message chat-message-loading", style={"padding": "12px 15px"}))

    # Keep polling to detect when agent actually stops
    return messages, False


# Interrupt handling callbacks
@app.callback(
    [Output("chat-messages", "children", allow_duplicate=True),
     Output("poll-interval", "disabled", allow_duplicate=True)],
    [Input("interrupt-approve-btn", "n_clicks"),
     Input("interrupt-reject-btn", "n_clicks"),
     Input("interrupt-edit-btn", "n_clicks")],
    [State("interrupt-input", "value"),
     State("chat-history", "data"),
     State("theme-store", "data"),
     State("session-id", "data")],
    prevent_initial_call=True
)
def handle_interrupt_response(approve_clicks, reject_clicks, edit_clicks, input_value, history, theme, session_id):
    """Handle user response to an interrupt.

    Note: Click parameters are required for Dash callback inputs but we use
    ctx.triggered to determine which button was clicked.
    """
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate

    triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]
    triggered_value = ctx.triggered[0].get("value")

    # Only proceed if there was an actual click (value > 0)
    if not triggered_value or triggered_value <= 0:
        raise PreventUpdate

    colors = get_colors(theme or "light")
    history = history or []

    # Determine action based on which button was clicked
    if triggered_id == "interrupt-approve-btn":
        if not approve_clicks or approve_clicks <= 0:
            raise PreventUpdate
        action = "approve"
        decision = input_value or "approved"
    elif triggered_id == "interrupt-reject-btn":
        if not reject_clicks or reject_clicks <= 0:
            raise PreventUpdate
        action = "reject"
        decision = input_value or "rejected"
    elif triggered_id == "interrupt-edit-btn":
        if not edit_clicks or edit_clicks <= 0:
            raise PreventUpdate
        action = "edit"
        decision = input_value or ""
        if not decision:
            raise PreventUpdate  # Need input for edit action
    else:
        raise PreventUpdate

    # Resume the agent with the user's decision
    resume_agent_from_interrupt(decision, action, session_id=session_id)

    # Show loading state while agent resumes
    # Order: tool calls -> todos -> thinking -> display inline items
    messages = []
    for msg in history:
        msg_response_time = msg.get("response_time") if msg["role"] == "assistant" else None
        messages.append(format_message(msg["role"], msg["content"], colors, STYLES, response_time=msg_response_time))
        if msg.get("tool_calls"):
            # Show collapsed tool calls section first
            tool_calls_block = format_tool_calls_inline(msg["tool_calls"], colors)
            if tool_calls_block:
                messages.append(tool_calls_block)
        # Render todos stored with this message
        if msg.get("todos"):
            todos_block = format_todos_inline(msg["todos"], colors)
            if todos_block:
                messages.append(todos_block)
        if msg.get("tool_calls"):
            # Extract and show thinking from tool calls
            thinking_blocks = extract_thinking_from_tool_calls(msg["tool_calls"], colors)
            messages.extend(thinking_blocks)
            # Extract and show display_inline results prominently
            inline_results = extract_display_inline_results(msg["tool_calls"], colors)
            messages.extend(inline_results)
        # Render display_inline items stored with this message
        if msg.get("display_inline_items"):
            for item in msg["display_inline_items"]:
                rendered = render_display_inline_result(item, colors)
                messages.append(rendered)

    messages.append(format_loading(colors))

    # Re-enable polling
    return messages, False


# Folder toggle callback - triggered by clicking the expand icon
@app.callback(
    [Output({"type": "folder-children", "path": ALL}, "style"),
     Output({"type": "folder-icon", "path": ALL}, "style"),
     Output({"type": "folder-children", "path": ALL}, "children"),
     Output("expanded-folders", "data")],
    Input({"type": "folder-icon", "path": ALL}, "n_clicks"),
    [State({"type": "folder-header", "path": ALL}, "id"),
     State({"type": "folder-header", "path": ALL}, "data-realpath"),
     State({"type": "folder-children", "path": ALL}, "id"),
     State({"type": "folder-icon", "path": ALL}, "id"),
     State({"type": "folder-children", "path": ALL}, "style"),
     State({"type": "folder-icon", "path": ALL}, "style"),
     State({"type": "folder-children", "path": ALL}, "children"),
     State("theme-store", "data"),
     State("session-id", "data"),
     State("expanded-folders", "data")],
    prevent_initial_call=True
)
def toggle_folder(n_clicks, header_ids, real_paths, children_ids, icon_ids, children_styles, icon_styles, children_content, theme, session_id, expanded_folders):
    """Toggle folder expansion and lazy load contents if needed."""
    ctx = callback_context
    if not ctx.triggered or not any(n_clicks):
        raise PreventUpdate

    colors = get_colors(theme or "light")
    expanded_folders = expanded_folders or []

    # Get workspace for this session (virtual or physical)
    workspace_root = get_workspace_for_session(session_id)
    triggered = ctx.triggered[0]["prop_id"]
    try:
        id_str = triggered.rsplit(".", 1)[0]
        id_dict = json.loads(id_str)
        clicked_path = id_dict.get("path")
    except:
        raise PreventUpdate

    # Build a mapping from folder path to real path using header_ids and real_paths
    path_to_realpath = {}
    for i, header_id in enumerate(header_ids):
        if i < len(real_paths):
            path_to_realpath[header_id["path"]] = real_paths[i]

    folder_rel_path = path_to_realpath.get(clicked_path)
    if not folder_rel_path:
        raise PreventUpdate

    new_children_styles = []
    new_icon_styles = []
    new_children_content = []

    # Track whether we're expanding or collapsing the clicked folder
    will_expand = None

    # Process all folder-children elements
    for i, child_id in enumerate(children_ids):
        path = child_id["path"]
        current_style = children_styles[i] if i < len(children_styles) else {"display": "none"}
        current_content = children_content[i] if i < len(children_content) else []

        if path == clicked_path:
            # Toggle this folder
            is_expanded = current_style.get("display") != "none"
            will_expand = not is_expanded
            new_children_styles.append({"display": "none" if is_expanded else "block"})

            # If expanding and content is just "Loading...", load the actual contents
            if not is_expanded and current_content:
                # Check if content is the loading placeholder
                if (isinstance(current_content, list) and len(current_content) == 1 and
                    isinstance(current_content[0], dict) and
                    current_content[0].get("props", {}).get("children") == "Loading..."):
                    # Load folder contents using real path
                    try:
                        folder_items = load_folder_contents(folder_rel_path, workspace_root)
                        loaded_content = render_file_tree(folder_items, colors, STYLES,
                                                          level=folder_rel_path.count("/") + folder_rel_path.count("\\") + 1,
                                                          parent_path=folder_rel_path,
                                                          expanded_folders=expanded_folders,
                                                          workspace_root=workspace_root)
                        new_children_content.append(loaded_content if loaded_content else current_content)
                    except Exception as e:
                        print(f"Error loading folder {folder_rel_path}: {e}")
                        new_children_content.append(current_content)
                else:
                    new_children_content.append(current_content)
            else:
                new_children_content.append(current_content)
        else:
            new_children_styles.append(current_style)
            new_children_content.append(current_content)

    # Process all folder-icon elements
    for i, icon_id in enumerate(icon_ids):
        path = icon_id["path"]
        current_icon_style = icon_styles[i] if i < len(icon_styles) else {}

        if path == clicked_path:
            # Find corresponding children style to check if expanded
            children_idx = next((idx for idx, cid in enumerate(children_ids) if cid["path"] == path), None)
            if children_idx is not None:
                current_children_style = children_styles[children_idx] if children_idx < len(children_styles) else {"display": "none"}
                is_expanded = current_children_style.get("display") != "none"
                new_icon_styles.append({
                    "marginRight": "5px",
                    "fontSize": "10px",
                    "transition": "transform 0.15s",
                    "display": "inline-block",
                    "padding": "2px",
                    "transform": "rotate(0deg)" if is_expanded else "rotate(90deg)",
                })
            else:
                new_icon_styles.append(current_icon_style)
        else:
            new_icon_styles.append(current_icon_style)

    # Update expanded folders list
    new_expanded_folders = list(expanded_folders)
    if will_expand is not None:
        if will_expand and clicked_path not in new_expanded_folders:
            new_expanded_folders.append(clicked_path)
        elif not will_expand and clicked_path in new_expanded_folders:
            new_expanded_folders.remove(clicked_path)

    return new_children_styles, new_icon_styles, new_children_content, new_expanded_folders


# Enter folder callback - triggered by double-clicking folder name (changes workspace root)
@app.callback(
    [Output("current-workspace-path", "data"),
     Output("workspace-breadcrumb", "children"),
     Output("file-tree", "children", allow_duplicate=True),
     Output("expanded-folders", "data", allow_duplicate=True)],
    [Input({"type": "folder-select", "path": ALL}, "n_clicks"),
     Input("breadcrumb-root", "n_clicks"),
     Input({"type": "breadcrumb-segment", "index": ALL}, "n_clicks")],
    [State({"type": "folder-select", "path": ALL}, "id"),
     State({"type": "folder-select", "path": ALL}, "data-folderpath"),
     State({"type": "folder-select", "path": ALL}, "n_clicks"),
     State("current-workspace-path", "data"),
     State("theme-store", "data"),
     State("session-id", "data")],
    prevent_initial_call=True
)
def enter_folder(folder_clicks, root_clicks, breadcrumb_clicks, folder_ids, folder_paths, _prev_clicks, current_path, theme, session_id):
    """Enter a folder (double-click) or navigate via breadcrumb."""
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate

    colors = get_colors(theme or "light")
    triggered = ctx.triggered[0]["prop_id"]

    new_path = current_path or ""

    # Check if breadcrumb root was clicked
    if "breadcrumb-root" in triggered:
        new_path = ""
    # Check if a breadcrumb segment was clicked
    elif "breadcrumb-segment" in triggered:
        try:
            id_str = triggered.rsplit(".", 1)[0]
            id_dict = json.loads(id_str)
            segment_index = id_dict.get("index")
            # Build path up to this segment
            if current_path:
                parts = current_path.split("/")
                new_path = "/".join(parts[:segment_index + 1])
            else:
                new_path = ""
        except:
            raise PreventUpdate
    # Check if a folder was double-clicked (n_clicks >= 2 and increased by 1)
    elif "folder-select" in triggered:
        try:
            id_str = triggered.rsplit(".", 1)[0]
            id_dict = json.loads(id_str)
            clicked_path = id_dict.get("path")
        except:
            raise PreventUpdate

        # Find the folder and check for double-click
        for i, folder_id in enumerate(folder_ids):
            if folder_id["path"] == clicked_path:
                current_clicks = folder_clicks[i] if i < len(folder_clicks) else 0

                # Only enter on double-click (clicks increased and is even number >= 2)
                if current_clicks and current_clicks >= 2 and current_clicks % 2 == 0:
                    folder_rel_path = folder_paths[i] if i < len(folder_paths) else ""
                    # Combine with current workspace path
                    if current_path:
                        new_path = f"{current_path}/{folder_rel_path}"
                    else:
                        new_path = folder_rel_path
                else:
                    # Single click - don't change workspace
                    raise PreventUpdate
                break
        else:
            raise PreventUpdate
    else:
        raise PreventUpdate

    # Build breadcrumb navigation
    breadcrumb_children = [
        html.Span([
            DashIconify(icon="mdi:home", width=14, style={"marginRight": "4px"}),
            "root"
        ], id="breadcrumb-root", className="breadcrumb-item breadcrumb-clickable", style={
            "display": "inline-flex",
            "alignItems": "center",
            "cursor": "pointer",
            "padding": "2px 6px",
            "borderRadius": "3px",
        }),
    ]

    if new_path:
        parts = new_path.split("/")
        for i, part in enumerate(parts):
            # Add separator
            breadcrumb_children.append(
                html.Span(" / ", className="breadcrumb-separator", style={
                    "color": "var(--mantine-color-dimmed)",
                    "margin": "0 2px",
                })
            )
            # Add clickable segment
            breadcrumb_children.append(
                html.Span(part, id={"type": "breadcrumb-segment", "index": i},
                    className="breadcrumb-item breadcrumb-clickable",
                    style={
                        "cursor": "pointer",
                        "padding": "2px 6px",
                        "borderRadius": "3px",
                    }
                )
            )

    # Get workspace for this session (virtual or physical)
    workspace_root = get_workspace_for_session(session_id)

    # Calculate the actual workspace path
    if USE_VIRTUAL_FS:
        workspace_full_path = workspace_root.path(new_path) if new_path else workspace_root.root
    else:
        workspace_full_path = workspace_root / new_path if new_path else workspace_root

    # Render new file tree (reset expanded folders when navigating)
    file_tree = render_file_tree(
        build_file_tree(workspace_full_path, workspace_full_path),
        colors, STYLES,
        workspace_root=workspace_root
    )

    return new_path, breadcrumb_children, file_tree, []  # Reset expanded folders


# File click - open modal
@app.callback(
    [Output("file-modal", "opened"),
     Output("file-modal", "title"),
     Output("modal-content", "children"),
     Output("file-to-view", "data"),
     Output("file-click-tracker", "data")],
    Input({"type": "file-item", "path": ALL}, "n_clicks"),
    [State({"type": "file-item", "path": ALL}, "id"),
     State("file-click-tracker", "data"),
     State("theme-store", "data"),
     State("session-id", "data")],
    prevent_initial_call=True
)
def open_file_modal(all_n_clicks, all_ids, click_tracker, theme, session_id):
    """Open file in modal - only on actual new clicks."""
    ctx = callback_context

    if not ctx.triggered_id:
        raise PreventUpdate

    # ctx.triggered_id is the dict {"type": "file-item", "path": "..."}
    if not isinstance(ctx.triggered_id, dict):
        raise PreventUpdate

    if ctx.triggered_id.get("type") != "file-item":
        raise PreventUpdate

    file_path = ctx.triggered_id.get("path")
    if not file_path:
        raise PreventUpdate

    # Find the index of the triggered item to get its click count
    clicked_idx = None
    for i, item_id in enumerate(all_ids):
        if item_id.get("path") == file_path:
            clicked_idx = i
            break

    if clicked_idx is None:
        raise PreventUpdate

    # Get current click count for this file
    current_clicks = all_n_clicks[clicked_idx] if clicked_idx < len(all_n_clicks) else None

    # Must be an actual click (not None, not 0)
    if not current_clicks:
        raise PreventUpdate

    # Check if this is a NEW click vs a re-render with existing clicks
    click_tracker = click_tracker or {}
    prev_clicks = click_tracker.get(file_path, 0)

    # Update tracker regardless of whether we open modal
    new_tracker = click_tracker.copy()
    new_tracker[file_path] = current_clicks

    if current_clicks <= prev_clicks:
        # Not a new click - component was re-rendered or this click was already processed
        # Still need to return updated tracker to avoid stale state
        raise PreventUpdate

    # Get workspace for this session (virtual or physical)
    workspace_root = get_workspace_for_session(session_id)

    # Verify file exists and is a file
    if USE_VIRTUAL_FS:
        full_path = workspace_root.path(file_path)
    else:
        full_path = workspace_root / file_path
    if not full_path.exists() or not full_path.is_file():
        raise PreventUpdate

    colors = get_colors(theme or "light")
    content, is_text, error = read_file_content(workspace_root, file_path)
    filename = Path(file_path).name
    file_ext = Path(file_path).suffix.lower()

    # Define file type categories for binary previews
    image_exts = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.bmp'}
    pdf_exts = {'.pdf'}

    # Check for binary preview types first
    if file_ext in image_exts | pdf_exts:
        b64, _, mime = get_file_download_data(workspace_root, file_path)
        if b64:
            data_url = f"data:{mime};base64,{b64}"

            if file_ext in image_exts:
                # Image preview
                modal_content = html.Div([
                    html.Img(
                        src=data_url,
                        style={
                            "maxWidth": "100%",
                            "maxHeight": "80vh",
                            "display": "block",
                            "margin": "0 auto",
                            "borderRadius": "4px",
                        }
                    )
                ], style={"textAlign": "center"})

            elif file_ext in pdf_exts:
                # PDF preview via embed
                modal_content = html.Embed(
                    src=data_url,
                    type="application/pdf",
                    style={
                        "width": "100%",
                        "height": "80vh",
                        "borderRadius": "4px",
                    }
                )
        else:
            # Failed to read binary file
            modal_content = html.Div([
                html.P("Failed to load file preview", style={
                    "color": colors["text_muted"],
                    "textAlign": "center",
                    "padding": "40px",
                }),
                html.P("Click Download to save the file.", style={
                    "color": colors["text_muted"],
                    "textAlign": "center",
                    "fontSize": "13px",
                })
            ])

    elif is_text and content:
        # HTML files get rendered preview
        if file_ext in ('.html', '.htm'):
            modal_content = html.Div([
                # Tab buttons for switching views
                html.Div([
                    html.Button("Preview", id="html-preview-tab", n_clicks=0,
                        className="html-tab-btn html-tab-active",
                        style={"marginRight": "8px", "padding": "6px 12px", "border": "none",
                               "borderRadius": "4px", "cursor": "pointer",
                               "background": colors["accent"], "color": "#fff"}),
                    html.Button("Source", id="html-source-tab", n_clicks=0,
                        className="html-tab-btn",
                        style={"padding": "6px 12px", "border": f"1px solid {colors['border']}",
                               "borderRadius": "4px", "cursor": "pointer",
                               "background": "transparent", "color": colors["text_primary"]}),
                ], style={"marginBottom": "12px", "display": "flex"}),
                # Preview iframe (default visible)
                html.Iframe(
                    srcDoc=content,
                    style={
                        "width": "100%",
                        "height": "80vh",
                        "border": f"1px solid {colors['border']}",
                        "borderRadius": "4px",
                        "background": "#fff",
                    },
                    id="html-preview-frame"
                ),
                # Source code (hidden by default)
                html.Pre(
                    content,
                    id="html-source-code",
                    style={
                        "display": "none",
                        "background": colors["bg_tertiary"],
                        "padding": "16px",
                        "fontSize": "12px",
                        "fontFamily": "'IBM Plex Mono', monospace",
                        "overflow": "auto",
                        "maxHeight": "80vh",
                        "whiteSpace": "pre-wrap",
                        "wordBreak": "break-word",
                        "margin": "0",
                        "color": colors["text_primary"],
                        "border": f"1px solid {colors['border']}",
                        "borderRadius": "4px",
                    }
                )
            ])
        elif file_ext == '.json':
            # Try to parse as Plotly JSON figure
            plotly_figure = None
            try:
                data = json.loads(content)
                # Check if it looks like a Plotly figure (has 'data' key with list)
                if isinstance(data, dict) and 'data' in data and isinstance(data['data'], list):
                    plotly_figure = data
            except (json.JSONDecodeError, KeyError):
                pass

            if plotly_figure:
                # Render as interactive Plotly chart with source toggle
                modal_content = html.Div([
                    # Tab buttons for switching views
                    html.Div([
                        html.Button("Chart", id="html-preview-tab", n_clicks=0,
                            className="html-tab-btn html-tab-active",
                            style={"marginRight": "8px", "padding": "6px 12px", "border": "none",
                                   "borderRadius": "4px", "cursor": "pointer",
                                   "background": colors["accent"], "color": "#fff"}),
                        html.Button("JSON", id="html-source-tab", n_clicks=0,
                            className="html-tab-btn",
                            style={"padding": "6px 12px", "border": f"1px solid {colors['border']}",
                                   "borderRadius": "4px", "cursor": "pointer",
                                   "background": "transparent", "color": colors["text_primary"]}),
                    ], style={"marginBottom": "12px", "display": "flex"}),
                    # Plotly chart (default visible)
                    html.Div([
                        dcc.Graph(
                            figure=plotly_figure,
                            style={"height": "75vh"},
                            config={"displayModeBar": True, "responsive": True}
                        )
                    ], id="html-preview-frame", style={
                        "border": f"1px solid {colors['border']}",
                        "borderRadius": "4px",
                        "background": "#fff",
                    }),
                    # JSON source (hidden by default)
                    html.Pre(
                        json.dumps(plotly_figure, indent=2),
                        id="html-source-code",
                        style={
                            "display": "none",
                            "background": colors["bg_tertiary"],
                            "padding": "16px",
                            "fontSize": "12px",
                            "fontFamily": "'IBM Plex Mono', monospace",
                            "overflow": "auto",
                            "maxHeight": "80vh",
                            "whiteSpace": "pre-wrap",
                            "wordBreak": "break-word",
                            "margin": "0",
                            "color": colors["text_primary"],
                            "border": f"1px solid {colors['border']}",
                            "borderRadius": "4px",
                        }
                    )
                ])
            else:
                # Regular JSON - show formatted
                try:
                    formatted = json.dumps(json.loads(content), indent=2)
                except json.JSONDecodeError:
                    formatted = content
                modal_content = html.Pre(
                    formatted,
                    style={
                        "background": colors["bg_tertiary"],
                        "padding": "16px",
                        "fontSize": "12px",
                        "fontFamily": "'IBM Plex Mono', monospace",
                        "overflow": "auto",
                        "maxHeight": "80vh",
                        "whiteSpace": "pre-wrap",
                        "wordBreak": "break-word",
                        "margin": "0",
                        "color": colors["text_primary"],
                    }
                )
        elif file_ext in ('.csv', '.tsv'):
            # CSV/TSV files - render as table with raw view option
            import io as _io
            try:
                import pandas as pd
                sep = '\t' if file_ext == '.tsv' else ','
                df = pd.read_csv(_io.StringIO(content), sep=sep)

                # Pagination settings
                rows_per_page = 50
                total_rows = len(df)
                total_pages = max(1, (total_rows + rows_per_page - 1) // rows_per_page)
                current_page = 0

                # Create table preview (first page)
                start_idx = current_page * rows_per_page
                end_idx = min(start_idx + rows_per_page, total_rows)
                preview_df = df.iloc[start_idx:end_idx]

                # Row info for display
                if total_rows > rows_per_page:
                    row_info = f"Rows {start_idx + 1}-{end_idx} of {total_rows}"
                else:
                    row_info = f"{total_rows} rows"

                modal_content = html.Div([
                    # Tab buttons for switching views
                    html.Div([
                        html.Button("Table", id="html-preview-tab", n_clicks=0,
                            className="html-tab-btn html-tab-active",
                            style={"marginRight": "8px", "padding": "6px 12px", "border": "none",
                                   "borderRadius": "4px", "cursor": "pointer",
                                   "background": colors["accent"], "color": "#fff"}),
                        html.Button("Raw", id="html-source-tab", n_clicks=0,
                            className="html-tab-btn",
                            style={"padding": "6px 12px", "border": f"1px solid {colors['border']}",
                                   "borderRadius": "4px", "cursor": "pointer",
                                   "background": "transparent", "color": colors["text_primary"]}),
                    ], style={"marginBottom": "12px", "display": "flex"}),
                    # Row count info and pagination controls
                    html.Div([
                        html.Span(f"{len(df.columns)} columns, {row_info}", id="csv-row-info", style={
                            "fontSize": "12px",
                            "color": colors["text_muted"],
                        }),
                        # Pagination controls (only show if more than one page)
                        html.Div([
                            html.Button("◀", id="csv-prev-page", n_clicks=0,
                                disabled=current_page == 0,
                                style={
                                    "padding": "4px 8px", "border": f"1px solid {colors['border']}",
                                    "borderRadius": "4px", "cursor": "pointer",
                                    "background": "transparent", "color": colors["text_primary"],
                                    "marginRight": "8px", "fontSize": "12px",
                                }),
                            html.Span(f"Page {current_page + 1} of {total_pages}", id="csv-page-info",
                                style={"fontSize": "12px", "color": colors["text_primary"]}),
                            html.Button("▶", id="csv-next-page", n_clicks=0,
                                disabled=current_page >= total_pages - 1,
                                style={
                                    "padding": "4px 8px", "border": f"1px solid {colors['border']}",
                                    "borderRadius": "4px", "cursor": "pointer",
                                    "background": "transparent", "color": colors["text_primary"],
                                    "marginLeft": "8px", "fontSize": "12px",
                                }),
                        ], style={"display": "flex" if total_pages > 1 else "none", "alignItems": "center"}),
                    ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "8px"}),
                    # Store CSV data for pagination
                    dcc.Store(id="csv-data-store", data={
                        "content": content,
                        "sep": sep,
                        "total_rows": total_rows,
                        "total_pages": total_pages,
                        "rows_per_page": rows_per_page,
                        "current_page": current_page,
                    }),
                    # Table preview (default visible)
                    html.Div([
                        dcc.Markdown(
                            preview_df.to_html(index=False, classes="csv-preview-table"),
                            dangerously_allow_html=True,
                            style={"overflow": "auto"}
                        )
                    ], id="html-preview-frame", className="csv-table-container", style={
                        "border": f"1px solid {colors['border']}",
                        "borderRadius": "4px",
                        "background": colors["bg_secondary"],
                        "maxHeight": "65vh",
                        "overflow": "auto",
                    }),
                    # Raw CSV (hidden by default)
                    html.Pre(
                        content,
                        id="html-source-code",
                        style={
                            "display": "none",
                            "background": colors["bg_tertiary"],
                            "padding": "16px",
                            "fontSize": "12px",
                            "fontFamily": "'IBM Plex Mono', monospace",
                            "overflow": "auto",
                            "maxHeight": "80vh",
                            "whiteSpace": "pre-wrap",
                            "wordBreak": "break-word",
                            "margin": "0",
                            "color": colors["text_primary"],
                            "border": f"1px solid {colors['border']}",
                            "borderRadius": "4px",
                        }
                    )
                ])
            except Exception as e:
                # Fall back to raw text if parsing fails
                modal_content = html.Div([
                    html.Div(f"Could not parse as CSV: {e}", style={
                        "fontSize": "12px",
                        "color": colors["text_muted"],
                        "marginBottom": "8px",
                    }),
                    html.Pre(
                        content,
                        style={
                            "background": colors["bg_tertiary"],
                            "padding": "16px",
                            "fontSize": "12px",
                            "fontFamily": "'IBM Plex Mono', monospace",
                            "overflow": "auto",
                            "maxHeight": "80vh",
                            "whiteSpace": "pre-wrap",
                            "wordBreak": "break-word",
                            "margin": "0",
                            "color": colors["text_primary"],
                        }
                    )
                ])
        else:
            # Regular text files
            modal_content = html.Pre(
                content,
                style={
                    "background": colors["bg_tertiary"],
                    "padding": "16px",
                    "fontSize": "12px",
                    "fontFamily": "'IBM Plex Mono', monospace",
                    "overflow": "auto",
                    "maxHeight": "80vh",
                    "whiteSpace": "pre-wrap",
                    "wordBreak": "break-word",
                    "margin": "0",
                    "color": colors["text_primary"],
                }
            )
    else:
        modal_content = html.Div([
            html.P(error or "Cannot display file", style={
                "color": colors["text_muted"],
                "textAlign": "center",
                "padding": "40px",
            }),
            html.P("Click Download to save the file.", style={
                "color": colors["text_muted"],
                "textAlign": "center",
                "fontSize": "13px",
            })
        ])

    return True, filename, modal_content, file_path, new_tracker

# Modal download button
@app.callback(
    Output("file-download", "data", allow_duplicate=True),
    Input("modal-download-btn", "n_clicks"),
    [State("file-to-view", "data"),
     State("session-id", "data")],
    prevent_initial_call=True
)
def download_from_modal(n_clicks, file_path, session_id):
    """Download file from modal."""
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate

    # Verify this callback was actually triggered by the download button
    triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]
    if triggered_id != "modal-download-btn":
        raise PreventUpdate

    if not n_clicks or not file_path:
        raise PreventUpdate

    # Get workspace for this session (virtual or physical)
    workspace_root = get_workspace_for_session(session_id)

    b64, filename, mime = get_file_download_data(workspace_root, file_path)
    if not b64:
        raise PreventUpdate

    return dict(content=b64, filename=filename, base64=True, type=mime)


# HTML preview/source tab switching
@app.callback(
    [Output("html-preview-frame", "style"),
     Output("html-source-code", "style"),
     Output("html-preview-tab", "style"),
     Output("html-source-tab", "style")],
    [Input("html-preview-tab", "n_clicks"),
     Input("html-source-tab", "n_clicks")],
    [State("theme-store", "data"),
     State("html-preview-frame", "style"),
     State("html-source-code", "style")],
    prevent_initial_call=True
)
def toggle_html_view(preview_clicks, source_clicks, theme, current_preview_style, current_source_style):
    """Toggle between HTML preview and source code view."""
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate

    colors = get_colors(theme or "light")
    triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]

    # Preserve current styles and only update display property
    # This ensures background colors set by the modal content are preserved
    preview_frame_style = current_preview_style.copy() if current_preview_style else {}
    source_code_style = current_source_style.copy() if current_source_style else {}

    # Update theme-sensitive properties
    source_code_style.update({
        "background": colors["bg_tertiary"],
        "color": colors["text_primary"],
        "border": f"1px solid {colors['border']}",
    })

    active_btn_style = {
        "marginRight": "8px", "padding": "6px 12px", "border": "none",
        "borderRadius": "4px", "cursor": "pointer",
        "background": colors["accent"], "color": "#fff"
    }
    inactive_btn_style = {
        "padding": "6px 12px", "border": f"1px solid {colors['border']}",
        "borderRadius": "4px", "cursor": "pointer",
        "background": "transparent", "color": colors["text_primary"]
    }

    if triggered_id == "html-source-tab":
        # Show source, hide preview
        preview_frame_style["display"] = "none"
        source_code_style["display"] = "block"
        return preview_frame_style, source_code_style, {**inactive_btn_style, "marginRight": "8px"}, active_btn_style
    else:
        # Show preview, hide source (default)
        preview_frame_style["display"] = "block"
        source_code_style["display"] = "none"
        return preview_frame_style, source_code_style, active_btn_style, {**inactive_btn_style}


# CSV pagination
@app.callback(
    [Output("html-preview-frame", "children", allow_duplicate=True),
     Output("csv-row-info", "children"),
     Output("csv-page-info", "children"),
     Output("csv-prev-page", "disabled"),
     Output("csv-next-page", "disabled"),
     Output("csv-data-store", "data")],
    [Input("csv-prev-page", "n_clicks"),
     Input("csv-next-page", "n_clicks")],
    [State("csv-data-store", "data"),
     State("theme-store", "data")],
    prevent_initial_call=True
)
def paginate_csv(prev_clicks, next_clicks, csv_data, theme):
    """Handle CSV pagination."""
    ctx = callback_context
    if not ctx.triggered or not csv_data:
        raise PreventUpdate

    triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]

    import io as _io
    import pandas as pd

    # Get current state
    content = csv_data.get("content", "")
    sep = csv_data.get("sep", ",")
    total_rows = csv_data.get("total_rows", 0)
    total_pages = csv_data.get("total_pages", 1)
    rows_per_page = csv_data.get("rows_per_page", 50)
    current_page = csv_data.get("current_page", 0)

    # Update page based on which button was clicked
    if triggered_id == "csv-prev-page" and current_page > 0:
        current_page -= 1
    elif triggered_id == "csv-next-page" and current_page < total_pages - 1:
        current_page += 1
    else:
        raise PreventUpdate

    # Parse CSV and get the page slice
    try:
        df = pd.read_csv(_io.StringIO(content), sep=sep)
        start_idx = current_page * rows_per_page
        end_idx = min(start_idx + rows_per_page, total_rows)
        preview_df = df.iloc[start_idx:end_idx]

        # Generate row info
        if total_rows > rows_per_page:
            row_info = f"{len(df.columns)} columns, Rows {start_idx + 1}-{end_idx} of {total_rows}"
        else:
            row_info = f"{len(df.columns)} columns, {total_rows} rows"

        # Generate table HTML
        table_html = dcc.Markdown(
            preview_df.to_html(index=False, classes="csv-preview-table"),
            dangerously_allow_html=True,
            style={"overflow": "auto"}
        )

        # Update pagination state
        updated_csv_data = {
            **csv_data,
            "current_page": current_page,
        }

        return (
            table_html,
            row_info,
            f"Page {current_page + 1} of {total_pages}",
            current_page == 0,  # prev disabled
            current_page >= total_pages - 1,  # next disabled
            updated_csv_data
        )
    except Exception:
        raise PreventUpdate


# Open terminal
@app.callback(
    Output("open-terminal-btn", "n_clicks"),
    Input("open-terminal-btn", "n_clicks"),
    prevent_initial_call=True
)
def open_terminal(n_clicks):
    """Open system terminal at workspace directory."""
    if not n_clicks:
        raise PreventUpdate

    # Terminal doesn't work with virtual filesystem (no physical path)
    if USE_VIRTUAL_FS:
        print("Terminal not available in virtual filesystem mode")
        raise PreventUpdate

    workspace_path = str(WORKSPACE_ROOT)
    system = platform.system()

    try:
        if system == "Darwin":  # macOS
            subprocess.Popen(["open", "-a", "Terminal", workspace_path])
        elif system == "Windows":
            subprocess.Popen(["cmd", "/c", "start", "cmd", "/K", f"cd /d {workspace_path}"], shell=True)
        else:  # Linux
            # Try common terminal emulators
            terminals = [
                ["gnome-terminal", f"--working-directory={workspace_path}"],
                ["konsole", f"--workdir={workspace_path}"],
                ["xfce4-terminal", f"--working-directory={workspace_path}"],
                ["xterm", "-e", f"cd {workspace_path} && $SHELL"],
            ]
            for term_cmd in terminals:
                try:
                    subprocess.Popen(term_cmd)
                    break
                except FileNotFoundError:
                    continue
    except Exception as e:
        print(f"Failed to open terminal: {e}")

    raise PreventUpdate


# Refresh both file tree and canvas content
@app.callback(
    [Output("file-tree", "children"),
     Output("canvas-content", "children", allow_duplicate=True)],
    Input("refresh-btn", "n_clicks"),
    [State("current-workspace-path", "data"),
     State("theme-store", "data"),
     State("collapsed-canvas-items", "data"),
     State("session-id", "data"),
     State("expanded-folders", "data")],
    prevent_initial_call=True
)
def refresh_sidebar(n_clicks, current_workspace, theme, collapsed_ids, session_id, expanded_folders):
    """Refresh both file tree and canvas content."""
    colors = get_colors(theme or "light")
    collapsed_ids = collapsed_ids or []
    expanded_folders = expanded_folders or []

    # Get workspace for this session (virtual or physical)
    workspace_root = get_workspace_for_session(session_id)

    # Calculate current workspace directory
    if USE_VIRTUAL_FS:
        current_workspace_dir = workspace_root.path(current_workspace) if current_workspace else workspace_root.root
    else:
        current_workspace_dir = workspace_root / current_workspace if current_workspace else workspace_root

    # Refresh file tree for current workspace, preserving expanded folders
    file_tree = render_file_tree(build_file_tree(current_workspace_dir, current_workspace_dir), colors, STYLES, expanded_folders=expanded_folders, workspace_root=workspace_root)

    # Re-render canvas from current in-memory state (don't reload from file)
    # This preserves canvas items that may not have been exported to .canvas/canvas.md yet
    state = get_agent_state(session_id)
    canvas_items = state.get("canvas", [])

    # Render the canvas items with preserved collapsed state
    canvas_content = render_canvas_items(canvas_items, colors, collapsed_ids)

    return file_tree, canvas_content


# File upload (sidebar button) - uploads to current workspace directory
@app.callback(
    Output("file-tree", "children", allow_duplicate=True),
    Input("file-upload-sidebar", "contents"),
    [State("file-upload-sidebar", "filename"),
     State("current-workspace-path", "data"),
     State("theme-store", "data"),
     State("session-id", "data"),
     State("expanded-folders", "data")],
    prevent_initial_call=True
)
def handle_sidebar_upload(contents, filenames, current_workspace, theme, session_id, expanded_folders):
    """Handle file uploads from sidebar button to current workspace."""
    if not contents:
        raise PreventUpdate

    colors = get_colors(theme or "light")
    expanded_folders = expanded_folders or []

    # Get workspace for this session (virtual or physical)
    workspace_root = get_workspace_for_session(session_id)

    # Calculate current workspace directory
    if USE_VIRTUAL_FS:
        current_workspace_dir = workspace_root.path(current_workspace) if current_workspace else workspace_root.root
    else:
        current_workspace_dir = workspace_root / current_workspace if current_workspace else workspace_root

    for content, filename in zip(contents, filenames):
        try:
            _, content_string = content.split(',')
            decoded = base64.b64decode(content_string)
            file_path = current_workspace_dir / filename
            try:
                file_path.write_text(decoded.decode('utf-8'))
            except UnicodeDecodeError:
                file_path.write_bytes(decoded)
        except Exception as e:
            print(f"Upload error: {e}")

    return render_file_tree(build_file_tree(current_workspace_dir, current_workspace_dir), colors, STYLES, expanded_folders=expanded_folders, workspace_root=workspace_root)


# Create folder modal - open
@app.callback(
    Output("create-folder-modal", "opened"),
    [Input("create-folder-btn", "n_clicks"),
     Input("cancel-folder-btn", "n_clicks"),
     Input("confirm-folder-btn", "n_clicks")],
    [State("create-folder-modal", "opened"),
     State("new-folder-name", "value")],
    prevent_initial_call=True
)
def toggle_create_folder_modal(open_clicks, cancel_clicks, confirm_clicks, is_open, folder_name):
    """Open/close the create folder modal."""
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate

    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if trigger_id == "create-folder-btn":
        return True
    elif trigger_id == "cancel-folder-btn":
        return False
    elif trigger_id == "confirm-folder-btn":
        # Close modal only if folder name is provided
        if folder_name and folder_name.strip():
            return False
        return True  # Keep open if no name provided

    return is_open


# Create folder - action
@app.callback(
    [Output("file-tree", "children", allow_duplicate=True),
     Output("create-folder-error", "children"),
     Output("new-folder-name", "value")],
    Input("confirm-folder-btn", "n_clicks"),
    [State("new-folder-name", "value"),
     State("current-workspace-path", "data"),
     State("theme-store", "data"),
     State("session-id", "data"),
     State("expanded-folders", "data")],
    prevent_initial_call=True
)
def create_folder(n_clicks, folder_name, current_workspace, theme, session_id, expanded_folders):
    """Create a new folder in the current workspace directory."""
    if not n_clicks:
        raise PreventUpdate

    colors = get_colors(theme or "light")
    expanded_folders = expanded_folders or []

    if not folder_name or not folder_name.strip():
        return no_update, "Please enter a folder name", no_update

    folder_name = folder_name.strip()

    # Validate folder name
    invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    if any(char in folder_name for char in invalid_chars):
        return no_update, f"Folder name cannot contain: {' '.join(invalid_chars)}", no_update

    # Get workspace for this session (virtual or physical)
    workspace_root = get_workspace_for_session(session_id)

    # Calculate current workspace directory
    if USE_VIRTUAL_FS:
        current_workspace_dir = workspace_root.path(current_workspace) if current_workspace else workspace_root.root
    else:
        current_workspace_dir = workspace_root / current_workspace if current_workspace else workspace_root

    folder_path = current_workspace_dir / folder_name

    if folder_path.exists():
        return no_update, f"Folder '{folder_name}' already exists", no_update

    try:
        folder_path.mkdir(parents=True, exist_ok=False)
        return render_file_tree(build_file_tree(current_workspace_dir, current_workspace_dir), colors, STYLES, expanded_folders=expanded_folders, workspace_root=workspace_root), "", ""
    except Exception as e:
        return no_update, f"Error creating folder: {e}", no_update


# View toggle callbacks - using SegmentedControl
@app.callback(
    [Output("files-view", "style"),
     Output("canvas-view", "style"),
     Output("open-terminal-btn", "style"),
     Output("create-folder-btn", "style"),
     Output("file-upload-sidebar", "style")],
    [Input("sidebar-view-toggle", "value")],
    prevent_initial_call=True
)
def toggle_view(view_value):
    """Toggle between files and canvas view using SegmentedControl."""
    if not view_value:
        raise PreventUpdate

    if view_value == "canvas":
        # Show canvas, hide files, hide file-related buttons
        return (
            {"flex": "1", "display": "none", "flexDirection": "column"},
            {
                "flex": "1",
                "minHeight": "0",
                "display": "flex",
                "flexDirection": "column",
                "overflow": "hidden"
            },
            {"display": "none"},  # Hide terminal button
            {"display": "none"},  # Hide create folder button
            {"display": "none"},  # Hide file upload button
        )
    else:
        # Show files, hide canvas, show file-related buttons
        return (
            {
                "flex": "1",
                "minHeight": "0",
                "display": "flex",
                "flexDirection": "column",
                "paddingBottom": "5%"
            },
            {
                "flex": "1",
                "minHeight": "0",
                "display": "none",
                "flexDirection": "column",
                "overflow": "hidden"
            },
            {},  # Show terminal button (default styles)
            {},  # Show create folder button (default styles)
            {},  # Show file upload button (default styles)
        )


# Canvas content update
@app.callback(
    Output("canvas-content", "children"),
    [Input("poll-interval", "n_intervals"),
     Input("sidebar-view-toggle", "value")],
    [State("theme-store", "data"),
     State("collapsed-canvas-items", "data"),
     State("session-id", "data")],
    prevent_initial_call=False
)
def update_canvas_content(n_intervals, view_value, theme, collapsed_ids, session_id):
    """Update canvas content from agent state."""
    state = get_agent_state(session_id)
    canvas_items = state.get("canvas", [])
    colors = get_colors(theme or "light")
    collapsed_ids = collapsed_ids or []

    # Use imported rendering function with preserved collapsed state
    return render_canvas_items(canvas_items, colors, collapsed_ids)


# File tree polling update - refresh file tree during agent execution
@app.callback(
    Output("file-tree", "children", allow_duplicate=True),
    Input("poll-interval", "n_intervals"),
    [State("current-workspace-path", "data"),
     State("theme-store", "data"),
     State("session-id", "data"),
     State("sidebar-view-toggle", "value"),
     State("expanded-folders", "data")],
    prevent_initial_call=True
)
def poll_file_tree_update(n_intervals, current_workspace, theme, session_id, view_value, expanded_folders):
    """Refresh file tree during agent execution to show newly created files.

    This callback runs on each poll interval and refreshes the file tree
    so that files created by the agent are visible in real-time.
    Only updates when viewing files (not canvas).
    Preserves expanded folder state across refreshes.
    """
    # Only refresh when viewing files panel
    if view_value != "files":
        raise PreventUpdate

    # Get agent state to check if we should refresh
    state = get_agent_state(session_id)

    # Only refresh if agent is running or just finished (within last update window)
    # This avoids unnecessary refreshes when agent is idle
    last_update = state.get("last_update", 0)
    if not state["running"] and (time.time() - last_update) > 2:
        raise PreventUpdate

    colors = get_colors(theme or "light")
    expanded_folders = expanded_folders or []

    # Get workspace for this session (virtual or physical)
    workspace_root = get_workspace_for_session(session_id)

    # Calculate current workspace directory
    if USE_VIRTUAL_FS:
        current_workspace_dir = workspace_root.path(current_workspace) if current_workspace else workspace_root.root
    else:
        current_workspace_dir = workspace_root / current_workspace if current_workspace else workspace_root

    # Refresh file tree, preserving expanded folder state
    return render_file_tree(build_file_tree(current_workspace_dir, current_workspace_dir), colors, STYLES, expanded_folders=expanded_folders, workspace_root=workspace_root)


# Open clear canvas confirmation modal
@app.callback(
    Output("clear-canvas-modal", "opened"),
    Input("clear-canvas-btn", "n_clicks"),
    prevent_initial_call=True
)
def open_clear_canvas_modal(n_clicks):
    """Open the clear canvas confirmation modal."""
    if not n_clicks:
        raise PreventUpdate
    return True


# Handle clear canvas confirmation
@app.callback(
    [Output("canvas-content", "children", allow_duplicate=True),
     Output("clear-canvas-modal", "opened", allow_duplicate=True),
     Output("collapsed-canvas-items", "data", allow_duplicate=True)],
    [Input("confirm-clear-canvas-btn", "n_clicks"),
     Input("cancel-clear-canvas-btn", "n_clicks")],
    [State("theme-store", "data"),
     State("session-id", "data")],
    prevent_initial_call=True
)
def handle_clear_canvas_confirmation(confirm_clicks, cancel_clicks, theme, session_id):
    """Handle the clear canvas confirmation - either clear or cancel."""
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate

    triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if triggered_id == "cancel-clear-canvas-btn":
        # Close modal without clearing
        return no_update, False, no_update

    if triggered_id == "confirm-clear-canvas-btn":
        if not confirm_clicks:
            raise PreventUpdate

        global _agent_state
        colors = get_colors(theme or "light")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Get workspace for this session (virtual or physical)
        workspace_root = get_workspace_for_session(session_id)

        # Archive .canvas folder if it exists (contains canvas.md and all assets)
        # Note: Archive only works with physical filesystem
        if not USE_VIRTUAL_FS:
            canvas_dir = workspace_root / ".canvas"
            if canvas_dir.exists() and canvas_dir.is_dir():
                try:
                    archive_dir = workspace_root / f".canvas_{timestamp}"
                    shutil.move(str(canvas_dir), str(archive_dir))
                    print(f"Archived .canvas folder to {archive_dir}")
                except Exception as e:
                    print(f"Failed to archive .canvas folder: {e}")
        else:
            # For virtual FS, just clear the .canvas directory
            try:
                canvas_path = workspace_root.path("/.canvas")
                if canvas_path.exists():
                    # Clear files in the .canvas directory
                    for item in canvas_path.iterdir():
                        if item.is_file():
                            item.unlink()
            except Exception as e:
                print(f"Failed to clear virtual canvas: {e}")

        # Clear canvas in state
        with _agent_state_lock:
            _agent_state["canvas"] = []

        # Return empty state, close modal, and clear collapsed items
        return html.Div([
            html.Div("🗒", style={
                "fontSize": "48px",
                "textAlign": "center",
                "marginBottom": "16px",
                "opacity": "0.3"
            }),
            html.P("Canvas is empty", style={
                "textAlign": "center",
                "color": colors["text_muted"],
                "fontSize": "14px"
            }),
            html.P("The agent will add visualizations, charts, and notes here", style={
                "textAlign": "center",
                "color": colors["text_muted"],
                "fontSize": "12px",
                "marginTop": "8px"
            })
        ], style={
            "display": "flex",
            "flexDirection": "column",
            "alignItems": "center",
            "justifyContent": "center",
            "height": "100%",
            "padding": "40px"
        }), False, []

    raise PreventUpdate


# Collapse/expand canvas item callback
@app.callback(
    [Output({"type": "canvas-item-content", "index": ALL}, "style"),
     Output({"type": "canvas-collapse-btn", "index": ALL}, "children"),
     Output("collapsed-canvas-items", "data")],
    Input({"type": "canvas-collapse-btn", "index": ALL}, "n_clicks"),
    [State({"type": "canvas-collapse-btn", "index": ALL}, "id"),
     State({"type": "canvas-item-content", "index": ALL}, "style"),
     State({"type": "canvas-item-content", "index": ALL}, "id"),
     State("collapsed-canvas-items", "data")],
    prevent_initial_call=True
)
def toggle_canvas_item_collapse(all_clicks, btn_ids, content_styles, content_ids, collapsed_ids):
    """Toggle collapse/expand state of a canvas item."""
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate

    # Find which button was clicked
    triggered = ctx.triggered[0]
    triggered_id = triggered["prop_id"]
    triggered_value = triggered.get("value")

    if not triggered_value or triggered_value <= 0:
        raise PreventUpdate

    try:
        id_str = triggered_id.rsplit(".", 1)[0]
        id_dict = json.loads(id_str)
        clicked_item_id = id_dict.get("index")
    except:
        raise PreventUpdate

    if not clicked_item_id:
        raise PreventUpdate

    # Initialize collapsed_ids if None
    collapsed_ids = collapsed_ids or []

    # Build new styles and icons for all items
    new_styles = []
    new_icons = []
    new_collapsed_ids = collapsed_ids.copy()

    for i, content_id in enumerate(content_ids):
        item_id = content_id.get("index")
        current_style = content_styles[i] if i < len(content_styles) else {"display": "block"}

        if item_id == clicked_item_id:
            # Toggle this item
            is_collapsed = current_style.get("display") == "none"
            new_styles.append({"display": "block"} if is_collapsed else {"display": "none"})
            # Change icon based on new state
            new_icons.append(
                DashIconify(icon="mdi:chevron-down" if is_collapsed else "mdi:chevron-right", width=16)
            )
            # Update collapsed_ids list
            if is_collapsed:
                # Was collapsed, now expanding - remove from list
                if item_id in new_collapsed_ids:
                    new_collapsed_ids.remove(item_id)
            else:
                # Was expanded, now collapsing - add to list
                if item_id not in new_collapsed_ids:
                    new_collapsed_ids.append(item_id)
        else:
            new_styles.append(current_style)
            # Keep existing icon state
            is_collapsed = current_style.get("display") == "none"
            new_icons.append(
                DashIconify(icon="mdi:chevron-right" if is_collapsed else "mdi:chevron-down", width=16)
            )

    return new_styles, new_icons, new_collapsed_ids


# Open delete confirmation modal
@app.callback(
    [Output("delete-canvas-item-modal", "opened"),
     Output("delete-canvas-item-id", "data")],
    Input({"type": "canvas-delete-btn", "index": ALL}, "n_clicks"),
    [State({"type": "canvas-delete-btn", "index": ALL}, "id")],
    prevent_initial_call=True
)
def open_delete_confirmation(all_clicks, all_ids):
    """Open the delete confirmation modal when delete button is clicked."""
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate

    triggered = ctx.triggered[0]
    triggered_id = triggered["prop_id"]
    triggered_value = triggered.get("value")

    if not triggered_value or triggered_value <= 0:
        raise PreventUpdate

    try:
        id_str = triggered_id.rsplit(".", 1)[0]
        id_dict = json.loads(id_str)
        item_id_to_delete = id_dict.get("index")
    except:
        raise PreventUpdate

    if not item_id_to_delete:
        raise PreventUpdate

    return True, item_id_to_delete


# Handle delete confirmation modal actions
@app.callback(
    [Output("canvas-content", "children", allow_duplicate=True),
     Output("delete-canvas-item-modal", "opened", allow_duplicate=True),
     Output("collapsed-canvas-items", "data", allow_duplicate=True)],
    [Input("confirm-delete-canvas-btn", "n_clicks"),
     Input("cancel-delete-canvas-btn", "n_clicks")],
    [State("delete-canvas-item-id", "data"),
     State("theme-store", "data"),
     State("collapsed-canvas-items", "data"),
     State("session-id", "data")],
    prevent_initial_call=True
)
def handle_delete_confirmation(confirm_clicks, cancel_clicks, item_id, theme, collapsed_ids, session_id):
    """Handle the delete confirmation - either delete or cancel."""
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate

    triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if triggered_id == "cancel-delete-canvas-btn":
        # Close modal without deleting
        return no_update, False, no_update

    if triggered_id == "confirm-delete-canvas-btn":
        if not confirm_clicks or not item_id:
            raise PreventUpdate

        colors = get_colors(theme or "light")
        collapsed_ids = collapsed_ids or []

        # Get workspace for this session (virtual or physical)
        workspace_root = get_workspace_for_session(session_id)

        # Remove the item from canvas (session-specific in virtual FS mode)
        if USE_VIRTUAL_FS and session_id:
            current_state = _get_session_state(session_id)
            with _session_agents_lock:
                current_state["canvas"] = [
                    item for item in current_state.get("canvas", [])
                    if item.get("id") != item_id
                ]
                canvas_items = current_state["canvas"].copy()
        else:
            with _agent_state_lock:
                _agent_state["canvas"] = [
                    item for item in _agent_state["canvas"]
                    if item.get("id") != item_id
                ]
                canvas_items = _agent_state["canvas"].copy()

        # Export updated canvas to markdown file
        try:
            export_canvas_to_markdown(canvas_items, workspace_root)
        except Exception as e:
            print(f"Failed to export canvas after delete: {e}")

        # Remove deleted item from collapsed_ids if present
        new_collapsed_ids = [cid for cid in collapsed_ids if cid != item_id]

        # Render updated canvas with preserved collapsed state and close modal
        return render_canvas_items(canvas_items, colors, new_collapsed_ids), False, new_collapsed_ids

    raise PreventUpdate


# =============================================================================
# ADD DISPLAY_INLINE TO CANVAS CALLBACK
# =============================================================================

@app.callback(
    [Output("canvas-content", "children", allow_duplicate=True),
     Output("sidebar-view-toggle", "value", allow_duplicate=True)],
    Input({"type": "add-display-to-canvas-btn", "index": ALL}, "n_clicks"),
    [State({"type": "display-inline-data", "index": ALL}, "data"),
     State("theme-store", "data"),
     State("collapsed-canvas-items", "data"),
     State("session-id", "data")],
    prevent_initial_call=True
)
def add_display_inline_to_canvas(n_clicks_list, data_list, theme, collapsed_ids, session_id):
    """Add a display_inline item to the canvas when the button is clicked.

    This allows users to save inline display items to the canvas for persistent reference.
    """
    from .canvas import generate_canvas_id, export_canvas_to_markdown
    from datetime import datetime

    # Check if any button was actually clicked
    if not n_clicks_list or not any(n_clicks_list):
        raise PreventUpdate

    # Find which button was clicked
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate

    triggered = ctx.triggered[0]
    triggered_id = triggered["prop_id"]

    # Parse the pattern-matching ID to get the index
    try:
        # Format: {"type":"add-display-to-canvas-btn","index":"abc123"}.n_clicks
        id_part = triggered_id.rsplit(".", 1)[0]
        id_dict = json.loads(id_part)
        clicked_index = id_dict.get("index")
    except (json.JSONDecodeError, KeyError, AttributeError):
        raise PreventUpdate

    if not clicked_index:
        raise PreventUpdate

    # Find the corresponding data
    display_data = None
    for data in data_list:
        if data and data.get("_item_id") == clicked_index:
            display_data = data
            break

    if not display_data:
        raise PreventUpdate

    colors = get_colors(theme or "light")
    collapsed_ids = collapsed_ids or []

    # Get workspace for this session (virtual or physical)
    workspace_root = get_workspace_for_session(session_id)

    # Convert display_inline result to canvas item format
    display_type = display_data.get("display_type", "text")
    title = display_data.get("title")
    data = display_data.get("data")

    # Generate new canvas ID and timestamp
    canvas_id = generate_canvas_id()
    created_at = datetime.now().isoformat()

    # Map display_inline types to canvas types
    canvas_item = {
        "id": canvas_id,
        "created_at": created_at,
    }

    if title:
        canvas_item["title"] = title

    if display_type == "image":
        canvas_item["type"] = "image"
        canvas_item["data"] = data  # base64 image data
    elif display_type == "plotly":
        canvas_item["type"] = "plotly"
        canvas_item["data"] = data  # Plotly JSON
    elif display_type == "dataframe":
        canvas_item["type"] = "dataframe"
        canvas_item["data"] = display_data.get("csv", {}).get("data", [])
        canvas_item["columns"] = display_data.get("csv", {}).get("columns", [])
        canvas_item["html"] = display_data.get("csv", {}).get("html", "")
    elif display_type == "pdf":
        canvas_item["type"] = "pdf"
        canvas_item["data"] = data  # base64 PDF data
        canvas_item["mime_type"] = display_data.get("mime_type", "application/pdf")
    elif display_type == "html":
        canvas_item["type"] = "markdown"
        canvas_item["data"] = data  # Store HTML as markdown (will render)
    elif display_type == "json":
        canvas_item["type"] = "markdown"
        canvas_item["data"] = f"```json\n{json.dumps(data, indent=2)}\n```"
    else:
        # text or other
        canvas_item["type"] = "markdown"
        canvas_item["data"] = str(data) if data else ""

    # Add item to canvas (session-specific in virtual FS mode)
    if USE_VIRTUAL_FS and session_id:
        current_state = _get_session_state(session_id)
        with _session_agents_lock:
            current_state["canvas"].append(canvas_item)
            canvas_items = current_state["canvas"].copy()
    else:
        with _agent_state_lock:
            _agent_state["canvas"].append(canvas_item)
            canvas_items = _agent_state["canvas"].copy()

    # Export updated canvas to markdown file
    try:
        export_canvas_to_markdown(canvas_items, workspace_root)
    except Exception as e:
        print(f"Failed to export canvas after adding display item: {e}")

    # Render updated canvas and switch to canvas view
    return render_canvas_items(canvas_items, colors, collapsed_ids), "canvas"


# =============================================================================
# FULLSCREEN PREVIEW CALLBACK - Open HTML/PDF in fullscreen modal
# =============================================================================

@app.callback(
    [Output("fullscreen-preview-modal", "opened"),
     Output("fullscreen-preview-modal", "title"),
     Output("fullscreen-preview-content", "children")],
    Input({"type": "fullscreen-btn", "index": ALL}, "n_clicks"),
    State({"type": "fullscreen-data", "index": ALL}, "data"),
    prevent_initial_call=True
)
def open_fullscreen_preview(n_clicks_list, data_list):
    """Open fullscreen modal for HTML/PDF preview."""
    if not n_clicks_list or not any(n_clicks_list):
        raise PreventUpdate

    # Find which button was clicked
    triggered = ctx.triggered[0]
    triggered_id = triggered["prop_id"]

    try:
        id_part = triggered_id.rsplit(".", 1)[0]
        id_dict = json.loads(id_part)
        clicked_index = id_dict.get("index")
    except (json.JSONDecodeError, KeyError, AttributeError):
        raise PreventUpdate

    # Find the corresponding data
    fullscreen_data = None
    for i, data in enumerate(data_list):
        if data and n_clicks_list[i]:
            # Match by checking trigger
            btn_ids = ctx.inputs_list[0]
            if i < len(btn_ids) and btn_ids[i].get("id", {}).get("index") == clicked_index:
                fullscreen_data = data
                break

    if not fullscreen_data:
        raise PreventUpdate

    content_type = fullscreen_data.get("type")
    content = fullscreen_data.get("content")
    title = fullscreen_data.get("title", "Preview")

    if content_type == "html":
        preview_content = html.Iframe(
            srcDoc=content,
            style={
                "width": "100%",
                "height": "100%",
                "border": "none",
                "backgroundColor": "white",
            }
        )
    elif content_type == "pdf":
        preview_content = html.Iframe(
            src=content,
            style={
                "width": "100%",
                "height": "100%",
                "border": "none",
            }
        )
    else:
        preview_content = html.Div("Unsupported content type")

    return True, title, preview_content


# =============================================================================
# THEME TOGGLE CALLBACK - Using DMC 2.4 forceColorScheme
# =============================================================================

@app.callback(
    [Output("theme-store", "data"),
     Output("mantine-provider", "forceColorScheme"),
     Output("theme-toggle-btn", "children")],
    [Input("theme-toggle-btn", "n_clicks")],
    [State("theme-store", "data")],
    prevent_initial_call=True
)
def toggle_theme(n_clicks, current_theme):
    """Toggle between light and dark theme using DMC's forceColorScheme."""
    if not n_clicks:
        raise PreventUpdate

    # Toggle theme
    new_theme = "dark" if current_theme == "light" else "light"

    # Update the icon
    toggle_icon = DashIconify(
        icon="radix-icons:sun" if new_theme == "dark" else "radix-icons:moon",
        width=18
    )

    return new_theme, new_theme, toggle_icon


# Callback to initialize theme on page load
@app.callback(
    [Output("mantine-provider", "forceColorScheme", allow_duplicate=True),
     Output("theme-toggle-btn", "children", allow_duplicate=True)],
    [Input("theme-store", "data")],
    prevent_initial_call='initial_duplicate'
)
def initialize_theme(theme):
    """Initialize theme on page load from stored preference."""
    if not theme:
        theme = "light"

    toggle_icon = DashIconify(
        icon="radix-icons:sun" if theme == "dark" else "radix-icons:moon",
        width=18
    )

    return theme, toggle_icon


# =============================================================================
# PROGRAMMATIC API
# =============================================================================

def run_app(
    agent_instance=None,
    workspace=None,
    agent_spec=None,
    port=None,
    host=None,
    debug=None,
    title=None,
    subtitle=None,
    welcome_message=None,
    config_file=None,
    virtual_fs=None
):
    """
    Run DeepAgent Dash programmatically.

    This function can be called from Python code or used as the entry point
    for the CLI. It handles configuration loading and overrides.

    Args:
        agent_instance (object, optional): Agent object instance (Python API only)
        workspace (str, optional): Workspace directory path
        agent_spec (str, optional): Agent specification (overrides agent_instance).
            Supports two formats (both use colon separator):
            - File path: "path/to/file.py:object_name"
            - Module path: "mypackage.module:object_name"
        port (int, optional): Port number
        host (str, optional): Host to bind to
        debug (bool, optional): Debug mode
        title (str, optional): Application title
        subtitle (str, optional): Application subtitle
        welcome_message (str, optional): Welcome message shown on startup (supports markdown)
        config_file (str, optional): Path to config file (default: ./config.py)
        virtual_fs (bool, optional): Use in-memory virtual filesystem instead of disk.
            When enabled, each session gets isolated ephemeral storage.
            Can also be set via DEEPAGENT_SESSION_ISOLATION=true environment variable.

    Returns:
        int: Exit code (0 for success, non-zero for error)

    Examples:
        >>> # Using agent instance directly
        >>> from cowork_dash import run_app
        >>> my_agent = MyAgent()
        >>> run_app(my_agent, workspace="~/my-workspace")

        >>> # Using agent spec (file path format)
        >>> run_app(agent_spec="my_agent.py:agent", port=8080)

        >>> # Using agent spec (module format)
        >>> run_app(agent_spec="mypackage.agents:my_agent", port=8080)

        >>> # Without agent (manual mode)
        >>> run_app(workspace="~/my-workspace", debug=True)
    """
    global WORKSPACE_ROOT, APP_TITLE, APP_SUBTITLE, PORT, HOST, DEBUG, WELCOME_MESSAGE, agent, AGENT_ERROR, args, USE_VIRTUAL_FS

    # Determine virtual filesystem mode (CLI arg > env var > config default)
    USE_VIRTUAL_FS = virtual_fs if virtual_fs is not None else config.VIRTUAL_FS

    # Load config file if specified and exists
    config_module = None
    if config_file:
        config_path = Path(config_file).resolve()
        if config_path.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location("user_config", config_path)
            if spec and spec.loader:
                config_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(config_module)
                print(f"✓ Loaded config from {config_path}")
        else:
            print(f"⚠️  Config file not found: {config_path}, using defaults")

    # Apply configuration with overrides
    if config_module:
        # Use config file values as base
        WORKSPACE_ROOT = Path(workspace).resolve() if workspace else getattr(config_module, "WORKSPACE_ROOT", config.WORKSPACE_ROOT)
        APP_TITLE = title if title else getattr(config_module, "APP_TITLE", config.APP_TITLE)
        APP_SUBTITLE = subtitle if subtitle else getattr(config_module, "APP_SUBTITLE", config.APP_SUBTITLE)
        PORT = port if port is not None else getattr(config_module, "PORT", config.PORT)
        HOST = host if host else getattr(config_module, "HOST", config.HOST)
        DEBUG = debug if debug is not None else getattr(config_module, "DEBUG", config.DEBUG)
        WELCOME_MESSAGE = welcome_message if welcome_message else getattr(config_module, "WELCOME_MESSAGE", config.WELCOME_MESSAGE)

        # Agent priority: agent_spec > agent_instance > config file
        if agent_spec:
            # Load agent from spec (highest priority)
            agent, AGENT_ERROR = load_agent_from_spec(agent_spec)
        elif agent_instance is not None:
            # Use provided agent instance
            agent = agent_instance
            AGENT_ERROR = None
        else:
            # Get agent from config file
            get_agent_func = getattr(config_module, "get_agent", None)
            if get_agent_func:
                result = get_agent_func()
                if isinstance(result, tuple):
                    agent, AGENT_ERROR = result
                else:
                    agent = result
                    AGENT_ERROR = None
            else:
                agent = None
                AGENT_ERROR = "No get_agent() function in config file"
    else:
        # No config file, use CLI args or defaults
        WORKSPACE_ROOT = Path(workspace).resolve() if workspace else config.WORKSPACE_ROOT
        APP_TITLE = title if title else config.APP_TITLE
        APP_SUBTITLE = subtitle if subtitle else config.APP_SUBTITLE
        PORT = port if port is not None else config.PORT
        HOST = host if host else config.HOST
        DEBUG = debug if debug is not None else config.DEBUG
        WELCOME_MESSAGE = welcome_message if welcome_message else config.WELCOME_MESSAGE

        # Agent priority: agent_spec > agent_instance > config default
        if agent_spec:
            # Load agent from spec (highest priority)
            agent, AGENT_ERROR = load_agent_from_spec(agent_spec)
        elif agent_instance is not None:
            # Use provided agent instance
            agent = agent_instance
            AGENT_ERROR = None
        else:
            # Use default config agent
            agent, AGENT_ERROR = load_agent_from_spec(config.AGENT_SPEC)

    # Update global agent state
    global _agent_state

    # Ensure workspace exists (only for physical filesystem mode)
    if not USE_VIRTUAL_FS:
        WORKSPACE_ROOT.mkdir(exist_ok=True, parents=True)

        # Set environment variable for agent to access workspace
        # This allows user agents to read DEEPAGENT_WORKSPACE_ROOT
        os.environ['DEEPAGENT_WORKSPACE_ROOT'] = str(WORKSPACE_ROOT)

        # Update global state to use the configured workspace
        _agent_state["canvas"] = load_canvas_from_markdown(WORKSPACE_ROOT)
    else:
        # For virtual FS, canvas is loaded per-session in callbacks
        _agent_state["canvas"] = []

    # Create a mock args object for compatibility with existing code
    class Args:
        pass
    args = Args()
    args.workspace = workspace
    args.agent = agent_spec

    # Print startup banner
    print("\n" + "="*50)
    print(f"  {APP_TITLE}")
    print("="*50)
    if USE_VIRTUAL_FS:
        print("  Filesystem: Virtual (in-memory, ephemeral)")
        print("    Sessions are isolated and data is not persisted")
    else:
        print(f"  Workspace: {WORKSPACE_ROOT}")
        if workspace:
            print(f"    (from CLI: --workspace {workspace})")
    print(f"  Agent: {'Ready' if agent else 'Not available'}")
    if agent_spec:
        print(f"    (from CLI: --agent {agent_spec})")
    if AGENT_ERROR:
        print(f"    Error: {AGENT_ERROR}")
    print(f"  URL: http://{HOST}:{PORT}")
    print(f"  Debug: {DEBUG}")
    print("="*50 + "\n")

    # Run the app
    try:
        app.run(debug=DEBUG, host=HOST, port=PORT)
        return 0
    except Exception as e:
        print(f"\n❌ Error running app: {e}")
        return 1