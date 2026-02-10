from typing import Any, Dict, List, Optional
import sys
import io
import os
import traceback
import subprocess
import threading
import platform
from contextlib import redirect_stdout, redirect_stderr, contextmanager

from langchain_core.tools import tool as langchain_tool

from .config import WORKSPACE_ROOT, VIRTUAL_FS
from .canvas import parse_canvas_object, load_canvas_from_markdown, export_canvas_to_markdown


# =============================================================================


# Memory limit for cell execution (in bytes)
# Default: 512 MB - can be overridden via environment variable
CELL_MEMORY_LIMIT_MB = int(os.environ.get("COWORK_CELL_MEMORY_LIMIT_MB", "512"))
CELL_MEMORY_LIMIT_BYTES = CELL_MEMORY_LIMIT_MB * 1024 * 1024


@contextmanager
def memory_limit(max_bytes: int = CELL_MEMORY_LIMIT_BYTES):
    """Context manager to set memory limits for code execution on Linux.

    On Linux, uses resource.setrlimit() to set soft memory limit.
    On other platforms (macOS, Windows), this is a no-op as they don't
    support RLIMIT_AS in the same way or at all.

    The limit applies to the virtual address space (RLIMIT_AS) which
    will cause MemoryError when exceeded rather than OOM kill.

    Args:
        max_bytes: Maximum memory in bytes. Default from CELL_MEMORY_LIMIT_BYTES.
    """
    if platform.system() != "Linux":
        # Memory limits via resource module only work reliably on Linux
        yield
        return

    try:
        import resource
    except ImportError:
        yield
        return

    # Get current limits
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)

    try:
        # Set new soft limit (don't exceed hard limit)
        new_soft = min(max_bytes, hard) if hard != resource.RLIM_INFINITY else max_bytes
        resource.setrlimit(resource.RLIMIT_AS, (new_soft, hard))
        yield
    finally:
        # Restore original limits
        resource.setrlimit(resource.RLIMIT_AS, (soft, hard))


# Thread-local storage for current session context
# This allows tools to know which session they're operating in
_tool_context = threading.local()


def set_tool_session_context(session_id: Optional[str]) -> None:
    """Set the current session context for tool operations.

    This should be called before invoking agent tools in virtual FS mode.
    """
    _tool_context.session_id = session_id


def get_tool_session_context() -> Optional[str]:
    """Get the current session context for tool operations."""
    return getattr(_tool_context, 'session_id', None)


def clear_tool_session_context() -> None:
    """Clear the current session context."""
    _tool_context.session_id = None


def _get_workspace_root_for_context() -> Any:
    """Get the appropriate workspace root based on current context.

    Returns VirtualFilesystem in virtual FS mode with session context,
    otherwise returns the physical WORKSPACE_ROOT path.
    """
    # Import config dynamically to get current value (in case it changed)
    from . import config as cfg
    if cfg.VIRTUAL_FS:
        session_id = get_tool_session_context()
        if session_id:
            from .virtual_fs import get_session_manager
            fs = get_session_manager().get_filesystem(session_id)
            if fs is not None:
                return fs
    return cfg.WORKSPACE_ROOT


# =============================================================================
# JUPYTER-LIKE CODE EXECUTION TOOLS
# =============================================================================

