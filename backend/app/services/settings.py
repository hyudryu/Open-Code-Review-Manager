"""Application settings service (SPEC §19 Application, §30)."""

from __future__ import annotations

import io
import json
import platform
import sys
import zipfile
from typing import Any

from sqlalchemy import select

from app.core.logging import redact_text
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

    async def recent_errors(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """Last ``limit`` sanitized backend errors (failed jobs + error events)."""

        errors: list[dict[str, Any]] = []
        failed_jobs = await self.session.execute(
            select(models.ReviewJob)
            .where(models.ReviewJob.status == "failed")
            .order_by(models.ReviewJob.completed_at.desc())
            .limit(limit)
        )
        for job in failed_jobs.scalars():
            errors.append(
                {
                    "kind": "job_failed",
                    "job_id": job.id,
                    "message": redact_text(job.status_message or ""),
                    "at": job.completed_at.isoformat() if job.completed_at else None,
                }
            )
        error_events = await self.session.execute(
            select(models.JobEvent)
            .where(models.JobEvent.event_type.like("%error%"))
            .order_by(models.JobEvent.id.desc())
            .limit(limit)
        )
        for event in error_events.scalars():
            errors.append(
                {
                    "kind": event.event_type,
                    "job_id": event.job_id,
                    "message": redact_text(
                        json.dumps(event.payload_json or {}, ensure_ascii=False)
                    )[:1000],
                    "at": event.created_at.isoformat() if event.created_at else None,
                }
            )
        errors.sort(key=lambda e: e.get("at") or "", reverse=True)
        return errors[:limit]

    #: Per-file cap for log excerpts inside the diagnostics bundle (SPEC §30).
    BUNDLE_LOG_CAP_BYTES = 16_000
    #: How many recent jobs contribute log excerpts.
    BUNDLE_LOG_JOB_COUNT = 5

    async def build_bundle(self, *, queue_worker=None, webhook_worker=None) -> bytes:
        """Sanitized zip diagnostics bundle (SPEC §30).

        Contains the system-info snapshot, sanitized settings, recent errors,
        and capped/redacted log excerpts. Never includes credentials (the DB
        only stores secret references) or source file content.
        """

        info = await self.collect(
            queue_worker=queue_worker, webhook_worker=webhook_worker
        )
        settings_map = await SettingsService(self.session).get_all()

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "README.txt",
                "OpenCodeReview Control Center diagnostics bundle\n"
                "Sanitized by construction: no credentials (only secret\n"
                "references are ever stored), no source file content, log\n"
                f"excerpts capped at {self.BUNDLE_LOG_CAP_BYTES} bytes and\n"
                "run through the credential redactor.\n",
            )
            zf.writestr(
                "system-info.json",
                json.dumps(info, indent=2, default=str, ensure_ascii=False),
            )
            zf.writestr(
                "settings.json",
                redact_text(
                    json.dumps(settings_map, indent=2, default=str, ensure_ascii=False)
                ),
            )
            zf.writestr(
                "recent-errors.json",
                json.dumps(
                    await self.recent_errors(), indent=2, ensure_ascii=False
                ),
            )

            recent_jobs = await self.session.execute(
                select(models.ReviewJob)
                .order_by(models.ReviewJob.queued_at.desc())
                .limit(self.BUNDLE_LOG_JOB_COUNT)
            )
            from pathlib import Path

            for job in recent_jobs.scalars():
                for stream, path_str in (
                    ("stdout", job.stdout_path),
                    ("stderr", job.stderr_path),
                ):
                    if not path_str:
                        continue
                    path = Path(path_str)
                    try:
                        if not path.is_file():
                            continue
                        size = path.stat().st_size
                        with path.open("rb") as fh:
                            fh.seek(max(0, size - self.BUNDLE_LOG_CAP_BYTES))
                            data = fh.read(self.BUNDLE_LOG_CAP_BYTES)
                    except OSError:
                        continue
                    text = redact_text(data.decode("utf-8", errors="replace"))
                    zf.writestr(f"logs/{job.id[:8]}-{stream}.log", text)
        return buffer.getvalue()
