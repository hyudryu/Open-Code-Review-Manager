"""JobRunner: executes one queued job end-to-end (SPEC §10-14).

Lifecycle: preparing (job dir, per-job HOME + config, worktree for
range/commit, workspace lock for workspace mode) → running (asyncio exec,
stdout/stderr streamed to files, session JSONL tailed into normalized
events) → terminal transition with parsed findings, summary, tokens, and
credential-redacted metadata. Cancellation uses grace + process-tree kill.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from sqlalchemy import delete as sa_delete

from app.core.config import Settings
from app.core.logging import get_logger, redact_text, redactor
from app.core.security import redact_environment
from app.core.secrets import SecretStore
from app.db import models
from app.db.session import get_session_factory
from app.git.service import GitError, GitService
from app.ocr.adapter import OCRAdapter, UnsupportedFeatureError
from app.ocr.models import SessionEvent
from app.queue.bus import get_event_bus
from app.queue.processes import terminate_process_tree
from app.queue.service import QueueService, TERMINAL_STATUSES, WebhookDispatcher
from app.services.providers import ProviderService

logger = get_logger(__name__)

ResultWaiter = Callable[[], Awaitable[int]]


class ActiveJob:
    """Mutable runtime state for one executing job."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self.proc: asyncio.subprocess.Process | None = None
        self.cancel_requested = asyncio.Event()
        self.cancelled = False


