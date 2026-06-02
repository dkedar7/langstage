"""In-memory cron scheduler for cowork-dash.

Schedules recurring agent runs that live as long as the app process does (not
persisted). Each job runs the configured agent — via the shared
``SessionAdapter`` — on its own session (`cron-<id>`), on a standard 5-field
cron schedule.

Two ways to create jobs:
- **Agents** call the ``schedule_run`` tool (see below), wired into the default
  agent's toolset.
- **Users** create them from the Schedules tab in the UI (POST /api/cron).

The scheduler is process-global (a module singleton) so the agent tools can
reach it without threading it through agent state.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from langchain_core.tools import tool as langchain_tool

logger = logging.getLogger(__name__)

try:
    from croniter import croniter
except ModuleNotFoundError:  # pragma: no cover
    croniter = None  # type: ignore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_cron(expr: str) -> None:
    """Raise ValueError if ``expr`` isn't a valid 5-field cron expression."""
    if croniter is None:  # pragma: no cover
        raise RuntimeError("croniter is required for scheduling. pip install croniter")
    if not croniter.is_valid(expr):
        raise ValueError(
            f"Invalid cron expression: {expr!r}. Expected 5 fields "
            "'min hour day month weekday', e.g. '*/15 * * * *' or '0 9 * * 1-5'."
        )


@dataclass
class CronJob:
    id: str
    name: str
    cron: str
    prompt: str
    created_at: str
    created_by: str = "user"            # "user" | "agent"
    enabled: bool = True
    next_run: Optional[str] = None
    last_run: Optional[str] = None
    last_status: Optional[str] = None   # "ok" | "running" | "error: ..."
    run_count: int = 0

    @property
    def session_id(self) -> str:
        return f"cron-{self.id}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["session_id"] = self.session_id
        return d


