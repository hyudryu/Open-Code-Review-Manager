"""Webhook routes (SPEC §19 Webhooks)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import webhook_service
from app.schemas.jobs import (
    WebhookCreate,
    WebhookDeliveryOut,
    WebhookOut,
    WebhookUpdate,
)
from app.webhooks.service import WebhookService

router = APIRouter(tags=["webhooks"])


async def _out(service: WebhookService, endpoint) -> WebhookOut:
    data = WebhookOut.model_validate(endpoint)
    data.has_secret = bool(endpoint.secret_reference)
    return data


@router.get("/webhooks", response_model=list[WebhookOut])
async def list_webhooks(service: WebhookService = Depends(webhook_service)):
    endpoints = await service.list_endpoints()
    return [await _out(service, e) for e in endpoints]


@router.post("/webhooks", response_model=WebhookOut, status_code=201)
async def create_webhook(
    payload: WebhookCreate, service: WebhookService = Depends(webhook_service)
):
    endpoint = await service.create_endpoint(**payload.model_dump())
    return await _out(service, endpoint)


@router.get("/webhooks/{endpoint_id}", response_model=WebhookOut)
async def get_webhook(
    endpoint_id: str, service: WebhookService = Depends(webhook_service)
):
    return await _out(service, await service.get_endpoint(endpoint_id))


@router.patch("/webhooks/{endpoint_id}", response_model=WebhookOut)
async def update_webhook(
    endpoint_id: str,
    payload: WebhookUpdate,
    service: WebhookService = Depends(webhook_service),
):
    endpoint = await service.update_endpoint(
        endpoint_id, **payload.model_dump(exclude_unset=True)
    )
    return await _out(service, endpoint)


@router.delete("/webhooks/{endpoint_id}", status_code=204)
async def delete_webhook(
    endpoint_id: str, service: WebhookService = Depends(webhook_service)
):
    await service.delete_endpoint(endpoint_id)
    return Response(status_code=204)


@router.post("/webhooks/{endpoint_id}/test", response_model=WebhookDeliveryOut)
async def test_webhook(
    endpoint_id: str, service: WebhookService = Depends(webhook_service)
):
    return await service.test_endpoint(endpoint_id)


@router.get("/webhooks/{endpoint_id}/deliveries", response_model=list[WebhookDeliveryOut])
async def list_deliveries(
    endpoint_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: WebhookService = Depends(webhook_service),
):
    return await service.list_deliveries(endpoint_id, limit=limit, offset=offset)


@router.post(
    "/webhook-deliveries/{delivery_id}/replay", response_model=WebhookDeliveryOut
)
async def replay_delivery(
    delivery_id: str, service: WebhookService = Depends(webhook_service)
):
    delivery = await service.replay(delivery_id)
    from app.webhooks.worker import get_current_webhook_worker

    worker = get_current_webhook_worker()
    if worker is not None:
        worker.notify()
    return delivery
