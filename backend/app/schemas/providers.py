"""Provider / model / profile schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.projects import ORMModel

Protocol = Literal["openai", "openai-responses", "anthropic"]
DiscoveryMode = Literal["auto", "manual", "adapter"]
PlanMode = Literal["auto", "always", "never"]


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    provider_type: str = "custom"
    protocol: Protocol
    base_url: str = ""
    credential: str | None = None  # write-only; stored via SecretStore
    auth_header: str | None = None
    http_timeout_seconds: int = Field(default=600, ge=1, le=3600)
    extra_headers: dict[str, str] | None = None
    extra_body: dict[str, Any] | None = None
    model_discovery_mode: DiscoveryMode = "auto"
    enabled: bool = True


class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    provider_type: str | None = None
    protocol: Protocol | None = None
    base_url: str | None = None
    credential: str | None = None
    auth_header: str | None = None
    http_timeout_seconds: int | None = Field(default=None, ge=1, le=3600)
    extra_headers: dict[str, str] | None = None
    extra_body: dict[str, Any] | None = None
    model_discovery_mode: DiscoveryMode | None = None
    enabled: bool | None = None


class ProviderOut(ORMModel):
    id: str
    name: str
    provider_type: str
    protocol: str
    base_url: str
    has_credential: bool = False
    auth_header: str | None
    http_timeout_seconds: int
    model_discovery_mode: str
    enabled: bool
    last_discovery_at: datetime | None
    last_discovery_error: str | None
    created_at: datetime


class ModelOut(ORMModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    model_id: str
    display_name: str | None
    context_length: int | None
    supports_tools: bool | None
    is_manual: bool
    is_enabled: bool
    last_discovered_at: datetime | None


class ManualModelCreate(BaseModel):
    model_id: str = Field(min_length=1, max_length=255)
    display_name: str | None = None
    context_length: int | None = None


class ProviderTestOut(BaseModel):
    ok: bool
    status: str
    exit_code: int | None = None
    elapsed_ms: float | None = None
    stdout: str = ""
    stderr: str = ""
    message: str | None = None
    # Direct-ping fields (llm_ping); exit_code/stdout/stderr are legacy.
    reply: str | None = None
    http_status: int | None = None
    detail: str | None = None
    next_action: str | None = None


class ProviderHealthOut(BaseModel):
    """Result of the list-page ``GET /models`` reachability probe.

    Drives the status dot on the Providers table. ``online`` is a green dot
    regardless of whether a credential was sent (keyless local servers that
    answer 2xx are genuinely up). ``auth_needed`` (401/403) is yellow.
    ``offline`` is red. ``reachable``/``authed`` give the UI the nuance if it
    wants it; ``status`` is the canonical bucket.
    """

    ok: bool
    status: Literal["online", "auth_needed", "offline", "unauthorized"]
    reachable: bool
    authed: bool
    elapsed_ms: float | None = None
    http_status: int | None = None
    detail: str | None = None  # sanitized: never contains the credential
    checked_at: datetime


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    provider_profile_id: str | None = None
    model_id: str | None = None
    language: str | None = None
    concurrency: int | None = Field(default=None, ge=1, le=64)
    per_file_timeout_minutes: int | None = Field(default=None, ge=1, le=240)
    llm_http_timeout_seconds: int | None = Field(default=None, ge=1, le=7200)
    max_tools: int | None = Field(default=None, ge=1, le=200)
    max_git_processes: int | None = Field(default=None, ge=1, le=64)
    plan_mode: PlanMode = "auto"
    plan_threshold_lines: int | None = Field(default=None, ge=1)
    max_tokens: int | None = Field(default=None, ge=1)
    template_path: str | None = None
    exclude_patterns: list[str] | None = None
    rule_file_path: str | None = None
    tools_file_path: str | None = None
    background_template: str | None = None
    additional_arguments: str | None = None


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    provider_profile_id: str | None = None
    model_id: str | None = None
    language: str | None = None
    concurrency: int | None = Field(default=None, ge=1, le=64)
    per_file_timeout_minutes: int | None = Field(default=None, ge=1, le=240)
    llm_http_timeout_seconds: int | None = Field(default=None, ge=1, le=7200)
    max_tools: int | None = Field(default=None, ge=1, le=200)
    max_git_processes: int | None = Field(default=None, ge=1, le=64)
    plan_mode: PlanMode | None = None
    plan_threshold_lines: int | None = Field(default=None, ge=1)
    max_tokens: int | None = Field(default=None, ge=1)
    template_path: str | None = None
    exclude_patterns: list[str] | None = None
    rule_file_path: str | None = None
    tools_file_path: str | None = None
    background_template: str | None = None
    additional_arguments: str | None = None


class ProfileOut(ORMModel):
    id: str
    name: str
    description: str | None
    provider_profile_id: str | None
    model_id: str | None
    language: str | None
    concurrency: int | None
    per_file_timeout_minutes: int | None
    llm_http_timeout_seconds: int | None
    max_tools: int | None
    max_git_processes: int | None
    plan_mode: str
    plan_threshold_lines: int | None
    max_tokens: int | None
    template_path: str | None
    exclude_patterns: list[str] | None
    rule_file_path: str | None
    tools_file_path: str | None
    background_template: str | None
    additional_arguments: str | None
    is_system: bool = False
    created_at: datetime