class CronScheduler:
    """Runs ``CronJob``s on the app's asyncio loop. In-memory only."""

    def __init__(self, adapter: Any):
        self._adapter = adapter
        self._jobs: dict[str, CronJob] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._started = False

    # ── queries ──────────────────────────────────────────────────────
    def list_jobs(self) -> list[dict[str, Any]]:
        return [j.to_dict() for j in self._jobs.values()]

    def get(self, job_id: str) -> Optional[CronJob]:
        return self._jobs.get(job_id)

    # ── mutations ────────────────────────────────────────────────────
    def add_job(self, *, name: str, cron: str, prompt: str, created_by: str = "user") -> CronJob:
        validate_cron(cron)
        if not name or not name.strip():
            raise ValueError("Schedule name is required.")
        if not prompt or not prompt.strip():
            raise ValueError("Schedule prompt is required.")
        job = CronJob(
            id=uuid.uuid4().hex[:8],
            name=name.strip(),
            cron=cron.strip(),
            prompt=prompt.strip(),
            created_at=_now_iso(),
            created_by=created_by,
        )
        self._jobs[job.id] = job
        if self._started:
            self._start_job(job)
        else:
            job.next_run = self._compute_next(job.cron)
        return job

    def remove_job(self, job_id: str) -> bool:
        job = self._jobs.pop(job_id, None)
        if job is None:
            return False
        task = self._tasks.pop(job_id, None)
        if task is not None:
            task.cancel()
        return True

    async def run_now(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None:
            return False
        await self._fire(job)
        return True

    # ── lifecycle ────────────────────────────────────────────────────
    def start(self) -> None:
        """Start run-loops for all enabled jobs (call once the loop is running)."""
        self._started = True
        for job in self._jobs.values():
            if job.enabled and job.id not in self._tasks:
                self._start_job(job)

    def shutdown(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()
        self._started = False

    # ── internals ────────────────────────────────────────────────────
    @staticmethod
    def _compute_next(expr: str) -> Optional[str]:
        if croniter is None:  # pragma: no cover
            return None
        nxt = croniter(expr, datetime.now()).get_next(datetime)
        return nxt.astimezone(timezone.utc).isoformat(timespec="seconds")

    def _start_job(self, job: CronJob) -> None:
        self._tasks[job.id] = asyncio.create_task(self._run_loop(job))

    async def _run_loop(self, job: CronJob) -> None:
        try:
            itr = croniter(job.cron, datetime.now())
            while True:
                nxt = itr.get_next(datetime)
                job.next_run = nxt.astimezone(timezone.utc).isoformat(timespec="seconds")
                delay = (nxt - datetime.now()).total_seconds()
                if delay > 0:
                    await asyncio.sleep(delay)
                await self._fire(job)
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - defensive; keep the loop's failure visible
            logger.exception("cron job %s loop crashed", job.id)
            job.last_status = "error: loop crashed"

    async def _fire(self, job: CronJob) -> None:
        job.last_status = "running"
        try:
            session = self._adapter.submit_message(
                job.session_id, job.prompt,
                context_parts=[f"[Scheduled run: {job.name}]"],
            )
            task = getattr(session, "current_task", None)
            if task is not None:
                await task
            # Headless run with no SSE consumer: drain the queue so it can't
            # grow unbounded across repeated fires.
            if not getattr(session, "sse_connected", False):
                q = getattr(session, "event_queue", None)
                while q is not None and not q.empty():
                    q.get_nowait()
            job.last_status = "ok"
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            job.last_status = f"error: {type(exc).__name__}: {exc}"
            logger.exception("cron job %s fire failed", job.id)
        finally:
            job.last_run = _now_iso()
            job.run_count += 1


# ── process-global singleton (so agent tools can reach the scheduler) ──
_scheduler: Optional[CronScheduler] = None


def set_scheduler(scheduler: Optional[CronScheduler]) -> None:
    global _scheduler
    _scheduler = scheduler


def get_scheduler() -> Optional[CronScheduler]:
    return _scheduler


# ── agent tools ────────────────────────────────────────────────────────

@langchain_tool
def schedule_run(name: str, cron: str, prompt: str) -> str:
    """Schedule a recurring agent run on a cron schedule.

    The scheduled run executes the given prompt automatically on the schedule,
    for as long as the app is running (schedules are not persisted across
    restarts).

    Args:
        name: A short human-readable name for the schedule.
        cron: A standard 5-field cron expression: 'min hour day month weekday'.
            Examples: '*/15 * * * *' (every 15 min), '0 9 * * 1-5' (9am weekdays).
        prompt: The instruction to run on each fire.
    """
    sched = get_scheduler()
    if sched is None:
        return "Scheduling is unavailable (no scheduler is running in this context)."
    try:
        job = sched.add_job(name=name, cron=cron, prompt=prompt, created_by="agent")
    except (ValueError, RuntimeError) as e:
        return f"Could not schedule run: {e}"
    return (
        f"Scheduled '{job.name}' (id {job.id}) on '{job.cron}'. "
        f"Next run: {job.next_run or 'pending'}."
    )


@langchain_tool
def list_scheduled_runs() -> str:
    """List the currently active scheduled runs (cron jobs)."""
    sched = get_scheduler()
    if sched is None:
        return "Scheduling is unavailable."
    jobs = sched.list_jobs()
    if not jobs:
        return "No scheduled runs."
    lines = [
        f"- {j['id']}: '{j['name']}' on '{j['cron']}' "
        f"(next: {j['next_run'] or 'pending'}, runs: {j['run_count']}, "
        f"last: {j['last_status'] or 'never'})"
        for j in jobs
    ]
    return "Scheduled runs:\n" + "\n".join(lines)


@langchain_tool
def cancel_scheduled_run(job_id: str) -> str:
    """Cancel and remove a scheduled run by its id."""
    sched = get_scheduler()
    if sched is None:
        return "Scheduling is unavailable."
    return f"Cancelled scheduled run {job_id}." if sched.remove_job(job_id) else f"No scheduled run with id {job_id}."


CRON_TOOLS = [schedule_run, list_scheduled_runs, cancel_scheduled_run]
