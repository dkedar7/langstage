"""File tree and file operations utilities.

Supports both physical filesystem (Path) and virtual filesystem (VirtualFilesystem)
for session isolation in multi-user deployments.
"""

import base64
from pathlib import Path, PurePosixPath
from typing import List, Dict, Tuple, Union, Optional
from dash import html

from .virtual_fs import VirtualFilesystem, VirtualPath


TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json", ".md", ".txt",
    ".yaml", ".yml", ".toml", ".xml", ".csv", ".sh", ".bash", ".sql", ".env",
    ".gitignore", ".dockerignore", ".cfg", ".ini", ".conf", ".log"
}

# Type alias for paths that work with both physical and virtual filesystems
AnyPath = Union[Path, VirtualPath]
AnyRoot = Union[Path, VirtualFilesystem]


def is_text_file(filename: str) -> bool:
    """Check if a file can be viewed as text."""
    ext = Path(filename).suffix.lower()
    return ext in TEXT_EXTENSIONS or ext == ""


def _get_path(root: AnyRoot, path: str = "") -> AnyPath:
    """Get a path object from root, handling both Path and VirtualFilesystem."""
    if isinstance(root, VirtualFilesystem):
        return root.path(path) if path else root.root
    else:
        return root / path if path else root


def _relative_path(path: AnyPath, root: AnyPath) -> str:
    """Get relative path string."""
    if isinstance(path, VirtualPath):
        path_str = str(path)
        root_str = str(root)
        if path_str.startswith(root_str):
            rel = path_str[len(root_str):].lstrip("/")
            return rel or "."
        return str(path)
    else:
        return str(path.relative_to(root))


def build_file_tree(
    root: AnyPath,
    workspace_root: AnyRoot,
    lazy_load: bool = True
) -> List[Dict]:
    """
    Build file tree structure.

    Args:
        root: Directory to scan (Path or VirtualPath)
        workspace_root: Root workspace directory for relative paths (Path or VirtualFilesystem)
        lazy_load: If True, only load immediate children (subdirs not expanded)

    Returns:
        List of file/folder items
    """
    items = []

    # Get the root path object if workspace_root is a VirtualFilesystem
    if isinstance(workspace_root, VirtualFilesystem):
        workspace_root_path = workspace_root.root
    else:
        workspace_root_path = workspace_root

    try:
        # Get entries from directory
        if isinstance(root, VirtualPath):
            entries = list(root.iterdir())
        else:
            entries = list(root.iterdir())

        # Sort: directories first, then by name
        entries = sorted(entries, key=lambda x: (not x.is_dir(), x.name.lower()))

        for entry in entries:
            if entry.name.startswith('.'):
                continue

            rel_path = _relative_path(entry, workspace_root_path)

            if entry.is_dir():
                # Count immediate children to show if folder is empty
                try:
                    has_children = any(not item.name.startswith('.') for item in entry.iterdir())
                except (PermissionError, OSError):
                    has_children = False

                items.append({
                    "type": "folder",
                    "name": entry.name,
                    "path": rel_path,
                    "has_children": has_children,
                    # Only recursively load children if not lazy loading
                    "children": [] if lazy_load else build_file_tree(entry, workspace_root, lazy_load=False)
                })
            else:
                items.append({
                    "type": "file",
                    "name": entry.name,
                    "path": rel_path,
                    "viewable": is_text_file(entry.name)
                })
    except (PermissionError, FileNotFoundError):
        pass

    return items


def load_folder_contents(
    folder_path: str,
    workspace_root: AnyRoot
) -> List[Dict]:
    """
    Load contents of a specific folder (for lazy loading).

    Args:
        folder_path: Relative path to the folder from workspace root
        workspace_root: Root workspace directory (Path or VirtualFilesystem)

    Returns:
        List of file/folder items in the specified folder
    """
    full_path = _get_path(workspace_root, folder_path)
    return build_file_tree(full_path, workspace_root, lazy_load=True)


