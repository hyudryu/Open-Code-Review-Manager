"""MCP tool smoke tests: direct calls over app services (SPEC §17).

Tools are thin wrappers; these tests exercise them end-to-end with the fake
OCR and assert the async submission contract (immediate job id).
"""

from __future__ import annotations

import pytest

from app.mcp import server as mcp_server
from app.services.profiles import ProfileService
from app.services.providers import ProviderService
from app.db.session import session_scope


async def test_mcp_server_builds() -> None:
    mcp = mcp_server.build_mcp_server()
    tools = {tool.name for tool in await mcp.list_tools()}
    assert {
        "ocr_list_projects",
        "ocr_add_project",
        "ocr_list_branches",
        "ocr_list_profiles",
        "ocr_preview_review",
        "ocr_submit_review",
        "ocr_get_job",
        "ocr_get_job_results",
        "ocr_get_findings",
        "ocr_cancel_job",
        "ocr_retry_job",
        "ocr_reorder_job",
    } <= tools
    prompts = {prompt.name for prompt in await mcp.list_prompts()}
    assert {
        "review_branch",
        "review_commit",
        "review_workspace",
        "summarize_findings",
        "turn_findings_into_fix_plan",
    } <= prompts


async def test_submit_get_findings_flow(project, fake_ocr, make_worker) -> None:
    project_id, _ = project

    projects = await mcp_server.ocr_list_projects()
    assert any(p["id"] == project_id for p in projects)

    branches = await mcp_server.ocr_list_branches(project_id)
    assert any(b["name"] == "main" for b in branches)

    # Submission returns immediately with a durable job id (SPEC §17).
    submitted = await mcp_server.ocr_submit_review(
        project_id=project_id,
        mode="commit",
        commit_ref="HEAD",
        metadata={"agent_run_id": "run_123"},
    )
    assert submitted["status"] == "queued"
    assert submitted["queue_position"] == 1
    job_id = submitted["job_id"]
    assert submitted["status_url"].endswith(job_id)
    assert submitted["result_resource"] == f"ocr://jobs/{job_id}/result"

    worker = make_worker()
    await worker.drain()

    job = await mcp_server.ocr_get_job(job_id)
    assert job["status"] == "completed"
    assert job["summary"]["files_reviewed"] == 1
    assert job["comments_count"] == 1
    assert job["comments"][0]["path"] == "hello.py"

    # The displayed OCR session id is accepted anywhere status/results are
    # requested, so callers do not need to retain the manager job id.
    by_session = await mcp_server.ocr_get_job(job["ocr_session_id"])
    assert by_session["id"] == job_id
    assert by_session["comments"][0]["content"] == "Consider adding a docstring."
    results_by_session = await mcp_server.ocr_get_job_results(
        job["ocr_session_id"], timeout_seconds=1
    )
    assert results_by_session["terminal"] is True
    assert results_by_session["comments_count"] == 1
    assert results_by_session["result"]["findings"][0]["path"] == "hello.py"

    findings = await mcp_server.ocr_get_findings(job_id)
    assert findings["total"] == 1
    assert findings["findings"][0]["path"] == "hello.py"

    # Resources.
    import json

    result = json.loads(await mcp_server.resource_job_result(job_id))
    assert result["job"]["id"] == job_id
    assert result["findings"][0]["path"] == "hello.py"
    job_resource = json.loads(await mcp_server.resource_job(job_id))
    assert job_resource["status"] == "completed"
    logs = json.loads(await mcp_server.resource_job_logs(job_id))
    assert "stdout" in logs


async def test_cancel_and_retry_via_tools(project, fake_ocr, make_worker) -> None:
    project_id, _ = project

    submitted = await mcp_server.ocr_submit_review(
        project_id=project_id, mode="commit", commit_ref="HEAD"
    )
    job_id = submitted["job_id"]

    cancelled = await mcp_server.ocr_cancel_job(job_id)
    assert cancelled["status"] == "cancelled"

    retried = await mcp_server.ocr_retry_job(job_id)
    assert retried["retry_of"] == job_id

    worker = make_worker()
    await worker.drain()
    job = await mcp_server.ocr_get_job(retried["job_id"])
    assert job["status"] == "completed"


async def test_reorder_tool(project, fake_ocr) -> None:
    project_id, _ = project
    first = await mcp_server.ocr_submit_review(
        project_id=project_id, mode="commit", commit_ref="HEAD"
    )
    second = await mcp_server.ocr_submit_review(
        project_id=project_id, mode="commit", commit_ref="HEAD"
    )
    assert second["queue_position"] == 2
    moved = await mcp_server.ocr_reorder_job(second["job_id"], "top")
    assert moved["queue_position"] == 1
    # Bad job id yields a structured error payload, not an exception.
    error = await mcp_server.ocr_reorder_job("missing-id", "top")
    assert error["error"]["code"] == "not_found"


