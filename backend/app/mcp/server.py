"""MCP Streamable HTTP server (SPEC §17).

Every tool is a thin wrapper over ``app.services`` — zero duplicated
business logic (SPEC §38 rules 9-10). Submission is asynchronous: callers
get a durable job id immediately, check ``ocr_get_job`` for quick status, or
wait for the complete export through ``ocr_get_job_results``.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from app.db import models
from app.db.session import get_session_factory
from app.queue.service import TERMINAL_STATUSES
from app.schemas.ocr_mcp import OcrMcpServerConfig
from app.services.errors import ServiceError
from app.services.eta import EtaService
from app.services.findings import FindingService
from app.services.jobs import JobService
from app.services.ocr_mcp import OcrMcpServerService
from app.services.profiles import ProfileService
from app.services.projects import ProjectService
from app.services.waits import wait_for_job_terminal

# ---------------------------------------------------------------------------
# Tool implementations (plain async functions — directly testable)
# ---------------------------------------------------------------------------


def _error_payload(exc: ServiceError) -> dict[str, Any]:
    return {"error": exc.to_dict()["error"]}


def _project_brief(p: models.Project) -> dict[str, Any]:
    """Compact project summary shared by list/add tools."""

    return {
        "id": p.id,
        "display_name": p.display_name,
        "absolute_path": p.absolute_path,
        "default_branch": p.default_branch,
        "current_branch": p.current_branch,
        "is_available": p.is_available,
    }


async def ocr_list_projects(
    query: str | None = None, include_unavailable: bool = False
) -> list[dict[str, Any]]:
    factory = get_session_factory()
    async with factory() as session:
        service = ProjectService(session)
        projects = await service.list(query=query, include_unavailable=include_unavailable)
        return [_project_brief(p) for p in projects]


async def ocr_add_project(
    absolute_path: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    """Register the repository at ``absolute_path`` and return its project id.

    Idempotent: if the repository (resolved to its git top-level) is already
    registered, the existing project is returned unchanged. Use this to recover
    when another tool (e.g. ``ocr_submit_review``) returns ``not_found`` for a
    project id — point it at the repository path you want reviewed, then retry.
    """

    factory = get_session_factory()
    async with factory() as session:
        service = ProjectService(session)
        existing = await service.find_by_path(absolute_path)
        if existing is not None:
            await session.commit()
            return {**_project_brief(existing), "already_registered": True}
        try:
            project = await service.create(
                absolute_path=absolute_path, display_name=display_name
            )
            await session.commit()
        except ServiceError as exc:
            return _error_payload(exc)
        return {**_project_brief(project), "already_registered": False}


async def ocr_list_branches(
    project_id: str, refresh: bool = False, fetch: bool = False
) -> list[dict[str, Any]] | dict[str, Any]:
    factory = get_session_factory()
    async with factory() as session:
        service = ProjectService(session)
        try:
            if refresh or fetch:
                await service.refresh_branches(project_id, fetch=fetch)
            branches = await service.list_branches(project_id)
            await session.commit()
        except ServiceError as exc:
            return _error_payload(exc)
        return [
            {
                "name": b.name,
                "full_ref": b.full_ref,
                "kind": b.kind,
                "remote_name": b.remote_name,
                "commit_sha": b.commit_sha,
                "is_default": b.is_default,
                "is_current": b.is_current,
            }
            for b in branches
        ]


async def ocr_list_profiles() -> list[dict[str, Any]]:
    factory = get_session_factory()
    async with factory() as session:
        service = ProfileService(session)
        profiles = await service.list()
        return [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "provider_profile_id": p.provider_profile_id,
                "model_id": p.model_id,
                "language": p.language,
            }
            for p in profiles
        ]


async def ocr_preview_review(
    project_id: str,
    mode: str = "range",
    base_ref: str | None = None,
    target_ref: str | None = None,
    commit_ref: str | None = None,
    pr_number: int | None = None,
    profile_id: str | None = None,
    exclude_patterns: list[str] | None = None,
) -> dict[str, Any]:
    factory = get_session_factory()
    async with factory() as session:
        service = JobService(session)
        try:
            result = await service.preview(
                project_id=project_id,
                mode=mode,
                base_ref=base_ref,
                target_ref=target_ref,
                commit_ref=commit_ref,
                pr_number=pr_number,
                profile_id=profile_id,
                exclude_patterns=exclude_patterns,
            )
        except ServiceError as exc:
            payload = _error_payload(exc)
            if exc.code == "validation_failed":
                payload["error"]["detail"] = (
                    (payload["error"].get("detail") or "") + "\n\n" + _MODE_GUIDE
                ).strip()
            return payload
        return result.model_dump()


_MODE_GUIDE = (
    "Review modes (each needs different refs):\n"
    "  range     — compare base_ref against target_ref (two branches). "
    "base_ref defaults to the project's default branch if omitted; "
    "target_ref is required.\n"
    "  commit    — review a single commit_ref or SHA (e.g. \"HEAD\").\n"
    "  workspace — review uncommitted changes in the working tree. No refs needed.\n"
    "  pr        — review pull request pr_number head vs its base.\n"
    "  scan      — scan every supported file at the project's current commit."
)


async def ocr_submit_review(
    project_id: str,
    mode: str = "range",
    base_ref: str | None = None,
    target_ref: str | None = None,
    commit_ref: str | None = None,
    pr_number: int | None = None,
    profile_id: str | None = None,
    background: str | None = None,
    priority: int = 50,
    webhook_url: str | None = None,
    webhook_secret: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Asynchronous submission — returns a durable job id immediately.

    mode defaults to "range". In range mode, base_ref defaults to the
    project's default branch (usually "main") so only target_ref is
    strictly required.
    """

    factory = get_session_factory()
    async with factory() as session:
        service = JobService(session)
        try:
            job = await service.create(
                project_id=project_id,
                mode=mode,
                base_ref=base_ref,
                target_ref=target_ref,
                commit_ref=commit_ref,
                pr_number=pr_number,
                profile_id=profile_id,
                background=background,
                priority=priority,
                source="mcp",
                webhook_url=webhook_url,
                webhook_secret=webhook_secret,
                metadata=metadata,
            )
            queue = service._queue()
            position = await queue.queue_position(job)
            await session.commit()
        except ServiceError as exc:
            payload = _error_payload(exc)
            # Enrich missing-ref errors with the full mode guide so the
            # agent can self-correct without another round-trip.
            if exc.code == "validation_failed":
                payload["error"]["detail"] = (
                    (payload["error"].get("detail") or "") + "\n\n" + _MODE_GUIDE
                ).strip()
            return payload
        return {
            "job_id": job.id,
            "status": job.status,
            "queue_position": position,
            "status_url": f"/api/v1/jobs/{job.id}",
            "result_resource": f"ocr://jobs/{job.id}/result",
        }


