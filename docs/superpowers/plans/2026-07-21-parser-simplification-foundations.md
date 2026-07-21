# Parser Simplification Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centralize exact financial arithmetic, lexical/date rules, geometry, filesystem traversal, summary projection, and safe mechanical cleanup without changing established parser outputs.

**Architecture:** Add small dependency-neutral primitive modules, characterize every current boundary before migration, and move call sites one subsystem at a time. Domain-specific extraction rules remain in their current modules; the new modules own only reusable mechanics and validation.

**Tech Stack:** Python 3.13, Pydantic 2, PyMuPDF, Typer, pytest 9, Ruff, mypy strict.

## Global Constraints

- Use Python 3.13 and the repository `.venv`.
- Develop every production behavior test-first and run the repository verification gates before each task is considered complete.
- Keep all financial arithmetic in `Decimal` and make it independent of the active Decimal context.
- Do not add document-, issuer-, filename-, path-, hash-, merchant-, date-, amount-, or total-specific production branches.
- Preserve public model fields, JSON keys, CSV columns and ordering, diagnostic strings, transaction ordering, source evidence, and deterministic output.
- Keep private documents and derived financial data local and outside Git.
- Keep the public `strict` parsing parameter as a compatibility surface; the CLI continues to own strict exit-code behavior.
- Preserve OCR cache keys, command tuples, cache versions, and targeted-recognition pass boundaries.

---

### Task 1: Context-Independent Decimal Core

**Files:**
- Create: `src/ccparser/decimal_math.py`
- Create: `tests/test_decimal_math.py`
- Modify: `src/ccparser/models.py:18-50,155-174`
- Modify: `src/ccparser/reconcile.py:18-61`
- Modify: `src/ccparser/fx.py:357-368`
- Modify: `src/ccparser/discovery.py:1898-1933`
- Modify: `src/ccparser/output.py:110-123`
- Test: `tests/test_models.py`
- Test: `tests/test_fx.py`
- Test: `tests/test_discovery.py`
- Test: `tests/test_output.py`
- Test: `tests/test_reconcile.py`

**Interfaces:**
- Produces: `finite_decimal(value: Decimal) -> Decimal`
- Produces: `exact_sum(values: Iterable[Decimal]) -> Decimal`
- Produces: `exact_difference(minuend: Decimal, subtrahend: Decimal) -> Decimal`
- Produces: `is_exact_multiple(value: Decimal, unit: Decimal) -> bool`
- Produces: `plain_decimal_string(value: Decimal) -> str`

- [ ] **Step 1: Add focused unit tests for the new exact arithmetic contract**

```python
# tests/test_decimal_math.py
from __future__ import annotations

from decimal import Decimal, localcontext

import pytest

from ccparser.decimal_math import (
    exact_difference,
    exact_sum,
    finite_decimal,
    is_exact_multiple,
    plain_decimal_string,
)


def test_exact_arithmetic_ignores_active_decimal_context() -> None:
    large = Decimal("123456789012345678901234567890.12")
    with localcontext() as context:
        context.prec = 5
        assert exact_sum((large, Decimal("0.01"))) == Decimal(
            "123456789012345678901234567890.13"
        )
        assert exact_difference(large, Decimal("0.01")) == Decimal(
            "123456789012345678901234567890.11"
        )


def test_decimal_helpers_validate_and_format_without_rounding() -> None:
    assert finite_decimal(Decimal("-0")) == Decimal("-0")
    assert plain_decimal_string(Decimal("100.1200")) == "100.12"
    assert plain_decimal_string(Decimal("-0.00")) == "0"
    assert is_exact_multiple(Decimal("100.125"), Decimal("0.001"))
    assert not is_exact_multiple(Decimal("100.125"), Decimal("0.01"))
    with pytest.raises(ValueError, match="finite"):
        finite_decimal(Decimal("NaN"))
    with pytest.raises(ValueError, match="positive"):
        is_exact_multiple(Decimal("1"), Decimal("0"))
```

- [ ] **Step 2: Run the new unit tests and verify the import fails**