class NotebookState:
    """
    Maintains persistent state for Jupyter-like code execution.

    This class manages:
    - An ordered list of code cells (the "script")
    - A persistent namespace for variable state across cells
    - Execution history and outputs
    - Canvas items generated during cell execution

    In virtual filesystem mode, file operations are restricted and virtual
    filesystem helpers are provided instead.
    """

    def __init__(self, session_id: Optional[str] = None):
        self._cells: List[Dict[str, Any]] = []
        self._namespace: Dict[str, Any] = {}
        self._execution_count: int = 0
        self._ipython_shell = None
        self._canvas_items: List[Dict[str, Any]] = []  # Collected canvas items
        self._session_id = session_id
        self._initialize_namespace()

    def _initialize_namespace(self):
        """Initialize the namespace with common imports and utilities."""
        # Pre-populate with commonly used modules
        # In virtual FS mode, we provide virtual filesystem helpers
        if VIRTUAL_FS:
            init_code = """
import sys
import json

# Data science essentials (imported if available)
try:
    import pandas as pd
except (ImportError, AttributeError):
    pd = None

try:
    import numpy as np
except (ImportError, AttributeError):
    np = None

try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
except (ImportError, AttributeError):
    plt = None

try:
    import plotly.express as px
    import plotly.graph_objects as go
except (ImportError, AttributeError):
    px = None
    go = None

# Note: In virtual filesystem mode, standard file operations (open, os.listdir, etc.)
# are not available. Use the provided vfs_* functions instead.
"""
        else:
            init_code = """
import sys
import os
import json
from pathlib import Path

# Data science essentials (imported if available)
try:
    import pandas as pd
except (ImportError, AttributeError):
    pd = None

try:
    import numpy as np
except (ImportError, AttributeError):
    np = None

try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
except (ImportError, AttributeError):
    plt = None

try:
    import plotly.express as px
    import plotly.graph_objects as go
except (ImportError, AttributeError):
    px = None
    go = None
"""
        # Execute initialization silently
        try:
            exec(init_code, self._namespace)
        except Exception:
            pass  # Ignore import errors for optional packages

        # In virtual FS mode, inject virtual filesystem helpers
        if VIRTUAL_FS:
            self._inject_virtual_fs_helpers()

    def _inject_virtual_fs_helpers(self):
        """Inject virtual filesystem helper functions into the namespace."""
        from .virtual_fs import get_session_manager

        session_id = self._session_id

        def vfs_read_file(path: str) -> str:
            """Read a text file from the virtual filesystem."""
            if not session_id:
                raise RuntimeError("No session ID available for virtual filesystem")
            fs = get_session_manager().get_filesystem(session_id)
            if not fs:
                raise RuntimeError(f"Session {session_id} not found")
            return fs.read_text(path)

        def vfs_write_file(path: str, content: str) -> int:
            """Write content to a file in the virtual filesystem."""
            if not session_id:
                raise RuntimeError("No session ID available for virtual filesystem")
            fs = get_session_manager().get_filesystem(session_id)
            if not fs:
                raise RuntimeError(f"Session {session_id} not found")
            return fs.write_text(path, content)

        def vfs_list_dir(path: str = "/workspace") -> list:
            """List files in a directory in the virtual filesystem."""
            if not session_id:
                raise RuntimeError("No session ID available for virtual filesystem")
            fs = get_session_manager().get_filesystem(session_id)
            if not fs:
                raise RuntimeError(f"Session {session_id} not found")
            return fs.listdir(path)

        def vfs_exists(path: str) -> bool:
            """Check if a file or directory exists in the virtual filesystem."""
            if not session_id:
                raise RuntimeError("No session ID available for virtual filesystem")
            fs = get_session_manager().get_filesystem(session_id)
            if not fs:
                raise RuntimeError(f"Session {session_id} not found")
            return fs.exists(path)

        def vfs_mkdir(path: str, parents: bool = True) -> None:
            """Create a directory in the virtual filesystem."""
            if not session_id:
                raise RuntimeError("No session ID available for virtual filesystem")
            fs = get_session_manager().get_filesystem(session_id)
            if not fs:
                raise RuntimeError(f"Session {session_id} not found")
            fs.mkdir(path, parents=parents, exist_ok=True)

        # Inject the helpers
        self._namespace["vfs_read_file"] = vfs_read_file
        self._namespace["vfs_write_file"] = vfs_write_file
        self._namespace["vfs_list_dir"] = vfs_list_dir
        self._namespace["vfs_exists"] = vfs_exists
        self._namespace["vfs_mkdir"] = vfs_mkdir

        # Add a notice about virtual FS mode
        self._namespace["__VFS_MODE__"] = True

    def _get_ipython(self):
        """Get or create an IPython InteractiveShell for enhanced execution."""
        if self._ipython_shell is None:
            try:
                from IPython.core.interactiveshell import InteractiveShell
                self._ipython_shell = InteractiveShell.instance()
                # Share the namespace
                self._ipython_shell.user_ns = self._namespace
            except ImportError:
                # IPython not available, will use exec() fallback
                pass
        return self._ipython_shell

    @property
    def cells(self) -> List[Dict[str, Any]]:
        """Return a copy of all cells."""
        return [cell.copy() for cell in self._cells]

    @property
    def namespace(self) -> Dict[str, Any]:
        """Return the current namespace (variable state)."""
        return self._namespace

    def get_cell(self, cell_index: int) -> Optional[Dict[str, Any]]:
        """Get a cell by index."""
        if 0 <= cell_index < len(self._cells):
            return self._cells[cell_index].copy()
        return None

    def add_cell(self, code: str, cell_type: str = "code") -> Dict[str, Any]:
        """Add a new cell to the end of the script."""
        cell = {
            "index": len(self._cells),
            "type": cell_type,
            "source": code,
            "execution_count": None,
            "outputs": [],
            "status": "pending"
        }
        self._cells.append(cell)
        return cell.copy()

    def insert_cell(self, index: int, code: str, cell_type: str = "code") -> Dict[str, Any]:
        """Insert a cell at a specific index."""
        if index < 0:
            index = 0
        if index > len(self._cells):
            index = len(self._cells)

        cell = {
            "index": index,
            "type": cell_type,
            "source": code,
            "execution_count": None,
            "outputs": [],
            "status": "pending"
        }
        self._cells.insert(index, cell)

        # Update indices for subsequent cells
        for i in range(index + 1, len(self._cells)):
            self._cells[i]["index"] = i

        return cell.copy()

    def modify_cell(self, cell_index: int, new_code: str) -> Dict[str, Any]:
        """Modify the code in an existing cell."""
        if not (0 <= cell_index < len(self._cells)):
            return {
                "error": f"Cell index {cell_index} out of range. Valid range: 0-{len(self._cells) - 1}"
            }

        self._cells[cell_index]["source"] = new_code
        self._cells[cell_index]["status"] = "modified"
        self._cells[cell_index]["outputs"] = []  # Clear previous outputs

        return self._cells[cell_index].copy()

    def delete_cell(self, cell_index: int) -> Dict[str, Any]:
        """Delete a cell by index."""
        if not (0 <= cell_index < len(self._cells)):
            return {
                "error": f"Cell index {cell_index} out of range. Valid range: 0-{len(self._cells) - 1}"
            }

        deleted_cell = self._cells.pop(cell_index)

        # Update indices for subsequent cells
        for i in range(cell_index, len(self._cells)):
            self._cells[i]["index"] = i

        return {"deleted": deleted_cell, "remaining_cells": len(self._cells)}

    def execute_cell(self, cell_index: int) -> Dict[str, Any]:
        """Execute a single cell and capture its output."""
        if not (0 <= cell_index < len(self._cells)):
            return {
                "error": f"Cell index {cell_index} out of range. Valid range: 0-{len(self._cells) - 1}"
            }

        cell = self._cells[cell_index]

        if cell["type"] != "code":
            return {
                "index": cell_index,
                "type": cell["type"],
                "source": cell["source"],
                "output": "(markdown cell - not executed)",
                "status": "skipped"
            }

        self._execution_count += 1
        cell["execution_count"] = self._execution_count

        # Track canvas items added during this cell's execution
        canvas_count_before = len(self._canvas_items)

        # Capture stdout and stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        result = {
            "index": cell_index,
            "execution_count": self._execution_count,
            "source": cell["source"],
            "stdout": "",
            "stderr": "",
            "result": None,
            "error": None,
            "status": "success",
            "canvas_items": []  # Canvas items added during execution
        }

        try:
            # Apply memory limit on Linux to prevent OOM kills
            with memory_limit():
                # Try IPython first for better execution handling
                ipython = self._get_ipython()

                if ipython is not None:
                    # Use IPython's run_cell for magic commands support
                    with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                        exec_result = ipython.run_cell(cell["source"], store_history=True)

                    result["stdout"] = stdout_capture.getvalue()
                    result["stderr"] = stderr_capture.getvalue()

                    if exec_result.success:
                        if exec_result.result is not None:
                            result["result"] = repr(exec_result.result)
                    else:
                        if exec_result.error_in_exec:
                            result["error"] = str(exec_result.error_in_exec)
                            result["status"] = "error"
                        elif exec_result.error_before_exec:
                            result["error"] = str(exec_result.error_before_exec)
                            result["status"] = "error"
                else:
                    # Fallback to exec() if IPython is not available
                    with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                        # Compile to check for expression vs statement
                        code = cell["source"].strip()

                        # Try to evaluate as expression first (to get return value)
                        try:
                            # Check if it's a simple expression
                            compiled = compile(code, "<cell>", "eval")
                            exec_result = eval(compiled, self._namespace)
                            if exec_result is not None:
                                result["result"] = repr(exec_result)
                        except SyntaxError:
                            # It's a statement, execute it
                            exec(code, self._namespace)

                    result["stdout"] = stdout_capture.getvalue()
                    result["stderr"] = stderr_capture.getvalue()

        except MemoryError:
            result["error"] = f"MemoryError: Cell execution exceeded memory limit ({CELL_MEMORY_LIMIT_MB} MB). Try processing data in smaller chunks."
            result["status"] = "error"
            result["stdout"] = stdout_capture.getvalue()
            result["stderr"] = stderr_capture.getvalue()
        except Exception:
            result["error"] = traceback.format_exc()
            result["status"] = "error"
            result["stdout"] = stdout_capture.getvalue()
            result["stderr"] = stderr_capture.getvalue()

        # Capture any canvas items added during this cell's execution
        canvas_items_added = self._canvas_items[canvas_count_before:]
        result["canvas_items"] = canvas_items_added

        # Store outputs in cell
        cell["outputs"] = [result]
        cell["status"] = result["status"]

        return result

    def execute_all(self) -> List[Dict[str, Any]]:
        """Execute all cells in order."""
        results = []
        for i in range(len(self._cells)):
            results.append(self.execute_cell(i))
        return results

    def get_script(self) -> str:
        """Get all code cells concatenated as a single script."""
        code_cells = [cell["source"] for cell in self._cells if cell["type"] == "code"]
        return "\n\n".join(code_cells)

    def get_variables(self) -> Dict[str, str]:
        """Get a summary of user-defined variables in the namespace."""
        # Filter out modules, builtins, and private variables
        user_vars = {}
        for name, value in self._namespace.items():
            if name.startswith("_"):
                continue
            if isinstance(value, type(sys)):  # Skip modules
                continue
            if callable(value) and hasattr(value, "__module__"):
                # Skip imported functions
                if value.__module__ != "__main__" and value.__module__ not in [None, "builtins"]:
                    continue
            try:
                # Get a short repr
                value_repr = repr(value)
                if len(value_repr) > 100:
                    value_repr = value_repr[:97] + "..."
                user_vars[name] = f"{type(value).__name__}: {value_repr}"
            except Exception:
                user_vars[name] = f"{type(value).__name__}: <unable to repr>"
        return user_vars

    def get_canvas_items(self) -> List[Dict[str, Any]]:
        """Get all canvas items collected during execution."""
        return self._canvas_items.copy()

    def clear_canvas_items(self) -> Dict[str, Any]:
        """Clear collected canvas items."""
        count = len(self._canvas_items)
        self._canvas_items = []
        return {"cleared": count}

    def reset(self):
        """Reset the notebook state (clear all cells and namespace)."""
        self._cells = []
        self._namespace = {}
        self._execution_count = 0
        self._canvas_items = []
        self._initialize_namespace()
        return {"status": "reset", "message": "Notebook state cleared"}


