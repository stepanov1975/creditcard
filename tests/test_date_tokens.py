from __future__ import annotations

import pytest

from ccparser.date_tokens import (
    FULL_DATE_TOKEN_PATTERNS,
    SHORT_DATE_TOKEN_PATTERNS,
    DateTokenStyle,
    validate_suffix_year_mapping,
)


@pytest.mark.parametrize(
    ("style", "full", "short"),
    (
        (DateTokenStyle.DAY_FIRST_SLASH, "31 / 12 / 2026", "31 / 12 / 26"),
        (DateTokenStyle.DAY_FIRST_DOT, "31 . 12 . 2026", "31 . 12 . 26"),
        (DateTokenStyle.DAY_FIRST_DASH, "31 - 12 - 2026", "31 - 12 - 26"),
        (DateTokenStyle.YEAR_FIRST_SLASH, "2026 / 12 / 31", "26 / 12 / 31"),
        (DateTokenStyle.YEAR_FIRST_DOT, "2026 . 12 . 31", "26 . 12 . 31"),
        (DateTokenStyle.YEAR_FIRST_DASH, "2026 - 12 - 31", "26 - 12 - 31"),
    ),
)
def test_date_patterns_cover_every_supported_style(
    style: DateTokenStyle,
    full: str,
    short: str,
) -> None:
    assert FULL_DATE_TOKEN_PATTERNS[style].fullmatch(full)
    assert SHORT_DATE_TOKEN_PATTERNS[style].fullmatch(short)


def test_suffix_year_mapping_validation_is_shared_and_canonical() -> None:
    assert validate_suffix_year_mapping(2026, ()) == ((26, 2026),)
    assert validate_suffix_year_mapping(None, ((25, 2025), (26, 2026))) == (
        (25, 2025),
        (26, 2026),
    )
    with pytest.raises(ValueError, match="sorted"):
        validate_suffix_year_mapping(None, ((26, 2026), (25, 2025)))
    with pytest.raises(ValueError, match="unique"):
        validate_suffix_year_mapping(None, ((26, 2026), (26, 2026)))


@pytest.mark.parametrize(
    ("year", "mapping", "expected_message"),
    (
        (None, (), "at least one proven suffix-year mapping is required"),
        (2026, ((25, 2025),), "single year must agree with its suffix mapping"),
    ),
    ids=("empty", "single_year_disagreement"),
)
def test_suffix_year_mapping_rejects_missing_or_disagreeing_evidence(
    year: int | None,
    mapping: tuple[tuple[int, int], ...],
    expected_message: str,
) -> None:
    with pytest.raises(ValueError, match=expected_message):
        validate_suffix_year_mapping(year, mapping)
