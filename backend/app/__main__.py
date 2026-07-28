"""``python -m app`` — single-command startup (uvicorn)."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import uvicorn

from app.core.config import get_settings


def _port(value: str) -> int:
    port = int(value)
    if port < 1 or port > 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the OpenCodeReview Manager.")
    parser.add_argument(
        "--host",
        help="Host to bind. Defaults to OCR_CC_HOST or 127.0.0.1.",
    )
    parser.add_argument(
        "--port",
        type=_port,
        help="Port to bind. Overrides OCR_CC_PORT for this startup.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    settings = get_settings()
    if args.host:
        settings.host = args.host
    if args.port is not None:
        settings.port = args.port
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=False,
    )


if __name__ == "__main__":
    main()
