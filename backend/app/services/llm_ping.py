"""Direct minimal LLM ping behind the provider connection test (SPEC §9).

Sends one tiny "Reply with exactly: hi" request straight to the configured
endpoint over httpx instead of shelling out to ``ocr llm test``. This works
for unauthenticated local inference servers (no API key saved) and never
writes OCR config or logs the credential.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from pydantic import BaseModel

from app.core.logging import get_logger, redact_text, redactor
from app.ocr.models import ProviderResolution

logger = get_logger(__name__)

#: The entire prompt — success means the model replies (usually "hi").
PING_PROMPT = "Reply with exactly: hi"

#: Cap for sanitized response-body excerpts surfaced on failure.
MAX_FAILURE_BODY_CHARS = 300

#: Cap for the model reply excerpt surfaced on success.
MAX_REPLY_CHARS = 120

#: A ping must stay quick even when the provider allows long job timeouts.
PING_TIMEOUT_CAP_SECONDS = 60.0

#: A list-page health probe must stay snappy — dead providers cannot stall
#: the whole table. Five seconds is enough for a slow cold start while
#: keeping the page interactive.
HEALTH_TIMEOUT_CAP_SECONDS = 5.0


class ConnectionTestResult(BaseModel):
    """Structured result of a direct endpoint ping.

    Field-for-field compatible with the ``ProviderTestOut`` API schema
    (``exit_code``/``stdout``/``stderr`` stay schema-side defaults from the
    retired ``ocr llm test`` path).
    """

    ok: bool
    status: Literal["ok", "failed"]
    elapsed_ms: float | None = None
    message: str | None = None
    reply: str | None = None  # sanitized excerpt of the model's reply
    http_status: int | None = None
    detail: str | None = None  # sanitized: what failed / why
    next_action: str | None = None  # what the user can do next


def _request_spec(
    resolution: ProviderResolution,
) -> tuple[str, str, dict[str, Any], dict[str, str]]:
    """(path, /v1 fallback path, body, headers) for the resolved protocol."""

    protocol = resolution.protocol or "openai"
    token = resolution.token
    headers: dict[str, str] = {}

    if protocol == "anthropic":
        body: dict[str, Any] = {
            "model": resolution.model,
            "max_tokens": 8,
            "messages": [{"role": "user", "content": PING_PROMPT}],
        }
        headers["anthropic-version"] = "2023-06-01"
        if token:
            headers[resolution.auth_header or "x-api-key"] = token
        return "/messages", "/v1/messages", body, headers

    if protocol == "openai-responses":
        body = {
            "model": resolution.model,
            "input": PING_PROMPT,
            "max_output_tokens": 16,
        }
        if token:
            if resolution.auth_header:
                headers[resolution.auth_header] = token
            else:
                headers["Authorization"] = f"Bearer {token}"
        return "/responses", "/v1/responses", body, headers

    # openai (chat completions)
    body = {
        "model": resolution.model,
        "messages": [{"role": "user", "content": PING_PROMPT}],
        "max_tokens": 8,
        **resolution.extra_body,
    }
    if token:
        if resolution.auth_header:
            headers[resolution.auth_header] = token
        else:
            headers["Authorization"] = f"Bearer {token}"
    return "/chat/completions", "/v1/chat/completions", body, headers


def _extract_reply(protocol: str, payload: Any) -> str | None:
    """Pull the model's reply text out of a protocol-shaped response."""

    if not isinstance(payload, dict):
        return None
    if protocol == "anthropic":
        content = payload.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    text = block["text"].strip()
                    if text:
                        return text
        return None
    if protocol == "openai-responses":
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()
        output = payload.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                for block in item.get("content") or []:
                    if isinstance(block, dict) and isinstance(block.get("text"), str):
                        text = block["text"].strip()
                        if text:
                            return text
        return None
    # openai (chat completions)
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            text = message["content"].strip()
            if text:
                return text
    return None


def _failure_for_status(status_code: int) -> tuple[str, str]:
    """SPEC §29-style (message, next_action) for an HTTP failure status."""

    if status_code in (401, 403):
        return (
            "Authentication failed.",
            "Check the API key (or auth header override) for this provider, then retry.",
        )
    if status_code == 404:
        return (
            "The endpoint path was not found.",
            "Check the base URL — include or omit the /v1 suffix as your server expects.",
        )
    if status_code == 429:
        return (
            "The endpoint rate-limited the request.",
            "Wait a moment and retry, or lower per-provider concurrency.",
        )
    if status_code >= 500:
        return (
            "The endpoint returned a server error.",
            "Check the inference server's logs, then retry.",
        )
    return (
        "The endpoint rejected the request.",
        "Check the protocol, model id, and extra request fields, then retry.",
    )


