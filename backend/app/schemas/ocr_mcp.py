"""Schemas for the OCR CLI's own MCP server registry.

OpenCodeReview acts as an MCP client: every entry under ``mcp_servers`` in
its user config is connected before a review and its tools become available
to the review agent. Field semantics mirror the upstream ``MCP Servers``
documentation (``type``, ``command``, ``args``, ``url``, ``headers``,
``tools``, ``setup``, ``env``) so anything saved here round-trips through
``ocr config`` unchanged.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Server names share the ``mcp_servers.<name>.<field>`` key namespace of
#: ``ocr config set``, so a dot would make the entry unreachable from the CLI.
NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"


def _strip_or_none(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) else None


class OcrMcpServerConfig(BaseModel):
    """One entry of the OCR user config's ``mcp_servers`` map."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["stdio", "remote"] = Field(
        default="stdio",
        description=(
            "stdio starts a local subprocess; remote connects to a "
            "Streamable HTTP endpoint."
        ),
    )
    command: str | None = Field(
        default=None,
        description="Executable that starts the MCP server (stdio only).",
    )
    args: list[str] | None = Field(
        default=None,
        description="Arguments passed to command (stdio only).",
    )
    url: str | None = Field(
        default=None,
        description="HTTP or HTTPS MCP endpoint (remote only).",
    )
    headers: dict[str, str] | None = Field(
        default=None,
        description=(
            "HTTP headers for the remote endpoint; values may reference "
            "$ENV_VARS expanded by OCR at connection time."
        ),
    )
    tools: list[str] | None = Field(
        default=None,
        description="Tool-name allowlist; empty or omitted registers every tool.",
    )
    setup: str | None = Field(
        default=None,
        description="Shell command run once before the server starts (stdio only).",
    )
    env: list[str] | None = Field(
        default=None,
        description=(
            "Extra subprocess environment variables as KEY=VALUE entries "
            "(stdio only)."
        ),
    )

    @field_validator("command", "url", "setup")
    @classmethod
    def _strip_strings(cls, value: str | None) -> str | None:
        return _strip_or_none(value)

    @field_validator("command", "setup")
    @classmethod
    def _single_line(cls, value: str | None) -> str | None:
        """Commands are persisted and later run by the OCR binary — a single
        line keeps the stored value reviewable and blocks multi-line payloads."""
        if value and ("\n" in value or "\r" in value):
            raise ValueError("command and setup must each be a single line")
        return _strip_or_none(value)

    @field_validator("args", "tools")
    @classmethod
    def _strip_string_lists(
        cls, value: list[str] | None
    ) -> list[str] | None:
        if value is None:
            return None
        cleaned = [item.strip() for item in value]
        return [item for item in cleaned if item] or None

    @field_validator("env")
    @classmethod
    def _strip_env_entries(cls, value: list[str] | None) -> list[str] | None:
        """Env entries must be KEY=VALUE; the value may be empty, the key may not."""
        if value is None:
            return None
        cleaned: list[str] = []
        for item in value:
            entry = item.strip()
            if not entry:
                continue
            key, sep, _rest = entry.partition("=")
            if not sep or not key.strip():
                raise ValueError(
                    "env entries must be KEY=VALUE strings "
                    "(e.g. DOCS_TOKEN=secret)"
                )
            cleaned.append(entry)
        return cleaned or None

    @field_validator("headers")
    @classmethod
    def _strip_header_map(
        cls, value: dict[str, str] | None
    ) -> dict[str, str] | None:
        if value is None:
            return None
        cleaned = {
            str(key).strip(): str(item)
            for key, item in value.items()
            if str(key).strip()
        }
        return cleaned or None


class OcrMcpServerUpsert(OcrMcpServerConfig):
    """Request body for creating or replacing an OCR MCP server."""


class OcrMcpServerOut(OcrMcpServerConfig):
    """One configured server as exposed by the API and MCP tools."""

    name: str = Field(pattern=NAME_PATTERN)
