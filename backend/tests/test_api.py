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
            # The lifespan seeds an unconfigured Default profile. Bind a
            # provider + model to it so reviews submitted without a profile_id
            # (the fallback) actually run — mirroring a configured install.
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


async def test_stale_csrf_cookie_is_refreshed(client) -> None:
    client.cookies.set(
        "ocrcc_csrf", "stale-token", domain="testserver.local", path="/"
    )

    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    refreshed = client.cookies.get("ocrcc_csrf", domain="testserver.local", path="/")
    assert refreshed and refreshed != "stale-token"

    response = await client.post(
        "/api/v1/system/ocr/test",
        headers={"X-OCR-CSRF": refreshed},
    )
    assert response.status_code == 200

    client.cookies.set(
        "ocrcc_csrf", "stale-token-again", domain="testserver.local", path="/"
    )
    response = await client.post(
        "/api/v1/system/ocr/test",
        headers={"X-OCR-CSRF": "stale-token-again"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"
    assert (
        client.cookies.get("ocrcc_csrf", domain="testserver.local", path="/")
        == refreshed
    )


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


async def test_mcp_status_endpoint(client) -> None:
    response = await client.get("/api/v1/system/mcp")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["transport"] == "streamable-http"
    assert body["path"] == "/mcp"
    assert body["url"].endswith("/mcp")
    assert body["tool_count"] == 12
    assert body["resource_count"] == 7
    assert body["prompt_count"] == 5


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


async def test_server_port_setting_roundtrip(client) -> None:
    # Default value is exposed (the running port during tests).
    response = await client.get("/api/v1/settings")
    assert response.status_code == 200
    assert "server.port" in response.json()

    headers = csrf(client)
    response = await client.patch(
        "/api/v1/settings",
        json={"changes": {"server.port": 9000}},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["server.port"] == 9000

    # Persisted on reload.
    response = await client.get("/api/v1/settings")
    assert response.json()["server.port"] == 9000


async def test_server_port_setting_validates_range(client) -> None:
    headers = csrf(client)
    for bad in (0, 65536, 8372.5, "8372", True):
        response = await client.patch(
            "/api/v1/settings",
            json={"changes": {"server.port": bad}},
            headers=headers,
        )
        assert response.status_code == 422, bad
        assert response.json()["error"]["code"] == "validation_failed"


async def test_system_info_reports_running_and_configured_port(client) -> None:
    headers = csrf(client)
    # No saved override yet: configured_port == running_port.
    response = await client.get("/api/v1/system/info")
    info = response.json()
    assert info["running_port"] == info["configured_port"]

    # Save a different port: now they differ (restart needed).
    await client.patch(
        "/api/v1/settings",
        json={"changes": {"server.port": 9001}},
        headers=headers,
    )
    response = await client.get("/api/v1/system/info")
    info = response.json()
    assert info["configured_port"] == 9001
    assert info["running_port"] != 9001


async def test_resolve_port_precedence(settings, db, monkeypatch) -> None:
    """Startup precedence: CLI > OCR_CC_PORT env > saved setting > default.

    The ``settings``/``db`` fixtures wire the global singleton + migrated DB to
    a temp data dir. We keep the fixture's ``database_url`` intact so the saved
    setting is written and read through the same DB file.
    """

    from app.__main__ import _resolve_port, _read_saved_port
    from app.core.config import Settings, set_settings, get_settings
    from app.services.settings import SettingsService
    from app.db.session import session_scope

    # Base kwargs preserved across every reconstructed singleton, so the DB the
    # service writes to == the DB _read_saved_port reads from.
    base = dict(
        data_dir=settings.data_dir,
        database_url=settings.database_url,
        allowed_roots=settings.allowed_roots,
        path_restrictions_enabled=settings.path_restrictions_enabled,
    )

    monkeypatch.delenv("OCR_CC_PORT", raising=False)

    # 4. Default: no env, no saved row.
    set_settings(Settings(**base))
    assert _resolve_port(None) == 8372

    # 3. Saved setting wins over default (no env, no CLI).
    async with session_scope() as session:
        await SettingsService(session, settings=get_settings()).update(
            {"server.port": 7000}
        )
    assert _read_saved_port() == 7000
    assert _resolve_port(None) == 7000

    # 1. CLI flag wins over saved and env.
    assert _resolve_port(1234) == 1234

    # 2. OCR_CC_PORT env wins over saved (CLI absent). Env must be set before
    #    the Settings singleton is constructed for Pydantic to pick it up.
    monkeypatch.setenv("OCR_CC_PORT", "8000")
    set_settings(Settings(**base))  # reads OCR_CC_PORT at construction
    assert _resolve_port(None) == 8000



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
    for timestamp in ("queued_at", "started_at", "completed_at"):
        assert job[timestamp].endswith("Z")

    # 6. Findings.
    response = await client.get(f"/api/v1/jobs/{job_id}/findings")
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 1
    finding = page["items"][0]
    assert finding["path"] == "hello.py"
    # Reasoning is never returned by default (SPEC §38.15).
    assert finding["thinking"] is None
    assert "secret chain-of-thought" not in response.text
    # Opt-in reasoning via query param.
    response = await client.get(
        f"/api/v1/jobs/{job_id}/findings?include_reasoning=true"
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["thinking"] == "secret chain-of-thought"
    # Single-finding endpoint follows the same opt-in rule.
    response = await client.get(f"/api/v1/jobs/{job_id}/findings/{finding['id']}")
    assert response.status_code == 200
    assert response.json()["thinking"] is None
    response = await client.get(
        f"/api/v1/jobs/{job_id}/findings/{finding['id']}?include_reasoning=true"
    )
    assert response.json()["thinking"] == "secret chain-of-thought"
    response = await client.patch(
        f"/api/v1/jobs/{job_id}/findings/{finding['id']}",
        json={"user_state": "accepted", "user_note": "lgtm"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["user_state"] == "accepted"
    assert response.json()["thinking"] is None

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
    log_index = next(
        index for index, event in enumerate(history) if event["event_type"] == "job.log"
    )
    assert log_index > 0
    assert isinstance(history[log_index]["id"], int)
    second = history[log_index - 1]

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
                if event.get("event") == "job.log":
                    break
                event = {}
    assert received, "expected replayed SSE events"
    assert all(e["id"] > second["id"] for e in received)
    assert any(e["event"] == "job.log" for e in received)


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


async def test_provider_health_endpoint(client, repo) -> None:
    """GET /providers/{id}/health is read-only (no CSRF) and surfaces a
    validation error when the provider has no base URL. The auth-header and
    per-status buckets are covered in test_provider_health.py."""

    headers = csrf(client)
    response = await client.post(
        "/api/v1/providers",
        json={
            "name": "HealthNoUrl",
            "protocol": "openai",
            "base_url": "",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    provider_id = response.json()["id"]

    # GET is safe: no CSRF header required.
    response = await client.get(f"/api/v1/providers/{provider_id}/health")
    assert response.status_code == 422, response.text
    body = response.json()
    assert "base url" in body["error"]["message"].lower()


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


async def _completed_job(client, repo) -> str:
    """Create a project + commit job and wait for a terminal status."""

    headers = csrf(client)
    response = await client.post(
        "/api/v1/projects", json={"absolute_path": str(repo)}, headers=headers
    )
    assert response.status_code == 201, response.text
    project_id = response.json()["id"]
    response = await client.post(
        "/api/v1/jobs",
        json={"project_id": project_id, "mode": "commit", "commit_ref": "HEAD"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    job_id = response.json()["id"]
    for _ in range(300):
        response = await client.get(f"/api/v1/jobs/{job_id}")
        if response.json()["status"] in {
            "completed", "completed_with_warnings", "failed", "cancelled"
        }:
            break
        await asyncio.sleep(0.1)
    assert response.json()["status"] == "completed", response.json()
    return job_id


async def test_session_inspector_server_side_filters(client, repo) -> None:
    job_id = await _completed_job(client, repo)

    # Unfiltered baseline: fake OCR emits 3 session records.
    response = await client.get(f"/api/v1/jobs/{job_id}/session")
    assert response.status_code == 200
    assert response.json()["total"] == 3

    # Full-text search narrows to the records mentioning the file.
    response = await client.get(f"/api/v1/jobs/{job_id}/session?q=hello")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert all("hello" in json.dumps(r) for r in body["records"])

    # File filter (substring, case-insensitive).
    response = await client.get(f"/api/v1/jobs/{job_id}/session?file=HELLO.py")
    assert response.json()["total"] == 2
    response = await client.get(f"/api/v1/jobs/{job_id}/session?file=missing.py")
    assert response.json()["total"] == 0
    assert response.json()["records"] == []

    # Task-type filter: fake session records carry no task_type.
    response = await client.get(
        f"/api/v1/jobs/{job_id}/session?task_type=plan_task"
    )
    assert response.json()["total"] == 0

    # Filters compose; pagination applies after filtering.
    response = await client.get(
        f"/api/v1/jobs/{job_id}/session?q=hello&limit=1&offset=1"
    )
    body = response.json()
    assert body["total"] == 2
    assert len(body["records"]) == 1


async def test_diagnostics_bundle(client, repo) -> None:
    headers = csrf(client)
    # Seed a credential that must never appear in the bundle.
    response = await client.post(
        "/api/v1/providers",
        json={
            "name": "BundleProv",
            "protocol": "openai",
            "base_url": "https://api.example.test/v1",
            "credential": "sk-BUNDLE-SECRET-999",
        },
        headers=headers,
    )
    assert response.status_code == 201
    job_id = await _completed_job(client, repo)

    response = await client.get("/api/v1/system/diagnostics/bundle")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]

    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        names = set(zf.namelist())
        assert "system-info.json" in names
        assert "settings.json" in names
        assert "recent-errors.json" in names
        assert "README.txt" in names
        # Capped log excerpts for the completed job are included.
        assert any(n.startswith(f"logs/{job_id[:8]}-stdout") for n in names)
        payload = b"".join(zf.read(n) for n in names)

    text = payload.decode("utf-8", errors="replace")
    assert "sk-BUNDLE-SECRET-999" not in text
    info = json.loads(zipfile.ZipFile(io.BytesIO(response.content)).read("system-info.json"))
    assert info["ocr"]["version"] == "9.9.9-fake"
    # Log excerpts stay within the documented cap.
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        for name in zf.namelist():
            if name.startswith("logs/"):
                assert len(zf.read(name)) <= 16_000 + 512  # cap + redaction slack


async def test_profile_template_path_roundtrip(client) -> None:
    """--template is profile-owned (SPEC §8): the field persists through the
    API and is part of the planning-controls contract."""

    headers = csrf(client)
    response = await client.post(
        "/api/v1/review-profiles",
        json={"name": "Tpl", "template_path": "templates/custom.json"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    profile = response.json()
    assert profile["template_path"] == "templates/custom.json"

    response = await client.get(f"/api/v1/review-profiles/{profile['id']}")
    assert response.json()["template_path"] == "templates/custom.json"

    response = await client.patch(
        f"/api/v1/review-profiles/{profile['id']}",
        json={"template_path": "templates/v2.json"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["template_path"] == "templates/v2.json"


async def test_browse_directory_lists_subdirs_only(client, tmp_path) -> None:
    # Use a dedicated dir so fixture-created siblings (data/, repo/) don't
    # leak into the assertion.
    root = tmp_path / "root"
    root.mkdir()
    (root / "alpha").mkdir()
    (root / "beta").mkdir()
    (root / "alpha" / "nested").mkdir()
    (root / "a-file.txt").write_text("hi")  # files must be excluded
    (root / ".hidden-dir").mkdir()  # dot-dirs must be excluded

    response = await client.get("/api/v1/system/browse", params={"path": str(root)})
    assert response.status_code == 200
    body = response.json()
    assert body["path"] == str(root)
    names = {e["name"] for e in body["entries"]}
    assert names == {"alpha", "beta"}
    # Entries point under the browsed root.
    for entry in body["entries"]:
        assert entry["path"].replace("\\", "/").startswith(
            str(root).replace("\\", "/")
        )
    assert body["truncated"] is False


async def test_browse_directory_default_targets_home(client, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: tmp_path))
    (tmp_path / "visible").mkdir()

    response = await client.get("/api/v1/system/browse")
    assert response.status_code == 200
    assert response.json()["path"] == str(tmp_path)


async def test_browse_directory_provides_parent(client, tmp_path) -> None:
    child = tmp_path / "child"
    child.mkdir()

    response = await client.get("/api/v1/system/browse", params={"path": str(child)})
    assert response.status_code == 200
    assert response.json()["parent"] == str(tmp_path)


async def test_browse_directory_nonexistent_is_422(client, tmp_path) -> None:
    response = await client.get(
        "/api/v1/system/browse", params={"path": str(tmp_path / "nope")}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


async def test_browse_directory_file_is_422(client, tmp_path) -> None:
    file = tmp_path / "not-a-dir.txt"
    file.write_text("x")

    response = await client.get("/api/v1/system/browse", params={"path": str(file)})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


async def test_default_profile_seeded_and_non_deletable(client) -> None:
    """The lifespan seeds a system Default profile; it's flagged is_system and
    cannot be deleted. Newly created profiles are not system profiles."""

    response = await client.get("/api/v1/review-profiles")
    profiles = response.json()
    defaults = [p for p in profiles if p["is_system"]]
    assert len(defaults) == 1
    default = defaults[0]
    assert default["name"] == "Default"

    headers = csrf(client)
    response = await client.delete(
        f"/api/v1/review-profiles/{default['id']}", headers=headers
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"

    # A user-created profile is not a system profile.
    response = await client.post(
        "/api/v1/review-profiles",
        json={"name": "Custom"},
        headers=headers,
    )
    assert response.status_code == 201
    assert response.json()["is_system"] is False


async def test_submit_without_profile_uses_configured_default(client, repo) -> None:
    """A job submitted with no profile_id resolves to the (configured) Default
    profile rather than being rejected. The client fixture configures Default
    with a provider + model, so this should queue and complete."""

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
    assert response.status_code == 201
    job_id = response.json()["id"]

    # The job should record the system Default profile as its profile.
    default = next(p for p in (await client.get("/api/v1/review-profiles")).json() if p["is_system"])
    job = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert job["profile_id"] == default["id"]

