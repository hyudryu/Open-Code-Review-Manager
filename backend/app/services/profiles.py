"""Review profile management: CRUD + duplicate (SPEC §4, §8)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.db import models
from app.services.deps import ServiceBase
from app.services.errors import ConflictError, NotFoundError, ValidationFailedError

_EDITABLE_FIELDS = (
    "name",
    "description",
    "provider_profile_id",
    "model_id",
    "language",
    "concurrency",
    "per_file_timeout_minutes",
    "llm_http_timeout_seconds",
    "max_tools",
    "max_git_processes",
    "plan_mode",
    "plan_threshold_lines",
    "max_tokens",
    "template_path",
    "exclude_patterns",
    "rule_file_path",
    "tools_file_path",
    "background_template",
    "additional_arguments",
)


class ProfileService(ServiceBase):
    async def list(self) -> list[models.ReviewProfile]:
        result = await self.session.execute(
            select(models.ReviewProfile).order_by(models.ReviewProfile.name)
        )
        return list(result.scalars())

    async def get(self, profile_id: str) -> models.ReviewProfile:
        profile = await self.session.get(models.ReviewProfile, profile_id)
        if profile is None:
            raise NotFoundError("Review profile", profile_id)
        return profile

    async def _validate(self, fields: dict[str, Any]) -> None:
        plan_mode = fields.get("plan_mode")
        if plan_mode is not None and plan_mode not in models.PLAN_MODES:
            raise ValidationFailedError(
                f"Unsupported plan mode '{plan_mode}'.",
                detail=f"Supported: {', '.join(models.PLAN_MODES)}.",
            )
        additional = fields.get("additional_arguments")
        if additional:
            from app.core.security import AdditionalArgsError, parse_additional_arguments

            try:
                parse_additional_arguments(additional)
            except AdditionalArgsError as exc:
                raise ValidationFailedError(
                    "The additional arguments are not allowed.",
                    detail=str(exc),
                    next_action="Remove shell metacharacters and control-plane-owned flags.",
                ) from exc

    async def _ensure_unique_name(self, name: str, exclude_id: str | None = None) -> None:
        stmt = select(models.ReviewProfile).where(models.ReviewProfile.name == name.strip())
        if exclude_id:
            stmt = stmt.where(models.ReviewProfile.id != exclude_id)
        result = await self.session.execute(stmt)
        if result.scalar_one_or_none() is not None:
            raise ConflictError(
                f"A review profile named '{name.strip()}' already exists.",
                next_action="Pick a different name.",
            )

    async def create(self, **fields: Any) -> models.ReviewProfile:
        unknown = set(fields) - set(_EDITABLE_FIELDS)
        if unknown:
            raise ValidationFailedError(f"Unknown profile fields: {sorted(unknown)}")
        if not fields.get("name"):
            raise ValidationFailedError("Profile name is required.")
        await self._validate(fields)
        await self._ensure_unique_name(fields["name"])
        profile = models.ReviewProfile(
            **{k: v for k, v in fields.items() if k in _EDITABLE_FIELDS}
        )
        self.session.add(profile)
        await self.session.flush()
        return profile

    async def update(self, profile_id: str, **fields: Any) -> models.ReviewProfile:
        profile = await self.get(profile_id)
        fields = {k: v for k, v in fields.items() if k in _EDITABLE_FIELDS and v is not None}
        await self._validate(fields)
        if "name" in fields:
            await self._ensure_unique_name(fields["name"], exclude_id=profile_id)
        for key, value in fields.items():
            setattr(profile, key, value)
        await self.session.flush()
        return profile

    async def delete(self, profile_id: str) -> None:
        profile = await self.get(profile_id)
        await self.session.delete(profile)
        await self.session.flush()

    async def duplicate(
        self, profile_id: str, *, new_name: str | None = None
    ) -> models.ReviewProfile:
        source = await self.get(profile_id)
        base_name = new_name or f"{source.name} copy"
        name = base_name
        suffix = 2
        while True:
            try:
                await self._ensure_unique_name(name)
                break
            except ConflictError:
                name = f"{base_name} {suffix}"
                suffix += 1
        clone = models.ReviewProfile(
            **{field: getattr(source, field) for field in _EDITABLE_FIELDS if field != "name"},
            name=name,
        )
        self.session.add(clone)
        await self.session.flush()
        return clone
