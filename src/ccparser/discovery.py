"""Positive-evidence statement discovery over glyph-corrected logical rows."""

from __future__ import annotations

import statistics
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from itertools import pairwise

from pydantic import BaseModel, ConfigDict, Field

from ccparser.evidence.models import BBox, DocumentEvidence
from ccparser.layout import TableRegion, detect_table_regions, logical_rows
from ccparser.layout.models import Cell, ColumnRole, Row
from ccparser.models import EvidenceReference
from ccparser.money import currencies_in_text, parse_amount


class _ImmutableDiscoveryModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


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
    billing_columns = tuple(
        column for column in region.table_schema.columns if column.role in billing_roles
    )
    currencies = {
        currency
        for row in region.rows
        for column in billing_columns
        for cell in row.cells
        if column.bbox[0] <= (cell.bbox[0] + cell.bbox[2]) / 2 <= column.bbox[2]
        for currency in currencies_in_text(cell.text)
    }
    return tuple(sorted(currencies))


def _reading_key_bbox(page_number: int, bbox: BBox) -> tuple[int, float, float]:
    return (page_number, bbox[1], bbox[0])


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
    return columns_compatible and first_header == second_header


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
    total_marker_rows = tuple(
        row
        for row in page_rows
        if any(_contains_phrase(cell.text, _TOTAL_MARKERS) for cell in row.cells)
    )
    groups: list[StatementGroupDiscovery] = []
    diagnostics: list[str] = []
    total_candidates: list[tuple[Row, DiscoveredPrintedTotal]] = []
    for total_row in total_marker_rows:
        preceding = tuple(
            region
            for region in regions
            if _reading_key_bbox(region.page_number, region.bbox)
            < _reading_key_bbox(total_row.page_number, total_row.bbox)
        )
        total, total_diagnostics = _total_from_row(total_row, preceding)
        diagnostics.extend(total_diagnostics)
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

    metadata = {field_name: _metadata_field(page_rows, field_name) for field_name in _FIELD_LABELS}
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
        confidence=confidence,
        reason_codes=reason_codes,
        diagnostics=_deduplicated(diagnostics),
    )


__all__ = [
    "DiscoveredField",
    "DiscoveredPrintedTotal",
    "DocumentClassification",
    "StatementDiscovery",
    "StatementGroupDiscovery",
    "discover_statement",
]
