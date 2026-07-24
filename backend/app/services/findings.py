"""Findings: user_state transitions + notes (SPEC §15)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.db import models
from app.services.deps import ServiceBase
from app.services.errors import NotFoundError, ValidationFailedError


class FindingService(ServiceBase):
    async def list_for_job(
        self,
        job_id: str,
        *,
        user_state: str | None = None,
        path: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[models.Finding], int]:
        if await self.session.get(models.ReviewJob, job_id) is None:
            raise NotFoundError("Review job", job_id)
        stmt = select(models.Finding).where(models.Finding.job_id == job_id)
        count_stmt = select(func.count(models.Finding.id)).where(
            models.Finding.job_id == job_id
        )
        if user_state:
            stmt = stmt.where(models.Finding.user_state == user_state)
            count_stmt = count_stmt.where(models.Finding.user_state == user_state)
        if path:
            stmt = stmt.where(models.Finding.path == path)
            count_stmt = count_stmt.where(models.Finding.path == path)
        total = (await self.session.execute(count_stmt)).scalar_one()
        stmt = (
            stmt.order_by(models.Finding.path, models.Finding.start_line)
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars()), total

    async def get(self, finding_id: str) -> models.Finding:
        finding = await self.session.get(models.Finding, finding_id)
        if finding is None:
            raise NotFoundError("Finding", finding_id)
        return finding

    async def update(
        self,
        finding_id: str,
        *,
        user_state: str | None = None,
        user_note: str | None = None,
    ) -> models.Finding:
        finding = await self.get(finding_id)
        if user_state is not None:
            if user_state not in models.FINDING_USER_STATES:
                raise ValidationFailedError(
                    f"Unknown finding state '{user_state}'.",
                    detail=f"Supported: {', '.join(models.FINDING_USER_STATES)}.",
                )
            finding.user_state = user_state
        if user_note is not None:
            finding.user_note = user_note or None
        await self.session.flush()
        return finding

    async def grouped_by_file(self, job_id: str) -> dict[str, list[dict[str, Any]]]:
        findings, _total = await self.list_for_job(job_id, limit=10_000)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for finding in findings:
            grouped.setdefault(finding.path, []).append(
                {
                    "id": finding.id,
                    "content": finding.content,
                    "start_line": finding.start_line,
                    "end_line": finding.end_line,
                    "severity": finding.severity,
                    "category": finding.category,
                    "user_state": finding.user_state,
                }
            )
        return grouped
