"""WebhookService: endpoints, HMAC signing, SSRF-safe delivery (SPEC §18).

Payload shape, headers, and signature are exactly per spec:

    X-OCR-Signature-256: sha256=HMAC_SHA256(secret, timestamp + "." + raw_body)

Delivery goes through httpx with SSRF guards (HTTPS by default, private
networks blocked unless explicitly allowed, redirects revalidated, bounded
response size/timeouts) and a fixed retry schedule with jitter.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import random
import socket
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy import select

from app.core.config import Settings
from app.core.logging import get_logger, redact_text
from app.core.secrets import SecretStore
from app.db import models
from app.services.deps import ServiceBase
from app.services.errors import NotFoundError, ValidationFailedError

logger = get_logger(__name__)

#: SPEC §18 default: terminal events only.
DEFAULT_ALLOWED_EVENTS = [
    "review.completed",
    "review.completed_with_warnings",
    "review.failed",
    "review.cancelled",
]
ALL_EVENTS = list(models.WEBHOOK_EVENTS)

#: Retry schedule in seconds (SPEC §18): immediate, 1m, 5m, 30m, 2h, 12h, 24h.
RETRY_SCHEDULE_SECONDS = [0, 60, 300, 1800, 7200, 43200, 86400]

#: Status codes that must NOT be retried (SPEC §18).
NO_RETRY_STATUSES = frozenset({400, 401, 403, 404, 410})

MAX_REDIRECTS = 3
RESPONSE_EXCERPT_LEN = 500
JITTER_FRACTION = 0.2


def sign_payload(secret: str, timestamp: str, raw_body: bytes) -> str:
    """``sha256=HMAC_SHA256(secret, timestamp + "." + raw_body)`` (SPEC §18)."""

    digest = hmac.new(
        secret.encode("utf-8"),
        timestamp.encode("utf-8") + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def verify_signature(
    secret: str, timestamp: str, raw_body: bytes, signature: str
) -> bool:
    """Constant-time verification helper (used by docs/examples + tests)."""

    expected = sign_payload(secret, timestamp, raw_body)
    return hmac.compare_digest(expected, signature)


def classify_status(status: int) -> str:
    """``success`` | ``no_retry`` | ``retry`` per SPEC §18 delivery policy."""

    if 200 <= status < 300:
        return "success"
    if status in NO_RETRY_STATUSES:
        return "no_retry"
    return "retry"  # 408/409/425/429/5xx and everything else


def parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header (seconds or HTTP-date) into seconds."""

    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    from email.utils import parsedate_to_datetime

    try:
        target = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    return max(0.0, (target - datetime.now(timezone.utc)).total_seconds())


def next_retry_delay(attempt: int, *, retry_after: float | None = None) -> float | None:
    """Delay before the next attempt, or ``None`` when attempts are exhausted.

    ``attempt`` is the 1-based number of the attempt that just failed.
    """

    if retry_after is not None:
        base = retry_after
    else:
        if attempt >= len(RETRY_SCHEDULE_SECONDS):
            return None
        base = float(RETRY_SCHEDULE_SECONDS[attempt])
    jitter = base * JITTER_FRACTION * random.random()
    return base + jitter


class SSRFError(ValidationFailedError):
    def __init__(self, detail: str) -> None:
        super().__init__(
            "The webhook URL is not allowed.",
            detail=detail,
            next_action="Use an HTTPS endpoint on a public host, or explicitly allow private targets in settings.",
        )


