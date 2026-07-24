"""Direct LLM ping behind the provider connection test (SPEC §9).

Covers ``app.services.llm_ping.ping_llm`` with ``httpx.MockTransport`` plus
``ProviderService.test_connection`` validation — no ``ocr`` binary involved.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.logging import redact_text
from app.db.session import session_scope
from app.ocr.models import ProviderResolution
from app.services.errors import ValidationFailedError
from app.services.llm_ping import PING_PROMPT, ping_llm
from app.services.providers import ProviderService


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)


def _resolution(**overrides) -> ProviderResolution:
    base = {
        "base_url": "http://llm.test",
        "token": "sk-secret-123",
        "model": "test-model",
        "protocol": "openai",
        "http_timeout_seconds": 30,
    }
    return ProviderResolution(**(base | overrides))


def _openai_ok(reply: str = "hi") -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": reply}}]},
    )


async def test_openai_ping_success() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return _openai_ok()

    async with _client(handler) as client:
        result = await ping_llm(_resolution(), http_client=client)

    assert result.ok is True
    assert result.status == "ok"
    assert result.reply == "hi"
    assert result.elapsed_ms is not None and result.elapsed_ms >= 0
    assert seen["url"] == "http://llm.test/chat/completions"
    assert seen["auth"] == "Bearer sk-secret-123"
    body = seen["body"]
    assert body["model"] == "test-model"
    assert body["messages"] == [{"role": "user", "content": PING_PROMPT}]
    assert body["max_tokens"] == 8


async def test_openai_ping_404_falls_back_to_v1() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/chat/completions":
            return httpx.Response(404, text="no such route")
        return _openai_ok()

    async with _client(handler) as client:
        # Base URL deliberately without the /v1 suffix.
        result = await ping_llm(_resolution(), http_client=client)

    assert result.ok is True
    assert result.reply == "hi"
    assert calls == [
        "http://llm.test/chat/completions",
        "http://llm.test/v1/chat/completions",
    ]


async def test_openai_ping_no_fallback_when_base_has_v1() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(404, text="no such route")

    async with _client(handler) as client:
        result = await ping_llm(
            _resolution(base_url="http://llm.test/v1"), http_client=client
        )

    assert result.ok is False
    assert result.http_status == 404
    # No double-/v1 retry.
    assert calls == ["http://llm.test/v1/chat/completions"]


async def test_anthropic_ping_success() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["api_key"] = request.headers.get("x-api-key")
        seen["version"] = request.headers.get("anthropic-version")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"content": [{"type": "text", "text": "hi"}]}
        )

    async with _client(handler) as client:
        result = await ping_llm(
            _resolution(
                base_url="http://anthropic.test",
                token="sk-ant-xyz",
                protocol="anthropic",
            ),
            http_client=client,
        )

    assert result.ok is True
    assert result.reply == "hi"
    assert seen["url"] == "http://anthropic.test/messages"
    assert seen["api_key"] == "sk-ant-xyz"
    assert seen["version"] == "2023-06-01"
    assert seen["body"]["max_tokens"] == 8


async def test_auth_header_omitted_without_token() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["has_auth"] = "authorization" in request.headers
        seen["has_api_key"] = "x-api-key" in request.headers
        return _openai_ok()

    async with _client(handler) as client:
        # Unauthenticated local server: no credential saved.
        result = await ping_llm(_resolution(token=None), http_client=client)

    assert result.ok is True
    assert seen["has_auth"] is False
    assert seen["has_api_key"] is False


async def test_401_maps_to_actionable_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text='{"error": "invalid api key"}')

    async with _client(handler) as client:
        result = await ping_llm(_resolution(), http_client=client)

    assert result.ok is False
    assert result.status == "failed"
    assert result.http_status == 401
    assert "Authentication" in (result.message or "")
    assert result.next_action
    assert "HTTP 401" in (result.detail or "")
    # Secrets never leak into the detail excerpt.
    assert "sk-secret-123" not in (result.detail or "")


async def test_timeout_maps_to_actionable_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow server", request=request)

    async with _client(handler) as client:
        result = await ping_llm(_resolution(), http_client=client)

    assert result.ok is False
    assert result.status == "failed"
    assert "timed out" in (result.message or "").lower()
    assert result.next_action


async def test_unparseable_success_body_is_a_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    async with _client(handler) as client:
        result = await ping_llm(_resolution(), http_client=client)

    assert result.ok is False
    assert "reply" in (result.message or "").lower()


async def test_token_registered_with_redactor() -> None:
    async with _client(lambda request: _openai_ok()) as client:
        await ping_llm(_resolution(), http_client=client)
    assert "sk-secret-123" not in redact_text("the token is sk-secret-123 ok")


# -- ProviderService.test_connection -------------------------------------------


async def test_service_requires_explicit_model(db) -> None:
    async with session_scope() as session:
        service = ProviderService(session)
        provider = await service.create(
            name="PingNoModel", protocol="openai", base_url="http://llm.test"
        )
        with pytest.raises(ValidationFailedError) as excinfo:
            await service.test_connection(provider.id)
        assert "model" in excinfo.value.message.lower()


async def test_service_requires_base_url(db) -> None:
    async with session_scope() as session:
        service = ProviderService(session)
        provider = await service.create(
            name="PingNoUrl", protocol="openai", base_url=""
        )
        with pytest.raises(ValidationFailedError) as excinfo:
            await service.test_connection(provider.id, model_id="m1")
        assert "base url" in excinfo.value.message.lower()


async def test_service_ping_success_with_mock_transport(db) -> None:
    async with session_scope() as session:
        service = ProviderService(session)
        provider = await service.create(
            name="PingOk", protocol="openai", base_url="http://llm.test"
        )
        async with _client(lambda request: _openai_ok()) as client:
            result = await service.test_connection(
                provider.id, model_id="test-model", http_client=client
            )
        assert result.ok is True
        assert result.reply == "hi"
