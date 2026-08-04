"""ETA estimation tests: pure math + :class:`EtaService` across job states.

The pure helpers are tested directly; the service tests seed jobs and their
persisted progress events to exercise queued / running / terminal branches.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db import models
from app.db.session import session_scope
from app.services.eta import (
    EtaService,
    blend_pace,
    format_eta,
    poll_interval_seconds,
    progress_percent,
    running_eta_seconds,
)


# --- pure helpers ------------------------------------------------------------


def test_progress_percent() -> None:
    assert progress_percent(0, 10) == 0.0
    assert progress_percent(1, 4) == 25.0
    assert progress_percent(99, 100) == 99.0
    assert progress_percent(5, 5) == 100.0
    assert progress_percent(2, None) is None
    assert progress_percent(2, 0) is None


def test_blend_pace_prefers_own_pace_as_files_complete() -> None:
    # No history yet → the observed pace wins outright.
    assert blend_pace(10.0, None, 1) == 10.0
    assert blend_pace(10.0, 0, 1) == 10.0
    # History counts as HISTORY_PRIOR_WEIGHT pseudo-observations.
    assert blend_pace(10.0, 100.0, 0) == 100.0
    early = blend_pace(30.0, 10.0, 1)
    assert early < 30.0  # pulled down by the fast historical average
    later = blend_pace(30.0, 10.0, 100)
    assert 28.0 < later < 31.0  # converges to the job's own pace


def test_running_eta_seconds() -> None:
    # Known inventory + one completion → extrapolate remaining files.
    assert running_eta_seconds(
        total_files=5, completed_files=1, elapsed_seconds=100.0
    ) == 400.0
    # All done → 0.
    assert running_eta_seconds(
        total_files=5, completed_files=5, elapsed_seconds=100.0
    ) == 0.0
    # No inventory → unknown.
    assert running_eta_seconds(
        total_files=None, completed_files=1, elapsed_seconds=100.0
    ) is None
    # Known inventory but no observed pace yet (no completions / no elapsed):
    # with history we fall back to the historical-only estimate (matches the
    # frontend), without history it stays unknown.
    assert running_eta_seconds(
        total_files=5, completed_files=0, elapsed_seconds=100.0
    ) is None
    assert running_eta_seconds(
        total_files=5, completed_files=1, elapsed_seconds=0.0
    ) is None
    assert running_eta_seconds(
        total_files=5,
        completed_files=0,
        elapsed_seconds=0.0,
        historical_per_file=12.0,
    ) == 60.0  # 5 remaining * 12 s/file
    assert running_eta_seconds(
        total_files=5,
        completed_files=1,
        elapsed_seconds=0.0,
        historical_per_file=12.0,
    ) == 48.0  # 4 remaining * 12 s/file
    # Non-positive history is treated as no history → unknown.
    assert running_eta_seconds(
        total_files=5, completed_files=0, elapsed_seconds=0.0, historical_per_file=0.0
    ) is None
    assert running_eta_seconds(
        total_files=5,
        completed_files=0,
        elapsed_seconds=0.0,
        historical_per_file=-1.0,
    ) is None


def test_format_eta() -> None:
    assert format_eta(None) is None
    assert format_eta(0) == "now"
    assert format_eta(1) == "about 1 s"
    assert format_eta(120) == "about 2 min"  # exactly 2 minutes
    assert format_eta(150) == "about 2 min"  # 2 min 30 s
    assert format_eta(180) == "about 3 min"  # exactly 3 minutes
    assert format_eta(7200) == "about 2 h 0 min"


def test_poll_interval_seconds() -> None:
    assert poll_interval_seconds(0, running=True) == 0
    assert poll_interval_seconds(0, running=False) == 0
    # Unknown → status-specific fallback.
    assert poll_interval_seconds(None, running=True) == 5
    assert poll_interval_seconds(None, running=False) == 10
    # Known → bounded fraction of the remaining time.
    assert poll_interval_seconds(10, running=True) == 5
    assert poll_interval_seconds(30_000, running=True) == 30
    assert poll_interval_seconds(1, running=True) == 5


# --- EtaService across job states ---------------------------------------------


async def _seed_job(project_id: str, **kwargs) -> str:
    async with session_scope() as session:
        job = models.ReviewJob(
            project_id=project_id,
            source="mcp",
            mode="commit",
            priority=50,
            **kwargs,
        )
        session.add(job)
        await session.flush()
        job_id = job.id
        await session.commit()
    return job_id


async def _add_event(job_id: str, event_type: str, payload: dict) -> None:
    async with session_scope() as session:
        session.add(
            models.JobEvent(job_id=job_id, event_type=event_type, payload_json=payload)
        )
        await session.commit()


async def _describe(job_id: str) -> dict:
    async with session_scope() as session:
        job = await session.get(models.ReviewJob, job_id)
        return await EtaService(session).describe(job)


async def test_terminal_job_stops_polling(project) -> None:
    project_id, _ = project
    job_id = await _seed_job(
        project_id,
        status="completed",
        started_at=datetime.now(timezone.utc) - timedelta(seconds=60),
        completed_at=datetime.now(timezone.utc),
        result_summary_json={"files_reviewed": 1, "comments": 0},
    )
    result = await _describe(job_id)
    assert result["eta_seconds"] == 0
    assert result["eta"] == "now"
    assert result["poll_interval_seconds"] == 0
    assert result["progress"] == {
        "total_files": None,
        "completed_files": 0,
        "percent": None,
    }


async def test_running_job_eta_from_progress(project) -> None:
    project_id, _ = project
    job_id = await _seed_job(
        project_id,
        status="running",
        started_at=datetime.now(timezone.utc) - timedelta(seconds=100),
    )
    await _add_event(job_id, "job.inventory", {"total_files": 5})
    await _add_event(job_id, "job.file_started", {"file": "a.py"})
    await _add_event(job_id, "job.file_completed", {"file": "a.py", "comments": 1})

    result = await _describe(job_id)
    assert result["progress"]["total_files"] == 5
    assert result["progress"]["completed_files"] == 1
    assert result["progress"]["percent"] == 20.0
    assert result["eta_seconds"] is not None and result["eta_seconds"] > 0
    assert result["poll_interval_seconds"] in (5, 10, 15, 20, 25, 30)


async def test_running_job_without_inventory_is_unknown(project) -> None:
    project_id, _ = project
    job_id = await _seed_job(
        project_id,
        status="running",
        started_at=datetime.now(timezone.utc) - timedelta(seconds=50),
    )
    result = await _describe(job_id)
    assert result["eta_seconds"] is None
    assert result["eta"] is None
    assert result["poll_interval_seconds"] == 5


async def test_running_job_no_completions_uses_history(project) -> None:
    # A running job with a known inventory but zero completed files still
    # produces an estimate by falling back to the historical per-file average
    # (mirrors the frontend's estimateActiveJobETA).
    project_id, _ = project
    now = datetime.now(timezone.utc)
    await _seed_job(
        project_id,
        status="completed",
        started_at=now - timedelta(seconds=100),
        completed_at=now,
        result_summary_json={"files_reviewed": 5},
    )
    job_id = await _seed_job(
        project_id,
        status="running",
        started_at=datetime.now(timezone.utc) - timedelta(seconds=10),
    )
    await _add_event(job_id, "job.inventory", {"total_files": 5})
    # No file_completed events — no observed pace.

    result = await _describe(job_id)
    assert result["progress"]["total_files"] == 5
    assert result["progress"]["completed_files"] == 0
    assert result["progress"]["percent"] == 0.0
    assert result["eta_seconds"] is not None and result["eta_seconds"] > 0
    assert result["eta"] is not None
    assert result["poll_interval_seconds"] in (5, 10, 15, 20, 25, 30)


async def test_queued_job_no_history_unknown(project) -> None:
    project_id, _ = project
    job_id = await _seed_job(project_id, status="queued", queue_position=1)
    result = await _describe(job_id)
    assert result["eta_seconds"] is None
    assert result["eta"] is None
    assert result["poll_interval_seconds"] == 10


async def test_queued_job_with_history_estimates(project) -> None:
    project_id, _ = project
    now = datetime.now(timezone.utc)
    # A recently completed job provides the historical timing baseline.
    await _seed_job(
        project_id,
        status="completed",
        started_at=now - timedelta(seconds=60),
        completed_at=now,
        result_summary_json={"files_reviewed": 1},
    )
    job_id = await _seed_job(project_id, status="queued", queue_position=1)
    result = await _describe(job_id)
    assert result["eta_seconds"] is not None and result["eta_seconds"] > 0
    assert result["poll_interval_seconds"] >= 5
