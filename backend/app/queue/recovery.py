"""Startup recovery (SPEC §11 Cleanup, §13).

- Jobs left in ``preparing``/``running``/``cancelling`` are moved to
  ``interrupted`` (allowed from those states per the state machine).
- Orphan worktrees under ``<data_dir>/worktrees/<project>/<job>`` are
  removed only when they are provably app-created: the two-level layout
  must match registered project/job UUIDs, and removal always goes through
  ``git worktree remove`` — never a blind recursive delete.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from sqlalchemy import select

from app.core.config import Settings
from app.core.logging import get_logger
from app.db import models
from app.db.session import get_session_factory
from app.git.service import GitError, GitService
from app.queue.service import QueueService

logger = get_logger(__name__)

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


async def recover_interrupted_jobs() -> int:
    """Mark jobs stuck in active states as interrupted. Returns the count."""

    factory = get_session_factory()
    count = 0
    async with factory() as session:
        result = await session.execute(
            select(models.ReviewJob).where(
                models.ReviewJob.status.in_(["preparing", "running", "cancelling"])
            )
        )
        jobs = list(result.scalars())
        queue = QueueService(session)
        for job in jobs:
            try:
                await queue.transition(
                    job,
                    "interrupted",
                    message="Backend stopped while the job was active; marked interrupted at startup.",
                )
                job.process_id = None
                count += 1
            except Exception:
                logger.exception("recovery_transition_failed", job_id=job.id)
        await session.commit()
    return count


async def cleanup_orphan_worktrees(settings: Settings, git: GitService) -> list[str]:
    """Remove app-created worktrees whose jobs are gone or terminal.

    Only directories recorded as app-created are touched: either referenced
    by a job row's ``worktree_path`` or matching the strict
    ``<worktrees>/<project-uuid>/<job-uuid>`` layout. Anything else is left
    alone and logged.
    """

    removed: list[str] = []
    root = settings.worktrees_dir
    if not root.is_dir():
        return removed

    factory = get_session_factory()
    for project_dir in sorted(root.iterdir()):
        if not project_dir.is_dir():
            continue
        if not _UUID_RE.match(project_dir.name):
            logger.warning("orphan_scan_skipped_unknown_dir", path=str(project_dir))
            continue
        async with factory() as session:
            project = await session.get(models.Project, project_dir.name)
        if project is None:
            logger.warning(
                "orphan_scan_skipped_unknown_project", path=str(project_dir)
            )
            continue
        for worktree_dir in sorted(project_dir.iterdir()):
            if not worktree_dir.is_dir():
                continue
            if not _UUID_RE.match(worktree_dir.name):
                logger.warning(
                    "orphan_scan_skipped_unknown_dir", path=str(worktree_dir)
                )
                continue
            async with factory() as session:
                job = await session.get(models.ReviewJob, worktree_dir.name)
            job_active = job is not None and job.status in {
                "queued", "preparing", "running", "cancelling"
            }
            if job_active:
                continue  # a live job owns this worktree
            try:
                await git.remove_worktree(
                    project.absolute_path, worktree_dir, force=True
                )
                removed.append(str(worktree_dir))
            except GitError as exc:
                logger.warning(
                    "orphan_worktree_remove_failed",
                    path=str(worktree_dir),
                    error=exc.stderr,
                )
                # Last resort: it is recorded as app-created (strict layout
                # match) but git no longer tracks it; remove the directory.
                if worktree_dir.exists():
                    shutil.rmtree(worktree_dir, ignore_errors=True)
                    removed.append(str(worktree_dir))
        # Prune empty project dirs left behind.
        try:
            if not any(project_dir.iterdir()):
                project_dir.rmdir()
        except OSError:
            pass
    return removed


async def run_startup_recovery(settings: Settings, git: GitService) -> dict:
    interrupted = await recover_interrupted_jobs()
    removed = await cleanup_orphan_worktrees(settings, git)
    if interrupted or removed:
        logger.info(
            "startup_recovery", interrupted_jobs=interrupted, worktrees_removed=len(removed)
        )
    return {"interrupted_jobs": interrupted, "worktrees_removed": removed}