# Global notebook state instance (for physical FS mode)
# In virtual FS mode, each session should have its own NotebookState
_notebook_state = NotebookState()
_session_notebook_states: Dict[str, NotebookState] = {}


def get_notebook_state(session_id: Optional[str] = None) -> NotebookState:
    """Get the notebook state for a session.

    In virtual FS mode, returns a session-specific NotebookState.
    In physical FS mode, returns the global shared NotebookState.
    """
    if not VIRTUAL_FS or not session_id:
        return _notebook_state

    if session_id not in _session_notebook_states:
        _session_notebook_states[session_id] = NotebookState(session_id=session_id)

    return _session_notebook_states[session_id]


def create_cell(code: str, cell_type: str = "code") -> Dict[str, Any]:
    """
    Create a new code or markdown cell and add it to the end of the script.

    This simulates creating a new cell in a Jupyter notebook. The cell is added
    but not executed - use execute_cell() to run it.

    Args:
        code: The Python code or markdown content for the cell
        cell_type: Either "code" or "markdown" (default: "code")

    Returns:
        Dictionary with cell information including:
        - index: The cell's position in the notebook
        - type: The cell type
        - source: The cell's code/content
        - status: "pending" (not yet executed)

    Examples:
        # Create a code cell
        create_cell("x = 42\\nprint(f'x = {x}')")

        # Create a markdown cell
        create_cell("## Analysis Results", cell_type="markdown")
    """
    return _notebook_state.add_cell(code, cell_type)