Run: `.venv/bin/pytest -q tests/test_decimal_math.py`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'ccparser.decimal_math'`.

- [ ] **Step 3: Implement the dependency-neutral exact Decimal module**

```python
# src/ccparser/decimal_math.py
"""Context-independent exact arithmetic and formatting for financial Decimals."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal


def finite_decimal(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("financial values must be finite")
    return value


def _integer_coefficient(value: Decimal) -> tuple[int, int]:
    finite_decimal(value)
    parts = value.as_tuple()
    if not isinstance(parts.exponent, int):
        raise ValueError("financial values must have a finite exponent")
    coefficient = 0
    for digit in parts.digits:
        coefficient = coefficient * 10 + digit
    return (-coefficient if parts.sign else coefficient), parts.exponent


def _from_coefficient(coefficient: int, exponent: int) -> Decimal:
    digits = tuple(int(character) for character in str(abs(coefficient)))
    return Decimal((int(coefficient < 0), digits, exponent))


def exact_sum(values: Iterable[Decimal]) -> Decimal:
    parts = tuple(_integer_coefficient(value) for value in values)
    if not parts:
        return Decimal("0")
    common_exponent = min(exponent for _, exponent in parts)
    coefficient = sum(
        value * 10 ** (exponent - common_exponent) for value, exponent in parts
    )
    return _from_coefficient(coefficient, common_exponent)


def exact_difference(minuend: Decimal, subtrahend: Decimal) -> Decimal:
    return exact_sum((minuend, subtrahend.copy_negate()))


def is_exact_multiple(value: Decimal, unit: Decimal) -> bool:
    if unit <= 0:
        raise ValueError("minor unit must be positive")
    value_coefficient, value_exponent = _integer_coefficient(value)
    unit_coefficient, unit_exponent = _integer_coefficient(unit)
    common_exponent = min(value_exponent, unit_exponent)
    scaled_value = value_coefficient * 10 ** (value_exponent - common_exponent)
    scaled_unit = unit_coefficient * 10 ** (unit_exponent - common_exponent)
    return scaled_value % scaled_unit == 0


def plain_decimal_string(value: Decimal) -> str:
    finite_decimal(value)
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


__all__ = [
    "exact_difference",
    "exact_sum",
    "finite_decimal",
    "is_exact_multiple",
    "plain_decimal_string",
]
```

- [ ] **Step 4: Run the exact arithmetic unit tests and verify they pass**

Run: `.venv/bin/pytest -q tests/test_decimal_math.py`

Expected: `2 passed`.

- [ ] **Step 5: Add low-precision regression tests at every financial call site**

Add this model regression beside the existing FX derivation test:

```python
def test_foreign_exchange_derivation_is_exact_under_low_decimal_precision() -> None:
    from decimal import localcontext

    from ccparser.models import ExtractedMoney, ForeignExchangeDetails

    fee_evidence = _fx_evidence("fee", 20.0)
    discount_evidence = _fx_evidence("discount", 30.0)
    gross = ExtractedMoney(
        amount=Decimal("123456789012345678901234567890.12"),
        currency="ILS",
        evidence=(fee_evidence,),
    )
    discount = ExtractedMoney(
        amount=Decimal("0.01"),
        currency="ILS",
        evidence=(discount_evidence,),
    )
    exact_net = ExtractedMoney(
        amount=Decimal("123456789012345678901234567890.11"),
        currency="ILS",
        evidence=(fee_evidence, discount_evidence),
        derivation="gross_fee_minus_discount",
    )
    with localcontext() as context:
        context.prec = 5
        details = ForeignExchangeDetails(
            gross_fee=gross,
            fee_discount=discount,
            net_fee=exact_net,
        )
    assert details.net_fee == exact_net
```

Add corresponding low-precision cases to `tests/test_fx.py` using the existing
`_continuation_rows` helper, to `tests/test_discovery.py` using a singleton amount
that completes a large printed total exactly, and to `tests/test_output.py` asserting
large and signed-zero values retain their existing plain representation.

- [ ] **Step 6: Run the regressions and confirm current context-sensitive behavior fails**

Run: `.venv/bin/pytest -q tests/test_models.py tests/test_fx.py tests/test_discovery.py tests/test_output.py tests/test_reconcile.py`

Expected: FAIL in the new low-precision model, FX, and discovery cases; existing tests remain green.

- [ ] **Step 7: Migrate all financial call sites to the shared module**

Apply these exact migrations:

- `models.py`: use `finite_decimal` in `FiniteDecimal` and `plain_decimal_string` in serializers; validate derived net fees with `exact_difference`.
- `reconcile.py`: delete its four private arithmetic helpers; import `exact_sum`, `exact_difference`, and `is_exact_multiple`.
- `fx.py`: derive `net_fee.amount` with `exact_difference`.
- `discovery.py`: calculate singleton totals with `exact_sum` and missing amounts with `exact_difference`.
- `output.py`: delete `_decimal_string`; use a nullable wrapper that returns `""` for `None` and `plain_decimal_string(value)` otherwise.

- [ ] **Step 8: Run focused and full verification**

Run: `.venv/bin/pytest -q tests/test_decimal_math.py tests/test_models.py tests/test_fx.py tests/test_discovery.py tests/test_output.py tests/test_reconcile.py`

Expected: all focused tests pass.

Run: `.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy src && .venv/bin/pytest -q`

Expected: all four commands exit 0 and all tests pass.

- [ ] **Step 9: Commit the exact arithmetic foundation**

```bash
git add src/ccparser/decimal_math.py src/ccparser/models.py src/ccparser/reconcile.py src/ccparser/fx.py src/ccparser/discovery.py src/ccparser/output.py tests/test_decimal_math.py tests/test_models.py tests/test_fx.py tests/test_discovery.py tests/test_output.py tests/test_reconcile.py
git commit -m "refactor: centralize exact decimal arithmetic"
```

### Task 2: Shared Text Tokens and Boundary-Safe FX Cues

**Files:**
- Create: `src/ccparser/text_tokens.py`
- Create: `tests/test_text_tokens.py`
- Modify: `src/ccparser/money.py:72-98`
- Modify: `src/ccparser/normalize.py:181-197`
- Modify: `src/ccparser/fx.py:73-103`
- Modify: `src/ccparser/discovery.py:315-393`
- Modify: `src/ccparser/layout/columns.py:357-370`
- Modify: `src/ccparser/layout/regions.py:132-160`
- Test: `tests/test_fx.py`
- Test: `tests/test_normalize.py`
- Test: `tests/test_discovery.py`
- Test: `tests/layout/test_columns.py`
- Test: `tests/layout/test_regions.py`

**Interfaces:**
- Produces: `normalize_text(text: str) -> str`
- Produces: `phrase_tokens(text: str, *, ignore_acronym_quotes: bool = False) -> tuple[str, ...]`
- Produces: `contains_token_sequence(text: str, phrases: Iterable[str], *, ignore_acronym_quotes: bool = False) -> bool`

- [ ] **Step 1: Add unit tests for normalization modes and token boundaries**

```python
# tests/test_text_tokens.py
from ccparser.text_tokens import contains_token_sequence, normalize_text, phrase_tokens


def test_text_tokenization_is_nfc_casefolded_and_boundary_aware() -> None:
    assert normalize_text("  Cafe\u0301   SHOP ") == "Café SHOP"
    assert phrase_tokens("Foreign-currency FEE") == ("foreign", "currency", "fee")
    assert contains_token_sequence("foreign currency fee", ("currency fee",))
    assert not contains_token_sequence("Coffee amount", ("fee",))
    assert not contains_token_sequence("Corporate date", ("rate",))


def test_acronym_quote_policy_is_explicit() -> None:
    assert phrase_tokens('סה"כ', ignore_acronym_quotes=True) == ("סהכ",)
    assert phrase_tokens('סה"כ') == ("סה", "כ")
```

- [ ] **Step 2: Run the unit tests and verify the new module import fails**

Run: `.venv/bin/pytest -q tests/test_text_tokens.py`

Expected: FAIL during collection with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the shared token module**

```python
# src/ccparser/text_tokens.py
"""Shared Unicode normalization and phrase-token matching."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable

