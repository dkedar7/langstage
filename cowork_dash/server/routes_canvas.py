"""REST endpoints: /api/canvas/*."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from cowork_dash.workspace.canvas_manager import CanvasManager


def create_canvas_router(canvas_manager: CanvasManager) -> APIRouter:
    """Create the canvas router with the given CanvasManager."""
    r = APIRouter(prefix="/api/canvas")

    @r.get("/items")
    async def list_items():
        return canvas_manager.get_items()

    @r.get("/assets/{filename:path}")
    async def get_asset(filename: str):
        """Serve a file from the .canvas/ directory."""
        path = canvas_manager.get_asset_path(filename)
        if path is None:
            raise HTTPException(status_code=404, detail=f"Asset not found: {filename}")
        return FileResponse(str(path))

    @r.delete("/items/{item_id}")
    async def delete_item(item_id: str):
        try:
            canvas_manager.remove_item(item_id)
            return {"status": "ok"}
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Item not found: {item_id}")

    @r.delete("/items")
    async def clear_items():
        canvas_manager.clear()
        return {"status": "ok"}

    @r.get("/export")
    async def export_markdown():
        return {"content": canvas_manager.export_markdown()}

    return r
