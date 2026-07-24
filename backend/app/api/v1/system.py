"""Application routes: health, system info, OCR check, settings, diagnostics
(SPEC §19 Application, §30)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.api.deps import diagnostics_service, settings_service
from app.core.config import get_settings
from app.schemas.jobs import HealthOut, McpStatusOut, SettingsUpdate
from app.services.deps import get_ocr_adapter
from app.services.settings import DiagnosticsService, SettingsService

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthOut)
async def health(request: Request):
    adapter = get_ocr_adapter()
    status = await adapter.detect()
    return HealthOut(
        status="ok",
        version=get_settings().app_version,
        ocr_status=status.status,
    )


@router.get("/system/mcp", response_model=McpStatusOut)
async def mcp_status(request: Request) -> McpStatusOut:
    """Live MCP server status; counts introspected from the FastMCP server."""

    settings = get_settings()
    server = getattr(request.app.state, "mcp_server", None)
    if server is None:
        # Fallback for apps constructed without create_app wiring.
        from app.mcp.server import build_mcp_server

        server = build_mcp_server()
    tools = await server.list_tools()
    resources = await server.list_resources()
    templates = await server.list_resource_templates()
    prompts = await server.list_prompts()
    return McpStatusOut(
        enabled=True,
        transport="streamable-http",
        path="/mcp",
        port=settings.port,
        url=f"http://{settings.host}:{settings.port}/mcp",
        tool_count=len(tools),
        resource_count=len(resources) + len(templates),
        prompt_count=len(prompts),
    )


@router.get("/system/info")
async def system_info(
    request: Request,
    service: DiagnosticsService = Depends(diagnostics_service),
) -> dict[str, Any]:
    queue_worker = getattr(request.app.state, "queue_worker", None)
    webhook_worker = getattr(request.app.state, "webhook_worker", None)
    return await service.collect(
        queue_worker=queue_worker, webhook_worker=webhook_worker
    )


@router.get("/system/ocr")
async def ocr_status():
    adapter = get_ocr_adapter()
    status = await adapter.detect()
    return status.model_dump()


@router.post("/system/ocr/test")
async def ocr_reprobe():
    adapter = get_ocr_adapter()
    status = await adapter.detect(force=True)
    return status.model_dump()


@router.get("/settings")
async def get_settings_map(service: SettingsService = Depends(settings_service)):
    return await service.get_all()


@router.patch("/settings")
async def update_settings(
    payload: SettingsUpdate, service: SettingsService = Depends(settings_service)
):
    return await service.update(payload.changes)


@router.get("/system/diagnostics/bundle")
async def diagnostics_bundle(
    request: Request,
    service: DiagnosticsService = Depends(diagnostics_service),
):
    """Downloadable sanitized diagnostics bundle (SPEC §30)."""

    queue_worker = getattr(request.app.state, "queue_worker", None)
    webhook_worker = getattr(request.app.state, "webhook_worker", None)
    data = await service.build_bundle(
        queue_worker=queue_worker, webhook_worker=webhook_worker
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="ocr-diagnostics-{stamp}.zip"'
            )
        },
    )


@router.get("/system/python")
async def python_info() -> dict[str, str]:
    return {"version": sys.version, "executable": sys.executable}