async def test_profiles_and_preview_tools(project, fake_ocr) -> None:
    project_id, _ = project
    async with session_scope() as session:
        providers = ProviderService(session)
        provider = await providers.create(
            name="MCPProv", protocol="openai", base_url="https://api.example.test/v1"
        )
        model = await providers.add_manual_model(provider.id, model_id="fake-model")
        profiles = ProfileService(session)
        profile = await profiles.create(
            name="MCPProfile", provider_profile_id=provider.id, model_id=model.id
        )
        profile_id = profile.id

    listed = await mcp_server.ocr_list_profiles()
    assert any(p["id"] == profile_id for p in listed)

    preview = await mcp_server.ocr_preview_review(
        project_id=project_id, mode="commit", commit_ref="HEAD", profile_id=profile_id
    )
    assert preview["ok"] is True
    assert preview["reviewable_count"] == 1
    assert preview["files"][1]["exclude_reason"] == "binary"


async def test_scan_preview_and_submission_via_mcp(
    project, fake_ocr, make_worker
) -> None:
    project_id, _ = project

    preview = await mcp_server.ocr_preview_review(
        project_id=project_id, mode="scan"
    )
    assert preview["ok"] is True
    assert preview["reviewable_count"] == 1

    submitted = await mcp_server.ocr_submit_review(
        project_id=project_id, mode="scan"
    )
    assert submitted["status"] == "queued"

    worker = make_worker()
    await worker.drain()
    job = await mcp_server.ocr_get_job(submitted["job_id"])
    assert job["status"] == "completed"
    assert job["mode"] == "scan"


async def test_add_project_registers_and_recovers_not_found(
    db, runtime, make_repo, fake_ocr
) -> None:
    """ocr_add_project recovers a not_found error from ocr_submit_review.

    Mirrors the agent workflow: submit fails because the repo isn't
    registered, the agent registers it via ocr_add_project, then retries.
    """

    repo = make_repo("agent_repo")

    # Submitting against a bogus project id yields not_found, not an exception.
    error = await mcp_server.ocr_submit_review(
        project_id="not-a-real-project", mode="commit", commit_ref="HEAD"
    )
    assert error["error"]["code"] == "not_found"

    # Register the repo the agent is working in.
    added = await mcp_server.ocr_add_project(absolute_path=str(repo))
    assert added["already_registered"] is False
    project_id = added["id"]
    assert added["absolute_path"] == str(repo)
    assert added["is_available"] is True

    # It now shows up in ocr_list_projects.
    listed = await mcp_server.ocr_list_projects()
    assert any(p["id"] == project_id for p in listed)

    # The same id now succeeds (recovery flow).
    submitted = await mcp_server.ocr_submit_review(
        project_id=project_id, mode="commit", commit_ref="HEAD"
    )
    assert submitted["status"] == "queued"


async def test_add_project_is_idempotent(project, repo) -> None:
    """Re-adding an already-registered repo returns it unchanged."""

    project_id, _ = project

    again = await mcp_server.ocr_add_project(absolute_path=str(repo))
    assert again["already_registered"] is True
    assert again["id"] == project_id

    # No duplicate row was created.
    listed = await mcp_server.ocr_list_projects()
    matches = [p for p in listed if p["absolute_path"] == str(repo)]
    assert len(matches) == 1


async def test_add_project_resolves_subdirectory(project, repo) -> None:
    """A subdirectory resolves to the registered repo's top-level."""

    project_id, _ = project
    subdir = repo / "src" / "deep"
    subdir.mkdir(parents=True)

    found = await mcp_server.ocr_add_project(absolute_path=str(subdir))
    assert found["already_registered"] is True
    assert found["id"] == project_id


async def test_add_project_rejects_non_repo(db, runtime, tmp_path) -> None:
    """A path that isn't a git repo returns a structured validation error."""

    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()

    error = await mcp_server.ocr_add_project(absolute_path=str(not_a_repo))
    assert error["error"]["code"] == "validation_failed"


async def _configure_default_profile(provider_id: str, model_id: str) -> None:
    """Seed + configure the system Default profile for MCP tests (no lifespan)."""

    async with session_scope() as session:
        service = ProfileService(session)
        default = await service.ensure_default()
        default.provider_profile_id = provider_id
        default.model_id = model_id


