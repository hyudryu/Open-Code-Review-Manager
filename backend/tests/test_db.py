"""Database: migrations create the schema; models round-trip."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text

from app.core.config import Settings
from app.db import models
from app.db.migrate import run_migrations_async
from app.db.session import dispose_engine, init_engine, session_scope

EXPECTED_TABLES = {
    "folders",
    "projects",
    "branch_cache",
    "provider_profiles",
    "models",
    "review_profiles",
    "review_jobs",
    "findings",
    "webhook_endpoints",
    "webhook_deliveries",
    "job_events",
    "app_settings",
    "alembic_version",
}


@pytest.fixture()
async def db_url(settings: Settings):
    url = settings.resolved_database_url
    await run_migrations_async(url)
    init_engine(url)
    yield url
    await dispose_engine()


async def test_migration_creates_all_tables(db_url: str) -> None:
    from app.db.session import get_engine

    engine = get_engine()
    async with engine.connect() as conn:
        tables = await conn.run_sync(
            lambda sync_conn: set(inspect(sync_conn).get_table_names())
        )
        wal = await conn.execute(text("PRAGMA journal_mode"))
        mode = wal.scalar()
    assert EXPECTED_TABLES <= tables
    assert str(mode).lower() == "wal"


async def test_entity_roundtrip(db_url: str) -> None:
    async with session_scope() as s:
        folder = models.Folder(
            display_name="work", absolute_path="/tmp/work", scan_depth=3
        )
        project = models.Project(
            folder=folder,
            display_name="api",
            absolute_path="/tmp/work/api",
            current_branch="main",
        )
        provider = models.ProviderProfile(
            name="local",
            provider_type="custom",
            protocol="openai",
            base_url="http://localhost:8000/v1",
            credential_reference="keyring:provider/local",
        )
        s.add_all([folder, project, provider])
        await s.flush()
        model = models.Model(
            provider_profile_id=provider.id, model_id="qwen3", is_manual=True
        )
        profile = models.ReviewProfile(
            name="default",
            provider_profile_id=provider.id,
            model_id=model.id,
            plan_mode="auto",
            exclude_patterns=["*.lock"],
        )
        s.add_all([model, profile])
        await s.flush()
        job = models.ReviewJob(
            project_id=project.id,
            profile_id=profile.id,
            source="mcp",
            mode="range",
            base_ref="main",
            target_ref="feature/x",
            priority=80,
        )
        branch = models.BranchCache(
            project_id=project.id,
            name="main",
            full_ref="refs/heads/main",
            kind="local",
            is_current=True,
            is_default=True,
        )
        endpoint = models.WebhookEndpoint(
            name="agent-hook",
            url="https://agent.example.com/hook",
            allowed_events=["review.completed"],
        )
        s.add_all([job, branch, endpoint])
        await s.flush()
        finding = models.Finding(
            job_id=job.id,
            path="src/a.py",
            content="timing-unsafe compare",
            start_line=1,
            end_line=2,
        )
        delivery = models.WebhookDelivery(endpoint_id=endpoint.id, job_id=job.id,
                                          event_type="review.completed")
        event1 = models.JobEvent(job_id=job.id, event_type="job.status",
                                 payload_json={"status": "queued"})
        event2 = models.JobEvent(job_id=job.id, event_type="job.status",
                                 payload_json={"status": "running"})
        setting = models.AppSetting(key="queue.paused", value_json=False)
        s.add_all([finding, delivery, event1, event2, setting])

    async with session_scope() as s:
        jobs = (await s.execute(select(models.ReviewJob))).scalars().all()
        assert len(jobs) == 1
        job = jobs[0]
        assert job.status == "queued" and job.priority == 80
        assert job.queued_at is not None

        events = (
            (
                await s.execute(
                    select(models.JobEvent)
                    .where(models.JobEvent.job_id == job.id)
                    .order_by(models.JobEvent.id)
                )
            )
            .scalars()
            .all()
        )
        # Autoincrement ids are monotonically increasing per job (SSE resume).
        assert [e.id for e in events] == sorted(e.id for e in events)
        assert [e.payload_json["status"] for e in events] == ["queued", "running"]

        finding = (
            await s.execute(select(models.Finding).where(models.Finding.job_id == job.id))
        ).scalar_one()
        assert finding.user_state == "unreviewed"
        assert finding.severity is None  # never invented

        found_setting = await s.get(models.AppSetting, "queue.paused")
        assert found_setting is not None and found_setting.value_json is False


async def test_foreign_keys_enforced(db_url: str) -> None:
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        async with session_scope() as s:
            s.add(models.Finding(job_id="nonexistent-job", path="a", content="b"))


async def test_migration_idempotent(settings: Settings, tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'idem.db').as_posix()}"
    await run_migrations_async(url)
    await run_migrations_async(url)  # second run is a no-op


async def test_review_profile_has_is_system_column(db_url: str) -> None:
    """Migration 0004 added review_profiles.is_system (NOT NULL, default false)."""

    from app.db.session import get_engine

    engine = get_engine()
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda sync_conn: {
                c["name"]: c for c in inspect(sync_conn).get_columns("review_profiles")
            }
        )
    assert "is_system" in cols
    assert not bool(cols["is_system"]["nullable"])


async def test_ensure_default_seeds_and_adopts(db_url: str) -> None:
    """ensure_default() seeds a fresh Default when none exists, and adopts
    (flags is_system) an existing "Default" when one does — preserving config."""

    from app.services.profiles import ProfileService

    # No profiles yet → seeds a fresh, unconfigured system Default.
    async with session_scope() as s:
        default = await ProfileService(s).ensure_default()
        default_id = default.id
    assert default.is_system is True
    assert default.name == "Default"

    # Re-running is idempotent: same row, still system, no duplicate.
    async with session_scope() as s:
        again = await ProfileService(s).ensure_default()
        rows = await s.execute(select(models.ReviewProfile))
        assert len(rows.scalars().all()) == 1
    assert again.id == default_id
    assert again.is_system is True

    # If a user-made "Default" already exists, it gets adopted (flagged system)
    # without losing its configuration.
    async with session_scope() as s:
        await s.execute(text("DELETE FROM review_profiles"))
        user_default = models.ReviewProfile(name="Default", language="rust")
        s.add(user_default)
        await s.flush()
        adopted = await ProfileService(s).ensure_default()
        assert adopted.id == user_default.id
        assert adopted.is_system is True
        assert adopted.language == "rust"  # config preserved
