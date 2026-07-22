"""Positive-evidence statement discovery over glyph-corrected logical rows."""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ccparser.date_tokens import (
    FULL_DATE_TOKEN_PATTERNS,
    MAX_CONTEXT_YEAR,
    MIN_CONTEXT_YEAR,
    SHORT_DATE_TOKEN_PATTERNS,
    DateTokenStyle,
    _SuffixYearMappingValidationError,
    _SuffixYearMappingViolation,
    validate_suffix_year_mapping,
)
from ccparser.decimal_math import exact_difference, exact_sum
from ccparser.evidence.models import BBox, DocumentEvidence, Glyph
from ccparser.geometry import (
    bbox_center_x as _center_x,
)
from ccparser.geometry import (
    bbox_height,
)
from ccparser.geometry import (
    center_inside as _center_inside_bbox,
)
from ccparser.layout import TableRegion, logical_rows
from ccparser.layout.columns import (
    cells_in_column,
    explicit_billed_amount_column,
    infer_column_roles,
    proven_billed_amount_column,
)
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row
from ccparser.layout.regions import (
    _detect_table_regions_from_rows,
    _literal_header_role_count,
    _merged_header_bands,
    _page_row_key,
    _singleton_transaction_candidates,
)
from ccparser.layout.row_tags import RowTag, has_row_tag, is_structural_continuation
from ccparser.layout.text import logical_text_for_evidence
from ccparser.models import EvidenceReference
from ccparser.money import canonical_currency, currencies_in_text, is_money_shaped, parse_amount
from ccparser.text_tokens import contains_token_sequence, phrase_tokens


class _ImmutableDiscoveryModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


_DISCOVERED_SUFFIX_YEAR_MAPPING_VIOLATION_PRIORITY = (
    _SuffixYearMappingViolation.EMPTY,
    _SuffixYearMappingViolation.DUPLICATE_SUFFIX,
    _SuffixYearMappingViolation.INVALID_SUFFIX,
    _SuffixYearMappingViolation.INVALID_YEAR,
    _SuffixYearMappingViolation.SUFFIX_YEAR_MISMATCH,
    _SuffixYearMappingViolation.UNSORTED,
    _SuffixYearMappingViolation.SINGLE_YEAR_DISAGREEMENT,
)