ACRONYM_QUOTES = frozenset({'"', "'", "\u2018", "\u2019", "\u201c", "\u201d", "\u05f3", "\u05f4"})


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
) -> bool:
    tokens = phrase_tokens(text, ignore_acronym_quotes=ignore_acronym_quotes)
    for phrase in phrases:
        candidate = phrase_tokens(phrase, ignore_acronym_quotes=ignore_acronym_quotes)
        if candidate and any(
            tokens[index : index + len(candidate)] == candidate
            for index in range(len(tokens) - len(candidate) + 1)
        ):
            return True
    return False


__all__ = ["contains_token_sequence", "normalize_text", "phrase_tokens"]
```

- [ ] **Step 4: Add FX regressions for substring false positives**

Add two tests to `tests/test_fx.py`. Construct `_region(row, fee_header="Coffee amount")`
for the first and replace the conversion-date header source cell with `Corporate date`
for the second. Assert the extraction contains no fee/rate value and no unparsed
fee/rate diagnostic solely because those substrings occur.

- [ ] **Step 5: Run the FX regressions and verify they fail against substring matching**

Run: `.venv/bin/pytest -q tests/test_fx.py -k 'coffee or corporate'`

Expected: both new tests fail because `_contains_cue` currently uses substring containment.

- [ ] **Step 6: Migrate consumers without changing specialized policies**

- `money.py` and `normalize.py`: replace identical `_normalized_text`, `_normalized_phrase`, and `_contains_marker` bodies with shared functions.
- `fx.py`: remove `_normalized_phrase` and implement `_contains_cue` with `contains_token_sequence`.
- `layout/columns.py`: replace `_normalized_header` and `_contains_token_phrase` mechanics with `phrase_tokens` while preserving exact/header-specific scoring.
- `discovery.py` and `layout/regions.py`: use `ignore_acronym_quotes=True` for compact Hebrew marker behavior.
- Keep `_remove_markers` in `money.py`, because source-text removal is distinct from token recognition.

- [ ] **Step 7: Run focused and full verification**

Run: `.venv/bin/pytest -q tests/test_text_tokens.py tests/test_fx.py tests/test_normalize.py tests/test_discovery.py tests/layout/test_columns.py tests/layout/test_regions.py`

Expected: all focused tests pass with existing diagnostic strings unchanged.

Run: `.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy src && .venv/bin/pytest -q`

Expected: all commands exit 0.

- [ ] **Step 8: Commit the shared text-token policy**

```bash
git add src/ccparser/text_tokens.py src/ccparser/money.py src/ccparser/normalize.py src/ccparser/fx.py src/ccparser/discovery.py src/ccparser/layout/columns.py src/ccparser/layout/regions.py tests/test_text_tokens.py tests/test_fx.py tests/test_normalize.py tests/test_discovery.py tests/layout/test_columns.py tests/layout/test_regions.py
git commit -m "refactor: share boundary-aware phrase matching"
```

### Task 3: Neutral Date-Token Policy

**Files:**
- Create: `src/ccparser/date_tokens.py`
- Create: `tests/test_date_tokens.py`
- Modify: `src/ccparser/discovery.py:48-57,80-113,315-359`
- Modify: `src/ccparser/normalize.py:17-22,108-158`
- Modify: `src/ccparser/models.py:277-309`
- Test: `tests/test_discovery.py`
- Test: `tests/test_normalize.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `DateTokenStyle`
- Produces: `FULL_DATE_TOKEN_PATTERNS: Mapping[DateTokenStyle, Pattern[str]]`
- Produces: `SHORT_DATE_TOKEN_PATTERNS: Mapping[DateTokenStyle, Pattern[str]]`
- Produces: `MIN_CONTEXT_YEAR = 1900`, `MAX_CONTEXT_YEAR = 2100`
- Produces: `validate_suffix_year_mapping(year: int | None, mapping: tuple[tuple[int, int], ...]) -> tuple[tuple[int, int], ...]`

