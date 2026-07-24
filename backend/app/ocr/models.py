"""Pydantic schemas for the OCR compatibility layer (SPEC §35).

Everything the rest of the backend knows about OCR flows through these
types; route handlers never see raw OCR output.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ReviewMode = Literal["range", "commit", "workspace", "pr"]
PlanMode = Literal["auto", "always", "never"]


class OCRCapabilities(BaseModel):
    """Feature flags detected from the installed binary's help output."""

    model_config = ConfigDict(frozen=True)

    json_output: bool = False
    agent_audience: bool = False
    resume: bool = False
    background: bool = False
    background_file: bool = False
    exclude_flag: bool = False
    preview: bool = False
    model_override: bool = False
    rule_flag: bool = False
    tools_flag: bool = False
    concurrency_flag: bool = False
    timeout_flag: bool = False
    max_tools_flag: bool = False
    max_git_procs_flag: bool = False
    # Planning-control patch set (Stage 4) — absent on stock upstream builds.
    plan_mode: bool = False
    plan_threshold: bool = False
    max_tokens: bool = False
    template_override: bool = False
    # Subcommands.
    llm_test: bool = False
    llm_providers: bool = False
    scan: bool = False
    rules_check: bool = False
    viewer: bool = False
    config_set: bool = False


class OCRStatus(BaseModel):
    """Result of binary detection + capability probing.

    ``status`` is ``"ok"`` or ``"ocr_not_found"`` — never an exception.
    """

    status: Literal["ok", "ocr_not_found", "probe_failed"]
    binary_path: str | None = None
    version: str | None = None
    capabilities: OCRCapabilities = Field(default_factory=OCRCapabilities)
    honored_env_overrides: list[str] = Field(default_factory=list)
    message: str | None = None


class ReviewJobContext(BaseModel):
    """Everything needed to build one ``ocr review`` invocation.

    Refs/SHAs must already be resolved by the caller (queue stage); the
    adapter only maps them onto argv.
    """

    mode: ReviewMode
    repo_path: str  # worktree for range/commit; real path for workspace
    base_ref: str | None = None
    target_ref: str | None = None
    commit_ref: str | None = None
    base_sha: str | None = None
    target_sha: str | None = None
    commit_sha: str | None = None
    resume_session_id: str | None = None
    # profile options
    language: str | None = None
    concurrency: int | None = None
    per_file_timeout_minutes: int | None = None
    max_tools: int | None = None
    max_git_processes: int | None = None
    rule_file_path: str | None = None
    exclude_patterns: list[str] = Field(default_factory=list)
    tools_file_path: str | None = None
    model: str | None = None
    background: str | None = None
    background_file: str | None = None
    # planning patch controls
    plan_mode: PlanMode = "auto"
    plan_threshold_lines: int | None = None
    max_tokens: int | None = None
    template_path: str | None = None
    # expert escape hatch (already validated by core.security)
    additional_arguments: list[str] = Field(default_factory=list)


class ProviderResolution(BaseModel):
    """Resolved provider settings for a single job (secrets resolved)."""

    base_url: str | None = None
    token: str | None = None  # never logged; registered with the redactor
    model: str | None = None
    protocol: str | None = None  # openai | openai-responses | anthropic
    auth_header: str | None = None
    http_timeout_seconds: int | None = None
    extra_headers: dict[str, str] = Field(default_factory=dict)
    extra_body: dict[str, Any] = Field(default_factory=dict)
    language: str | None = None


class NormalizedFinding(BaseModel):
    path: str
    content: str
    start_line: int | None = None
    end_line: int | None = None
    existing_code: str | None = None
    suggestion_code: str | None = None
    thinking: str | None = None
    # Pass-through only when OCR provides them; never invented (SPEC §38.16).
    category: str | None = None
    severity: str | None = None


class NormalizedWarning(BaseModel):
    file: str | None = None
    message: str
    type: str | None = None


class ResultSummary(BaseModel):
    files_reviewed: int | None = None
    comments: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    total_tokens: int | None = None
    elapsed: str | None = None


class ParsedResult(BaseModel):
    status: str
    message: str | None = None
    trace_id: str | None = None
    session_id: str | None = None
    findings: list[NormalizedFinding] = Field(default_factory=list)
    warnings: list[NormalizedWarning] = Field(default_factory=list)
    summary: ResultSummary = Field(default_factory=ResultSummary)
    tool_calls: dict[str, int] = Field(default_factory=dict)
    project_summary: str | None = None
    resume: dict[str, Any] | None = None


class SessionEvent(BaseModel):
    """One normalized OCR session JSONL record (SPEC §14, §15)."""

    seq: int  # 0-based line number within the file
    record_type: str  # session_start, llm_request, tool_call, ...
    timestamp: datetime | None = None
    session_id: str | None = None
    file_path: str | None = None
    task_type: str | None = None  # plan_task, main_task, ...
    request_no: int | None = None
    tool_name: str | None = None
    error: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    duration_ms: float | None = None
    comments_count: int | None = None
    raw: dict[str, Any] | None = None  # kept for the session inspector


class LLMTestResult(BaseModel):
    ok: bool
    status: Literal["ok", "failed", "ocr_not_found"]
    exit_code: int | None = None
    elapsed_ms: float | None = None
    stdout: str = ""
    stderr: str = ""
    message: str | None = None


class PreviewFile(BaseModel):
    path: str
    status: str | None = None
    insertions: int | None = None
    deletions: int | None = None
    will_review: bool = True
    exclude_reason: str | None = None


class PreviewResult(BaseModel):
    ok: bool
    files: list[PreviewFile] = Field(default_factory=list)
    total_files: int | None = None
    reviewable_count: int | None = None
    excluded_count: int | None = None
    total_insertions: int | None = None
    total_deletions: int | None = None
    raw_text: str | None = None
    message: str | None = None