class DocumentClassification(StrEnum):
    """Classification supported by positive structural evidence."""

    STATEMENT = "statement"
    NOT_STATEMENT = "not_statement"
    AMBIGUOUS = "ambiguous"


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

    year: int | None = Field(default=None, ge=MIN_CONTEXT_YEAR, le=MAX_CONTEXT_YEAR)
    year_by_suffix: tuple[tuple[int, int], ...] = ()
    style: DateTokenStyle
    evidence: tuple[EvidenceReference, ...] = Field(min_length=1)
    metadata_evidence: tuple[tuple[str, str], ...] = ()
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_year_mapping(self) -> DiscoveredDateYearContext:
        try:
            validate_suffix_year_mapping(self.year, self.year_by_suffix)
        except _SuffixYearMappingValidationError as error:
            _, message = error.resolve(_DISCOVERED_SUFFIX_YEAR_MAPPING_VIOLATION_PRIORITY)
            raise ValueError(message) from error
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
        "subtotal",
        "total",
        "total amount",
        "total billed",
        "total charges due",
        "total for date",
        "סה כ",
        "סה כ חיוב",
        "סהכ",
        "סך חיוב",
        "סך הכל",
        "סךהכל",
        "סך החיובים הצפויים למועד החיוב הבא",
        "סכום כולל",
        "סכוםכולל",
        "סכום לחיוב",
        "סכוםלחיוב",
    }
)
_NO_ACTIVITY_MARKERS = frozenset(
    {
        "no activity this month",
        "no activity this period",
        "no transactions this month",
        "no transactions this period",
        "לא בוצעו עסקאות החודש",
        "לא בוצעו עסקאות בתקופה זו",
        "לא בוצעו עסקות החודש",
        "לא בוצעו עסקות בתקופה זו",
    }
)
_CONTINUATION_HEADING_MARKERS = frozenset(
    {
        "continued transaction details",
        "continued transactions",
        "transaction details continued",
        "המשך פירוט עסקאות",
        "המשך פירוט עסקות",
    }
)
_TRANSACTION_HISTORY_TITLE_MARKERS = frozenset(
    {
        "transaction details",
        "transactions details",
        "פירוט עסקאות",
        "פירוט עסקות",
    }
)
_TRANSACTION_HISTORY_ROUTE_PATTERN = re.compile(
    r"https?://\S*/transactions(?:/|\b)",
    re.IGNORECASE,
)
_FUTURE_BILLING_HEADING_MARKERS = frozenset(
    {
        "future billing transaction details",
        "future billing transactions",
        "future charges",
        "transactions for future billing",
        "פירוט עסקאות לחיוב עתידי",
        "פירוט עסקות לחיוב עתידי",
        "חיובים עתידיים",
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
_FEE_SUMMARY_MARKERS = frozenset(
    {
        "commission",
        "commissions",
        "fee",
        "fees",
        "עמלה",
        "העמלה",
        "עמלות",
        "העמלות",
        "סך העמלות",
        "סהכעמלות",
    }
)
_PAID_FEE_SUMMARY_MARKERS = frozenset(
    {
        "commissions paid",
        "fees paid",
        "total commissions paid",
        "total fees paid",
        "העמלות ששולמו",
        "עמלות ששולמו",
    }
)
_TAX_SUMMARY_MARKERS = frozenset({"tax", "vat", "מס", "מעמ", "מע מ"})
_RATE_HEADER_MARKERS = frozenset(
    {
        "annual percentage rate",
        "annual rate",
        "apr",
        "effective rate",
        "interest rate",
        "interest rates",
        "nominal rate",
        "rate",
        "rates",
        "ריבית",
        "ריביות",
        "ריבית אפקטיבית",
        "ריבית מתואמת",
        "ריבית נומינלית",
        "שיעור ריבית",
        "שיעור הריבית",
    }
)
_COUNT_VALUE_PATTERN = re.compile(r"^[+-]?(?:\d+|\d{1,3}(?:[,\s]\d{3})+)$")
_PERCENT_VALUE_PATTERN = re.compile(r"^[+-]?\d+(?:[.,]\d+)?\s*%$")
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
_CANCELLATION_PURPOSES = frozenset(
    {
        "card cancellation",
        "cancellation of card",
        "ביטול כרטיס",
    }
)
_FIELD_LABELS: dict[str, frozenset[str]] = {
    "issuer": frozenset({"card issuer", "issuer", "מנפיק", "שם המנפיק"}),
    "account_number": frozenset({"account", "account no", "account number", "חשבון", "מספר חשבון"}),
    "card_number": frozenset({"card no", "card number", "credit card number", "מספר כרטיס"}),
    "statement_date": frozenset({"billing date", "statement date", "תאריך דוח", "תאריך חיוב"}),
}
_YEAR_MONTH_TOKEN_PATTERN = re.compile(
    r"(?<!\d)(?P<year>(?:19|20)\d{2})\s*[/\-]\s*"
    r"(?P<month>0?[1-9]|1[0-2])(?!\s*[/\-]\s*\d)(?!\d)"
)
_PDF_METADATA_DATE_PATTERN = re.compile(r"^D:(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})")
_COMPOUND_TOTAL_AMOUNT_PATTERN = re.compile(
    r"(?<![\d.,])(?P<amount>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)[.,]\d{2}-?)"
)


def _normalized_phrase(text: str) -> str:
    return " ".join(phrase_tokens(text, ignore_acronym_quotes=True))


def _contains_phrase(text: str, phrases: Iterable[str]) -> bool:
    candidates = tuple(phrases)
    if contains_token_sequence(text, candidates, ignore_acronym_quotes=True):
        return True
    tokens = phrase_tokens(text, ignore_acronym_quotes=True)
    for phrase in candidates:
        candidate_tokens = phrase_tokens(phrase, ignore_acronym_quotes=True)
        compact_phrase = "".join(candidate_tokens)
        if len(candidate_tokens) > 1 and compact_phrase in tokens:
            return True
        if any("\u0590" <= char <= "\u05ff" for char in phrase) and any(
            token.startswith(compact_phrase) for token in tokens
        ):
            return True
    return False


def _positive_zero_activity_evidence(rows: Sequence[Row]) -> Cell | None:
    return next(
        (
            cell
            for row in rows
            for cell in row.cells
            if _contains_phrase(cell.text, _NO_ACTIVITY_MARKERS)
        ),
        None,
    )


def _is_future_billing_region(region: TableRegion, rows: Sequence[Row]) -> bool:
    preceding = tuple(
        row
        for row in rows
        if row.page_number == region.page_number and row.bbox[3] <= region.header.bbox[1]
    )
    if not preceding:
        return False
    heading = max(preceding, key=lambda row: row.bbox[3])
    heading_height = max(0.0, heading.bbox[3] - heading.bbox[1])
    gap = region.header.bbox[1] - heading.bbox[3]
    return (
        heading_height > 0
        and gap <= heading_height * 2
        and any(
            _contains_phrase(cell.text, _FUTURE_BILLING_HEADING_MARKERS) for cell in heading.cells
        )
    )


def _is_future_billing_total(
    candidate: Row,
    future_regions: Sequence[TableRegion],
    current_regions: Sequence[TableRegion],
    rows: Sequence[Row],
    date_year_context: DiscoveredDateYearContext | None,
) -> bool:
    preceding = tuple(
        region
        for region in (*future_regions, *current_regions)
        if region.page_number == candidate.page_number and region.bbox[3] <= candidate.bbox[1]
    )
    if not preceding:
        return False
    nearest = max(preceding, key=lambda region: _reading_key_bbox(region.page_number, region.bbox))
    if any(nearest is region for region in future_regions):
        return True

    candidate_key = _reading_key_bbox(candidate.page_number, candidate.bbox)
    structural_rows = _merged_header_bands(
        tuple(row for row in rows if row.page_number == candidate.page_number)
    )
    header_candidates = tuple(
        row
        for row in structural_rows
        if _reading_key_bbox(row.page_number, row.bbox) < candidate_key
        and _literal_header_role_count(row) >= 2
    )
    if not header_candidates:
        return False
    header = max(
        header_candidates,
        key=lambda row: _reading_key_bbox(row.page_number, row.bbox),
    )
    header_key = _reading_key_bbox(header.page_number, header.bbox)
    section_rows = tuple(
        row
        for row in structural_rows
        if header_key < _reading_key_bbox(row.page_number, row.bbox) < candidate_key
    )
    if len(section_rows) != 1 or any(_literal_header_role_count(row) >= 2 for row in section_rows):
        return False
    schema = infer_column_roles(
        header.cells,
        tuple(cell for row in section_rows for cell in row.cells),
    )
    billed_column = explicit_billed_amount_column(schema.columns, schema.header_cells)
    original_columns = tuple(
        column for column in schema.columns if column.role is ColumnRole.ORIGINAL_AMOUNT
    )
    if (
        billed_column is None
        or len(original_columns) != 1
        or sum(column.role is ColumnRole.DATE for column in schema.columns) != 1
        or sum(column.role is ColumnRole.DESCRIPTION for column in schema.columns) != 1
    ):
        return False

    evidence_cells = (*header.cells, *section_rows[0].cells, *candidate.cells)
    provenance_sources = tuple(
        source
        for cell in evidence_cells
        for source in (
            *(word.source for word in cell.words),
            *(glyph.source for glyph in cell.glyphs),
        )
    )
    if not provenance_sources or any(source != "digital" for source in provenance_sources):
        return False
    observed_currencies = {
        currency
        for cell in evidence_cells
        for value in (cell.text, *(word.text for word in cell.words))
        for currency in currencies_in_text(value)
    }
    if len(observed_currencies) != 1:
        return False
    section_currency = next(iter(observed_currencies))

    def parsed_values(values: Iterable[str]) -> frozenset[tuple[Decimal, str]]:
        parsed: set[tuple[Decimal, str]] = set()
        for value in values:
            currencies = currencies_in_text(value)
            if len(currencies) > 1 or any(currency != section_currency for currency in currencies):
                continue
            result = parse_amount(
                value,
                currency_hint=section_currency,
            )
            if result.amount is not None and result.currency is not None:
                parsed.add((result.amount, result.currency))
        return frozenset(parsed)

    billed_cells: list[Cell] = []
    original_values: set[tuple[Decimal, str]] = set()
    for row in section_rows:
        for cell in row.cells:
            center = _center_x(cell.bbox)
            values = (cell.text, *(word.text for word in cell.words))
            if billed_column.bbox[0] <= center <= billed_column.bbox[2]:
                billed_cells.append(cell)
            elif original_columns[0].bbox[0] <= center <= original_columns[0].bbox[2]:
                original_values.update(parsed_values(values))
    candidate_values = parsed_values(
        (*[cell.text for cell in candidate.cells], *[word.text for word in candidate.words])
    )
    if billed_cells or len(candidate_values) != 1 or candidate_values != frozenset(original_values):
        return False

    def parsed_dates(cells: Sequence[Cell]) -> frozenset[date]:
        dates: set[date] = set()
        full_patterns = tuple(FULL_DATE_TOKEN_PATTERNS.values())
        year_mapping = (
            dict(date_year_context.year_by_suffix) if date_year_context is not None else {}
        )
        if (
            date_year_context is not None
            and not year_mapping
            and date_year_context.year is not None
        ):
            year_mapping[date_year_context.year % 100] = date_year_context.year
        for cell in cells:
            for full_pattern in full_patterns:
                for match in full_pattern.finditer(cell.text):
                    year = int(match.group("year"))
                    try:
                        dates.add(date(year, int(match.group("month")), int(match.group("day"))))
                    except ValueError:
                        continue
            if date_year_context is not None:
                for match in SHORT_DATE_TOKEN_PATTERNS[date_year_context.style].finditer(cell.text):
                    resolved_year = year_mapping.get(int(match.group("year")))
                    if resolved_year is None:
                        continue
                    try:
                        dates.add(
                            date(
                                resolved_year,
                                int(match.group("month")),
                                int(match.group("day")),
                            )
                        )
                    except ValueError:
                        continue
        return frozenset(dates)

    section_date_columns = tuple(
        column for column in schema.columns if column.role is ColumnRole.DATE
    )
    section_date_cells = tuple(
        cell
        for cell in section_rows[0].cells
        if section_date_columns[0].bbox[0]
        <= _center_x(cell.bbox)
        <= section_date_columns[0].bbox[2]
    )
    preceding_current_regions = tuple(
        region
        for region in current_regions
        if _reading_key_bbox(region.page_number, region.bbox) < candidate_key
    )
    current_date_cells = _table_date_cells(preceding_current_regions)
    date_provenance_sources = tuple(
        source
        for cell in (*section_date_cells, *current_date_cells)
        for source in (
            *(word.source for word in cell.words),
            *(glyph.source for glyph in cell.glyphs),
        )
    )
    section_dates = parsed_dates(section_date_cells)
    current_dates = parsed_dates(current_date_cells)
    return (
        bool(date_provenance_sources)
        and all(source == "digital" for source in date_provenance_sources)
        and len(section_dates) == 1
        and bool(current_dates)
        and next(iter(section_dates)) > max(current_dates)
    )


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
        for cell in cells_in_column(cells, column)
        for currency in currencies_in_text(cell.text)
    }
    return tuple(sorted(currencies))


def _can_inherit_printed_total_currency(region: TableRegion) -> bool:
    roles = {column.role for column in region.table_schema.columns}
    if roles & {ColumnRole.CURRENCY, ColumnRole.BILLING_CURRENCY}:
        return False
    explicit_column = explicit_billed_amount_column(
        region.table_schema.columns,
        region.table_schema.header_cells,
    )
    proven_column = proven_billed_amount_column(region.table_schema, region.rows)
    if (
        explicit_column is None
        or proven_column is None
        or explicit_column.index != proven_column.index
        or not region.rows
    ):
        return False
    for row in region.rows:
        cells = cells_in_column(row.cells, proven_column)
        if (
            len(cells) != 1
            or not is_money_shaped(cells[0].text)
            or currencies_in_text(cells[0].text)
        ):
            return False
    return True


def _table_matches_total_currency(region: TableRegion, currency: str) -> bool:
    table_currencies = _table_currencies(region)
    if table_currencies:
        return table_currencies == (currency,)
    return _can_inherit_printed_total_currency(region)


def _reading_key_bbox(page_number: int, bbox: BBox) -> tuple[int, float, float]:
    return (page_number, bbox[1], bbox[0])


def _normalized_exact_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


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


def _cell_backed_row_signature(
    row: Row,
) -> tuple[tuple[tuple[str, str], ...], str, tuple[str, ...]]:
    return _row_glyph_authoritative_signature(
        row.model_copy(
            update={
                "words": tuple(word for cell in row.cells for word in cell.words),
                "glyphs": tuple(glyph for cell in row.cells for glyph in cell.glyphs),
            }
        )
    )


def _has_lossless_overlay_signature(candidate: Row, reference: Row) -> bool:
    candidate_row = _row_glyph_authoritative_signature(candidate)
    reference_row = _row_glyph_authoritative_signature(reference)
    if candidate_row == reference_row:
        return True

    candidate_cells = _cell_backed_row_signature(candidate)
    reference_cells = _cell_backed_row_signature(reference)
    empty_orphans = ("", ())
    if (
        candidate_cells != reference_cells
        or candidate_row != candidate_cells
        or candidate_cells[1:] != empty_orphans
        or reference_cells[1:] != empty_orphans
        or reference_row[1:] != empty_orphans
    ):
        return False
    return reference_row[0] == tuple(sorted((*reference_cells[0], *candidate_cells[0])))


def _cell_glyph_inventory(row: Row) -> tuple[str, ...]:
    return tuple(
        sorted(
            char
            for cell in row.cells
            for glyph in cell.glyphs
            for char in unicodedata.normalize("NFC", glyph.char).casefold()
            if not char.isspace()
        )
    )


def _text_without_printed_amount(
    row: Row,
    total: DiscoveredPrintedTotal,
) -> str | None:
    text = "".join(
        char
        for cell in row.cells
        for char in unicodedata.normalize("NFC", cell.text).casefold()
        if not char.isspace()
    )
    amount = "".join(unicodedata.normalize("NFC", total.amount_text).casefold().split())
    if not amount or text.count(amount) != 1:
        return None
    return text.replace(amount, "", 1)


def _inventory_without_text(inventory: tuple[str, ...], text: str) -> tuple[str, ...] | None:
    remaining = list(inventory)
    for char in unicodedata.normalize("NFC", text).casefold():
        if char.isspace():
            continue
        try:
            remaining.remove(char)
        except ValueError:
            return None
    return tuple(remaining)


def _single_contiguous_insertion(longer: str, shorter: str) -> str | None:
    if len(longer) <= len(shorter):
        return None
    prefix_length = 0
    while prefix_length < len(shorter) and longer[prefix_length] == shorter[prefix_length]:
        prefix_length += 1
    extra_length = len(longer) - len(shorter)
    if longer[prefix_length + extra_length :] != shorter[prefix_length:]:
        return None
    return longer[prefix_length : prefix_length + extra_length]


def _has_lossless_compound_total_overlay_signature(
    candidate: Row,
    reference: Row,
    candidate_total: DiscoveredPrintedTotal,
    reference_total: DiscoveredPrintedTotal,
) -> bool:
    if candidate_total.currency != reference_total.currency:
        return False
    candidate_amount = parse_amount(
        candidate_total.amount_text,
        currency_hint=candidate_total.currency,
    ).amount
    reference_amount = parse_amount(
        reference_total.amount_text,
        currency_hint=reference_total.currency,
    ).amount
    if candidate_amount is None or candidate_amount != reference_amount:
        return False
    candidate_residual = _text_without_printed_amount(candidate, candidate_total)
    reference_residual = _text_without_printed_amount(reference, reference_total)
    if candidate_residual is None or reference_residual is None:
        return False
    candidate_glyphs = _cell_glyph_inventory(candidate)
    reference_glyphs = _cell_glyph_inventory(reference)
    if not candidate_glyphs or not reference_glyphs:
        return False
    if candidate_residual == reference_residual:
        return candidate_glyphs == reference_glyphs
    extra = _single_contiguous_insertion(candidate_residual, reference_residual)
    if extra is not None:
        return (
            canonical_currency(extra) == candidate_total.currency
            and _inventory_without_text(candidate_glyphs, extra) == reference_glyphs
        )
    extra = _single_contiguous_insertion(reference_residual, candidate_residual)
    if extra is not None:
        return (
            canonical_currency(extra) == reference_total.currency
            and _inventory_without_text(reference_glyphs, extra) == candidate_glyphs
        )
    return False


def _row_total_marker_signature(row: Row) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                "".join(_normalized_phrase(marker).split())
                for marker in _TOTAL_MARKERS
                if any(_contains_phrase(cell.text, (marker,)) for cell in row.cells)
            }
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
        if len(reference.cells) < 2 or bbox_height(reference.bbox) <= 0:
            continue
        if bbox_height(candidate.bbox) > bbox_height(reference.bbox) * 0.2:
            continue
        if _vertical_gap(candidate.bbox, reference.bbox) > bbox_height(reference.bbox) * 1.5:
            continue
        if _horizontal_containment_fraction(candidate.bbox, reference.bbox) < 0.9:
            continue
        if _row_total_marker_signature(candidate) != _row_total_marker_signature(reference):
            continue
        preceding = tuple(
            region
            for region in regions
            if _reading_key_bbox(region.page_number, region.bbox)
            < _reading_key_bbox(reference.page_number, reference.bbox)
        )
        reference_total, _ = _total_from_row(reference, preceding)
        if reference_total is None:
            continue
        if _has_lossless_overlay_signature(candidate, reference):
            return True
        candidate_preceding = tuple(
            region
            for region in regions
            if _reading_key_bbox(region.page_number, region.bbox)
            < _reading_key_bbox(candidate.page_number, candidate.bbox)
        )
        candidate_total, _ = _total_from_row(candidate, candidate_preceding)
        if candidate_total is not None and _has_lossless_compound_total_overlay_signature(
            candidate,
            reference,
            candidate_total,
            reference_total,
        ):
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