- [ ] **Step 1: Add exhaustive lexical and mapping tests**

```python
# tests/test_date_tokens.py
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
```

- [ ] **Step 2: Run the new tests and verify the module import fails**

Run: `.venv/bin/pytest -q tests/test_date_tokens.py`

Expected: FAIL during collection with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the neutral date-token module**

Move `DateTokenStyle`, `_DATE_STYLE_CONFIGURATION`, `_styled_date_pattern`, the full
and short pattern mappings, and the 1900/2100 bounds from `discovery.py`. Add
`validate_suffix_year_mapping` with the exact union of the two existing Pydantic
validators' checks: nonempty effective mapping, sorted order, unique suffixes,
matching suffix/year, supported bounds, and agreement with an optional single year.

- [ ] **Step 4: Run date-token unit tests**

Run: `.venv/bin/pytest -q tests/test_date_tokens.py`

Expected: all tests pass.

- [ ] **Step 5: Add model parity tests before migration**

Parameterize both `DiscoveredDateYearContext` and `DiscoveryDateYearContextSummary`
with the same valid rollover mapping and the same invalid duplicate, unsorted,
out-of-range, and suffix-mismatch mappings. Assert they accept and reject identically.

- [ ] **Step 6: Migrate discovery, normalization, and public summary validation**

- Import `DateTokenStyle`, pattern maps, and year bounds from `date_tokens.py`.
- Replace normalization's six handwritten short-date regexes with the shared mapping.
- Have both Pydantic validators call `validate_suffix_year_mapping` and retain their
  existing public error surface as `ValueError`.