def _job_payload(job: models.ReviewJob) -> dict[str, Any]:
    snapshot = job.configuration_snapshot_json or {}
    return {
        "id": job.id,
        "status": job.status,
        "status_message": job.status_message,
        "error_code": job.error_code,
        "mode": job.mode,
        "source": job.source,
        "project_id": job.project_id,
        "base_ref": job.base_ref,
        "target_ref": job.target_ref,
        "commit_ref": job.commit_ref,
        "priority": job.priority,
        "ocr_session_id": job.ocr_session_id,
        "summary": job.result_summary_json,
        "warnings": job.warnings_json,
        "resolved_shas": {
            "base_sha": snapshot.get("base_sha"),
            "target_sha": snapshot.get("target_sha"),
            "commit_sha": snapshot.get("commit_sha"),
        },
        "queued_at": job.queued_at.isoformat() if job.queued_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "status_url": f"/api/v1/jobs/{job.id}",
        "result_resource": f"ocr://jobs/{job.id}/result",
    }


def _finding_payload(finding: models.Finding) -> dict[str, Any]:
    return {
        "path": finding.path,
        "start_line": finding.start_line,
        "end_line": finding.end_line,
        "content": finding.content,
        "existing_code": finding.existing_code,
        "suggestion_code": finding.suggestion_code,
        "category": finding.category,
        "severity": finding.severity,
        "user_state": finding.user_state,
    }


