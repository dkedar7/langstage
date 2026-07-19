"""REST endpoints: /api/canvas/*."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from langstage.server.models import CanvasExport, CanvasItemResponse, StatusResponse
from langstage.workspace.canvas_manager import CanvasManager


def create_canvas_router(canvas_manager: CanvasManager) -> APIRouter:
    """Create the canvas router with the given CanvasManager."""
    r = APIRouter(prefix="/api/canvas")

    @r.get("/items", response_model=list[CanvasItemResponse], response_model_exclude_unset=True)
    async def list_items():
        return canvas_manager.get_items()

    @r.get(
        "/assets/{filename:path}",
        response_class=FileResponse,
        responses={200: {"content": {"application/octet-stream": {}}}},
    )
    async def get_asset(filename: str):
        """Serve a file from the .canvas/ directory."""
        path = canvas_manager.get_asset_path(filename)
        if path is None:
            raise HTTPException(status_code=404, detail=f"Asset not found: {filename}")
        return FileResponse(str(path))

    @r.delete("/items/{item_id}", response_model=StatusResponse, response_model_exclude_unset=True)
    async def delete_item(item_id: str):
        try:
            canvas_manager.remove_item(item_id)
            return {"status": "ok"}
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Item not found: {item_id}")

    @r.delete("/items", response_model=StatusResponse, response_model_exclude_unset=True)
    async def clear_items():
        canvas_manager.clear()
        return {"status": "ok"}

    @r.get("/export", response_model=CanvasExport, response_model_exclude_unset=True)
    async def export_markdown():
        return {"content": canvas_manager.export_markdown()}

    return r
