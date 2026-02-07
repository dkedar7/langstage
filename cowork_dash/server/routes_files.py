"""REST endpoints: /api/files/*."""

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel

from cowork_dash.workspace.file_manager import FileManager


class PathRequest(BaseModel):
    path: str


def create_files_router(file_manager: FileManager) -> APIRouter:
    """Create the files router with the given FileManager."""
    r = APIRouter(prefix="/api/files")

    @r.get("/tree")
    async def get_tree(
        path: str = Query("/", description="Directory path relative to workspace"),
        depth: int = Query(1, description="Directory depth to load"),
    ):
        try:
            tree = file_manager.get_tree(path=path, depth=depth)
            return tree
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Path not found: {path}")

    @r.get("/read")
    async def read_file(
        path: str = Query(..., description="File path relative to workspace"),
    ):
        try:
            content = file_manager.read_file(path)
            return content
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"File not found: {path}")
        except IsADirectoryError:
            raise HTTPException(status_code=400, detail=f"Path is a directory: {path}")

    @r.get("/preview")
    async def preview_file(
        path: str = Query(..., description="File path relative to workspace"),
    ):
        """Return structured preview data for any file type."""
        try:
            return file_manager.preview_file(path)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"File not found: {path}")
        except IsADirectoryError:
            raise HTTPException(status_code=400, detail=f"Path is a directory: {path}")

    @r.get("/download")
    async def download_file(
        path: str = Query(..., description="File path relative to workspace"),
    ):
        """Serve a file for download."""
        try:
            abs_path = file_manager.get_absolute_path(path)
            if not abs_path.is_file():
                raise HTTPException(status_code=404, detail=f"File not found: {path}")
            return FileResponse(str(abs_path), filename=abs_path.name)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @r.post("/upload")
    async def upload_file(
        path: str = Query(..., description="Destination dir relative to workspace"),
        file: UploadFile = File(...),
    ):
        """Upload a file to the workspace."""
        try:
            dest = path.rstrip("/") + "/" + file.filename
            content = await file.read()
            result = file_manager.save_upload(dest, content)
            return result
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @r.post("/mkdir")
    async def create_folder(body: PathRequest):
        """Create a new directory in the workspace."""
        try:
            result = file_manager.create_directory(body.path)
            return result
        except FileExistsError:
            raise HTTPException(status_code=409, detail=f"Already exists: {body.path}")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @r.post("/delete")
    async def delete_path(body: PathRequest):
        """Delete a file or directory."""
        try:
            result = file_manager.delete_path(body.path)
            return result
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Not found: {body.path}")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    return r
