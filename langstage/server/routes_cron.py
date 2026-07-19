"""REST endpoints for the in-memory cron scheduler (Schedules tab)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from langstage.scheduler import CronScheduler
from langstage.server.models import CronJob, OkResponse


class CronCreate(BaseModel):
    name: str
    cron: str
    prompt: str


def create_cron_router(scheduler: CronScheduler) -> APIRouter:
    router = APIRouter(prefix="/api/cron", tags=["cron"])

    @router.get("", response_model=list[CronJob], response_model_exclude_unset=True)
    async def list_jobs():
        # Enriched with each schedule's last run state so a client can surface a
        # run stuck awaiting review (gh #78).
        return await scheduler.list_jobs_with_state()

    @router.post("", status_code=201, response_model=CronJob, response_model_exclude_unset=True)
    async def create_job(body: CronCreate):
        try:
            job = scheduler.add_job(
                name=body.name, cron=body.cron, prompt=body.prompt, created_by="user"
            )
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        return job.to_dict()

    @router.delete("/{job_id}", response_model=OkResponse, response_model_exclude_unset=True)
    async def delete_job(job_id: str):
        if not scheduler.remove_job(job_id):
            raise HTTPException(status_code=404, detail="Schedule not found")
        return {"ok": True}

    @router.post("/{job_id}/run", response_model=OkResponse, response_model_exclude_unset=True)
    async def run_now(job_id: str):
        if not await scheduler.run_now(job_id):
            raise HTTPException(status_code=404, detail="Schedule not found")
        return {"ok": True}

    return router
