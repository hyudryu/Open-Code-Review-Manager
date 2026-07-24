"""OCR compatibility layer (all ocr access goes through OCRAdapter)."""

from app.ocr.adapter import OCRAdapter, ResultParseError, UnsupportedFeatureError
from app.ocr.models import (
    LLMTestResult,
    NormalizedFinding,
    NormalizedWarning,
    OCRCapabilities,
    OCRStatus,
    ParsedResult,
    PreviewFile,
    PreviewResult,
    ProviderResolution,
    ResultSummary,
    ReviewJobContext,
    SessionEvent,
)

__all__ = [
    "LLMTestResult",
    "NormalizedFinding",
    "NormalizedWarning",
    "OCRCapabilities",
    "OCRAdapter",
    "OCRStatus",
    "ParsedResult",
    "PreviewFile",
    "PreviewResult",
    "ProviderResolution",
    "ResultParseError",
    "ResultSummary",
    "ReviewJobContext",
    "SessionEvent",
    "UnsupportedFeatureError",
]