class WebhookService(ServiceBase):
    def __init__(self, session, *, http_client: httpx.AsyncClient | None = None, **kwargs: Any) -> None:
        super().__init__(session, **kwargs)
        self._http_client = http_client  # test hook (mock transport)

    # ------------------------------------------------------------------
    # endpoint CRUD
    # ------------------------------------------------------------------

    async def list_endpoints(self) -> list[models.WebhookEndpoint]:
        result = await self.session.execute(
            select(models.WebhookEndpoint).order_by(models.WebhookEndpoint.name)
        )
        return list(result.scalars())

    async def get_endpoint(self, endpoint_id: str) -> models.WebhookEndpoint:
        endpoint = await self.session.get(models.WebhookEndpoint, endpoint_id)
        if endpoint is None:
            raise NotFoundError("Webhook endpoint", endpoint_id)
        return endpoint

    async def create_endpoint(
        self,
        *,
        name: str,
        url: str,
        secret: str | None = None,
        allowed_events: list[str] | None = None,
        enabled: bool = True,
    ) -> models.WebhookEndpoint:
        await self.validate_target_url(url)
        events = allowed_events or list(DEFAULT_ALLOWED_EVENTS)
        invalid = set(events) - set(ALL_EVENTS) - {"test"}
        if invalid:
            raise ValidationFailedError(
                f"Unknown webhook events: {sorted(invalid)}.",
                detail=f"Supported: {', '.join(ALL_EVENTS)}.",
            )
        endpoint = models.WebhookEndpoint(
            name=name.strip(), url=url.strip(), allowed_events=events, enabled=enabled
        )
        self.session.add(endpoint)
        await self.session.flush()
        import secrets as _secrets

        secret_value = secret or _secrets.token_urlsafe(32)
        endpoint.secret_reference = await self.secrets.set(
            f"webhook:{endpoint.id}", secret_value
        )
        await self.session.flush()
        return endpoint

    async def update_endpoint(self, endpoint_id: str, **fields: Any) -> models.WebhookEndpoint:
        endpoint = await self.get_endpoint(endpoint_id)
        if "url" in fields and fields["url"]:
            await self.validate_target_url(fields["url"])
            endpoint.url = fields["url"].strip()
        if "name" in fields and fields["name"]:
            endpoint.name = fields["name"].strip()
        if "allowed_events" in fields and fields["allowed_events"] is not None:
            invalid = set(fields["allowed_events"]) - set(ALL_EVENTS) - {"test"}
            if invalid:
                raise ValidationFailedError(f"Unknown webhook events: {sorted(invalid)}.")
            endpoint.allowed_events = list(fields["allowed_events"])
        if "enabled" in fields and fields["enabled"] is not None:
            endpoint.enabled = bool(fields["enabled"])
        if fields.get("rotate_secret"):
            import secrets as _secrets

            endpoint.secret_reference = await self.secrets.set(
                f"webhook:{endpoint.id}", _secrets.token_urlsafe(32)
            )
        await self.session.flush()
        return endpoint

    async def delete_endpoint(self, endpoint_id: str) -> None:
        endpoint = await self.get_endpoint(endpoint_id)
        if endpoint.secret_reference:
            await self.secrets.delete(endpoint.secret_reference)
        await self.session.delete(endpoint)
        await self.session.flush()

    # ------------------------------------------------------------------
    # SSRF guards (SPEC §27 Webhook Security)
    # ------------------------------------------------------------------

    async def validate_target_url(self, url: str) -> str:
        settings = self.settings
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise SSRFError(f"Unsupported URL scheme '{parsed.scheme or '(none)'}'.")
        if parsed.scheme == "http" and settings.webhook_require_https:
            raise SSRFError("HTTPS is required for webhook endpoints.")
        if not parsed.hostname:
            raise SSRFError("The URL has no host.")
        if parsed.username or parsed.password:
            raise SSRFError("Credentials in webhook URLs are not allowed.")
        if not settings.webhook_allow_private_networks:
            await self._assert_public_host(parsed.hostname)
        return url

    async def _assert_public_host(self, hostname: str) -> None:
        try:
            infos = await asyncio.to_thread(
                socket.getaddrinfo, hostname, None, proto=socket.IPPROTO_TCP
            )
        except socket.gaierror as exc:
            raise SSRFError(f"Host {hostname!r} could not be resolved.") from exc
        addresses = {info[4][0] for info in infos}
        if not addresses:
            raise SSRFError(f"Host {hostname!r} resolved to no addresses.")
        for raw in addresses:
            try:
                ip = ipaddress.ip_address(raw)
            except ValueError:
                raise SSRFError(f"Host {hostname!r} resolved to an invalid address.")
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                raise SSRFError(
                    f"Host {hostname!r} resolves to a non-public address ({ip})."
                )

    # ------------------------------------------------------------------
    # payload + dispatch
    # ------------------------------------------------------------------

    def build_payload(
        self,
        *,
        delivery_id: str,
        event_type: str,
        job: models.ReviewJob,
        project_name: str | None = None,
        findings: list[models.Finding] | None = None,
    ) -> dict[str, Any]:
        """Exact SPEC §18 payload shape (credentials never included)."""

        snapshot = job.configuration_snapshot_json or {}
        summary = dict(job.result_summary_json or {})
        now = datetime.now(timezone.utc)
        return {
            "id": delivery_id,
            "event": event_type,
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "job": {
                "id": job.id,
                "source": job.source,
                "status": job.status,
                "project_id": job.project_id,
                "project_name": project_name,
                "mode": job.mode,
                "base_ref": job.base_ref,
                "target_ref": job.target_ref,
                "base_sha": snapshot.get("base_sha"),
                "target_sha": snapshot.get("target_sha"),
                "provider": (snapshot.get("provider") or {}).get("name"),
                "model": (snapshot.get("model") or {}).get("model_id"),
                "queued_at": job.queued_at.isoformat() if job.queued_at else None,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "completed_at": (
                    job.completed_at.isoformat() if job.completed_at else None
                ),
            },
            "summary": {
                "files_reviewed": summary.get("files_reviewed"),
                "comments": summary.get("comments"),
                "warnings": summary.get("warnings", len(job.warnings_json or [])),
                "input_tokens": summary.get("input_tokens"),
                "output_tokens": summary.get("output_tokens"),
                "total_tokens": summary.get("total_tokens"),
                "elapsed_ms": summary.get("elapsed_ms"),
            },
            "findings": [
                {
                    "path": f.path,
                    "start_line": f.start_line,
                    "end_line": f.end_line,
                    "content": f.content,
                    "existing_code": f.existing_code,
                    "suggestion_code": f.suggestion_code,
                }
                for f in (findings or [])
            ],
            "warnings": job.warnings_json or [],
            "metadata": {
                k: v
                for k, v in (job.request_metadata_json or {}).items()
                if k not in {"webhook_url", "webhook_secret_reference"}
            },
        }

    async def dispatch_event(
        self, session, job: models.ReviewJob, event_type: str
    ) -> list[models.WebhookDelivery]:
        """Create pending deliveries for a job event (SPEC §18 events).

        Fans out to enabled endpoints subscribed to the event, plus the
        job's per-request webhook (MCP ``webhook_url``) when present.
        """

        # ``session`` is the caller's session (same transaction as the
        # transition); the service was constructed with its own session —
        # prefer the caller's for atomicity.
        self.session = session
        deliveries: list[models.WebhookDelivery] = []

        result = await session.execute(
            select(models.WebhookEndpoint).where(models.WebhookEndpoint.enabled.is_(True))
        )
        for endpoint in result.scalars():
            if event_type not in (endpoint.allowed_events or []):
                continue
            if job.webhook_endpoint_id and job.webhook_endpoint_id != endpoint.id:
                continue
            delivery = models.WebhookDelivery(
                endpoint_id=endpoint.id,
                job_id=job.id,
                event_type=event_type,
                attempt=0,
                status="pending",
                next_attempt_at=datetime.now(timezone.utc),
            )
            session.add(delivery)
            deliveries.append(delivery)

        # Ad-hoc per-job webhook (MCP submit webhook_url).
        metadata = job.request_metadata_json or {}
        adhoc_url = metadata.get("webhook_url")
        if adhoc_url:
            endpoint = await self._ensure_adhoc_endpoint(adhoc_url, metadata)
            if event_type in (endpoint.allowed_events or DEFAULT_ALLOWED_EVENTS):
                delivery = models.WebhookDelivery(
                    endpoint_id=endpoint.id,
                    job_id=job.id,
                    event_type=event_type,
                    attempt=0,
                    status="pending",
                    next_attempt_at=datetime.now(timezone.utc),
                )
                session.add(delivery)
                deliveries.append(delivery)

        await session.flush()
        return deliveries

    async def _ensure_adhoc_endpoint(
        self, url: str, metadata: dict[str, Any]
    ) -> models.WebhookEndpoint:
        result = await self.session.execute(
            select(models.WebhookEndpoint).where(
                models.WebhookEndpoint.url == url,
                models.WebhookEndpoint.name == "mcp:ad-hoc",
            )
        )
        endpoint = result.scalar_one_or_none()
        if endpoint is None:
            endpoint = models.WebhookEndpoint(
                name="mcp:ad-hoc",
                url=url,
                allowed_events=list(DEFAULT_ALLOWED_EVENTS),
                enabled=True,
            )
            self.session.add(endpoint)
            await self.session.flush()
        secret_ref = metadata.get("webhook_secret_reference")
        if secret_ref:
            endpoint.secret_reference = secret_ref
        return endpoint

    # ------------------------------------------------------------------
    # delivery
    # ------------------------------------------------------------------

    async def list_deliveries(
        self, endpoint_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[models.WebhookDelivery]:
        await self.get_endpoint(endpoint_id)
        result = await self.session.execute(
            select(models.WebhookDelivery)
            .where(models.WebhookDelivery.endpoint_id == endpoint_id)
            .order_by(models.WebhookDelivery.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars())

    async def due_deliveries(self, *, limit: int = 20) -> list[models.WebhookDelivery]:
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            select(models.WebhookDelivery)
            .where(
                models.WebhookDelivery.status == "pending",
                models.WebhookDelivery.next_attempt_at <= now,
            )
            .order_by(models.WebhookDelivery.next_attempt_at)
            .limit(limit)
        )
        return list(result.scalars())

    async def _resolve_secret(self, endpoint: models.WebhookEndpoint) -> str:
        if endpoint.secret_reference:
            secret = await self.secrets.get(endpoint.secret_reference)
            if secret:
                return secret
        return ""  # unsigned delivery (documented: sign only when configured)

    async def _build_body(self, delivery: models.WebhookDelivery) -> bytes:
        job = None
        project_name = None
        findings: list[models.Finding] = []
        if delivery.job_id:
            job = await self.session.get(models.ReviewJob, delivery.job_id)
        if job is not None:
            project = await self.session.get(models.Project, job.project_id)
            project_name = project.display_name if project else None
            result = await self.session.execute(
                select(models.Finding).where(models.Finding.job_id == job.id)
            )
            findings = list(result.scalars())
        if job is None:
            # Test deliveries without a job carry a sample payload.
            payload = {
                "id": delivery.delivery_id,
                "event": delivery.event_type,
                "created_at": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "job": None,
                "summary": None,
                "findings": [],
                "warnings": [],
                "metadata": {"test": True},
            }
        else:
            payload = self.build_payload(
                delivery_id=delivery.delivery_id,
                event_type=delivery.event_type,
                job=job,
                project_name=project_name,
                findings=findings,
            )
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )

    async def deliver(self, delivery: models.WebhookDelivery) -> models.WebhookDelivery:
        """Attempt one delivery; update status/schedule per SPEC §18."""

        endpoint = await self.get_endpoint(delivery.endpoint_id)
        delivery.status = "delivering"
        delivery.attempt += 1
        await self.session.flush()

        body = await self._build_body(delivery)
        secret = await self._resolve_secret(endpoint)
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        headers = {
            "Content-Type": "application/json",
            "X-OCR-Event": delivery.event_type,
            "X-OCR-Delivery": delivery.delivery_id,
            "X-OCR-Timestamp": timestamp,
        }
        if secret:
            headers["X-OCR-Signature-256"] = sign_payload(secret, timestamp, body)

        http_status: int | None = None
        excerpt = ""
        error: str | None = None
        retry_after: float | None = None
        try:
            http_status, excerpt, retry_after = await self._post_with_guards(
                endpoint.url, headers, body
            )
        except (httpx.HTTPError, SSRFError, asyncio.TimeoutError) as exc:
            error = redact_text(f"{type(exc).__name__}: {exc}")[:500]

        now = datetime.now(timezone.utc)
        if http_status is not None and classify_status(http_status) == "success":
            delivery.status = "succeeded"
            delivery.http_status = http_status
            delivery.completed_at = now
            delivery.next_attempt_at = None
            endpoint.last_delivery_at = now
        elif http_status is not None and classify_status(http_status) == "no_retry":
            delivery.status = "failed"
            delivery.http_status = http_status
            delivery.completed_at = now
            delivery.next_attempt_at = None
        else:
            delay = next_retry_delay(delivery.attempt, retry_after=retry_after)
            delivery.http_status = http_status
            if delay is None:
                delivery.status = "exhausted"
                delivery.completed_at = now
                delivery.next_attempt_at = None
            else:
                delivery.status = "pending"
                delivery.next_attempt_at = now + timedelta(seconds=delay)
        delivery.response_excerpt = redact_text(
            (error or excerpt)[:RESPONSE_EXCERPT_LEN]
        )
        await self.session.flush()
        return delivery

    async def _post_with_guards(
        self, url: str, headers: dict[str, str], body: bytes
    ) -> tuple[int, str, float | None]:
        """POST with redirect revalidation + size/time limits.

        Returns ``(status, excerpt, retry_after_seconds)``.
        """

        settings: Settings = self.settings
        timeout = httpx.Timeout(settings.webhook_timeout_seconds)
        owns = self._http_client is None
        client = self._http_client or httpx.AsyncClient(
            timeout=timeout, follow_redirects=False
        )
        current_url = url
        try:
            for _hop in range(MAX_REDIRECTS + 1):
                await self.validate_target_url(current_url)
                response = await client.post(
                    current_url,
                    content=body,
                    headers=headers,
                )
                if response.is_redirect and response.headers.get("location"):
                    current_url = urljoin(current_url, response.headers["location"])
                    continue
                excerpt = response.content[: settings.webhook_max_response_bytes].decode(
                    "utf-8", errors="replace"
                )
                return (
                    response.status_code,
                    excerpt,
                    parse_retry_after(response.headers.get("retry-after")),
                )
            return 599, "too many redirects", None
        finally:
            if owns:
                await client.aclose()

    # ------------------------------------------------------------------
    # administration: test + replay
    # ------------------------------------------------------------------

    async def test_endpoint(self, endpoint_id: str) -> models.WebhookDelivery:
        endpoint = await self.get_endpoint(endpoint_id)
        delivery = models.WebhookDelivery(
            endpoint_id=endpoint.id,
            job_id=None,
            event_type="test",
            attempt=0,
            status="pending",
            next_attempt_at=datetime.now(timezone.utc),
        )
        self.session.add(delivery)
        await self.session.flush()
        return await self.deliver(delivery)

    async def replay(self, delivery_id: str) -> models.WebhookDelivery:
        delivery = await self.session.get(models.WebhookDelivery, delivery_id)
        if delivery is None:
            raise NotFoundError("Webhook delivery", delivery_id)
        delivery.status = "pending"
        delivery.attempt = 0
        delivery.http_status = None
        delivery.response_excerpt = None
        delivery.completed_at = None
        delivery.next_attempt_at = datetime.now(timezone.utc)
        # A replay must get a fresh idempotency id? SPEC: delivery UUID is
        # the idempotency key — a replay of the SAME delivery keeps it so
        # receivers can deduplicate.
        await self.session.flush()
        return delivery