async def ocr_get_job(job_id: str) -> dict[str, Any]:
    """Return status and comments for a manager job id or OCR session id."""

    factory = get_session_factory()
    async with factory() as session:
        service = JobService(session)
        try:
            job = await service.get_by_job_or_session_id(job_id)
        except ServiceError as exc:
            return _error_payload(exc)
        payload = _job_payload(job)
        findings, total = await FindingService(session).list_for_job(
            job.id, limit=10_000
        )
        payload["comments_count"] = total
        payload["comments"] = [_finding_payload(finding) for finding in findings]
        # ETA + progress so the agent knows how long to wait before polling again.
        payload.update(await EtaService(session).describe(job))

    return payload


async def ocr_get_job_results(
    job_id: str,
    timeout_seconds: int = 0,
) -> dict[str, Any]:
    """Wait for terminal state, then return the complete JSON result export.

    ``timeout_seconds=0`` waits indefinitely. A positive timeout returns the
    current status with ``wait_expired=true`` and never includes a partial
    ``result`` object.
    """

    payload = await ocr_get_job(job_id)
    if "error" in payload:
        return payload

    resolved_job_id = payload["id"]
    terminal = payload["status"] in TERMINAL_STATUSES
    if not terminal:
        terminal = await wait_for_job_terminal(resolved_job_id, timeout_seconds)
        payload = await ocr_get_job(resolved_job_id)
        if "error" in payload:
            return payload
        terminal = terminal or payload["status"] in TERMINAL_STATUSES

    payload["terminal"] = terminal
    payload["wait_expired"] = not terminal
    if not terminal:
        return payload

    factory = get_session_factory()
    async with factory() as session:
        service = JobService(session)
        try:
            content, _media, _filename = await service.export(resolved_job_id, "json")
        except ServiceError as exc:
            return _error_payload(exc)
    payload["result"] = json.loads(content)
    return payload


async def ocr_get_findings(
    job_id: str, limit: int = 200, offset: int = 0
) -> dict[str, Any]:
    factory = get_session_factory()
    async with factory() as session:
        service = FindingService(session)
        try:
            findings, total = await service.list_for_job(
                job_id, limit=limit, offset=offset
            )
        except ServiceError as exc:
            return _error_payload(exc)
        return {
            "job_id": job_id,
            "total": total,
            "findings": [_finding_payload(f) for f in findings],
        }


async def ocr_cancel_job(job_id: str) -> dict[str, Any]:
    factory = get_session_factory()
    async with factory() as session:
        service = JobService(session)
        try:
            job = await service.cancel(job_id)
            await session.commit()
        except ServiceError as exc:
            return _error_payload(exc)
        return {"job_id": job.id, "status": job.status}


async def ocr_retry_job(job_id: str) -> dict[str, Any]:
    factory = get_session_factory()
    async with factory() as session:
        service = JobService(session)
        try:
            job = await service.retry(job_id)
            await session.commit()
        except ServiceError as exc:
            return _error_payload(exc)
        return {
            "job_id": job.id,
            "status": job.status,
            "retry_of": job.retry_of_job_id,
            "status_url": f"/api/v1/jobs/{job.id}",
        }


async def ocr_reorder_job(job_id: str, action: str) -> dict[str, Any]:
    factory = get_session_factory()
    async with factory() as session:
        service = JobService(session)
        try:
            job = await service.move(job_id, action)
            position = await service._queue().queue_position(job)
            await session.commit()
        except ServiceError as exc:
            return _error_payload(exc)
        return {"job_id": job.id, "status": job.status, "queue_position": position}


