"""OCR MCP server registry (SPEC §17 extension).

Reads and writes the ``mcp_servers`` map of the OpenCodeReview CLI user
config — the same map ``ocr config set mcp_servers.<name>.<field>`` and
``ocr config unset mcp_servers.<name>`` maintain. Every configured server is
connected by OCR before a review and its tools become available to the
review agent, so this is the single integration point for attaching external
context providers (docs lookup, issue trackers, Cognee, CodeGraph, …) to
reviews.

The config file stays the source of truth: nothing is duplicated into the
manager database, and unknown keys written by the CLI itself are preserved
on every write.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

from app.core.logging import get_logger, redactor
from app.schemas.ocr_mcp import NAME_PATTERN, OcrMcpServerConfig
from app.services.errors import NotFoundError, ValidationFailedError

logger = get_logger(__name__)

_NAME_RE = re.compile(NAME_PATTERN)

#: Serializes read-modify-write cycles on the config file within this process.
_WRITE_LOCK = asyncio.Lock()


def ocr_user_config_path() -> Path:
    """Path of the OCR CLI user config.

    Honors the ``OCR_CONFIG_PATH`` override the binary itself supports, so a
    non-standard installation managed through Settings stays consistent.
    """

    override = os.environ.get("OCR_CONFIG_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".opencodereview" / "config.json"


class OcrMcpServerService:
    """CRUD over the ``mcp_servers`` map of the OCR user config."""

    # ------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------

    async def list(self) -> list[dict[str, Any]]:
        servers = self._read_servers()
        return [
            {"name": name, **self._normalize(config)}
            for name, config in sorted(servers.items())
        ]

    async def get(self, name: str) -> dict[str, Any]:
        servers = self._read_servers()
        if name not in servers:
            raise NotFoundError("MCP server", name)
        return {"name": name, **self._normalize(servers[name])}

    # ------------------------------------------------------------------
    # mutations
    # ------------------------------------------------------------------

    async def upsert(self, name: str, config: OcrMcpServerConfig) -> dict[str, Any]:
        """Create or replace one server entry and return the stored config."""

        self._validate_name(name)
        self._validate_fields(config)
        data = config.model_dump(exclude_none=True, exclude_defaults=True)
        # The transport type is the one default we always persist: it decides
        # which target field (command vs url) OCR reads, and an omitted type
        # would make a "remote" entry with only url present read as stdio.
        data.setdefault("type", config.type)

        async with _WRITE_LOCK:
            path = ocr_user_config_path()
            document = self._read_document(path)
            servers = document.setdefault("mcp_servers", {})
            replaced = name in servers
            servers[name] = data
            self._write_document(path, document)

        self._register_secrets(data)
        logger.info(
            "ocr_mcp_server_saved",
            name=name,
            type=data.get("type"),
            replaced=replaced,
        )
        return {"name": name, **data}

    async def remove(self, name: str) -> dict[str, Any]:
        """Delete one server entry and return the removed config."""

        self._validate_name(name)
        async with _WRITE_LOCK:
            path = ocr_user_config_path()
            document = self._read_document(path)
            servers = document.get("mcp_servers")
            if not isinstance(servers, dict) or name not in servers:
                raise NotFoundError("MCP server", name)
            removed = servers.pop(name)
            self._write_document(path, document)

        logger.info("ocr_mcp_server_removed", name=name)
        return {"name": name, "removed": True, **self._normalize(removed)}

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_name(name: str) -> None:
        if not _NAME_RE.match(name or ""):
            raise ValidationFailedError(
                "Invalid MCP server name.",
                detail=(
                    f"Server name {name!r} must match {NAME_PATTERN} — letters, "
                    "digits, hyphen, and underscore only (no dots, which are "
                    "the ocr config set key separator)."
                ),
                next_action="Pick a name like 'docs', 'codegraph', or 'cognee'.",
            )

    @staticmethod
    def _validate_fields(config: OcrMcpServerConfig) -> None:
        """Semantic checks pydantic cannot express (transport/target pairing)."""

        if config.type == "stdio":
            if not config.command:
                raise ValidationFailedError(
                    "A stdio MCP server requires a command.",
                    detail="Set command to the executable that starts the server (e.g. npx).",
                    next_action="Add a command, or switch the server type to remote.",
                )
        elif not config.url:
            raise ValidationFailedError(
                "A remote MCP server requires a url.",
                detail="Setting only the type is not enough: the default type is stdio.",
                next_action="Set url to the Streamable HTTP endpoint of the server.",
            )

    @staticmethod
    def _normalize(config: Any) -> dict[str, Any]:
        """Coerce one stored entry to the schema shape, tolerating CLI-written data."""

        if not isinstance(config, dict):
            return {"type": "stdio"}
        normalized = OcrMcpServerConfig.model_validate(config).model_dump(
            exclude_none=True
        )
        return normalized

    @staticmethod
    def _read_servers() -> dict[str, Any]:
        servers = OcrMcpServerService._read_document(
            ocr_user_config_path()
        ).get("mcp_servers")
        return servers if isinstance(servers, dict) else {}

    @staticmethod
    def _read_document(path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationFailedError(
                "The OpenCodeReview config file could not be read.",
                detail=f"{type(exc).__name__} while reading {path}: {exc}",
                next_action=(
                    "Fix or remove the config file, then retry. Managed MCP "
                    "servers live under its mcp_servers key."
                ),
            ) from exc
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _write_document(path: Path, document: dict[str, Any]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(document, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            tmp.replace(path)
        except OSError as exc:
            raise ValidationFailedError(
                "The OpenCodeReview config file could not be written.",
                detail=f"{type(exc).__name__} while writing {path}: {exc}",
                next_action="Check file permissions, then retry.",
            ) from exc

    @staticmethod
    def _register_secrets(data: dict[str, Any]) -> None:
        """Keep header/env secret values out of log output.

        These values live in the user config file by design (the CLI reads
        them from there), but they must never surface in manager logs.
        """

        for value in (data.get("headers") or {}).values():
            redactor.register(str(value))
        for entry in data.get("env") or []:
            redactor.register(str(entry).partition("=")[2])
