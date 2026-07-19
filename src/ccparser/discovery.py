"""Positive-evidence statement discovery over glyph-corrected logical rows."""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from enum import StrEnum
from itertools import pairwise

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ccparser.evidence.models import BBox, DocumentEvidence, Glyph
from ccparser.layout import TableRegion, detect_table_regions, logical_rows
from ccparser.layout.columns import infer_column_roles, proven_billed_amount_column
from ccparser.layout.models import Cell, ColumnRole, Row
from ccparser.layout.text import logical_text_for_evidence
from ccparser.models import EvidenceReference
from ccparser.money import currencies_in_text, parse_amount


class _ImmutableDiscoveryModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DocumentClassification(StrEnum):
    """Classification supported by positive structural evidence."""

    STATEMENT = "statement"
    NOT_STATEMENT = "not_statement"
    AMBIGUOUS = "ambiguous"


class DateTokenStyle(StrEnum):
    """Supported relative ordering and separator for abbreviated date tokens."""

    DAY_FIRST_SLASH = "day_first_slash"
    DAY_FIRST_DOT = "day_first_dot"
    DAY_FIRST_DASH = "day_first_dash"
    YEAR_FIRST_SLASH = "year_first_slash"
    YEAR_FIRST_DOT = "year_first_dot"
    YEAR_FIRST_DASH = "year_first_dash"


class DiscoveredField(_ImmutableDiscoveryModel):
    """A labeled metadata value retained only in an explicit evidence field."""

    field_name: str
    value: str
    evidence: EvidenceReference
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()


class DiscoveredPrintedTotal(_ImmutableDiscoveryModel):
    """An unambiguous total label, monetary text, and currency association."""

    amount_text: str
    currency: str
    label_evidence: EvidenceReference
    value_evidence: EvidenceReference
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()


class DiscoveredDateYearContext(_ImmutableDiscoveryModel):
    """Proven short-date suffix mappings supported by complete document dates."""

    year: int | None = Field(default=None, ge=1900, le=2100)
    year_by_suffix: tuple[tuple[int, int], ...] = ()
    style: DateTokenStyle
    evidence: tuple[EvidenceReference, ...] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_year_mapping(self) -> DiscoveredDateYearContext:
        mapping = self.year_by_suffix
        if not mapping and self.year is not None:
            mapping = ((self.year % 100, self.year),)
        if not mapping:
            raise ValueError("at least one proven suffix-year mapping is required")
        suffixes = tuple(suffix for suffix, _ in mapping)
        years = tuple(year for _, year in mapping)
        if len(set(suffixes)) != len(suffixes):
            raise ValueError("date suffix-year mappings must have unique suffixes")
        if any(not 0 <= suffix <= 99 for suffix in suffixes):
            raise ValueError("date suffix must be between 0 and 99")
        if any(not 1900 <= year <= 2100 for year in years):
            raise ValueError("mapped year must be between 1900 and 2100")
        if any(year % 100 != suffix for suffix, year in mapping):
            raise ValueError("mapped year must match its two-digit suffix")
        if tuple(sorted(mapping)) != mapping:
            raise ValueError("date suffix-year mappings must be sorted")
        if self.year is not None and mapping != ((self.year % 100, self.year),):
            raise ValueError("single year must agree with its suffix mapping")
        return self


class RejectedTotalCandidate(_ImmutableDiscoveryModel):
    """A total-like row rejected from grouping, retained with exact evidence."""

    evidence: tuple[EvidenceReference, ...] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = Field(min_length=1)


class StatementGroupDiscovery(_ImmutableDiscoveryModel):
    """Structural statement section associated with exactly one printed total."""

    group_id: str
    table_regions: tuple[TableRegion, ...]
    printed_total: DiscoveredPrintedTotal
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()