def _is_rate_ledger_header(row: Row) -> bool:
    return any(_contains_phrase(cell.text, _RATE_HEADER_MARKERS) for cell in row.cells)


def _is_percentage_value(text: str) -> bool:
    return _PERCENT_VALUE_PATTERN.fullmatch(" ".join(text.split())) is not None


def _contiguous_rate_section(
    header: Row,
    rows: Sequence[Row],
    regions: Sequence[TableRegion],
) -> tuple[Row, ...]:
    header_key = _reading_key_bbox(header.page_number, header.bbox)
    table_header_keys = {
        _page_row_key(region.header)
        for region in regions
        if region.page_number == header.page_number
        and _reading_key_bbox(region.header.page_number, region.header.bbox) > header_key
    }
    ordered = tuple(
        row
        for row in rows
        if row.page_number == header.page_number
        and _reading_key_bbox(row.page_number, row.bbox) >= header_key
    )
    section: list[Row] = []
    for row in ordered:
        if section:
            previous = section[-1]
            gap_scale = max(bbox_height(previous.bbox), bbox_height(row.bbox))
            if gap_scale <= 0 or _vertical_gap(previous.bbox, row.bbox) > gap_scale * 1.5:
                break
            if _page_row_key(row) in table_header_keys or _is_financial_header_row(row):
                break
        section.append(row)
    return tuple(section)


