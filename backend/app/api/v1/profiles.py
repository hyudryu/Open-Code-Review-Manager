"""Review profile routes (SPEC §19 Review Profiles)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.api.deps import profile_service
from app.schemas.providers import ProfileCreate, ProfileOut, ProfileUpdate
from app.services.profiles import ProfileService

router = APIRouter(prefix="/review-profiles", tags=["review-profiles"])


@router.get("", response_model=list[ProfileOut])
async def list_profiles(service: ProfileService = Depends(profile_service)):
    return await service.list()


@router.post("", response_model=ProfileOut, status_code=201)
async def create_profile(
    payload: ProfileCreate, service: ProfileService = Depends(profile_service)
):
    return await service.create(**payload.model_dump())


@router.get("/{profile_id}", response_model=ProfileOut)
async def get_profile(
    profile_id: str, service: ProfileService = Depends(profile_service)
):
    return await service.get(profile_id)


@router.patch("/{profile_id}", response_model=ProfileOut)
async def update_profile(
    profile_id: str,
    payload: ProfileUpdate,
    service: ProfileService = Depends(profile_service),
):
    return await service.update(
        profile_id, **payload.model_dump(exclude_unset=True)
    )


@router.delete("/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: str, service: ProfileService = Depends(profile_service)
):
    await service.delete(profile_id)
    return Response(status_code=204)


@router.post("/{profile_id}/duplicate", response_model=ProfileOut, status_code=201)
async def duplicate_profile(
    profile_id: str,
    new_name: str | None = None,
    service: ProfileService = Depends(profile_service),
):
    return await service.duplicate(profile_id, new_name=new_name)