async def test_submit_without_profile_rejects_unconfigured_default(
    db, runtime, make_repo, fake_ocr
) -> None:
    """When profile_id is omitted and the Default profile isn't configured, the
    agent gets a structured default_profile_not_configured error it can surface."""

    repo = make_repo("agent_repo")
    async with session_scope() as session:
        await ProfileService(session).ensure_default()  # unconfigured Default

    added = await mcp_server.ocr_add_project(absolute_path=str(repo))
    project_id = added["id"]

    error = await mcp_server.ocr_submit_review(
        project_id=project_id, mode="commit", commit_ref="HEAD"
    )
    assert error["error"]["code"] == "default_profile_not_configured"
    assert "provider" in error["error"]["detail"]
    assert error["error"]["next_action"]

    # Preview is gated the same way.
    error = await mcp_server.ocr_preview_review(
        project_id=project_id, mode="commit", commit_ref="HEAD"
    )
    assert error["error"]["code"] == "default_profile_not_configured"


async def test_submit_without_profile_uses_configured_default(
    db, runtime, make_repo, make_worker, fake_ocr
) -> None:
    """Once the Default profile is configured, omitting profile_id queues a
    review that runs to completion — the happy path the agent relies on."""

    repo = make_repo("agent_repo2")
    async with session_scope() as session:
        providers = ProviderService(session)
        provider = await providers.create(
            name="DefProv", protocol="openai", base_url="https://api.example.test/v1"
        )
        model = await providers.add_manual_model(provider.id, model_id="def-model")
        provider_id, model_pk = provider.id, model.id
    await _configure_default_profile(provider_id, model_pk)

    added = await mcp_server.ocr_add_project(absolute_path=str(repo))
    project_id = added["id"]

    submitted = await mcp_server.ocr_submit_review(
        project_id=project_id, mode="commit", commit_ref="HEAD"
    )
    assert submitted["status"] == "queued"
    job_id = submitted["job_id"]

    worker = make_worker()
    await worker.drain()

    job = await mcp_server.ocr_get_job(job_id)
    assert job["status"] == "completed"
    findings = await mcp_server.ocr_get_findings(job_id)
    assert findings["total"] >= 1


async def test_default_profile_not_deletable(db, runtime) -> None:
    """The system Default profile is protected from deletion."""

    async with session_scope() as session:
        service = ProfileService(session)
        default = await service.ensure_default()
        default_id = default.id
        from app.services.errors import ConflictError

        with pytest.raises(ConflictError):
            await service.delete(default_id)


async def _configure_default_for_range_tests(make_repo) -> str:
    """Set up a provider+model on Default and return a registered project id."""
    repo = make_repo("range_repo")
    async with session_scope() as session:
        providers = ProviderService(session)
        provider = await providers.create(
            name="RangeProv", protocol="openai", base_url="https://api.example.test/v1"
        )
        model = await providers.add_manual_model(provider.id, model_id="range-model")
        provider_id, model_pk = provider.id, model.id
    await _configure_default_profile(provider_id, model_pk)
    added = await mcp_server.ocr_add_project(absolute_path=str(repo))
    return added["id"]


async def test_submit_default_mode_defaults_to_range(db, runtime, make_repo, fake_ocr) -> None:
    """Omitting mode defaults to 'range'. With no target_ref, the error should
    be self-documenting and mention all modes."""
    project_id = await _configure_default_for_range_tests(make_repo)
    result = await mcp_server.ocr_submit_review(project_id=project_id)
    assert "error" in result
    err = result["error"]
    assert err["code"] == "validation_failed"
    # The mode guide must be appended so the agent can self-correct.
    assert "range" in err["detail"]
    assert "commit" in err["detail"]
    assert "workspace" in err["detail"]
    assert "pr" in err["detail"]
    assert "scan" in err["detail"]


async def test_submit_range_auto_defaults_base_ref(db, runtime, make_repo, make_worker, fake_ocr) -> None:
    """In range mode, omitting base_ref auto-defaults to the project's
    default branch. Only target_ref is required."""
    project_id = await _configure_default_for_range_tests(make_repo)
    # The test repo only has 'main', so review main..main (valid range).
    submitted = await mcp_server.ocr_submit_review(
        project_id=project_id, target_ref="main"
    )
    assert "status" in submitted, f"unexpected error: {submitted}"
    assert submitted["status"] == "queued"
    job_id = submitted["job_id"]

    worker = make_worker()
    await worker.drain()
    job = await mcp_server.ocr_get_job(job_id)
    assert job["status"] in ("completed", "completed_with_warnings")
    # base_sha should be resolved (the auto-defaulted base branch).
    resolved = job.get("resolved_shas", {})
    assert resolved.get("base_sha") is not None
    assert resolved.get("target_sha") is not None
