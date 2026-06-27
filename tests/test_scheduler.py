"""Tests for the in-memory cron scheduler + agent tools."""
import asyncio

import pytest

from langstage.scheduler import (
    CronScheduler,
    validate_cron,
    set_scheduler,
    schedule_run,
    list_scheduled_runs,
    cancel_scheduled_run,
)


class FakeRunner:
    """Records enqueue calls (the scheduler is now a producer onto the runner)."""

    def __init__(self):
        self.enqueued = []

    async def enqueue(self, *, title, prompt, agent_spec=None, parent_id=None):
        self.enqueued.append(
            {"title": title, "prompt": prompt, "agent_spec": agent_spec, "parent_id": parent_id}
        )
        return "task-fake"


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
    s = CronScheduler(FakeRunner())
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
    s = CronScheduler(FakeRunner())
    with pytest.raises(ValueError):
        s.add_job(name="x", cron="nope", prompt="p")
    with pytest.raises(ValueError):
        s.add_job(name="  ", cron="* * * * *", prompt="p")
    with pytest.raises(ValueError):
        s.add_job(name="x", cron="* * * * *", prompt="")


# ── firing ───────────────────────────────────────────────────────────


async def test_fire_enqueues_onto_runner():
    runner = FakeRunner()
    s = CronScheduler(runner)
    job = s.add_job(name="j", cron="* * * * *", prompt="do it")

    await s._fire(job)

    assert len(runner.enqueued) == 1
    assert runner.enqueued[0]["title"] == "j"
    assert runner.enqueued[0]["prompt"] == "do it"
    assert job.last_status == "queued"
    assert job.run_count == 1
    assert job.last_run


async def test_run_now():
    runner = FakeRunner()
    s = CronScheduler(runner)
    job = s.add_job(name="j", cron="* * * * *", prompt="p")
    assert await s.run_now(job.id) is True
    assert await s.run_now("missing") is False
    assert len(runner.enqueued) == 1


async def test_next_run_populated_on_create_for_started_scheduler():
    # gh #37: on a live (started) server, add_job used to defer next_run to the
    # run loop, so the POST create response (and schedule_run) returned null.
    s = CronScheduler(FakeRunner())
    s.start()  # _started=True; creates run-loop tasks (needs the running loop)
    try:
        job = s.add_job(name="daily3", cron="0 9 * * 1-5", prompt="morning")
        assert job.next_run, "next_run must be set synchronously on create"
    finally:
        s.shutdown()


async def test_schedule_run_tool_reports_next_run_on_started_scheduler():
    s = CronScheduler(FakeRunner())
    s.start()
    set_scheduler(s)
    try:
        out = schedule_run.invoke({"name": "nightly", "cron": "0 9 * * 1-5", "prompt": "p"})
        assert "Next run: pending" not in out
        assert "Next run:" in out
    finally:
        set_scheduler(None)
        s.shutdown()


# ── agent tools ──────────────────────────────────────────────────────


def test_tools_schedule_list_cancel():
    s = CronScheduler(FakeRunner())
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
    s = CronScheduler(FakeRunner())
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