def render_file_tree(items: List[Dict], colors: Dict, styles: Dict, level: int = 0, parent_path: str = "", expanded_folders: List[str] = None, workspace_root: AnyRoot = None) -> List:
    """Render file tree with collapsible folders using CSS classes for theming.

    Args:
        items: List of file/folder items from build_file_tree
        colors: Theme colors dict
        styles: Style dict
        level: Current nesting level
        parent_path: Path of parent folder
        expanded_folders: List of folder IDs that should be expanded
        workspace_root: Workspace root for loading expanded folder contents
    """
    components = []
    indent = level * 15  # Scaled up indent
    expanded_folders = expanded_folders or []

    for item in items:
        if item["type"] == "folder":
            folder_id = item["path"].replace("/", "_").replace("\\", "_")
            children = item.get("children", [])
            is_expanded = folder_id in expanded_folders

            # Folder header with expand icon and selectable name
            components.append(
                html.Div([
                    # Expand/collapse icon (left side)
                    html.Span(
                        "▶",
                        id={"type": "folder-icon", "path": folder_id},
                        className="folder-icon folder-expand-toggle",
                        style={
                            "marginRight": "5px",
                            "fontSize": "10px",
                            "transition": "transform 0.15s",
                            "display": "inline-block",
                            "padding": "2px",
                            "transform": "rotate(90deg)" if is_expanded else "rotate(0deg)",
                        }
                    ),
                    # Folder name (clickable for selection)
                    html.Span(item["name"],
                        id={"type": "folder-select", "path": folder_id},
                        className="folder-name folder-select-target",
                        **{"data-folderpath": item["path"]},
                        style={
                            "fontWeight": "500",
                            "fontSize": "14px",
                            "flex": "1",
                            "padding": "2px 4px",
                            "borderRadius": "3px",
                        }
                    )
                ],
                id={"type": "folder-header", "path": folder_id},
                **{"data-realpath": item["path"]},  # Store actual path for lazy loading
                className="folder-header file-tree-item",
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "padding": "5px 10px",
                    "paddingLeft": f"{10 + indent}px",
                    "cursor": "pointer",
                    "userSelect": "none",
                },
                )
            )

            # Folder children (hidden by default) - always create even if empty
            # Show different content based on whether children are loaded
            has_children = item.get("has_children", True)

            if children:
                # Children are loaded, render them
                child_content = render_file_tree(children, colors, styles, level + 1, item["path"], expanded_folders, workspace_root)
            elif not has_children:
                # Folder is known to be empty
                child_content = [
                    html.Div("(empty)", className="file-tree-empty", style={
                        "padding": "4px 10px",
                        "paddingLeft": f"{25 + (level + 1) * 15}px",
                        "fontSize": "12px",
                        "fontStyle": "italic",
                    })
                ]
            elif is_expanded and workspace_root is not None:
                # Folder is expanded but children not loaded - load them now
                # This happens when rebuilding the tree with preserved expanded_folders state
                try:
                    folder_items = load_folder_contents(item["path"], workspace_root)
                    child_content = render_file_tree(folder_items, colors, styles, level + 1, item["path"], expanded_folders, workspace_root)
                    if not child_content:
                        child_content = [
                            html.Div("(empty)", className="file-tree-empty", style={
                                "padding": "4px 10px",
                                "paddingLeft": f"{25 + (level + 1) * 15}px",
                                "fontSize": "12px",
                                "fontStyle": "italic",
                            })
                        ]
                except Exception:
                    # Fall back to loading placeholder if loading fails
                    child_content = [
                        html.Div("Loading...",
                            id={"type": "folder-loading", "path": folder_id},
                            className="file-tree-loading",
                            style={
                                "padding": "4px 10px",
                                "paddingLeft": f"{25 + (level + 1) * 15}px",
                                "fontSize": "12px",
                                "fontStyle": "italic",
                            }
                        )
                    ]
            else:
                # Children not yet loaded (lazy loading) and folder is collapsed
                child_content = [
                    html.Div("Loading...",
                        id={"type": "folder-loading", "path": folder_id},
                        className="file-tree-loading",
                        style={
                            "padding": "4px 10px",
                            "paddingLeft": f"{25 + (level + 1) * 15}px",
                            "fontSize": "12px",
                            "fontStyle": "italic",
                        }
                    )
                ]

            components.append(
                html.Div(
                    child_content,
                    id={"type": "folder-children", "path": folder_id},
                    style={"display": "block" if is_expanded else "none"}
                )
            )
        else:
            # File item
            components.append(
                html.Div(
                    item["name"],
                    id={"type": "file-item", "path": item["path"]},
                    className="file-item file-tree-item",
                    style={
                        "fontSize": "14px",
                        "padding": "5px 10px",
                        "paddingLeft": f"{25 + indent}px",
                        "cursor": "pointer",
                    },
                    **{"data-viewable": "true" if item["viewable"] else "false"}
                )
            )

    return components


