"""Startup recovery: interrupted jobs + orphan worktree cleanup (SPEC §11)."""

from __future__ import annotations

from pathlib import Path

from app.db import models
from app.db.session import session_scope
from app.queue.recovery import (
    cleanup_orphan_worktrees,
    recover_interrupted_jobs,
    run_startup_recovery,
)
from app.services.deps import get_git_service


async def _seed_job(project_id: str, status: str) -> str:
    async with session_scope() as session:
        job = models.ReviewJob(
            project_id=project_id,
            mode="commit",
            commit_ref="HEAD",
            status=status,
            configuration_snapshot_json={},
            generated_command_json={"argv": ["ocr", "review"]},
        )
        session.add(job)
        await session.flush()
        return job.id


async def test_interrupted_recovery_marks_active_jobs(project) -> None:
    project_id, _ = project
    stuck = [
        await _seed_job(project_id, "preparing"),
        await _seed_job(project_id, "running"),
        await _seed_job(project_id, "cancelling"),
    ]
    queued = await _seed_job(project_id, "queued")
    done = await _seed_job(project_id, "completed")

    count = await recover_interrupted_jobs()
    assert count == 3

    async with session_scope() as session:
        for job_id in stuck:
            job = await session.get(models.ReviewJob, job_id)
            assert job.status == "interrupted"
            assert job.process_id is None
        assert (await session.get(models.ReviewJob, queued)).status == "queued"
        assert (await session.get(models.ReviewJob, done)).status == "completed"

        events = (
            await session.execute(
                models.JobEvent.__table__.select().where(
                    models.JobEvent.job_id.in_(stuck)
                )
            )
        ).all()
        assert len(events) == 3  # one persisted event per transition


async def test_orphan_worktree_cleanup(settings, project, make_worker, fake_ocr) -> None:
    """App-created worktrees of terminal jobs are removed; unknown dirs are
    left untouched (SPEC §11 'never delete unrecorded directories')."""

    project_id, project_path = project
    git = get_git_service()

    # Recorded app-created worktree layout: <worktrees>/<project>/<job>.
    finished_job = await _seed_job(project_id, "interrupted")
    orphan = settings.worktree_path(project_id, finished_job)
    orphan.mkdir(parents=True)
    (orphan / "marker.txt").write_text("x", encoding="utf-8")

    # An unknown directory that must survive.
    stranger = settings.worktrees_dir / "not-a-uuid"
    stranger.mkdir(parents=True)
    (stranger / "keep.txt").write_text("x", encoding="utf-8")

    removed = await cleanup_orphan_worktrees(settings, git)
    assert str(orphan) in removed
    assert not orphan.exists()
    assert stranger.exists()
    assert (stranger / "keep.txt").exists()


async def test_run_startup_recovery_combined(settings, project) -> None:
    project_id, _ = project
    await _seed_job(project_id, "running")
    result = await run_startup_recovery(settings, get_git_service())
    assert result["interrupted_jobs"] == 1
    assert isinstance(result["worktrees_removed"], list)
