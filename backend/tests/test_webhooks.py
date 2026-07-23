"""WebhookService: HMAC signing known vectors, retry policy, SSRF guards,
and end-to-end delivery through an httpx mock transport (SPEC §18)."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.db import models
from app.db.session import session_scope
from app.services.errors import ValidationFailedError
from app.webhooks.service import (
    WebhookService,
    classify_status,
    next_retry_delay,
    parse_retry_after,
    sign_payload,
    verify_signature,
)

SECRET = "whsec_testsecret"
TIMESTAMP = "1721721600"
BODY = b'{"id":"d1","event":"review.completed"}'


def test_sign_payload_known_vector() -> None:
    expected = (
        "sha256="
        + hmac.new(
            SECRET.encode(), TIMESTAMP.encode() + b"." + BODY, hashlib.sha256
        ).hexdigest()
    )
    assert sign_payload(SECRET, TIMESTAMP, BODY) == expected


def test_verify_signature_constant_time() -> None:
    signature = sign_payload(SECRET, TIMESTAMP, BODY)
    assert verify_signature(SECRET, TIMESTAMP, BODY, signature)
    assert not verify_signature(SECRET, TIMESTAMP, BODY, signature[:-2] + "00")
    assert not verify_signature("other", TIMESTAMP, BODY, signature)


def test_classify_status_policy() -> None:
    assert classify_status(200) == "success"
    assert classify_status(204) == "success"
    for code in (400, 401, 403, 404, 410):
        assert classify_status(code) == "no_retry"
    for code in (408, 409, 425, 429, 500, 502, 503):
        assert classify_status(code) == "retry"


def test_parse_retry_after_seconds_and_http_date() -> None:
    assert parse_retry_after("120") == 120.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("junk") is None
    future = datetime.now(timezone.utc) + timedelta(seconds=90)
    from email.utils import format_datetime

    parsed = parse_retry_after(format_datetime(future))
    assert parsed is not None and 60 < parsed <= 90


def test_next_retry_delay_schedule_and_exhaustion() -> None:
    # attempt 1 -> schedule[1] = 60s (+ jitter)
    delay = next_retry_delay(1)
    assert delay is not None and 60 <= delay <= 72
    delay = next_retry_delay(3)
    assert delay is not None and 1800 <= delay <= 2160
    # Retry-After overrides the schedule.
    assert next_retry_delay(1, retry_after=5.0) >= 5.0
    # Exhausted after the last schedule entry.
    assert next_retry_delay(7) is None


async def test_ssrf_guards(settings) -> None:
    service = WebhookService(None, settings=settings)

    # HTTPS required by default.
    with pytest.raises(ValidationFailedError):
        await service.validate_target_url("http://example.com/hook")
    # Private/loopback blocked (IP literals need no DNS).
    with pytest.raises(ValidationFailedError):
        await service.validate_target_url("https://127.0.0.1/hook")
    with pytest.raises(ValidationFailedError):
        await service.validate_target_url("https://10.0.0.5/hook")
    with pytest.raises(ValidationFailedError):
        await service.validate_target_url("https://[::1]/hook")
    with pytest.raises(ValidationFailedError):
        await service.validate_target_url("ftp://example.com/hook")
    with pytest.raises(ValidationFailedError):
        await service.validate_target_url("https://user:pw@example.com/hook")
    # Explicitly allowed private targets skip the network checks.
    settings.webhook_allow_private_networks = True
    settings.webhook_require_https = False
    assert (
        await service.validate_target_url("http://127.0.0.1:9000/hook")
        == "http://127.0.0.1:9000/hook"
    )


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _make_endpoint(session, settings, url="http://receiver.test/hook") -> models.WebhookEndpoint:
    service = WebhookService(session, settings=settings)
    return await service.create_endpoint(name="hook", url=url, secret=SECRET)


async def _make_job(session, project_id: str, status: str = "completed") -> models.ReviewJob:
    job = models.ReviewJob(
        project_id=project_id,
        mode="range",
        base_ref="main",
        target_ref="feature",
        status=status,
        configuration_snapshot_json={
            "provider": {"id": "p1", "name": "prov"},
            "model": {"id": "m1", "model_id": "model-x"},
            "base_sha": "abc123",
            "target_sha": "def456",
        },
        result_summary_json={"files_reviewed": 3, "comments": 1, "total_tokens": 42},
        request_metadata_json={"agent_run_id": "run_123"},
    )
    session.add(job)
    await session.flush()
    return job


async def test_delivery_success_signs_and_completes(settings, project) -> None:
    settings.webhook_require_https = False
    settings.webhook_allow_private_networks = True
    project_id, _ = project
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content
        return httpx.Response(200, text="ok")

    client = _mock_client(handler)
    async with session_scope() as session:
        service = WebhookService(session, settings=settings, http_client=client)
        endpoint = await _make_endpoint(session, settings)
        job = await _make_job(session, project_id)
        deliveries = await service.dispatch_event(session, job, "review.completed")
        assert len(deliveries) == 1
        delivery = await service.deliver(deliveries[0])
        assert delivery.status == "succeeded"
        assert delivery.http_status == 200
        assert delivery.completed_at is not None

    headers = captured["headers"]
    assert headers["x-ocr-event"] == "review.completed"
    assert headers["x-ocr-delivery"] == delivery.delivery_id
    timestamp = headers["x-ocr-timestamp"]
    signature = headers["x-ocr-signature-256"]
    assert verify_signature(SECRET, timestamp, captured["body"], signature)

    payload = json.loads(captured["body"])
    assert payload["event"] == "review.completed"
    assert payload["job"]["base_sha"] == "abc123"
    assert payload["job"]["provider"] == "prov"
    assert payload["job"]["model"] == "model-x"
    assert payload["summary"]["files_reviewed"] == 3
    assert payload["metadata"] == {"agent_run_id": "run_123"}
    assert SECRET not in captured["body"].decode()


async def test_delivery_no_retry_statuses(settings, project) -> None:
    settings.webhook_require_https = False
    settings.webhook_allow_private_networks = True
    project_id, _ = project
    client = _mock_client(lambda req: httpx.Response(404, text="gone"))
    async with session_scope() as session:
        service = WebhookService(session, settings=settings, http_client=client)
        endpoint = await _make_endpoint(session, settings)
        job = await _make_job(session, project_id)
        (delivery,) = await service.dispatch_event(session, job, "review.failed")
        await service.deliver(delivery)
        assert delivery.status == "failed"
        assert delivery.next_attempt_at is None


async def test_delivery_retry_respects_retry_after(settings, project) -> None:
    settings.webhook_require_https = False
    settings.webhook_allow_private_networks = True
    project_id, _ = project
    client = _mock_client(
        lambda req: httpx.Response(429, text="slow down", headers={"Retry-After": "45"})
    )
    async with session_scope() as session:
        service = WebhookService(session, settings=settings, http_client=client)
        endpoint = await _make_endpoint(session, settings)
        job = await _make_job(session, project_id)
        (delivery,) = await service.dispatch_event(session, job, "review.failed")
        await service.deliver(delivery)
        assert delivery.status == "pending"
        assert delivery.http_status == 429
        eta = (delivery.next_attempt_at - datetime.now(timezone.utc)).total_seconds()
        assert 45 <= eta <= 60


async def test_delivery_network_error_schedules_retry(settings, project) -> None:
    settings.webhook_require_https = False
    settings.webhook_allow_private_networks = True
    project_id, _ = project

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = _mock_client(handler)
    async with session_scope() as session:
        service = WebhookService(session, settings=settings, http_client=client)
        endpoint = await _make_endpoint(session, settings)
        job = await _make_job(session, project_id)
        (delivery,) = await service.dispatch_event(session, job, "review.cancelled")
        await service.deliver(delivery)
        assert delivery.status == "pending"
        assert delivery.next_attempt_at is not None
        assert "ConnectError" in (delivery.response_excerpt or "")


async def test_event_filtering_and_replay(settings, project) -> None:
    settings.webhook_require_https = False
    settings.webhook_allow_private_networks = True
    project_id, _ = project
    client = _mock_client(lambda req: httpx.Response(200))
    async with session_scope() as session:
        service = WebhookService(session, settings=settings, http_client=client)
        endpoint = await _make_endpoint(session, settings)
        job = await _make_job(session, project_id)
        # review.queued is not in the default terminal-only filter.
        assert await service.dispatch_event(session, job, "review.queued") == []
        (delivery,) = await service.dispatch_event(session, job, "review.completed")
        await service.deliver(delivery)
        assert delivery.status == "succeeded"
        # Replay resets the delivery but keeps the idempotency id.
        replayed = await service.replay(delivery.id)
        assert replayed.status == "pending"
        assert replayed.attempt == 0
        assert replayed.delivery_id == delivery.delivery_id


async def test_test_endpoint_action(settings, db, runtime) -> None:
    settings.webhook_require_https = False
    settings.webhook_allow_private_networks = True
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(200)

    client = _mock_client(handler)
    async with session_scope() as session:
        service = WebhookService(session, settings=settings, http_client=client)
        endpoint = await _make_endpoint(session, settings)
        delivery = await service.test_endpoint(endpoint.id)
        assert delivery.status == "succeeded"
        assert delivery.event_type == "test"
        payload = json.loads(captured["body"])
        assert payload["metadata"]["test"] is True