async def ping_llm(
    resolution: ProviderResolution,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> ConnectionTestResult:
    """Send the minimal ping request; never raises, never logs secrets."""

    base_url = (resolution.base_url or "").rstrip("/")
    protocol = resolution.protocol or "openai"

    # Register secrets with the process-wide redactor before any logging.
    redactor.register(resolution.token)
    for value in resolution.extra_headers.values():
        redactor.register(value)

    path, fallback_path, body, headers = _request_spec(resolution)
    headers.update(resolution.extra_headers)
    timeout = httpx.Timeout(
        min(float(resolution.http_timeout_seconds or 30), PING_TIMEOUT_CAP_SECONDS)
    )

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(
        timeout=timeout, follow_redirects=False
    )
    start = time.monotonic()
    try:
        response = await client.post(base_url + path, json=body, headers=headers)
        if response.status_code == 404 and not base_url.endswith("/v1"):
            # Base URL without the /v1 suffix — retry against the versioned path.
            response = await client.post(
                base_url + fallback_path, json=body, headers=headers
            )
        elapsed_ms = (time.monotonic() - start) * 1000
    except httpx.TimeoutException:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info("llm_ping_timeout", protocol=protocol)
        return ConnectionTestResult(
            ok=False,
            status="failed",
            elapsed_ms=elapsed_ms,
            message="The connection timed out.",
            detail=f"No response within {timeout.read:.0f} s.",
            next_action=(
                "Check that the server is running and reachable from this "
                "machine, then retry."
            ),
        )
    except httpx.HTTPError as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info("llm_ping_transport_error", protocol=protocol, error=type(exc).__name__)
        return ConnectionTestResult(
            ok=False,
            status="failed",
            elapsed_ms=elapsed_ms,
            message="Could not reach the endpoint.",
            detail=redact_text(f"{type(exc).__name__}: {exc}")[:MAX_FAILURE_BODY_CHARS],
            next_action="Check the base URL and that the server is running, then retry.",
        )
    finally:
        if owns_client:
            await client.aclose()

    if not 200 <= response.status_code < 300:
        message, next_action = _failure_for_status(response.status_code)
        logger.info(
            "llm_ping_http_error", protocol=protocol, http_status=response.status_code
        )
        return ConnectionTestResult(
            ok=False,
            status="failed",
            elapsed_ms=elapsed_ms,
            http_status=response.status_code,
            message=message,
            detail=redact_text(
                f"HTTP {response.status_code}: "
                f"{response.text[:MAX_FAILURE_BODY_CHARS]}"
            ),
            next_action=next_action,
        )

    try:
        payload = response.json()
    except ValueError:
        return ConnectionTestResult(
            ok=False,
            status="failed",
            elapsed_ms=elapsed_ms,
            http_status=response.status_code,
            message="The endpoint returned a non-JSON response.",
            detail=redact_text(response.text[:MAX_FAILURE_BODY_CHARS]),
            next_action="Check that the base URL points at an LLM API endpoint.",
        )

    reply = _extract_reply(protocol, payload)
    if not reply:
        return ConnectionTestResult(
            ok=False,
            status="failed",
            elapsed_ms=elapsed_ms,
            http_status=response.status_code,
            message="The endpoint responded, but no reply text could be parsed.",
            detail=redact_text(response.text[:MAX_FAILURE_BODY_CHARS]),
            next_action=(
                "Check that the selected model supports this protocol's "
                "response shape."
            ),
        )

    excerpt = redact_text(reply)[:MAX_REPLY_CHARS]
    logger.info("llm_ping_ok", protocol=protocol, elapsed_ms=round(elapsed_ms))
    return ConnectionTestResult(
        ok=True,
        status="ok",
        elapsed_ms=elapsed_ms,
        http_status=response.status_code,
        reply=excerpt,
    )


# ---------------------------------------------------------------------------
# Lightweight list-page health probe (no model required).
# ---------------------------------------------------------------------------


class HealthProbeResult(BaseModel):
    """Structured result of a keyless ``GET /models`` reachability probe.

    ``reachable`` distinguishes "the host answered" from "it answered 2xx":
    a keyless provider returning 401/403 is reachable but not authenticated,
    which the UI renders as a distinct "auth needed" state. ``authed`` is
    True only when a credential was supplied AND accepted (2xx).
    """

    ok: bool
    status: Literal["online", "auth_needed", "offline", "unauthorized"]
    reachable: bool
    authed: bool
    elapsed_ms: float | None = None
    http_status: int | None = None
    detail: str | None = None  # sanitized: what failed / why
    checked_at: datetime


def _health_headers(resolution: ProviderResolution) -> dict[str, str]:
    """Auth headers for ``GET /models`` (sent only when a credential exists)."""

    headers: dict[str, str] = {}
    token = resolution.token
    if not token:
        return headers
    protocol = resolution.protocol or "openai"
    if protocol == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
        headers[resolution.auth_header or "x-api-key"] = token
    elif resolution.auth_header:
        headers[resolution.auth_header] = token
    else:
        headers["Authorization"] = f"Bearer {token}"
    headers.update(resolution.extra_headers)
    return headers


async def probe_health(
    resolution: ProviderResolution,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> HealthProbeResult:
    """Lightweight ``GET /models`` reachability probe; never raises, never logs secrets.

    Unlike :func:`ping_llm`, this sends no model/credentials-shaped body and
    needs no model id, so it works for every provider on the list page
    (including keyless local servers). It only asks "did the endpoint answer
    our request?" — a 2xx is "online", 401/403 is "auth needed", anything
    else is "offline".
    """

    base_url = (resolution.base_url or "").rstrip("/")
    protocol = resolution.protocol or "openai"

    # Register secrets with the process-wide redactor before any logging.
    redactor.register(resolution.token)
    for value in resolution.extra_headers.values():
        redactor.register(value)

    headers = _health_headers(resolution)
    timeout = httpx.Timeout(HEALTH_TIMEOUT_CAP_SECONDS)
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(
        timeout=timeout, follow_redirects=False
    )
    start = time.monotonic()
    try:
        response = await client.get(base_url + "/models", headers=headers)
        if response.status_code == 404 and not base_url.endswith("/v1"):
            # Base URL without the /v1 suffix — retry against the versioned path.
            response = await client.get(
                base_url + "/v1/models", headers=headers
            )
        elapsed_ms = (time.monotonic() - start) * 1000
    except httpx.TimeoutException:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info("provider_health_timeout", protocol=protocol)
        return HealthProbeResult(
            ok=False,
            status="offline",
            reachable=False,
            authed=False,
            elapsed_ms=elapsed_ms,
            detail=f"No response within {timeout.read:.0f} s.",
            checked_at=datetime.now(timezone.utc),
        )
    except httpx.HTTPError as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "provider_health_transport_error",
            protocol=protocol,
            error=type(exc).__name__,
        )
        return HealthProbeResult(
            ok=False,
            status="offline",
            reachable=False,
            authed=False,
            elapsed_ms=elapsed_ms,
            detail=redact_text(f"{type(exc).__name__}: {exc}")[
                :MAX_FAILURE_BODY_CHARS
            ],
            checked_at=datetime.now(timezone.utc),
        )
    finally:
        if owns_client:
            await client.aclose()

    # We reached a responding server — that is "reachable" regardless of
    # the status it returned. A keyless 2xx means the server genuinely
    # does not require auth, so it counts as authed too.
    reachable = True
    authed = 200 <= response.status_code < 300 and bool(resolution.token)

    if response.status_code in (401, 403):
        logger.info(
            "provider_health_auth_needed",
            protocol=protocol,
            http_status=response.status_code,
        )
        return HealthProbeResult(
            ok=False,
            status="auth_needed",
            reachable=reachable,
            authed=False,
            elapsed_ms=elapsed_ms,
            http_status=response.status_code,
            detail=redact_text(
                f"HTTP {response.status_code}: "
                f"{response.text[:MAX_FAILURE_BODY_CHARS]}"
            ),
            checked_at=datetime.now(timezone.utc),
        )

    if not 200 <= response.status_code < 300:
        message, _ = _failure_for_status(response.status_code)
        logger.info(
            "provider_health_http_error",
            protocol=protocol,
            http_status=response.status_code,
        )
        return HealthProbeResult(
            ok=False,
            status="offline",
            reachable=reachable,
            authed=False,
            elapsed_ms=elapsed_ms,
            http_status=response.status_code,
            detail=redact_text(
                f"{message} "
                f"HTTP {response.status_code}: "
                f"{response.text[:MAX_FAILURE_BODY_CHARS]}"
            ),
            checked_at=datetime.now(timezone.utc),
        )

    logger.info(
        "provider_health_ok",
        protocol=protocol,
        http_status=response.status_code,
        elapsed_ms=round(elapsed_ms),
    )
    return HealthProbeResult(
        ok=True,
        status="online",
        reachable=reachable,
        authed=authed,
        elapsed_ms=elapsed_ms,
        http_status=response.status_code,
        checked_at=datetime.now(timezone.utc),
    )
