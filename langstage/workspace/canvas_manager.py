"""File-backed canvas reader. All state lives in .canvas/canvas.md."""

from pathlib import Path
from typing import Optional

from langstage.canvas import load_canvas_from_markdown, export_canvas_to_markdown


class CanvasManager:
    """Reads and writes canvas items from .canvas/canvas.md.

    No in-memory state — every read goes to the file so the UI
    always reflects the latest content.
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace

    def get_items(self) -> list[dict]:
        """Read all canvas items from .canvas/canvas.md."""
        return load_canvas_from_markdown(self.workspace)

    def get_asset_path(self, filename: str) -> Optional[Path]:
        """Return the absolute path to an asset in .canvas/, or None."""
        # Prevent directory traversal
        if ".." in filename or filename.startswith("/"):
            return None
        path = self.workspace / ".canvas" / filename
        if path.resolve().is_relative_to((self.workspace / ".canvas").resolve()) and path.is_file():
            return path
        return None

    def remove_item(self, item_id: str) -> None:
        """Remove an item by ID and rewrite the file."""
        items = load_canvas_from_markdown(self.workspace)
        filtered = [item for item in items if item.get("id") != item_id]
        if len(filtered) == len(items):
            raise KeyError(f"Item not found: {item_id}")
        export_canvas_to_markdown(filtered, self.workspace)

    def clear(self) -> None:
        """Remove all canvas items."""
        canvas_md = self.workspace / ".canvas" / "canvas.md"
        if canvas_md.exists():
            canvas_md.unlink()

    def export_markdown(self) -> str:
        """Return the raw .canvas/canvas.md content."""
        canvas_md = self.workspace / ".canvas" / "canvas.md"
        if canvas_md.exists():
            return canvas_md.read_text()
        return ""
