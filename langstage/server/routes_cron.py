"""REST endpoints for the in-memory cron scheduler (Schedules tab)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from langstage.scheduler import CronScheduler


class CronCreate(BaseModel):
    name: str
    cron: str
    prompt: str


def create_cron_router(scheduler: CronScheduler) -> APIRouter:
    router = APIRouter(prefix="/api/cron", tags=["cron"])

    @router.get("")
    async def list_jobs():
        # Enriched with each schedule's last run state so a client can surface a
        # run stuck awaiting review (gh #78).
        return await scheduler.list_jobs_with_state()

    @router.post("", status_code=201)
    async def create_job(body: CronCreate):
        try:
            job = scheduler.add_job(
                name=body.name, cron=body.cron, prompt=body.prompt, created_by="user"
            )
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        return job.to_dict()

    @router.delete("/{job_id}")
    async def delete_job(job_id: str):
        if not scheduler.remove_job(job_id):
            raise HTTPException(status_code=404, detail="Schedule not found")
        return {"ok": True}

    @router.post("/{job_id}/run")
    async def run_now(job_id: str):
        if not await scheduler.run_now(job_id):
            raise HTTPException(status_code=404, detail="Schedule not found")
        return {"ok": True}

    return router
