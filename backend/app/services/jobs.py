"""Job service: creation with immutable snapshots, preview, retry/resume,
exports (SPEC §7-8, §12, §16, §36).

The configuration snapshot is written once at queue time and never mutated:
resolved provider/model, profile settings, refs→SHAs, generated command and
OCR version. Secrets are resolved only at execution time and never enter
the snapshot, the DB, logs, or exports.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from sqlalchemy import func, select

from app.core.logging import redact_text
from app.core.security import (
    RefValidationError,
    redact_environment,
    validate_git_ref,
)
from app.db import models
from app.git.service import GitError, RefNotFoundError
from app.ocr.adapter import UnsupportedFeatureError
from app.ocr.models import ReviewJobContext
from app.queue.service import QueueService
from app.services.deps import ServiceBase
from app.services.errors import (
    ConflictError,
    NotFoundError,
    ValidationFailedError,
)
from app.services.providers import ProviderService

EXPORT_FORMATS = ("md", "json", "csv", "jsonl", "txt", "agent-prompt", "github-summary")


class JobService(ServiceBase):
    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    async def get(self, job_id: str) -> models.ReviewJob:
        job = await self.session.get(models.ReviewJob, job_id)
        if job is None:
            raise NotFoundError("Review job", job_id)
        return job

    async def list(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
        source: str | None = None,
        provider_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[models.ReviewJob], int]:
        stmt = select(models.ReviewJob)
        count_stmt = select(func.count(models.ReviewJob.id))
        filters = []
        if status:
            filters.append(models.ReviewJob.status == status)
        if project_id:
            filters.append(models.ReviewJob.project_id == project_id)
        if source:
            filters.append(models.ReviewJob.source == source)
        if provider_id:
            # JSON path comparison works on SQLite (JSON1) and Postgres alike.
            filters.append(
                models.ReviewJob.configuration_snapshot_json["provider"]["id"].as_string()
                == provider_id
            )
        for clause in filters:
            stmt = stmt.where(clause)
            count_stmt = count_stmt.where(clause)
        total = (await self.session.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(models.ReviewJob.queued_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars()), total

    # ------------------------------------------------------------------
    # creation
    # ------------------------------------------------------------------

    def _queue(self) -> QueueService:
        queue = QueueService(
            self.session,
            settings=self.settings,
            git=self.git,
            adapter=self.adapter,
            secrets=self.secrets,
        )
        from app.webhooks.service import WebhookService

        async def _dispatch(session, job, event_type):
            await WebhookService(session, settings=self.settings).dispatch_event(
                session, job, event_type
            )

        queue.webhook_dispatcher = _dispatch
        from app.queue.worker import get_current_worker

        worker = get_current_worker()
        if worker is not None:
            queue.cancel_handler = worker.cancel_handler
        return queue

    async def _resolve_refs(
        self,
        project: models.Project,
        *,
        mode: str,
        base_ref: str | None,
        target_ref: str | None,
        commit_ref: str | None,
    ) -> dict[str, str | None]:
        """Resolve user refs to immutable SHAs at queue time (SPEC §7)."""

        shas: dict[str, str | None] = {
            "base_sha": None,
            "target_sha": None,
            "commit_sha": None,
        }
        try:
            if mode == "range":
                if not base_ref or not target_ref:
                    raise ValidationFailedError(
                        "Range reviews need a base and a target ref.",
                        next_action="Pick both branches in the review form.",
                    )
                shas["base_sha"] = await self.git.resolve_ref(
                    project.absolute_path, base_ref
                )
                shas["target_sha"] = await self.git.resolve_ref(
                    project.absolute_path, target_ref
                )
            elif mode == "commit":
                if not commit_ref:
                    raise ValidationFailedError(
                        "Commit reviews need a commit ref or SHA.",
                    )
                shas["commit_sha"] = await self.git.resolve_ref(
                    project.absolute_path, commit_ref
                )
        except RefValidationError as exc:
            raise ValidationFailedError(
                "A git ref is not valid.", detail=str(exc)
            ) from exc
        except RefNotFoundError as exc:
            raise ValidationFailedError(
                "OpenCodeReview could not resolve a branch or commit.",
                detail=exc.stderr or str(exc),
                next_action="Refresh the project branches and select a valid ref.",
            ) from exc
        except GitError as exc:
            raise ValidationFailedError(
                "Git could not inspect the repository.",
                detail=exc.stderr or str(exc),
            ) from exc
        return shas

    def _build_context(
        self,
        *,
        mode: str,
        repo_path: str,
        profile: models.ReviewProfile | None,
        shas: dict[str, str | None],
        base_ref: str | None,
        target_ref: str | None,
        commit_ref: str | None,
        background: str | None,
        background_file: str | None,
        exclude_patterns: list[str] | None,
        resume_session_id: str | None = None,
        model_id: str | None = None,
    ) -> ReviewJobContext:
        from app.core.security import parse_additional_arguments

        additional = parse_additional_arguments(
            profile.additional_arguments if profile else None
        )
        return ReviewJobContext(
            mode=mode,  # type: ignore[arg-type]
            repo_path=repo_path,
            base_ref=base_ref,
            target_ref=target_ref,
            commit_ref=commit_ref,
            base_sha=shas.get("base_sha"),
            target_sha=shas.get("target_sha"),
            commit_sha=shas.get("commit_sha"),
            resume_session_id=resume_session_id,
            language=profile.language if profile else None,
            concurrency=profile.concurrency if profile else None,
            per_file_timeout_minutes=(
                profile.per_file_timeout_minutes if profile else None
            ),
            max_tools=profile.max_tools if profile else None,
            max_git_processes=profile.max_git_processes if profile else None,
            rule_file_path=profile.rule_file_path if profile else None,
            exclude_patterns=(
                exclude_patterns
                if exclude_patterns is not None
                else list(profile.exclude_patterns or []) if profile else []
            ),
            tools_file_path=profile.tools_file_path if profile else None,
            model=model_id,
            background=background,
            background_file=background_file,
            plan_mode=profile.plan_mode if profile else "auto",  # type: ignore[arg-type]
            plan_threshold_lines=profile.plan_threshold_lines if profile else None,
            max_tokens=profile.max_tokens if profile else None,
            additional_arguments=additional,
        )

    async def _resolve_provider(
        self, profile: models.ReviewProfile | None
    ) -> tuple[models.ProviderProfile | None, models.Model | None]:
        if profile is None or not profile.provider_profile_id:
            return None, None
        provider = await self.session.get(
            models.ProviderProfile, profile.provider_profile_id
        )
        if provider is None:
            raise ValidationFailedError(
                "The review profile references a provider that no longer exists.",
                next_action="Edit the profile and pick a valid provider.",
            )
        model = None
        if profile.model_id:
            model = await self.session.get(models.Model, profile.model_id)
        return provider, model

    async def create(
        self,
        *,
        project_id: str,
        mode: str,
        base_ref: str | None = None,
        target_ref: str | None = None,
        commit_ref: str | None = None,
        profile_id: str | None = None,
        background: str | None = None,
        background_file: str | None = None,
        exclude_patterns: list[str] | None = None,
        priority: int = 50,
        source: str = "web",
        webhook_endpoint_id: str | None = None,
        webhook_url: str | None = None,
        webhook_secret: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> models.ReviewJob:
        if mode not in models.JOB_MODES:
            raise ValidationFailedError(
                f"Unknown review mode '{mode}'.",
                detail=f"Supported: {', '.join(models.JOB_MODES)}.",
            )
        if source not in models.JOB_SOURCES:
            raise ValidationFailedError(f"Unknown job source '{source}'.")
        project = await self.session.get(models.Project, project_id)
        if project is None:
            raise NotFoundError("Project", project_id)
        profile = None
        if profile_id:
            profile = await self.session.get(models.ReviewProfile, profile_id)
            if profile is None:
                raise NotFoundError("Review profile", profile_id)

        if mode == "range":
            validate_git_ref(base_ref or "")
            validate_git_ref(target_ref or "")
        if mode == "commit":
            validate_git_ref(commit_ref or "")

        shas = await self._resolve_refs(
            project,
            mode=mode,
            base_ref=base_ref,
            target_ref=target_ref,
            commit_ref=commit_ref,
        )
        provider, model = await self._resolve_provider(profile)
        status = await self.adapter.detect()

        job = models.ReviewJob(
            project_id=project.id,
            profile_id=profile.id if profile else None,
            source=source,
            mode=mode,
            base_ref=base_ref,
            target_ref=target_ref,
            commit_ref=commit_ref,
            workspace_path=project.absolute_path if mode == "workspace" else None,
            priority=max(0, min(priority, 100)),
            status="queued",
            ocr_version=status.version,
            webhook_endpoint_id=webhook_endpoint_id,
            request_metadata_json=dict(metadata or {}),
        )
        self.session.add(job)
        await self.session.flush()  # assigns job.id

        # Workspace dirty-state fingerprint recorded at queue time (§11).
        if mode == "workspace":
            from app.queue.runner import JobRunner

            job.dirty_fingerprint = await JobRunner(
                self.settings, self.git, self.adapter, self.secrets
            ).workspace_fingerprint(project.absolute_path)

        # Deterministic paths: the worktree location is known before it exists.
        repo_path = (
            project.absolute_path
            if mode == "workspace"
            else str(self.settings.worktree_path(project.id, job.id))
        )
        ctx = self._build_context(
            mode=mode,
            repo_path=repo_path,
            profile=profile,
            shas=shas,
            base_ref=base_ref,
            target_ref=target_ref,
            commit_ref=commit_ref,
            background=background,
            background_file=background_file,
            exclude_patterns=exclude_patterns,
            model_id=model.model_id if model else None,
        )
        try:
            argv = self.adapter.build_review_command(
                ctx, status.capabilities if status.status == "ok" else None
            )
        except (UnsupportedFeatureError, ValueError) as exc:
            raise ValidationFailedError(
                "The installed OCR cannot run this review as configured.",
                detail=str(exc),
                next_action="Adjust the profile settings or update the OCR binary.",
            ) from exc

        # Redacted environment preview (secrets resolved, then masked).
        providers = ProviderService(
            self.session,
            settings=self.settings,
            git=self.git,
            adapter=self.adapter,
            secrets=self.secrets,
        )
        env_preview: dict[str, str] = {}
        if provider is not None:
            resolution = await providers.resolve(
                provider,
                model_id=model.model_id if model else None,
                language=profile.language if profile else None,
            )
            env_preview = redact_environment(
                {
                    k: v
                    for k, v in self.adapter.build_job_environment(
                        self.settings.job_home(job.id), resolution
                    ).items()
                    if k.startswith("OCR_") or k in {"HOME", "USERPROFILE"}
                }
            )

        job.configuration_snapshot_json = {
            "provider": (
                {
                    "id": provider.id,
                    "name": provider.name,
                    "protocol": provider.protocol,
                    "base_url": provider.base_url,
                }
                if provider
                else None
            ),
            "model": (
                {"id": model.id, "model_id": model.model_id} if model else None
            ),
            "settings": (
                {
                    key: getattr(profile, key)
                    for key in (
                        "language", "concurrency", "per_file_timeout_minutes",
                        "llm_http_timeout_seconds", "max_tools", "max_git_processes",
                        "plan_mode", "plan_threshold_lines", "max_tokens",
                        "exclude_patterns", "rule_file_path", "tools_file_path",
                        "background_template", "additional_arguments",
                    )
                }
                if profile
                else {}
            ),
            "refs": {
                "base_ref": base_ref,
                "target_ref": target_ref,
                "commit_ref": commit_ref,
            },
            "base_sha": shas.get("base_sha"),
            "target_sha": shas.get("target_sha"),
            "commit_sha": shas.get("commit_sha"),
            "background": background,
            "context": ctx.model_dump(exclude={"repo_path"}),
            "ocr_version": status.version,
            "ocr_capabilities": (
                status.capabilities.model_dump() if status.status == "ok" else None
            ),
        }
        job.generated_command_json = {
            "argv": argv,
            "env": env_preview,
            "cwd": repo_path,
            "executable": argv[0] if argv else None,
        }

        queue = self._queue()
        await queue.enqueue(job)

        # Ad-hoc webhook (MCP submit): store secret behind a reference.
        if webhook_url:
            from app.webhooks.service import WebhookService

            hooks = WebhookService(
                self.session,
                settings=self.settings,
                git=self.git,
                adapter=self.adapter,
                secrets=self.secrets,
            )
            await hooks.validate_target_url(webhook_url)
            secret_ref = None
            if webhook_secret:
                secret_ref = await self.secrets.set(
                    f"job-webhook:{job.id}", webhook_secret
                )
            job.request_metadata_json = {
                **(job.request_metadata_json or {}),
                "webhook_url": webhook_url,
                "webhook_secret_reference": secret_ref,
            }
        await self.session.flush()

        # review.queued webhook dispatch + persisted event.
        await queue.emit_event(
            job.id,
            "job.status",
            {"from": None, "to": "queued", "message": "Job queued."},
        )
        if queue.webhook_dispatcher is not None:
            await queue.webhook_dispatcher(self.session, job, "review.queued")

        from app.queue.worker import get_current_worker

        worker = get_current_worker()
        if worker is not None:
            worker.notify()
        return job

    # ------------------------------------------------------------------
    # preview (SPEC §7 Preview)
    # ------------------------------------------------------------------

    async def preview(
        self,
        *,
        project_id: str,
        mode: str,
        base_ref: str | None = None,
        target_ref: str | None = None,
        commit_ref: str | None = None,
        profile_id: str | None = None,
        exclude_patterns: list[str] | None = None,
    ):
        project = await self.session.get(models.Project, project_id)
        if project is None:
            raise NotFoundError("Project", project_id)
        profile = None
        if profile_id:
            profile = await self.session.get(models.ReviewProfile, profile_id)
        shas = await self._resolve_refs(
            project,
            mode=mode,
            base_ref=base_ref,
            target_ref=target_ref,
            commit_ref=commit_ref,
        )
        _provider, model = await self._resolve_provider(profile)
        ctx = self._build_context(
            mode=mode,
            repo_path=project.absolute_path,
            profile=profile,
            shas=shas,
            base_ref=base_ref,
            target_ref=target_ref,
            commit_ref=commit_ref,
            background=None,
            background_file=None,
            exclude_patterns=exclude_patterns,
            model_id=model.model_id if model else None,
        )
        result = await self.adapter.run_preview(ctx)
        if not result.ok:
            raise ValidationFailedError(
                "The preview could not be generated.",
                detail=redact_text(result.message or "preview failed"),
                next_action="Check that OCR is installed and the refs are valid.",
            )
        return result

    # ------------------------------------------------------------------
    # actions: cancel / retry / resume / duplicate / move
    # ------------------------------------------------------------------

    async def cancel(self, job_id: str) -> models.ReviewJob:
        queue = self._queue()
        job = await queue.cancel(job_id)
        from app.queue.worker import get_current_worker

        worker = get_current_worker()
        if worker is not None:
            worker.notify()
        return job

    async def move(self, job_id: str, action: str) -> models.ReviewJob:
        queue = self._queue()
        job = await queue.move(job_id, action)
        from app.queue.worker import get_current_worker

        worker = get_current_worker()
        if worker is not None:
            worker.notify()
        return job

    async def retry(
        self,
        job_id: str,
        *,
        priority: int | None = None,
        background: str | None = None,
    ) -> models.ReviewJob:
        """New job copying the immutable snapshot (SPEC §12 Retry)."""

        original = await self.get(job_id)
        if original.status not in {"failed", "interrupted", "cancelled"}:
            raise ConflictError(
                "Only failed, interrupted, or cancelled jobs can be retried.",
                detail=f"Job is currently '{original.status}'.",
            )
        return await self._clone(
            original,
            source="retry",
            retry_of_job_id=original.id,
            priority=priority,
            background=background,
        )

    async def duplicate(self, job_id: str) -> models.ReviewJob:
        original = await self.get(job_id)
        return await self._clone(original, source=original.source)

    async def _clone(
        self,
        original: models.ReviewJob,
        *,
        source: str,
        retry_of_job_id: str | None = None,
        priority: int | None = None,
        background: str | None = None,
        resume_session_id: str | None = None,
    ) -> models.ReviewJob:
        snapshot = dict(original.configuration_snapshot_json or {})
        if background is not None:
            snapshot["background"] = background
        job = models.ReviewJob(
            project_id=original.project_id,
            profile_id=original.profile_id,
            source=source,
            mode=original.mode,
            base_ref=original.base_ref,
            target_ref=original.target_ref,
            commit_ref=original.commit_ref,
            workspace_path=original.workspace_path,
            priority=priority if priority is not None else original.priority,
            status="queued",
            ocr_version=original.ocr_version,
            webhook_endpoint_id=original.webhook_endpoint_id,
            request_metadata_json=original.request_metadata_json,
            retry_of_job_id=retry_of_job_id,
            resume_from_session_id=resume_session_id,
            configuration_snapshot_json=snapshot,
        )
        self.session.add(job)
        await self.session.flush()

        # Rebuild the command for the new job id (worktree path changes);
        # everything else comes from the frozen snapshot.
        ctx_data = dict(snapshot.get("context") or {})
        repo_path = (
            original.workspace_path
            if original.mode == "workspace"
            else str(self.settings.worktree_path(original.project_id, job.id))
        )
        if resume_session_id:
            ctx_data["resume_session_id"] = resume_session_id
        ctx = ReviewJobContext(repo_path=repo_path, **ctx_data)
        try:
            argv = self.adapter.build_review_command(ctx)
        except (UnsupportedFeatureError, ValueError) as exc:
            raise ValidationFailedError(
                "The stored configuration can no longer be executed.",
                detail=str(exc),
            ) from exc
        job.generated_command_json = {
            "argv": argv,
            "env": (original.generated_command_json or {}).get("env") or {},
            "cwd": repo_path,
            "executable": argv[0] if argv else None,
        }
        queue = self._queue()
        await queue.enqueue(job)
        await queue.emit_event(
            job.id,
            "job.status",
            {
                "from": None,
                "to": "queued",
                "message": (
                    f"Retry of job {original.id}." if retry_of_job_id else "Job queued."
                ),
            },
        )
        from app.queue.worker import get_current_worker

        worker = get_current_worker()
        if worker is not None:
            worker.notify()
        return job

    async def resume(self, job_id: str) -> models.ReviewJob:
        """New job resuming the original's OCR session (SPEC §12 Resume)."""

        original = await self.get(job_id)
        if not original.ocr_session_id:
            raise ConflictError(
                "This job has no resumable OCR session.",
                next_action="Retry the job instead of resuming.",
            )
        status = await self.adapter.detect()
        if status.status == "ok" and not status.capabilities.resume:
            raise ConflictError(
                "The installed OCR does not support session resume.",
                detail=f"ocr {status.version or ''} lacks --resume support.",
            )
        # Mode + refs must match the original (SPEC §12): we copy them
        # verbatim, so validation is by construction.
        return await self._clone(
            original,
            source="retry",
            retry_of_job_id=original.id,
            resume_session_id=original.ocr_session_id,
        )

    async def delete(self, job_id: str) -> None:
        job = await self.get(job_id)
        if job.status in {"preparing", "running", "cancelling"}:
            raise ConflictError(
                "A running job cannot be deleted.",
                next_action="Cancel the job first, then delete it.",
            )
        await self.session.delete(job)
        await self.session.flush()

    # ------------------------------------------------------------------
    # artifacts: logs / session / events
    # ------------------------------------------------------------------

    async def read_log(
        self, job_id: str, stream: str, *, tail_bytes: int = 64_000, offset: int = 0
    ) -> dict[str, Any]:
        job = await self.get(job_id)
        path_str = job.stdout_path if stream == "stdout" else job.stderr_path
        if not path_str:
            return {"stream": stream, "text": "", "size": 0, "truncated": False}
        from pathlib import Path

        path = Path(path_str)
        if not path.is_file():
            return {"stream": stream, "text": "", "size": 0, "truncated": False}
        size = path.stat().st_size
        with path.open("rb") as fh:
            if offset:
                fh.seek(offset)
                data = fh.read(tail_bytes)
                truncated = size > offset + len(data)
            else:
                start = max(0, size - tail_bytes)
                fh.seek(start)
                data = fh.read(tail_bytes)
                truncated = start > 0
        return {
            "stream": stream,
            "text": redact_text(data.decode("utf-8", errors="replace")),
            "size": size,
            "truncated": truncated,
        }

    async def read_session(
        self,
        job_id: str,
        *,
        limit: int = 200,
        offset: int = 0,
        q: str | None = None,
        task_type: str | None = None,
        file: str | None = None,
    ) -> dict[str, Any]:
        """Paginated raw session records for the inspector (SPEC §15).

        ``q``/``task_type``/``file`` filter server-side so the UI never has
        to load the whole transcript to search it. ``total`` reflects the
        filtered record count.
        """

        job = await self.get(job_id)
        if not job.job_home_path:
            return {"records": [], "total": 0}
        session_file = self.adapter.locate_session_file(job.job_home_path)
        if session_file is None:
            return {"records": [], "total": 0}

        needle = q.strip().lower() if q else None
        task = task_type.strip() if task_type else None
        file_needle = file.strip().lower() if file else None

        def _matches(line: str, record: dict[str, Any] | None) -> bool:
            if needle and needle not in line.lower():
                return False
            if record is not None:
                if task:
                    record_task = record.get("task_type") or record.get("taskType")
                    if record_task != task:
                        return False
                if file_needle:
                    record_file = (
                        record.get("file_path")
                        or record.get("filePath")
                        or record.get("path")
                        or ""
                    )
                    if file_needle not in str(record_file).lower():
                        return False
            elif task or file_needle:
                # Unparseable lines can only satisfy a plain-text search.
                return False
            return True

        records: list[dict[str, Any]] = []
        matched = 0
        total = 0
        with session_file.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                total += 1
                try:
                    parsed: dict[str, Any] | None = json.loads(line)
                except json.JSONDecodeError:
                    parsed = None
                if not _matches(line, parsed):
                    continue
                if matched >= offset and len(records) < limit:
                    if parsed is not None:
                        records.append(parsed)
                    else:
                        records.append({"type": "unparseable", "raw": line[:500]})
                matched += 1
        return {
            "records": records,
            "total": matched if (needle or task or file_needle) else total,
            "session_file": str(session_file),
            "session_id": job.ocr_session_id,
        }

    # ------------------------------------------------------------------
    # export (SPEC §16)
    # ------------------------------------------------------------------

    async def export(
        self,
        job_id: str,
        fmt: str,
        *,
        include_reasoning: bool = False,
    ) -> tuple[str, str, str]:
        """Return ``(content, media_type, filename)`` for an export format.

        Credentials and auth headers never appear; reasoning (``thinking``)
        is excluded by default (SPEC §38.15).
        """

        if fmt not in EXPORT_FORMATS:
            raise ValidationFailedError(
                f"Unknown export format '{fmt}'.",
                detail=f"Supported: {', '.join(EXPORT_FORMATS)}.",
            )
        job = await self.get(job_id)
        project = await self.session.get(models.Project, job.project_id)
        result = await self.session.execute(
            select(models.Finding)
            .where(models.Finding.job_id == job.id)
            .order_by(models.Finding.path, models.Finding.start_line)
        )
        findings = list(result.scalars())
        snapshot = job.configuration_snapshot_json or {}
        summary = job.result_summary_json or {}

        header = {
            "project": project.display_name if project else job.project_id,
            "mode": job.mode,
            "base_ref": job.base_ref,
            "target_ref": job.target_ref,
            "commit_ref": job.commit_ref,
            "model": (snapshot.get("model") or {}).get("model_id"),
            "provider": (snapshot.get("provider") or {}).get("name"),
            "status": job.status,
            "files_reviewed": summary.get("files_reviewed"),
            "findings_count": len(findings),
            "duration": summary.get("elapsed"),
            "session_id": job.ocr_session_id,
            "queued_at": job.queued_at.isoformat() if job.queued_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }

        def finding_dict(f: models.Finding) -> dict[str, Any]:
            data: dict[str, Any] = {
                "path": f.path,
                "start_line": f.start_line,
                "end_line": f.end_line,
                "content": f.content,
                "existing_code": f.existing_code,
                "suggestion_code": f.suggestion_code,
                "category": f.category,
                "severity": f.severity,
                "user_state": f.user_state,
            }
            if include_reasoning:
                data["thinking"] = f.thinking
            return data

        safe_name = f"ocr-review-{job.id[:8]}"

        if fmt == "json":
            payload = {
                "job": {**header, "id": job.id, "priority": job.priority},
                "resolved_refs": snapshot.get("refs"),
                "resolved_shas": {
                    "base_sha": snapshot.get("base_sha"),
                    "target_sha": snapshot.get("target_sha"),
                    "commit_sha": snapshot.get("commit_sha"),
                },
                "configuration_snapshot": {
                    k: v
                    for k, v in snapshot.items()
                    if k not in {"context"}
                },
                "summary": summary,
                "findings": [finding_dict(f) for f in findings],
                "warnings": job.warnings_json or [],
            }
            return (
                json.dumps(payload, indent=2, ensure_ascii=False),
                "application/json",
                f"{safe_name}.json",
            )

        if fmt == "jsonl":
            lines = [json.dumps(finding_dict(f), ensure_ascii=False) for f in findings]
            return "\n".join(lines) + "\n", "application/x-ndjson", f"{safe_name}.jsonl"

        if fmt == "csv":
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(
                ["path", "start_line", "end_line", "category", "severity",
                 "user_state", "content", "suggestion_code"]
            )
            for f in findings:
                writer.writerow(
                    [f.path, f.start_line, f.end_line, f.category, f.severity,
                     f.user_state, f.content, f.suggestion_code]
                )
            return buffer.getvalue(), "text/csv", f"{safe_name}.csv"

        if fmt == "txt":
            parts = [
                f"OpenCodeReview — {header['project']} ({job.mode})",
                f"Status: {job.status}  Findings: {len(findings)}",
                "",
            ]
            for f in findings:
                location = f.path
                if f.start_line:
                    location += f":{f.start_line}"
                    if f.end_line and f.end_line != f.start_line:
                        location += f"-{f.end_line}"
                parts.append(f"* {location}")
                parts.append(f"  {f.content}")
                if f.suggestion_code:
                    parts.append(f"  Suggestion: {f.suggestion_code}")
                parts.append("")
            return "\n".join(parts), "text/plain", f"{safe_name}.txt"

        if fmt == "md":
            return (
                self._export_markdown(header, findings, include_reasoning),
                "text/markdown",
                f"{safe_name}.md",
            )

        if fmt == "agent-prompt":
            return (
                self._export_agent_prompt(header, findings),
                "text/markdown",
                f"{safe_name}-agent-prompt.md",
            )

        # github-summary
        return (
            self._export_github_summary(header, findings, summary),
            "text/markdown",
            f"{safe_name}-github-summary.md",
        )

    @staticmethod
    def _export_markdown(
        header: dict[str, Any],
        findings: list[models.Finding],
        include_reasoning: bool,
    ) -> str:
        """SPEC §16 Markdown Structure."""

        lines = [
            "# OpenCodeReview Findings",
            "",
            "## Summary",
            "",
            f"- Project: {header['project']}",
            f"- Review: {header['mode']}"
            + (f" ({header['base_ref']} → {header['target_ref']})" if header["mode"] == "range" else ""),
            f"- Model: {header['model'] or 'n/a'}",
            f"- Files reviewed: {header['files_reviewed'] if header['files_reviewed'] is not None else 'n/a'}",
            f"- Findings: {header['findings_count']}",
            f"- Duration: {header['duration'] or 'n/a'}",
            "",
            "## Findings",
            "",
        ]
        for f in findings:
            location = f.path
            if f.start_line:
                location += f":{f.start_line}"
                if f.end_line and f.end_line != f.start_line:
                    location += f"-{f.end_line}"
            lines.append(f"### `{location}`")
            lines.append("")
            lines.append(f.content)
            lines.append("")
            if f.existing_code:
                lines += ["**Existing code**", "", "```", f.existing_code, "```", ""]
            if f.suggestion_code:
                lines += ["**Suggested code**", "", "```", f.suggestion_code, "```", ""]
            if include_reasoning and f.thinking:
                lines += ["<details><summary>Reasoning</summary>", "", f.thinking, "", "</details>", ""]
        return "\n".join(lines)

    @staticmethod
    def _export_agent_prompt(
        header: dict[str, Any], findings: list[models.Finding]
    ) -> str:
        lines = [
            "# Code Review Findings — Fix Request",
            "",
            f"The automated review of **{header['project']}** "
            f"({header['mode']}) produced {header['findings_count']} finding(s).",
            "Address each finding below. Keep changes minimal and consistent "
            "with the surrounding code style.",
            "",
        ]
        for index, f in enumerate(findings, start=1):
            location = f.path
            if f.start_line:
                location += f":{f.start_line}"
            lines.append(f"## {index}. `{location}`")
            lines.append("")
            lines.append(f.content)
            if f.suggestion_code:
                lines += ["", "Suggested change:", "", "```", f.suggestion_code, "```"]
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _export_github_summary(
        header: dict[str, Any],
        findings: list[models.Finding],
        summary: dict[str, Any],
    ) -> str:
        status_icon = {"completed": "✅", "completed_with_warnings": "⚠️"}.get(
            header["status"], "❌"
        )
        lines = [
            f"### {status_icon} OpenCodeReview — {header['status'].replace('_', ' ')}",
            "",
            f"| | |",
            f"|---|---|",
            f"| Project | `{header['project']}` |",
            f"| Mode | `{header['mode']}` |",
            f"| Model | `{header['model'] or 'n/a'}` |",
            f"| Files reviewed | {summary.get('files_reviewed', 'n/a')} |",
            f"| Findings | {len(findings)} |",
            f"| Warnings | {summary.get('warnings', 0)} |",
            "",
        ]
        if findings:
            lines.append("<details><summary>Findings</summary>")
            lines.append("")
            for f in findings:
                location = f.path + (f":{f.start_line}" if f.start_line else "")
                lines.append(f"- **`{location}`** — {f.content.splitlines()[0] if f.content else ''}")
            lines += ["", "</details>"]
        return "\n".join(lines)