def _is_rate_ledger_total(
    candidate: Row,
    rows: Sequence[Row],
    regions: Sequence[TableRegion],
) -> bool:
    candidate_key = _reading_key_bbox(candidate.page_number, candidate.bbox)
    preceding_headers = tuple(
        row
        for row in rows
        if row.page_number == candidate.page_number
        and _reading_key_bbox(row.page_number, row.bbox) < candidate_key
        and _is_rate_ledger_header(row)
    )
    for header in reversed(preceding_headers):
        section = _contiguous_rate_section(header, rows, regions)
        if candidate not in section:
            continue
        percentage_cells = tuple(
            cell for row in section for cell in row.cells if _is_percentage_value(cell.text)
        )
        if len(percentage_cells) >= 2:
            return True
    return False


def _is_fee_tax_summary_total(candidate: Row, rows: Sequence[Row] = ()) -> bool:
    text = " ".join(cell.text for cell in candidate.cells)

    def currency_evidence_count(row: Row) -> int:
        return sum(
            bool(currencies_in_text(value))
            for value in (
                tuple(word.text for word in row.words) or tuple(cell.text for cell in row.cells)
            )
        )

    candidate_currency_evidence_count = currency_evidence_count(candidate)
    explicit_fee_tax_summary = (
        _contains_phrase(text, _FEE_SUMMARY_MARKERS)
        and _contains_phrase(text, _TAX_SUMMARY_MARKERS)
        and candidate_currency_evidence_count >= 2
    )
    explicit_paid_fee_summary = (
        _contains_phrase(text, _TOTAL_MARKERS)
        and _contains_phrase(text, _FEE_SUMMARY_MARKERS)
        and _contains_phrase(text, _PAID_FEE_SUMMARY_MARKERS)
        and candidate_currency_evidence_count >= 1
    )
    summary_rows = tuple(
        sorted(
            (
                row
                for row in rows
                if row.page_number == candidate.page_number
                and any(_contains_phrase(cell.text, _TOTAL_MARKERS) for cell in row.cells)
                and (
                    _contains_phrase(
                        " ".join(cell.text for cell in row.cells),
                        _FEE_SUMMARY_MARKERS,
                    )
                    or _contains_phrase(
                        " ".join(cell.text for cell in row.cells), _TAX_SUMMARY_MARKERS
                    )
                )
            ),
            key=lambda row: row.bbox[1],
        )
    )
    multiline_fee_tax_summary = False
    candidate_indices = tuple(index for index, row in enumerate(summary_rows) if row is candidate)
    if len(candidate_indices) == 1:
        start = candidate_indices[0]
        end = start
        while (
            start > 0
            and _vertical_gap(summary_rows[start - 1].bbox, summary_rows[start].bbox)
            <= max(
                bbox_height(summary_rows[start - 1].bbox),
                bbox_height(summary_rows[start].bbox),
            )
            * 2
        ):
            start -= 1
        while (
            end + 1 < len(summary_rows)
            and _vertical_gap(summary_rows[end].bbox, summary_rows[end + 1].bbox)
            <= max(
                bbox_height(summary_rows[end].bbox),
                bbox_height(summary_rows[end + 1].bbox),
            )
            * 2
        ):
            end += 1
        block = summary_rows[start : end + 1]
        block_texts = tuple(" ".join(cell.text for cell in row.cells) for row in block)
        multiline_fee_tax_summary = (
            len(block) >= 2
            and all(currency_evidence_count(row) >= 1 for row in block)
            and any(
                _contains_phrase(value, _FEE_SUMMARY_MARKERS)
                and _contains_phrase(value, _TAX_SUMMARY_MARKERS)
                for value in block_texts
            )
            and all(
                _contains_phrase(value, _FEE_SUMMARY_MARKERS)
                or _contains_phrase(value, _TAX_SUMMARY_MARKERS)
                for value in block_texts
            )
        )
    return explicit_fee_tax_summary or explicit_paid_fee_summary or multiline_fee_tax_summary


def _amount_cells_in_nearest_billed_band(
    row: Row,
    amount_cells: Sequence[tuple[Cell, str]],
    preceding_regions: Sequence[TableRegion],
) -> tuple[tuple[Cell, str], ...]:
    same_page_regions = tuple(
        region
        for region in preceding_regions
        if region.page_number == row.page_number and region.bbox[3] <= row.bbox[3]
    )
    if not same_page_regions:
        return ()
    region = max(
        same_page_regions,
        key=lambda candidate: _reading_key_bbox(candidate.page_number, candidate.bbox),
    )
    transaction_rows = tuple(
        candidate
        for candidate in region.rows
        if not has_row_tag(candidate, RowTag.SUBORDINATE_DETAIL)
    )
    billed_column = proven_billed_amount_column(region.table_schema, transaction_rows)
    if billed_column is None:
        return ()
    return tuple(
        candidate
        for candidate in amount_cells
        if billed_column.bbox[0] <= _center_x(candidate[0].bbox) <= billed_column.bbox[2]
    )


def _without_isolated_ocr_letter(
    cell: Cell,
    text: str,
    currency: str,
) -> str | None:
    if not cell.words or any(word.source != "ocr" for word in cell.words):
        return None
    normalized = "".join(
        char for char in unicodedata.normalize("NFC", text) if unicodedata.category(char) != "Cf"
    )
    candidates: list[str] = []
    leading = re.fullmatch(r"\s*[A-Za-z]\s+(.+?)\s*", normalized)
    if leading is not None:
        candidates.append(leading.group(1))
    trailing = re.fullmatch(r"\s*(.+?)\s+[A-Za-z]\s*", normalized)
    if trailing is not None:
        candidates.append(trailing.group(1))
    valid = tuple(
        candidate
        for candidate in dict.fromkeys(candidates)
        if parse_amount(candidate, currency_hint=currency).amount is not None
    )
    return valid[0] if len(valid) == 1 else None


def _unique_compound_total_amount(text: str, currency: str) -> str | None:
    candidates = tuple(
        match.group("amount")
        for match in _COMPOUND_TOTAL_AMOUNT_PATTERN.finditer(unicodedata.normalize("NFC", text))
        if parse_amount(match.group("amount"), currency_hint=currency).amount is not None
    )
    return candidates[0] if len(candidates) == 1 else None


