"""Unit tests for the OCR self-update service (npm install resolution)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import ocr_update
from app.services.ocr_update import OCRUpdateError, npm_install_argv


def _write_shim_layout(shim: Path, script_body: str = "") -> Path:
    """Create an npm-style shim plus the npm-cli.js file it points at."""

    shim.parent.mkdir(parents=True, exist_ok=True)
    shim.write_text(
        "@ECHO off\r\n"
        'endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  '
        '"%dp0%\\node_modules\\npm\\bin\\npm-cli.js" %*\r\n',
        encoding="utf-8",
    )
    script = shim.parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(script_body, encoding="utf-8")
    return script


def test_npm_install_argv_posix(monkeypatch, tmp_path) -> None:
    npm = tmp_path / "bin" / "npm"
    npm.parent.mkdir(parents=True)
    npm.write_text("#!/bin/sh\n")
    monkeypatch.setattr(ocr_update.shutil, "which", lambda name: str(npm))
    monkeypatch.setattr(ocr_update, "_IS_WINDOWS", False)

    assert npm_install_argv() == [
        str(npm),
        "install",
        "-g",
        ocr_update.OCR_NPM_PACKAGE,
    ]


def test_npm_install_argv_windows_unwraps_shim(monkeypatch, tmp_path) -> None:
    shim = tmp_path / "npm-root" / "npm.CMD"
    script = _write_shim_layout(shim)
    node = tmp_path / "node.exe"
    node.write_text("")
    monkeypatch.setattr(
        ocr_update.shutil,
        "which",
        lambda name: str(shim) if name == "npm" else str(node),
    )
    monkeypatch.setattr(ocr_update, "_IS_WINDOWS", True)

    argv = npm_install_argv()
    assert [Path(argv[0]), Path(argv[1])] == [node, script]
    assert argv[2:] == ["install", "-g", ocr_update.OCR_NPM_PACKAGE]


def test_npm_install_argv_windows_cmd_fallback(monkeypatch, tmp_path) -> None:
    shim = tmp_path / "npm-root" / "npm.CMD"
    shim.parent.mkdir(parents=True)
    shim.write_text("rem not a recognizable npm shim\r\n")
    monkeypatch.setattr(
        ocr_update.shutil, "which", lambda name: str(shim) if name == "npm" else None
    )
    monkeypatch.setattr(ocr_update, "_IS_WINDOWS", True)

    assert npm_install_argv() == [
        "cmd",
        "/c",
        str(shim),
        "install",
        "-g",
        ocr_update.OCR_NPM_PACKAGE,
    ]


def test_npm_install_argv_missing_npm(monkeypatch) -> None:
    monkeypatch.setattr(ocr_update.shutil, "which", lambda name: None)
    with pytest.raises(OCRUpdateError, match="npm was not found"):
        npm_install_argv()
