"""REST API happy-path tests via httpx ASGI transport (SPEC §19).

Drives the real app (lifespan included) with the fake OCR executable:
folders → projects → providers → profiles → job lifecycle → exports → SSE.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.main import create_app


@pytest.fixture()
async def client(settings, fake_ocr, runtime, repo):
    app = create_app(settings)

    # Run the lifespan in ONE dedicated task: the MCP session manager uses
    # anyio cancel scopes, which must be entered/exited in the same task.
    ready = asyncio.Event()
    stop = asyncio.Event()

    async def _lifespan_runner() -> None:
        async with app.router.lifespan_context(app):
            ready.set()
            await stop.wait()

    lifespan_task = asyncio.create_task(_lifespan_runner())
    await ready.wait()
    app.state.queue_worker.poll_seconds = 0.05
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as c:
            # Prime the CSRF cookie via a safe request.
            response = await c.get("/api/v1/health")
            assert response.status_code == 200
            yield c
    finally:
        stop.set()
        await asyncio.wait_for(lifespan_task, timeout=10)


def csrf(client: httpx.AsyncClient) -> dict[str, str]:
    return {"X-OCR-CSRF": client.cookies.get("ocrcc_csrf")}


async def test_health_and_csrf(client, repo) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    # State-changing request without the CSRF header is rejected.
    response = await client.post(
        "/api/v1/folders",
        json={"display_name": "x", "absolute_path": str(repo.parent)},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


async def test_system_endpoints(client) -> None:
    response = await client.get("/api/v1/system/ocr")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["version"] == "9.9.9-fake"
    response = await client.post("/api/v1/system/ocr/test", headers=csrf(client))
    assert response.status_code == 200
    response = await client.get("/api/v1/system/info")
    assert response.status_code == 200
    body = response.json()
    assert body["ocr"]["version"] == "9.9.9-fake"
    assert body["queue_worker"]["running"] is True
    assert "python_version" in body


async def test_settings_roundtrip(client) -> None:
    response = await client.get("/api/v1/settings")
    assert response.status_code == 200
    assert response.json()["queue.global_concurrency"] == 1
    response = await client.patch(
        "/api/v1/settings",
        json={"changes": {"queue.global_concurrency": 2}},
        headers=csrf(client),
    )
    assert response.status_code == 200
    assert response.json()["queue.global_concurrency"] == 2
    response = await client.patch(
        "/api/v1/settings",
        json={"changes": {"nope.key": 1}},
        headers=csrf(client),
    )
    assert response.status_code == 422


async def test_full_happy_path(client, repo, tmp_path) -> None:
    headers = csrf(client)

    # 1. Folder + scan.
    response = await client.post(
        "/api/v1/folders",
        json={"display_name": "work", "absolute_path": str(tmp_path)},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    folder_id = response.json()["id"]
    response = await client.post(f"/api/v1/folders/{folder_id}/scan", headers=headers)
    assert response.status_code == 200
    paths = [r["path"] for r in response.json()["repos"]]
    assert any("repo" in p for p in paths)

    # 2. Project.
    response = await client.post(
        "/api/v1/projects", json={"absolute_path": str(repo)}, headers=headers
    )
    assert response.status_code == 201, response.text
    project_id = response.json()["id"]
    response = await client.get(f"/api/v1/projects/{project_id}/branches")
    assert response.status_code == 200
    assert any(b["name"] == "main" for b in response.json())

    # 3. Provider + manual model.
    response = await client.post(
        "/api/v1/providers",
        json={
            "name": "APIProv",
            "protocol": "openai",
            "base_url": "https://api.example.test/v1",
            "credential": "sk-API-SECRET-000",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    provider = response.json()
    assert provider["has_credential"] is True
    assert "credential_reference" not in response.text
    assert "sk-API-SECRET-000" not in response.text
    provider_id = provider["id"]
    response = await client.post(
        f"/api/v1/providers/{provider_id}/models",
        json={"model_id": "fake-model"},
        headers=headers,
    )
    assert response.status_code == 201
    model_pk = response.json()["id"]

    # 4. Profile.
    response = await client.post(
        "/api/v1/review-profiles",
        json={
            "name": "APIProfile",
            "provider_profile_id": provider_id,
            "model_id": model_pk,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    profile_id = response.json()["id"]

    # 5. Job lifecycle (commit mode, fake OCR).
    response = await client.post(
        "/api/v1/jobs",
        json={
            "project_id": project_id,
            "mode": "commit",
            "commit_ref": "HEAD",
            "profile_id": profile_id,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    job = response.json()
    job_id = job["id"]
    assert job["status"] == "queued"
    assert job["generated_command_json"]["env"]["OCR_LLM_TOKEN"] == "***REDACTED***"
    assert "sk-API-SECRET-000" not in json.dumps(job)

    for _ in range(300):
        response = await client.get(f"/api/v1/jobs/{job_id}")
        if response.json()["status"] in {
            "completed", "completed_with_warnings", "failed", "cancelled"
        }:
            break
        await asyncio.sleep(0.1)
    job = response.json()
    assert job["status"] == "completed", job.get("status_message")
    assert job["result_summary_json"]["files_reviewed"] == 1

    # 6. Findings.
    response = await client.get(f"/api/v1/jobs/{job_id}/findings")
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 1
    finding = page["items"][0]
    assert finding["path"] == "hello.py"
    response = await client.patch(
        f"/api/v1/jobs/{job_id}/findings/{finding['id']}",
        json={"user_state": "accepted", "user_note": "lgtm"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["user_state"] == "accepted"

    # 7. Warnings/logs/session.
    response = await client.get(f"/api/v1/jobs/{job_id}/warnings")
    assert response.status_code == 200
    response = await client.get(f"/api/v1/jobs/{job_id}/logs?stream=stdout")
    assert response.status_code == 200
    assert "comments" in response.json()["text"]
    response = await client.get(f"/api/v1/jobs/{job_id}/session")
    assert response.status_code == 200
    assert response.json()["total"] >= 3

    # 8. Exports: no credentials, no reasoning by default.
    for fmt in ("md", "json", "csv", "jsonl", "txt", "agent-prompt", "github-summary"):
        response = await client.get(f"/api/v1/jobs/{job_id}/export?format={fmt}")
        assert response.status_code == 200, fmt
        assert "sk-API-SECRET-000" not in response.text
        assert "secret chain-of-thought" not in response.text
    response = await client.get(f"/api/v1/jobs/{job_id}/export?format=md")
    assert response.text.startswith("# OpenCodeReview Findings")

    # 9. Queue + events history.
    response = await client.get("/api/v1/queue")
    assert response.status_code == 200
    response = await client.get(f"/api/v1/jobs/{job_id}/events/history")
    assert response.status_code == 200
    assert len(response.json()) >= 3


async def test_sse_resume_by_last_event_id(client, repo) -> None:
    headers = csrf(client)
    response = await client.post(
        "/api/v1/projects", json={"absolute_path": str(repo)}, headers=headers
    )
    project_id = response.json()["id"]
    response = await client.post(
        "/api/v1/jobs",
        json={"project_id": project_id, "mode": "commit", "commit_ref": "HEAD"},
        headers=headers,
    )
    job_id = response.json()["id"]

    for _ in range(300):
        response = await client.get(f"/api/v1/jobs/{job_id}")
        if response.json()["status"] in {"completed", "failed"}:
            break
        await asyncio.sleep(0.1)
    assert response.json()["status"] == "completed"

    # All persisted events.
    response = await client.get(f"/api/v1/jobs/{job_id}/events/history")
    history = response.json()
    assert len(history) >= 2
    second = history[1]

    # Resume from the second event: replay must start strictly after it.
    received: list[dict] = []
    async with client.stream(
        "GET",
        f"/api/v1/jobs/{job_id}/events",
        headers={"Last-Event-ID": str(second["id"])},
    ) as stream_response:
        assert stream_response.status_code == 200
        event: dict = {}
        async for line in stream_response.aiter_lines():
            if line.startswith("id: "):
                event["id"] = int(line[4:])
            elif line.startswith("event: "):
                event["event"] = line[7:]
            elif line.startswith("data: "):
                event["data"] = line[6:]
            elif line == "" and event:
                received.append(event)
                if len(received) >= 2:
                    break
                event = {}
    assert received, "expected replayed SSE events"
    assert all(e["id"] > second["id"] for e in received)


async def test_job_validation_error_shape(client, repo) -> None:
    headers = csrf(client)
    response = await client.post(
        "/api/v1/projects", json={"absolute_path": str(repo)}, headers=headers
    )
    project_id = response.json()["id"]
    response = await client.post(
        "/api/v1/jobs",
        json={
            "project_id": project_id,
            "mode": "range",
            "base_ref": "main",
            "target_ref": "does-not-exist",
        },
        headers=headers,
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert error["message"]
    assert error["next_action"]


async def test_provider_crud_and_queue_controls(client, repo) -> None:
    headers = csrf(client)
    # Queue pause/resume.
    response = await client.post("/api/v1/queue/pause", headers=headers)
    assert response.status_code == 200
    assert response.json()["paused"] is True
    response = await client.post("/api/v1/queue/resume", headers=headers)
    assert response.status_code == 200
    assert response.json()["paused"] is False

    # Provider update + delete.
    response = await client.post(
        "/api/v1/providers",
        json={"name": "Temp", "protocol": "anthropic", "base_url": "https://api.anthropic.com"},
        headers=headers,
    )
    provider_id = response.json()["id"]
    response = await client.patch(
        f"/api/v1/providers/{provider_id}",
        json={"http_timeout_seconds": 120},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["http_timeout_seconds"] == 120
    response = await client.delete(
        f"/api/v1/providers/{provider_id}", headers=headers
    )
    assert response.status_code == 204

    # Profile duplicate.
    response = await client.post(
        "/api/v1/review-profiles", json={"name": "Base"}, headers=headers
    )
    profile_id = response.json()["id"]
    response = await client.post(
        f"/api/v1/review-profiles/{profile_id}/duplicate", headers=headers
    )
    assert response.status_code == 201
    assert response.json()["name"] == "Base copy"
