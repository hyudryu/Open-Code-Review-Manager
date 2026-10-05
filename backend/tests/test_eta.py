"""ETA estimation tests: pure math + :class:`EtaService` across job states.

The pure helpers are tested directly; the service tests seed jobs and their
persisted progress events to exercise queued / running / terminal branches.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.db import models
from app.db.session import session_scope
from app.services.eta import (
    EtaService,
    blend_pace,
    file_work_seconds,
    fit_size_model,
    format_eta,
    micro_progress_files,
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


def test_progress_percent_micro_credit() -> None:
    # Model requests are themselves small progress: each credits a fraction
    # of a file so the bar moves before the first file completes.
    assert progress_percent(0, 10, model_requests=5) == 5.0
    assert progress_percent(0, 18, model_requests=3) == 1.7
    # Completed files and the request credit add up, clamped at 100.
    assert progress_percent(1, 10, model_requests=30) == 30.0
    assert progress_percent(10, 10, model_requests=50) == 100.0


def test_micro_progress_files_caps_request_credit() -> None:
    assert micro_progress_files(0) == 0.0
    assert micro_progress_files(1) == pytest.approx(0.1)
    assert micro_progress_files(19) == pytest.approx(1.9)
    assert micro_progress_files(20) == 2.0
    assert micro_progress_files(500) == 2.0  # capped


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


# --- size model --------------------------------------------------------------


def test_fit_size_model_recovers_coefficients() -> None:
    # Points exactly on runtime = 60*files + 0.5*lines.
    samples = [(160.0, 1, 200), (170.0, 2, 100), (440.0, 4, 400)]
    fit = fit_size_model(samples)
    assert fit is not None
    alpha, beta = fit
    assert alpha == pytest.approx(60.0, abs=1e-6)
    assert beta == pytest.approx(0.5, abs=1e-6)


def test_fit_size_model_needs_enough_samples() -> None:
    assert fit_size_model([]) is None
    assert fit_size_model([(100.0, 1, 50)]) is None
    assert fit_size_model([(100.0, 1, 50), (200.0, 2, 100)]) is None


def test_fit_size_model_rejects_singular_system() -> None:
    # All jobs the same shape: files and lines are collinear, alpha/beta
    # cannot be separated.
    samples = [(100.0, 1, 50), (200.0, 2, 100), (300.0, 3, 150)]
    assert fit_size_model(samples) is None


def test_fit_size_model_rejects_negative_coefficients() -> None:
    # Runtime falling as size grows is noise, not a usable model.
    samples = [(300.0, 1, 100), (200.0, 2, 200), (100.0, 3, 300)]
    assert fit_size_model(samples) is None


def test_file_work_seconds() -> None:
    assert file_work_seconds(60.0, 0.5, 100, 0) == 110.0
    assert file_work_seconds(60.0, 0.5, 0, 0) == 60.0
    # Negative/None-ish inputs are clamped, never negative work.
    assert file_work_seconds(60.0, 0.5, -5, -5) == 60.0


def test_running_eta_seconds_size_aware() -> None:
    # No completions: the fitted model is the estimate (multiplier prior 1.0).
    assert running_eta_seconds(
        total_files=2,
        completed_files=0,
        elapsed_seconds=500.0,
        remaining_work=220.0,
        completed_work=None,
    ) == 220.0
    # Completions correct the model: elapsed twice the predicted completed
    # work → blended multiplier (3*1.0 + 2*1)/4 = 1.25.
    assert running_eta_seconds(
        total_files=2,
        completed_files=1,
        elapsed_seconds=220.0,
        remaining_work=110.0,
        completed_work=110.0,
    ) == pytest.approx(137.5)
    # Converges toward the observed multiplier as completions accumulate
    # (prior of 1.0 drowns out; observed here is 2.0 × predicted).
    converged = running_eta_seconds(
        total_files=3100,
        completed_files=3000,
        elapsed_seconds=60000.0,
        remaining_work=30000.0,
        completed_work=30000.0,
    )
    assert 59000.0 < converged < 60000.0
    # Everything done or nothing left to price → 0.
    assert running_eta_seconds(
        total_files=2,
        completed_files=2,
        elapsed_seconds=100.0,
        remaining_work=0.0,
        completed_work=100.0,
    ) == 0.0
    assert running_eta_seconds(
        total_files=2,
        completed_files=0,
        elapsed_seconds=0.0,
        remaining_work=0.0,
        completed_work=None,
    ) == 0.0
    # Legacy path untouched when no work sums are given.
    assert running_eta_seconds(
        total_files=5, completed_files=1, elapsed_seconds=100.0
    ) == 400.0


def test_size_fit_for_prefers_exact_bucket_then_model_then_global() -> None:
    history = {
        "size_fits_by_bucket": {("m1", 4): (10.0, 1.0)},
        "size_fits_by_model": {"m1": (20.0, 2.0), "m2": (30.0, 3.0)},
        "size_fit_global": (40.0, 4.0),
    }

    def _job(model, concurrency):
        return SimpleNamespace(
            configuration_snapshot_json={
                "model": {"model_id": model},
                "settings": {"concurrency": concurrency},
            }
        )

    resolve = EtaService._size_fit_for
    assert resolve(_job("m1", 4), history) == (10.0, 1.0)  # exact bucket
    assert resolve(_job("m1", 99), history) == (20.0, 2.0)  # model fallback
    assert resolve(_job("m3", 7), history) == (40.0, 4.0)  # global fallback
    # Missing snapshot keys degrade gracefully instead of raising.
    assert resolve(SimpleNamespace(configuration_snapshot_json={}), history) == (
        40.0,
        4.0,
    )


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
        "model_requests": 0,
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


async def test_running_job_micro_progress_from_model_requests(project) -> None:
    # Requests observed before the first completion still register progress.
    project_id, _ = project
    job_id = await _seed_job(
        project_id,
        status="running",
        started_at=datetime.now(timezone.utc) - timedelta(seconds=30),
    )
    await _add_event(job_id, "job.inventory", {"total_files": 5})
    for count in (1, 2, 3):
        await _add_event(job_id, "job.model_request", {"count": count, "seq": count})
    # A delayed out-of-order count must not lower the running total.
    await _add_event(job_id, "job.model_request", {"count": 2, "seq": 9})

    result = await _describe(job_id)
    assert result["progress"]["model_requests"] == 3
    assert result["progress"]["completed_files"] == 0
    assert result["progress"]["percent"] == 6.0  # 3 * 0.1 files / 5 files


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


async def test_running_job_started_only_stays_unknown(project) -> None:
    # No ``job.inventory`` event: ``_read_progress`` falls back to a synthetic
    # total derived from file_started events. That synthetic total must NOT be
    # treated as a real denominator, or the historical fallback would report
    # ~one file of ETA for what is really an unknown-size review.
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
        started_at=datetime.now(timezone.utc) - timedelta(seconds=30),
    )
    # file_started drives the synthetic denominator, but there is no inventory.
    await _add_event(job_id, "job.file_started", {"file": "a.py"})
    await _add_event(job_id, "job.file_started", {"file": "b.py"})

    result = await _describe(job_id)
    # Progress surfaces the started-derived total for display, but ETA stays
    # unknown because the real inventory is missing.
    assert result["progress"]["total_files"] == 2
    assert result["eta_seconds"] is None
    assert result["eta"] is None
    assert result["poll_interval_seconds"] == 5


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


# --- size-aware ETA (service level) -------------------------------------------


def _even_stats(files: int, lines: int) -> list[dict]:
    """file_stats entries splitting ``lines`` changed lines across ``files``."""

    per = lines // files if files else 0
    stats = []
    for i in range(files):
        insertions = per + (lines - per * files if i == 0 else 0)
        stats.append({"path": f"f{i}.py", "insertions": insertions, "deletions": 0})
    return stats


async def _seed_completed_with_stats(
    project_id: str,
    *,
    snapshot: dict,
    files: int,
    lines: int,
    runtime_s: float,
    now: datetime,
) -> None:
    job_id = await _seed_job(
        project_id,
        status="completed",
        started_at=now - timedelta(seconds=runtime_s),
        completed_at=now,
        result_summary_json={"files_reviewed": files},
        configuration_snapshot_json=snapshot,
    )
    stats = _even_stats(files, lines)
    await _add_event(
        job_id,
        "job.inventory",
        {"files": [s["path"] for s in stats], "total_files": files, "file_stats": stats},
    )


_SNAPSHOT = {"model": {"model_id": "m1"}, "settings": {"concurrency": 4}}


async def test_running_job_size_aware_initial_estimate(project) -> None:
    # With per-file stats and a fittable history, the 0-completion estimate
    # prices each remaining file by size instead of counting files equally.
    project_id, _ = project
    now = datetime.now(timezone.utc)
    # Runtimes exactly on runtime = 60*files + 0.5*lines.
    for files, lines, runtime in ((1, 200, 160.0), (2, 100, 170.0), (4, 400, 440.0)):
        await _seed_completed_with_stats(
            project_id,
            snapshot=_SNAPSHOT,
            files=files,
            lines=lines,
            runtime_s=runtime,
            now=now,
        )
    job_id = await _seed_job(
        project_id,
        status="running",
        started_at=now - timedelta(seconds=5),
        configuration_snapshot_json=_SNAPSHOT,
    )
    stats = [
        {"path": "a.py", "insertions": 100, "deletions": 0},
        {"path": "b.py", "insertions": 0, "deletions": 100},
    ]
    await _add_event(
        job_id,
        "job.inventory",
        {"files": ["a.py", "b.py"], "total_files": 2, "file_stats": stats},
    )

    result = await _describe(job_id)
    # Each remaining file costs 60 + 0.5*100 = 110s of fitted wall time.
    assert result["eta_seconds"] == 220
    assert result["eta"] == "about 3 min"


async def test_running_job_size_aware_uses_observed_pace(project) -> None:
    # Once a file completes, the job's own elapsed-to-predicted ratio corrects
    # the fitted model: elapsed = 2x the completed file's predicted cost
    # → blended multiplier (3*1.0 + 2*1)/4 = 1.25.
    project_id, _ = project
    now = datetime.now(timezone.utc)
    for files, lines, runtime in ((1, 200, 160.0), (2, 100, 170.0), (4, 400, 440.0)):
        await _seed_completed_with_stats(
            project_id,
            snapshot=_SNAPSHOT,
            files=files,
            lines=lines,
            runtime_s=runtime,
            now=now,
        )
    job_id = await _seed_job(
        project_id,
        status="running",
        started_at=now - timedelta(seconds=220),
        configuration_snapshot_json=_SNAPSHOT,
    )
    stats = [
        {"path": "a.py", "insertions": 100, "deletions": 0},
        {"path": "b.py", "insertions": 0, "deletions": 100},
    ]
    await _add_event(
        job_id,
        "job.inventory",
        {"files": ["a.py", "b.py"], "total_files": 2, "file_stats": stats},
    )
    await _add_event(job_id, "job.file_completed", {"file": "a.py", "comments": 0})

    result = await _describe(job_id)
    # Observed multiplier = elapsed / predicted completed work (110s); blended
    # with the 1.0 prior at weight 3: 110 * (3 + observed) / 4, ceiled.
    async with session_scope() as session:
        job = await session.get(models.ReviewJob, job_id)
        elapsed = (
            datetime.now(timezone.utc) - job.started_at.replace(tzinfo=timezone.utc)
        ).total_seconds()
    observed = elapsed / 110.0
    assert result["eta_seconds"] == math.ceil(110 * (3 + observed) / 4)


async def test_running_job_partial_stats_falls_back_to_history(project) -> None:
    # Inventory stats that do not cover every reviewable file must not be
    # priced partially — the legacy per-file average takes over.
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
        started_at=now - timedelta(seconds=5),
        configuration_snapshot_json=_SNAPSHOT,
    )
    await _add_event(
        job_id,
        "job.inventory",
        {
            "files": ["a.py", "b.py"],
            "total_files": 2,
            "file_stats": [{"path": "a.py", "insertions": 100, "deletions": 0}],
        },
    )

    result = await _describe(job_id)
    # Legacy estimate: 2 remaining files × (100s / 5 files) historical average.
    assert result["eta_seconds"] == 40
