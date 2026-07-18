"""Pure monetary parsing and geometry-driven transaction normalization."""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field

from ccparser.discovery import StatementDiscovery, StatementGroupDiscovery
from ccparser.evidence.models import BBox
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableRegion
from ccparser.models import (
    EvidenceReference,
    PrintedTotal,
    StatementResult,
    Status,
    Transaction,
    TransactionCategory,
    TransactionKind,
)
from ccparser.reconcile import reconcile


class _ImmutableNormalizationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AmountParseResult(_ImmutableNormalizationModel):
    """A monetary parse or explicit ambiguity without a guessed value."""

    raw_text: str
    amount: Decimal | None = None
    currency: str | None = None
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()


class RowNormalizationResult(_ImmutableNormalizationModel):
    """One source-row outcome with raw local evidence and explicit diagnostics."""

    page_number: int = Field(gt=0)
    bbox: BBox
    raw_text: str
    evidence: tuple[EvidenceReference, ...]
    transaction: Transaction | None = None
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()


class StatementNormalization(_ImmutableNormalizationModel):
    """Normalized transactions, totals, and exact reconciliation outcome."""

    discovery: StatementDiscovery
    transactions: tuple[Transaction, ...]
    printed_totals: tuple[PrintedTotal, ...]
    row_results: tuple[RowNormalizationResult, ...]
    reconciliation: StatementResult
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()


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
_CREDIT_MARKERS = (
    "credit",
    "credited",
    "refund",
    "refunded",
    "זיכוי",
    "החזר",
)
_CHARGE_MARKERS = ("charge", "charged", "debit", "חיוב")
_CATEGORY_VOCABULARY: tuple[tuple[TransactionCategory, tuple[str, ...]], ...] = (
    (TransactionCategory.REFUND, ("credit", "refund", "זיכוי", "החזר")),
    (TransactionCategory.INTEREST, ("interest", "ריבית")),
    (TransactionCategory.FEE, ("commission", "fee", "עמלה", "דמי")),
    (TransactionCategory.ADJUSTMENT, ("adjustment", "correction", "התאמה", "תיקון")),
)
_DATE_PATTERN = re.compile(r"^(\d{1,4})\s*([./-])\s*(\d{1,2})\s*\2\s*(\d{1,4})$")
_INSTALLMENT_PATTERN = re.compile(r"^(\d{1,3})\s*/\s*(\d{1,3})$")


def _normalized_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def _normalized_phrase(text: str) -> str:
    normalized = _normalized_text(text).casefold()
    return " ".join("".join(char if char.isalnum() else " " for char in normalized).split())


def _contains_marker(text: str, markers: Iterable[str]) -> bool:
    tokens = _normalized_phrase(text).split()
    return any(
        marker.split() == tokens[index : index + len(marker.split())]
        for marker in markers
        for index in range(len(tokens))
    )


def _remove_markers(text: str, markers: Iterable[str]) -> str:
    result = text
    for marker in sorted(markers, key=len, reverse=True):
        result = re.sub(
            rf"(?<!\w){re.escape(marker).replace(r'\ ', r'\s+')}(?!\w)",
            " ",
            result,
            flags=re.IGNORECASE,
        )
    return result


def _canonical_currency(value: str) -> str | None:
    stripped = _normalized_text(value)
    if stripped in _CURRENCY_ALIASES:
        return _CURRENCY_ALIASES[stripped]
    normalized_phrase = _normalized_phrase(stripped).upper()
    return _CURRENCY_ALIASES.get(stripped.upper()) or _CURRENCY_ALIASES.get(normalized_phrase)


