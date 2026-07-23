"""Application settings service (SPEC §19 Application, §30)."""

from __future__ import annotations

import platform
import sys
from typing import Any

from sqlalchemy import select

from app.db import models
from app.services.deps import ServiceBase

#: Keys writable through the settings API, with defaults from config.
EDITABLE_SETTINGS: dict[str, str] = {
    "queue.global_concurrency": "global_concurrency",
    "queue.per_project_concurrency": "per_project_concurrency",
    "queue.per_provider_concurrency": "default_provider_concurrency",
    "retention.artifact_days": "artifact_retention_days",
    "retention.keep_worktrees": "keep_worktrees",
    "webhooks.require_https": "webhook_require_https",
    "webhooks.allow_private_networks": "webhook_allow_private_networks",
    "ocr.executable": "ocr_executable",
    "git.executable": "git_executable",
}


class SettingsService(ServiceBase):
    async def get_all(self) -> dict[str, Any]:
        result = await self.session.execute(select(models.AppSetting))
        stored = {row.key: row.value_json for row in result.scalars()}
        out: dict[str, Any] = {}
        for key, attr in EDITABLE_SETTINGS.items():
            if key in stored:
                out[key] = stored[key]
            else:
                value = getattr(self.settings, attr, None)
                out[key] = str(value) if value is not None and attr.endswith("executable") else value
        out["queue.paused"] = bool(stored.get("queue.paused", False))
        return out

    async def update(self, changes: dict[str, Any]) -> dict[str, Any]:
        from app.services.errors import ValidationFailedError

        unknown = set(changes) - set(EDITABLE_SETTINGS) - {"queue.paused"}
        if unknown:
            raise ValidationFailedError(
                f"Unknown settings: {sorted(unknown)}.",
                detail=f"Editable: {', '.join(sorted(EDITABLE_SETTINGS))}.",
            )
        for key, value in changes.items():
            row = await self.session.get(models.AppSetting, key)
            if row is None:
                row = models.AppSetting(key=key, value_json=value)
                self.session.add(row)
            else:
                row.value_json = value
        await self.session.flush()
        return await self.get_all()


class DiagnosticsService(ServiceBase):
    """SPEC §30 diagnostics snapshot (sanitized; no secrets)."""

    async def collect(self, *, queue_worker=None, webhook_worker=None) -> dict[str, Any]:
        from app.db.session import get_engine

        status = await self.adapter.detect()
        try:
            git_version = await self.git.version()
        except Exception:
            git_version = None

        job_count = (
            await self.session.execute(select(models.ReviewJob.id))
        ).all()
        worktrees = 0
        if self.settings.worktrees_dir.is_dir():
            worktrees = sum(
                1
                for project_dir in self.settings.worktrees_dir.iterdir()
                if project_dir.is_dir()
                for child in project_dir.iterdir()
                if child.is_dir()
            )
        session_bytes = 0
        if self.settings.jobs_dir.is_dir():
            for path in self.settings.jobs_dir.rglob("*.jsonl"):
                try:
                    session_bytes += path.stat().st_size
                except OSError:
                    continue

        return {
            "app_version": self.settings.app_version,
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "database_path": str(self.settings.database_path),
            "database_status": "ok" if get_engine() is not None else "unavailable",
            "data_dir": str(self.settings.resolved_data_dir),
            "ocr": status.model_dump(),
            "git_version": git_version,
            "mcp": {"mounted": True, "endpoint": "/mcp"},
            "queue_worker": {
                "running": bool(queue_worker and queue_worker._loop_task),
                "active_jobs": queue_worker.runner.active_count if queue_worker else 0,
            },
            "webhook_worker": {
                "running": bool(webhook_worker and webhook_worker._task),
            },
            "active_process_count": queue_worker.runner.active_count if queue_worker else 0,
            "job_count": len(job_count),
            "worktree_count": worktrees,
            "session_storage_bytes": session_bytes,
        }