def insert_cell(index: int, code: str, cell_type: str = "code") -> Dict[str, Any]:
    """
    Insert a new cell at a specific position in the script.

    This is useful when you need to add code between existing cells,
    such as adding a missing import or intermediate calculation.

    Args:
        index: Position to insert the cell (0-based). Cells after this
               position will be shifted down.
        code: The Python code or markdown content
        cell_type: Either "code" or "markdown" (default: "code")

    Returns:
        Dictionary with cell information including index and status

    Examples:
        # Insert an import at the beginning
        insert_cell(0, "import pandas as pd")

        # Insert a cell between cells 2 and 3
        insert_cell(3, "intermediate_result = process(data)")
    """
    return _notebook_state.insert_cell(index, code, cell_type)


def modify_cell(cell_index: int, new_code: str) -> Dict[str, Any]:
    """
    Modify the code in an existing cell.

    Use this to fix errors, update logic, or refine code in a cell.
    The cell's outputs are cleared and status set to "modified".
    You'll need to re-execute the cell to see the new results.

    Args:
        cell_index: The index of the cell to modify (0-based)
        new_code: The new code to replace the existing code

    Returns:
        Dictionary with updated cell information, or error if index invalid

    Examples:
        # Fix a typo in cell 2
        modify_cell(2, "result = data.groupby('category').mean()")

        # Update a calculation
        modify_cell(0, "threshold = 0.95  # Updated from 0.9")
    """
    return _notebook_state.modify_cell(cell_index, new_code)


def delete_cell(cell_index: int) -> Dict[str, Any]:
    """
    Delete a cell from the script.

    Removes the cell at the specified index. Subsequent cells will have
    their indices updated. Note: This does NOT undo any side effects
    from executing the deleted cell (variables remain in namespace).

    Args:
        cell_index: The index of the cell to delete (0-based)

    Returns:
        Dictionary with deleted cell info and remaining cell count

    Examples:
        # Remove cell 3
        delete_cell(3)
    """
    return _notebook_state.delete_cell(cell_index)


def execute_cell(cell_index: int) -> Dict[str, Any]:
    """
    Execute a single cell and return its output.

    Runs the code in the specified cell within the persistent namespace.
    Variables created or modified will be available to subsequent cells.
    Captures stdout, stderr, and the cell's return value (if any).

    Args:
        cell_index: The index of the cell to execute (0-based)

    Returns:
        Dictionary containing:
        - index: Cell index
        - execution_count: Global execution counter
        - source: The executed code
        - stdout: Captured print() output
        - stderr: Captured error output
        - result: Return value of the last expression (if any)
        - error: Error traceback (if execution failed)
        - status: "success" or "error"

    Examples:
        # Execute the first cell
        execute_cell(0)

        # Execute and check for errors
        result = execute_cell(2)
        if result["status"] == "error":
            print(result["error"])
    """
    return _notebook_state.execute_cell(cell_index)


def execute_all_cells() -> List[Dict[str, Any]]:
    """
    Execute all cells in the script in order.

    Runs each cell sequentially from the beginning. Useful for
    re-running the entire notebook after modifications.

    Returns:
        List of execution results for each cell

    Examples:
        # Run entire notebook
        results = execute_all_cells()
        errors = [r for r in results if r.get("status") == "error"]
    """
    return _notebook_state.execute_all()


def get_script() -> Dict[str, Any]:
    """
    Get the complete script and current state.

    Returns all cells, the concatenated code, and current variable state.
    Useful for reviewing the notebook or exporting the code.

    Returns:
        Dictionary containing:
        - cells: List of all cells with their content and outputs
        - script: All code cells concatenated as a single script
        - variables: Summary of user-defined variables
        - cell_count: Total number of cells

    Examples:
        # Review current state
        state = get_script()
        print(f"Notebook has {state['cell_count']} cells")
        print(state['script'])
    """
    return {
        "cells": _notebook_state.cells,
        "script": _notebook_state.get_script(),
        "variables": _notebook_state.get_variables(),
        "cell_count": len(_notebook_state.cells)
    }


def get_variables() -> Dict[str, str]:
    """
    Get a summary of all user-defined variables in the namespace.

    Returns variable names with their types and values (truncated if long).
    Useful for understanding what data is available for use in new cells.

    Returns:
        Dictionary mapping variable names to "type: value" strings

    Examples:
        # Check available variables
        vars = get_variables()
        for name, info in vars.items():
            print(f"{name}: {info}")
    """
    return _notebook_state.get_variables()


def reset_notebook() -> Dict[str, Any]:
    """
    Reset the notebook state completely.

    Clears all cells and resets the namespace to its initial state.
    Use with caution - this cannot be undone.

    Returns:
        Dictionary confirming the reset

    Examples:
        # Start fresh
        reset_notebook()
    """
    return _notebook_state.reset()


# =============================================================================
# CANVAS TOOLS
# =============================================================================

def add_to_canvas(content: Any, title: Optional[str] = None, item_id: Optional[str] = None) -> str:
    """Add an item to the canvas for visualization. Canvas is like a note-taking tool where
    you can store charts, dataframes, images, and markdown text for the user to see.

    The canvas is backed by .canvas/canvas.md in the workspace. Items are written directly
    to the file so the UI can render the latest state.

    Args:
        content: Can be a pandas DataFrame, matplotlib Figure, plotly Figure,
                PIL Image, dictionary (for Plotly JSON), or string (for Markdown)
        title: Optional title for the canvas item (displayed as a header)
        item_id: Optional unique ID for the item. If provided, can be used to update
                or remove the item later. Auto-generated if not provided.

    Returns:
        Confirmation string describing what was added.

    Examples:
        # Add a DataFrame with a title
        import pandas as pd
        df = pd.DataFrame({"A": [1, 2, 3], "B": [4, 5, 6]})
        add_to_canvas(df, title="Sales Data")

        # Add a Matplotlib chart with a custom ID for later updates
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots()
        ax.plot([1, 2, 3], [1, 4, 9])
        add_to_canvas(fig, title="Growth Chart", item_id="growth_chart")

        # Add Markdown text
        add_to_canvas("## Key Findings\\n- Point 1\\n- Point 2", title="Summary")

        # Update an existing item by using the same ID
        add_to_canvas(new_fig, item_id="growth_chart")  # Replaces the previous chart
    """
    try:
        workspace_root = _get_workspace_root_for_context()

        # Parse the content into canvas format
        parsed = parse_canvas_object(
            content,
            workspace_root=workspace_root,
            title=title,
            item_id=item_id,
        )

        # Load existing items, append new one, write back
        items = load_canvas_from_markdown(workspace_root)

        # If item_id provided and already exists, replace it
        if item_id:
            items = [item for item in items if item.get("id") != item_id]

        items.append(parsed)
        export_canvas_to_markdown(items, workspace_root)

        item_type = parsed.get("type", "item")
        item_title = parsed.get("title", parsed.get("id", ""))
        return f"Added {item_type} to canvas: {item_title}"
    except Exception as e:
        return f"Failed to add to canvas: {e}"


