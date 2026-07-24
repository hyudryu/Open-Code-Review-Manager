"""Project routes (SPEC §19 Projects)."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Response

from app.api.deps import project_service
from app.schemas.jobs import JobOut
from app.schemas.projects import (
    BranchOut,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    PullRequestListOut,
    PullRequestOut,
    RefreshBranchesOut,
)
from app.services.projects import ProjectService
from app.services.pull_requests import PrService

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    query: str | None = None,
    include_unavailable: bool = True,
    service: ProjectService = Depends(project_service),
):
    return await service.list(query=query, include_unavailable=include_unavailable)


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    payload: ProjectCreate, service: ProjectService = Depends(project_service)
):
    return await service.create(**payload.model_dump())


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: str, service: ProjectService = Depends(project_service)
):
    return await service.get(project_id)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: str,
    payload: ProjectUpdate,
    service: ProjectService = Depends(project_service),
):
    return await service.update(
        project_id, **payload.model_dump(exclude_unset=True)
    )


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str, service: ProjectService = Depends(project_service)
):
    await service.delete(project_id)
    return Response(status_code=204)


@router.post("/{project_id}/refresh-branches", response_model=RefreshBranchesOut)
async def refresh_branches(
    project_id: str, service: ProjectService = Depends(project_service)
):
    branches, fetch_error = await service.refresh_branches(project_id)
    return RefreshBranchesOut(branches=branches, fetch_error=fetch_error)


@router.post("/{project_id}/fetch", response_model=RefreshBranchesOut)
async def fetch_project(
    project_id: str, service: ProjectService = Depends(project_service)
):
    branches, fetch_error = await service.refresh_branches(
        project_id, fetch=True, prune=True
    )
    return RefreshBranchesOut(branches=branches, fetch_error=fetch_error)


@router.get("/{project_id}/branches", response_model=list[BranchOut])
async def list_branches(
    project_id: str,
    kind: str | None = None,
    service: ProjectService = Depends(project_service),
):
    return await service.list_branches(project_id, kind=kind)


@router.get("/{project_id}/pull-requests", response_model=PullRequestListOut)
async def list_pull_requests(
    project_id: str, service: ProjectService = Depends(project_service)
):
    prs = PrService(service.session)
    listing = await prs.list_open_prs(project_id)
    return PullRequestListOut(
        prs=[PullRequestOut(**asdict(pr)) for pr in listing.prs],
        source=listing.source,
        warning=listing.warning,
    )


@router.get("/{project_id}/jobs", response_model=list[JobOut])
async def list_project_jobs(
    project_id: str, service: ProjectService = Depends(project_service)
):
    return await service.jobs(project_id)
