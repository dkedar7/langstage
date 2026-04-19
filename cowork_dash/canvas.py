"""Canvas utilities for parsing, exporting, and loading canvas objects.

Supports both physical filesystem (Path) and virtual filesystem (VirtualFilesystem)
for session isolation in multi-user deployments.
"""

import io
import json
import base64
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from datetime import datetime

# Early pandas import to prevent circular import issues with Plotly's JSON serializer.
# Plotly lazily imports pandas and checks `obj is pd.NaT` which fails if pandas
# is partially initialized due to concurrent imports.
try:
    import pandas
except (ImportError, AttributeError):
    pass

from .virtual_fs import VirtualFilesystem, VirtualPath


# Type alias for paths that work with both physical and virtual filesystems
AnyPath = Union[Path, VirtualPath]
AnyRoot = Union[Path, VirtualFilesystem]


def _get_path(root: AnyRoot, path: str = "") -> AnyPath:
    """Get a path object from root, handling both Path and VirtualFilesystem."""
    if isinstance(root, VirtualFilesystem):
        return root.path(path) if path else root.root
    else:
        return root / path if path else root


def generate_canvas_id() -> str:
    """Generate a unique ID for a canvas item."""
    return f"canvas_{uuid.uuid4().hex[:8]}"


# Extensions that should be copied as assets into .canvas/
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico"}
_HTML_EXTENSIONS = {".html", ".htm"}
_DATA_EXTENSIONS = {".csv", ".tsv"}
_PLOTLY_EXTENSIONS = {".json"}  # JSON files with Plotly structure


def _maybe_copy_asset_to_canvas(
    obj: str,
    workspace_root: AnyRoot,
    canvas_dir: AnyPath,
) -> Optional[Dict[str, Any]]:
    """If *obj* looks like a file path to a known asset type, copy it into
    .canvas/ and return the parsed canvas item dict.  Returns None if
    *obj* is not a recognised asset path.
    """
    # Quick reject: must look like a path (no newlines, not too long)
    if "\n" in obj or len(obj) > 500:
        return None

    from pathlib import PurePosixPath
    ext = PurePosixPath(obj).suffix.lower()
    known = _IMAGE_EXTENSIONS | _HTML_EXTENSIONS | _DATA_EXTENSIONS | _PLOTLY_EXTENSIONS
    if ext not in known:
        return None

    # Resolve the source file
    try:
        src = _get_path(workspace_root, obj.lstrip("/"))
        if not src.exists() or not src.is_file():
            # Try absolute path for physical filesystem
            if obj.startswith("/") and not isinstance(workspace_root, VirtualFilesystem):
                src = Path(obj)
                if not src.exists() or not src.is_file():
                    return None
            else:
                return None
    except Exception:
        return None

    # Determine destination filename (avoid collisions)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    dest_name = f"{timestamp}_{src.name}"
    dest = canvas_dir / dest_name

    # Copy the file into .canvas/
    try:
        dest.write_bytes(src.read_bytes())
    except Exception:
        return None

    # Build item dict based on extension
    if ext in _IMAGE_EXTENSIONS:
        img_b64 = base64.b64encode(src.read_bytes()).decode("utf-8")
        return {
            "type": "image",
            "file": dest_name,
            "data": img_b64,
        }

    if ext in _HTML_EXTENSIONS:
        html_content = src.read_text(errors="replace")
        return {
            "type": "html",
            "file": dest_name,
            "data": html_content,
        }

    if ext in _DATA_EXTENSIONS:
        try:
            import pandas as pd
            sep = "\t" if ext == ".tsv" else ","
            df = pd.read_csv(str(src) if isinstance(src, Path) else io.StringIO(src.read_text()), sep=sep)
            return {
                "type": "dataframe",
                "file": dest_name,
                "data": df.to_dict("records"),
                "columns": list(df.columns),
                "html": df.to_html(index=False, classes="dataframe-table"),
            }
        except Exception:
            # Fall back to markdown code block
            return {
                "type": "markdown",
                "file": dest_name,
                "data": f"```csv\n{src.read_text(errors='replace')}\n```",
            }

    if ext in _PLOTLY_EXTENSIONS:
        try:
            plotly_data = json.loads(src.read_text())
            if isinstance(plotly_data, dict) and ("data" in plotly_data or "layout" in plotly_data):
                return {
                    "type": "plotly",
                    "file": dest_name,
                    "data": plotly_data,
                }
        except (json.JSONDecodeError, Exception):
            pass

    return None


