"""Structured JSON logging with credential redaction.

Uses structlog on top of stdlib logging. A process-wide :class:`Redactor`
collects secret values (registered by the SecretStore and the OCR adapter);
every log record passes through a redaction processor that replaces any
occurrence of a registered secret with ``***REDACTED***`` before rendering.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
from pathlib import Path
from typing import Any

import structlog

REDACTED = "***REDACTED***"

# Substrings that mark a value as sensitive when redacting key=value style text.
SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)(token|api[_-]?key|secret|password|authorization|auth_token|credential)"
    r"(\s*[=:]\s*)"
    r"([^\s,;&]+)"
)


class Redactor:
    """Registry of secret values that must never reach log output."""

    def __init__(self) -> None:
        self._secrets: set[str] = set()

    def register(self, value: str | None) -> None:
        if value and len(value) >= 4:  # ignore trivial values to avoid over-redaction
            self._secrets.add(value)

    def unregister(self, value: str | None) -> None:
        if value:
            self._secrets.discard(value)

    def redact(self, text: str) -> str:
        if not text:
            return text
        for secret in self._secrets:
            if secret in text:
                text = text.replace(secret, REDACTED)
        return text

    def redact_mapping(self, mapping: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in mapping.items():
            if isinstance(value, str):
                out[key] = self.redact(value)
            elif isinstance(value, dict):
                out[key] = self.redact_mapping(value)
            elif isinstance(value, (list, tuple)):
                out[key] = [
                    self.redact(v) if isinstance(v, str) else v for v in value
                ]
            else:
                out[key] = value
        return out


#: Process-wide redactor; other modules register secrets here.
redactor = Redactor()


def redact_text(text: str) -> str:
    """Redact registered secrets and obvious key=value credentials."""

    return redactor.redact(SENSITIVE_KEY_PATTERN.sub(r"\1\2" + REDACTED, text))


def _redaction_processor(
    logger: logging.Logger, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    return redactor.redact_mapping(event_dict)


def configure_logging(
    level: str = "INFO",
    log_file: Path | None = None,
    max_bytes: int = 5_000_000,
    backup_count: int = 3,
) -> None:
    """Configure structlog + stdlib root handlers. Idempotent."""

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
        )

    logging.basicConfig(level=numeric_level, handlers=handlers, force=True)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redaction_processor,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