def _total_from_row(
    row: Row,
    preceding_regions: Sequence[TableRegion],
    document_currency: str | None = None,
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
    currency_inherited_from_document = False
    if len(explicit_currencies) == 1:
        currency = next(iter(explicit_currencies))
    elif not explicit_currencies and len(inferred_currencies) == 1:
        currency = next(iter(inferred_currencies))
    elif not explicit_currencies and not inferred_currencies and document_currency is not None:
        currency = document_currency
        currency_inherited_from_document = True
    else:
        currency = None
        diagnostics.append("unknown_total_currency")
    if len(explicit_currencies) > 1:
        diagnostics.append("conflicting_total_currency")
    amount_cells: list[tuple[Cell, str]] = []
    cleaned_amount_cells: list[Cell] = []
    compound_amount_cells: list[Cell] = []
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
            if parsed.amount is None and cell in label_cells:
                compound = _unique_compound_total_amount(candidate_text, currency)
                if compound is not None:
                    candidate_text = compound
                    parsed = parse_amount(candidate_text, currency_hint=currency)
                    compound_amount_cells.append(cell)
            if parsed.amount is None:
                cleaned = _without_isolated_ocr_letter(cell, candidate_text, currency)
                if cleaned is not None:
                    candidate_text = cleaned
                    parsed = parse_amount(candidate_text, currency_hint=currency)
                    cleaned_amount_cells.append(cell)
            if parsed.amount is not None:
                amount_cells.append((cell, candidate_text))
    aligned_to_billed_column = False
    if len(amount_cells) > 1:
        aligned = _amount_cells_in_nearest_billed_band(row, amount_cells, preceding_regions)
        if len(aligned) == 1:
            amount_cells = list(aligned)
            aligned_to_billed_column = True
    if len(amount_cells) != 1:
        diagnostics.append("ambiguous_total_value")
    if len(amount_cells) != 1 or currency is None:
        return None, tuple(diagnostics)
    value_cell, amount_text = amount_cells[0]
    ignored_isolated_ocr_letter = any(cell is value_cell for cell in cleaned_amount_cells)
    extracted_compound_total_amount = any(cell is value_cell for cell in compound_amount_cells)
    return (
        DiscoveredPrintedTotal(
            amount_text=amount_text,
            currency=currency,
            label_evidence=_evidence(label_cells[0]),
            value_evidence=_evidence(value_cell),
            confidence=min(row.confidence, label_cells[0].confidence, value_cell.confidence),
            diagnostics=tuple(
                (
                    *(("value_aligned_to_billed_column",) if aligned_to_billed_column else ()),
                    *(
                        ("currency_inherited_from_document",)
                        if currency_inherited_from_document
                        else ()
                    ),
                    *(("ignored_isolated_ocr_letter",) if ignored_isolated_ocr_letter else ()),
                    *(
                        ("extracted_compound_total_amount",)
                        if extracted_compound_total_amount
                        else ()
                    ),
                )
            ),
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
    if not MIN_CONTEXT_YEAR <= year <= MAX_CONTEXT_YEAR:
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
                cells.extend(cells_in_column(row.cells, column))
    return tuple(cells)


def _cross_style_year_anchors(cells: Sequence[Cell]) -> dict[int, tuple[Cell, ...]]:
    supporting: dict[int, list[Cell]] = {}
    for cell in cells:
        years: set[int] = set()
        for full_pattern in FULL_DATE_TOKEN_PATTERNS.values():
            for match in full_pattern.finditer(cell.text):
                year = int(match.group("year"))
                if not MIN_CONTEXT_YEAR <= year <= MAX_CONTEXT_YEAR:
                    continue
                try:
                    date(year, int(match.group("month")), int(match.group("day")))
                except ValueError:
                    continue
                years.add(year)
        for match in _YEAR_MONTH_TOKEN_PATTERN.finditer(cell.text):
            years.add(int(match.group("year")))
        for year in years:
            supporting.setdefault(year, []).append(cell)
    return {year: tuple(values) for year, values in supporting.items()}


def _pdf_date_metadata_anchor(
    metadata: Sequence[tuple[str, str]],
) -> tuple[int, tuple[tuple[str, str], ...]] | None:
    selected = tuple(item for item in metadata if item[0].casefold() in {"creationdate", "moddate"})
    if len(selected) != 2 or {key.casefold() for key, _ in selected} != {
        "creationdate",
        "moddate",
    }:
        return None
    parsed_dates: dict[str, date] = {}
    for key, value in selected:
        match = _PDF_METADATA_DATE_PATTERN.match(value)
        if match is None:
            return None
        year = int(match.group("year"))
        try:
            parsed_date = date(year, int(match.group("month")), int(match.group("day")))
        except ValueError:
            return None
        if not MIN_CONTEXT_YEAR <= year <= MAX_CONTEXT_YEAR:
            return None
        parsed_dates[key.casefold()] = parsed_date
    creation_date = parsed_dates["creationdate"]
    modification_date = parsed_dates["moddate"]
    if modification_date < creation_date or modification_date.year - creation_date.year > 1:
        return None
    return creation_date.year, selected


def _date_year_context(
    rows: Sequence[Row],
    regions: Sequence[TableRegion],
    metadata: Sequence[tuple[str, str]],
) -> DiscoveredDateYearContext | None:
    cells = tuple(cell for row in rows for cell in row.cells)
    table_date_cells = _table_date_cells(regions)
    table_short_years_by_style: dict[DateTokenStyle, set[int]] = {}
    table_short_months_by_style: dict[DateTokenStyle, dict[int, set[int]]] = {}
    for style, short_pattern in SHORT_DATE_TOKEN_PATTERNS.items():
        years: set[int] = set()
        months_by_year: dict[int, set[int]] = {}
        for cell in table_date_cells:
            for match in short_pattern.finditer(cell.text):
                try:
                    date(2000, int(match.group("month")), int(match.group("day")))
                except ValueError:
                    continue
                short_year = int(match.group("year"))
                years.add(short_year)
                months_by_year.setdefault(short_year, set()).add(int(match.group("month")))
        table_short_years_by_style[style] = years
        table_short_months_by_style[style] = months_by_year
    has_table_short_dates = any(table_short_years_by_style.values())
    cross_style_anchors = _cross_style_year_anchors(cells)
    pdf_date_metadata = _pdf_date_metadata_anchor(metadata)
    metadata_year = pdf_date_metadata[0] if pdf_date_metadata is not None else None
    candidates: list[
        tuple[
            DateTokenStyle,
            tuple[tuple[int, int], ...],
            tuple[Cell, ...],
            tuple[tuple[str, str], ...],
        ]
    ] = []
    for style, full_pattern in FULL_DATE_TOKEN_PATTERNS.items():
        short_pattern = SHORT_DATE_TOKEN_PATTERNS[style]
        full_years: set[int] = set(cross_style_anchors) if has_table_short_dates else set()
        if has_table_short_dates and metadata_year is not None:
            full_years.add(metadata_year)
        supporting_cells_by_year: dict[int, list[Cell]] = (
            {year: list(values) for year, values in cross_style_anchors.items()}
            if has_table_short_dates
            else {}
        )
        short_years: set[int] = set()
        for cell in cells:
            if not has_table_short_dates:
                for match in full_pattern.finditer(cell.text):
                    year = int(match.group("year"))
                    if not MIN_CONTEXT_YEAR <= year <= MAX_CONTEXT_YEAR:
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
            used_evidence_years: set[int] = set()
            for short_year in sorted(table_short_years):
                matching_years = tuple(
                    sorted(year for year in full_years if year % 100 == short_year)
                )
                candidate_evidence_years = {year: {year} for year in matching_years}
                for bracketed_year in range(MIN_CONTEXT_YEAR, MAX_CONTEXT_YEAR + 1):
                    if (
                        bracketed_year % 100 == short_year
                        and bracketed_year - 1 in full_years
                        and bracketed_year + 1 in full_years
                    ):
                        candidate_evidence_years.setdefault(bracketed_year, set()).update(
                            (bracketed_year - 1, bracketed_year + 1)
                        )
                if not candidate_evidence_years and len(table_short_years) == 2:
                    months_by_year = table_short_months_by_style[style]
                    for anchor_year in full_years:
                        anchor_suffix = anchor_year % 100
                        if anchor_suffix not in table_short_years or anchor_suffix == short_year:
                            continue
                        inferred_year: int | None = None
                        if short_year == (anchor_suffix - 1) % 100:
                            inferred_year = anchor_year - 1
                        elif short_year == (anchor_suffix + 1) % 100:
                            inferred_year = anchor_year + 1
                        if inferred_year is None or not (
                            MIN_CONTEXT_YEAR <= inferred_year <= MAX_CONTEXT_YEAR
                        ):
                            continue
                        earlier_suffix, later_suffix = (
                            (short_year, anchor_suffix)
                            if inferred_year < anchor_year
                            else (anchor_suffix, short_year)
                        )
                        earlier_months = months_by_year.get(earlier_suffix, set())
                        later_months = months_by_year.get(later_suffix, set())
                        if (
                            earlier_months
                            and later_months
                            and all(month >= 10 for month in earlier_months)
                            and all(month <= 3 for month in later_months)
                        ):
                            candidate_evidence_years.setdefault(inferred_year, set()).add(
                                anchor_year
                            )
                if len(candidate_evidence_years) != 1:
                    break
                selected_suffix_year, evidence_years = next(iter(candidate_evidence_years.items()))
                year_by_suffix.append((short_year, selected_suffix_year))
                used_evidence_years.update(evidence_years)
                for evidence_year in evidence_years:
                    for cell in supporting_cells_by_year.get(evidence_year, ()):
                        if not any(existing is cell for existing in context_supporting_cells):
                            context_supporting_cells.append(cell)
            if len(year_by_suffix) != len(table_short_years):
                continue
            if metadata_year is not None and not any(
                abs(resolved_year - metadata_year) <= 1 for _, resolved_year in year_by_suffix
            ):
                continue
            ordered_supporting_cells = tuple(
                cell
                for cell in cells
                if any(cell is supporting for supporting in context_supporting_cells)
            )
            if not ordered_supporting_cells:
                selected_suffixes = {suffix for suffix, _ in year_by_suffix}
                ordered_supporting_cells = tuple(
                    cell
                    for cell in table_date_cells
                    if any(
                        int(match.group("year")) in selected_suffixes
                        for match in short_pattern.finditer(cell.text)
                    )
                )
            selected_metadata = (
                pdf_date_metadata[1]
                if pdf_date_metadata is not None and metadata_year in used_evidence_years
                else ()
            )
            candidates.append(
                (style, tuple(year_by_suffix), ordered_supporting_cells, selected_metadata)
            )
            continue
        if len(full_years) == 1:
            year = next(iter(full_years))
            if short_years == {year % 100}:
                candidates.append(
                    (style, ((year % 100, year),), tuple(supporting_cells_by_year[year]), ())
                )
    if len(candidates) != 1:
        return None
    style, selected_year_by_suffix, supporting_cells, metadata_evidence = candidates[0]
    selected_year = selected_year_by_suffix[0][1] if len(selected_year_by_suffix) == 1 else None
    return DiscoveredDateYearContext(
        year=selected_year,
        year_by_suffix=selected_year_by_suffix,
        style=style,
        evidence=tuple(_evidence(cell) for cell in supporting_cells),
        metadata_evidence=metadata_evidence,
        confidence=statistics.mean(cell.confidence for cell in supporting_cells),
        diagnostics=("pdf_metadata_year_anchor",) if metadata_evidence else (),
    )


def _positive_form_evidence(rows: Sequence[Row]) -> bool:
    has_title = any(_contains_phrase(cell.text, _FORM_TITLES) for row in rows for cell in row.cells)
    field_count = sum(
        _contains_phrase(cell.text, _FORM_FIELDS) for row in rows for cell in row.cells
    )
    return has_title and field_count >= 2


def _positive_cancellation_correspondence_evidence(rows: Sequence[Row]) -> bool:
    return any(
        _contains_phrase(" ".join(cell.text for cell in row.cells), _CANCELLATION_PURPOSES)
        for row in rows
    )


def _positive_transaction_history_export_evidence(rows: Sequence[Row]) -> bool:
    has_title = any(
        _contains_phrase(cell.text, _TRANSACTION_HISTORY_TITLE_MARKERS)
        for row in rows
        for cell in row.cells
    )
    has_export_route = any(
        _TRANSACTION_HISTORY_ROUTE_PATTERN.search(value) is not None
        for row in rows
        for cell in row.cells
        for value in (cell.text, *(word.text for word in cell.words))
    )
    return has_title and has_export_route


def _deduplicated(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _schemas_compatible(first: TableRegion, second: TableRegion) -> bool:
    first_columns = first.table_schema.columns
    second_columns = second.table_schema.columns
    same_column_count = len(first_columns) == len(second_columns)
    columns_compatible = same_column_count and all(
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
    known_role_count = (
        sum(
            first_column.role is not ColumnRole.UNKNOWN
            for first_column, second_column in zip(first_columns, second_columns, strict=True)
            if first_column.role is second_column.role
        )
        if same_column_count
        else 0
    )
    if columns_compatible and (first_header == second_header or known_role_count >= 3):
        return True

    first_known = tuple(
        column
        for column in first_columns
        if column.role is not ColumnRole.UNKNOWN and "role_evidence:header" in column.diagnostics
    )
    second_known = tuple(
        column
        for column in second_columns
        if column.role is not ColumnRole.UNKNOWN and "role_evidence:header" in column.diagnostics
    )
    if len(first_known) < 3 or len(first_known) != len(second_known):
        return False
    if any(
        first_column.role is not second_column.role
        for first_column, second_column in zip(first_known, second_known, strict=True)
    ):
        return False

    def core_geometry(columns: Sequence[ColumnSpec]) -> tuple[tuple[float, float], ...]:
        left = min(column.bbox[0] for column in columns)
        right = max(column.bbox[2] for column in columns)
        width = right - left
        if width <= 0:
            return ()
        return tuple(
            ((column.bbox[0] - left) / width, (column.bbox[2] - left) / width) for column in columns
        )

    first_geometry = core_geometry(first_known)
    second_geometry = core_geometry(second_known)
    geometry_compatible = bool(first_geometry) and all(
        abs(first_x0 - second_x0) <= 0.08 and abs(first_x1 - second_x1) <= 0.08
        for (first_x0, first_x1), (second_x0, second_x1) in zip(
            first_geometry,
            second_geometry,
            strict=True,
        )
    )
    if geometry_compatible:
        return True

    def semantic_header_geometry(
        region: TableRegion,
        columns: Sequence[ColumnSpec],
    ) -> tuple[float, ...]:
        anchors: list[Cell] = []
        for column in columns:
            associated = tuple(
                cell for cell in region.table_schema.header_cells if cell in column.source_cells
            )
            if len(associated) != 1:
                return ()
            anchors.append(associated[0])
        left = min(anchor.bbox[0] for anchor in anchors)
        right = max(anchor.bbox[2] for anchor in anchors)
        width = right - left
        if width <= 0:
            return ()
        return tuple((_center_x(anchor.bbox) - left) / width for anchor in anchors)

    first_header_geometry = semantic_header_geometry(first, first_known)
    second_header_geometry = semantic_header_geometry(second, second_known)
    return bool(first_header_geometry) and all(
        abs(first_anchor - second_anchor) <= 0.05
        for first_anchor, second_anchor in zip(
            first_header_geometry,
            second_header_geometry,
            strict=True,
        )
    )


def _has_explicit_continuation_heading(
    region: TableRegion,
    rows: Sequence[Row],
    page_height: float,
) -> bool:
    return any(
        cell.bbox[3] <= region.header.bbox[1]
        and region.header.bbox[1] - cell.bbox[3] <= page_height * 0.12
        and _contains_phrase(cell.text, _CONTINUATION_HEADING_MARKERS)
        for row in rows
        for cell in row.cells
    )


def _proven_page_continuation(
    regions: Sequence[TableRegion],
    page_heights: Mapping[int, float],
    page_rows: Mapping[int, Sequence[Row]],
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
        has_edge_continuation = previous.bbox[3] >= previous_height * 0.75
        has_explicit_heading = _has_explicit_continuation_heading(
            following,
            page_rows.get(following.page_number, ()),
            following_height,
        )
        if not has_edge_continuation and not has_explicit_heading:
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
    page_rows: Mapping[int, Sequence[Row]],
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
    section_currencies_match = all(
        _table_matches_total_currency(region, total.currency) for region in section
    )
    if len(section) == 1:
        if not section_currencies_match:
            return (), ("ambiguous_table_currency",)
        return section, ()
    if section_currencies_match and _proven_page_continuation(
        section,
        page_heights,
        page_rows,
    ):
        return section, ()
    same_page = tuple(region for region in section if region.page_number == total_row.page_number)
    compatible_same_page_candidate = (
        len(same_page) == 1
        and same_page[0] is section[-1]
        and _table_matches_total_currency(same_page[0], total.currency)
    )
    if (
        compatible_same_page_candidate
        and sum(
            candidate.currency == total.currency
            and candidate.label_evidence.page_number == total_row.page_number
            for candidate in remaining_totals
        )
        == 1
    ):
        return same_page, ()
    if not section_currencies_match:
        return (), ("ambiguous_table_currency",)
    return (), ("ambiguous_group_region_association",)


def _region_billed_amounts(
    region: TableRegion,
    currency: str,
) -> tuple[Decimal, ...] | None:
    billed_column = proven_billed_amount_column(region.table_schema, region.rows)
    if billed_column is None:
        return None
    amounts: list[Decimal] = []
    for row in region.rows:
        if is_structural_continuation(row):
            continue
        cells = tuple(
            cell
            for cell in row.cells
            if billed_column.bbox[0] <= _center_x(cell.bbox) <= billed_column.bbox[2]
        )
        if len(cells) != 1:
            return None
        parsed = parse_amount(cells[0].text, currency_hint=currency)
        if parsed.amount is None or parsed.currency != currency:
            return None
        if parsed.amount:
            amounts.append(parsed.amount)
    return tuple(amounts)


def _attach_exact_singleton_regions(
    groups: Sequence[StatementGroupDiscovery],
    candidates: Sequence[TableRegion],
) -> tuple[tuple[StatementGroupDiscovery, ...], tuple[TableRegion, ...]]:
    def compatible(existing: TableRegion, candidate: TableRegion) -> bool:
        if _schemas_compatible(existing, candidate):
            return True
        anchor_pairs = []
        for role in (ColumnRole.AMOUNT, ColumnRole.DATE):
            existing_columns = tuple(
                column for column in existing.table_schema.columns if column.role is role
            )
            candidate_columns = tuple(
                column for column in candidate.table_schema.columns if column.role is role
            )
            if len(existing_columns) != 1 or len(candidate_columns) != 1:
                return False
            anchor_pairs.append((existing_columns[0], candidate_columns[0]))
        return all(
            abs(
                _center_x(existing_column.bbox) / max(existing.header.bbox[2], 1.0)
                - _center_x(candidate_column.bbox) / max(candidate.header.bbox[2], 1.0)
            )
            <= 0.1
            for existing_column, candidate_column in anchor_pairs
        )

    matches: list[tuple[int, int]] = []
    for group_index, group in enumerate(groups):
        total = parse_amount(
            group.printed_total.amount_text,
            currency_hint=group.printed_total.currency,
        )
        if total.amount is None or total.currency != group.printed_total.currency:
            continue
        existing_amount_groups = tuple(
            _region_billed_amounts(region, group.printed_total.currency)
            for region in group.table_regions
        )
        if any(amounts is None for amounts in existing_amount_groups):
            continue
        calculated = exact_sum(
            amount
            for amounts in existing_amount_groups
            if amounts is not None
            for amount in amounts
        )
        missing = exact_difference(total.amount, calculated)
        for candidate_index, candidate in enumerate(candidates):
            if not any(compatible(region, candidate) for region in group.table_regions):
                continue
            candidate_amounts = _region_billed_amounts(
                candidate,
                group.printed_total.currency,
            )
            if (
                candidate_amounts is not None
                and len(candidate_amounts) == 1
                and candidate_amounts[0] == missing
            ):
                matches.append((group_index, candidate_index))
    unique_matches = tuple(
        match
        for match in matches
        if sum(other[0] == match[0] for other in matches) == 1
        and sum(other[1] == match[1] for other in matches) == 1
    )
    attached: list[TableRegion] = []
    updated = list(groups)
    for group_index, candidate_index in unique_matches:
        group = updated[group_index]
        candidate = candidates[candidate_index]
        attached.append(candidate)
        updated[group_index] = group.model_copy(
            update={
                "table_regions": (*group.table_regions, candidate),
                "confidence": statistics.mean((group.confidence, candidate.confidence)),
                "diagnostics": _deduplicated(
                    (*group.diagnostics, "exact_singleton_reconciliation")
                ),
            }
        )
    return tuple(updated), tuple(attached)


def _is_duplicate_group_summary_label(
    row: Row,
    groups: Sequence[StatementGroupDiscovery],
    page_rows: Sequence[Row],
    page_height: float,
) -> bool:
    same_page_regions = tuple(
        region
        for group in groups
        for region in group.table_regions
        if region.page_number == row.page_number
    )
    if not same_page_regions or any(region.bbox[1] <= row.bbox[3] for region in same_page_regions):
        return False
    group_totals = {
        parsed.amount
        for group in groups
        if (
            parsed := parse_amount(
                group.printed_total.amount_text,
                currency_hint=group.printed_total.currency,
            )
        ).amount
        is not None
    }
    if not group_totals:
        return False
    candidates: set[Decimal] = set()
    for following in page_rows:
        if following.page_number != row.page_number or following.bbox[1] <= row.bbox[3]:
            continue
        if following.bbox[1] - row.bbox[3] > page_height * 0.2:
            break
        if _literal_header_role_count(following) >= 2:
            break
        for cell in following.cells:
            for value in (cell.text, *(word.text for word in cell.words)):
                if not (currencies_in_text(value) or re.search(r"\d[.,]\d{2}(?!\d)", value)):
                    continue
                parsed_values = {
                    parsed.amount
                    for group in groups
                    if (
                        parsed := parse_amount(
                            value,
                            currency_hint=group.printed_total.currency,
                        )
                    ).amount
                    is not None
                    and parsed.currency == group.printed_total.currency
                    and parsed.amount in group_totals
                }
                candidates.update(parsed_values)
    return len(candidates) == 1 and next(iter(candidates)) in group_totals


def _is_noncontributing_zero_summary(
    row: Row,
    total: DiscoveredPrintedTotal,
    groups: Sequence[StatementGroupDiscovery],
) -> bool:
    parsed = parse_amount(total.amount_text, currency_hint=total.currency)
    if parsed.amount != 0 or parsed.currency != total.currency:
        return False
    row_key = _reading_key_bbox(row.page_number, row.bbox)
    matching_regions = tuple(
        region
        for group in groups
        if group.printed_total.currency == total.currency
        for region in group.table_regions
    )
    return any(
        _reading_key_bbox(region.page_number, region.bbox) < row_key for region in matching_regions
    ) and any(
        _reading_key_bbox(region.page_number, region.bbox) > row_key for region in matching_regions
    )


def discover_statement(evidence: DocumentEvidence) -> StatementDiscovery:
    """Discover statement groups and classify only from positive semantic evidence."""

    ordered_pages = tuple(sorted(evidence.pages, key=lambda item: item.page_number))
    logical_rows_by_page = {page.page_number: logical_rows(page) for page in ordered_pages}
    merged_rows_by_page = {
        page.page_number: _merged_header_bands(logical_rows_by_page[page.page_number])
        for page in ordered_pages
    }
    page_rows = tuple(
        row for page in ordered_pages for row in logical_rows_by_page[page.page_number]
    )
    initial_regions_by_page = {
        page.page_number: _detect_table_regions_from_rows(
            page,
            merged_rows_by_page[page.page_number],
        )
        for page in ordered_pages
    }
    initial_regions = tuple(
        sorted(
            (
                region
                for page in ordered_pages
                for region in initial_regions_by_page[page.page_number]
            ),
            key=lambda region: _reading_key_bbox(region.page_number, region.bbox),
        )
    )
    observed_total_marker_rows = tuple(
        row
        for row in page_rows
        if any(_contains_phrase(cell.text, _TOTAL_MARKERS) for cell in row.cells)
    )
    proven_total_overlay_keys = frozenset(
        _page_row_key(row)
        for row in observed_total_marker_rows
        if _is_lossless_total_overlay_artifact(
            row,
            observed_total_marker_rows,
            initial_regions,
        )
    )
    affected_pages = frozenset(row.page_number for row in proven_total_overlay_keys)
    regions = tuple(
        sorted(
            (
                region
                for page in ordered_pages
                for region in (
                    _detect_table_regions_from_rows(
                        page,
                        merged_rows_by_page[page.page_number],
                        proven_total_overlay_keys,
                    )
                    if page.page_number in affected_pages
                    else initial_regions_by_page[page.page_number]
                )
            ),
            key=lambda region: _reading_key_bbox(region.page_number, region.bbox),
        )
    )
    provisional_date_year_context = _date_year_context(
        page_rows,
        regions,
        evidence.metadata,
    )
    future_regions = tuple(
        region for region in regions if _is_future_billing_region(region, page_rows)
    )
    regions = tuple(region for region in regions if region not in future_regions)
    singleton_candidates = tuple(
        candidate
        for page in ordered_pages
        for candidate in _singleton_transaction_candidates(
            page,
            tuple(region for region in regions if region.page_number == page.page_number),
        )
        if not _is_future_billing_region(candidate, page_rows)
    )
    total_marker_rows = tuple(
        row
        for row in observed_total_marker_rows
        if _page_row_key(row) not in proven_total_overlay_keys
        and not _is_future_billing_total(
            row,
            future_regions,
            regions,
            page_rows,
            provisional_date_year_context,
        )
        and not _is_points_ledger_total(row, page_rows, regions)
        and not _is_rate_ledger_total(row, page_rows, regions)
        and not _is_fee_tax_summary_total(row, page_rows)
    )
    observed_document_currencies = {
        currency
        for row in total_marker_rows
        for cell in row.cells
        for currency in currencies_in_text(cell.text)
    } | {currency for region in regions for currency in _table_currencies(region)}
    document_currency = (
        next(iter(observed_document_currencies)) if len(observed_document_currencies) == 1 else None
    )
    groups: list[StatementGroupDiscovery] = []
    diagnostics: list[str] = []
    rejected_total_rows: list[tuple[Row, RejectedTotalCandidate]] = []
    unassociated_total_rows: list[tuple[Row, DiscoveredPrintedTotal, tuple[str, ...]]] = []
    standalone_total_candidates: list[tuple[Row, DiscoveredPrintedTotal]] = []
    total_candidates: list[tuple[Row, DiscoveredPrintedTotal]] = []
    for total_row in total_marker_rows:
        preceding = tuple(
            region
            for region in regions
            if _reading_key_bbox(region.page_number, region.bbox)
            < _reading_key_bbox(total_row.page_number, total_row.bbox)
        )
        total, total_diagnostics = _total_from_row(
            total_row,
            preceding,
            document_currency,
        )
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
        if total is not None:
            standalone_total_candidates.append((total_row, total))
            if preceding:
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
            page_rows=logical_rows_by_page,
        )
        previous_total_row = total_row
        if not associated:
            unassociated_total_rows.append((total_row, total, association_diagnostics))
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

    zero_activity_cell = _positive_zero_activity_evidence(page_rows)
    if (
        not groups
        and not regions
        and zero_activity_cell is not None
        and len(standalone_total_candidates) == 1
    ):
        _, zero_total = standalone_total_candidates[0]
        parsed_zero_total = parse_amount(
            zero_total.amount_text,
            currency_hint=zero_total.currency,
        )
        if parsed_zero_total.amount == 0 and parsed_zero_total.currency == zero_total.currency:
            groups.append(
                StatementGroupDiscovery(
                    group_id="group-0001",
                    table_regions=(),
                    printed_total=zero_total,
                    confidence=statistics.mean(
                        (zero_total.confidence, zero_activity_cell.confidence)
                    ),
                    diagnostics=("explicit_zero_activity",),
                )
            )

    groups_tuple, attached_singletons = _attach_exact_singleton_regions(
        groups,
        singleton_candidates,
    )
    groups = list(groups_tuple)
    if attached_singletons:
        regions = tuple(
            sorted(
                (*regions, *attached_singletons),
                key=lambda region: _reading_key_bbox(region.page_number, region.bbox),
            )
        )

    for total_row, total, association_diagnostics in unassociated_total_rows:
        if association_diagnostics == ("total_without_table",) and (
            _is_noncontributing_zero_summary(total_row, total, groups)
        ):
            rejected_total_rows.append(
                (
                    total_row,
                    RejectedTotalCandidate(
                        evidence=tuple(_evidence(cell) for cell in total_row.cells),
                        confidence=statistics.mean(cell.confidence for cell in total_row.cells),
                        diagnostics=("noncontributing_zero_summary",),
                    ),
                )
            )
            continue
        diagnostics.extend(association_diagnostics)
    rejected_total_rows.sort(key=lambda item: _reading_key_bbox(item[0].page_number, item[0].bbox))

    resolved_rejected_total_rows: list[tuple[Row, RejectedTotalCandidate]] = []
    for rejected_row, candidate in rejected_total_rows:
        if candidate.diagnostics == ("noncontributing_zero_summary",):
            pass
        elif "ambiguous_total_value" in candidate.diagnostics and _is_duplicate_group_summary_label(
            rejected_row,
            groups,
            logical_rows_by_page[rejected_row.page_number],
            page_heights[rejected_row.page_number],
        ):
            candidate = candidate.model_copy(
                update={"diagnostics": ("duplicate_group_summary_label",)}
            )
        else:
            diagnostics.extend(candidate.diagnostics)
        resolved_rejected_total_rows.append((rejected_row, candidate))
    rejected_total_rows = resolved_rejected_total_rows

    claimed_regions = tuple(region for group in groups for region in group.table_regions)
    if any(not any(region is claimed for claimed in claimed_regions) for region in regions):
        diagnostics.append("unclaimed_table_region")

    metadata = {field_name: _metadata_field(page_rows, field_name) for field_name in _FIELD_LABELS}
    date_year_context = _date_year_context(page_rows, regions, evidence.metadata)
    if _positive_transaction_history_export_evidence(page_rows):
        classification = DocumentClassification.NOT_STATEMENT
        confidence = 0.98
        reason_codes = ("positive_non_statement_transaction_history_evidence",)
        groups = []
        regions = ()
        rejected_total_rows = []
        diagnostics = []
    elif groups:
        classification = DocumentClassification.STATEMENT
        confidence = statistics.mean(group.confidence for group in groups)
        reason_codes = (
            ("zero_activity_statement_with_compatible_total",)
            if all(not group.table_regions for group in groups)
            else ("transaction_table_with_compatible_total",)
        )
    elif not regions and not total_marker_rows and _positive_form_evidence(page_rows):
        classification = DocumentClassification.NOT_STATEMENT
        confidence = 0.95
        reason_codes = ("positive_non_statement_form_evidence",)
    elif (
        not regions
        and not observed_total_marker_rows
        and not rejected_total_rows
        and _positive_cancellation_correspondence_evidence(page_rows)
    ):
        classification = DocumentClassification.NOT_STATEMENT
        confidence = 0.95
        reason_codes = ("positive_non_statement_cancellation_evidence",)
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
