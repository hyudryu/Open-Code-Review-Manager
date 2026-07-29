"""wait_for_terminal: server-side blocking job completion wait (MCP + REST).

The MCP tool and the REST endpoint share ``app.services.waits`` — an async
long-poll over the in-process event bus with a periodic DB safety re-check.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.db.session import session_scope
from app.main import create_app
from app.mcp import server as mcp_server
from app.queue.bus import get_event_bus
from app.services.jobs import JobService
from app.services.waits import wait_for_job_terminal


async def _create_job(project_id: str, **kwargs) -> str:
    async with session_scope() as session:
        service = JobService(session)
        job = await service.create(project_id=project_id, **kwargs)
        return job.id


# --- MCP tool -------------------------------------------------------------


async def test_wait_returns_promptly_when_already_terminal(
    project, fake_ocr, make_worker
) -> None:
    project_id, _ = project
    job_id = await _create_job(project_id, mode="commit", commit_ref="HEAD")
    worker = make_worker()
    await worker.drain()

    loop = asyncio.get_running_loop()
    start = loop.time()
    payload = await mcp_server.ocr_get_job_results(job_id, timeout_seconds=30)
    elapsed = loop.time() - start

    assert elapsed < 5  # no actual waiting happened
    assert payload["status"] == "completed"
    assert payload["terminal"] is True
    assert payload["wait_expired"] is False
    assert payload["result"]["job"]["id"] == job_id


async def test_wait_blocks_until_job_completes(
    project, fake_ocr, make_worker, monkeypatch
) -> None:
    monkeypatch.setenv("FAKE_OCR_SLEEP", "1")  # job is mid-flight while we wait
    project_id, _ = project
    job_id = await _create_job(project_id, mode="commit", commit_ref="HEAD")
    worker = make_worker()
    drain_task = asyncio.create_task(worker.drain())

    payload = await mcp_server.ocr_get_job_results(job_id, timeout_seconds=60)
    await drain_task

    assert payload["status"] == "completed"
    assert payload["terminal"] is True
    assert payload["wait_expired"] is False
    assert payload["summary"]["files_reviewed"] == 1
    assert payload["completed_at"] is not None
    assert payload["result"]["findings"]


async def test_wait_timeout_returns_current_status(project, fake_ocr) -> None:
    project_id, _ = project
    job_id = await _create_job(project_id, mode="commit", commit_ref="HEAD")
    # No worker ever runs — the job stays queued.

    loop = asyncio.get_running_loop()
    start = loop.time()
    payload = await mcp_server.ocr_get_job_results(job_id, timeout_seconds=1)
    elapsed = loop.time() - start

    assert elapsed >= 1
    assert payload["status"] == "queued"
    assert payload["terminal"] is False
    assert payload["wait_expired"] is True
    assert "result" not in payload


async def test_wait_missing_job_returns_error_immediately(project, fake_ocr) -> None:
    loop = asyncio.get_running_loop()
    start = loop.time()
    payload = await mcp_server.ocr_get_job_results(
        "missing-id", timeout_seconds=60
    )
    assert loop.time() - start < 5
    assert payload["error"]["code"] == "not_found"


async def test_default_call_has_no_wait_flags(project, fake_ocr, make_worker) -> None:
    project_id, _ = project
    job_id = await _create_job(project_id, mode="commit", commit_ref="HEAD")
    payload = await mcp_server.ocr_get_job(job_id)
    assert payload["status"] == "queued"
    assert "terminal" not in payload
    assert "wait_expired" not in payload


# --- bus subscription hygiene ----------------------------------------------


async def test_no_leaked_subscription_after_timeout(project, fake_ocr) -> None:
    project_id, _ = project
    job_id = await _create_job(project_id, mode="commit", commit_ref="HEAD")
    bus = get_event_bus()

    terminal = await wait_for_job_terminal(job_id, timeout_seconds=1)

    assert terminal is False
    assert job_id not in bus._subscribers


async def test_no_leaked_subscription_after_cancellation(project, fake_ocr) -> None:
    project_id, _ = project
    job_id = await _create_job(project_id, mode="commit", commit_ref="HEAD")
    bus = get_event_bus()

    task = asyncio.create_task(wait_for_job_terminal(job_id, timeout_seconds=60))
    await asyncio.sleep(0.2)  # let it subscribe
    assert bus._subscribers.get(job_id)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert job_id not in bus._subscribers


# --- REST parity ------------------------------------------------------------


@pytest.fixture()
async def client(settings, fake_ocr, runtime, repo):
    app = create_app(settings)

    # Lifespan in ONE dedicated task: anyio cancel scopes must be entered
    # and exited in the same task (same pattern as test_api.py).
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
            response = await c.get("/api/v1/health")
            assert response.status_code == 200
            # Bind a provider + model to the seeded system Default profile so
            # jobs submitted without a profile_id (the fallback) can run.
            h = {"X-OCR-CSRF": c.cookies.get("ocrcc_csrf")}
            r = await c.post(
                "/api/v1/providers",
                json={"name": "DefaultProv", "protocol": "openai"},
                headers=h,
            )
            provider_id = r.json()["id"]
            r = await c.post(
                f"/api/v1/providers/{provider_id}/models",
                json={"model_id": "default-model"},
                headers=h,
            )
            model_id = r.json()["id"]
            default = next(
                p for p in (await c.get("/api/v1/review-profiles")).json()
                if p["is_system"]
            )
            await c.patch(
                f"/api/v1/review-profiles/{default['id']}",
                json={"provider_profile_id": provider_id, "model_id": model_id},
                headers=h,
            )
            yield c
    finally:
        stop.set()
        await asyncio.wait_for(lifespan_task, timeout=10)


def _csrf(client: httpx.AsyncClient) -> dict[str, str]:
    return {"X-OCR-CSRF": client.cookies.get("ocrcc_csrf")}


async def _submit_job(client: httpx.AsyncClient, repo) -> str:
    response = await client.post(
        "/api/v1/projects",
        json={"absolute_path": str(repo)},
        headers=_csrf(client),
    )
    assert response.status_code == 201, response.text
    project_id = response.json()["id"]
    response = await client.post(
        "/api/v1/jobs",
        json={"project_id": project_id, "mode": "commit", "commit_ref": "HEAD"},
        headers=_csrf(client),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_rest_wait_for_terminal_returns_completed(
    client, repo, monkeypatch
) -> None:
    monkeypatch.setenv("FAKE_OCR_SLEEP", "1")
    job_id = await _submit_job(client, repo)

    # The lifespan queue worker runs the job; the GET blocks until terminal.
    response = await client.get(
        f"/api/v1/jobs/{job_id}",
        params={"wait_for_terminal": "true", "timeout_seconds": 60},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"
    assert response.json()["completed_at"] is not None


async def test_rest_wait_timeout_returns_current_status(
    client, repo, monkeypatch
) -> None:
    # Even if the worker dequeues the job before we pause it, the fake OCR
    # sleeps 30s, so the job can never reach a terminal state during the wait.
    monkeypatch.setenv("FAKE_OCR_SLEEP", "30")
    job_id = await _submit_job(client, repo)
    await client.post(f"/api/v1/jobs/{job_id}/pause", headers=_csrf(client))

    loop = asyncio.get_running_loop()
    start = loop.time()
    response = await client.get(
        f"/api/v1/jobs/{job_id}",
        params={"wait_for_terminal": "true", "timeout_seconds": 1},
    )
    elapsed = loop.time() - start

    assert response.status_code == 200, response.text
    assert elapsed >= 1
    assert response.json()["status"] in {"queued", "running"}  # non-terminal