def update_canvas_item(item_id: str, content: Any, title: Optional[str] = None) -> str:
    """Update an existing canvas item by its ID. If the item doesn't exist, it will be added.

    This is useful for updating charts or data that change over time, like progress
    indicators, live data visualizations, or iteratively refined content.

    Args:
        item_id: The unique ID of the canvas item to update
        content: The new content (DataFrame, Figure, Image, string, etc.)
        title: Optional new title for the item

    Returns:
        Confirmation string.

    Examples:
        # Create an initial chart
        add_to_canvas(initial_fig, title="Progress", item_id="progress_chart")

        # Later, update it with new data
        update_canvas_item("progress_chart", updated_fig)

        # Update with a new title too
        update_canvas_item("progress_chart", final_fig, title="Final Results")
    """
    try:
        workspace_root = _get_workspace_root_for_context()

        parsed = parse_canvas_object(
            content,
            workspace_root=workspace_root,
            title=title,
            item_id=item_id,
        )

        # Load existing items, replace matching ID or append
        items = load_canvas_from_markdown(workspace_root)
        replaced = False
        for i, item in enumerate(items):
            if item.get("id") == item_id:
                items[i] = parsed
                replaced = True
                break
        if not replaced:
            items.append(parsed)

        export_canvas_to_markdown(items, workspace_root)
        return f"Updated canvas item: {item_id}"
    except Exception as e:
        return f"Failed to update canvas item: {e}"


def remove_canvas_item(item_id: str) -> str:
    """Remove a canvas item by its ID.

    Args:
        item_id: The unique ID of the canvas item to remove

    Returns:
        Confirmation string.

    Examples:
        # Add a temporary notification
        add_to_canvas("Processing...", title="Status", item_id="status_msg")

        # Remove it when done
        remove_canvas_item("status_msg")
    """
    try:
        workspace_root = _get_workspace_root_for_context()

        items = load_canvas_from_markdown(workspace_root)
        original_count = len(items)
        items = [item for item in items if item.get("id") != item_id]

        if len(items) == original_count:
            return f"Canvas item not found: {item_id}"

        export_canvas_to_markdown(items, workspace_root)
        return f"Removed canvas item: {item_id}"
    except Exception as e:
        return f"Failed to remove canvas item: {e}"


# =============================================================================
# DISPLAY INLINE TOOL
# =============================================================================

@langchain_tool(response_format="content_and_artifact")
def display_inline(
    file_path: Any,
    title: Optional[str] = None,
    display_type: Optional[str] = None
) -> tuple[str, dict]:
    """Display a file to the user in a rich, interactive format inline in the chat.

    IMPORTANT: Always pass a file path, not raw content. Save your data to a file
    first (e.g. write a CSV, save a plot as PNG, export HTML to a file), then pass
    the file path to this tool. Passing raw strings, base64 data, or in-memory
    objects directly will produce rendering errors in the UI.

    This tool renders file content directly in the conversation for immediate
    visibility. Use this when you want the user to see results right away without
    navigating to the canvas. Supports images, HTML, Plotly charts, CSV/DataFrames,
    PDFs, JSON, and more.

    The full display data is sent as an artifact (not visible to the model) to avoid
    consuming context tokens. The model only sees a short confirmation message.

    Args:
        file_path: Path to the file to display. Must be a file path (absolute or
            relative to the workspace). Supported file types:
            - Images: .png, .jpg, .jpeg, .gif, .webp, .svg, .bmp, .ico
            - Documents: .html, .htm, .pdf
            - Data: .csv, .tsv, .json
            Do NOT pass raw content strings — save to a file first.
        title: Optional title displayed above the content
        display_type: Optional hint for how to render the content. One of:
            - "image": Force image rendering (PNG, JPEG, GIF, etc.)
            - "html": Force HTML rendering with preview
            - "plotly": Force Plotly chart rendering
            - "csv" or "dataframe": Force table rendering
            - "json": Force JSON rendering
            - "text": Force plain text rendering
            Auto-detected from file extension if not provided.

    Returns:
        Tuple of (content_for_model, artifact_for_ui):
        - content_for_model: Short confirmation string for the LLM
        - artifact_for_ui: Full display data dict for the UI

    Examples:
        # Show an image file
        display_inline("analysis_results.png", title="Results Chart")

        # Show a CSV file as a table
        display_inline("report.csv", title="Monthly Report")

        # Show an HTML file
        display_inline("output/dashboard.html", title="Dashboard")

        # Show a PDF
        display_inline("report.pdf", title="Final Report")
    """
    result_dict = _display_inline_impl(file_path, title, display_type)

    # Build a short stub for the model's context
    dt = result_dict.get("display_type", "content")
    t = result_dict.get("title") or dt
    status = result_dict.get("status", "success")
    if status == "error":
        stub = f"Display error: {result_dict.get('error', 'unknown error')}"
    else:
        stub = f"Displayed {dt} inline: {t}"

    return (stub, result_dict)


