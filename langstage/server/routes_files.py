"""REST endpoints: /api/files/*."""

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel

from langstage.server.models import (
    FileContent,
    FileOpResult,
    FilePreview,
    FileTree,
)
from langstage.workspace.file_manager import FileManager


class PathRequest(BaseModel):
    path: str


def create_files_router(file_manager: FileManager) -> APIRouter:
    """Create the files router with the given FileManager."""
    r = APIRouter(prefix="/api/files")

    @r.get("/tree", response_model=FileTree, response_model_exclude_unset=True)
    async def get_tree(
        path: str = Query("/", description="Directory path relative to workspace"),
        depth: int = Query(1, description="Directory depth to load"),
    ):
        try:
            tree = file_manager.get_tree(path=path, depth=depth)
            return tree
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Path not found: {path}")
        except ValueError as e:
            # Path escapes the workspace — the boundary holds (no traversal), but
            # return a clean 400 instead of letting it fall through to a 500.
            raise HTTPException(status_code=400, detail=str(e))

    @r.get("/read", response_model=FileContent, response_model_exclude_unset=True)
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
        except ValueError as e:
            # Path escapes the workspace — boundary holds; return 400, not 500.
            raise HTTPException(status_code=400, detail=str(e))

    @r.get("/preview", response_model=FilePreview, response_model_exclude_unset=True)
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
        except ValueError as e:
            # Path escapes the workspace — boundary holds; return 400, not 500.
            raise HTTPException(status_code=400, detail=str(e))

    # Binary passthrough, not JSON: declare the real media type so the schema
    # does not advertise an (empty) application/json body (gh #98).
    @r.get(
        "/download",
        response_class=FileResponse,
        responses={200: {"content": {"application/octet-stream": {}}}},
    )
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

    @r.post("/upload", response_model=FileOpResult, response_model_exclude_unset=True)
    async def upload_file(
        path: str = Query(
            ...,
            description=(
                "Destination path relative to workspace. By DEFAULT this is the full target "
                "path — `upload?path=P` stores the file AT `P`, so `read?path=P` round-trips, "
                "symmetric with read/preview/download/delete/mkdir. To drop the upload INTO a "
                "directory under its own multipart filename, end `path` with '/' or point it "
                "at an existing directory."
            ),
        ),
        file: UploadFile = File(...),
    ):
        """Upload a file to the workspace.

        `path` is the full destination path by default, so it round-trips with the other
        files routes (`upload?path=reports/q3.md` → `read?path=reports/q3.md`). Previously
        `path` was always treated as a *parent directory* and the multipart filename was
        appended, which silently misplaced a `path`-symmetric client's file at
        `P/<filename>` and broke the round-trip (gh #75). The directory-drop mode is still
        available explicitly: a trailing '/' or an existing-directory `path` appends the
        multipart filename (this is what the file-browser UI uses — it uploads into the
        directory being viewed).
        """
        try:
            drop_into_dir = path.endswith("/") or file_manager.get_absolute_path(path).is_dir()
            dest = (path.rstrip("/") + "/" + file.filename) if drop_into_dir else path
            content = await file.read()
            result = file_manager.save_upload(dest, content)
            return result
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @r.post("/mkdir", response_model=FileOpResult, response_model_exclude_unset=True)
    async def create_folder(body: PathRequest):
        """Create a new directory in the workspace."""
        try:
            result = file_manager.create_directory(body.path)
            return result
        except FileExistsError:
            raise HTTPException(status_code=409, detail=f"Already exists: {body.path}")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    def _delete(target: str):
        try:
            return file_manager.delete_path(target)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Not found: {target}")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @r.post("/delete", response_model=FileOpResult, response_model_exclude_unset=True)
    async def delete_path(
        path: str | None = Query(
            None,
            description="File/dir path relative to workspace. Query form is symmetric "
            'with read/download/upload (so delete?path=P round-trips); a JSON body '
            '{"path": ...} also works.',
        ),
        body: PathRequest | None = None,
    ):
        """Delete a file or directory. Accepts ``path`` as a **query** parameter —
        ``delete?path=P``, symmetric with read/download/upload so the documented
        round-trip holds — or a JSON body ``{"path": ...}`` (used by the file
        browser UI). (gh #81)"""
        target = path if path is not None else (body.path if body else None)
        if not target:
            raise HTTPException(
                status_code=422,
                detail='Provide `path` as a query parameter or a JSON body {"path": ...}.',
            )
        return _delete(target)

    @r.delete("/delete", response_model=FileOpResult, response_model_exclude_unset=True)
    async def delete_path_verb(
        path: str = Query(..., description="File/dir path relative to workspace."),
    ):
        """``DELETE /api/files/delete?path=P`` — the natural REST verb, symmetric
        with the other files routes. (gh #81)"""
        return _delete(path)

    return r
