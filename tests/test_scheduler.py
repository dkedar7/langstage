"""Tests for the in-memory cron scheduler + agent tools."""
import asyncio

import pytest

from cowork_dash.scheduler import (
    CronScheduler,
    validate_cron,
    set_scheduler,
    schedule_run,
    list_scheduled_runs,
    cancel_scheduled_run,
)


class FakeSession:
    def __init__(self):
        self.current_task = None
        self.sse_connected = False
        self.event_queue = asyncio.Queue()


class FakeAdapter:
    """Records submit_message calls; returns a headless session."""

    def __init__(self):
        self.calls = []

    def submit_message(self, session_id, content, *, context_parts=None):
        self.calls.append(
            {"session_id": session_id, "content": content, "context_parts": context_parts}
        )
        return FakeSession()


# ── cron validation ──────────────────────────────────────────────────


def test_validate_cron_accepts_valid():
    validate_cron("*/5 * * * *")
    validate_cron("0 9 * * 1-5")


def test_validate_cron_rejects_invalid():
    with pytest.raises(ValueError):
        validate_cron("not a cron")
    with pytest.raises(ValueError):
        validate_cron("* * * *")  # only 4 fields


# ── add / list / remove ──────────────────────────────────────────────


def test_add_list_remove():
    s = CronScheduler(FakeAdapter())
    job = s.add_job(name="daily report", cron="0 9 * * *", prompt="write the report")
    assert job.id
    assert job.created_by == "user"

    jobs = s.list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["session_id"] == f"cron-{job.id}"
    assert jobs[0]["next_run"]  # computed even before start()

    assert s.remove_job(job.id) is True
    assert s.list_jobs() == []
    assert s.remove_job("missing") is False


def test_add_job_validates():
    s = CronScheduler(FakeAdapter())
    with pytest.raises(ValueError):
        s.add_job(name="x", cron="nope", prompt="p")
    with pytest.raises(ValueError):
        s.add_job(name="  ", cron="* * * * *", prompt="p")
    with pytest.raises(ValueError):
        s.add_job(name="x", cron="* * * * *", prompt="")


# ── firing ───────────────────────────────────────────────────────────


async def test_fire_runs_agent_on_its_own_session():
    adapter = FakeAdapter()
    s = CronScheduler(adapter)
    job = s.add_job(name="j", cron="* * * * *", prompt="do it")

    await s._fire(job)

    assert len(adapter.calls) == 1
    assert adapter.calls[0]["session_id"] == f"cron-{job.id}"
    assert adapter.calls[0]["content"] == "do it"
    assert any("Scheduled run" in p for p in adapter.calls[0]["context_parts"])
    assert job.last_status == "ok"
    assert job.run_count == 1
    assert job.last_run


async def test_run_now():
    adapter = FakeAdapter()
    s = CronScheduler(adapter)
    job = s.add_job(name="j", cron="* * * * *", prompt="p")
    assert await s.run_now(job.id) is True
    assert await s.run_now("missing") is False
    assert len(adapter.calls) == 1


# ── agent tools ──────────────────────────────────────────────────────


def test_tools_schedule_list_cancel():
    s = CronScheduler(FakeAdapter())
    set_scheduler(s)
    try:
        out = schedule_run.invoke({"name": "nightly", "cron": "0 0 * * *", "prompt": "summarize"})
        assert "Scheduled 'nightly'" in out
        assert len(s.list_jobs()) == 1

        assert "nightly" in list_scheduled_runs.invoke({})

        job_id = s.list_jobs()[0]["id"]
        assert "Cancelled" in cancel_scheduled_run.invoke({"job_id": job_id})
        assert s.list_jobs() == []
    finally:
        set_scheduler(None)


def test_tool_reports_invalid_cron():
    s = CronScheduler(FakeAdapter())
    set_scheduler(s)
    try:
        out = schedule_run.invoke({"name": "x", "cron": "bad", "prompt": "p"})
        assert "Could not schedule" in out
        assert s.list_jobs() == []
    finally:
        set_scheduler(None)


def test_tool_unavailable_without_scheduler():
    set_scheduler(None)
    out = schedule_run.invoke({"name": "x", "cron": "* * * * *", "prompt": "p"})
    assert "unavailable" in out.lower()