async def ocr_list_mcp_servers() -> list[dict[str, Any]]:
    """List the MCP servers configured for the OpenCodeReview CLI itself."""

    return await OcrMcpServerService().list()


async def ocr_add_mcp_server(
    name: str,
    type: str = "stdio",
    command: str | None = None,
    args: list[str] | None = None,
    url: str | None = None,
    headers: dict[str, str] | None = None,
    tools: list[str] | None = None,
    setup: str | None = None,
    env: list[str] | None = None,
) -> dict[str, Any]:
    """Add or replace an MCP server in the OpenCodeReview CLI config."""

    try:
        config = OcrMcpServerConfig.model_validate(
            {
                "type": type,
                "command": command,
                "args": args,
                "url": url,
                "headers": headers,
                "tools": tools,
                "setup": setup,
                "env": env,
            }
        )
        return await OcrMcpServerService().upsert(name, config)
    except ServiceError as exc:
        return _error_payload(exc)
    except ValidationError as exc:
        # Format without echoing inputs — header/env values may hold secrets.
        details = [
            {
                "loc": [str(part) for part in err.get("loc", [])],
                "msg": err.get("msg", ""),
            }
            for err in exc.errors(include_url=False, include_input=False)
        ]
        return {
            "error": {
                "code": "validation_failed",
                "message": "The MCP server configuration is not valid.",
                "detail": details,
                "next_action": "Fix the flagged fields and retry.",
            }
        }


async def ocr_remove_mcp_server(name: str) -> dict[str, Any]:
    """Remove an MCP server from the OpenCodeReview CLI config."""

    try:
        return await OcrMcpServerService().remove(name)
    except ServiceError as exc:
        return _error_payload(exc)


# ---------------------------------------------------------------------------
# Resource implementations
# ---------------------------------------------------------------------------


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


async def resource_projects() -> str:
    return _json(await ocr_list_projects(include_unavailable=True))


async def resource_project(project_id: str) -> str:
    factory = get_session_factory()
    async with factory() as session:
        service = ProjectService(session)
        try:
            project = await service.get(project_id)
        except ServiceError as exc:
            return _json(_error_payload(exc))
        return _json(
            {
                "id": project.id,
                "display_name": project.display_name,
                "absolute_path": project.absolute_path,
                "default_branch": project.default_branch,
                "remote_url": project.remote_url,
                "current_branch": project.current_branch,
                "is_dirty": project.is_dirty,
            }
        )


async def resource_project_branches(project_id: str) -> str:
    return _json(await ocr_list_branches(project_id))


async def resource_job(job_id: str) -> str:
    return _json(await ocr_get_job(job_id))


async def resource_job_result(job_id: str) -> str:
    factory = get_session_factory()
    async with factory() as session:
        service = JobService(session)
        try:
            content, _media, _filename = await service.export(job_id, "json")
        except ServiceError as exc:
            return _json(_error_payload(exc))
        return content


async def resource_job_findings(job_id: str) -> str:
    return _json(await ocr_get_findings(job_id, limit=1000))


async def resource_job_logs(job_id: str) -> str:
    factory = get_session_factory()
    async with factory() as session:
        service = JobService(session)
        try:
            stdout = await service.read_log(job_id, "stdout")
            stderr = await service.read_log(job_id, "stderr")
        except ServiceError as exc:
            return _json(_error_payload(exc))
        return _json({"stdout": stdout, "stderr": stderr})


async def resource_ocr_mcp_servers() -> str:
    return _json(await ocr_list_mcp_servers())


# ---------------------------------------------------------------------------
# Prompts (SPEC §17 optional prompts)
# ---------------------------------------------------------------------------