class StatementDiscovery(_ImmutableDiscoveryModel):
    """Deterministic statement structure, metadata, and classification evidence."""

    classification: DocumentClassification
    groups: tuple[StatementGroupDiscovery, ...] = ()
    table_regions: tuple[TableRegion, ...] = ()
    issuer: DiscoveredField | None = None
    account_number: DiscoveredField | None = None
    card_number: DiscoveredField | None = None
    statement_date: DiscoveredField | None = None
    date_year_context: DiscoveredDateYearContext | None = None
    rejected_total_candidates: tuple[RejectedTotalCandidate, ...] = ()
    confidence: float = Field(ge=0, le=1)
    reason_codes: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()


_TOTAL_MARKERS = frozenset(
    {
        "amount due",
        "billing total",
        "grand total",
        "statement total",
        "total",
        "total amount",
        "total billed",
        "סהכ",
        "סך הכל",
        "סךהכל",
        "סכום כולל",
        "סכוםכולל",
        "סכום לחיוב",
        "סכוםלחיוב",
    }
)
_POINTS_UNIT_MARKERS = frozenset(
    {
        "loyalty points",
        "points",
        "reward points",
        "rewards points",
        "נקודה",
        "נקודות",
    }
)
_COUNT_VALUE_PATTERN = re.compile(r"^[+-]?(?:\d+|\d{1,3}(?:[,\s]\d{3})+)$")
_FORM_TITLES = frozenset(
    {
        "application form",
        "card application",
        "card cancellation",
        "card cancellation form",
        "cancellation form",
        "request form",
        "טופס ביטול",
        "טופס בקשה",
        "בקשה לביטול כרטיס",
    }
)
_FORM_FIELDS = frozenset(
    {
        "applicant name",
        "date of birth",
        "identity number",
        "signature",
        "שם המבקש",
        "מספר זהות",
        "חתימה",
    }
)
_FIELD_LABELS: dict[str, frozenset[str]] = {
    "issuer": frozenset({"card issuer", "issuer", "מנפיק", "שם המנפיק"}),
    "account_number": frozenset({"account", "account no", "account number", "חשבון", "מספר חשבון"}),
    "card_number": frozenset({"card no", "card number", "credit card number", "מספר כרטיס"}),
    "statement_date": frozenset({"billing date", "statement date", "תאריך דוח", "תאריך חיוב"}),
}
_ACRONYM_QUOTES = frozenset({'"', "'", "\u2018", "\u2019", "\u201c", "\u201d", "\u05f3", "\u05f4"})
_DATE_TOKEN_PATTERN = re.compile(r"(?<!\d)(\d{1,4})\s*([./-])\s*(\d{1,2})\s*\2\s*(\d{1,4})(?!\d)")
_MIN_CONTEXT_YEAR = 1900
_MAX_CONTEXT_YEAR = 2100
_DATE_STYLE_CONFIGURATION: dict[DateTokenStyle, tuple[str, bool]] = {
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


_FULL_DATE_TOKEN_PATTERNS = {
    style: _styled_date_pattern(separator, year_first=year_first, year_digits=4)
    for style, (separator, year_first) in _DATE_STYLE_CONFIGURATION.items()
}
_SHORT_DATE_TOKEN_PATTERNS = {
    style: _styled_date_pattern(separator, year_first=year_first, year_digits=2)
    for style, (separator, year_first) in _DATE_STYLE_CONFIGURATION.items()
}


def _normalized_phrase(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text).casefold()
    canonical: list[str] = []
    for index, char in enumerate(normalized):
        between_letters = (
            0 < index < len(normalized) - 1
            and normalized[index - 1].isalpha()
            and normalized[index + 1].isalpha()
        )
        if char in _ACRONYM_QUOTES and between_letters:
            continue
        canonical.append(char if char.isalnum() else " ")
    return " ".join("".join(canonical).split())


def _contains_phrase(text: str, phrases: Iterable[str]) -> bool:
    tokens = _normalized_phrase(text).split()
    for phrase in phrases:
        phrase_tokens = phrase.split()
        length = len(phrase_tokens)
        if any(tokens[index : index + length] == phrase_tokens for index in range(len(tokens))):
            return True
        if any("\u0590" <= char <= "\u05ff" for char in phrase):
            compact_phrase = "".join(phrase_tokens)
            if any(token.startswith(compact_phrase) for token in tokens):
                return True
    return False


def _evidence(cell: Cell) -> EvidenceReference:
    return EvidenceReference(page_number=cell.page_number, bbox=cell.bbox, raw_text=cell.text)


def _table_currencies(region: TableRegion) -> tuple[str, ...]:
    roles = {column.role for column in region.table_schema.columns}
    billing_roles = {ColumnRole.AMOUNT, ColumnRole.BILLING_CURRENCY}
    if ColumnRole.CURRENCY in roles:
        if ColumnRole.ORIGINAL_AMOUNT in roles:
            return ()
        billing_roles.add(ColumnRole.CURRENCY)
    proven_amount_column = proven_billed_amount_column(
        region.table_schema,
        region.rows,
    )
    billing_columns = tuple(
        column
        for column in region.table_schema.columns
        if column.role in billing_roles
        and (
            column.role is not ColumnRole.AMOUNT
            or proven_amount_column is None
            or column is proven_amount_column
        )
    )
    currencies = {
        currency
        for cells in (
            tuple(cell for row in region.rows for cell in row.cells),
            region.header.cells,
        )
        for column in billing_columns
        for cell in cells
        if column.bbox[0] <= (cell.bbox[0] + cell.bbox[2]) / 2 <= column.bbox[2]
        for currency in currencies_in_text(cell.text)
    }
    return tuple(sorted(currencies))


def _reading_key_bbox(page_number: int, bbox: BBox) -> tuple[int, float, float]:
    return (page_number, bbox[1], bbox[0])


def _center_x(bbox: BBox) -> float:
    return (bbox[0] + bbox[2]) / 2


def _row_height(row: Row) -> float:
    return max(0.0, row.bbox[3] - row.bbox[1])


def _normalized_exact_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def _center_inside_bbox(candidate: BBox, container: BBox) -> bool:
    center_x = (candidate[0] + candidate[2]) / 2
    center_y = (candidate[1] + candidate[3]) / 2
    return container[0] <= center_x <= container[2] and container[1] <= center_y <= container[3]


def _row_glyph_authoritative_signature(
    row: Row,
) -> tuple[tuple[tuple[str, str], ...], str, tuple[str, ...]]:
    assigned: list[list[Glyph]] = [[] for _ in row.words]
    orphan_glyphs: list[Glyph] = []
    for glyph in row.glyphs:
        owners = tuple(
            index
            for index, word in enumerate(row.words)
            if _center_inside_bbox(glyph.bbox, word.bbox)
        )
        if len(owners) == 1:
            assigned[owners[0]].append(glyph)
        else:
            orphan_glyphs.append(glyph)
    word_evidence = tuple(
        sorted(
            (
                _normalized_exact_text(word.text),
                _normalized_exact_text(logical_text_for_evidence(glyphs, (word,))),
            )
            for word, glyphs in zip(row.words, assigned, strict=True)
        )
    )
    orphan_tuple = tuple(orphan_glyphs)
    return (
        word_evidence,
        _normalized_exact_text(logical_text_for_evidence(orphan_tuple, ())),
        tuple(
            sorted(token for glyph in orphan_tuple if (token := _normalized_exact_text(glyph.char)))
        ),
    )


def _row_total_marker_signature(row: Row) -> tuple[str, ...]:
    return tuple(
        sorted(
            marker
            for marker in _TOTAL_MARKERS
            if any(_contains_phrase(cell.text, (marker,)) for cell in row.cells)
        )
    )


def _horizontal_containment_fraction(candidate: BBox, reference: BBox) -> float:
    overlap = max(0.0, min(candidate[2], reference[2]) - max(candidate[0], reference[0]))
    candidate_width = candidate[2] - candidate[0]
    return overlap / candidate_width if candidate_width > 0 else 0.0


def _vertical_gap(first: BBox, second: BBox) -> float:
    return max(0.0, max(first[1], second[1]) - min(first[3], second[3]))


def _is_lossless_total_overlay_artifact(
    candidate: Row,
    total_marker_rows: Sequence[Row],
    regions: Sequence[TableRegion],
) -> bool:
    if not candidate.words:
        return False
    for reference in total_marker_rows:
        if reference is candidate or reference.page_number != candidate.page_number:
            continue
        if len(reference.cells) < 2 or _row_height(reference) <= 0:
            continue
        if _row_height(candidate) > _row_height(reference) * 0.2:
            continue
        if _vertical_gap(candidate.bbox, reference.bbox) > _row_height(reference) * 1.5:
            continue
        if _horizontal_containment_fraction(candidate.bbox, reference.bbox) < 0.9:
            continue
        if _row_total_marker_signature(candidate) != _row_total_marker_signature(reference):
            continue
        if _row_glyph_authoritative_signature(candidate) != _row_glyph_authoritative_signature(
            reference
        ):
            continue
        preceding = tuple(
            region
            for region in regions
            if _reading_key_bbox(region.page_number, region.bbox)
            < _reading_key_bbox(reference.page_number, reference.bbox)
        )
        reference_total, _ = _total_from_row(reference, preceding)
        if reference_total is not None:
            return True
    return False


def _is_count_value(text: str) -> bool:
    return _COUNT_VALUE_PATTERN.fullmatch(" ".join(text.split())) is not None


def _is_financial_header_row(row: Row) -> bool:
    if len(row.cells) < 2:
        return False
    roles = {
        column.role
        for column in infer_column_roles(row.cells, ()).columns
        if column.role is not ColumnRole.UNKNOWN
    }
    return ColumnRole.AMOUNT in roles and bool(roles & {ColumnRole.DATE, ColumnRole.DESCRIPTION})


def _is_points_ledger_total(
    candidate: Row,
    rows: Sequence[Row],
    regions: Sequence[TableRegion],
) -> bool:
    if any(currency for cell in candidate.cells for currency in currencies_in_text(cell.text)):
        return False
    count_cells = tuple(cell for cell in candidate.cells if _is_count_value(cell.text))
    if not count_cells:
        return False
    candidate_key = _reading_key_bbox(candidate.page_number, candidate.bbox)
    preceding_headers = tuple(
        (row, cell)
        for row in rows
        if row.page_number == candidate.page_number
        and _reading_key_bbox(row.page_number, row.bbox) < candidate_key
        for cell in row.cells
        if _contains_phrase(cell.text, _POINTS_UNIT_MARKERS)
        and any(cell.bbox[0] <= _center_x(count.bbox) <= cell.bbox[2] for count in count_cells)
    )
    if not preceding_headers:
        return False
    header_row, header_cell = max(
        preceding_headers,
        key=lambda item: _reading_key_bbox(item[0].page_number, item[0].bbox),
    )
    header_key = _reading_key_bbox(header_row.page_number, header_row.bbox)
    section_rows = tuple(
        row
        for row in rows
        if row.page_number == candidate.page_number
        and header_key < _reading_key_bbox(row.page_number, row.bbox) < candidate_key
    )
    if any(
        _contains_phrase(cell.text, _TOTAL_MARKERS) for row in section_rows for cell in row.cells
    ):
        return False
    if any(
        region.page_number == candidate.page_number
        and header_key
        < _reading_key_bbox(region.header.page_number, region.header.bbox)
        < candidate_key
        for region in regions
    ):
        return False
    if any(_is_financial_header_row(row) for row in section_rows):
        return False
    return any(
        _is_count_value(cell.text)
        and header_cell.bbox[0] <= _center_x(cell.bbox) <= header_cell.bbox[2]
        for row in section_rows
        for cell in row.cells
    )


def _total_from_row(
    row: Row,
    preceding_regions: Sequence[TableRegion],
) -> tuple[DiscoveredPrintedTotal | None, tuple[str, ...]]:
    label_cells = tuple(cell for cell in row.cells if _contains_phrase(cell.text, _TOTAL_MARKERS))
    if not label_cells:
        return None, ()
    diagnostics: list[str] = []
    explicit_currencies = {
        currency for cell in row.cells for currency in currencies_in_text(cell.text)
    }
    inferred_currencies = {
        currency
        for region in preceding_regions
        for currencies in (_table_currencies(region),)
        if len(currencies) == 1
        for currency in currencies
    }
    if len(explicit_currencies) == 1:
        currency = next(iter(explicit_currencies))
    elif not explicit_currencies and len(inferred_currencies) == 1:
        currency = next(iter(inferred_currencies))
    else:
        currency = None
        diagnostics.append("unknown_total_currency")
    if len(explicit_currencies) > 1:
        diagnostics.append("conflicting_total_currency")
    amount_cells: list[tuple[Cell, str]] = []
    if currency is not None:
        for cell in row.cells:
            candidate_text = cell.text
            if cell in label_cells:
                normalized = _normalized_phrase(candidate_text)
                if normalized in _TOTAL_MARKERS:
                    continue
                for marker in sorted(_TOTAL_MARKERS, key=len, reverse=True):
                    if candidate_text.casefold().startswith(marker.casefold()):
                        candidate_text = candidate_text[len(marker) :].strip(" :")
                        break
            parsed = parse_amount(candidate_text, currency_hint=currency)
            if parsed.amount is not None:
                amount_cells.append((cell, candidate_text))
    if len(amount_cells) != 1:
        diagnostics.append("ambiguous_total_value")
    if len(amount_cells) != 1 or currency is None:
        return None, tuple(diagnostics)
    value_cell, amount_text = amount_cells[0]
    return (
        DiscoveredPrintedTotal(
            amount_text=amount_text,
            currency=currency,
            label_evidence=_evidence(label_cells[0]),
            value_evidence=_evidence(value_cell),
            confidence=min(row.confidence, label_cells[0].confidence, value_cell.confidence),
        ),
        tuple(diagnostics),
    )


def _metadata_field(rows: Sequence[Row], field_name: str) -> DiscoveredField | None:
    labels = _FIELD_LABELS[field_name]
    for row in rows:
        for label_index, cell in enumerate(row.cells):
            normalized = _normalized_phrase(cell.text)
            if normalized not in labels:
                continue
            candidates = tuple(
                candidate
                for index, candidate in enumerate(row.cells)
                if index != label_index and candidate.text.strip()
            )
            if len(candidates) != 1:
                continue
            value_cell = candidates[0]
            return DiscoveredField(
                field_name=field_name,
                value=unicodedata.normalize("NFC", value_cell.text.strip()),
                evidence=_evidence(value_cell),
                confidence=min(cell.confidence, value_cell.confidence),
            )
    return None


def _complete_date_year(match: re.Match[str]) -> int | None:
    first, _, second, third = match.groups()
    if len(first) == 4 and len(third) != 4:
        year, month, day = int(first), int(second), int(third)
    elif len(third) == 4 and len(first) != 4:
        day, month, year = int(first), int(second), int(third)
    else:
        return None
    if not _MIN_CONTEXT_YEAR <= year <= _MAX_CONTEXT_YEAR:
        return None
    try:
        date(year, month, day)
    except ValueError:
        return None
    return year


def _table_date_cells(regions: Sequence[TableRegion]) -> tuple[Cell, ...]:
    cells: list[Cell] = []
    for region in regions:
        date_columns = tuple(
            column
            for column in region.table_schema.columns
            if column.role in {ColumnRole.DATE, ColumnRole.CONVERSION_DATE}
        )
        for row in region.rows:
            for column in date_columns:
                cells.extend(
                    cell
                    for cell in row.cells
                    if column.bbox[0] <= (cell.bbox[0] + cell.bbox[2]) / 2 <= column.bbox[2]
                )
    return tuple(cells)


def _date_year_context(
    rows: Sequence[Row], regions: Sequence[TableRegion]
) -> DiscoveredDateYearContext | None:
    cells = tuple(cell for row in rows for cell in row.cells)
    table_date_cells = _table_date_cells(regions)
    table_short_years_by_style: dict[DateTokenStyle, set[int]] = {}
    for style, short_pattern in _SHORT_DATE_TOKEN_PATTERNS.items():
        years: set[int] = set()
        for cell in table_date_cells:
            for match in short_pattern.finditer(cell.text):
                try:
                    date(2000, int(match.group("month")), int(match.group("day")))
                except ValueError:
                    continue
                years.add(int(match.group("year")))
        table_short_years_by_style[style] = years
    has_table_short_dates = any(table_short_years_by_style.values())
    candidates: list[tuple[DateTokenStyle, tuple[tuple[int, int], ...], tuple[Cell, ...]]] = []
    for style, full_pattern in _FULL_DATE_TOKEN_PATTERNS.items():
        short_pattern = _SHORT_DATE_TOKEN_PATTERNS[style]
        full_years: set[int] = set()
        supporting_cells_by_year: dict[int, list[Cell]] = {}
        short_years: set[int] = set()
        for cell in cells:
            for match in full_pattern.finditer(cell.text):
                year = int(match.group("year"))
                if not _MIN_CONTEXT_YEAR <= year <= _MAX_CONTEXT_YEAR:
                    continue
                try:
                    date(year, int(match.group("month")), int(match.group("day")))
                except ValueError:
                    continue
                full_years.add(year)
                supporting_cells_by_year.setdefault(year, []).append(cell)
            for match in short_pattern.finditer(cell.text):
                try:
                    date(2000, int(match.group("month")), int(match.group("day")))
                except ValueError:
                    continue
                short_years.add(int(match.group("year")))
        if has_table_short_dates:
            table_short_years = table_short_years_by_style[style]
            if not table_short_years:
                continue
            year_by_suffix: list[tuple[int, int]] = []
            context_supporting_cells: list[Cell] = []
            for short_year in sorted(table_short_years):
                matching_years = tuple(
                    sorted(year for year in full_years if year % 100 == short_year)
                )
                candidate_evidence_years = {year: {year} for year in matching_years}
                for bracketed_year in range(_MIN_CONTEXT_YEAR, _MAX_CONTEXT_YEAR + 1):
                    if (
                        bracketed_year % 100 == short_year
                        and bracketed_year - 1 in full_years
                        and bracketed_year + 1 in full_years
                    ):
                        candidate_evidence_years.setdefault(bracketed_year, set()).update(
                            (bracketed_year - 1, bracketed_year + 1)
                        )
                if len(candidate_evidence_years) != 1:
                    break
                selected_suffix_year, evidence_years = next(iter(candidate_evidence_years.items()))
                year_by_suffix.append((short_year, selected_suffix_year))
                for evidence_year in evidence_years:
                    for cell in supporting_cells_by_year[evidence_year]:
                        if not any(existing is cell for existing in context_supporting_cells):
                            context_supporting_cells.append(cell)
            if len(year_by_suffix) != len(table_short_years):
                continue
            ordered_supporting_cells = tuple(
                cell
                for cell in cells
                if any(cell is supporting for supporting in context_supporting_cells)
            )
            candidates.append((style, tuple(year_by_suffix), ordered_supporting_cells))
            continue
        if len(full_years) == 1:
            year = next(iter(full_years))
            if short_years == {year % 100}:
                candidates.append(
                    (
                        style,
                        ((year % 100, year),),
                        tuple(supporting_cells_by_year[year]),
                    )
                )
    if len(candidates) != 1:
        return None
    style, selected_year_by_suffix, supporting_cells = candidates[0]
    selected_year = selected_year_by_suffix[0][1] if len(selected_year_by_suffix) == 1 else None
    return DiscoveredDateYearContext(
        year=selected_year,
        year_by_suffix=selected_year_by_suffix,
        style=style,
        evidence=tuple(_evidence(cell) for cell in supporting_cells),
        confidence=statistics.mean(cell.confidence for cell in supporting_cells),
    )


def _positive_form_evidence(rows: Sequence[Row]) -> bool:
    has_title = any(_contains_phrase(cell.text, _FORM_TITLES) for row in rows for cell in row.cells)
    field_count = sum(
        _contains_phrase(cell.text, _FORM_FIELDS) for row in rows for cell in row.cells
    )
    return has_title and field_count >= 2


def _deduplicated(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _schemas_compatible(first: TableRegion, second: TableRegion) -> bool:
    first_columns = first.table_schema.columns
    second_columns = second.table_schema.columns
    if len(first_columns) != len(second_columns):
        return False
    columns_compatible = all(
        first_column.role is second_column.role
        and abs(first_column.relative_x0 - second_column.relative_x0) <= 0.08
        and abs(first_column.relative_x1 - second_column.relative_x1) <= 0.08
        for first_column, second_column in zip(first_columns, second_columns, strict=True)
    )
    first_header = tuple(
        _normalized_phrase(cell.text)
        for cell in sorted(first.header.cells, key=lambda cell: (cell.bbox[0], cell.bbox[1]))
    )
    second_header = tuple(
        _normalized_phrase(cell.text)
        for cell in sorted(second.header.cells, key=lambda cell: (cell.bbox[0], cell.bbox[1]))
    )
    known_role_count = sum(
        first_column.role is not ColumnRole.UNKNOWN
        for first_column, second_column in zip(first_columns, second_columns, strict=True)
        if first_column.role is second_column.role
    )
    return columns_compatible and (first_header == second_header or known_role_count >= 3)


def _proven_page_continuation(
    regions: Sequence[TableRegion], page_heights: Mapping[int, float]
) -> bool:
    if len(regions) < 2 or len({region.page_number for region in regions}) != len(regions):
        return False
    for previous, following in pairwise(regions):
        previous_height = page_heights.get(previous.page_number)
        following_height = page_heights.get(following.page_number)
        if previous_height is None or following_height is None:
            return False
        if following.page_number != previous.page_number + 1:
            return False
        if not _schemas_compatible(previous, following):
            return False
        if previous.bbox[3] < previous_height * 0.75:
            return False
        if following.header.bbox[1] > following_height * 0.25:
            return False
    return True


def _associate_regions(
    *,
    total_row: Row,
    total: DiscoveredPrintedTotal,
    regions: Sequence[TableRegion],
    previous_total_row: Row | None,
    remaining_totals: Sequence[DiscoveredPrintedTotal],
    page_heights: Mapping[int, float],
) -> tuple[tuple[TableRegion, ...], tuple[str, ...]]:
    total_key = _reading_key_bbox(total_row.page_number, total_row.bbox)
    previous_total_key = (
        _reading_key_bbox(previous_total_row.page_number, previous_total_row.bbox)
        if previous_total_row is not None
        else None
    )
    section = tuple(
        region
        for region in regions
        if _reading_key_bbox(region.page_number, region.bbox) < total_key
        and (
            previous_total_key is None
            or _reading_key_bbox(region.page_number, region.bbox) > previous_total_key
        )
    )
    if not section:
        return (), ("total_without_table",)
    if any(_table_currencies(region) != (total.currency,) for region in section):
        return (), ("ambiguous_table_currency",)
    if len(section) == 1:
        return section, ()
    if sum(candidate.currency == total.currency for candidate in remaining_totals) > 1:
        return (), ("ambiguous_group_region_association",)
    if _proven_page_continuation(section, page_heights):
        return section, ()
    return (), ("ambiguous_group_region_association",)


def discover_statement(evidence: DocumentEvidence) -> StatementDiscovery:
    """Discover statement groups and classify only from positive semantic evidence."""

    page_rows = tuple(
        row
        for page in sorted(evidence.pages, key=lambda item: item.page_number)
        for row in logical_rows(page)
    )
    regions = tuple(
        sorted(
            (
                region
                for page in sorted(evidence.pages, key=lambda item: item.page_number)
                for region in detect_table_regions(page)
            ),
            key=lambda region: _reading_key_bbox(region.page_number, region.bbox),
        )
    )
    observed_total_marker_rows = tuple(
        row
        for row in page_rows
        if any(_contains_phrase(cell.text, _TOTAL_MARKERS) for cell in row.cells)
    )
    total_marker_rows = tuple(
        row
        for row in observed_total_marker_rows
        if not _is_lossless_total_overlay_artifact(row, observed_total_marker_rows, regions)
        and not _is_points_ledger_total(row, page_rows, regions)
    )
    groups: list[StatementGroupDiscovery] = []
    diagnostics: list[str] = []
    rejected_total_rows: list[tuple[Row, RejectedTotalCandidate]] = []
    total_candidates: list[tuple[Row, DiscoveredPrintedTotal]] = []
    for total_row in total_marker_rows:
        preceding = tuple(
            region
            for region in regions
            if _reading_key_bbox(region.page_number, region.bbox)
            < _reading_key_bbox(total_row.page_number, total_row.bbox)
        )
        total, total_diagnostics = _total_from_row(total_row, preceding)
        if total is None and total_diagnostics:
            rejected_total_rows.append(
                (
                    total_row,
                    RejectedTotalCandidate(
                        evidence=tuple(_evidence(cell) for cell in total_row.cells),
                        confidence=statistics.mean(cell.confidence for cell in total_row.cells),
                        diagnostics=total_diagnostics,
                    ),
                )
            )
        if total is not None and preceding:
            total_candidates.append((total_row, total))

    page_heights = {page.page_number: page.height for page in evidence.pages}
    previous_total_row: Row | None = None
    for total_index, (total_row, total) in enumerate(total_candidates):
        associated, association_diagnostics = _associate_regions(
            total_row=total_row,
            total=total,
            regions=regions,
            previous_total_row=previous_total_row,
            remaining_totals=tuple(candidate for _, candidate in total_candidates[total_index:]),
            page_heights=page_heights,
        )
        previous_total_row = total_row
        diagnostics.extend(association_diagnostics)
        if not associated:
            continue
        group_id = f"group-{len(groups) + 1:04d}"
        confidence = statistics.mean(
            (total.confidence, *(region.confidence for region in associated))
        )
        groups.append(
            StatementGroupDiscovery(
                group_id=group_id,
                table_regions=associated,
                printed_total=total,
                confidence=confidence,
            )
        )

    claimed_regions = tuple(region for group in groups for region in group.table_regions)
    if any(not any(region is claimed for claimed in claimed_regions) for region in regions):
        diagnostics.append("unclaimed_table_region")

    metadata = {field_name: _metadata_field(page_rows, field_name) for field_name in _FIELD_LABELS}
    date_year_context = _date_year_context(page_rows, regions)
    diagnostics.extend(
        diagnostic for _, candidate in rejected_total_rows for diagnostic in candidate.diagnostics
    )
    if groups:
        classification = DocumentClassification.STATEMENT
        confidence = statistics.mean(group.confidence for group in groups)
        reason_codes = ("transaction_table_with_compatible_total",)
    elif not regions and not total_marker_rows and _positive_form_evidence(page_rows):
        classification = DocumentClassification.NOT_STATEMENT
        confidence = 0.95
        reason_codes = ("positive_non_statement_form_evidence",)
    else:
        classification = DocumentClassification.AMBIGUOUS
        confidence = 0.5 if regions or total_marker_rows else 0.2
        reason_codes = (
            ("statement_evidence_incomplete",)
            if regions or total_marker_rows
            else ("insufficient_positive_evidence",)
        )

    return StatementDiscovery(
        classification=classification,
        groups=tuple(groups),
        table_regions=regions,
        issuer=metadata["issuer"],
        account_number=metadata["account_number"],
        card_number=metadata["card_number"],
        statement_date=metadata["statement_date"],
        date_year_context=date_year_context,
        rejected_total_candidates=tuple(candidate for _, candidate in rejected_total_rows),
        confidence=confidence,
        reason_codes=reason_codes,
        diagnostics=_deduplicated(diagnostics),
    )


__all__ = [
    "DateTokenStyle",
    "DiscoveredDateYearContext",
    "DiscoveredField",
    "DiscoveredPrintedTotal",
    "DocumentClassification",
    "RejectedTotalCandidate",
    "StatementDiscovery",
    "StatementGroupDiscovery",
    "discover_statement",
]
