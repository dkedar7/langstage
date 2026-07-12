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


class FakeStore:
    """Minimal task store: task_id -> state, matching the bit of TaskStore.get()
    the scheduler's overlap check reads."""

    def __init__(self):
        self.states: dict[str, str] = {}

    async def get(self, task_id):
        state = self.states.get(task_id)
        return {"task_id": task_id, "state": state} if state is not None else None


class FakeRunner:
    """Records enqueue calls (the scheduler is now a producer onto the runner)
    and exposes a store so overlap protection can query prior-run state."""

    def __init__(self):
        self.enqueued = []
        self.store = FakeStore()
        self._n = 0

    async def enqueue(self, *, title, prompt, agent_spec=None, parent_id=None):
        self._n += 1
        task_id = f"task-{self._n}"
        self.enqueued.append(
            {"title": title, "prompt": prompt, "agent_spec": agent_spec,
             "parent_id": parent_id, "task_id": task_id}
        )
        self.store.states[task_id] = "queued"
        return task_id


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


# ── overlap protection (gh #78) ──────────────────────────────────────


async def test_fire_skips_while_previous_run_unresolved():
    runner = FakeRunner()
    s = CronScheduler(runner)
    job = s.add_job(name="j", cron="* * * * *", prompt="p")

    await s._fire(job)                       # first automatic fire enqueues
    assert len(runner.enqueued) == 1
    tid = job.last_task_id
    assert tid

    # The run parks at the HITL review gate; an automatic re-fire must skip.
    runner.store.states[tid] = "review_needed"
    await s._fire(job)
    assert len(runner.enqueued) == 1, "must not enqueue while prev run awaits review"
    assert "skipped" in (job.last_status or "")
    assert "review_needed" in job.last_status
    assert job.run_count == 1, "a skipped fire is not a run"

    # Same for still-ongoing / still-queued previous runs.
    for state in ("ongoing", "queued"):
        runner.store.states[tid] = state
        await s._fire(job)
    assert len(runner.enqueued) == 1


async def test_fire_proceeds_once_previous_run_finishes():
    runner = FakeRunner()
    s = CronScheduler(runner)
    job = s.add_job(name="j", cron="* * * * *", prompt="p")

    await s._fire(job)
    runner.store.states[job.last_task_id] = "done"
    await s._fire(job)                       # prev resolved → fire again
    assert len(runner.enqueued) == 2
    assert job.run_count == 2
    assert job.last_status == "queued"


async def test_run_now_bypasses_overlap_protection():
    runner = FakeRunner()
    s = CronScheduler(runner)
    job = s.add_job(name="j", cron="* * * * *", prompt="p")

    await s._fire(job)
    runner.store.states[job.last_task_id] = "review_needed"
    # Explicit manual trigger runs even though the previous run is unresolved.
    assert await s.run_now(job.id) is True
    assert len(runner.enqueued) == 2


async def test_list_jobs_with_state_reports_last_run_state():
    runner = FakeRunner()
    s = CronScheduler(runner)
    job = s.add_job(name="j", cron="* * * * *", prompt="p")

    enriched = await s.list_jobs_with_state()
    assert enriched[0]["last_run_state"] is None      # no run yet

    await s._fire(job)
    runner.store.states[job.last_task_id] = "review_needed"
    enriched = await s.list_jobs_with_state()
    assert enriched[0]["last_task_id"] == job.last_task_id
    assert enriched[0]["last_run_state"] == "review_needed"


async def test_overlap_protection_is_noop_without_a_store():
    # A runner without a store must not break firing (best-effort protection).
    class NoStoreRunner:
        def __init__(self):
            self.enqueued = []

        async def enqueue(self, *, title, prompt, agent_spec=None, parent_id=None):
            self.enqueued.append(title)
            return "t"

    s = CronScheduler(NoStoreRunner())
    job = s.add_job(name="j", cron="* * * * *", prompt="p")
    await s._fire(job)
    await s._fire(job)                       # no store to check → proceeds
    assert len(s._runner.enqueued) == 2


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


# ── agent-created schedules run off the loop thread (gh #82) ─────────


async def _wait_for_task(scheduler, job_id, tries=50):
    """call_soon_threadsafe defers the run-loop spawn to the loop; let it run."""
    for _ in range(tries):
        if job_id in scheduler._tasks:
            return True
        await asyncio.sleep(0.01)
    return False


async def test_off_loop_add_job_starts_run_loop_not_zombie():
    # The sync schedule_run tool runs in a worker thread; add_job from there used
    # to raise "no running event loop" and leave a registered-but-unstarted job.
    s = CronScheduler(FakeRunner())
    s.start()  # captures the loop
    try:
        job = await asyncio.to_thread(
            lambda: s.add_job(name="n", cron="* * * * *", prompt="p", created_by="agent")
        )
        assert job.id in s._jobs
        assert await _wait_for_task(s, job.id), "run-loop must be started (no zombie)"
    finally:
        s.shutdown()


async def test_schedule_run_tool_from_worker_thread_succeeds():
    # The exact bug: the tool returned "no running event loop" and the schedule
    # never fired. Now it reports success and the job has a live run-loop.
    s = CronScheduler(FakeRunner())
    s.start()
    set_scheduler(s)
    try:
        out = await asyncio.to_thread(
            lambda: schedule_run.invoke({"name": "nightly", "cron": "* * * * *", "prompt": "p"})
        )
        assert "no running event loop" not in out
        assert "Scheduled 'nightly'" in out
        jobs = s.list_jobs()
        assert len(jobs) == 1
        assert await _wait_for_task(s, jobs[0]["id"]), "agent schedule must have a run-loop"
    finally:
        set_scheduler(None)
        s.shutdown()


async def test_add_job_rolls_back_when_run_loop_cannot_start(monkeypatch):
    # If starting the run-loop fails, add_job must not leave a zombie in _jobs.
    s = CronScheduler(FakeRunner())
    s.start()

    def boom(job):
        raise RuntimeError("cannot start")

    monkeypatch.setattr(s, "_start_job", boom)
    try:
        with pytest.raises(RuntimeError):
            s.add_job(name="x", cron="* * * * *", prompt="p")
        assert s.list_jobs() == [], "a failed start must roll back the insert"
    finally:
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
