"""REST endpoints for the async task board (Tasks/Board tab).

Reads come from the durable store; mutations go through the TaskRunner so the
worker pool and state machine stay authoritative. Approve/reject (the HITL
review gate) land in Slice 2.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from langgraph_stream_parser.tasks import TaskRunner
from langgraph_stream_parser.tasks.store import TaskStore


class TaskCreate(BaseModel):
    prompt: str
    title: Optional[str] = None
    agent_spec: Optional[str] = None
    parent_id: Optional[str] = None


def create_tasks_router(runner: TaskRunner, store: TaskStore) -> APIRouter:
    router = APIRouter(prefix="/api/tasks", tags=["tasks"])

    @router.get("")
    async def list_tasks(state: Optional[str] = None, parent_id: Optional[str] = None):
        return await store.list(state=state, parent_id=parent_id)

    @router.get("/{task_id}")
    async def get_task(task_id: str):
        task = await store.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    @router.post("", status_code=201)
    async def create_task(body: TaskCreate):
        try:
            task_id = await runner.enqueue(
                title=body.title or body.prompt,
                prompt=body.prompt,
                agent_spec=body.agent_spec,
                parent_id=body.parent_id,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return await store.get(task_id)

    @router.post("/{task_id}/cancel")
    async def cancel_task(task_id: str):
        if not await runner.cancel(task_id):
            raise HTTPException(status_code=400, detail="Task not found or already finished")
        return {"ok": True}

    @router.post("/{task_id}/retry")
    async def retry_task(task_id: str):
        if not await runner.retry(task_id):
            raise HTTPException(status_code=400, detail="Task not found or not retryable")
        return {"ok": True}

    return router
