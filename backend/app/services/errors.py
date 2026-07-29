"""Structured service-layer errors (SPEC §29).

Every error carries: what failed (``message``), why it likely failed
(``detail``), what the user can do next (``next_action``), and a machine
``code``. The API layer renders these into the SPEC §29 error envelope;
nothing here ever carries secrets or stack traces.
"""

from __future__ import annotations

from typing import Any


class ServiceError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        detail: str | None = None,
        next_action: str | None = None,
        http_status: int = 400,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail
        self.next_action = next_action
        self.http_status = http_status
        self.extra = extra or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "detail": self.detail,
                "next_action": self.next_action,
                **self.extra,
            }
        }


class NotFoundError(ServiceError):
    def __init__(self, what: str, identifier: str) -> None:
        super().__init__(
            "not_found",
            f"{what} was not found.",
            detail=f"No {what.lower()} exists with id {identifier!r}.",
            next_action="Refresh the list and pick an existing entry.",
            http_status=404,
        )


class ConflictError(ServiceError):
    def __init__(self, message: str, *, detail: str | None = None, next_action: str | None = None) -> None:
        super().__init__(
            "conflict", message, detail=detail, next_action=next_action, http_status=409
        )


class ValidationFailedError(ServiceError):
    def __init__(
        self,
        message: str,
        *,
        detail: str | None = None,
        next_action: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            "validation_failed",
            message,
            detail=detail,
            next_action=next_action,
            http_status=422,
            extra=extra,
        )


class DefaultProfileNotConfiguredError(ServiceError):
    """The system Default profile lacks a provider and/or model.

    Distinct ``code`` so MCP clients and the UI can react specifically (e.g.
    prompt the user to fill out the Default profile) rather than treat it as a
    generic validation failure.
    """

    def __init__(self, *, detail: str, next_action: str | None = None) -> None:
        super().__init__(
            "default_profile_not_configured",
            "The Default review profile isn't configured yet.",
            detail=detail,
            next_action=(
                next_action
                or "Open the Profiles page, select the Default profile, and set a "
                "provider and a model before queuing a review."
            ),
            http_status=422,
        )


class InvalidTransitionError(ServiceError):
    def __init__(self, job_id: str, current: str, target: str) -> None:
        super().__init__(
            "invalid_transition",
            f"Job cannot move from '{current}' to '{target}'.",
            detail=f"Job {job_id} is currently '{current}'; the state machine does not allow '{target}'.",
            next_action="Refresh the job and retry with an allowed action.",
            http_status=409,
        )
