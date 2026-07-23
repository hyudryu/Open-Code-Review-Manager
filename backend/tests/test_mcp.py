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
        "ocr_list_branches",
        "ocr_list_profiles",
        "ocr_preview_review",
        "ocr_submit_review",
        "ocr_get_job",
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