class JobRunner:
    def __init__(
        self,
        settings: Settings,
        git: GitService,
        adapter: OCRAdapter,
        secrets: SecretStore,
        *,
        webhook_dispatcher: WebhookDispatcher | None = None,
    ) -> None:
        self.settings = settings
        self.git = git
        self.adapter = adapter
        self.secrets = secrets
        self.webhook_dispatcher = webhook_dispatcher
        self._active: dict[str, ActiveJob] = {}
        self._workspace_locks: dict[str, asyncio.Lock] = {}
        self._worktree_locks: dict[str, asyncio.Lock] = {}
        self._project_index: dict[str, str] = {}  # job_id -> project_id
        self._provider_index: dict[str, str] = {}  # job_id -> provider key
        self._repo_paths: dict[str, str] = {}  # job_id -> cwd for the process

    # ------------------------------------------------------------------
    # introspection (used by the worker for concurrency limits)
    # ------------------------------------------------------------------

    @property
    def active_count(self) -> int:
        return len(self._active)

    def active_for_project(self, project_id: str) -> int:
        return sum(
            1 for pid in self._project_index.values() if pid == project_id
        )

    def _project_of(self, job_id: str) -> str | None:
        return self._project_index.get(job_id)

    def active_for_provider(self, provider_key: str) -> int:
        return sum(1 for key in self._provider_index.values() if key == provider_key)

    # ------------------------------------------------------------------
    # cancellation
    # ------------------------------------------------------------------

    async def request_cancel(self, job_id: str) -> None:
        active = self._active.get(job_id)
        if active is not None:
            active.cancel_requested.set()

    # ------------------------------------------------------------------
    # main entry
    # ------------------------------------------------------------------

    async def run_job(self, job_id: str) -> None:
        active = ActiveJob(job_id)
        self._active[job_id] = active
        worktree_created: Path | None = None
        workspace_lock: asyncio.Lock | None = None
        project: models.Project | None = None
        try:
            factory = get_session_factory()
            async with factory() as session:
                job = await session.get(models.ReviewJob, job_id)
                if job is None or job.status != "queued":
                    return
                project = await session.get(models.Project, job.project_id)
                self._project_index[job_id] = job.project_id
                snapshot = job.configuration_snapshot_json or {}
                provider_key = (snapshot.get("provider") or {}).get("id") or "none"
                self._provider_index[job_id] = provider_key
                queue = self._queue(session)
                await queue.transition(job, "preparing")
                await session.commit()

            try:
                # Enforce a preparation deadline so a hang in git worktree
                # creation or secret resolution can't leave the job stuck in
                # "preparing" forever.
                worktree_created, workspace_lock = await asyncio.wait_for(
                    self._prepare(job_id),
                    timeout=self.settings.prepare_timeout_seconds,
                )
            except TimeoutError:
                await self._fail(
                    job_id,
                    f"preparation exceeded {self.settings.prepare_timeout_seconds:.0f}s timeout",
                    error_code="preparation_timeout",
                )
                return
            except Exception as exc:
                await self._fail(job_id, f"preparation failed: {redact_text(str(exc))[:500]}", error_code="preparation_failed")
                raise

            await self._execute(job_id, active)
        except Exception as exc:
            # Safety net: if any unhandled exception escapes after the job
            # transitioned to preparing/running, ensure it reaches a terminal
            # state rather than staying stuck forever.
            if not isinstance(exc, (asyncio.CancelledError,)):
                logger.exception("runner_unhandled_exception", job_id=job_id)
                await self._fail(
                    job_id,
                    f"runner crashed: {redact_text(str(exc))[:500]}",
                    error_code="runner_crashed",
                )
            raise
        finally:
            # Release resources no matter how the job ended.
            if workspace_lock is not None and workspace_lock.locked():
                workspace_lock.release()
            if worktree_created is not None and not self.settings.keep_worktrees:
                await self._remove_worktree(job_id, worktree_created)
            self._active.pop(job_id, None)
            self._project_index.pop(job_id, None)
            self._provider_index.pop(job_id, None)
            self._repo_paths.pop(job_id, None)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _queue(self, session) -> QueueService:
        queue = QueueService(
            session,
            settings=self.settings,
            git=self.git,
            adapter=self.adapter,
            secrets=self.secrets,
        )
        queue.webhook_dispatcher = self.webhook_dispatcher
        return queue

    async def _emit(
        self, job_id: str, event_type: str, payload: dict[str, Any] | None = None,
        *, persist: bool = True,
    ) -> None:
        factory = get_session_factory()
        async with factory() as session:
            queue = self._queue(session)
            await queue.emit_event(job_id, event_type, payload, persist=persist)
            await session.commit()

    async def _fail(
        self, job_id: str, message: str, *, error_code: str = "ocr_exit"
    ) -> None:
        factory = get_session_factory()
        async with factory() as session:
            job = await session.get(models.ReviewJob, job_id)
            if job is None:
                return
            queue = self._queue(session)
            try:
                if job.status == "cancelling":
                    await queue.transition(
                        job, "cancelled", message="Cancelled.", error_code="cancelled"
                    )
                elif job.status in {"preparing", "running"}:
                    await queue.transition(
                        job, "failed", message=message, error_code=error_code
                    )
            except Exception:
                logger.exception("job_fail_transition_error", job_id=job_id)
            await session.commit()

    # ------------------------------------------------------------------
    # preparation
    # ------------------------------------------------------------------

    async def _prepare(
        self, job_id: str
    ) -> tuple[Path | None, asyncio.Lock | None]:
        """Create job dir, per-job HOME/config, worktree or workspace lock."""

        factory = get_session_factory()
        async with factory() as session:
            job = await session.get(models.ReviewJob, job_id)
            assert job is not None
            project = await session.get(models.Project, job.project_id)
            if project is None:
                raise RuntimeError("job references a missing project")
            snapshot = dict(job.configuration_snapshot_json or {})

        job_dir = self.settings.job_dir(job_id)
        home = self.settings.job_home(job_id)
        (job_dir / "template").mkdir(parents=True, exist_ok=True)
        (home / ".opencodereview" / "sessions").mkdir(parents=True, exist_ok=True)

        # Resolve provider secrets at execution time (never stored on the job).
        provider_info = snapshot.get("provider") or {}
        resolution = None
        if provider_info.get("id"):
            async with factory() as session:
                providers = ProviderService(
                    session,
                    settings=self.settings,
                    git=self.git,
                    adapter=self.adapter,
                    secrets=self.secrets,
                )
                provider = await session.get(models.ProviderProfile, provider_info["id"])
                if provider is None:
                    raise RuntimeError(
                        "the provider used by this job was deleted; retry with a new provider"
                    )
                resolution = await providers.resolve(
                    provider,
                    model_id=(snapshot.get("model") or {}).get("model_id"),
                    language=snapshot.get("settings", {}).get("language"),
                )
        if resolution is not None:
            self.adapter.write_job_config(
                home, resolution, language=snapshot.get("settings", {}).get("language")
            )

        worktree_created: Path | None = None
        workspace_lock: asyncio.Lock | None = None

        if job.mode in {"range", "commit", "pr"}:
            target_sha = snapshot.get("target_sha") or snapshot.get("commit_sha")
            if not target_sha:
                raise RuntimeError("job snapshot is missing the resolved target SHA")
            worktree_path = self.settings.worktree_path(job.project_id, job.id)
            worktree_path.parent.mkdir(parents=True, exist_ok=True)
            lock = self._worktree_locks.setdefault(job.project_id, asyncio.Lock())
            async with lock:
                await self.git.add_detached_worktree(
                    project.absolute_path, worktree_path, target_sha
                )
            worktree_created = worktree_path
            repo_path = str(worktree_path)
        else:
            # Workspace mode: per-project exclusive lock + dirty fingerprint.
            workspace_lock = self._workspace_locks.setdefault(
                job.project_id, asyncio.Lock()
            )
            await workspace_lock.acquire()
            fingerprint = await self.workspace_fingerprint(project.absolute_path)
            if job.dirty_fingerprint and fingerprint != job.dirty_fingerprint:
                await self._emit(
                    job_id,
                    "job.warning",
                    {
                        "message": (
                            "Workspace changed since this job was queued; results "
                            "reflect the working state at execution time."
                        )
                    },
                )
            async with factory() as session:
                current = await session.get(models.ReviewJob, job_id)
                if current is not None:
                    current.dirty_fingerprint = fingerprint
                    await session.commit()
            repo_path = project.absolute_path

        async with factory() as session:
            current = await session.get(models.ReviewJob, job_id)
            if current is not None:
                current.job_home_path = str(home)
                current.worktree_path = str(worktree_created) if worktree_created else None
                await session.commit()

        # Persist the effective repo path into the runtime context.
        self._repo_paths[job_id] = repo_path
        return worktree_created, workspace_lock

    async def workspace_fingerprint(self, repo_path: str) -> str:
        """SHA-256 over porcelain status — the dirty-state fingerprint (§11)."""

        try:
            result = await self.git.run(
                ["status", "--porcelain"], cwd=repo_path
            )
            content = result.stdout
        except GitError:
            content = ""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    async def _remove_worktree(self, job_id: str, worktree_path: Path) -> None:
        project_id = self._project_index.get(job_id)
        try:
            factory = get_session_factory()
            async with factory() as session:
                job = await session.get(models.ReviewJob, job_id)
                if job is not None:
                    job.worktree_path = None
                    await session.commit()
                project = (
                    await session.get(models.Project, project_id)
                    if project_id
                    else None
                )
                repo_path = project.absolute_path if project else None
            if repo_path and worktree_path.exists():
                lock = self._worktree_locks.setdefault(project_id or "", asyncio.Lock())
                async with lock:
                    try:
                        await self.git.remove_worktree(repo_path, worktree_path, force=True)
                    except GitError as exc:
                        logger.warning(
                            "worktree_remove_failed", path=str(worktree_path), error=exc.stderr
                        )
            elif worktree_path.exists():
                shutil.rmtree(worktree_path, ignore_errors=True)
        except Exception:
            logger.exception("worktree_cleanup_error", path=str(worktree_path))

    # ------------------------------------------------------------------
    # execution
    # ------------------------------------------------------------------

    async def _execute(self, job_id: str, active: ActiveJob) -> None:
        factory = get_session_factory()
        async with factory() as session:
            job = await session.get(models.ReviewJob, job_id)
            assert job is not None
            snapshot = dict(job.configuration_snapshot_json or {})
            command = dict(job.generated_command_json or {})
            argv = list(command.get("argv") or [])
            if not argv:
                await self._fail(job_id, "job has no generated command", error_code="no_generated_command")
                return
            repo_path = self._repo_paths.get(job_id, job.workspace_path)
            job_home = Path(job.job_home_path or self.settings.job_home(job_id))

        # Rebuild the environment (secrets resolved fresh, never persisted).
        env: dict[str, str]
        provider_info = snapshot.get("provider") or {}
        if provider_info.get("id"):
            async with factory() as session:
                providers = ProviderService(
                    session,
                    settings=self.settings,
                    git=self.git,
                    adapter=self.adapter,
                    secrets=self.secrets,
                )
                provider = await session.get(models.ProviderProfile, provider_info["id"])
                if provider is None:
                    await self._fail(
                        job_id, "the provider used by this job was deleted",
                        error_code="provider_unavailable",
                    )
                    return
                resolution = await providers.resolve(
                    provider,
                    model_id=(snapshot.get("model") or {}).get("model_id"),
                    language=snapshot.get("settings", {}).get("language"),
                )
            env = self.adapter.build_job_environment(job_home, resolution)
        else:
            env = self.adapter._base_env()
            env["HOME"] = str(job_home)
            env["USERPROFILE"] = str(job_home)

        job_dir = self.settings.job_dir(job_id)
        stdout_path = job_dir / "stdout.log"
        stderr_path = job_dir / "stderr.log"

        exec_argv = self.adapter.exec_argv(argv)
        try:
            proc = await asyncio.create_subprocess_exec(
                *exec_argv,
                cwd=repo_path,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            await self._fail(
                job_id, f"could not start OCR: {redact_text(str(exc))[:300]}",
                error_code="ocr_process_start_failed",
            )
            return
        active.proc = proc

        async with factory() as session:
            current = await session.get(models.ReviewJob, job_id)
            if current is None:
                proc.kill()
                return
            current.process_id = proc.pid
            current.stdout_path = str(stdout_path)
            current.stderr_path = str(stderr_path)
            queue = self._queue(session)
            await queue.transition(current, "running")
            await session.commit()

        stdout_task = asyncio.create_task(
            self._stream(proc.stdout, stdout_path, job_id, "stdout")
        )
        stderr_task = asyncio.create_task(
            self._stream(proc.stderr, stderr_path, job_id, "stderr")
        )
        tail_state: dict[str, Any] = {
            "offset": 0,
            "path": None,
            "seen_files": set(),
            "stop": asyncio.Event(),
        }
        tail_task = asyncio.create_task(self._tail_session(job_id, job_home, tail_state))

        # Wait for exit or cancellation, enforcing the process timeout.
        timeout = self.settings.ocr_process_timeout_seconds
        wait_task = asyncio.create_task(proc.wait())
        cancel_task = asyncio.create_task(active.cancel_requested.wait())
        try:
            done, _pending = await asyncio.wait(
                {wait_task, cancel_task},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                await self._emit(
                    job_id, "job.warning",
                    {"message": f"OCR exceeded the {timeout:.0f}s process timeout; killing."},
                )
                active.cancel_requested.set()
            if cancel_task in done or not done:
                active.cancelled = True
                await terminate_process_tree(
                    proc, grace_seconds=self.settings.cancel_grace_seconds
                )
            exit_code = await wait_task if wait_task.done() else proc.returncode
        finally:
            cancel_task.cancel()
            for task in (stdout_task, stderr_task):
                task.cancel()
            # Stop the tailer gracefully rather than cancelling it: a drain
            # cancelled between advancing the parse offset and emitting the
            # events would silently drop progress events (observed as flaky
            # missing job.file_started/job.file_completed on fast jobs).
            tail_state["stop"].set()
            try:
                await asyncio.wait_for(tail_task, timeout=5)
            except (TimeoutError, asyncio.CancelledError):
                tail_task.cancel()
            await asyncio.gather(
                stdout_task, stderr_task, tail_task, return_exceptions=True
            )

        # Final drain: catch session records written just before process exit
        # (fast jobs can finish before the first tailer poll).
        try:
            await self._drain_session(job_id, job_home, tail_state)
        except Exception:
            logger.exception("session_final_drain_error", job_id=job_id)

        await self._finalize(job_id, active, exit_code, stdout_path, stderr_path)

    async def _stream(self, reader, path: Path, job_id: str, stream: str) -> None:
        """Stream a process pipe to its log file and durable job events."""

        if reader is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab") as fh:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                fh.write(chunk)
                fh.flush()
                text = chunk.decode("utf-8", errors="replace").strip()
                if text:
                    payload = {
                        "stream": stream,
                        "text": redact_text(text)[-2000:],
                    }
                    try:
                        await self._emit(job_id, "job.log", payload)
                    except Exception:
                        # Never stop draining a child pipe because SQLite was
                        # briefly unavailable; a full pipe can deadlock OCR.
                        logger.exception(
                            "job_log_persist_failed", job_id=job_id, stream=stream
                        )
                        get_event_bus().publish(
                            job_id,
                            {"id": None, "type": "job.log", "payload": payload},
                        )

    # ------------------------------------------------------------------
    # session tailing (SPEC §14)
    # ------------------------------------------------------------------

    async def _tail_session(
        self, job_id: str, job_home: Path, state: dict[str, Any]
    ) -> None:
        poll = max(self.settings.session_poll_seconds, 0.05)
        stop: asyncio.Event = state["stop"]
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=poll)
                break
            except TimeoutError:
                pass
            try:
                await self._drain_session(job_id, job_home, state)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("session_tail_error", job_id=job_id)

    async def _drain_session(
        self, job_id: str, job_home: Path, state: dict[str, Any]
    ) -> None:
        """Locate + incrementally parse the session JSONL; emit mapped events."""

        session_path: Path | None = state.get("path")
        if session_path is None:
            session_path = self.adapter.locate_session_file(job_home)
            if session_path is None:
                return
            state["path"] = session_path
        events, new_offset = self.adapter.parse_session_jsonl(
            session_path, offset=state["offset"], keep_raw=False
        )
        state["offset"] = new_offset
        for event in events:
            mapped = self._map_session_event(event, state["seen_files"])
            if mapped is not None:
                event_type, payload = mapped
                await self._emit(job_id, event_type, payload)

    @staticmethod
    def _map_session_event(
        event: SessionEvent, seen_files: set[str]
    ) -> tuple[str, dict[str, Any]] | None:
        """Map normalized session records onto SPEC §14 job events."""

        record_type = (event.record_type or "").lower()
        payload: dict[str, Any] = {
            "session_id": event.session_id,
            "file": event.file_path,
            "seq": event.seq,
        }
        if event.error:
            payload["message"] = event.error
            return "job.warning", payload
        if record_type in {"session_start", "start"}:
            payload["phase"] = "session_started"
            return "job.phase", payload
        if event.file_path and (
            "start" in record_type or record_type in {"file", "file_start"}
        ):
            if event.file_path not in seen_files:
                seen_files.add(event.file_path)
                return "job.file_started", payload
            return None
        if event.file_path and (
            "complete" in record_type
            or "done" in record_type
            or "finish" in record_type
            or event.comments_count is not None
        ):
            payload["comments"] = event.comments_count
            return "job.file_completed", payload
        if record_type in {"summary", "final", "result"}:
            return "job.summary", payload
        if record_type in {"plan", "planning"}:
            payload["phase"] = "planning"
            return "job.phase", payload
        return None  # noisy records (llm_request, tool_call) are not persisted

    # ------------------------------------------------------------------
    # finalization
    # ------------------------------------------------------------------

    async def _finalize(
        self,
        job_id: str,
        active: ActiveJob,
        exit_code: int | None,
        stdout_path: Path,
        stderr_path: Path,
    ) -> None:
        factory = get_session_factory()
        job_dir = self.settings.job_dir(job_id)

        if active.cancelled:
            async with factory() as session:
                job = await session.get(models.ReviewJob, job_id)
                if job is not None:
                    job.exit_code = exit_code
                    queue = self._queue(session)
                    if job.status in {"running", "preparing"}:
                        await queue.transition(
                            job, "cancelling", message="Cancellation requested."
                        )
                    if job.status == "cancelling":
                        await queue.transition(
                            job, "cancelled", message="Cancelled by user."
                        )
                    await session.commit()
            await self._write_metadata(job_id, exit_code)
            return

        # Another backend/reaper may have terminalized the row while this
        # runner still owned the process. Finalization must not attempt an
        # invalid terminal -> terminal transition or discard the first result.
        async with factory() as session:
            terminal_job = await session.get(models.ReviewJob, job_id)
            if terminal_job is None:
                return
            terminal_status = (
                terminal_job.status if terminal_job.status in TERMINAL_STATUSES else None
            )
            if terminal_status is not None:
                if terminal_job.exit_code is None:
                    terminal_job.exit_code = exit_code
                await session.commit()
        if terminal_status is not None:
            logger.info(
                "job_finalize_skipped_terminal",
                job_id=job_id,
                status=terminal_status,
            )
            await self._write_metadata(job_id, exit_code)
            await self._apply_retention()
            return

        # result.json: written by the binary or recovered from stdout JSON.
        result_path = job_dir / "result.json"
        parsed = None
        parse_error: str | None = None
        if result_path.exists():
            candidate = result_path
        else:
            candidate = self._recover_result_from_stdout(stdout_path, result_path)
        if candidate is not None:
            try:
                parsed = self.adapter.parse_result_json(candidate)
            except Exception as exc:
                parse_error = f"{type(exc).__name__}: {exc}"

        async with factory() as session:
            job = await session.get(models.ReviewJob, job_id)
            if job is None:
                return
            job.exit_code = exit_code
            queue = self._queue(session)

            if parsed is None:
                stderr_tail = ""
                try:
                    stderr_tail = stderr_path.read_text(
                        encoding="utf-8", errors="replace"
                    )[-1000:]
                except OSError:
                    pass
                message = (
                    f"OCR exited with code {exit_code} without a usable result."
                    if exit_code
                    else (parse_error or "OCR produced no parseable result.")
                )
                detail = redact_text(stderr_tail).strip()
                await queue.transition(
                    job,
                    "failed",
                    message=message,
                    error_code="ocr_exit",
                    payload={"detail": detail[:500], "exit_code": exit_code},
                )
                job.status_message = (
                    f"{message} {detail[:300]}".strip() if detail else message
                )
            else:
                # Replace any prior findings (idempotent re-finalization).
                await session.execute(
                    sa_delete(models.Finding).where(models.Finding.job_id == job.id)
                )
                for item in parsed.findings:
                    session.add(
                        models.Finding(
                            job_id=job.id,
                            path=item.path,
                            content=item.content,
                            start_line=item.start_line,
                            end_line=item.end_line,
                            existing_code=item.existing_code,
                            suggestion_code=item.suggestion_code,
                            thinking=item.thinking,
                            category=item.category,
                            severity=item.severity,
                        )
                    )
                summary = parsed.summary.model_dump()
                summary["warnings"] = len(parsed.warnings)
                job.result_summary_json = summary
                job.warnings_json = [w.model_dump() for w in parsed.warnings]
                job.ocr_session_id = parsed.session_id or job.ocr_session_id
                job.result_json_path = str(result_path)
                if parsed.status == "completed_with_warnings" or parsed.warnings:
                    final = "completed_with_warnings"
                elif parsed.status in {"completed", "ok", "success"} or exit_code == 0:
                    final = "completed"
                else:
                    final = "failed"
                if final == "failed":
                    await queue.transition(
                        job,
                        "failed",
                        message=parsed.message or "OCR reported a failure.",
                        error_code="ocr_reported_failure",
                        payload={"exit_code": exit_code},
                    )
                else:
                    await queue.transition(
                        job,
                        final,
                        message=parsed.message,
                        payload={"summary": summary, "exit_code": exit_code},
                    )
                    await queue.emit_event(
                        job.id, "job.summary", {"summary": summary}
                    )
            await session.commit()

        await self._write_metadata(job_id, exit_code)
        await self._apply_retention()

    def _recover_result_from_stdout(
        self, stdout_path: Path, result_path: Path
    ) -> Path | None:
        """OCR prints JSON to stdout; persist it as the job's result.json."""

        try:
            text = stdout_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        text = text.strip()
        if not text:
            return None
        # Try the whole output first, then the last JSON-looking block.
        candidates = [text]
        last_brace = text.rfind("\n{")
        if last_brace != -1:
            candidates.append(text[last_brace + 1 :])
        for candidate in candidates:
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and (
                "status" in data or "comments" in data or "findings" in data
            ):
                result_path.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                return result_path
        return None

    async def _write_metadata(self, job_id: str, exit_code: int | None) -> None:
        """metadata.json with credentials redacted (SPEC §10)."""

        factory = get_session_factory()
        async with factory() as session:
            job = await session.get(models.ReviewJob, job_id)
            if job is None:
                return
            command = dict(job.generated_command_json or {})
            metadata = {
                "job_id": job.id,
                "project_id": job.project_id,
                "mode": job.mode,
                "status": job.status,
                "argv": command.get("argv"),
                "env": redact_environment(dict(command.get("env") or {})),
                "ocr_version": job.ocr_version,
                "ocr_session_id": job.ocr_session_id,
                "exit_code": exit_code,
                "queued_at": job.queued_at.isoformat() if job.queued_at else None,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "completed_at": (
                    job.completed_at.isoformat() if job.completed_at else None
                ),
            }
        metadata = redactor.redact_mapping(metadata)
        path = self.settings.job_dir(job_id) / "metadata.json"
        try:
            path.write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            logger.warning("metadata_write_failed", job_id=job_id)

    async def _apply_retention(self) -> None:
        """Delete job artifact dirs past the retention window (SPEC §10/§28)."""

        days = self.settings.artifact_retention_days
        if days <= 0:
            return
        cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
        jobs_dir = self.settings.jobs_dir
        if not jobs_dir.is_dir():
            return
        factory = get_session_factory()
        for child in jobs_dir.iterdir():
            if not child.is_dir():
                continue
            try:
                if child.stat().st_mtime > cutoff:
                    continue
                async with factory() as session:
                    job = await session.get(models.ReviewJob, child.name)
                    if job is not None and job.status in {
                        "queued", "preparing", "running", "cancelling"
                    }:
                        continue
                shutil.rmtree(child, ignore_errors=True)
            except OSError:
                continue
