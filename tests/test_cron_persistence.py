"""Schedules survive a server restart (gh #151).

Before this, cron jobs lived only in ``CronScheduler._jobs`` and were silently lost
on any restart, while the task board they enqueue onto persisted in
``<workspace>/.langstage/tasks.db``. Schedules now live in a ``cron_jobs`` table in
that same database and are reloaded (and restarted) when the server comes back up.
"""
import sqlite3
from typing import TypedDict

from fastapi.testclient import TestClient
from langgraph.graph import END, START, StateGraph

from langstage.app import CoworkApp
from langstage.scheduler import CronScheduler
from langstage.tasks import SqliteCronStore


class _S(TypedDict):
    x: int


def _graph():
    g = StateGraph(_S)
    g.add_node("n", lambda s: {"x": s.get("x", 0) + 1})
    g.add_edge(START, "n")
    g.add_edge("n", END)
    return g.compile()


def _server(ws):
    return TestClient(CoworkApp(agent=_graph(), workspace=str(ws)).create_server())


def test_schedule_survives_a_server_restart(tmp_path):
    """The issue's repro: one task + one schedule, restart against the same
    workspace — both must still be there (only the task survived before)."""
    with _server(tmp_path) as c:  # `with` drives lifespan (store setup, scheduler start)
        assert c.post("/api/tasks", json={"prompt": "my task"}).status_code in (200, 201)
        r = c.post("/api/cron", json={"name": "nightly", "cron": "0 9 * * *", "prompt": "run nightly"})
        assert r.status_code == 201, r.text
        created = r.json()
        gone = c.post("/api/cron", json={"name": "doomed", "cron": "*/5 * * * *", "prompt": "x"}).json()
        assert c.delete(f"/api/cron/{gone['id']}").status_code == 200

    with _server(tmp_path) as c:  # restart
        assert len(c.get("/api/tasks").json()) == 1
        jobs = c.get("/api/cron").json()
    assert [j["id"] for j in jobs] == [created["id"]]  # the deleted one stays deleted
    job = jobs[0]
    for key in ("name", "cron", "prompt", "created_at", "created_by", "session_id"):
        assert job[key] == created[key]
    assert job["next_run"]  # recomputed from the cron expression on load

    # Persisted alongside the task board, not in a separate file.
    with sqlite3.connect(tmp_path / ".langstage" / "tasks.db") as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"tasks", "cron_jobs"} <= tables


class _Runner:
    def __init__(self):
        self.n = 0

    async def enqueue(self, *, title, prompt, agent_spec=None, parent_id=None):
        self.n += 1
        return f"task-{self.n}"


async def test_run_stats_persist_and_reload(tmp_path):
    """last_run / last_status / run_count / last_task_id are saved on each fire, so
    overlap protection (gh #78) still knows the previous run after a restart."""
    store = SqliteCronStore(tmp_path / "t.db")
    s = CronScheduler(_Runner(), store=store)
    job = s.add_job(name="n", cron="0 9 * * *", prompt="p", created_by="agent")
    await s.run_now(job.id)

    reloaded = CronScheduler(_Runner(), store=SqliteCronStore(tmp_path / "t.db")).get(job.id)
    assert reloaded is not None
    assert reloaded.created_by == "agent"
    assert reloaded.run_count == 1
    assert reloaded.last_status == "queued"
    assert reloaded.last_task_id == "task-1"
    assert reloaded.last_run == job.last_run


def test_store_is_optional_and_invalid_rows_are_skipped(tmp_path):
    # No store → the old in-memory behavior, nothing written anywhere.
    s = CronScheduler(_Runner())
    s.add_job(name="n", cron="0 9 * * *", prompt="p")
    assert len(s.list_jobs()) == 1

    # A stored row whose cron no longer validates is skipped on load, not fatal.
    store = SqliteCronStore(tmp_path / "t.db")
    good = CronScheduler(_Runner(), store=store).add_job(name="ok", cron="0 9 * * *", prompt="p")
    with sqlite3.connect(tmp_path / "t.db") as db:
        db.execute(
            "INSERT INTO cron_jobs (id, name, cron, prompt, created_at) VALUES (?, ?, ?, ?, ?)",
            ("bad1", "bad", "0 0 9 * * *", "p", "2026-01-01T00:00:00+00:00"),
        )
    ids = [j["id"] for j in CronScheduler(_Runner(), store=SqliteCronStore(tmp_path / "t.db")).list_jobs()]
    assert ids == [good.id]
