"""Shared Unicode normalization and phrase-token matching."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from functools import lru_cache

ACRONYM_QUOTES = frozenset({'"', "'", "\u2018", "\u2019", "\u201c", "\u201d", "\u05f3", "\u05f4"})
HEBREW_CLITIC_PREFIXES = frozenset("ובכלמהש")
IGNORABLE_FORMAT_CONTROLS = frozenset(
    {
        "\u00ad",  # Soft hyphen
        "\u061c",  # Arabic letter mark
        "\u200e",  # Left-to-right mark
        "\u200f",  # Right-to-left mark
        "\u202a",  # Left-to-right embedding
        "\u202b",  # Right-to-left embedding
        "\u202c",  # Pop directional formatting
        "\u202d",  # Left-to-right override
        "\u202e",  # Right-to-left override
        "\u2060",  # Word joiner
        "\u2066",  # Left-to-right isolate
        "\u2067",  # Right-to-left isolate
        "\u2068",  # First-strong isolate
        "\u2069",  # Pop directional isolate
        "\ufeff",  # Byte-order mark / zero-width no-break space
    }
)
TOKEN_JOIN_CONTROLS = frozenset({"\u200c", "\u200d"})

type TokenSequence = tuple[str, ...]
type CompiledTokenPhrases = tuple[TokenSequence, ...]

_PHRASE_TOKEN_CACHE_SIZE = 8_192


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text)
    normalized_controls = "".join(
        "" if char in IGNORABLE_FORMAT_CONTROLS else " " if char == "\u200b" else char
        for char in normalized
    )
    return " ".join(normalized_controls.split())


@lru_cache(maxsize=_PHRASE_TOKEN_CACHE_SIZE)
def _cached_phrase_tokens(
    text: str,
    ignore_acronym_quotes: bool,
) -> TokenSequence:
    normalized = normalize_text(text).casefold()
    canonical: list[str] = []
    for index, char in enumerate(normalized):
        if char in TOKEN_JOIN_CONTROLS:
            continue
        between_letters = (
            0 < index < len(normalized) - 1
            and normalized[index - 1].isalpha()
            and normalized[index + 1].isalpha()
        )
        if ignore_acronym_quotes and char in ACRONYM_QUOTES and between_letters:
            continue
        canonical.append(char if char.isalnum() else " ")
    return tuple("".join(canonical).split())


def phrase_tokens(
    text: str,
    *,
    ignore_acronym_quotes: bool = False,
) -> TokenSequence:
    return _cached_phrase_tokens(text, ignore_acronym_quotes)


def compile_token_phrases(
    phrases: Iterable[str],
    *,
    ignore_acronym_quotes: bool = False,
) -> CompiledTokenPhrases:
    compiled: list[TokenSequence] = []
    for phrase in phrases:
        candidate = phrase_tokens(
            phrase,
            ignore_acronym_quotes=ignore_acronym_quotes,
        )
        if candidate:
            compiled.append(candidate)
    return tuple(compiled)


def contains_token_sequence(
    text: str,
    phrases: Iterable[str],
    *,
    ignore_acronym_quotes: bool = False,
    allow_hebrew_clitic_prefix: bool = False,
) -> bool:
    tokens = phrase_tokens(text, ignore_acronym_quotes=ignore_acronym_quotes)
    for phrase in phrases:
        candidate = phrase_tokens(
            phrase,
            ignore_acronym_quotes=ignore_acronym_quotes,
        )
        if candidate and contains_compiled_token_sequence(
            tokens,
            (candidate,),
            allow_hebrew_clitic_prefix=allow_hebrew_clitic_prefix,
        ):
            return True
    return False


def _token_window_matches(
    window: TokenSequence,
    candidate: TokenSequence,
    *,
    allow_hebrew_clitic_prefix: bool,
) -> bool:
    return (
        len(window) == len(candidate)
        and _first_token_matches(
            window[0],
            candidate[0],
            allow_hebrew_clitic_prefix=allow_hebrew_clitic_prefix,
        )
        and window[1:] == candidate[1:]
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


def contains_compiled_token_sequence(
    tokens: TokenSequence,
    phrases: CompiledTokenPhrases,
    *,
    allow_hebrew_clitic_prefix: bool = False,
) -> bool:
    return any(
        _token_window_matches(
            tokens[index : index + len(candidate)],
            candidate,
            allow_hebrew_clitic_prefix=allow_hebrew_clitic_prefix,
        )
        for candidate in phrases
        if candidate
        for index in range(len(tokens) - len(candidate) + 1)
    )


__all__ = [
    "CompiledTokenPhrases",
    "TokenSequence",
    "compile_token_phrases",
    "contains_compiled_token_sequence",
    "contains_token_sequence",
    "normalize_text",
    "phrase_tokens",
]
