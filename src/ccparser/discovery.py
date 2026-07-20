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
from ccparser.layout import TableRegion, logical_rows
from ccparser.layout.columns import (
    explicit_billed_amount_column,
    infer_column_roles,
    proven_billed_amount_column,
)
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row
from ccparser.layout.regions import (
    _detect_table_regions_from_rows,
    _merged_header_bands,
    _page_row_key,
)
from ccparser.layout.text import logical_text_for_evidence
from ccparser.models import EvidenceReference
from ccparser.money import canonical_currency, currencies_in_text, is_money_shaped, parse_amount


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
    metadata_evidence: tuple[tuple[str, str], ...] = ()
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
_YEAR_MONTH_TOKEN_PATTERN = re.compile(
    r"(?<!\d)(?P<year>(?:19|20)\d{2})\s*[/\-]\s*"
    r"(?P<month>0?[1-9]|1[0-2])(?!\s*[/\-]\s*\d)(?!\d)"
)
_PDF_METADATA_DATE_PATTERN = re.compile(r"^D:(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})")
_COMPOUND_TOTAL_AMOUNT_PATTERN = re.compile(
    r"(?<![\d.,])(?P<amount>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)[.,]\d{2}-?)"
)


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
        phrase_tokens = _normalized_phrase(phrase).split()
        length = len(phrase_tokens)
        if any(tokens[index : index + length] == phrase_tokens for index in range(len(tokens))):
            return True
        compact_phrase = "".join(phrase_tokens)
        if len(phrase_tokens) > 1 and compact_phrase in tokens:
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
) -> bool:
    preceding = tuple(
        region
        for region in (*future_regions, *current_regions)
        if region.page_number == candidate.page_number and region.bbox[3] <= candidate.bbox[1]
    )
    if not preceding:
        return False
    nearest = max(preceding, key=lambda region: _reading_key_bbox(region.page_number, region.bbox))
    return any(nearest is region for region in future_regions)


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
        cells = tuple(
            cell
            for cell in row.cells
            if proven_column.bbox[0] <= (cell.bbox[0] + cell.bbox[2]) / 2 <= proven_column.bbox[2]
        )
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
            gap_scale = max(_row_height(previous), _row_height(row))
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
                tuple(word.text for word in row.words)
                or tuple(cell.text for cell in row.cells)
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
    candidate_indices = tuple(
        index for index, row in enumerate(summary_rows) if row is candidate
    )
    if len(candidate_indices) == 1:
        start = candidate_indices[0]
        end = start
        while start > 0 and _vertical_gap(
            summary_rows[start - 1].bbox, summary_rows[start].bbox
        ) <= max(_row_height(summary_rows[start - 1]), _row_height(summary_rows[start])) * 2:
            start -= 1
        while end + 1 < len(summary_rows) and _vertical_gap(
            summary_rows[end].bbox, summary_rows[end + 1].bbox
        ) <= max(_row_height(summary_rows[end]), _row_height(summary_rows[end + 1])) * 2:
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
    return (
        explicit_fee_tax_summary
        or explicit_paid_fee_summary
        or multiline_fee_tax_summary
    )


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
        if "subordinate_detail_continuation" not in candidate.diagnostics
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


def _cross_style_year_anchors(cells: Sequence[Cell]) -> dict[int, tuple[Cell, ...]]:
    supporting: dict[int, list[Cell]] = {}
    for cell in cells:
        years: set[int] = set()
        for full_pattern in _FULL_DATE_TOKEN_PATTERNS.values():
            for match in full_pattern.finditer(cell.text):
                year = int(match.group("year"))
                if not _MIN_CONTEXT_YEAR <= year <= _MAX_CONTEXT_YEAR:
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
        if not _MIN_CONTEXT_YEAR <= year <= _MAX_CONTEXT_YEAR:
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
    for style, short_pattern in _SHORT_DATE_TOKEN_PATTERNS.items():
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
    for style, full_pattern in _FULL_DATE_TOKEN_PATTERNS.items():
        short_pattern = _SHORT_DATE_TOKEN_PATTERNS[style]
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
            used_evidence_years: set[int] = set()
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
                            _MIN_CONTEXT_YEAR <= inferred_year <= _MAX_CONTEXT_YEAR
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
    return bool(first_geometry) and all(
        abs(first_x0 - second_x0) <= 0.08 and abs(first_x1 - second_x1) <= 0.08
        for (first_x0, first_x1), (second_x0, second_x1) in zip(
            first_geometry,
            second_geometry,
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
    future_regions = tuple(
        region for region in regions if _is_future_billing_region(region, page_rows)
    )
    regions = tuple(region for region in regions if region not in future_regions)
    total_marker_rows = tuple(
        row
        for row in observed_total_marker_rows
        if _page_row_key(row) not in proven_total_overlay_keys
        and not _is_future_billing_total(row, future_regions, regions)
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

    claimed_regions = tuple(region for group in groups for region in group.table_regions)
    if any(not any(region is claimed for claimed in claimed_regions) for region in regions):
        diagnostics.append("unclaimed_table_region")

    metadata = {field_name: _metadata_field(page_rows, field_name) for field_name in _FIELD_LABELS}
    date_year_context = _date_year_context(page_rows, regions, evidence.metadata)
    diagnostics.extend(
        diagnostic for _, candidate in rejected_total_rows for diagnostic in candidate.diagnostics
    )
    if groups:
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