def read_file_content(
    workspace_root: AnyRoot,
    path: str
) -> Tuple[Optional[str], bool, Optional[str]]:
    """Read file content. Returns (content, is_text, error)."""
    full_path = _get_path(workspace_root, path)

    if not full_path.exists() or not full_path.is_file():
        return None, False, "File not found"

    if is_text_file(path):
        try:
            content = full_path.read_text(encoding="utf-8")
            return content, True, None
        except UnicodeDecodeError:
            return None, False, "Binary file - cannot display"
        except Exception as e:
            return None, False, str(e)
    else:
        return None, False, "Binary file - download to view"


def get_file_download_data(
    workspace_root: AnyRoot,
    path: str
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Get file data for download. Returns (base64_content, filename, mime_type)."""
    full_path = _get_path(workspace_root, path)

    if not full_path.exists():
        return None, None, None

    try:
        content = full_path.read_bytes()
        b64 = base64.b64encode(content).decode('utf-8')

        # Determine MIME type
        ext = PurePosixPath(path).suffix.lower()
        mime_types = {
            # Text
            ".txt": "text/plain", ".py": "text/x-python", ".js": "text/javascript",
            ".json": "application/json", ".html": "text/html", ".htm": "text/html",
            ".css": "text/css", ".md": "text/markdown", ".csv": "text/csv",
            ".xml": "text/xml", ".yaml": "text/yaml", ".yml": "text/yaml",
            # Images
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
            ".ico": "image/x-icon", ".bmp": "image/bmp",
            # Video
            ".mp4": "video/mp4", ".webm": "video/webm", ".ogg": "video/ogg",
            ".mov": "video/quicktime",
            # Audio
            ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
            ".flac": "audio/flac",
            # Documents
            ".pdf": "application/pdf",
            # Archives
            ".zip": "application/zip",
        }
        mime = mime_types.get(ext, "application/octet-stream")

        # Get filename
        if isinstance(full_path, VirtualPath):
            filename = full_path.name
        else:
            filename = full_path.name

        return b64, filename, mime
    except Exception:
        return None, None, None


def write_file(
    workspace_root: AnyRoot,
    path: str,
    content: Union[str, bytes],
    encoding: str = "utf-8"
) -> bool:
    """
    Write content to a file.

    Args:
        workspace_root: Root workspace directory (Path or VirtualFilesystem)
        path: Relative path to the file
        content: Content to write (str or bytes)
        encoding: Encoding for text content

    Returns:
        True if successful, False otherwise
    """
    full_path = _get_path(workspace_root, path)

    try:
        if isinstance(content, str):
            full_path.write_text(content, encoding=encoding)
        else:
            full_path.write_bytes(content)
        return True
    except Exception as e:
        print(f"Error writing file {path}: {e}")
        return False


def create_directory(
    workspace_root: AnyRoot,
    path: str,
    parents: bool = True,
    exist_ok: bool = True
) -> bool:
    """
    Create a directory.

    Args:
        workspace_root: Root workspace directory (Path or VirtualFilesystem)
        path: Relative path to the directory
        parents: Create parent directories if needed
        exist_ok: Don't error if directory exists

    Returns:
        True if successful, False otherwise
    """
    full_path = _get_path(workspace_root, path)

    try:
        full_path.mkdir(parents=parents, exist_ok=exist_ok)
        return True
    except Exception as e:
        print(f"Error creating directory {path}: {e}")
        return False