def _display_inline_impl(
    file_path: Any,
    title: Optional[str] = None,
    display_type: Optional[str] = None
) -> Dict[str, Any]:
    """Internal implementation of display_inline that returns a dict."""
    import base64
    import io
    import json
    from pathlib import PurePath

    result = {
        "type": "display_inline",
        "display_type": None,
        "title": title,
        "data": None,
        "preview": None,  # For thumbnails
        "downloadable": False,
        "status": "success",
        "error": None
    }

    try:
        # Get workspace root for file operations
        workspace_root = _get_workspace_root_for_context()

        # Detect content type and process accordingly
        obj_type = type(file_path).__name__
        obj_module = type(file_path).__module__

        # Handle file paths (strings that look like file paths)
        if isinstance(file_path, str) and not display_type:
            # Check if it's a file path
            if _is_file_path(file_path, workspace_root):
                return _process_file_for_display(file_path, workspace_root, title, display_type)

            # If it looks like a file path but doesn't exist, try to find it
            from pathlib import PurePath
            ext = PurePath(file_path).suffix.lower()
            known_file_extensions = {
                '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.ico',
                '.html', '.htm', '.csv', '.tsv', '.json', '.pdf'
            }
            if ext in known_file_extensions and "\n" not in file_path and len(file_path) < 500:
                # Try to find the file - check if just filename was passed
                found_path = _find_file_in_workspace(file_path, workspace_root)
                if found_path:
                    return _process_file_for_display(found_path, workspace_root, title, display_type)
                else:
                    # Return error - file not found
                    result["status"] = "error"
                    result["display_type"] = "error"
                    result["error"] = f"File not found: {file_path}"
                    result["data"] = f"Could not find file '{file_path}' in workspace. Make sure the file exists and the path is correct."
                    return result

            # Otherwise, check for explicit display types or treat as text/HTML
            if file_path.strip().startswith("<") and ">" in file_path:
                result["display_type"] = "html"
                result["data"] = file_path
                result["preview"] = file_path[:500] + "..." if len(file_path) > 500 else file_path
                return result

        # Handle explicit display_type for strings
        if isinstance(file_path, str) and display_type:
            if display_type == "html":
                # Check if it's a file path first
                if _is_file_path(file_path, workspace_root):
                    return _process_file_for_display(file_path, workspace_root, title, "html")
                result["display_type"] = "html"
                result["data"] = file_path
                result["preview"] = file_path[:500] + "..." if len(file_path) > 500 else file_path
                return result
            elif display_type == "text":
                result["display_type"] = "text"
                result["data"] = file_path
                return result
            elif display_type in ("csv", "dataframe"):
                # Check if it's a file path first
                if _is_file_path(file_path, workspace_root):
                    return _process_file_for_display(file_path, workspace_root, title, "csv")
                # Parse CSV string
                try:
                    import pandas as pd
                    df = pd.read_csv(io.StringIO(file_path))
                    return _process_dataframe_for_display(df, title)
                except Exception as e:
                    result["display_type"] = "text"
                    result["data"] = file_path
                    result["error"] = f"Could not parse as CSV: {e}"
                    return result
            elif display_type == "json":
                # Check if it's a file path first
                if _is_file_path(file_path, workspace_root):
                    return _process_file_for_display(file_path, workspace_root, title, "json")
                result["display_type"] = "json"
                try:
                    result["data"] = json.loads(file_path) if isinstance(file_path, str) else file_path
                except json.JSONDecodeError:
                    result["data"] = file_path
                return result
            elif display_type == "image":
                # Assume it's base64 or file path
                if _is_file_path(file_path, workspace_root):
                    return _process_file_for_display(file_path, workspace_root, title, "image")
                result["display_type"] = "image"
                result["data"] = file_path  # Assume base64
                return result
            elif display_type == "plotly":
                # Check if it's a file path first
                if _is_file_path(file_path, workspace_root):
                    return _process_file_for_display(file_path, workspace_root, title, "plotly")
                result["display_type"] = "plotly"
                if isinstance(file_path, str):
                    result["data"] = json.loads(file_path)
                else:
                    result["data"] = file_path
                return result

        # Handle bytes (binary data - likely image)
        if isinstance(file_path, bytes):
            result["display_type"] = "image"
            result["data"] = base64.b64encode(file_path).decode('utf-8')
            return result

        # Handle pandas DataFrame
        if obj_module.startswith('pandas') and obj_type == 'DataFrame':
            return _process_dataframe_for_display(file_path, title)

        # Handle matplotlib Figure
        if obj_module.startswith('matplotlib') and 'Figure' in obj_type:
            buf = io.BytesIO()
            file_path.savefig(buf, format='png', bbox_inches='tight', dpi=100)
            buf.seek(0)
            img_data = buf.read()
            buf.close()

            result["display_type"] = "image"
            result["data"] = base64.b64encode(img_data).decode('utf-8')
            result["mime_type"] = "image/png"
            return result

        # Handle Plotly Figure
        if obj_module.startswith('plotly') and 'Figure' in obj_type:
            result["display_type"] = "plotly"
            result["data"] = json.loads(file_path.to_json())
            return result

        # Handle dict (check for Plotly JSON structure or serialization artifacts)
        if isinstance(file_path, dict):
            # Check if this looks like a serialized matplotlib/plotly reference (common mistake)
            if file_path.get('type') in ('matplotlib', 'plotly') and 'figure' in file_path:
                result["status"] = "error"
                result["display_type"] = "error"
                result["error"] = (
                    "Cannot display figure objects directly. The figure was serialized to a reference. "
                    "To display matplotlib figures, save them to a file first:\n"
                    "  fig.savefig('chart.png')\n"
                    "  display_inline('chart.png')\n"
                    "Or use add_to_canvas(fig) inside a notebook cell."
                )
                result["data"] = str(file_path)
                return result
            # Check for Plotly JSON structure
            if 'data' in file_path and isinstance(file_path.get('data'), list):
                result["display_type"] = "plotly"
                result["data"] = file_path
                return result
            else:
                result["display_type"] = "json"
                result["data"] = file_path
                return result

        # Handle PIL Image
        if obj_module.startswith('PIL') and 'Image' in obj_type:
            buf = io.BytesIO()
            file_path.save(buf, format='PNG')
            buf.seek(0)
            img_data = buf.read()
            buf.close()

            result["display_type"] = "image"
            result["data"] = base64.b64encode(img_data).decode('utf-8')
            result["mime_type"] = "image/png"
            return result

        # Handle list (could be data for table)
        if isinstance(file_path, list) and len(file_path) > 0:
            if isinstance(file_path[0], dict):
                # List of dicts - render as table
                try:
                    import pandas as pd
                    df = pd.DataFrame(file_path)
                    return _process_dataframe_for_display(df, title)
                except Exception:
                    result["display_type"] = "json"
                    result["data"] = file_path
                    return result
            else:
                result["display_type"] = "json"
                result["data"] = file_path
                return result

        # Default: convert to string
        result["display_type"] = "text"
        result["data"] = str(file_path)
        return result

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        result["display_type"] = "error"
        result["data"] = f"Error processing content: {e}"
        return result


