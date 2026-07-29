"""List-page provider health probe (SPEC §9).

Covers :func:`app.services.llm_ping.probe_health` and
``ProviderService.health_check`` with ``httpx.MockTransport`` — the same
pattern as ``test_llm_ping.py``. No network, no ``ocr`` binary, no model id.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.logging import redact_text
from app.db.session import session_scope
from app.ocr.models import ProviderResolution
from app.services.errors import ValidationFailedError
from app.services.llm_ping import probe_health
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


def _models_ok() -> httpx.Response:
    return httpx.Response(200, json={"data": [{"id": "test-model"}]})


async def test_openai_health_success() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["auth"] = request.headers.get("authorization")
        return _models_ok()

    async with _client(handler) as client:
        result = await probe_health(_resolution(), http_client=client)

    assert result.ok is True
    assert result.status == "online"
    assert result.reachable is True
    assert result.authed is True
    assert result.http_status == 200
    assert result.checked_at is not None
    # GET /models, no request body, Bearer auth sent.
    assert seen["url"] == "http://llm.test/models"
    assert seen["method"] == "GET"
    assert seen["auth"] == "Bearer sk-secret-123"


async def test_keyless_2xx_is_online_green() -> None:
    """The headline behaviour: a keyless provider answering 2xx is online."""

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["has_auth"] = "authorization" in request.headers
        return _models_ok()

    async with _client(handler) as client:
        result = await probe_health(_resolution(token=None), http_client=client)

    assert result.ok is True
    assert result.status == "online"
    assert result.reachable is True
    # No credential sent, so auth is not proven — but the server is up.
    assert result.authed is False
    assert seen["has_auth"] is False


async def test_401_is_auth_needed_yellow() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text='{"error": "invalid api key"}')

    async with _client(handler) as client:
        result = await probe_health(_resolution(), http_client=client)

    assert result.ok is False
    assert result.status == "auth_needed"
    # The host answered — it is reachable — but auth failed.
    assert result.reachable is True
    assert result.authed is False
    assert result.http_status == 401
    # Secrets never leak into the detail excerpt.
    assert "sk-secret-123" not in (result.detail or "")


async def test_keyless_401_is_still_auth_needed() -> None:
    """A keyless provider returning 401 means it needs a key (yellow)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="auth required")

    async with _client(handler) as client:
        result = await probe_health(_resolution(token=None), http_client=client)

    assert result.ok is False
    assert result.status == "auth_needed"
    assert result.reachable is True


async def test_500_is_offline_red() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    async with _client(handler) as client:
        result = await probe_health(_resolution(), http_client=client)

    assert result.ok is False
    assert result.status == "offline"
    assert result.reachable is True
    assert result.http_status == 500


async def test_connection_error_is_offline() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async with _client(handler) as client:
        result = await probe_health(_resolution(), http_client=client)

    assert result.ok is False
    assert result.status == "offline"
    assert result.reachable is False
    assert result.http_status is None


async def test_timeout_is_offline() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow server", request=request)

    async with _client(handler) as client:
        result = await probe_health(_resolution(), http_client=client)

    assert result.ok is False
    assert result.status == "offline"
    assert result.reachable is False


async def test_404_falls_back_to_v1() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/models":
            return httpx.Response(404, text="no such route")
        return _models_ok()

    async with _client(handler) as client:
        # Base URL deliberately without the /v1 suffix.
        result = await probe_health(_resolution(), http_client=client)

    assert result.ok is True
    assert result.status == "online"
    assert calls == ["http://llm.test/models", "http://llm.test/v1/models"]


async def test_no_fallback_when_base_has_v1() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(404, text="no such route")

    async with _client(handler) as client:
        result = await probe_health(
            _resolution(base_url="http://llm.test/v1"), http_client=client
        )

    assert result.ok is False
    assert result.http_status == 404
    # No double-/v1 retry.
    assert calls == ["http://llm.test/v1/models"]


async def test_anthropic_health_sends_xapikey() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["api_key"] = request.headers.get("x-api-key")
        seen["version"] = request.headers.get("anthropic-version")
        return _models_ok()

    async with _client(handler) as client:
        result = await probe_health(
            _resolution(
                base_url="http://anthropic.test",
                token="sk-ant-xyz",
                protocol="anthropic",
            ),
            http_client=client,
        )

    assert result.ok is True
    assert result.status == "online"
    assert seen["url"] == "http://anthropic.test/models"
    assert seen["api_key"] == "sk-ant-xyz"
    assert seen["version"] == "2023-06-01"


async def test_token_registered_with_redactor() -> None:
    async with _client(lambda request: _models_ok()) as client:
        await probe_health(_resolution(), http_client=client)
    assert "sk-secret-123" not in redact_text("the token is sk-secret-123 ok")


# -- ProviderService.health_check --------------------------------------------


async def test_service_requires_base_url(db) -> None:
    async with session_scope() as session:
        service = ProviderService(session)
        provider = await service.create(
            name="HealthNoUrl", protocol="openai", base_url=""
        )
        with pytest.raises(ValidationFailedError) as excinfo:
            await service.health_check(provider.id)
        assert "base url" in excinfo.value.message.lower()


async def test_service_health_success_with_mock_transport(db) -> None:
    async with session_scope() as session:
        service = ProviderService(session)
        provider = await service.create(
            name="HealthOk", protocol="openai", base_url="http://llm.test"
        )
        async with _client(lambda request: _models_ok()) as client:
            result = await service.health_check(provider.id, http_client=client)
        assert result.ok is True
        assert result.status == "online"
