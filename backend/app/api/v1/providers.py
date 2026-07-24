"""Provider + model routes (SPEC §19 Providers and Models)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.api.deps import provider_service
from app.schemas.providers import (
    ManualModelCreate,
    ModelOut,
    ProviderCreate,
    ProviderOut,
    ProviderTestOut,
    ProviderUpdate,
)
from app.services.providers import ProviderService

router = APIRouter(prefix="/providers", tags=["providers"])


async def _out(service: ProviderService, provider) -> ProviderOut:
    data = ProviderOut.model_validate(provider)
    data.has_credential = await service.has_credential(provider)
    return data


@router.get("", response_model=list[ProviderOut])
async def list_providers(service: ProviderService = Depends(provider_service)):
    providers = await service.list()
    return [await _out(service, p) for p in providers]


@router.post("", response_model=ProviderOut, status_code=201)
async def create_provider(
    payload: ProviderCreate, service: ProviderService = Depends(provider_service)
):
    provider = await service.create(**payload.model_dump())
    return await _out(service, provider)


@router.get("/{provider_id}", response_model=ProviderOut)
async def get_provider(
    provider_id: str, service: ProviderService = Depends(provider_service)
):
    return await _out(service, await service.get(provider_id))


@router.patch("/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: str,
    payload: ProviderUpdate,
    service: ProviderService = Depends(provider_service),
):
    provider = await service.update(
        provider_id, **payload.model_dump(exclude_unset=True)
    )
    return await _out(service, provider)


@router.delete("/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: str, service: ProviderService = Depends(provider_service)
):
    await service.delete(provider_id)
    return Response(status_code=204)


@router.post("/{provider_id}/test", response_model=ProviderTestOut)
async def test_provider(
    provider_id: str,
    model_id: str | None = None,
    service: ProviderService = Depends(provider_service),
):
    result = await service.test_connection(provider_id, model_id=model_id)
    return ProviderTestOut(**result.model_dump())


@router.post("/{provider_id}/discover-models", response_model=list[ModelOut])
async def discover_models(
    provider_id: str, service: ProviderService = Depends(provider_service)
):
    return await service.discover_models(provider_id)


@router.get("/{provider_id}/models", response_model=list[ModelOut])
async def list_models(
    provider_id: str, service: ProviderService = Depends(provider_service)
):
    return await service.list_models(provider_id)


@router.post("/{provider_id}/models", response_model=ModelOut, status_code=201)
async def add_manual_model(
    provider_id: str,
    payload: ManualModelCreate,
    service: ProviderService = Depends(provider_service),
):
    return await service.add_manual_model(provider_id, **payload.model_dump())


@router.delete("/{provider_id}/models/{model_pk}", status_code=204)
async def remove_model(
    provider_id: str,
    model_pk: str,
    service: ProviderService = Depends(provider_service),
):
    await service.remove_model(provider_id, model_pk)
    return Response(status_code=204)