def _is_file_path(content: str, workspace_root: Any) -> bool:
    """Check if a string looks like a file path that exists."""
    if not content or len(content) > 500:  # Too long to be a path
        return False
    if "\n" in content:  # Contains newlines - not a path
        return False

    # Check for common file extensions
    from pathlib import Path, PurePath
    ext = PurePath(content).suffix.lower()
    known_extensions = {
        '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.ico',
        '.html', '.htm',
        '.csv', '.tsv',
        '.json',
        '.pdf'
    }

    if ext in known_extensions:
        from .file_utils import _get_path
        from .virtual_fs import VirtualFilesystem

        try:
            # For absolute paths with physical filesystem, check the path directly
            # This handles cases where an absolute path is passed that may be outside workspace
            if content.startswith('/') and not isinstance(workspace_root, VirtualFilesystem):
                abs_path = Path(content)
                return abs_path.exists() and abs_path.is_file()

            # For relative paths or VirtualFilesystem, use _get_path
            full_path = _get_path(workspace_root, content)
            return full_path.exists()
        except Exception:
            return False

    return False


def _find_file_in_workspace(filename: str, workspace_root: Any) -> Optional[str]:
    """Try to find a file in the workspace by searching common locations.

    Args:
        filename: The filename or path to search for
        workspace_root: The workspace root (Path or VirtualFilesystem)

    Returns:
        The relative path to the file if found, None otherwise
    """
    from pathlib import PurePath
    from .file_utils import _get_path

    # Extract just the filename if a path was provided
    basename = PurePath(filename).name

    # Locations to search (in order of priority)
    search_paths = [
        filename,  # As provided
        basename,  # Just the filename in root
        f".canvas/{basename}",  # In canvas folder
        f"output/{basename}",  # Common output folder
        f"outputs/{basename}",
        f"results/{basename}",
    ]

    # Also try the exact path as-is first
    for path in search_paths:
        try:
            full_path = _get_path(workspace_root, path)
            if full_path.exists() and full_path.is_file():
                return path
        except Exception:
            continue

    # Try recursive search for the filename (limited depth)
    try:
        from .virtual_fs import VirtualFilesystem
        if isinstance(workspace_root, VirtualFilesystem):
            # For VirtualFilesystem, check all files
            for file_path in workspace_root.glob("**/*"):
                if file_path.name == basename and file_path.is_file():
                    # Return relative path
                    return str(file_path).lstrip("/")
        else:
            # For physical filesystem
            import os
            for root, dirs, files in os.walk(workspace_root):
                # Limit depth to 3 levels
                rel_root = os.path.relpath(root, workspace_root)
                if rel_root.count(os.sep) > 3:
                    continue
                # Skip hidden directories
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                if basename in files:
                    return os.path.relpath(os.path.join(root, basename), workspace_root)
    except Exception:
        pass

    return None


