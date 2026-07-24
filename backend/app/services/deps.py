"""Shared service singletons (settings, git, OCR adapter, secret store).

Services are constructed per DB session but share these process-wide
collaborators so binary detection and credential stores are reused.
"""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.core.secrets import SecretStore, get_secret_store
from app.git.service import GitService
from app.ocr.adapter import OCRAdapter

_git: GitService | None = None
_adapter: OCRAdapter | None = None


def get_git_service() -> GitService:
    global _git
    if _git is None:
        _git = GitService(get_settings())
    return _git


def get_ocr_adapter() -> OCRAdapter:
    global _adapter
    if _adapter is None:
        _adapter = OCRAdapter(get_settings())
    return _adapter


def reset_service_singletons() -> None:
    """Tests call this when replacing settings (new data dir / binaries)."""

    global _git, _adapter
    _git = None
    _adapter = None


class ServiceBase:
    """Common collaborators for session-scoped services."""

    def __init__(
        self,
        session,
        *,
        settings: Settings | None = None,
        git: GitService | None = None,
        adapter: OCRAdapter | None = None,
        secrets: SecretStore | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.git = git or get_git_service()
        self.adapter = adapter or get_ocr_adapter()
        self.secrets = secrets or get_secret_store()
