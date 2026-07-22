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


class SuffixYearMappingViolation(StrEnum):
    EMPTY = "empty"
    UNSORTED = "unsorted"
    DUPLICATE_SUFFIX = "duplicate_suffix"
    INVALID_SUFFIX = "invalid_suffix"
    INVALID_YEAR = "invalid_year"
    SUFFIX_YEAR_MISMATCH = "suffix_year_mismatch"
    SINGLE_YEAR_DISAGREEMENT = "single_year_disagreement"


_SUFFIX_YEAR_MAPPING_VIOLATION_MESSAGES: Mapping[SuffixYearMappingViolation, str] = {
    SuffixYearMappingViolation.EMPTY: "at least one proven suffix-year mapping is required",
    SuffixYearMappingViolation.UNSORTED: "date suffix-year mappings must be sorted",
    SuffixYearMappingViolation.DUPLICATE_SUFFIX: (
        "date suffix-year mappings must have unique suffixes"
    ),
    SuffixYearMappingViolation.INVALID_SUFFIX: "date suffix must be between 0 and 99",
    SuffixYearMappingViolation.INVALID_YEAR: (
        f"mapped year must be between {MIN_CONTEXT_YEAR} and {MAX_CONTEXT_YEAR}"
    ),
    SuffixYearMappingViolation.SUFFIX_YEAR_MISMATCH: (
        "mapped year must match its two-digit suffix"
    ),
    SuffixYearMappingViolation.SINGLE_YEAR_DISAGREEMENT: (
        "single year must agree with its suffix mapping"
    ),
}
_DEFAULT_SUFFIX_YEAR_MAPPING_VIOLATION_PRIORITY = (
    SuffixYearMappingViolation.EMPTY,
    SuffixYearMappingViolation.UNSORTED,
    SuffixYearMappingViolation.DUPLICATE_SUFFIX,
    SuffixYearMappingViolation.INVALID_SUFFIX,
    SuffixYearMappingViolation.INVALID_YEAR,
    SuffixYearMappingViolation.SUFFIX_YEAR_MISMATCH,
    SuffixYearMappingViolation.SINGLE_YEAR_DISAGREEMENT,
)


class SuffixYearMappingValidationError(ValueError):
    def __init__(self, violations: frozenset[SuffixYearMappingViolation]) -> None:
        self.violations = violations
        _, message = self.resolve(_DEFAULT_SUFFIX_YEAR_MAPPING_VIOLATION_PRIORITY)
        super().__init__(message)

    def resolve(
        self,
        priority: tuple[SuffixYearMappingViolation, ...],
    ) -> tuple[SuffixYearMappingViolation, str]:
        for violation in priority:
            if violation in self.violations:
                return violation, _SUFFIX_YEAR_MAPPING_VIOLATION_MESSAGES[violation]
        raise RuntimeError("suffix-year mapping priority does not cover every violation")


def _suffix_year_mapping_violations(
    year: int | None,
    mapping: tuple[tuple[int, int], ...],
) -> frozenset[SuffixYearMappingViolation]:
    if not mapping:
        return frozenset({SuffixYearMappingViolation.EMPTY})

    violations: set[SuffixYearMappingViolation] = set()
    suffixes = tuple(suffix for suffix, _ in mapping)
    mapped_years = tuple(mapped_year for _, mapped_year in mapping)
    if tuple(sorted(mapping)) != mapping:
        violations.add(SuffixYearMappingViolation.UNSORTED)
    if len(set(suffixes)) != len(suffixes):
        violations.add(SuffixYearMappingViolation.DUPLICATE_SUFFIX)
    if any(not 0 <= suffix <= 99 for suffix in suffixes):
        violations.add(SuffixYearMappingViolation.INVALID_SUFFIX)
    if any(not MIN_CONTEXT_YEAR <= mapped_year <= MAX_CONTEXT_YEAR for mapped_year in mapped_years):
        violations.add(SuffixYearMappingViolation.INVALID_YEAR)
    if any(mapped_year % 100 != suffix for suffix, mapped_year in mapping):
        violations.add(SuffixYearMappingViolation.SUFFIX_YEAR_MISMATCH)
    if year is not None and mapping != ((year % 100, year),):
        violations.add(SuffixYearMappingViolation.SINGLE_YEAR_DISAGREEMENT)
    return frozenset(violations)


def validate_suffix_year_mapping(
    year: int | None,
    mapping: tuple[tuple[int, int], ...],
) -> tuple[tuple[int, int], ...]:
    """Return the effective suffix-year mapping after validating its invariants."""

    effective_mapping = mapping
    if not effective_mapping and year is not None:
        effective_mapping = ((year % 100, year),)
    violations = _suffix_year_mapping_violations(year, effective_mapping)
    if violations:
        raise SuffixYearMappingValidationError(violations)
    return effective_mapping


__all__ = [
    "FULL_DATE_TOKEN_PATTERNS",
    "MAX_CONTEXT_YEAR",
    "MIN_CONTEXT_YEAR",
    "SHORT_DATE_TOKEN_PATTERNS",
    "DateTokenStyle",
    "SuffixYearMappingValidationError",
    "SuffixYearMappingViolation",
    "validate_suffix_year_mapping",
]
