"""Application routes: health, system info, OCR check, settings, diagnostics
(SPEC §19 Application, §30)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.api.deps import diagnostics_service, settings_service
from app.core.config import get_settings
from app.schemas.jobs import HealthOut, McpStatusOut, SettingsUpdate
from app.schemas.system import DirBrowseOut
from app.services.deps import get_ocr_adapter, get_ocr_update_service
from app.services.settings import DiagnosticsService, SettingsService
from app.services.system_browse import SystemBrowseService

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


@router.get("/system/ocr/update-status")
async def ocr_update_status():
    """Check if a newer version of OpenCodeReview is available on npm.

    Queries the npm registry for the latest ``@alibaba-group/open-code-review``
    version and compares it with the currently detected installation.
    ``update_in_progress`` reports whether an update install is running.
    """

    from app.ocr.version import is_newer
    from app.services.ocr_update import INSTALL_COMMAND, latest_npm_version

    adapter = get_ocr_adapter()
    status = await adapter.detect()
    current_version = status.version
    update_service = get_ocr_update_service()

    # If we can't detect the current version, we can't compare.
    if not current_version:
        return {
            "current_version": None,
            "latest_version": None,
            "update_available": False,
            "update_in_progress": update_service.in_progress,
            "install_command": INSTALL_COMMAND,
            "error": "Current version not detected",
        }

    latest_version = await latest_npm_version()
    if latest_version is None:
        return {
            "current_version": current_version,
            "latest_version": None,
            "update_available": False,
            "update_in_progress": update_service.in_progress,
            "install_command": INSTALL_COMMAND,
            "error": "Could not reach npm registry",
        }

    return {
        "current_version": current_version,
        "latest_version": latest_version,
        "update_available": is_newer(current_version, latest_version),
        "update_in_progress": update_service.in_progress,
        "install_command": INSTALL_COMMAND,
    }


@router.post("/system/ocr/update")
async def ocr_update(request: Request):
    """Install the latest OpenCodeReview release via npm and re-probe OCR.

    Long-running (up to ``ocr_update_timeout_seconds``); the response carries
    the refreshed version comparison. Refuses to run concurrently with
    another update or while a review job is executing.
    """

    from app.services.ocr_update import OCRUpdateError

    update_service = get_ocr_update_service()
    if update_service.in_progress:
        raise HTTPException(
            status_code=409, detail="An OpenCodeReview update is already running."
        )
    queue_worker = getattr(request.app.state, "queue_worker", None)
    if queue_worker is not None and queue_worker.runner.active_count:
        raise HTTPException(
            status_code=409,
            detail=(
                "A review is currently running. Wait for it to finish or cancel "
                "it before updating OpenCodeReview."
            ),
        )
    try:
        return await update_service.update()
    except OCRUpdateError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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


@router.get("/system/browse", response_model=DirBrowseOut)
async def browse_directory(path: str | None = None) -> DirBrowseOut:
    """List subdirectories of a host path for the folder picker.

    A browser cannot read absolute filesystem paths from a file picker, so the
    picker browses the backend host instead. Returns real directories so the
    chosen absolute path can be pasted into the form.
    """

    return await SystemBrowseService().browse(path)
