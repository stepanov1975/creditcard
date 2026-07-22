"""Shared Unicode normalization and phrase-token matching."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable

ACRONYM_QUOTES = frozenset({'"', "'", "\u2018", "\u2019", "\u201c", "\u201d", "\u05f3", "\u05f4"})
HEBREW_CLITIC_PREFIXES = frozenset("ובכלמהש")


def normalize_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def phrase_tokens(
    text: str,
    *,
    ignore_acronym_quotes: bool = False,
) -> tuple[str, ...]:
    normalized = normalize_text(text).casefold()
    canonical: list[str] = []
    for index, char in enumerate(normalized):
        between_letters = (
            0 < index < len(normalized) - 1
            and normalized[index - 1].isalpha()
            and normalized[index + 1].isalpha()
        )
        if ignore_acronym_quotes and char in ACRONYM_QUOTES and between_letters:
            continue
        canonical.append(char if char.isalnum() else " ")
    return tuple("".join(canonical).split())


def contains_token_sequence(
    text: str,
    phrases: Iterable[str],
    *,
    ignore_acronym_quotes: bool = False,
    allow_hebrew_clitic_prefix: bool = False,
) -> bool:
    tokens = phrase_tokens(text, ignore_acronym_quotes=ignore_acronym_quotes)
    for phrase in phrases:
        candidate = phrase_tokens(phrase, ignore_acronym_quotes=ignore_acronym_quotes)
        if candidate and any(
            _token_sequence_matches(
                tokens[index : index + len(candidate)],
                candidate,
                allow_hebrew_clitic_prefix=allow_hebrew_clitic_prefix,
            )
            for index in range(len(tokens) - len(candidate) + 1)
        ):
            return True
    return False


def _token_sequence_matches(
    source: tuple[str, ...],
    candidate: tuple[str, ...],
    *,
    allow_hebrew_clitic_prefix: bool,
) -> bool:
    return (
        len(source) == len(candidate)
        and _first_token_matches(
            source[0],
            candidate[0],
            allow_hebrew_clitic_prefix=allow_hebrew_clitic_prefix,
        )
        and source[1:] == candidate[1:]
    )


def _first_token_matches(
    source: str,
    candidate: str,
    *,
    allow_hebrew_clitic_prefix: bool,
) -> bool:
    if source == candidate:
        return True
    return (
        allow_hebrew_clitic_prefix
        and len(source) > len(candidate)
        and source[0] in HEBREW_CLITIC_PREFIXES
        and source[1:] == candidate
        and any("\u0590" <= char <= "\u05ff" for char in candidate)
    )


__all__ = ["contains_token_sequence", "normalize_text", "phrase_tokens"]
