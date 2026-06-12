"""REST endpoint: /api/config."""

from fastapi import APIRouter

from langstage.config import AppConfig

router = APIRouter(prefix="/api")


def create_config_router(config: AppConfig) -> APIRouter:
    """Create the config router with the given AppConfig."""
    r = APIRouter(prefix="/api")

    @r.get("/config")
    async def get_config():
        return config.to_client_dict()

    return r