- Keep discovery year inference and normalization semantic assignment in place.

- [ ] **Step 7: Run focused and full verification**

Run: `.venv/bin/pytest -q tests/test_date_tokens.py tests/test_discovery.py tests/test_normalize.py tests/test_models.py`

Expected: all focused tests pass.

Run: `.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy src && .venv/bin/pytest -q`

Expected: all commands exit 0.

- [ ] **Step 8: Commit the date-token foundation**

```bash
git add src/ccparser/date_tokens.py src/ccparser/discovery.py src/ccparser/normalize.py src/ccparser/models.py tests/test_date_tokens.py tests/test_discovery.py tests/test_normalize.py tests/test_models.py
git commit -m "refactor: centralize date token policy"
```

### Task 4: Canonical Geometry and Column Association

**Files:**
- Create: `src/ccparser/geometry.py`
- Create: `tests/test_geometry.py`
- Modify: `src/ccparser/evidence/models.py`
- Modify: `src/ccparser/evidence/currency.py`
- Modify: `src/ccparser/evidence/ocr.py`
- Modify: `src/ccparser/layout/models.py`
- Modify: `src/ccparser/layout/rows.py`
- Modify: `src/ccparser/layout/text.py`
- Modify: `src/ccparser/layout/columns.py`
- Modify: `src/ccparser/layout/regions.py`
- Modify: `src/ccparser/normalize.py`
- Modify: `src/ccparser/fx.py`
- Modify: `src/ccparser/ocr_repair.py`
- Test: `tests/evidence/test_evidence_models.py`
- Test: `tests/layout/test_layout_models.py`
- Test: `tests/evidence/test_ocr.py`
- Test: `tests/layout/test_rows.py`
- Test: `tests/layout/test_text.py`
- Test: `tests/layout/test_columns.py`
- Test: `tests/layout/test_regions.py`

**Interfaces:**
- Produces: `BBox`, `Point`
- Produces: `bbox_width`, `bbox_height`, `bbox_center_x`, `bbox_center_y`
- Produces: `union_bbox`, `intersection_over_union`, `intersection_over_smaller`, `vertical_overlap`
- Produces: `center_inside(inner: BBox, outer: BBox) -> bool`
- Produces: `cells_in_column(cells: Iterable[Cell], column: ColumnSpec) -> tuple[Cell, ...]`
- Produces: `source_or_center_cells(cells: Iterable[Cell], column: ColumnSpec) -> tuple[Cell, ...]`
- Produces: `columns_for_role(schema: ColumnSchema, role: ColumnRole) -> tuple[ColumnSpec, ...]`

- [ ] **Step 1: Characterize every geometry boundary before moving helpers**

Add table-driven tests for zero-width/zero-height boxes, disjoint boxes, identical boxes,
inclusive center-on-edge membership, union ordering, and deterministic input ordering. Add
column tests that distinguish the two current policies:

```python
def test_cells_in_column_uses_inclusive_cell_centers() -> None:
    column = _column(x0=10.0, x1=20.0)
    left_edge = _cell("left", bbox=(8.0, 0.0, 12.0, 4.0))
    right_edge = _cell("right", bbox=(18.0, 0.0, 22.0, 4.0))
    outside = _cell("outside", bbox=(20.1, 0.0, 22.1, 4.0))
    assert cells_in_column((left_edge, right_edge, outside), column) == (
        left_edge,
        right_edge,
    )


def test_source_or_center_cells_prefers_nonempty_source_cells() -> None:
    source = _cell("source", bbox=(30.0, 0.0, 34.0, 4.0))
    centered = _cell("centered", bbox=(12.0, 0.0, 14.0, 4.0))
    column = _column(x0=10.0, x1=20.0, source_cells=(source,))
    assert source_or_center_cells((source, centered), column) == (source,)
```

- [ ] **Step 2: Run the focused tests and confirm the new imports fail**

Run: `.venv/bin/pytest -q tests/test_geometry.py tests/layout/test_columns.py`

Expected: FAIL during collection because `ccparser.geometry` and the supported column
association helpers do not exist.

- [ ] **Step 3: Implement the dependency-neutral geometry module**

Move the `BBox` and `Point` aliases to `geometry.py` and re-export them from
`evidence.models` for compatibility. Implement the shared formulas with the current
degenerate-box behavior: overlap ratios return `0.0` when their denominator is not
positive, center checks are inclusive, and `union_bbox(())` raises `ValueError`.