def _process_file_for_display(
    file_path: str,
    workspace_root: Any,
    title: Optional[str],
    display_type: Optional[str]
) -> Dict[str, Any]:
    """Process a file path and return display data."""
    import base64
    import json
    from pathlib import Path, PurePath
    from .file_utils import _get_path, read_file_content, get_file_download_data
    from .virtual_fs import VirtualFilesystem

    result = {
        "type": "display_inline",
        "display_type": None,
        "title": title,
        "data": None,
        "preview": None,
        "filename": PurePath(file_path).name,
        "file_path": file_path,
        "downloadable": True,
        "status": "success",
        "error": None
    }

    ext = PurePath(file_path).suffix.lower()

    # For absolute paths with physical filesystem, use the path directly
    is_absolute_physical = file_path.startswith('/') and not isinstance(workspace_root, VirtualFilesystem)
    if is_absolute_physical:
        full_path = Path(file_path)
    else:
        full_path = _get_path(workspace_root, file_path)

    if not full_path.exists():
        result["status"] = "error"
        result["error"] = f"File not found: {file_path}"
        return result

    # Image files
    image_exts = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.ico'}
    if ext in image_exts or display_type == "image":
        b64, filename, mime = get_file_download_data(workspace_root, file_path)
        if b64:
            result["display_type"] = "image"
            result["data"] = b64
            result["mime_type"] = mime
            return result

    # HTML files
    if ext in {'.html', '.htm'} or display_type == "html":
        content, is_text, error = read_file_content(workspace_root, file_path)
        if content:
            result["display_type"] = "html"
            result["data"] = content
            result["preview"] = content[:1000] + "..." if len(content) > 1000 else content
            return result

    # CSV files
    if ext in {'.csv', '.tsv'} or display_type in ("csv", "dataframe"):
        content, is_text, error = read_file_content(workspace_root, file_path)
        if content:
            try:
                import pandas as pd
                import io
                sep = '\t' if ext == '.tsv' else ','
                df = pd.read_csv(io.StringIO(content), sep=sep)
                df_result = _process_dataframe_for_display(df, title)
                df_result["filename"] = result["filename"]
                df_result["file_path"] = file_path
                df_result["downloadable"] = True
                return df_result
            except Exception as e:
                result["display_type"] = "text"
                result["data"] = content
                result["error"] = f"Could not parse as CSV: {e}"
                return result

    # JSON files (check for Plotly) or explicit plotly display_type
    if ext == '.json' or display_type in ("json", "plotly"):
        content, is_text, error = read_file_content(workspace_root, file_path)
        if content:
            try:
                data = json.loads(content)
                # Force plotly if display_type is explicitly set, otherwise auto-detect
                if display_type == "plotly":
                    result["display_type"] = "plotly"
                    result["data"] = data
                # Check if it's Plotly JSON (auto-detect)
                elif isinstance(data, dict) and 'data' in data and isinstance(data.get('data'), list):
                    result["display_type"] = "plotly"
                    result["data"] = data
                else:
                    result["display_type"] = "json"
                    result["data"] = data
                return result
            except json.JSONDecodeError:
                result["display_type"] = "text"
                result["data"] = content
                return result

    # PDF files
    if ext == '.pdf':
        b64, filename, mime = get_file_download_data(workspace_root, file_path)
        if b64:
            result["display_type"] = "pdf"
            result["data"] = b64
            result["mime_type"] = mime
            return result

    # Default: try to read as text
    content, is_text, error = read_file_content(workspace_root, file_path)
    if content:
        result["display_type"] = "text"
        result["data"] = content
        return result

    result["status"] = "error"
    result["error"] = error or "Could not read file"
    return result


def _process_dataframe_for_display(df: Any, title: Optional[str]) -> Dict[str, Any]:
    """Process a pandas DataFrame for display."""
    result = {
        "type": "display_inline",
        "display_type": "dataframe",
        "title": title,
        "data": None,
        "preview": None,
        "downloadable": True,
        "status": "success",
        "error": None
    }

    # Create preview (first 10 rows)
    preview_df = df.head(10)
    result["preview"] = {
        "html": preview_df.to_html(index=False, classes="dataframe-table"),
        "rows_shown": len(preview_df),
        "total_rows": len(df),
        "columns": list(df.columns)
    }

    # Full data
    result["data"] = {
        "html": df.to_html(index=False, classes="dataframe-table"),
        "records": df.to_dict('records'),
        "columns": list(df.columns),
        "shape": list(df.shape)
    }

    # CSV for download
    result["csv"] = df.to_csv(index=False)

    return result


# =============================================================================
# BASH TOOL
# =============================================================================

def bash(command: str, timeout: int = 60) -> Dict[str, Any]:
    """Execute a bash command and return the output.

    Runs the command in the workspace directory. Use this for file operations,
    git commands, installing packages, or any shell operations.

    In virtual filesystem mode (Linux only), commands run in a bubblewrap sandbox
    with network disabled for security.

    Args:
        command: The bash command to execute
        timeout: Maximum time in seconds to wait for the command (default: 60)

    Returns:
        Dictionary containing:
        - stdout: Standard output from the command
        - stderr: Standard error output
        - return_code: Exit code (0 typically means success)
        - status: "success" or "error"

    Examples:
        # List files
        bash("ls -la")

        # Check git status
        bash("git status")

        # Install a package
        bash("pip install pandas")

        # Run a script
        bash("python script.py")
    """
    # In virtual filesystem mode, use sandboxed execution
    if VIRTUAL_FS:
        return _bash_sandboxed(command, timeout)

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(WORKSPACE_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout
        )

        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_code": result.returncode,
            "status": "success" if result.returncode == 0 else "error"
        }

    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds",
            "return_code": -1,
            "status": "error"
        }
    except Exception as e:
        return {
            "stdout": "",
            "stderr": str(e),
            "return_code": -1,
            "status": "error"
        }


def _bash_sandboxed(command: str, timeout: int = 60) -> Dict[str, Any]:
    """Execute bash command in sandboxed environment for virtual FS mode.

    Uses bubblewrap (Linux) for sandboxing with:
    - No network access
    - Isolated PID namespace
    - Read-only system directories
    - Writable workspace directory synced with VirtualFilesystem
    """
    from .sandbox import get_executor_for_session, get_available_sandbox
    from .virtual_fs import get_session_manager

    # Get current session context
    session_id = get_tool_session_context()
    if not session_id:
        return {
            "stdout": "",
            "stderr": "No session context available for sandboxed execution",
            "return_code": 1,
            "status": "error"
        }

    # Check if sandbox is available
    sandbox = get_available_sandbox()
    if sandbox is None:
        return {
            "stdout": "",
            "stderr": "Bash commands require bubblewrap (bwrap) or Docker in virtual filesystem mode. "
                      "Install bubblewrap: apt-get install bubblewrap",
            "return_code": 1,
            "status": "error"
        }

    # Get the virtual filesystem for this session
    fs = get_session_manager().get_filesystem(session_id)
    if fs is None:
        return {
            "stdout": "",
            "stderr": "Session filesystem not found",
            "return_code": 1,
            "status": "error"
        }

    # Get or create executor for this session
    executor = get_executor_for_session(session_id, fs)

    # Execute command in sandbox
    return executor.execute(command, timeout=timeout)


# Add a think tool
def think_tool(reflection: str) -> str:
    """A tool to reflect on your actions and reasoning.

    This tool allows you to pause and think about your next steps,
    evaluate your current state, or reconsider your approach. Use 
    this tool to generate internal reflections that the user can see.

    Args:
        reflection: The reflection text
    Returns:
        str: The recorded reflection
    """
    return reflection
