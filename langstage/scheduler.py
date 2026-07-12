"""In-memory cron scheduler for langstage.

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

# Task states a scheduled run can still be "in flight" in. A schedule must not
# re-fire while its previous run is unresolved (gh #78) — otherwise unattended
# fires pile up as stuck tasks, most painfully ``review_needed``, which waits for
# a human that an unattended schedule never gets. Imported from the task engine
# so the set stays in lockstep with the runner's state machine.
try:
    from langstage_core.tasks import ONGOING, QUEUED, REVIEW_NEEDED

    _UNRESOLVED_TASK_STATES = frozenset({QUEUED, ONGOING, REVIEW_NEEDED})
except Exception:  # pragma: no cover - defensive; core is always present in practice
    _UNRESOLVED_TASK_STATES = frozenset({"queued", "ongoing", "review_needed"})


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
    last_status: Optional[str] = None   # "queued" | "skipped: ..." | "error: ..."
    run_count: int = 0
    last_task_id: Optional[str] = None  # id of the last task enqueued onto the board (gh #78)

    @property
    def session_id(self) -> str:
        return f"cron-{self.id}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["session_id"] = self.session_id
        return d


class CronScheduler:
    """Schedules ``CronJob``s on the app's asyncio loop. In-memory schedules;
    on each fire it *enqueues* a task onto the durable TaskRunner (the runner
    owns execution, persistence, and the board). The scheduler is a producer."""

    def __init__(self, runner: Any):
        self._runner = runner
        self._jobs: dict[str, CronJob] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._started = False
        # The event loop the scheduler runs on, captured at start(). Lets
        # _start_job spawn a run-loop from a non-loop thread (the sync
        # schedule_run tool runs in a worker thread) instead of failing. (gh #82)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ── queries ──────────────────────────────────────────────────────
    def list_jobs(self) -> list[dict[str, Any]]:
        return [j.to_dict() for j in self._jobs.values()]

    async def list_jobs_with_state(self) -> list[dict[str, Any]]:
        """Like :meth:`list_jobs`, but each job is enriched with
        ``last_run_state`` — the current board state of its most recent run
        (``queued`` / ``ongoing`` / ``review_needed`` / ``done`` / …), or
        ``None`` if it hasn't run yet. Lets a client surface e.g. a schedule
        whose last run is stuck awaiting review (gh #78)."""
        jobs = self.list_jobs()
        for d in jobs:
            d["last_run_state"] = await self._task_state(d.get("last_task_id"))
        return jobs

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
        # Compute next_run synchronously so the POST create response and the
        # schedule_run tool's confirmation message carry it immediately. On a
        # started scheduler _start_job's run loop keeps refreshing it; without
        # this, a live server deferred next_run to the loop and returned null on
        # create (only a follow-up GET showed it). (gh #37)
        job.next_run = self._compute_next(job.cron)
        if self._started:
            try:
                self._start_job(job)
            except Exception:
                # Never leave a registered-but-unstarted (zombie) schedule: if the
                # run-loop can't be started, roll back the insert and surface the
                # error to the caller (the schedule_run tool / POST handler). (gh #82)
                self._jobs.pop(job.id, None)
                raise
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
        # Manual run-now is an explicit user action → bypass overlap protection.
        await self._fire(job, force=True)
        return True

    # ── lifecycle ────────────────────────────────────────────────────
    def start(self) -> None:
        """Start run-loops for all enabled jobs (call once the loop is running)."""
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - start() is always called on the loop
            self._loop = None
        self._started = True
        for job in self._jobs.values():
            if job.enabled and job.id not in self._tasks:
                self._start_job(job)

    def shutdown(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()
        self._started = False
        self._loop = None

    # ── internals ────────────────────────────────────────────────────
    @staticmethod
    def _compute_next(expr: str) -> Optional[str]:
        if croniter is None:  # pragma: no cover
            return None
        # Compute entirely in UTC: croniter interprets the cron expression
        # relative to its (tz-aware) base, so the displayed next_run and the
        # fire delay agree regardless of the host's local timezone.
        nxt = croniter(expr, datetime.now(timezone.utc)).get_next(datetime)
        return nxt.astimezone(timezone.utc).isoformat(timespec="seconds")

    def _start_job(self, job: CronJob) -> None:
        """Create the job's run-loop task. Safe to call from any thread (gh #82):
        the sync ``schedule_run`` tool runs in a worker thread with no running
        loop, so ``asyncio.create_task`` there raised ``RuntimeError: no running
        event loop`` and left a zombie. When off the scheduler's loop we hand the
        spawn to that loop via ``call_soon_threadsafe`` instead."""
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is not None and (self._loop is None or running is self._loop):
            self._spawn_run_loop(job)
        elif self._loop is not None:
            self._loop.call_soon_threadsafe(self._spawn_run_loop, job)
        else:  # pragma: no cover - no loop anywhere; add_job() rolls back the insert
            raise RuntimeError("scheduler has no running event loop to start the job on")

    def _spawn_run_loop(self, job: CronJob) -> None:
        """Create the run-loop task. Runs on the scheduler's loop thread; guarded
        against a job removed between scheduling and this (possibly deferred) call."""
        if job.id in self._jobs and job.id not in self._tasks:
            self._tasks[job.id] = asyncio.create_task(self._run_loop(job))

    async def _run_loop(self, job: CronJob) -> None:
        try:
            # UTC base + UTC "now" for the delay → no local/UTC skew.
            itr = croniter(job.cron, datetime.now(timezone.utc))
            while True:
                nxt = itr.get_next(datetime)
                job.next_run = nxt.astimezone(timezone.utc).isoformat(timespec="seconds")
                delay = (nxt - datetime.now(timezone.utc)).total_seconds()
                if delay > 0:
                    await asyncio.sleep(delay)
                await self._fire(job)
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - defensive; keep the loop's failure visible
            logger.exception("cron job %s loop crashed", job.id)
            job.last_status = "error: loop crashed"

    async def _fire(self, job: CronJob, *, force: bool = False) -> None:
        # Producer: enqueue a task onto the durable runner and return. The
        # runner executes it on the board (queued → ongoing → done), so the
        # scheduler no longer runs the agent or drains queues itself.
        #
        # Overlap protection (gh #78): an *automatic* fire is SKIPPED while the
        # schedule's previous run is still unresolved (queued/ongoing/awaiting
        # review). Without this, a schedule whose agent trips a human-in-the-loop
        # review gate silently piles up stuck ``review_needed`` tasks that never
        # complete — and the built-in default agent gates ``bash``, so that is the
        # common case, not an edge. Manual run-now passes ``force=True``.
        if not force and job.last_task_id is not None:
            prev_state = await self._task_state(job.last_task_id)
            if prev_state in _UNRESOLVED_TASK_STATES:
                job.last_status = f"skipped: previous run still {prev_state}"
                logger.info(
                    "cron job %s skipped fire: previous run %s still %s",
                    job.id, job.last_task_id, prev_state,
                )
                return
        try:
            task_id = await self._runner.enqueue(
                title=job.name,
                prompt=job.prompt,
            )
            job.last_task_id = task_id
            job.last_status = "queued"
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            job.last_status = f"error: {type(exc).__name__}: {exc}"
            logger.exception("cron job %s enqueue failed", job.id)
        finally:
            job.last_run = _now_iso()
            job.run_count += 1

    async def _task_state(self, task_id: Optional[str]) -> Optional[str]:
        """Current board state of ``task_id`` via the runner's store. Returns
        None if there's no id, no store, or the task is gone."""
        if not task_id:
            return None
        store = getattr(self._runner, "store", None)
        if store is None:
            return None
        try:
            task = await store.get(task_id)
        except Exception:  # pragma: no cover - defensive
            return None
        return task.get("state") if task else None


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
