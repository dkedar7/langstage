"""Contract tests for the POST /api/cron field-count guard (gh #108).

`croniter` accepts 5-, 6- and 7-field expressions (its seconds / year
extensions), but langstage documents and interprets standard 5-field UTC cron
only — and the 400 message promises exactly that ("Expected 5 fields …"). Before
the fix a 6-field Quartz/Spring/k8s-style cron pasted from another scheduler was
silently accepted (201) and fired at an unintended time. These tests pin that
any non-5-field expression is rejected with the same clean 400 the 4-field case
already got, while valid 5-field expressions (including steps/ranges) still 201.

The route is driven over ``httpx.ASGITransport`` — never a real server (starting
one would hang). ``add_job`` on an unstarted scheduler computes ``next_run``
synchronously via croniter and never touches the runner, so a trivial stub
runner suffices.
"""
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from langstage.scheduler import (
    CronScheduler,
    set_scheduler,
    schedule_run,
    validate_cron,
)
from langstage.server.routes_cron import create_cron_router


class _StubRunner:
    """The create path never fires, so no runner behaviour is exercised."""


def _client():
    scheduler = CronScheduler(_StubRunner())
    app = FastAPI()
    app.include_router(create_cron_router(scheduler))
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://t")
    return client, scheduler


_FIVE_FIELD_MSG = "Expected 5 fields 'min hour day month weekday'"


# ── the endpoint contract ────────────────────────────────────────────────────


async def test_four_field_cron_rejected_unchanged():
    """The pre-existing 4-field rejection is untouched — same 400, same message."""
    client, _ = _client()
    async with client as c:
        r = await c.post("/api/cron", json={"name": "A", "cron": "0 9 * *", "prompt": "x"})
    assert r.status_code == 400
    assert _FIVE_FIELD_MSG in r.json()["detail"]


@pytest.mark.parametrize(
    "cron",
    ["0 9 * * *", "*/15 * * * *", "0 9 * * 1-5", "0  9 * * *"],
)
async def test_valid_five_field_crons_accepted(cron):
    """Plain, step (*/15), range (1-5), and double-spaced 5-field crons all 201."""
    client, _ = _client()
    async with client as c:
        r = await c.post("/api/cron", json={"name": "ok", "cron": cron, "prompt": "x"})
    assert r.status_code == 201, r.text
    assert r.json()["next_run"]  # computed synchronously on create


@pytest.mark.parametrize(
    "cron",
    [
        "30 0 9 * * *",     # 6-field (croniter seconds) — the issue's case B
        "0 9 * * * * *",    # 7-field — the issue's case C
        "0 0 9 * * * 2030", # 7-field with year
    ],
)
async def test_six_and_seven_field_crons_now_rejected(cron):
    """Before gh #108 these were silently accepted (201) and fired at the wrong
    time; now they get the same clean 400 the 4-field case gets."""
    client, scheduler = _client()
    async with client as c:
        r = await c.post("/api/cron", json={"name": "B", "cron": cron, "prompt": "x"})
    assert r.status_code == 400
    assert _FIVE_FIELD_MSG in r.json()["detail"]
    assert scheduler.list_jobs() == []  # nothing persisted from a rejected create


# ── the agent-tool path shares the same validation ───────────────────────────


def test_validate_cron_rejects_six_and_seven_fields():
    """The single shared validator (used by both POST /api/cron and the
    schedule_run agent tool) enforces the 5-field contract."""
    validate_cron("0 9 * * *")          # 5 fields ok
    validate_cron("*/15 * * * *")       # steps ok
    validate_cron("0 9 * * 1-5")        # ranges ok
    validate_cron("0  9 * * *")         # double space still 5 fields
    for bad in ("30 0 9 * * *", "0 9 * * * * *", "0 0 9 * * * 2030"):
        with pytest.raises(ValueError):
            validate_cron(bad)


def test_schedule_run_agent_tool_rejects_six_field_cron():
    """The agent tool goes through add_job -> validate_cron, so it rejects a
    6-field cron too (no schedule created)."""
    s = CronScheduler(_StubRunner())
    set_scheduler(s)
    try:
        out = schedule_run.invoke({"name": "B", "cron": "30 0 9 * * *", "prompt": "p"})
        assert "Could not schedule" in out
        assert _FIVE_FIELD_MSG in out
        assert s.list_jobs() == []
    finally:
        set_scheduler(None)


# ── unknown body fields are rejected, not silently dropped ──────────────────


@pytest.mark.parametrize("enabled", [False, True])
async def test_enabled_in_create_body_is_rejected(enabled):
    """`enabled: false` used to be dropped, creating a schedule that fires anyway."""
    client, scheduler = _client()
    async with client as c:
        r = await c.post("/api/cron", json={
            "name": "A", "cron": "0 9 * * *", "prompt": "x", "enabled": enabled,
        })
    assert r.status_code == 422
    assert "pausing" in str(r.json()["detail"]).lower()
    assert scheduler.list_jobs() == []


async def test_unknown_create_field_is_rejected():
    client, scheduler = _client()
    async with client as c:
        r = await c.post("/api/cron", json={
            "name": "A", "cron": "0 9 * * *", "prompt": "x", "timezone": "PST",
        })
    assert r.status_code == 422
    assert scheduler.list_jobs() == []