- [ ] **Step 4: Implement the two named column association policies**

Put the public helpers in `layout/columns.py`. `cells_in_column` always uses inclusive
center membership. `source_or_center_cells` returns source cells when any source cell is
present in the candidate collection and otherwise delegates to `cells_in_column`.
Do not replace these names with a Boolean policy flag: inference/header association and
row-value association are separate contracts.

- [ ] **Step 5: Migrate one subsystem at a time and run its existing suite**

Use shared geometry formulas in this order, running the listed tests after each move:

1. `evidence/currency.py` and `evidence/ocr.py` — `tests/evidence/test_ocr.py` and currency tests.
2. `layout/rows.py` and `layout/text.py` — `tests/layout/test_rows.py tests/layout/test_text.py`.
3. `layout/columns.py` and `layout/regions.py` — `tests/layout/test_columns.py tests/layout/test_regions.py`.
4. `normalize.py`, `fx.py`, and `ocr_repair.py` — their focused suites.

Use `source_or_center_cells` only where the former columns implementation honored
`ColumnSpec.source_cells`. Use `cells_in_column` for normalization, FX, OCR repair, and
projected row values. Do not merge the two line-clustering algorithms or tune thresholds.

- [ ] **Step 6: Run focused and full verification**

Run: `.venv/bin/pytest -q tests/test_geometry.py tests/evidence tests/layout tests/test_normalize.py tests/test_fx.py tests/test_ocr_repair.py`

Expected: all focused tests pass with unchanged ordering, diagnostics, and evidence.

Run: `.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy src && .venv/bin/pytest -q`

Expected: all commands exit 0.

- [ ] **Step 7: Commit canonical geometry and association**

```bash
git add src/ccparser/geometry.py src/ccparser/evidence src/ccparser/layout src/ccparser/normalize.py src/ccparser/fx.py src/ccparser/ocr_repair.py tests/test_geometry.py tests/evidence tests/layout tests/test_normalize.py tests/test_fx.py tests/test_ocr_repair.py
git commit -m "refactor: centralize geometry and column association"
```

### Task 5: Validate Geometry and Share Word Deduplication

**Files:**
- Create: `src/ccparser/layout/word_dedup.py`
- Create: `tests/layout/test_word_dedup.py`
- Modify: `src/ccparser/geometry.py`
- Modify: `src/ccparser/evidence/models.py`
- Modify: `src/ccparser/layout/models.py`
- Modify: `src/ccparser/layout/rows.py`
- Modify: `src/ccparser/layout/text.py`
- Test: `tests/evidence/test_evidence_models.py`
- Test: `tests/layout/test_layout_models.py`
- Test: `tests/layout/test_rows.py`
- Test: `tests/layout/test_text.py`

**Interfaces:**
- Produces: `validate_bbox(value: BBox) -> BBox`
- Produces: `validate_point(value: Point) -> Point`
- Produces: `deduplicate_words(words: Iterable[Word], *, text_key: Callable[[str], str]) -> tuple[Word, ...]`

- [ ] **Step 1: Add failing model invariant tests**

Parameterize `Glyph`, `Word`, `Cell`, `Row`, `TableRegion`, and other bbox-bearing
models with `nan`, positive/negative infinity, inverted x coordinates, and inverted y
coordinates. Assert ordered finite boxes are accepted, including zero-area boxes and
slightly out-of-page coordinates. Add a `ColumnSpec` test requiring
`relative_x0 <= relative_x1` while preserving boundary values.

- [ ] **Step 2: Confirm impossible geometry is currently accepted**

Run: `.venv/bin/pytest -q tests/evidence/test_evidence_models.py tests/layout/test_layout_models.py`

Expected: the new invalid-geometry cases fail because models currently accept them.

- [ ] **Step 3: Add the narrow geometry validators at model boundaries**

Implement finite/order checks in `validate_bbox` and `validate_point`. Reuse them in
Pydantic `field_validator`s rather than duplicating checks. Validate relative column
bands separately. Do not add strict page containment: extraction evidence can
legitimately extend a small distance outside a page box.

- [ ] **Step 4: Characterize both existing word-deduplication modes**

Create fixtures covering exact duplicates, canonically equivalent Unicode text,
overlap at and immediately below both thresholds, differing confidence, input-order
ties, and repeated non-overlapping words. Assert rows use identity text while logical
text reconstruction uses NFC-normalized text.

- [ ] **Step 5: Run the deduplication tests and verify the supported helper is absent**

