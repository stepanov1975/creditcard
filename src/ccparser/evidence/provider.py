"""OCR provider contract used by PDF evidence extraction."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ccparser.evidence.models import BBox, Word


class OcrProvider(Protocol):
    """Read an immutable PDF snapshot into display-space words for one zero-based page."""

    def extract_words(
        self,
        pdf_bytes: bytes,
        source_sha256: str,
        page_index: int,
        clip: BBox | None = None,
    ) -> tuple[Word, ...]: ...


@runtime_checkable
class CurrencySymbolOcrProvider(Protocol):
    """Optional targeted OCR for one suspicious custom-font symbol clip."""

    def extract_currency_symbol(
        self,
        pdf_bytes: bytes,
        source_sha256: str,
        page_index: int,
        clip: BBox,
    ) -> Word | None: ...
