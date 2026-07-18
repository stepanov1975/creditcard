"""Positive-evidence statement discovery over glyph-corrected logical rows."""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections.abc import Iterable, Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ccparser.evidence.models import BBox, DocumentEvidence
from ccparser.layout import TableRegion, detect_table_regions, logical_rows
from ccparser.layout.models import Cell, Row
from ccparser.models import EvidenceReference


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
_CURRENCY_ALIASES = {
    "₪": "ILS",
    "ILS": "ILS",
    "NIS": "ILS",
    "שח": "ILS",
    "ש ח": "ILS",
    "$": "USD",
    "USD": "USD",
    "€": "EUR",
    "EUR": "EUR",
    "£": "GBP",
    "GBP": "GBP",
    "JPY": "JPY",
    "CHF": "CHF",
    "AUD": "AUD",
    "CAD": "CAD",
}
_CURRENCY_PATTERN = re.compile(
    r"(?<![A-Z])(?:ILS|NIS|USD|EUR|GBP|JPY|CHF|AUD|CAD)(?![A-Z])|[₪$€£]|ש[\s\"״']*ח",
    re.IGNORECASE,
)
_AMOUNT_PATTERN = re.compile(
    r"(?<![\d])(?:[₪$€£]\s*)?(?:[-+]?\s*|\(\s*)"
    r"(?:\d{1,3}(?:[ ,.']\d{3})+|\d+)(?:[.,]\d{1,3})?"
    r"(?:\s*(?:ILS|NIS|USD|EUR|GBP|JPY|CHF|AUD|CAD|[₪$€£]))?\s*\)?(?![\d])",
    re.IGNORECASE,
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


def _currency_tokens(text: str) -> tuple[str, ...]:
    currencies: list[str] = []
    for match in _CURRENCY_PATTERN.finditer(unicodedata.normalize("NFC", text)):
        normalized = _normalized_phrase(match.group()).upper()
        key = match.group() if match.group() in _CURRENCY_ALIASES else normalized
        currency = _CURRENCY_ALIASES.get(key)
        if currency is not None and currency not in currencies:
            currencies.append(currency)
    return tuple(currencies)


def _amount_matches(text: str) -> tuple[str, ...]:
    return tuple(match.group().strip() for match in _AMOUNT_PATTERN.finditer(text))


def _table_currency(region: TableRegion) -> str | None:
    currencies = {
        currency
        for row in region.rows
        for cell in row.cells
        for currency in _currency_tokens(cell.text)
    }
    return next(iter(currencies)) if len(currencies) == 1 else None


def _reading_key_bbox(page_number: int, bbox: BBox) -> tuple[int, float, float]:
    return (page_number, bbox[1], bbox[0])


def _total_from_row(
    row: Row,
    preceding_regions: Sequence[TableRegion],
) -> tuple[DiscoveredPrintedTotal | None, tuple[str, ...]]:
    label_cells = tuple(cell for cell in row.cells if _contains_phrase(cell.text, _TOTAL_MARKERS))
    if not label_cells:
        return None, ()
    amount_cells: list[tuple[Cell, str]] = []
    for cell in row.cells:
        matches = _amount_matches(cell.text)
        amount_cells.extend((cell, match) for match in matches)
    diagnostics: list[str] = []
    if len(amount_cells) != 1:
        diagnostics.append("ambiguous_total_value")

    explicit_currencies = {
        currency for cell in row.cells for currency in _currency_tokens(cell.text)
    }
    inferred_currencies = {
        currency
        for region in preceding_regions
        for currency in (_table_currency(region),)
        if currency is not None
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
    used_region_indexes: set[int] = set()
    groups: list[StatementGroupDiscovery] = []
    diagnostics: list[str] = []
    for total_row in total_marker_rows:
        preceding = tuple(
            region
            for index, region in enumerate(regions)
            if index not in used_region_indexes
            and _reading_key_bbox(region.page_number, region.bbox)
            < _reading_key_bbox(total_row.page_number, total_row.bbox)
        )
        total, total_diagnostics = _total_from_row(total_row, preceding)
        diagnostics.extend(total_diagnostics)
        if total is None or not preceding:
            continue
        compatible = tuple(
            region for region in preceding if _table_currency(region) in {None, total.currency}
        )
        if not compatible:
            diagnostics.append("total_without_compatible_table")
            continue
        group_id = f"group-{len(groups) + 1:04d}"
        confidence = statistics.mean(
            (total.confidence, *(region.confidence for region in compatible))
        )
        groups.append(
            StatementGroupDiscovery(
                group_id=group_id,
                table_regions=compatible,
                printed_total=total,
                confidence=confidence,
            )
        )
        used_region_indexes.update(regions.index(region) for region in compatible)

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