def prompt_review_branch(project: str, base: str = "main", target: str = "") -> str:
    return (
        f"Review the changes on branch '{target or '<target>'}' of project "
        f"'{project}' relative to '{base}'. Use ocr_preview_review to see the "
        f"files, then ocr_submit_review with mode 'range', and call "
        f"ocr_get_job_results until the review completes. Summarize the "
        f"findings."
    )


def prompt_review_commit(project: str, commit: str) -> str:
    return (
        f"Review commit '{commit}' of project '{project}'. Use "
        f"ocr_submit_review with mode 'commit', call ocr_get_job_results "
        f"until complete, then report the findings via "
        f"ocr_get_findings."
    )


def prompt_review_workspace(project: str) -> str:
    return (
        f"Review the current uncommitted workspace changes of project "
        f"'{project}'. Submit with ocr_submit_review mode 'workspace', call "
        f"ocr_get_job_results, then summarize findings."
    )


def prompt_summarize_findings(job_id: str) -> str:
    return (
        f"Fetch the findings of review job '{job_id}' via ocr_get_findings "
        f"and summarize them by file and theme, most impactful first."
    )


def prompt_turn_findings_into_fix_plan(job_id: str) -> str:
    return (
        f"Fetch the findings of review job '{job_id}' via ocr_get_findings "
        f"and turn them into an ordered, actionable fix plan with suggested "
        f"code changes per finding."
    )


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------