def parse_canvas_object(
    obj: Any,
    workspace_root: AnyRoot,
    title: Optional[str] = None,
    item_id: Optional[str] = None,
    source_cell: Optional[int] = None,
    execution_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Parse Python objects into canvas-renderable format.

    Args:
        obj: The Python object to parse (DataFrame, Figure, Image, str, etc.)
        workspace_root: Path to the workspace root directory (Path or VirtualFilesystem)
        title: Optional title for the canvas item
        item_id: Optional ID for the canvas item (auto-generated if not provided)
        source_cell: Optional cell index that produced this item
        execution_count: Optional execution count at the time of creation

    Supports:
    - pd.DataFrame (inline in markdown)
    - matplotlib.figure.Figure (saved to .canvas/ folder)
    - plotly.graph_objects.Figure (saved to .canvas/ folder)
    - PIL.Image (saved to .canvas/ folder)
    - dict (Plotly JSON - saved to .canvas/ folder)
    - str (Markdown with Mermaid support - inline)
    """
    obj_type = type(obj).__name__
    module = type(obj).__module__

    # Generate ID and timestamp for this item
    canvas_id = item_id or generate_canvas_id()
    created_at = datetime.now().isoformat()

    # Base metadata that all items will have
    def add_metadata(result: Dict) -> Dict:
        result["id"] = canvas_id
        result["created_at"] = created_at
        if title:
            result["title"] = title
        if source_cell is not None:
            result["source_cell"] = int(source_cell)
        if execution_count is not None:
            result["execution_count"] = int(execution_count)
        return result

    # Ensure .canvas directory exists
    canvas_dir = _get_path(workspace_root, ".canvas")
    canvas_dir.mkdir(exist_ok=True)

    # Section header — structural item for report organization
    if isinstance(obj, dict) and obj.get("__canvas_kind__") == "section":
        return add_metadata({
            "type": "section",
            "data": obj.get("text", ""),
            "level": int(obj.get("level", 1)),
        })

    # Pandas DataFrame - keep inline
    if module.startswith('pandas') and obj_type == 'DataFrame':
        return add_metadata({
            "type": "dataframe",
            "data": obj.to_dict('records'),
            "columns": list(obj.columns),
            "html": obj.to_html(index=False, classes="dataframe-table")
        })

    # Matplotlib Figure - save to file
    elif module.startswith('matplotlib') and 'Figure' in obj_type:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"matplotlib_{timestamp}.png"
        filepath = canvas_dir / filename

        # Save to buffer first, then to file
        buf = io.BytesIO()
        obj.savefig(buf, format='png', bbox_inches='tight', dpi=100)
        buf.seek(0)
        img_data = buf.read()
        buf.close()

        # Write to file (virtual or physical)
        filepath.write_bytes(img_data)

        # Also store base64 for in-memory rendering
        img_base64 = base64.b64encode(img_data).decode('utf-8')

        return add_metadata({
            "type": "matplotlib",
            "file": filename,  # Relative to .canvas/ directory where canvas.md lives
            "data": img_base64  # Keep for current session rendering
        })

    # Plotly Figure - save to file
    elif module.startswith('plotly') and 'Figure' in obj_type:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"plotly_{timestamp}.json"
        filepath = canvas_dir / filename

        plotly_data = json.loads(obj.to_json())
        filepath.write_text(json.dumps(plotly_data, indent=2))

        return add_metadata({
            "type": "plotly",
            "file": filename,  # Relative to .canvas/ directory where canvas.md lives
            "data": plotly_data  # Keep for current session rendering
        })

    # PIL Image - save to file
    elif module.startswith('PIL') and 'Image' in obj_type:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"image_{timestamp}.png"
        filepath = canvas_dir / filename

        # Save to buffer first
        buf = io.BytesIO()
        obj.save(buf, format='PNG')
        buf.seek(0)
        img_data = buf.read()
        buf.close()

        # Write to file (virtual or physical)
        filepath.write_bytes(img_data)

        # Also store base64 for in-memory rendering
        img_base64 = base64.b64encode(img_data).decode('utf-8')

        return add_metadata({
            "type": "image",
            "file": filename,  # Relative to .canvas/ directory where canvas.md lives
            "data": img_base64  # Keep for current session rendering
        })

    # Plotly dict format - save to file
    elif isinstance(obj, dict) and ('data' in obj or 'layout' in obj):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"plotly_{timestamp}.json"
        filepath = canvas_dir / filename

        filepath.write_text(json.dumps(obj, indent=2))

        return add_metadata({
            "type": "plotly",
            "file": filename,  # Relative to .canvas/ directory where canvas.md lives
            "data": obj  # Keep for current session rendering
        })

    # String - could be a file path or markdown text
    elif isinstance(obj, str):
        # Check if it's a file path pointing to an asset — copy it into .canvas/
        copied = _maybe_copy_asset_to_canvas(obj, workspace_root, canvas_dir)
        if copied:
            return add_metadata(copied)

        # Check if it's a Mermaid diagram
        if re.search(r'```mermaid', obj, re.IGNORECASE):
            match = re.search(r'```mermaid\s*\n?(.*?)```', obj, re.DOTALL | re.IGNORECASE)
            if match:
                mermaid_code = match.group(1).strip()
                return add_metadata({
                    "type": "mermaid",
                    "data": mermaid_code
                })

        return add_metadata({
            "type": "markdown",
            "data": obj
        })

    # Unknown type - convert to string - keep inline
    else:
        return add_metadata({
            "type": "markdown",
            "data": f"```\n{str(obj)}\n```"
        })


def export_canvas_to_markdown(
    canvas_items: List[Dict],
    workspace_root: AnyRoot,
    output_path: str = None
) -> str:
    """Export canvas to markdown file with file references and metadata.

    Args:
        canvas_items: List of parsed canvas items
        workspace_root: Path to the workspace root directory (Path or VirtualFilesystem)
        output_path: Optional custom output path (relative to workspace_root/.canvas/)

    Returns:
        Path to the output file
    """
    # Ensure .canvas directory exists
    canvas_dir = _get_path(workspace_root, ".canvas")
    canvas_dir.mkdir(exist_ok=True)

    if not output_path:
        output_file = canvas_dir / "canvas.md"
    else:
        output_file = _get_path(workspace_root, output_path)

    lines = [
        "# Canvas Export",
        f"\n*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n",
    ]

    for i, parsed in enumerate(canvas_items):
        item_type = parsed.get("type", "unknown")
        item_id = parsed.get("id", f"item_{i}")
        created_at = parsed.get("created_at", "")

        # Add item metadata as HTML comment (for reload)
        metadata = {"id": item_id, "type": item_type}
        if created_at:
            metadata["created_at"] = created_at
        if "title" in parsed:
            metadata["title"] = parsed["title"]
        if "source_cell" in parsed:
            metadata["source_cell"] = parsed["source_cell"]
        if "execution_count" in parsed:
            metadata["execution_count"] = parsed["execution_count"]
        lines.append(f"\n<!-- canvas-item: {json.dumps(metadata)} -->")

        # Add title if present
        if "title" in parsed:
            lines.append(f"\n## {parsed['title']}\n")

        if item_type == "markdown":
            lines.append(f"\n{parsed.get('data', '')}\n")

        elif item_type == "section":
            level = max(1, min(int(parsed.get("level", 1)), 6))
            hashes = "#" * level
            lines.append(f"\n{hashes} {parsed.get('data', '')}\n")

        elif item_type == "mermaid":
            lines.append(f"\n```mermaid\n{parsed.get('data', '')}\n```\n")

        elif item_type == "dataframe":
            lines.append(f"\n{parsed.get('html', '')}\n")

        elif item_type == "matplotlib" or item_type == "image":
            # Reference the file instead of embedding base64
            file_ref = parsed.get("file", "")
            if file_ref:
                lines.append(f"\n![Image]({file_ref})\n")
            else:
                # Fallback to base64 if no file
                img_data = parsed.get("data", "")
                lines.append(f"\n![Chart {i+1}](data:image/png;base64,{img_data})\n")

        elif item_type == "html":
            # Reference the file
            file_ref = parsed.get("file", "")
            if file_ref:
                lines.append(f"\n```html\n{file_ref}\n```\n")
            else:
                lines.append(f"\n```html\n{parsed.get('data', '')}\n```\n")

        elif item_type == "plotly":
            # Reference the file
            file_ref = parsed.get("file", "")
            if file_ref:
                lines.append(f"\n```plotly\n{file_ref}\n```\n")
            else:
                # Fallback to inline
                lines.append(f"\n```json\n{json.dumps(parsed.get('data'), indent=2)}\n```\n")

    # Write to file
    output_file.write_text("\n".join(lines))
    return str(output_file)


def load_canvas_from_markdown(
    workspace_root: AnyRoot,
    markdown_path: str = None
) -> List[Dict]:
    """Load canvas from markdown file and referenced assets, preserving metadata.

    Args:
        workspace_root: Path to the workspace root directory (Path or VirtualFilesystem)
        markdown_path: Optional custom markdown file path

    Returns:
        List of parsed canvas items
    """
    if not markdown_path:
        canvas_md = _get_path(workspace_root, ".canvas/canvas.md")
    else:
        canvas_md = _get_path(workspace_root, markdown_path)

    if not canvas_md.exists():
        return []

    content = canvas_md.read_text()
    canvas_items = []

    # Get parent directory for loading referenced files
    canvas_dir = canvas_md.parent

    # First, find all metadata comments to get item boundaries and metadata
    metadata_pattern = r'<!-- canvas-item: ({.*?}) -->'
    metadata_matches = list(re.finditer(metadata_pattern, content))

    # If we have metadata comments, use them to parse items
    if metadata_matches:
        for i, match in enumerate(metadata_matches):
            try:
                metadata = json.loads(match.group(1))
            except json.JSONDecodeError:
                metadata = {"id": generate_canvas_id()}

            # Find the content between this metadata and the next (or end of file)
            start = match.end()
            if i + 1 < len(metadata_matches):
                end = metadata_matches[i + 1].start()
            else:
                end = len(content)

            item_content = content[start:end].strip()
            item = _parse_item_content(item_content, metadata, canvas_dir)
            if item:
                canvas_items.append(item)
    else:
        # Fallback: legacy parsing without metadata (backwards compatibility)
        canvas_items = _parse_legacy_canvas(content, canvas_dir)

    return canvas_items


def _parse_item_content(
    content: str,
    metadata: Dict,
    canvas_dir: AnyPath
) -> Optional[Dict]:
    """Parse a single item's content given its metadata."""
    item_type = metadata.get("type", "markdown")
    item = {
        "id": metadata.get("id", generate_canvas_id()),
        "type": item_type,
    }
    if "title" in metadata:
        item["title"] = metadata["title"]
    if "created_at" in metadata:
        item["created_at"] = metadata["created_at"]
    if "source_cell" in metadata:
        item["source_cell"] = metadata["source_cell"]
    if "execution_count" in metadata:
        item["execution_count"] = metadata["execution_count"]

    # Remove title heading if present (we already have it in metadata)
    if "title" in metadata:
        title_pattern = rf'^##\s*{re.escape(metadata["title"])}\s*\n?'
        content = re.sub(title_pattern, '', content, count=1).strip()

    if item_type == "mermaid":
        match = re.search(r'```mermaid\s*\n(.*?)```', content, re.DOTALL | re.IGNORECASE)
        if match:
            item["data"] = match.group(1).strip()
            return item

    elif item_type == "html":
        match = re.search(r'```html\s*\n(.*?)```', content, re.DOTALL)
        if match:
            ref_or_content = match.group(1).strip()
            # If it's a single-line filename, load the file
            if "\n" not in ref_or_content:
                file_path = canvas_dir / ref_or_content
                if file_path.exists():
                    item["file"] = ref_or_content
                    item["data"] = file_path.read_text(errors="replace")
                    return item
            # Otherwise treat as inline HTML
            item["data"] = ref_or_content
            return item

    elif item_type == "plotly":
        match = re.search(r'```plotly\s*\n([^\n]+)\n```', content)
        if match:
            file_ref = match.group(1).strip()
            file_path = canvas_dir / file_ref
            if file_path.exists():
                item["file"] = file_ref
                item["data"] = json.loads(file_path.read_text())
                return item

    elif item_type in ("matplotlib", "image"):
        match = re.search(r'!\[.*?\]\(([^)]+)\)', content)
        if match:
            file_ref = match.group(1)
            if not file_ref.startswith('data:'):
                file_path = canvas_dir / file_ref
                if file_path.exists():
                    img_data = file_path.read_bytes()
                    item["data"] = base64.b64encode(img_data).decode('utf-8')
                    item["file"] = file_ref
                    item["type"] = "image"  # Normalize type
                    return item

    elif item_type == "dataframe":
        match = re.search(r'<table.*?</table>', content, re.DOTALL)
        if match:
            item["html"] = match.group(0)
            return item

    elif item_type == "section":
        match = re.search(r'^(#{1,6})\s+(.+?)\s*$', content.strip(), re.MULTILINE)
        if match:
            item["level"] = len(match.group(1))
            item["data"] = match.group(2).strip()
            return item
        # Fallback: treat whole content as section text
        item["level"] = 1
        item["data"] = content.strip()
        return item

    elif item_type == "markdown":
        # Clean up the content
        cleaned = content.strip()
        if cleaned:
            item["data"] = cleaned
            return item

    return None


def _parse_legacy_canvas(content: str, canvas_dir: AnyPath) -> List[Dict]:
    """Parse canvas without metadata comments (legacy format)."""
    canvas_items = []
    code_blocks = []

    # Find all mermaid blocks
    for match in re.finditer(r'```mermaid\s*\n(.*?)```', content, re.DOTALL | re.IGNORECASE):
        code_blocks.append({
            'type': 'mermaid',
            'start': match.start(),
            'end': match.end(),
            'content': match.group(1).strip()
        })

    # Find all plotly blocks
    for match in re.finditer(r'```plotly\s*\n([^\n]+)\n```', content, re.DOTALL):
        code_blocks.append({
            'type': 'plotly_file',
            'start': match.start(),
            'end': match.end(),
            'content': match.group(1).strip()
        })

    # Find all image references
    for match in re.finditer(r'!\[.*?\]\(([^)]+)\)', content):
        file_ref = match.group(1)
        if not file_ref.startswith('data:'):
            code_blocks.append({
                'type': 'image_file',
                'start': match.start(),
                'end': match.end(),
                'content': file_ref
            })

    # Find all HTML tables
    for match in re.finditer(r'<table.*?</table>', content, re.DOTALL):
        code_blocks.append({
            'type': 'table',
            'start': match.start(),
            'end': match.end(),
            'content': match.group(0)
        })

    code_blocks.sort(key=lambda x: x['start'])

    last_pos = 0
    for block in code_blocks:
        if block['start'] > last_pos:
            markdown_text = content[last_pos:block['start']].strip()
            lines = [l for l in markdown_text.split('\n')
                     if l.strip() not in ['# Canvas Export', '']
                     and not l.strip().startswith('*Generated:')
                     and not l.strip().startswith('<!-- canvas-item:')]
            cleaned = '\n'.join(lines).strip()
            if cleaned:
                canvas_items.append({
                    "id": generate_canvas_id(),
                    "type": "markdown",
                    "data": cleaned
                })

        item = {"id": generate_canvas_id()}
        if block['type'] == 'mermaid':
            item["type"] = "mermaid"
            item["data"] = block['content']
            canvas_items.append(item)
        elif block['type'] == 'plotly_file':
            file_path = canvas_dir / block['content']
            if file_path.exists():
                item["type"] = "plotly"
                item["file"] = block['content']
                item["data"] = json.loads(file_path.read_text())
                canvas_items.append(item)
        elif block['type'] == 'image_file':
            file_path = canvas_dir / block['content']
            if file_path.exists():
                img_data = file_path.read_bytes()
                item["data"] = base64.b64encode(img_data).decode('utf-8')
                item["type"] = "image"
                item["file"] = block['content']
                canvas_items.append(item)
        elif block['type'] == 'table':
            item["type"] = "dataframe"
            item["html"] = block['content']
            canvas_items.append(item)

        last_pos = block['end']

    if last_pos < len(content):
        remaining = content[last_pos:].strip()
        if remaining:
            canvas_items.append({
                "id": generate_canvas_id(),
                "type": "markdown",
                "data": remaining
            })

    return canvas_items