Run: `.venv/bin/pytest -q tests/layout/test_word_dedup.py`

Expected: FAIL during collection because `layout.word_dedup` does not exist.

- [ ] **Step 6: Extract the common algorithm without changing its policies**

Move the shared overlap thresholds, survivor ranking, and stable ordering into
`deduplicate_words`. Pass `lambda text: text` from `rows.py` and NFC normalization from
`text.py`. Preserve multiplicity for non-overlapping words and do not deduplicate
provenance outside this exact algorithm.

- [ ] **Step 7: Run focused and full verification**

Run: `.venv/bin/pytest -q tests/evidence/test_evidence_models.py tests/layout/test_layout_models.py tests/layout/test_word_dedup.py tests/layout/test_rows.py tests/layout/test_text.py tests/evidence/test_ocr.py tests/evidence/test_pdf.py`

Expected: all focused tests pass.

Run: `.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy src && .venv/bin/pytest -q`

Expected: all commands exit 0.

- [ ] **Step 8: Commit validation and word deduplication**

```bash
git add src/ccparser/geometry.py src/ccparser/evidence/models.py src/ccparser/layout/models.py src/ccparser/layout/word_dedup.py src/ccparser/layout/rows.py src/ccparser/layout/text.py tests/evidence/test_evidence_models.py tests/layout/test_layout_models.py tests/layout/test_word_dedup.py tests/layout/test_rows.py tests/layout/test_text.py
git commit -m "refactor: validate geometry and share word deduplication"
```

### Task 6: Shared Safe Paths and PDF Traversal

