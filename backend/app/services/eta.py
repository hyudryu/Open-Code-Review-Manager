"""Server-side job ETA estimation: progress + remaining time + poll interval.

Session-scoped helpers live in :class:`EtaService`; the math itself is in the
pure, DB-free helpers below so it can be unit-tested directly. The MCP job
tools (``ocr_get_job`` / ``ocr_get_job_results``) and the REST job-detail
endpoint attach the produced ``{progress, eta_seconds, eta,
poll_interval_seconds}`` dict to their responses so an agent knows how long to
wait before polling again.

Estimates are derived only from data already in the DB — no extra persistence
and no changes to the OCR process:

- Running jobs prefer a **size-aware** estimate when the inventory carries
  per-file changed-line counts and history can fit a runtime model
  (``runtime ≈ alpha * files + beta * changed_lines``, fitted per
  model/concurrency bucket). Files count by predicted cost, not equally, and
  once files complete the job's own elapsed-to-predicted ratio corrects the
  estimate (blended against a prior of 1.0). Without sizes the estimate blends
  the job's observed per-file pace with a historical per-file average.
- Queued jobs extrapolate from ``active-running-remaining + (position-1) *
  avg_runtime + avg_runtime`` using recent completed jobs.
- Terminal jobs report 0 and ask the caller to stop polling.

Anything we cannot time (a running job with no inventory yet, or a queued job
with no server history) returns ``eta_seconds=None`` with a conservative
``poll_interval_seconds`` so the agent still paces itself.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import select

from app.db import models
from app.queue.service import TERMINAL_STATUSES
from app.services.deps import ServiceBase

#: How much the historical per-file average is trusted as pseudo-observations
#: before the job's own pace has been seen (fewer completed files → the
#: historical average dominates; more completions → the job's own pace wins).
HISTORICAL_PRIOR_WEIGHT = 3

#: Suggested poll-interval bounds for jobs we can time (seconds).
_MIN_POLL_SECONDS = 5
_MAX_POLL_SECONDS = 30
#: Fallback interval when the remaining time is unknown (seconds).
_RUNNING_UNKNOWN_POLL_SECONDS = 5
_QUEUED_UNKNOWN_POLL_SECONDS = 10

#: How many recent completed jobs inform the historical timing averages.
_HISTORY_LIMIT = 30

#: Minimum completed jobs with changed-line stats before a size model is
#: fitted; below this the data cannot separate per-file overhead from
#: per-line cost reliably.
_MIN_FIT_SAMPLES = 3

#: Micro-progress credit for observed model requests. Each request counts as a
#: fraction of a completed file so the bar creeps forward while
#: planning/grouping requests run before the first file completes. The credit
#: is capped so request chatter can never dominate real file completions.
MICRO_STEP_FILES = 0.1
MICRO_CAP_FILES = 2.0


def micro_progress_files(model_requests: int) -> float:
    """File-equivalents credited for observed model requests (bounded)."""

    if model_requests <= 0:
        return 0.0
    return min(model_requests * MICRO_STEP_FILES, MICRO_CAP_FILES)


def progress_percent(
    completed_files: int,
    total_files: int | None,
    model_requests: int = 0,
) -> float | None:
    """Completion percentage (0–100, one decimal) or ``None`` if unknown.

    Completed files plus the bounded model-request micro credit over the
    inventory total; the micro credit lets the bar move between completions.
    """

    if not total_files or total_files <= 0:
        return None
    credit = completed_files + micro_progress_files(model_requests)
    return min(100.0, round(credit / total_files * 100.0, 1))


def blend_pace(
    observed_per_file: float,
    historical_per_file: float | None,
    completed_files: int,
) -> float:
    """Blend a job's own observed pace with the historical per-file average.

    The historical average counts as ``HISTORICAL_PRIOR_WEIGHT`` pseudo-
    observations; the observed pace counts one-for-one per completion, so the
    blended estimate converges to the job's true pace as files complete.
    """

    if historical_per_file is None or historical_per_file <= 0:
        return observed_per_file
    if completed_files <= 0:
        return historical_per_file
    return (
        historical_per_file * HISTORICAL_PRIOR_WEIGHT
        + observed_per_file * completed_files
    ) / (HISTORICAL_PRIOR_WEIGHT + completed_files)


def fit_size_model(
    samples: Sequence[tuple[float, int, int]],
) -> tuple[float, float] | None:
    """Least-squares fit of ``runtime ≈ alpha * files + beta * changed_lines``.

    Samples are ``(runtime_seconds, files_reviewed, changed_lines)`` triples
    from recent completed jobs, so the coefficients are wall-clock level: they
    already embed whatever concurrency those jobs ran with, which is why the
    fit is taken per (model, concurrency) bucket rather than globally.

    Returns ``(alpha, beta)`` — per-file fixed cost and seconds per changed
    line — or ``None`` when the data cannot support a fit: too few samples, a
    singular system (all jobs the same shape), or a negative coefficient
    (bigger reviews taking less time is noise, not signal).
    """

    if len(samples) < _MIN_FIT_SAMPLES:
        return None
    n = len(samples)
    sf = sum(s[1] for s in samples)
    ss = sum(s[2] for s in samples)
    sff = sum(s[1] * s[1] for s in samples)
    sss = sum(s[2] * s[2] for s in samples)
    sfs = sum(s[1] * s[2] for s in samples)
    sft = sum(s[1] * s[0] for s in samples)
    sst = sum(s[2] * s[0] for s in samples)
    det = sff * sss - sfs * sfs
    if det <= 1e-9 * max(sff * sss, 1.0):
        return None
    alpha = (sss * sft - sfs * sst) / det
    beta = (sff * sst - sfs * sft) / det
    if alpha < 0 or beta < 0:
        return None
    return alpha, beta


def file_work_seconds(alpha: float, beta: float, insertions: int, deletions: int) -> float:
    """Predicted wall-seconds for one file of the given changed-line size."""

    lines = max(0, (insertions or 0) + (deletions or 0))
    return alpha + beta * lines


def running_eta_seconds(
    *,
    total_files: int | None,
    completed_files: int,
    elapsed_seconds: float,
    historical_per_file: float | None = None,
    remaining_work: float | None = None,
    completed_work: float | None = None,
) -> float | None:
    """Estimated seconds remaining for a running job (``None`` = unknown).

    Requires a known inventory. Two paths:

    - **Size-aware** (``remaining_work`` given): remaining files are summed by
      their fitted per-file cost. The blended multiplier starts at the prior
      of 1.0 — the fit already reflects historical pace — and converges to the
      job's own ``elapsed / completed_work`` ratio, which absorbs startup
      overhead and concurrency dynamics the fit cannot see.
    - **Legacy**: a job with at least one completed file blends its own
      observed per-file pace with the historical average; a job that has not
      completed any file yet falls back to the historical per-file average so
      the estimate is stable from the start (mirroring the frontend).

    Returns 0 once every file has completed.
    """

    if total_files is None or total_files <= 0:
        return None
    remaining = total_files - completed_files
    if remaining <= 0:
        return 0.0
    if remaining_work is not None:
        if remaining_work <= 0:
            return 0.0
        if completed_files <= 0 or elapsed_seconds <= 0 or not completed_work:
            # No observed correction yet — the fitted model is the estimate.
            return remaining_work
        observed_mult = elapsed_seconds / completed_work
        blended = blend_pace(observed_mult, 1.0, completed_files)
        return blended * remaining_work
    if completed_files <= 0 or elapsed_seconds <= 0:
        # No observed pace yet — fall back to the historical-only estimate
        # (matches estimateActiveJobETA on the frontend). Unknown when there
        # is no history to lean on either.
        if historical_per_file is not None and historical_per_file > 0:
            return remaining * historical_per_file
        return None
    observed = elapsed_seconds / completed_files
    blended = blend_pace(observed, historical_per_file, completed_files)
    return remaining * blended


def format_eta(eta_seconds: float | None) -> str | None:
    """Human-readable ETA string (``"about 3 min"``) or ``None``."""

    if eta_seconds is None:
        return None
    if eta_seconds <= 0:
        return "now"
    seconds = int(math.ceil(eta_seconds))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"about {hours} h {minutes} min"
    if minutes:
        return f"about {minutes} min"
    return f"about {seconds} s"


def poll_interval_seconds(eta_seconds: float | None, *, running: bool) -> int:
    """Suggested seconds to wait before polling again, bucketed and bounded.

    ``eta_seconds=0`` (already done) → 0. A known ETA is polled at a bounded
    fraction of the remaining time; an unknown ETA falls back to a conservative
    status-specific interval.
    """

    if eta_seconds is not None and eta_seconds <= 0:
        return 0
    if eta_seconds is None:
        return (
            _RUNNING_UNKNOWN_POLL_SECONDS if running else _QUEUED_UNKNOWN_POLL_SECONDS
        )
    suggested = max(
        _MIN_POLL_SECONDS,
        min(_MAX_POLL_SECONDS, math.ceil(eta_seconds / 4)),
    )
    return int(suggested)


def _as_utc(value: datetime) -> datetime:
    """SQLite returns naive UTC; normalize to timezone-aware UTC."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _elapsed_seconds(job: models.ReviewJob, now: datetime | None = None) -> float:
    """Seconds since the job started (0 when it hasn't started yet)."""

    if job.started_at is None:
        return 0.0
    now = now or datetime.now(timezone.utc)
    return (now - _as_utc(job.started_at)).total_seconds()