def _currencies(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for match in _CURRENCY_PATTERN.finditer(text):
        currency = _canonical_currency(match.group())
        if currency is not None and currency not in found:
            found.append(currency)
    return tuple(found)


def _validate_grouped_integer(value: str, separator: str) -> str | None:
    groups = value.split(separator)
    if not groups or not 1 <= len(groups[0]) <= 3 or not all(group.isdigit() for group in groups):
        return None
    if any(len(group) != 3 for group in groups[1:]):
        return None
    return "".join(groups)


def _canonical_number(text: str) -> tuple[str | None, str | None]:
    compact = text.strip()
    if not compact:
        return None, "invalid_amount_text"
    if re.search(r"[^\d.,'\s]", compact):
        return None, "invalid_amount_text"
    if " " in compact or "'" in compact:
        space_normalized = re.sub(r"\s+", " ", compact.replace("'", " ")).strip()
        integer_part = re.split(r"[.,]", space_normalized, maxsplit=1)[0]
        if " " in integer_part and _validate_grouped_integer(integer_part, " ") is None:
            return None, "invalid_grouping_separator"
        compact = space_normalized.replace(" ", "")

    comma_count = compact.count(",")
    dot_count = compact.count(".")
    if comma_count and dot_count:
        decimal_separator = "," if compact.rfind(",") > compact.rfind(".") else "."
        grouping_separator = "." if decimal_separator == "," else ","
        integer, fraction = compact.rsplit(decimal_separator, 1)
        if not 1 <= len(fraction) <= 2 or not fraction.isdigit():
            return None, "ambiguous_decimal_separator"
        grouped = _validate_grouped_integer(integer, grouping_separator)
        if grouped is None:
            return None, "invalid_grouping_separator"
        return f"{grouped}.{fraction}", None

    separator = "," if comma_count else "." if dot_count else None
    if separator is None:
        return (compact, None) if compact.isdigit() else (None, "invalid_amount_text")
    count = compact.count(separator)
    if count > 1:
        grouped = _validate_grouped_integer(compact, separator)
        return (grouped, None) if grouped is not None else (None, "invalid_grouping_separator")
    integer, fraction = compact.split(separator)
    if not integer.isdigit() or not fraction.isdigit():
        return None, "invalid_amount_text"
    if len(fraction) == 3:
        return None, "ambiguous_decimal_separator"
    if not 1 <= len(fraction) <= 2:
        return None, "invalid_decimal_separator"
    return f"{integer}.{fraction}", None


def parse_amount(text: str, *, currency_hint: str | None = None) -> AmountParseResult:
    """Parse an unambiguous monetary string exactly, or return typed diagnostics."""

    raw_text = unicodedata.normalize("NFC", text)
    diagnostics: list[str] = []
    explicit_currencies = _currencies(raw_text)
    hint = _canonical_currency(currency_hint) if currency_hint is not None else None
    if currency_hint is not None and hint is None:
        diagnostics.append("unknown_currency_hint")
    if len(explicit_currencies) > 1:
        diagnostics.append("conflicting_currency")
    explicit_currency = explicit_currencies[0] if len(explicit_currencies) == 1 else None
    if explicit_currency is not None and hint is not None and explicit_currency != hint:
        diagnostics.append("currency_hint_conflict")
    currency = explicit_currency or hint
    if currency is None and "conflicting_currency" not in diagnostics:
        diagnostics.append("unknown_currency")

    credit_marker = _contains_marker(raw_text, _CREDIT_MARKERS)
    charge_marker = _contains_marker(raw_text, _CHARGE_MARKERS)
    if credit_marker and charge_marker:
        diagnostics.append("conflicting_sign_marker")
    without_semantics = _remove_markers(raw_text, (*_CREDIT_MARKERS, *_CHARGE_MARKERS))
    without_currency = _CURRENCY_PATTERN.sub(" ", without_semantics).strip()
    parenthesized = without_currency.startswith("(") and without_currency.endswith(")")
    sign_text = without_currency[1:-1].strip() if parenthesized else without_currency
    negative_sign = parenthesized or sign_text.startswith("-") or sign_text.endswith("-")
    positive_sign = sign_text.startswith("+") or sign_text.endswith("+")
    if negative_sign and positive_sign:
        diagnostics.append("conflicting_sign_marker")
    if (negative_sign and charge_marker) or (positive_sign and credit_marker):
        diagnostics.append("conflicting_sign_marker")
    numeric_text = sign_text.strip("+- ")
    canonical, numeric_diagnostic = _canonical_number(numeric_text)
    if numeric_diagnostic is not None:
        diagnostics.append(numeric_diagnostic)

    diagnostics = list(dict.fromkeys(diagnostics))
    if diagnostics or canonical is None or currency is None:
        return AmountParseResult(
            raw_text=raw_text,
            currency=currency if "conflicting_currency" not in diagnostics else None,
            confidence=0.0,
            diagnostics=tuple(diagnostics),
        )
    try:
        unsigned = Decimal(canonical)
    except InvalidOperation:
        return AmountParseResult(
            raw_text=raw_text,
            currency=currency,
            confidence=0.0,
            diagnostics=("invalid_amount_text",),
        )
    negative = negative_sign or credit_marker
    amount = unsigned.copy_negate() if negative else unsigned
    confidence = 1.0 if explicit_currency is not None else 0.95
    return AmountParseResult(
        raw_text=raw_text,
        amount=amount,
        currency=currency,
        confidence=confidence,
    )


def _center_x(bbox: BBox) -> float:
    return (bbox[0] + bbox[2]) / 2


def _height(bbox: BBox) -> float:
    return max(0.0, bbox[3] - bbox[1])


def _cells_for_column(row: Row, column: ColumnSpec) -> tuple[Cell, ...]:
    return tuple(
        cell for cell in row.cells if column.bbox[0] <= _center_x(cell.bbox) <= column.bbox[2]
    )


def _role_columns(region: TableRegion, role: ColumnRole) -> tuple[ColumnSpec, ...]:
    return tuple(column for column in region.table_schema.columns if column.role is role)


def _role_cells(row: Row, region: TableRegion, role: ColumnRole) -> tuple[Cell, ...]:
    return tuple(
        cell for column in _role_columns(region, role) for cell in _cells_for_column(row, column)
    )


def _row_evidence(rows: Sequence[Row]) -> tuple[EvidenceReference, ...]:
    return tuple(
        EvidenceReference(page_number=cell.page_number, bbox=cell.bbox, raw_text=cell.text)
        for row in rows
        for cell in row.cells
    )


def _row_text(rows: Sequence[Row]) -> str:
    return _normalized_text(" ".join(cell.text for row in rows for cell in row.cells))


def _parse_date(text: str) -> tuple[date | None, str | None]:
    normalized = _normalized_text(text)
    match = _DATE_PATTERN.fullmatch(normalized)
    if match is None:
        if _INSTALLMENT_PATTERN.fullmatch(normalized) is not None:
            return None, "ambiguous_date_or_installment"
        return None, "invalid_date"
    first, _, second, third = match.groups()
    if len(first) == 4:
        year, month, day = int(first), int(second), int(third)
    elif len(third) == 4:
        day, month, year = int(first), int(second), int(third)
    else:
        return None, "invalid_date"
    try:
        return date(year, month, day), None
    except ValueError:
        return None, "invalid_date"


def _parse_installment(text: str) -> tuple[tuple[int, int] | None, str | None]:
    match = _INSTALLMENT_PATTERN.fullmatch(_normalized_text(text))
    if match is None:
        return None, "invalid_installment"
    current, total = (int(value) for value in match.groups())
    if current < 1 or total < 1 or current > total:
        return None, "invalid_installment"
    return (current, total), None


def _header_kind(column: ColumnSpec) -> str | None:
    header = _normalized_phrase(" ".join(cell.text for cell in column.source_cells))
    if _contains_marker(header, ("posting date", "billing date", "תאריך חיוב")):
        return "posting"
    if _contains_marker(header, ("transaction date", "purchase date", "תאריך עסקה")):
        return "transaction"
    return None


def _category(description: str | None, has_installment: bool) -> TransactionCategory:
    if has_installment:
        return TransactionCategory.INSTALLMENT
    normalized = description or ""
    for category, markers in _CATEGORY_VOCABULARY:
        if _contains_marker(normalized, markers):
            return category
    return TransactionCategory.PURCHASE if description else TransactionCategory.UNKNOWN


def _is_continuation(row: Row, previous: Row, region: TableRegion) -> bool:
    description_cells = _role_cells(row, region, ColumnRole.DESCRIPTION)
    has_transaction_fields = any(
        _role_cells(row, region, role)
        for role in (
            ColumnRole.DATE,
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.INSTALLMENT,
        )
    )
    if len(description_cells) != 1 or has_transaction_fields:
        return False
    typical_height = statistics.median(
        _height(candidate.bbox) for candidate in (*previous.cells, *row.cells)
    )
    gap = max(0.0, row.bbox[1] - previous.bbox[3])
    return gap <= typical_height * 1.5


def _description(rows: Sequence[Row], region: TableRegion) -> tuple[str | None, list[str]]:
    cells = tuple(cell for row in rows for cell in _role_cells(row, region, ColumnRole.DESCRIPTION))
    diagnostics: list[str] = []
    if not cells:
        return None, diagnostics
    if len(cells) > len(rows):
        diagnostics.append("multiple_description_cells")
    return _normalized_text(" ".join(cell.text for cell in cells)), diagnostics


def _dates(row: Row, region: TableRegion) -> tuple[date | None, date | None, list[str]]:
    columns = _role_columns(region, ColumnRole.DATE)
    diagnostics: list[str] = []
    parsed: list[tuple[str | None, date | None, str | None]] = []
    for column in columns:
        cells = _cells_for_column(row, column)
        if len(cells) != 1:
            diagnostics.append("multiple_date_cells" if cells else "missing_date_cell")
            continue
        parsed_date, date_diagnostic = _parse_date(cells[0].text)
        parsed.append((_header_kind(column), parsed_date, date_diagnostic))
    transaction_date: date | None = None
    posting_date: date | None = None
    if len(columns) == 1 and parsed:
        transaction_date = parsed[0][1]
        if parsed[0][2] is not None:
            diagnostics.extend(("invalid_transaction_date", f"transaction_date:{parsed[0][2]}"))
    elif len(columns) > 1:
        kinds = tuple(kind for kind, _, _ in parsed)
        if kinds.count("transaction") != 1 or kinds.count("posting") != 1:
            diagnostics.append("unresolved_date_column_roles")
        else:
            for kind, parsed_date, date_diagnostic in parsed:
                if kind == "transaction":
                    transaction_date = parsed_date
                    if date_diagnostic is not None:
                        diagnostics.extend(
                            ("invalid_transaction_date", f"transaction_date:{date_diagnostic}")
                        )
                elif kind == "posting":
                    posting_date = parsed_date
                    if date_diagnostic is not None:
                        diagnostics.extend(
                            ("invalid_posting_date", f"posting_date:{date_diagnostic}")
                        )
    return transaction_date, posting_date, diagnostics


def _normalize_row(
    *,
    row: Row,
    continuation_rows: Sequence[Row],
    region: TableRegion,
    group: StatementGroupDiscovery,
    transaction_id: str,
) -> RowNormalizationResult:
    rows = (row, *continuation_rows)
    evidence = _row_evidence(rows)
    diagnostics: list[str] = []
    amount_columns = _role_columns(region, ColumnRole.AMOUNT)
    if len(amount_columns) != 1:
        diagnostics.append(
            "unknown_amount_column" if not amount_columns else "multiple_amount_columns"
        )
        return RowNormalizationResult(
            page_number=row.page_number,
            bbox=row.bbox,
            raw_text=_row_text(rows),
            evidence=evidence,
            confidence=0.0,
            diagnostics=tuple(diagnostics),
        )
    amount_cells = _cells_for_column(row, amount_columns[0])
    if len(amount_cells) != 1:
        diagnostics.append("missing_amount_cell" if not amount_cells else "multiple_amount_cells")
        return RowNormalizationResult(
            page_number=row.page_number,
            bbox=row.bbox,
            raw_text=_row_text(rows),
            evidence=evidence,
            confidence=0.0,
            diagnostics=tuple(diagnostics),
        )

    currency_hint = group.printed_total.currency
    currency_cells = _role_cells(row, region, ColumnRole.CURRENCY)
    if len(currency_cells) > 1:
        diagnostics.append("multiple_currency_cells")
    elif len(currency_cells) == 1:
        row_currency = _canonical_currency(currency_cells[0].text)
        if row_currency is None:
            diagnostics.append("unknown_billing_currency")
        elif row_currency != currency_hint:
            diagnostics.append("billing_currency_conflict")
        else:
            currency_hint = row_currency
    if diagnostics:
        return RowNormalizationResult(
            page_number=row.page_number,
            bbox=row.bbox,
            raw_text=_row_text(rows),
            evidence=evidence,
            confidence=0.0,
            diagnostics=tuple(diagnostics),
        )
    billed = parse_amount(amount_cells[0].text, currency_hint=currency_hint)
    if billed.amount is None or billed.currency is None:
        return RowNormalizationResult(
            page_number=row.page_number,
            bbox=row.bbox,
            raw_text=_row_text(rows),
            evidence=evidence,
            confidence=0.0,
            diagnostics=billed.diagnostics,
        )
    if billed.amount == 0:
        return RowNormalizationResult(
            page_number=row.page_number,
            bbox=row.bbox,
            raw_text=_row_text(rows),
            evidence=evidence,
            confidence=0.0,
            diagnostics=("zero_billed_amount",),
        )

    description, description_diagnostics = _description(rows, region)
    diagnostics.extend(description_diagnostics)
    transaction_date, posting_date, date_diagnostics = _dates(row, region)
    diagnostics.extend(date_diagnostics)

    original_amount: Decimal | None = None
    original_currency: str | None = None
    original_columns = _role_columns(region, ColumnRole.ORIGINAL_AMOUNT)
    if len(original_columns) > 1:
        diagnostics.append("multiple_original_amount_columns")
    elif len(original_columns) == 1:
        original_cells = _cells_for_column(row, original_columns[0])
        if len(original_cells) != 1:
            diagnostics.append(
                "missing_original_amount_cell"
                if not original_cells
                else "multiple_original_amount_cells"
            )
        else:
            original = parse_amount(original_cells[0].text)
            if original.amount is None or original.currency is None:
                diagnostics.extend(
                    f"original_amount:{diagnostic}" for diagnostic in original.diagnostics
                )
            else:
                original_amount = original.amount
                original_currency = original.currency

    installment_current: int | None = None
    installment_total: int | None = None
    installment_columns = _role_columns(region, ColumnRole.INSTALLMENT)
    if len(installment_columns) > 1:
        diagnostics.append("multiple_installment_columns")
    elif len(installment_columns) == 1:
        installment_cells = _cells_for_column(row, installment_columns[0])
        if len(installment_cells) != 1:
            diagnostics.append(
                "missing_installment_cell"
                if not installment_cells
                else "multiple_installment_cells"
            )
        else:
            installment, installment_diagnostic = _parse_installment(installment_cells[0].text)
            if installment_diagnostic is not None:
                diagnostics.append(installment_diagnostic)
            elif installment is not None:
                installment_current, installment_total = installment

    kind = TransactionKind.CREDIT if billed.amount < 0 else TransactionKind.CHARGE
    transaction = Transaction(
        transaction_id=transaction_id,
        kind=kind,
        billed_amount=billed.amount,
        billing_currency=billed.currency,
        reconciliation_group_ids=(group.group_id,),
        ambiguities=tuple(dict.fromkeys(diagnostics)),
        transaction_date=transaction_date,
        posting_date=posting_date,
        description=description,
        category=_category(description, installment_current is not None),
        original_amount=original_amount,
        original_currency=original_currency,
        installment_current=installment_current,
        installment_total=installment_total,
        evidence=evidence,
    )
    confidence_values = [row.confidence, billed.confidence]
    confidence_values.extend(continuation.confidence for continuation in continuation_rows)
    return RowNormalizationResult(
        page_number=row.page_number,
        bbox=row.bbox,
        raw_text=_row_text(rows),
        evidence=evidence,
        transaction=transaction,
        confidence=statistics.mean(confidence_values),
        diagnostics=transaction.ambiguities,
    )


def _printed_total(group: StatementGroupDiscovery) -> tuple[PrintedTotal | None, tuple[str, ...]]:
    parsed = parse_amount(
        group.printed_total.amount_text,
        currency_hint=group.printed_total.currency,
    )
    if parsed.amount is None or parsed.currency is None:
        return None, tuple(f"printed_total:{diagnostic}" for diagnostic in parsed.diagnostics)
    return (
        PrintedTotal(group_id=group.group_id, amount=parsed.amount, currency=parsed.currency),
        (),
    )


def normalize_statement(discovery: StatementDiscovery) -> StatementNormalization:
    """Normalize discovered current-cycle rows and reconcile exact printed totals."""

    transactions: list[Transaction] = []
    totals: list[PrintedTotal] = []
    row_results: list[RowNormalizationResult] = []
    diagnostics: list[str] = list(discovery.diagnostics)
    rows_not_emitted = 0
    for group in discovery.groups:
        total, total_diagnostics = _printed_total(group)
        diagnostics.extend(total_diagnostics)
        if total is not None:
            totals.append(total)
        row_ordinal = 0
        for region in sorted(
            group.table_regions,
            key=lambda item: (item.page_number, item.bbox[1], item.bbox[0]),
        ):
            rows = tuple(sorted(region.rows, key=lambda item: (item.bbox[1], item.bbox[0])))
            index = 0
            while index < len(rows):
                row = rows[index]
                row_ordinal += 1
                continuations: list[Row] = []
                continuation_index = index + 1
                previous = row
                while continuation_index < len(rows) and _is_continuation(
                    rows[continuation_index], previous, region
                ):
                    continuations.append(rows[continuation_index])
                    previous = rows[continuation_index]
                    continuation_index += 1
                transaction_id = f"{group.group_id}-p{row.page_number:03d}-r{row_ordinal:04d}"
                row_result = _normalize_row(
                    row=row,
                    continuation_rows=continuations,
                    region=region,
                    group=group,
                    transaction_id=transaction_id,
                )
                row_results.append(row_result)
                if row_result.transaction is None:
                    rows_not_emitted += 1
                else:
                    transactions.append(row_result.transaction)
                for continuation in continuations:
                    row_ordinal += 1
                    row_results.append(
                        RowNormalizationResult(
                            page_number=continuation.page_number,
                            bbox=continuation.bbox,
                            raw_text=_row_text((continuation,)),
                            evidence=_row_evidence((continuation,)),
                            confidence=continuation.confidence,
                            diagnostics=("merged_description_continuation",),
                        )
                    )
                index = continuation_index
    if rows_not_emitted:
        diagnostics.append(f"rows_not_emitted:{rows_not_emitted}")
    reconciliation = reconcile(transactions, totals)
    if diagnostics:
        reconciliation = reconciliation.model_copy(
            update={
                "status": Status.UNRECONCILED,
                "diagnostics": tuple(dict.fromkeys((*reconciliation.diagnostics, *diagnostics))),
            }
        )
    confidence_values = tuple(result.confidence for result in row_results)
    confidence = statistics.mean(confidence_values) if confidence_values else 0.0
    return StatementNormalization(
        discovery=discovery,
        transactions=tuple(transactions),
        printed_totals=tuple(totals),
        row_results=tuple(row_results),
        reconciliation=reconciliation,
        confidence=confidence,
        diagnostics=tuple(dict.fromkeys(diagnostics)),
    )


__all__ = [
    "AmountParseResult",
    "RowNormalizationResult",
    "StatementNormalization",
    "normalize_statement",
    "parse_amount",
]
