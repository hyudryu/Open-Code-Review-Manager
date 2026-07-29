"""SQLAlchemy 2 ORM models for every entity in SPEC §4.

Conventions:
- UUID string primary keys (``str(uuid4())``), Postgres-compatible.
- Timezone-aware datetimes (``DateTime(timezone=True)``, UTC defaults).
- Enumerations are stored as plain strings; validation happens at the
  Pydantic schema layer, keeping the models portable and migration-free
  when enum values evolve.
- JSON-ish fields use ``sa.JSON`` (native JSON on Postgres, TEXT on SQLite).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def new_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


# --- enum value sets (validated at the Pydantic layer) ----------------------

BRANCH_KINDS = ("local", "remote", "tag")
PROVIDER_PROTOCOLS = ("openai", "openai-responses", "anthropic")
MODEL_DISCOVERY_MODES = ("auto", "manual", "adapter")
PLAN_MODES = ("auto", "always", "never")
JOB_SOURCES = ("web", "mcp", "api", "retry")
JOB_MODES = ("range", "commit", "workspace", "pr")
JOB_STATUSES = (
    "queued",
    "preparing",
    "running",
    "cancelling",
    "completed",
    "completed_with_warnings",
    "failed",
    "cancelled",
    "interrupted",
)
FINDING_USER_STATES = ("unreviewed", "accepted", "dismissed", "needs_followup")
WEBHOOK_EVENTS = (
    "review.queued",
    "review.started",
    "review.completed",
    "review.completed_with_warnings",
    "review.failed",
    "review.cancelled",
)
DELIVERY_STATUSES = ("pending", "delivering", "succeeded", "failed", "exhausted")


class Folder(TimestampMixin, Base):
    __tablename__ = "folders"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=new_uuid)
    display_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    absolute_path: Mapped[str] = mapped_column(sa.Text, unique=True, nullable=False)
    scan_depth: Mapped[int] = mapped_column(sa.Integer, default=2, nullable=False)
    auto_discover: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    last_scanned_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    projects: Mapped[list["Project"]] = relationship(back_populates="folder")


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=new_uuid)
    folder_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("folders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    display_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    absolute_path: Mapped[str] = mapped_column(sa.Text, unique=True, nullable=False)
    git_common_dir: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    default_branch: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    remote_name: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    remote_url: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    current_branch: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    is_dirty: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    is_available: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    last_branch_refresh_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    folder: Mapped[Folder | None] = relationship(back_populates="projects")
    branches: Mapped[list["BranchCache"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class BranchCache(Base):
    __tablename__ = "branch_cache"
    __table_args__ = (
        sa.UniqueConstraint("project_id", "full_ref", name="uq_branch_project_ref"),
        sa.Index("ix_branch_project_kind", "project_id", "kind"),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    full_ref: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    kind: Mapped[str] = mapped_column(sa.String(16), nullable=False)  # BRANCH_KINDS
    remote_name: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    commit_subject: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    commit_timestamp: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    is_default: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    is_current: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="branches")


class ProviderProfile(TimestampMixin, Base):
    __tablename__ = "provider_profiles"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(sa.String(255), unique=True, nullable=False)
    provider_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    protocol: Mapped[str] = mapped_column(sa.String(32), nullable=False)  # PROVIDER_PROTOCOLS
    base_url: Mapped[str] = mapped_column(sa.Text, nullable=False)
    credential_reference: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    auth_header: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    http_timeout_seconds: Mapped[int] = mapped_column(sa.Integer, default=600, nullable=False)
    extra_headers_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    extra_body_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    model_discovery_mode: Mapped[str] = mapped_column(
        sa.String(16), default="auto", nullable=False
    )  # MODEL_DISCOVERY_MODES
    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    # Last model-discovery outcome (SPEC §9 "Store discovery failures").
    last_discovery_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    last_discovery_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    models: Mapped[list["Model"]] = relationship(
        back_populates="provider_profile", cascade="all, delete-orphan"
    )


class Model(Base):
    __tablename__ = "models"
    __table_args__ = (
        sa.UniqueConstraint(
            "provider_profile_id", "model_id", name="uq_model_provider_model"
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=new_uuid)
    provider_profile_id: Mapped[str] = mapped_column(
        sa.ForeignKey("provider_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    context_length: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    supports_tools: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    is_manual: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    last_discovered_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    provider_profile: Mapped[ProviderProfile] = relationship(back_populates="models")


class ReviewProfile(TimestampMixin, Base):
    __tablename__ = "review_profiles"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(sa.String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    provider_profile_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("provider_profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    model_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("models.id", ondelete="SET NULL"), nullable=True
    )
    language: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    concurrency: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    per_file_timeout_minutes: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    llm_http_timeout_seconds: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    max_tools: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    max_git_processes: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    plan_mode: Mapped[str] = mapped_column(sa.String(16), default="auto", nullable=False)
    plan_threshold_lines: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    template_path: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    exclude_patterns: Mapped[list[str] | None] = mapped_column(sa.JSON, nullable=True)
    rule_file_path: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    tools_file_path: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    background_template: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    additional_arguments: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=sa.false(), nullable=False
    )


class ReviewJob(Base):
    __tablename__ = "review_jobs"
    __table_args__ = (
        sa.Index("ix_jobs_status_priority", "status", "priority", "queued_at"),
        sa.Index("ix_jobs_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    profile_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("review_profiles.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(sa.String(16), default="web", nullable=False)
    mode: Mapped[str] = mapped_column(sa.String(16), nullable=False)  # JOB_MODES
    base_ref: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    target_ref: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    commit_ref: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    workspace_path: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    priority: Mapped[int] = mapped_column(sa.Integer, default=50, nullable=False)
    queue_position: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    manual_position: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    status: Mapped[str] = mapped_column(sa.String(32), default="queued", nullable=False)
    status_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    configuration_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(
        sa.JSON, nullable=True
    )
    generated_command_json: Mapped[dict[str, Any] | None] = mapped_column(
        sa.JSON, nullable=True
    )
    ocr_version: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    ocr_session_id: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    worktree_path: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    job_home_path: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    process_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    stdout_path: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    stderr_path: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    result_json_path: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    queued_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    # --- control-plane extensions (needed by queue/webhook stages) ---------
    webhook_endpoint_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("webhook_endpoints.id", ondelete="SET NULL"), nullable=True
    )
    request_metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        sa.JSON, nullable=True
    )
    retry_of_job_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("review_jobs.id", ondelete="SET NULL"), nullable=True
    )
    resume_from_session_id: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )

    # --- Stage 2 queue/runtime extensions ----------------------------------
    #: Individually paused queued job (status stays "queued").
    paused: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    #: Parsed result.json summary + token counts (no secrets).
    result_summary_json: Mapped[dict[str, Any] | None] = mapped_column(
        sa.JSON, nullable=True
    )
    #: Normalized OCR warnings from result.json.
    warnings_json: Mapped[list[Any] | None] = mapped_column(sa.JSON, nullable=True)
    #: Dirty-state fingerprint for workspace jobs (SPEC §11).
    dirty_fingerprint: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    findings: Mapped[list["Finding"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    events: Mapped[list["JobEvent"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (sa.Index("ix_findings_job_path", "job_id", "path"),)

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=new_uuid)
    job_id: Mapped[str] = mapped_column(
        sa.ForeignKey("review_jobs.id", ondelete="CASCADE"), nullable=False
    )
    path: Mapped[str] = mapped_column(sa.Text, nullable=False)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    start_line: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    end_line: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    existing_code: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    suggestion_code: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    thinking: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # OCR may emit category/severity — passed through verbatim, never invented.
    category: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    severity: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    user_state: Mapped[str] = mapped_column(
        sa.String(32), default="unreviewed", nullable=False
    )  # FINDING_USER_STATES
    user_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, nullable=False
    )

    job: Mapped[ReviewJob] = relationship(back_populates="findings")


class WebhookEndpoint(TimestampMixin, Base):
    __tablename__ = "webhook_endpoints"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    url: Mapped[str] = mapped_column(sa.Text, nullable=False)
    secret_reference: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    allowed_events: Mapped[list[str]] = mapped_column(sa.JSON, nullable=False)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    last_delivery_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    deliveries: Mapped[list["WebhookDelivery"]] = relationship(
        back_populates="endpoint", cascade="all, delete-orphan"
    )


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (sa.Index("ix_deliveries_endpoint", "endpoint_id", "created_at"),)

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=new_uuid)
    endpoint_id: Mapped[str] = mapped_column(
        sa.ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("review_jobs.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    delivery_id: Mapped[str] = mapped_column(
        sa.String(36), unique=True, nullable=False, default=new_uuid
    )
    attempt: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        sa.String(16), default="pending", nullable=False
    )  # DELIVERY_STATUSES
    http_status: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    response_excerpt: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    endpoint: Mapped[WebhookEndpoint] = relationship(back_populates="deliveries")


class JobEvent(Base):
    """Persisted SSE event. The autoincrement integer id is globally
    monotonic, therefore monotonically increasing per job, which is what the
    SSE ``Last-Event-ID`` resume mechanism relies on (SPEC §14)."""

    __tablename__ = "job_events"
    __table_args__ = (sa.Index("ix_job_events_job_id_id", "job_id", "id"),)

    id: Mapped[int] = mapped_column(
        # SQLite only treats INTEGER PRIMARY KEY as a rowid alias; use the
        # Integer variant there while staying BIGINT on Postgres.
        sa.BigInteger().with_variant(sa.Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    job_id: Mapped[str] = mapped_column(
        sa.ForeignKey("review_jobs.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, nullable=False
    )

    job: Mapped[ReviewJob] = relationship(back_populates="events")


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(sa.String(128), primary_key=True)
    value_json: Mapped[Any] = mapped_column(sa.JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