def build_mcp_server() -> FastMCP:
    mcp = FastMCP(
        "code-review",
        instructions=(
            "This MCP server provides automated CODE REVIEW. When the user "
            "asks to review code, find bugs, check a PR, or audit a diff, "
            "use these tools — do NOT attempt to review the code yourself.\n\n"
            "The server name 'code-review' means: this server reviews code.\n\n"
            "WHEN THE USER SAYS:\n"
            "• \"review my code\" / \"do a code review\" / \"review the code\" / "
            "\"check my changes\" / \"review this PR\" / \"find bugs in this diff\" "
            "/ \"audit this branch\":\n"
            "  → call submit_review (the primary tool).\n"
            "• \"what did the review find?\" / \"show me the findings\":\n"
            "  → call get_findings with the job id.\n"
            "• \"is the review done?\" / \"check review status\":\n"
            "  → call get_job for an immediate status response.\n"
            "• \"wait for the review\" / \"get the review results\":\n"
            "  → call get_job_results.\n\n"
            "WORKFLOW:\n"
            "1. Find the project: call list_projects (or add_project if not "
            "   registered).\n"
            "2. Submit review: call submit_review with the project id and mode.\n"
            "3. Wait and read the complete result: call get_job_results.\n"
            "4. For a lightweight status check instead, call get_job. When it "
            "returns, wait roughly poll_interval_seconds before calling again "
            "(0 means the job is done — stop polling).\n\n"
            "MODES:\n"
            "  range (default) — compare two branches. base_ref auto-defaults "
            "  to the project's main branch; only target_ref is required.\n"
            "  commit    — review a single commit (commit_ref='HEAD' for latest).\n"
            "  workspace — review uncommitted working-tree changes.\n"
            "  pr        — review a GitHub pull request by number.\n"
            "  scan      — scan every supported file at the current commit.\n\n"
            "PROFILES:\n"
            "  Omit profile_id to use the built-in Default profile. If you get "
            "  default_profile_not_configured, tell the user to set a provider "
            "  and model on the Default profile in the UI."
        ),
        streamable_http_path="/",
        json_response=True,
        stateless_http=True,
    )

    mcp.tool(
        name="ocr_list_projects",
        description=(
            "List all registered code repositories. Call this FIRST before "
            "submitting a code review to find the project_id. "
            "Returns id, display_name, absolute_path, default_branch, "
            "and current_branch for each."
        ),
    )(ocr_list_projects)
    mcp.tool(
        name="ocr_add_project",
        description=(
            "Register a repository for code review by its absolute_path. "
            "Idempotent: if the repo is already registered, returns the "
            "existing project. Use this when ocr_submit_review or "
            "ocr_list_projects returns 'not_found' — register the repo path, "
            "then retry the review."
        ),
    )(ocr_add_project)
    mcp.tool(
        name="ocr_list_branches",
        description=(
            "List the branches of a registered project. Useful to find the "
            "correct branch name (target_ref) before submitting a range review. "
            "Pass refresh=true to re-scan, fetch=true to also git-fetch remotes."
        ),
    )(ocr_list_branches)
    mcp.tool(
        name="ocr_list_profiles",
        description=(
            "List review profiles (OCR configurations: provider, model, "
            "limits). The built-in Default profile is used automatically when "
            "profile_id is omitted on review submission."
        ),
    )(ocr_list_profiles)
    mcp.tool(
        name="ocr_preview_review",
        description=(
            "Preview which files would be included/excluded in a review "
            "WITHOUT using the LLM (fast, free). Same parameters as "
            "ocr_submit_review. Useful to check scope before running a full "
            "review."
        ),
    )(ocr_preview_review)
    mcp.tool(
        name="ocr_submit_review",
        description=(
            "CODE REVIEW tool — reviews code for bugs, security issues, and "
            "quality problems. Use this when the user says: \"do a code "
            "review\", \"review my code\", \"review the code\", \"check my "
            "changes\", \"review this branch\", \"review this PR\", \"find "
            "bugs\", \"audit this diff\", or any similar request to review code.\n\n"
            "Do NOT review the code yourself — this tool runs a dedicated "
            "code review engine (OpenCodeReview) that analyzes diffs, finds "
            "bugs, and produces structured findings.\n\n"
            "Returns a durable job_id immediately (async). After submitting, "
            "call ocr_get_job for a quick status check or "
            "ocr_get_job_results to wait for the complete result.\n\n"
            "PARAMETERS:\n"
            "  project_id  — required. Get it from ocr_list_projects.\n"
            "  mode        — optional, defaults to 'range'.\n"
            "  target_ref  — for range mode: the branch to review (e.g. "
            "'feature/my-branch'). Required.\n"
            "  base_ref    — for range mode: the comparison base. Auto-defaults "
            "to the project's main branch, so you can usually omit it.\n"
            "  commit_ref  — for commit mode: a commit SHA or ref (e.g. 'HEAD').\n"
            "  pr_number   — for pr mode: the pull request number.\n"
            "  profile_id  — optional. Omit to use the Default profile.\n\n"
            "MODES:\n"
            "  range (default) — compare base_ref..target_ref (two branches). "
            "Best for reviewing a feature branch against main.\n"
            "  commit    — review a single commit's diff. Pass commit_ref.\n"
            "  workspace — review uncommitted working-tree changes. No refs "
            "needed.\n"
            "  pr        — review a pull request. Pass pr_number.\n"
            "  scan      — scan every supported file at the current commit.\n\n"
            "RESPONSE:\n"
            "  job_id          — the durable job identifier\n"
            "  status          — 'queued' on success\n"
            "  queue_position  — position in the queue\n"
            "  status_url      — REST endpoint for polling\n"
            "  result_resource — MCP resource URI for the full result\n\n"
            "On error: returns {error: {code, message, detail, next_action}}. "
            "Common codes: 'not_found' (unknown project_id), "
            "'default_profile_not_configured' (set a provider+model on Default), "
            "'validation_failed' (missing refs — detail includes a mode guide).\n\n"
            "EXAMPLES:\n"
            "  Review current branch vs main: mode='range', "
            "target_ref='feature/x'\n"
            "  Review latest commit: mode='commit', commit_ref='HEAD'\n"
            "  Review uncommitted changes: mode='workspace'\n"
            "  Review PR #42: mode='pr', pr_number=42\n"
            "  Scan the current repository: mode='scan'"
        ),
    )(ocr_submit_review)
    mcp.tool(
        name="ocr_get_job",
        description=(
            "Return the current code review status and any available comments "
            "immediately. Pass either the manager job id or the OCR session id. "
            "Use for lightweight polling and progress checks; this tool never waits.\n\n"
            "RESPONSE FIELDS:\n"
            "  status          — queued|preparing|running|completed|completed_with_warnings|failed|cancelled|interrupted\n"
            "  status_message  — human-readable detail or error (null when ok)\n"
            "  error_code      — machine-readable failure code (e.g. 'ocr_exit',\n"
            "                    'preparation_failed'); null on success\n"
            "  summary         — stats object (only when completed): {\n"
            "                      files_reviewed, comments, input_tokens,\n"
            "                      output_tokens, cache_read_tokens,\n"
            "                      total_tokens, elapsed, warnings\n"
            "                    }\n"
            "  resolved_shas   — {base_sha, target_sha, commit_sha} resolved at queue time\n"
            "  warnings        — list of warning objects\n"
            "  ocr_session_id  — OCR session id (for log inspection)\n"
            "  comments        — review comments/findings available for the job\n"
            "  progress        — {total_files, completed_files, model_requests,\n"
            "                    percent} as the review runs; percent includes a\n"
            "                    small bounded credit per observed model request\n"
            "  eta_seconds     — estimated seconds until a terminal state (0 when done,\n"
            "                    null when not estimable)\n"
            "  eta             — human-readable ETA (e.g. \"about 3 min\")\n"
            "  poll_interval_seconds — suggested seconds to wait before calling this\n"
            "                    tool again (0 when done)"
        ),
    )(ocr_get_job)
    mcp.tool(
        name="ocr_get_job_results",
        description=(
            "Pass either the manager job id or the OCR session id. Wait until "
            "the code review reaches a terminal state, then return "
            "the complete JSON export, including summary, findings, warnings, "
            "resolved refs, and configuration snapshot. This is the blocking "
            "counterpart to the quick ocr_get_job status call. "
            "timeout_seconds=0 (default) waits indefinitely. With a positive "
            "timeout, wait_expired=true means no partial result was returned "
            "and no result object is included. The response always carries the "
            "same progress / eta_seconds / eta / poll_interval_seconds hints "
            "as ocr_get_job, so when wait_expired you can poll again after "
            "poll_interval_seconds instead of guessing."
        ),
    )(ocr_get_job_results)
    mcp.tool(
        name="ocr_get_findings",
        description=(
            "Get code review results — the bugs, issues, and findings found "
            "by the review. Use when the user asks \"what did the review "
            "find?\", \"show me the findings\", \"what are the results?\", or "
            "\"show me the bugs\". Call after get_job shows status "
            "'completed' or 'completed_with_warnings'.\n\n"
            "RESPONSE:\n"
            "  job_id   — the reviewed job\n"
            "  total    — total number of findings\n"
            "  findings — list of finding objects, each with:\n"
            "    path            — file path\n"
            "    start_line      — first line of the issue\n"
            "    end_line        — last line of the issue\n"
            "    content         — the reviewer's explanation of the problem\n"
            "    existing_code   — the problematic code snippet\n"
            "    suggestion_code — suggested fix (may be null)\n"
            "    category        — bug|security|performance|style|maintainability|test\n"
            "    severity        — high|medium|low\n"
            "    user_state      — unreviewed|accepted|dismissed|needs_followup\n\n"
            "Supports pagination via limit (default 200) and offset."
        ),
    )(ocr_get_findings)
    mcp.tool(
        name="ocr_cancel_job",
        description="Cancel a running or queued review job.",
    )(ocr_cancel_job)
    mcp.tool(
        name="ocr_retry_job",
        description=(
            "Create a retry of a failed review job. The new job uses the same "
            "project, mode, refs, and profile as the original."
        ),
    )(ocr_retry_job)
    mcp.tool(
        name="ocr_reorder_job",
        description=(
            "Move a queued job's position in the review queue: 'top' (front), "
            "'up' (one position earlier), or 'down' (one position later)."
        ),
    )(ocr_reorder_job)
    mcp.tool(
        name="ocr_list_mcp_servers",
        description=(
            "List the MCP servers configured for the OpenCodeReview review "
            "engine (NOT this server's own tools). Each listed server is "
            "connected by OCR before a review runs and its tools become "
            "available to the review agent — e.g. docs lookup, issue "
            "trackers, Cognee, or CodeGraph. Returns each server's name, "
            "type (stdio|remote), command/args or url, tool allowlist, and "
            "env setup."
        ),
    )(ocr_list_mcp_servers)
    mcp.tool(
        name="ocr_add_mcp_server",
        description=(
            "Add or replace an MCP server in the OpenCodeReview review "
            "engine's config so its tools become available to the review "
            "agent. Use when the user asks to install, connect, or add an "
            "MCP server (e.g. Cognee, CodeGraph, a docs server) for code "
            "reviews.\n\n"
            "TWO TRANSPORT TYPES:\n"
            "  stdio (default) — local subprocess. Requires command (e.g. "
            "'npx', 'uvx', or an absolute path); args carries the command "
            "arguments (e.g. [\"-y\", \"@acme/docs-mcp-server\"]). Optional: "
            "env (KEY=VALUE strings), setup (shell command run once before "
            "the server starts, e.g. 'npm install -g @acme/server').\n"
            "  remote — Streamable HTTP endpoint. Requires url "
            "(http/https) AND type='remote'; setting only url is not "
            "enough. Optional: headers (object of HTTP headers; values may "
            "reference $ENV_VARS).\n\n"
            "OPTIONAL FOR BOTH: tools — allowlist of tool names to expose "
            "to the reviewer; omit to register every tool the server "
            "offers. Prefer an allowlist to cut token cost.\n\n"
            "The change persists in the OCR user config "
            "(~/.opencodereview/config.json) and applies to every "
            "subsequent review, including jobs queued through this "
            "manager. Re-calling with an existing name replaces that "
            "server."
        ),
    )(ocr_add_mcp_server)
    mcp.tool(
        name="ocr_remove_mcp_server",
        description=(
            "Remove an MCP server from the OpenCodeReview review engine's "
            "config. Its tools stop being available to the review agent on "
            "subsequent reviews. Pass the exact server name from "
            "ocr_list_mcp_servers."
        ),
    )(ocr_remove_mcp_server)

    mcp.resource("ocr://projects", description="All registered projects.")(
        resource_projects
    )
    mcp.resource(
        "ocr://projects/{project_id}", description="One project."
    )(resource_project)
    mcp.resource(
        "ocr://projects/{project_id}/branches", description="Cached branches."
    )(resource_project_branches)
    mcp.resource("ocr://jobs/{job_id}", description="Job status.")(resource_job)
    mcp.resource(
        "ocr://jobs/{job_id}/result", description="Full JSON result export."
    )(resource_job_result)
    mcp.resource(
        "ocr://jobs/{job_id}/findings", description="Structured findings."
    )(resource_job_findings)
    mcp.resource("ocr://jobs/{job_id}/logs", description="stdout/stderr tails.")(
        resource_job_logs
    )
    mcp.resource(
        "ocr://mcp-servers",
        description="MCP servers configured for the OpenCodeReview review engine.",
    )(resource_ocr_mcp_servers)

    mcp.prompt(name="review_branch", description="Review a branch range.")(
        prompt_review_branch
    )
    mcp.prompt(name="review_commit", description="Review a single commit.")(
        prompt_review_commit
    )
    mcp.prompt(name="review_workspace", description="Review workspace changes.")(
        prompt_review_workspace
    )
    mcp.prompt(
        name="summarize_findings", description="Summarize a job's findings."
    )(prompt_summarize_findings)
    mcp.prompt(
        name="turn_findings_into_fix_plan",
        description="Turn findings into a fix plan.",
    )(prompt_turn_findings_into_fix_plan)

    return mcp
