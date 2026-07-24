"""Provider + model management (SPEC §9).

Credentials live exclusively behind the SecretStore; DB rows hold only
``credential_reference`` strings. Model discovery for OpenAI-compatible
providers uses ``GET {base_url}/models``; failures are stored on the
provider row with actionable detail (SPEC §9 "Model Discovery").
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select

from app.core.logging import get_logger, redact_text
from app.db import models
from app.ocr.models import ProviderResolution
from app.services.deps import ServiceBase
from app.services.errors import ConflictError, NotFoundError, ValidationFailedError
from app.services.llm_ping import ConnectionTestResult, ping_llm

logger = get_logger(__name__)

#: Built-in provider presets (SPEC §9). Editable; never a hard allowlist.
PROVIDER_PRESETS: list[dict[str, Any]] = [
    {"name": "Anthropic", "provider_type": "anthropic", "protocol": "anthropic",
     "base_url": "https://api.anthropic.com"},
    {"name": "OpenAI", "provider_type": "openai", "protocol": "openai",
     "base_url": "https://api.openai.com/v1"},
    {"name": "DashScope", "provider_type": "dashscope", "protocol": "openai",
     "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
    {"name": "DeepSeek", "provider_type": "deepseek", "protocol": "openai",
     "base_url": "https://api.deepseek.com/v1"},
    {"name": "Kimi", "provider_type": "kimi", "protocol": "openai",
     "base_url": "https://api.moonshot.cn/v1"},
    {"name": "MiniMax", "provider_type": "minimax", "protocol": "openai",
     "base_url": "https://api.minimaxi.com/v1"},
    {"name": "Z.ai", "provider_type": "zai", "protocol": "openai",
     "base_url": "https://api.z.ai/api/paas/v4"},
    {"name": "Volcengine", "provider_type": "volcengine", "protocol": "openai",
     "base_url": "https://ark.cn-beijing.volces.com/api/v3"},
    {"name": "Tencent", "provider_type": "tencent", "protocol": "openai",
     "base_url": "https://api.hunyuan.cloud.tencent.com/v1"},
    {"name": "Baidu Qianfan", "provider_type": "qianfan", "protocol": "openai",
     "base_url": "https://qianfan.baidubce.com/v2"},
    {"name": "Local OpenAI-compatible", "provider_type": "local", "protocol": "openai",
     "base_url": "http://127.0.0.1:8000/v1"},
    {"name": "Custom Anthropic-compatible", "provider_type": "custom", "protocol": "anthropic",
     "base_url": ""},
    {"name": "Custom OpenAI Responses-compatible", "provider_type": "custom",
     "protocol": "openai-responses", "base_url": ""},
]

OPENAI_COMPATIBLE_PROTOCOLS = ("openai", "openai-responses")


def _credential_name(provider_id: str) -> str:
    return f"provider:{provider_id}"


class ProviderService(ServiceBase):
    # -- CRUD ---------------------------------------------------------------

    async def list(self) -> list[models.ProviderProfile]:
        result = await self.session.execute(
            select(models.ProviderProfile).order_by(models.ProviderProfile.name)
        )
        return list(result.scalars())

    async def get(self, provider_id: str) -> models.ProviderProfile:
        provider = await self.session.get(models.ProviderProfile, provider_id)
        if provider is None:
            raise NotFoundError("Provider", provider_id)
        return provider

    async def create(
        self,
        *,
        name: str,
        provider_type: str = "custom",
        protocol: str,
        base_url: str,
        credential: str | None = None,
        auth_header: str | None = None,
        http_timeout_seconds: int = 600,
        extra_headers: dict[str, str] | None = None,
        extra_body: dict[str, Any] | None = None,
        model_discovery_mode: str = "auto",
        enabled: bool = True,
    ) -> models.ProviderProfile:
        if protocol not in models.PROVIDER_PROTOCOLS:
            raise ValidationFailedError(
                f"Unsupported provider protocol '{protocol}'.",
                detail=f"Supported protocols: {', '.join(models.PROVIDER_PROTOCOLS)}.",
            )
        if model_discovery_mode not in models.MODEL_DISCOVERY_MODES:
            raise ValidationFailedError(
                f"Unsupported model discovery mode '{model_discovery_mode}'."
            )
        await self._ensure_unique_name(name)
        provider = models.ProviderProfile(
            name=name.strip(),
            provider_type=provider_type,
            protocol=protocol,
            base_url=base_url.strip(),
            auth_header=auth_header or None,
            http_timeout_seconds=http_timeout_seconds,
            extra_headers_json=extra_headers or None,
            extra_body_json=extra_body or None,
            model_discovery_mode=model_discovery_mode,
            enabled=enabled,
        )
        self.session.add(provider)
        await self.session.flush()
        if credential:
            provider.credential_reference = await self.set_credential(
                provider.id, credential
            )
            await self.session.flush()
        return provider

    async def _ensure_unique_name(self, name: str, exclude_id: str | None = None) -> None:
        stmt = select(models.ProviderProfile).where(
            models.ProviderProfile.name == name.strip()
        )
        if exclude_id:
            stmt = stmt.where(models.ProviderProfile.id != exclude_id)
        result = await self.session.execute(stmt)
        if result.scalar_one_or_none() is not None:
            raise ConflictError(
                f"A provider named '{name.strip()}' already exists.",
                next_action="Pick a different name.",
            )

    async def update(self, provider_id: str, **fields: Any) -> models.ProviderProfile:
        provider = await self.get(provider_id)
        credential = fields.pop("credential", None)
        if "name" in fields and fields["name"] is not None:
            await self._ensure_unique_name(fields["name"], exclude_id=provider_id)
            provider.name = fields["name"].strip()
        for key in (
            "provider_type", "protocol", "base_url", "auth_header",
            "http_timeout_seconds", "model_discovery_mode", "enabled",
        ):
            if key in fields and fields[key] is not None:
                setattr(provider, key, fields[key])
        if "extra_headers" in fields and fields["extra_headers"] is not None:
            provider.extra_headers_json = fields["extra_headers"]
        if "extra_body" in fields and fields["extra_body"] is not None:
            provider.extra_body_json = fields["extra_body"]
        if credential:
            provider.credential_reference = await self.set_credential(
                provider.id, credential
            )
        await self.session.flush()
        return provider

    async def delete(self, provider_id: str) -> None:
        provider = await self.get(provider_id)
        if provider.credential_reference:
            await self.secrets.delete(provider.credential_reference)
        await self.session.delete(provider)
        await self.session.flush()

    # -- credentials ---------------------------------------------------------

    async def set_credential(self, provider_id: str, value: str) -> str:
        """Store (or rotate) the provider credential; returns the reference."""

        return await self.secrets.set(_credential_name(provider_id), value)

    async def has_credential(self, provider: models.ProviderProfile) -> bool:
        if not provider.credential_reference:
            return False
        return await self.secrets.get(provider.credential_reference) is not None

    async def resolve(
        self,
        provider: models.ProviderProfile,
        *,
        model_id: str | None = None,
        language: str | None = None,
    ) -> ProviderResolution:
        """Resolve secrets into a ProviderResolution (never persisted/logged)."""

        token = None
        if provider.credential_reference:
            token = await self.secrets.get(provider.credential_reference)
        return ProviderResolution(
            base_url=provider.base_url or None,
            token=token,
            model=model_id,
            protocol=provider.protocol,
            auth_header=provider.auth_header,
            http_timeout_seconds=provider.http_timeout_seconds,
            extra_headers=dict(provider.extra_headers_json or {}),
            extra_body=dict(provider.extra_body_json or {}),
            language=language,
        )

    # -- connection test -------------------------------------------------------

    async def test_connection(
        self,
        provider_id: str,
        *,
        model_id: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> ConnectionTestResult:
        """Ping the endpoint directly with a minimal real request (SPEC §9).

        Sends "Reply with exactly: hi" to the configured endpoint via
        :func:`ping_llm` instead of shelling out to ``ocr llm test`` — this
        works for unauthenticated local servers (no API key saved). An
        explicit model selection is required; nothing is written to OCR
        config and the credential is never logged.
        """

        provider = await self.get(provider_id)
        resolution = await self.resolve(provider, model_id=model_id)
        if not (resolution.base_url or "").strip():
            raise ValidationFailedError(
                "This provider has no base URL configured.",
                next_action="Set the base URL on the provider, then retry.",
            )
        if not resolution.model:
            raise ValidationFailedError(
                "Select a model to run the connection test.",
                next_action=(
                    "Pick one of the provider's models in the test panel, "
                    "then retry."
                ),
            )
        return await ping_llm(resolution, http_client=http_client)

    # -- model discovery --------------------------------------------------------

    async def discover_models(
        self,
        provider_id: str,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> list[models.Model]:
        """Discover models for OpenAI-compatible providers (SPEC §9).

        Failures are stored on the provider row with sanitized detail.
        """

        provider = await self.get(provider_id)
        if provider.model_discovery_mode == "manual":
            raise ValidationFailedError(
                "This provider uses manual model entry.",
                next_action="Add models manually instead of running discovery.",
            )
        if provider.protocol not in OPENAI_COMPATIBLE_PROTOCOLS:
            provider.last_discovery_at = datetime.now(timezone.utc)
            provider.last_discovery_error = (
                f"Protocol '{provider.protocol}' has no compatible /models endpoint; "
                "add models manually."
            )
            await self.session.flush()
            raise ValidationFailedError(
                "This provider's protocol does not support model discovery.",
                detail=provider.last_discovery_error,
                next_action="Switch discovery mode to 'manual' and add model IDs.",
            )

        token = None
        if provider.credential_reference:
            token = await self.secrets.get(provider.credential_reference)
        url = provider.base_url.rstrip("/") + "/models"
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        owns_client = http_client is None
        client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(20.0), follow_redirects=False
        )
        try:
            response = await client.get(url, headers=headers)
            if response.status_code != 200:
                raise ValidationFailedError(
                    "Model discovery failed.",
                    detail=redact_text(
                        f"GET /models returned HTTP {response.status_code}: "
                        f"{response.text[:300]}"
                    ),
                    next_action="Check the base URL and credential, then retry.",
                )
            payload = response.json()
        except ValidationFailedError as exc:
            provider.last_discovery_at = datetime.now(timezone.utc)
            provider.last_discovery_error = exc.detail or exc.message
            await self.session.flush()
            raise
        except (httpx.HTTPError, ValueError) as exc:
            provider.last_discovery_at = datetime.now(timezone.utc)
            provider.last_discovery_error = redact_text(
                f"{type(exc).__name__}: {exc}"[:500]
            )
            await self.session.flush()
            raise ValidationFailedError(
                "Model discovery failed.",
                detail=provider.last_discovery_error,
                next_action="Check the base URL, network, and credential, then retry.",
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

        raw_models = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(raw_models, list):
            provider.last_discovery_at = datetime.now(timezone.utc)
            provider.last_discovery_error = "Response had no 'data' model list."
            await self.session.flush()
            raise ValidationFailedError(
                "Model discovery returned an unexpected payload.",
                detail="The /models response did not contain a 'data' array.",
            )

        ids = sorted(
            {
                str(item.get("id")).strip()
                for item in raw_models
                if isinstance(item, dict) and item.get("id")
            }
        )
        now = datetime.now(timezone.utc)
        existing = await self.list_models(provider_id)
        by_model_id = {m.model_id: m for m in existing}
        discovered: list[models.Model] = []
        for model_id in ids:
            row = by_model_id.get(model_id)
            if row is None:
                row = models.Model(
                    provider_profile_id=provider.id,
                    model_id=model_id,
                    is_manual=False,
                )
                self.session.add(row)
            row.last_discovered_at = now
            row.is_manual = row.is_manual and False
            discovered.append(row)
        provider.last_discovery_at = now
        provider.last_discovery_error = None
        await self.session.flush()
        return discovered

    async def list_models(self, provider_id: str) -> list[models.Model]:
        await self.get(provider_id)
        result = await self.session.execute(
            select(models.Model)
            .where(models.Model.provider_profile_id == provider_id)
            .order_by(models.Model.model_id)
        )
        return list(result.scalars())

    async def add_manual_model(
        self,
        provider_id: str,
        *,
        model_id: str,
        display_name: str | None = None,
        context_length: int | None = None,
    ) -> models.Model:
        await self.get(provider_id)
        model_id = model_id.strip()
        if not model_id:
            raise ValidationFailedError("Model id must not be empty.")
        result = await self.session.execute(
            select(models.Model).where(
                models.Model.provider_profile_id == provider_id,
                models.Model.model_id == model_id,
            )
        )
        if result.scalar_one_or_none() is not None:
            raise ConflictError(f"Model '{model_id}' already exists for this provider.")
        row = models.Model(
            provider_profile_id=provider_id,
            model_id=model_id,
            display_name=display_name,
            context_length=context_length,
            is_manual=True,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def remove_model(self, provider_id: str, model_pk: str) -> None:
        row = await self.session.get(models.Model, model_pk)
        if row is None or row.provider_profile_id != provider_id:
            raise NotFoundError("Model", model_pk)
        await self.session.delete(row)
        await self.session.flush()
