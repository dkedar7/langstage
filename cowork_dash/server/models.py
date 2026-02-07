"""Pydantic request/response schemas for REST endpoints."""

from pydantic import BaseModel


class FileEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int | None = None
    children: list["FileEntry"] | None = None


class FileTree(BaseModel):
    entries: list[FileEntry]
    root: str


class FileContent(BaseModel):
    content: str
    language: str
    size: int
    path: str


class CanvasItemResponse(BaseModel):
    id: str
    type: str
    title: str
    data: dict
    created_at: str


class AppConfigResponse(BaseModel):
    title: str
    subtitle: str
    welcome_message: str
    theme: str
    workspace_name: str
