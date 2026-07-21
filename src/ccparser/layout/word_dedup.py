"""Shared policy-driven deduplication for positioned words."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from ccparser.evidence.models import Word
from ccparser.geometry import intersection_over_smaller, intersection_over_union

_MIN_INTERSECTION_OVER_UNION = 0.7
_MIN_INTERSECTION_OVER_SMALLER = 0.9


def deduplicate_words(
    words: Iterable[Word],
    *,
    text_key: Callable[[str], str],
) -> tuple[Word, ...]:
    """Select deterministic word survivors under the supplied text policy."""

    ordered = sorted(
        ((word, text_key(word.text)) for word in words),
        key=lambda candidate: (
            -candidate[0].confidence,
            candidate[0].source != "digital",
            candidate[0].bbox,
            candidate[1],
        ),
    )
    selected: list[tuple[Word, str]] = []
    for word, canonical_text in ordered:
        if any(
            existing_text == canonical_text
            and (
                intersection_over_union(existing.bbox, word.bbox) >= _MIN_INTERSECTION_OVER_UNION
                or intersection_over_smaller(existing.bbox, word.bbox)
                >= _MIN_INTERSECTION_OVER_SMALLER
            )
            for existing, existing_text in selected
        ):
            continue
        selected.append((word, canonical_text))
    return tuple(word for word, _ in selected)
