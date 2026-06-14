"""Tests for the durable SqliteTaskStore.

The in-memory store's atomic-claim guarantee (an asyncio.Lock) does NOT transfer
to SQLite, so the claim atomicity + durability are proven here independently.
"""
import asyncio

from langgraph_stream_parser.tasks.state import DONE, ONGOING, QUEUED
from langgraph_stream_parser.tasks.store import now_iso
from langstage.tasks import SqliteTaskStore


def _row(task_id, *, state=QUEUED, created_at=None, parent_id=None):
    return {
        "task_id": task_id,
        "parent_id": parent_id,
        "title": task_id,
        "prompt": "do",
        "agent_spec": None,
        "state": state,
        "thread_id": f"task-{task_id}",
        "created_at": created_at or now_iso(),
        "started_at": None,
        "finished_at": None,
        "result": None,
        "artifacts": None,
        "error": None,
        "interrupt": None,
    }


async def test_create_get_roundtrip_with_json_columns(tmp_path):
    store = SqliteTaskStore(tmp_path / "t.db")
    await store.setup()
    try:
        row = _row("a")
        row["artifacts"] = ["out.csv", "plot.png"]
        row["interrupt"] = {"type": "interrupt", "action_requests": [{"tool": "bash"}]}
        await store.create(row)
        got = await store.get("a")
        assert got["artifacts"] == ["out.csv", "plot.png"]      # JSON round-trips
        assert got["interrupt"]["action_requests"][0]["tool"] == "bash"
        assert got["thread_id"] == "task-a"
    finally:
        await store.close()


async def test_claim_is_atomic_and_fifo(tmp_path):
    store = SqliteTaskStore(tmp_path / "t.db")
    await store.setup()
    try:
        await store.create(_row("a", created_at="2026-01-01T00:00:00+00:00"))
        await store.create(_row("b", created_at="2026-01-01T00:00:01+00:00"))
        c1, c2 = await asyncio.gather(store.claim_next(), store.claim_next())
        assert {c1["task_id"], c2["task_id"]} == {"a", "b"}   # no double-claim
        assert c1["task_id"] == "a"                            # FIFO
        assert all(c["state"] == ONGOING for c in (c1, c2))
        assert await store.claim_next() is None
    finally:
        await store.close()


async def test_durable_across_reopen(tmp_path):
    path = tmp_path / "t.db"
    s1 = SqliteTaskStore(path)
    await s1.setup()
    await s1.create(_row("x", state=DONE))
    await s1.update("x", result="the answer")
    await s1.close()

    s2 = SqliteTaskStore(path)   # simulate a process restart
    await s2.setup()
    try:
        got = await s2.get("x")
        assert got is not None and got["state"] == DONE
        assert got["result"] == "the answer"
    finally:
        await s2.close()


async def test_requeue_orphans(tmp_path):
    store = SqliteTaskStore(tmp_path / "t.db")
    await store.setup()
    try:
        await store.create(_row("running", state=ONGOING))
        await store.create(_row("finished", state=DONE))
        n = await store.requeue_orphans()
        assert n == 1
        assert (await store.get("running"))["state"] == QUEUED
        assert (await store.get("finished"))["state"] == DONE
    finally:
        await store.close()


async def test_list_filters(tmp_path):
    store = SqliteTaskStore(tmp_path / "t.db")
    await store.setup()
    try:
        await store.create(_row("p", state=DONE))
        await store.create(_row("c", parent_id="p"))
        assert {t["task_id"] for t in await store.list(state=DONE)} == {"p"}
        assert {t["task_id"] for t in await store.list(parent_id="p")} == {"c"}
        assert len(await store.list()) == 2
    finally:
        await store.close()


async def test_events_append_get_order(tmp_path):
    store = SqliteTaskStore(tmp_path / "t.db")
    await store.setup()
    try:
        await store.append_events("a", [{"type": "content", "content": "hi"}, {"type": "complete"}])
        await store.append_events("a", [{"type": "x"}])
        assert [e["type"] for e in await store.get_events("a")] == ["content", "complete", "x"]
        assert await store.get_events("missing") == []
    finally:
        await store.close()


async def test_events_durable_across_reopen(tmp_path):
    path = tmp_path / "t.db"
    s1 = SqliteTaskStore(path)
    await s1.setup()
    await s1.append_events("a", [{"type": "content", "content": "x"}, {"type": "complete"}])
    await s1.close()

    s2 = SqliteTaskStore(path)
    await s2.setup()
    try:
        assert len(await s2.get_events("a")) == 2
    finally:
        await s2.close()


async def test_update_rejects_unknown_column(tmp_path):
    import pytest

    store = SqliteTaskStore(tmp_path / "t.db")
    await store.setup()
    try:
        await store.create(_row("a"))
        with pytest.raises(ValueError):
            await store.update("a", bogus_column="x")
    finally:
        await store.close()
