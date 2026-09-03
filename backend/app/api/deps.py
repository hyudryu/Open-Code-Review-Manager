"""Shared API dependencies: DB sessions and services."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session_factory
from app.services.findings import FindingService
from app.services.folders import FolderService
from app.services.jobs import JobService
from app.services.ocr_mcp import OcrMcpServerService
from app.services.profiles import ProfileService
from app.services.projects import ProjectService
from app.services.providers import ProviderService
from app.services.settings import DiagnosticsService, SettingsService
from app.webhooks.service import WebhookService


async def get_db() -> AsyncIterator[AsyncSession]:
    """Request-scoped session with commit-on-success."""

    session = get_session_factory()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def folder_service(db: AsyncSession = Depends(get_db)) -> FolderService:
    return FolderService(db)


def project_service(db: AsyncSession = Depends(get_db)) -> ProjectService:
    return ProjectService(db)


def provider_service(db: AsyncSession = Depends(get_db)) -> ProviderService:
    return ProviderService(db)


def profile_service(db: AsyncSession = Depends(get_db)) -> ProfileService:
    return ProfileService(db)


def job_service(db: AsyncSession = Depends(get_db)) -> JobService:
    return JobService(db)


def finding_service(db: AsyncSession = Depends(get_db)) -> FindingService:
    return FindingService(db)


def settings_service(db: AsyncSession = Depends(get_db)) -> SettingsService:
    return SettingsService(db)


def diagnostics_service(db: AsyncSession = Depends(get_db)) -> DiagnosticsService:
    return DiagnosticsService(db)


def webhook_service(db: AsyncSession = Depends(get_db)) -> WebhookService:
    return WebhookService(db)


def ocr_mcp_server_service() -> OcrMcpServerService:
    """File-backed service — no database session needed."""
    return OcrMcpServerService()
