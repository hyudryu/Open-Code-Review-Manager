"""OCR MCP server routes.

CRUD over the ``mcp_servers`` map of the OpenCodeReview CLI user config —
the external MCP servers the review agent can call during reviews (SPEC §17
extension; upstream "MCP Servers" docs). Deliberately file-backed, not
database-backed: the CLI reads this map from its user config, so writing
here is what makes servers real for both managed and direct ``ocr`` runs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.api.deps import ocr_mcp_server_service
from app.schemas.ocr_mcp import OcrMcpServerOut, OcrMcpServerUpsert
from app.services.ocr_mcp import OcrMcpServerService

router = APIRouter(prefix="/ocr/mcp-servers", tags=["ocr-mcp"])


@router.get("", response_model=list[OcrMcpServerOut])
async def list_mcp_servers(
    service: OcrMcpServerService = Depends(ocr_mcp_server_service),
):
    return await service.list()


@router.get("/{name}", response_model=OcrMcpServerOut)
async def get_mcp_server(
    name: str, service: OcrMcpServerService = Depends(ocr_mcp_server_service)
):
    return await service.get(name)


@router.put("/{name}", response_model=OcrMcpServerOut)
async def upsert_mcp_server(
    name: str,
    payload: OcrMcpServerUpsert,
    service: OcrMcpServerService = Depends(ocr_mcp_server_service),
):
    """Create or replace the server stored under ``name``."""

    return await service.upsert(name, payload)


@router.delete("/{name}")
async def delete_mcp_server(
    name: str, service: OcrMcpServerService = Depends(ocr_mcp_server_service)
):
    await service.remove(name)
    return Response(status_code=204)