class EtaService(ServiceBase):
    """Computes the job-detail ETA block from DB state (progress + history)."""

    async def _read_progress(self, job_id: str) -> dict[str, Any]:
        """Reconstruct progress from persisted inventory/file/request events."""

        stmt = (
            select(models.JobEvent)
            .where(
                models.JobEvent.job_id == job_id,
                models.JobEvent.event_type.in_(
                    [
                        "job.inventory",
                        "job.file_completed",
                        "job.file_started",
                        "job.model_request",
                    ]
                ),
            )
            .order_by(models.JobEvent.id)
        )
        result = await self.session.execute(stmt)
        total_files: int | None = None
        # Whether ``total_files`` came from a real ``job.inventory`` event.
        # The started-files fallback below is only a live denominator for
        # percent; it must NOT be trusted as the ETA denominator, or a review
        # that never received an inventory would be estimated as a 1-file job.
        has_real_inventory = False
        completed_files = 0
        seen_completed: set[str] = set()
        # job.file_started drives the live denominator when OCR 1.8+ emits no
        # explicit inventory and reviewable-count is unknown.
        started_files = 0
        model_requests = 0
        # Size-aware inputs from the inventory event: the reviewable file list
        # and each file's changed-line counts (absent for human-text previews).
        inventory_files: list[str] = []
        file_stats: dict[str, tuple[int, int]] = {}
        for event in result.scalars():
            payload = event.payload_json or {}
            if event.event_type == "job.inventory":
                count = payload.get("total_files")
                if isinstance(count, int) and count > 0:
                    total_files = count
                    has_real_inventory = True
                files = payload.get("files")
                if isinstance(files, list) and files:
                    inventory_files = [f for f in files if isinstance(f, str)]
                stats = payload.get("file_stats")
                if isinstance(stats, list) and stats:
                    parsed: dict[str, tuple[int, int]] = {}
                    for entry in stats:
                        if not isinstance(entry, dict):
                            continue
                        path = entry.get("path")
                        ins = entry.get("insertions")
                        dele = entry.get("deletions")
                        if path and isinstance(ins, int) and isinstance(dele, int):
                            parsed[path] = (ins, dele)
                    if parsed:
                        file_stats = parsed
            elif event.event_type == "job.file_started":
                started_files += 1
            elif event.event_type == "job.file_completed":
                path = payload.get("file")
                if path:
                    if path not in seen_completed:
                        seen_completed.add(path)
                        completed_files += 1
                else:
                    completed_files += 1
            elif event.event_type == "job.model_request":
                count = payload.get("count")
                if isinstance(count, int) and count > model_requests:
                    model_requests = count
        if total_files is None and started_files:
            total_files = started_files
        return {
            "total_files": total_files,
            "completed_files": completed_files,
            "model_requests": model_requests,
            "percent": progress_percent(completed_files, total_files, model_requests),
            "has_real_inventory": has_real_inventory,
            # Internal keys: used by the size-aware ETA path; stripped before
            # the progress dict reaches API/MCP responses.
            "inventory_files": inventory_files,
            "file_stats": file_stats,
            "completed_paths": seen_completed,
        }

    async def _history_stats(self) -> dict[str, Any]:
        """Timing averages and size-model fits from recent completed jobs.

        Fits are keyed wall-clock level, per (model_id, concurrency) bucket
        with a model-only and a global fallback, because the coefficients
        embed the concurrency those jobs ran at.
        """

        stmt = (
            select(models.ReviewJob)
            .where(
                models.ReviewJob.status.in_(sorted(TERMINAL_STATUSES)),
                models.ReviewJob.started_at.is_not(None),
                models.ReviewJob.completed_at.is_not(None),
            )
            .order_by(models.ReviewJob.completed_at.desc())
            .limit(_HISTORY_LIMIT)
        )
        result = await self.session.execute(stmt)
        jobs = list(result.scalars())
        runtimes: list[float] = []
        per_files: list[float] = []
        samples: list[dict[str, Any]] = []
        for job in jobs:
            try:
                runtime_s = (
                    _as_utc(job.completed_at) - _as_utc(job.started_at)
                ).total_seconds()
            except TypeError:  # pragma: no cover - defensive
                continue
            if runtime_s <= 0:
                continue
            runtimes.append(runtime_s)
            summary = job.result_summary_json or {}
            files = summary.get("files_reviewed") or 0
            if files and files > 0:
                per_files.append(runtime_s / files)
            snapshot = job.configuration_snapshot_json or {}
            samples.append(
                {
                    "id": job.id,
                    "runtime": runtime_s,
                    "files": files,
                    "model": (snapshot.get("model") or {}).get("model_id"),
                    "concurrency": (snapshot.get("settings") or {}).get(
                        "concurrency"
                    ),
                }
            )

        # One batched query for the inventory events of all sampled jobs.
        lines_by_job: dict[str, int] = {}
        if samples:
            inv_stmt = select(models.JobEvent.job_id, models.JobEvent.payload_json).where(
                models.JobEvent.job_id.in_([s["id"] for s in samples]),
                models.JobEvent.event_type == "job.inventory",
            )
            for job_id, payload in (await self.session.execute(inv_stmt)):
                stats = (payload or {}).get("file_stats") or []
                if not isinstance(stats, list) or not stats:
                    continue
                total = sum(
                    (entry.get("insertions") or 0) + (entry.get("deletions") or 0)
                    for entry in stats
                    if isinstance(entry, dict)
                )
                lines_by_job[job_id] = max(lines_by_job.get(job_id, 0), total)

        by_bucket: dict[tuple[str | None, int | None], list[tuple[float, int, int]]] = {}
        by_model: dict[str | None, list[tuple[float, int, int]]] = {}
        glob: list[tuple[float, int, int]] = []
        for sample in samples:
            lines = lines_by_job.get(sample["id"])
            if lines is None or sample["files"] <= 0:
                continue
            point = (sample["runtime"], sample["files"], lines)
            by_bucket.setdefault(
                (sample["model"], sample["concurrency"]), []
            ).append(point)
            by_model.setdefault(sample["model"], []).append(point)
            glob.append(point)

        return {
            "count": len(runtimes),
            "avg_runtime_s": (sum(runtimes) / len(runtimes)) if runtimes else None,
            "avg_per_file_s": (sum(per_files) / len(per_files)) if per_files else None,
            "size_fits_by_bucket": {
                key: fit for key, points in by_bucket.items() if (fit := fit_size_model(points))
            },
            "size_fits_by_model": {
                key: fit for key, points in by_model.items() if (fit := fit_size_model(points))
            },
            "size_fit_global": fit_size_model(glob),
        }

    @staticmethod
    def _size_fit_for(
        job: models.ReviewJob, history: dict[str, Any]
    ) -> tuple[float, float] | None:
        """Best size model for a job: exact bucket, then model, then global."""

        snapshot = job.configuration_snapshot_json or {}
        model_id = (snapshot.get("model") or {}).get("model_id")
        concurrency = (snapshot.get("settings") or {}).get("concurrency")
        exact = history["size_fits_by_bucket"].get((model_id, concurrency))
        if exact:
            return exact
        if model_id is not None:
            by_model = history["size_fits_by_model"].get(model_id)
            if by_model:
                return by_model
        return history["size_fit_global"]

    def _size_aware_eta(
        self,
        job: models.ReviewJob,
        progress: dict[str, Any],
        elapsed_seconds: float,
        history: dict[str, Any],
    ) -> float | None:
        """Size-aware ETA, or ``None`` when the job lacks the data for one."""

        files = progress["inventory_files"]
        stats = progress["file_stats"]
        # Only trust the size path with complete coverage: files without
        # stats would silently vanish from the remaining-work sum.
        if not files or set(files) != set(stats):
            return None
        fit = self._size_fit_for(job, history)
        if fit is None or (fit[0] <= 0 and fit[1] <= 0):
            return None
        alpha, beta = fit
        completed_paths = progress["completed_paths"]
        completed_work = sum(
            file_work_seconds(alpha, beta, *stats[path])
            for path in completed_paths
            if path in stats
        )
        remaining_work = sum(
            file_work_seconds(alpha, beta, *stats[path])
            for path in files
            if path not in completed_paths
        )
        return running_eta_seconds(
            total_files=progress["total_files"],
            completed_files=progress["completed_files"],
            elapsed_seconds=elapsed_seconds,
            remaining_work=remaining_work,
            completed_work=completed_work or None,
        )

    async def _active_remaining_seconds(self, history: dict[str, Any]) -> float:
        """Total remaining time of jobs currently preparing/running."""

        stmt = select(models.ReviewJob).where(
            models.ReviewJob.status.in_(["preparing", "running"])
        )
        result = await self.session.execute(stmt)
        total = 0.0
        for job in result.scalars():
            progress = await self._read_progress(job.id)
            # Only a real inventory is a trustworthy ETA denominator; a
            # started-only job (no job.inventory) stays unknown so it cannot
            # drag the queued estimate down toward ~one file of work.
            if not progress["has_real_inventory"]:
                continue
            remaining = self._size_aware_eta(
                job, progress, _elapsed_seconds(job), history
            )
            if remaining is None:
                remaining = running_eta_seconds(
                    total_files=progress["total_files"],
                    completed_files=progress["completed_files"],
                    elapsed_seconds=_elapsed_seconds(job),
                    historical_per_file=history["avg_per_file_s"],
                )
            if remaining is not None and remaining > 0:
                total += remaining
        return total

    async def _queued_eta(
        self, job: models.ReviewJob
    ) -> tuple[float | None, int]:
        """ETA for a waiting job: active wait + queued-ahead + own run."""

        history = await self._history_stats()
        if history["avg_runtime_s"] is None:
            return None, _QUEUED_UNKNOWN_POLL_SECONDS
        active_remaining = await self._active_remaining_seconds(history)
        position = job.queue_position or 1
        jobs_ahead = max(0, position - 1)
        eta = active_remaining + jobs_ahead * history["avg_runtime_s"] + history[
            "avg_runtime_s"
        ]
        return int(math.ceil(eta)), poll_interval_seconds(eta, running=False)

    @staticmethod
    def _public_progress(progress: dict[str, Any]) -> dict[str, Any]:
        """The externally visible subset of ``_read_progress`` output."""

        return {
            "total_files": progress["total_files"],
            "completed_files": progress["completed_files"],
            "model_requests": progress["model_requests"],
            "percent": progress["percent"],
        }

    async def describe(self, job: models.ReviewJob) -> dict[str, Any]:
        """Return the ``{progress, eta_seconds, eta, poll_interval_seconds}`` block."""

        progress = await self._read_progress(job.id)
        public_progress = self._public_progress(progress)

        if job.status in TERMINAL_STATUSES:
            return {
                "progress": public_progress,
                "eta_seconds": 0,
                "eta": format_eta(0),
                "poll_interval_seconds": 0,
            }

        if job.status == "queued":
            eta_seconds, poll = await self._queued_eta(job)
            return {
                "progress": public_progress,
                "eta_seconds": eta_seconds,
                "eta": format_eta(eta_seconds),
                "poll_interval_seconds": poll,
            }

        # preparing / running / cancelling — pace from this job's own progress.
        elapsed_seconds = _elapsed_seconds(job)
        history = await self._history_stats()
        # Only a real ``job.inventory`` total is a safe ETA denominator. Without
        # one, ``total_files`` is a synthetic started-count that would make the
        # historical fallback report ~one file of ETA; keep those jobs unknown.
        eta_seconds = None
        if progress["has_real_inventory"]:
            eta_seconds = self._size_aware_eta(job, progress, elapsed_seconds, history)
        if eta_seconds is None:
            eta_seconds = running_eta_seconds(
                total_files=(
                    progress["total_files"] if progress["has_real_inventory"] else None
                ),
                completed_files=progress["completed_files"],
                elapsed_seconds=elapsed_seconds,
                historical_per_file=history["avg_per_file_s"],
            )
        return {
            "progress": public_progress,
            "eta_seconds": (
                int(math.ceil(eta_seconds)) if eta_seconds is not None else None
            ),
            "eta": format_eta(eta_seconds),
            "poll_interval_seconds": poll_interval_seconds(eta_seconds, running=True),
        }
