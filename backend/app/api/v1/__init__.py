"""API v1 router aggregation (SPEC §19)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    folders,
    jobs,
    ocr,
    profiles,
    projects,
    providers,
    queue,
    system,
    webhooks,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(folders.router)
api_router.include_router(projects.router)
api_router.include_router(providers.router)
api_router.include_router(profiles.router)
api_router.include_router(jobs.router)
api_router.include_router(queue.router)
api_router.include_router(webhooks.router)
api_router.include_router(ocr.router)
api_router.include_router(system.router)
