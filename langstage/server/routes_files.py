"""REST endpoints: /api/files/*."""

import errno
import logging

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel

from langstage.server.models import (
    FileContent,
    FileOpResult,
    FilePreview,
    FileTree,
)
from langstage.workspace.file_manager import BinaryFileError, FileManager


logger = logging.getLogger(__name__)

# Windows error codes for a bad path. Windows reports a name that's too long as
# ERROR_FILENAME_EXCED_RANGE and a name with characters like ':' or '<' as
# ERROR_INVALID_NAME (or ERROR_DIRECTORY from mkdir), not ENAMETOOLONG.
_WIN_NAME_TOO_LONG = 206
_WIN_INVALID_NAME = (123, 267)  # ERROR_INVALID_NAME, ERROR_DIRECTORY


class PathRequest(BaseModel):
    path: str


def _shown(path: str, limit: int = 80) -> str:
    return path if len(path) <= limit else path[:limit] + "…"


def _os_error(e: OSError, path: str) -> HTTPException:
    """A 4xx for an OS error on ``path``, instead of a bare 500 (gh #228).

    The detail names the workspace path the client sent, never the server's
    absolute path, which the OS puts in ``str(e)``. An error our own code raised
    (no errno) already has a workspace-relative message, so it's kept.
    """
    shown = _shown(path)
    winerror = getattr(e, "winerror", None)
    too_long = any(len(part.encode()) > 255 for part in path.replace("\\", "/").split("/"))
    if e.errno == errno.ENAMETOOLONG or winerror == _WIN_NAME_TOO_LONG:
        return HTTPException(status_code=400, detail=f"Invalid path, name too long: {shown}")
    if winerror in _WIN_INVALID_NAME or e.errno == errno.EINVAL:
        # Windows reports both a bad character and an over-long name this way.
        reason = "name too long" if too_long else "not a valid file name"
        return HTTPException(status_code=400, detail=f"Invalid path, {reason}: {shown}")
    if isinstance(e, NotADirectoryError):
        detail = str(e) if e.errno is None else f"Not a directory: {shown}"
        return HTTPException(status_code=400, detail=detail)
    if isinstance(e, IsADirectoryError):
        return HTTPException(status_code=400, detail=f"Path is a directory: {shown}")
    if isinstance(e, FileNotFoundError):
        return HTTPException(status_code=404, detail=f"Not found: {shown}")
    if isinstance(e, FileExistsError):
        return HTTPException(status_code=409, detail=f"Already exists: {shown}")
    if isinstance(e, PermissionError) or e.errno == errno.EROFS:
        return HTTPException(status_code=403, detail=f"Permission denied: {shown}")
    if e.errno in (errno.ENOSPC, getattr(errno, "EDQUOT", None)):
        return HTTPException(status_code=507, detail="Not enough space in the workspace")
    logger.warning("File operation on %r failed: %s", path, e)
    return HTTPException(status_code=500, detail=f"File system error: {e.strerror or e}")


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
        except NotADirectoryError as e:
            # A FILE was passed where a directory is expected — the mirror-image of
            # read/preview's IsADirectoryError guard. Return a clean 400 instead of
            # letting it fall through to a 500 (gh #117).
            raise HTTPException(status_code=400, detail=str(e))
        except ValueError as e:
            # Path escapes the workspace — the boundary holds (no traversal), but
            # return a clean 400 instead of letting it fall through to a 500.
            raise HTTPException(status_code=400, detail=str(e))
        except OSError as e:
            raise _os_error(e, path)

    @r.get(
        "/read",
        response_model=FileContent,
        response_model_exclude_unset=True,
        responses={415: {"description": "Not a UTF-8 text file; use /preview or /download"}},
    )
    async def read_file(
        path: str = Query(..., description="File path relative to workspace"),
    ):
        """Return a UTF-8 text file verbatim (line endings intact); ``size`` is in bytes.

        A binary (non-UTF-8, or containing NUL) file gets 415 instead of lossily
        decoded text; read it through ``/preview`` or ``/download``. (gh #144)
        """
        try:
            content = file_manager.read_file(path)
            return content
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"File not found: {path}")
        except IsADirectoryError:
            raise HTTPException(status_code=400, detail=f"Path is a directory: {path}")
        except BinaryFileError as e:
            raise HTTPException(status_code=415, detail=str(e))
        except ValueError as e:
            # Path escapes the workspace — boundary holds; return 400, not 500.
            raise HTTPException(status_code=400, detail=str(e))
        except OSError as e:
            raise _os_error(e, path)

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
        except OSError as e:
            raise _os_error(e, path)

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
            # Distinguish "exists but is a directory" (400) from "doesn't exist" (404),
            # instead of collapsing both into a misleading 404 "File not found" for a
            # directory that plainly exists. Mirrors read/preview's IsADirectoryError -> 400
            # and the #117 tree-on-a-file fix — download was the last files route to
            # misreport a node type (gh #124).
            if abs_path.is_dir():
                raise HTTPException(status_code=400, detail=f"Path is a directory: {path}")
            if not abs_path.is_file():
                raise HTTPException(status_code=404, detail=f"File not found: {path}")
            return FileResponse(str(abs_path), filename=abs_path.name)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OSError as e:
            raise _os_error(e, path)

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
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OSError as e:
            # The OS message named the server's absolute path. (gh #228)
            raise _os_error(e, path)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @r.post("/mkdir", response_model=FileOpResult, response_model_exclude_unset=True)
    async def create_folder(
        path: str | None = Query(
            None,
            description="Directory path relative to workspace. Query form is symmetric "
            'with read/download/upload/delete (mkdir?path=P); a JSON body {"path": ...} '
            "also works.",
        ),
        body: PathRequest | None = None,
    ):
        """Create a new directory in the workspace. Accepts ``path`` as a **query**
        parameter (``mkdir?path=P``, as the upload docs and README advertise) or a JSON
        body ``{"path": ...}`` (used by the file browser UI). It used to take only the
        body, so the advertised query form got a 422 (gh #159)."""
        target = path if path is not None else (body.path if body else None)
        if not target:
            raise HTTPException(
                status_code=422,
                detail='Provide `path` as a query parameter or a JSON body {"path": ...}.',
            )
        try:
            result = file_manager.create_directory(target)
            return result
        except FileExistsError:
            raise HTTPException(status_code=409, detail=f"Already exists: {target}")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OSError as e:
            raise _os_error(e, target)

    def _delete(target: str):
        try:
            return file_manager.delete_path(target)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Not found: {target}")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OSError as e:
            raise _os_error(e, target)

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
