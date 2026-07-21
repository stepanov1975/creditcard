"""Issuer-neutral lexical policy for supported date tokens and year suffixes."""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum


class DateTokenStyle(StrEnum):
    """Supported relative ordering and separator for abbreviated date tokens."""

    DAY_FIRST_SLASH = "day_first_slash"
    DAY_FIRST_DOT = "day_first_dot"
    DAY_FIRST_DASH = "day_first_dash"
    YEAR_FIRST_SLASH = "year_first_slash"
    YEAR_FIRST_DOT = "year_first_dot"
    YEAR_FIRST_DASH = "year_first_dash"


MIN_CONTEXT_YEAR = 1900
MAX_CONTEXT_YEAR = 2100

_DATE_STYLE_CONFIGURATION: Mapping[DateTokenStyle, tuple[str, bool]] = {
    DateTokenStyle.DAY_FIRST_SLASH: ("/", False),
    DateTokenStyle.DAY_FIRST_DOT: (".", False),
    DateTokenStyle.DAY_FIRST_DASH: ("-", False),
    DateTokenStyle.YEAR_FIRST_SLASH: ("/", True),
    DateTokenStyle.YEAR_FIRST_DOT: (".", True),
    DateTokenStyle.YEAR_FIRST_DASH: ("-", True),
}


def _styled_date_pattern(
    separator: str,
    *,
    year_first: bool,
    year_digits: int,
) -> re.Pattern[str]:
    escaped = re.escape(separator)
    day = r"(?P<day>\d{1,2})"
    month = r"(?P<month>\d{1,2})"
    year = rf"(?P<year>\d{{{year_digits}}})"
    components = (year, month, day) if year_first else (day, month, year)
    return re.compile(
        rf"(?<!\d){components[0]}\s*{escaped}\s*{components[1]}"
        rf"\s*{escaped}\s*{components[2]}(?!\d)"
    )


FULL_DATE_TOKEN_PATTERNS: Mapping[DateTokenStyle, re.Pattern[str]] = {
    style: _styled_date_pattern(separator, year_first=year_first, year_digits=4)
    for style, (separator, year_first) in _DATE_STYLE_CONFIGURATION.items()
}
SHORT_DATE_TOKEN_PATTERNS: Mapping[DateTokenStyle, re.Pattern[str]] = {
    style: _styled_date_pattern(separator, year_first=year_first, year_digits=2)
    for style, (separator, year_first) in _DATE_STYLE_CONFIGURATION.items()
}


def validate_suffix_year_mapping(
    year: int | None,
    mapping: tuple[tuple[int, int], ...],
) -> tuple[tuple[int, int], ...]:
    """Return the effective suffix-year mapping after validating its invariants."""

    effective_mapping = mapping
    if not effective_mapping and year is not None:
        effective_mapping = ((year % 100, year),)
    if not effective_mapping:
        raise ValueError("at least one proven suffix-year mapping is required")
    if tuple(sorted(effective_mapping)) != effective_mapping:
        raise ValueError("date suffix-year mappings must be sorted")
    suffixes = tuple(suffix for suffix, _ in effective_mapping)
    mapped_years = tuple(mapped_year for _, mapped_year in effective_mapping)
    if len(set(suffixes)) != len(suffixes):
        raise ValueError("date suffix-year mappings must have unique suffixes")
    if any(not 0 <= suffix <= 99 for suffix in suffixes):
        raise ValueError("date suffix must be between 0 and 99")
    if any(not MIN_CONTEXT_YEAR <= mapped_year <= MAX_CONTEXT_YEAR for mapped_year in mapped_years):
        raise ValueError(f"mapped year must be between {MIN_CONTEXT_YEAR} and {MAX_CONTEXT_YEAR}")
    if any(mapped_year % 100 != suffix for suffix, mapped_year in effective_mapping):
        raise ValueError("mapped year must match its two-digit suffix")
    if year is not None and effective_mapping != ((year % 100, year),):
        raise ValueError("single year must agree with its suffix mapping")
    return effective_mapping


__all__ = [
    "FULL_DATE_TOKEN_PATTERNS",
    "MAX_CONTEXT_YEAR",
    "MIN_CONTEXT_YEAR",
    "SHORT_DATE_TOKEN_PATTERNS",
    "DateTokenStyle",
    "validate_suffix_year_mapping",
]
