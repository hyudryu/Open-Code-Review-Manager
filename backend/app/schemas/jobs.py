"""Job / queue / finding / webhook / system schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.projects import ORMModel

JobMode = Literal["range", "commit", "workspace", "pr"]
JobSource = Literal["web", "mcp", "api", "retry"]
FindingState = Literal["unreviewed", "accepted", "dismissed", "needs_followup"]


class JobCreate(BaseModel):
    project_id: str
    mode: JobMode
    base_ref: str | None = None
    target_ref: str | None = None
    commit_ref: str | None = None
    pr_number: int | None = Field(default=None, ge=1)
    profile_id: str | None = None
    background: str | None = None
    background_file: str | None = None
    exclude_patterns: list[str] | None = None
    priority: int = Field(default=50, ge=0, le=100)
    webhook_endpoint_id: str | None = None
    webhook_url: str | None = None
    webhook_secret: str | None = None
    metadata: dict[str, Any] | None = None


class JobPreviewRequest(BaseModel):
    project_id: str
    mode: JobMode
    base_ref: str | None = None
    target_ref: str | None = None
    commit_ref: str | None = None
    pr_number: int | None = Field(default=None, ge=1)
    profile_id: str | None = None
    exclude_patterns: list[str] | None = None


class JobUpdate(BaseModel):
    priority: int | None = Field(default=None, ge=0, le=100)


class JobOut(ORMModel):
    id: str
    project_id: str
    profile_id: str | None
    source: str
    mode: str
    base_ref: str | None
    target_ref: str | None
    commit_ref: str | None
    priority: int
    queue_position: int | None
    status: str
    status_message: str | None
    paused: bool
    configuration_snapshot_json: dict[str, Any] | None
    generated_command_json: dict[str, Any] | None
    ocr_version: str | None
    ocr_session_id: str | None
    result_summary_json: dict[str, Any] | None
    warnings_json: list[Any] | None
    exit_code: int | None
    retry_of_job_id: str | None
    resume_from_session_id: str | None
    queued_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    findings_count: int = 0


class JobMoveRequest(BaseModel):
    action: Literal["top", "up", "down"]


class JobRetryRequest(BaseModel):
    priority: int | None = Field(default=None, ge=0, le=100)
    background: str | None = None


class JobEventOut(ORMModel):
    id: int
    job_id: str
    event_type: str
    payload_json: dict[str, Any] | None
    created_at: datetime


class FindingOut(ORMModel):
    id: str
    job_id: str
    path: str
    content: str
    start_line: int | None
    end_line: int | None
    existing_code: str | None
    suggestion_code: str | None
    category: str | None
    severity: str | None
    user_state: str
    user_note: str | None
    created_at: datetime
    # Raw model reasoning. Only populated when the caller explicitly opts in
    # via ``include_reasoning=true``; routes null it out otherwise (SPEC §38.15).
    thinking: str | None = None


class FindingUpdate(BaseModel):
    user_state: FindingState | None = None
    user_note: str | None = None


class QueueReorderRequest(BaseModel):
    job_ids: list[str] = Field(min_length=1)


class QueueStateOut(BaseModel):
    paused: bool
    jobs: list[JobOut]


class PreviewFileOut(BaseModel):
    path: str
    status: str | None
    insertions: int | None
    deletions: int | None
    will_review: bool
    exclude_reason: str | None


class JobPreviewOut(BaseModel):
    files: list[PreviewFileOut]
    total_files: int | None
    reviewable_count: int | None
    excluded_count: int | None
    total_insertions: int | None
    total_deletions: int | None


class LogOut(BaseModel):
    stream: str
    text: str
    size: int
    truncated: bool


class SessionOut(BaseModel):
    records: list[dict[str, Any]]
    total: int
    session_file: str | None = None
    session_id: str | None = None


# --- webhooks ---------------------------------------------------------------


class WebhookCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1)
    secret: str | None = None
    allowed_events: list[str] | None = None
    enabled: bool = True


class WebhookUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    url: str | None = None
    allowed_events: list[str] | None = None
    enabled: bool | None = None
    rotate_secret: bool = False


class WebhookOut(ORMModel):
    id: str
    name: str
    url: str
    allowed_events: list[str]
    enabled: bool
    has_secret: bool = False
    last_delivery_at: datetime | None
    created_at: datetime


class WebhookDeliveryOut(ORMModel):
    id: str
    endpoint_id: str
    job_id: str | None
    event_type: str
    delivery_id: str
    attempt: int
    status: str
    http_status: int | None
    response_excerpt: str | None
    next_attempt_at: datetime | None
    created_at: datetime
    completed_at: datetime | None


# --- settings / system -------------------------------------------------------


class SettingsUpdate(BaseModel):
    changes: dict[str, Any]


class HealthOut(BaseModel):
    status: str
    version: str
    ocr_status: str


class McpStatusOut(BaseModel):
    """Live status of the in-process MCP server (SPEC §17)."""

    enabled: bool
    transport: str
    path: str
    port: int
    url: str
    tool_count: int
    resource_count: int
    prompt_count: int
