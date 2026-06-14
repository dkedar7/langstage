"""Contract tests for the /api/tasks REST router.

Wires a real TaskRunner + SqliteTaskStore + SessionAdapter (fake agent) behind
the router and drives it over HTTP. (httpx ASGITransport doesn't fire lifespan,
so the store/runner are set up explicitly here rather than via app startup.)
"""
import asyncio

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from langgraph_stream_parser.adapters import SessionAdapter
from langgraph_stream_parser.tasks import TaskRunner
from langgraph_stream_parser.tasks.state import DONE
from langstage.server.routes_tasks import create_tasks_router
from langstage.tasks import SqliteTaskStore

from .test_streaming import FakeStreamingAgent


async def _wait(store, task_id, target, timeout=4.0):
    loop = asyncio.get_event_loop()
    end = loop.time() + timeout
    last = None
    while loop.time() < end:
        last = await store.get(task_id)
        if last and last["state"] == target:
            return last
        await asyncio.sleep(0.02)
    raise AssertionError(f"{task_id} never reached {target}; last={last}")


@pytest.fixture
async def ctx(tmp_path):
    store = SqliteTaskStore(tmp_path / "tasks.db")
    await store.setup()
    adapter = SessionAdapter(graph=FakeStreamingAgent(chunks=["all ", "done"]))
    runner = TaskRunner(adapter, store, concurrency=2, poll_interval=0.05)
    await runner.start()
    app = FastAPI()
    app.include_router(create_tasks_router(runner, store))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        yield client, store
    await runner.shutdown()
    await store.close()


async def test_create_runs_and_completes(ctx):
    client, store = ctx
    r = await client.post("/api/tasks", json={"prompt": "say hi", "title": "greet"})
    assert r.status_code == 201
    body = r.json()
    tid = body["task_id"]
    assert body["state"] in ("queued", "ongoing", "done")

    row = await _wait(store, tid, DONE)
    assert row["result"]  # final text captured

    # GET single + list reflect it
    g = await client.get(f"/api/tasks/{tid}")
    assert g.status_code == 200 and g.json()["state"] == "done"
    listed = await client.get("/api/tasks")
    assert any(t["task_id"] == tid for t in listed.json())


async def test_list_filter_by_state(ctx):
    client, store = ctx
    r = await client.post("/api/tasks", json={"prompt": "x"})
    tid = r.json()["task_id"]
    await _wait(store, tid, DONE)
    done = await client.get("/api/tasks", params={"state": "done"})
    assert all(t["state"] == "done" for t in done.json())
    assert any(t["task_id"] == tid for t in done.json())


async def test_get_unknown_404(ctx):
    client, _ = ctx
    assert (await client.get("/api/tasks/nope")).status_code == 404


async def test_create_requires_prompt(ctx):
    client, _ = ctx
    r = await client.post("/api/tasks", json={"prompt": "   "})
    assert r.status_code == 400


async def test_cancel_unknown_400(ctx):
    client, _ = ctx
    assert (await client.post("/api/tasks/nope/cancel")).status_code == 400


async def test_retry_done_task_is_400(ctx):
    client, store = ctx
    r = await client.post("/api/tasks", json={"prompt": "x"})
    tid = r.json()["task_id"]
    await _wait(store, tid, DONE)
    # a completed task is not retryable
    assert (await client.post(f"/api/tasks/{tid}/retry")).status_code == 400
