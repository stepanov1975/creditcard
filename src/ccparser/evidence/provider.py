"""OCR provider contract used by PDF evidence extraction."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ccparser.evidence.models import BBox, Word


class OcrProvider(Protocol):
    """Return OCR words in PDF point coordinates for one zero-based page."""

    def extract_words(
        self,
        path: Path,
        source_sha256: str,
        page_index: int,
        clip: BBox | None = None,
    ) -> tuple[Word, ...]: ...