**Files:**
- Create: `src/ccparser/paths.py`
- Create: `tests/test_paths.py`
- Modify: `src/ccparser/parser.py:434-483`
- Modify: `src/ccparser/audit.py:134-183`
- Modify: `src/ccparser/models.py:494-507`
- Test: `tests/test_parser.py`
- Test: `tests/test_audit.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `safe_relative_posix_path(value: str) -> PurePosixPath`
- Produces: `is_relative_to(path: Path, parent: Path) -> bool`
- Produces: `paths_overlap(left: Path, right: Path) -> bool`
- Produces: `iter_regular_pdf_files(root: Path, *, excluded_roots: Sequence[Path] = (), excluded_directory_names: Collection[str] = (), on_error: Callable[[OSError], None] | None = None) -> tuple[Path, ...]`

- [ ] **Step 1: Add unit tests for relative paths, containment, and walking**

Cover empty/absolute/traversal paths and the current POSIX treatment of backslashes,
nested and sibling containment, case-insensitive `.pdf` suffixes, regular files only, symlink exclusion,
deterministic ordering, excluded roots, and excluded directory names. Inject an
`os.walk` error and assert `on_error` receives the original exception exactly once.

- [ ] **Step 2: Run path tests and verify the module import fails**

Run: `.venv/bin/pytest -q tests/test_paths.py`

Expected: FAIL during collection with `ModuleNotFoundError`.

- [ ] **Step 3: Implement pure path validation and the policy-neutral walker**

The walker returns a sorted tuple of resolved regular PDF paths and never bakes in
`.cache`, output, quarantine, or OCR-cache policy. It prunes excluded resolved roots and
excluded directory names before descent, does not follow directory symlinks, and passes
`on_error` directly to `os.walk`.

- [ ] **Step 4: Add audit parity for unreadable subtrees**

Add the audit equivalent of parser's current `os.walk` error test. Assert the audit
raises its existing public exception rather than silently omitting the subtree. Retain
tests for quarantine/output/cache exclusions, `.cache`, overlap validation, symlinks,
and ordering.

- [ ] **Step 5: Migrate parser, audit, and model validation**

Delete duplicate `_is_relative_to`, safe-relative-path parsing, and PDF walking code.
Keep parser/audit exception translation at their public boundaries. Pass `.cache` only
from audit, and pass output/cache/quarantine roots only from the caller that owns each
policy. Preserve the source-file label and serialized relative path format.

- [ ] **Step 6: Run focused and full verification**

Run: `.venv/bin/pytest -q tests/test_paths.py tests/test_parser.py tests/test_audit.py tests/test_models.py`

Expected: all focused tests pass, including the new audit walk-error case.

Run: `.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy src && .venv/bin/pytest -q`

Expected: all commands exit 0.

- [ ] **Step 7: Commit shared path handling**

```bash
git add src/ccparser/paths.py src/ccparser/parser.py src/ccparser/audit.py src/ccparser/models.py tests/test_paths.py tests/test_parser.py tests/test_audit.py tests/test_models.py
git commit -m "refactor: share safe PDF traversal"
```

### Task 7: Summary Projection and Mechanical Dead-Code Cleanup

**Files:**
- Create: `src/ccparser/summary.py`
- Create: `tests/test_summary.py`
- Modify: `src/ccparser/parser.py:96-283,321-422`
- Modify: `src/ccparser/layout/text.py`
- Modify: `src/ccparser/layout/columns.py`
- Modify: `src/ccparser/layout/regions.py`
- Modify: `src/ccparser/ocr_repair.py`
- Modify: `src/ccparser/fx.py`
- Modify: `src/ccparser/normalize.py`
- Test: `tests/test_parser.py`
- Test: `tests/layout/test_regions.py`
- Test: `tests/test_ocr_repair.py`
- Test: `tests/test_fx.py`
- Test: `tests/test_normalize.py`

**Interfaces:**
- Produces: explicit typed converters in `ccparser.summary` from evidence, layout, and discovery objects to their existing public summary models
- Preserves: parser-level imports or private aliases only where tests or supported callers require them

- [ ] **Step 1: Add summary-adapter parity tests**

Build one object graph containing page evidence, an unclaimed table region, a claimed
group, rejected totals, and a rollover year mapping. Assert each new converter produces
the same Pydantic model and canonical `model_dump_json()` bytes as the existing parser
adapter. Add parser integration cases for statement, ambiguous, and not-statement
results and compare complete `StatementResult` equality.

- [ ] **Step 2: Run the tests and verify the summary module import fails**

Run: `.venv/bin/pytest -q tests/test_summary.py`

Expected: FAIL during collection because `ccparser.summary` does not exist.

- [ ] **Step 3: Move explicit typed adapters out of orchestration**

Move the adapter functions without replacing them with reflective `model_dump`
conversion. Keep flat `table_regions` separate from group-owned regions, because it can
contain unclaimed regions. Update parser imports and keep its orchestration order,
status calculation, diagnostics, and result construction unchanged.

- [ ] **Step 4: Add focused characterization for each removable argument/helper**

Before deletion, add or identify tests proving:

- row projection output is independent of its unused `page_evidence` argument;
- FX extraction output is independent of its unused `conversion_date` argument;
- `logical_rows` returns identical text, evidence, and ordering when reconstructing from
  its already-selected glyphs and words;
- no supported import references `_vertical_overlap` or `_cells_to_rows`.

- [ ] **Step 5: Apply only the proven mechanical cleanup**

- Remove unused `layout.text._vertical_overlap`.
- Remove unused `layout.columns._cells_to_rows`.
- Remove `page_evidence` from `_project_row_to_header_bands` and update region and OCR
  repair callers.
- Remove `conversion_date` from `extract_foreign_exchange` and update normalization and
  test callers.
- In `logical_rows`, call `logical_text_for_evidence(glyphs, words)` instead of
  reselecting the same bbox through `logical_text_for_bbox`.

Do not combine this step with threshold, ordering, or semantic-rule changes.

- [ ] **Step 6: Run focused and full verification**

Run: `.venv/bin/pytest -q tests/test_summary.py tests/test_parser.py tests/layout/test_regions.py tests/test_ocr_repair.py tests/test_fx.py tests/test_normalize.py`

Expected: all focused tests pass and canonical serialized results are unchanged.

Run: `.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy src && .venv/bin/pytest -q`

Expected: all commands exit 0.

- [ ] **Step 7: Commit adapter extraction and dead-code cleanup**

```bash
git add src/ccparser/summary.py src/ccparser/parser.py src/ccparser/layout/text.py src/ccparser/layout/columns.py src/ccparser/layout/regions.py src/ccparser/ocr_repair.py src/ccparser/fx.py src/ccparser/normalize.py tests/test_summary.py tests/test_parser.py tests/layout/test_regions.py tests/test_ocr_repair.py tests/test_fx.py tests/test_normalize.py
git commit -m "refactor: separate summaries and remove dead plumbing"
```

### Foundations Completion Gate

- [ ] Run `.venv/bin/ruff format --check .`
- [ ] Run `.venv/bin/ruff check .`
- [ ] Run `.venv/bin/mypy src`
- [ ] Run `.venv/bin/pytest -q`
- [ ] Record the exact passing test count and compare canonical parser fixtures before
  starting the structural plan.
