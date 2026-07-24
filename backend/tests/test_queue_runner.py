"""Job lifecycle end-to-end with the fake OCR binary (SPEC §10-14).

The fake ``ocr`` is a Python script registered as the custom OCR executable;
it emits a session JSONL under the per-job HOME and prints result JSON.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db import models
from app.db.session import session_scope
from app.services.jobs import JobService
from app.services.profiles import ProfileService
from app.services.providers import ProviderService


async def _create_job(project_id: str, **kwargs) -> str:
    async with session_scope() as session:
        service = JobService(session)
        job = await service.create(project_id=project_id, **kwargs)
        return job.id


async def _get_job(job_id: str) -> models.ReviewJob:
    async with session_scope() as session:
        job = await session.get(models.ReviewJob, job_id)
        assert job is not None
        session.expunge(job)
        return job


async def _wait_status(job_id: str, wanted: set[str], timeout: float = 15.0) -> str:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        job = await _get_job(job_id)
        if job.status in wanted:
            return job.status
        await asyncio.sleep(0.05)
    raise AssertionError(f"job {job_id} never reached {wanted}; last={job.status}")


async def test_commit_job_completes_end_to_end(project, fake_ocr, make_worker) -> None:
    project_id, _ = project
    job_id = await _create_job(project_id, mode="commit", commit_ref="HEAD")
    worker = make_worker()
    await worker.drain()

    job = await _get_job(job_id)
    assert job.status == "completed"
    assert job.ocr_session_id and job.ocr_session_id.startswith("sess-")
    assert job.exit_code == 0
    assert job.ocr_version == "9.9.9-fake"
    assert job.result_summary_json["files_reviewed"] == 1
    assert job.result_summary_json["total_tokens"] == 150

    async with session_scope() as session:
        findings = (
            await session.execute(
                select(models.Finding).where(models.Finding.job_id == job_id)
            )
        ).scalars().all()
        assert len(findings) == 1
        assert findings[0].path == "hello.py"
        assert findings[0].severity is None  # never invented (SPEC §38.16)

        events = (
            await session.execute(
                select(models.JobEvent)
                .where(models.JobEvent.job_id == job_id)
                .order_by(models.JobEvent.id)
            )
        ).scalars().all()
        types = [e.event_type for e in events]
        assert "job.status" in types
        assert "job.file_started" in types
        assert "job.file_completed" in types
        assert "job.summary" in types

    # Artifacts on disk.
    job_dir = Path(job.job_home_path).parent
    assert (job_dir / "stdout.log").is_file()
    assert (job_dir / "stderr.log").is_file()
    assert (job_dir / "result.json").is_file()
    metadata = json.loads((job_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "completed"
    # Worktree cleaned up (retention disabled by default).
    assert job.worktree_path is None


async def test_warnings_yield_completed_with_warnings(
    project, fake_ocr, make_worker, monkeypatch
) -> None:
    monkeypatch.setenv("FAKE_OCR_WARNINGS", "1")
    project_id, _ = project
    job_id = await _create_job(project_id, mode="commit", commit_ref="HEAD")
    worker = make_worker()
    await worker.drain()
    job = await _get_job(job_id)
    assert job.status == "completed_with_warnings"
    assert job.warnings_json and job.warnings_json[0]["type"] == "skip"


async def test_failed_ocr_marks_job_failed(
    project, fake_ocr, make_worker, monkeypatch
) -> None:
    monkeypatch.setenv("FAKE_OCR_FAIL", "1")
    project_id, _ = project
    job_id = await _create_job(project_id, mode="commit", commit_ref="HEAD")
    worker = make_worker()
    await worker.drain()
    job = await _get_job(job_id)
    assert job.status == "failed"
    assert job.exit_code == 3
    assert "simulated OCR failure" in (job.status_message or "")


async def test_cancel_running_job_kills_process_tree(
    project, fake_ocr, make_worker, monkeypatch
) -> None:
    monkeypatch.setenv("FAKE_OCR_SLEEP", "60")
    project_id, _ = project
    job_id = await _create_job(project_id, mode="commit", commit_ref="HEAD")
    worker = make_worker()
    drain_task = asyncio.create_task(worker.drain())

    await _wait_status(job_id, {"running"})

    async with session_scope() as session:
        service = JobService(session)
        await service.cancel(job_id)

    await asyncio.wait_for(drain_task, timeout=30)
    job = await _get_job(job_id)
    assert job.status == "cancelled"
    assert job.cancel_requested_at is not None
    assert worker.runner.active_count == 0
    # Partial logs are preserved.
    assert Path(job.stdout_path).exists() or Path(job.stderr_path).exists()


async def test_cancel_queued_job(project, fake_ocr, make_worker) -> None:
    project_id, _ = project
    job_id = await _create_job(project_id, mode="commit", commit_ref="HEAD")
    async with session_scope() as session:
        service = JobService(session)
        await service.cancel(job_id)
    job = await _get_job(job_id)
    assert job.status == "cancelled"


async def test_retry_links_to_original_and_copies_snapshot(
    project, fake_ocr, make_worker, monkeypatch
) -> None:
    monkeypatch.setenv("FAKE_OCR_FAIL", "1")
    project_id, _ = project
    job_id = await _create_job(project_id, mode="commit", commit_ref="HEAD", priority=33)
    worker = make_worker()
    await worker.drain()
    assert (await _get_job(job_id)).status == "failed"

    monkeypatch.delenv("FAKE_OCR_FAIL")
    async with session_scope() as session:
        service = JobService(session)
        retry = await service.retry(job_id)
        retry_id = retry.id

    retry_job = await _get_job(retry_id)
    original = await _get_job(job_id)
    assert retry_job.retry_of_job_id == job_id
    assert retry_job.source == "retry"
    assert retry_job.status == "queued"
    assert retry_job.priority == original.priority
    # Immutable snapshot copied verbatim.
    assert retry_job.configuration_snapshot_json == original.configuration_snapshot_json

    await worker.drain()
    assert (await _get_job(retry_id)).status == "completed"


async def test_resume_creates_session_linked_job(
    project, fake_ocr, make_worker
) -> None:
    project_id, _ = project
    job_id = await _create_job(project_id, mode="commit", commit_ref="HEAD")
    worker = make_worker()
    await worker.drain()
    original = await _get_job(job_id)
    assert original.ocr_session_id

    async with session_scope() as session:
        service = JobService(session)
        resumed = await service.resume(job_id)
        resumed_id = resumed.id

    resumed_job = await _get_job(resumed_id)
    assert resumed_job.resume_from_session_id == original.ocr_session_id
    assert resumed_job.retry_of_job_id == job_id
    argv = resumed_job.generated_command_json["argv"]
    assert "--resume" in argv
    assert argv[argv.index("--resume") + 1] == original.ocr_session_id


async def test_resume_rejected_without_session(project, fake_ocr, make_worker) -> None:
    from app.services.errors import ConflictError

    project_id, _ = project
    job_id = await _create_job(project_id, mode="commit", commit_ref="HEAD")
    async with session_scope() as session:
        service = JobService(session)
        with pytest.raises(ConflictError):
            await service.resume(job_id)


async def test_workspace_jobs_serialize_on_project_lock(
    project, fake_ocr, make_worker, monkeypatch
) -> None:
    """Two concurrent workspace jobs on one project never overlap (§11)."""

    monkeypatch.setenv("FAKE_OCR_SLEEP", "0.3")
    project_id, _ = project

    # Allow two concurrent jobs globally/per-project; the workspace lock
    # (not the concurrency limiter) must be what serializes them.
    async with session_scope() as session:
        session.add(models.AppSetting(key="queue.global_concurrency", value_json=2))
        session.add(models.AppSetting(key="queue.per_project_concurrency", value_json=2))

    job_a = await _create_job(project_id, mode="workspace")
    job_b = await _create_job(project_id, mode="workspace")
    worker = make_worker()
    await worker.drain()

    a = await _get_job(job_a)
    b = await _get_job(job_b)
    assert a.status == b.status == "completed"
    first, second = sorted([a, b], key=lambda j: j.started_at)
    assert second.started_at >= first.completed_at
    # Both recorded a dirty-state fingerprint.
    assert a.dirty_fingerprint and b.dirty_fingerprint


async def test_snapshot_is_immutable_after_profile_edits(
    project, fake_ocr, make_worker
) -> None:
    project_id, _ = project
    async with session_scope() as session:
        providers = ProviderService(session)
        provider = await providers.create(
            name="TestProv",
            protocol="openai",
            base_url="https://api.example.test/v1",
            credential="sk-TESTSECRET-123456",
        )
        model = await providers.add_manual_model(provider.id, model_id="fake-model")
        profiles = ProfileService(session)
        profile = await profiles.create(
            name="P1", provider_profile_id=provider.id, model_id=model.id,
            concurrency=4,
        )
        provider_id, profile_id = provider.id, profile.id

    async with session_scope() as session:
        service = JobService(session)
        job = await service.create(
            project_id=project_id, mode="commit", commit_ref="HEAD",
            profile_id=profile_id,
        )
        job_id = job.id
        snapshot_before = dict(job.configuration_snapshot_json)
        command_before = dict(job.generated_command_json)

    # Edit the profile and provider after queueing.
    async with session_scope() as session:
        profiles = ProfileService(session)
        await profiles.update(profile_id, name="P1-renamed", concurrency=99)
        providers = ProviderService(session)
        await providers.update(provider_id, name="TestProv-renamed")

    job = await _get_job(job_id)
    assert job.configuration_snapshot_json == snapshot_before
    assert job.generated_command_json == command_before
    assert job.configuration_snapshot_json["settings"]["concurrency"] == 4
    assert job.configuration_snapshot_json["provider"]["name"] == "TestProv"

    # Run the job; the redacted env preview must mask the credential.
    worker = make_worker()
    await worker.drain()
    job = await _get_job(job_id)
    assert job.status == "completed"
    env_preview = job.generated_command_json["env"]
    assert env_preview.get("OCR_LLM_TOKEN") == "***REDACTED***"
    metadata = json.loads(
        (Path(job.job_home_path).parent / "metadata.json").read_text(encoding="utf-8")
    )
    assert "sk-TESTSECRET-123456" not in json.dumps(metadata)


async def test_exports_never_leak_credentials_or_reasoning(
    project, fake_ocr, make_worker
) -> None:
    project_id, _ = project
    async with session_scope() as session:
        providers = ProviderService(session)
        provider = await providers.create(
            name="CredProv",
            protocol="openai",
            base_url="https://api.example.test/v1",
            credential="sk-EXPORT-SECRET-789",
        )
        model = await providers.add_manual_model(provider.id, model_id="fake-model")
        profiles = ProfileService(session)
        profile = await profiles.create(
            name="CredProfile", provider_profile_id=provider.id, model_id=model.id
        )
        profile_id = profile.id

    job_id = None
    async with session_scope() as session:
        service = JobService(session)
        job = await service.create(
            project_id=project_id, mode="commit", commit_ref="HEAD",
            profile_id=profile_id,
        )
        job_id = job.id

    worker = make_worker()
    await worker.drain()
    assert (await _get_job(job_id)).status == "completed"

    async with session_scope() as session:
        service = JobService(session)
        for fmt in ("md", "json", "csv", "jsonl", "txt", "agent-prompt", "github-summary"):
            content, media_type, filename = await service.export(job_id, fmt)
            assert content, fmt
            assert "sk-EXPORT-SECRET-789" not in content
            # Reasoning is excluded by default (SPEC §38.15).
            assert "secret chain-of-thought" not in content
        # Opt-in reasoning export includes thinking.
        content, _, _ = await service.export(job_id, "json", include_reasoning=True)
        assert "secret chain-of-thought" in content
