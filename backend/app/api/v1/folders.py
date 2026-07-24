"""Folder routes (SPEC §19 Folders)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.api.deps import folder_service
from app.schemas.projects import (
    FolderCreate,
    FolderOut,
    FolderScanOut,
    FolderUpdate,
    ProjectOut,
    RegisterScannedRequest,
)
from app.services.folders import FolderService

router = APIRouter(prefix="/folders", tags=["folders"])


@router.get("", response_model=list[FolderOut])
async def list_folders(service: FolderService = Depends(folder_service)):
    return await service.list()


@router.post("", response_model=FolderOut, status_code=201)
async def create_folder(
    payload: FolderCreate, service: FolderService = Depends(folder_service)
):
    return await service.create(**payload.model_dump())


@router.get("/{folder_id}", response_model=FolderOut)
async def get_folder(folder_id: str, service: FolderService = Depends(folder_service)):
    return await service.get(folder_id)


@router.patch("/{folder_id}", response_model=FolderOut)
async def update_folder(
    folder_id: str,
    payload: FolderUpdate,
    service: FolderService = Depends(folder_service),
):
    return await service.update(
        folder_id, **payload.model_dump(exclude_unset=True)
    )


@router.delete("/{folder_id}", status_code=204)
async def delete_folder(folder_id: str, service: FolderService = Depends(folder_service)):
    await service.delete(folder_id)
    return Response(status_code=204)


@router.post("/{folder_id}/scan", response_model=FolderScanOut)
async def scan_folder(folder_id: str, service: FolderService = Depends(folder_service)):
    return await service.scan(folder_id)


@router.post("/{folder_id}/register", response_model=list[ProjectOut], status_code=201)
async def register_scanned(
    folder_id: str,
    payload: RegisterScannedRequest,
    service: FolderService = Depends(folder_service),
):
    return await service.register_scanned(folder_id, payload.paths)
