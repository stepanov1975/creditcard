"""Pure monetary parsing and geometry-driven transaction normalization."""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise

from pydantic import BaseModel, ConfigDict, Field

from ccparser.discovery import (
    DiscoveredDateYearContext,
    StatementDiscovery,
    StatementGroupDiscovery,
)
from ccparser.fx import extract_foreign_exchange
from ccparser.geometry import BBox
from ccparser.geometry import (
    center_inside as _bbox_center_inside,
)
from ccparser.layout.columns import (
    cells_in_column,
    columns_for_role,
    proven_region_billed_amount_column,
)
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableRegion
from ccparser.layout.row_tags import RowTag, has_row_tag
from ccparser.models import (
    EvidenceReference,
    PrintedTotal,
    Status,
    Transaction,
    TransactionCategory,
    TransactionKind,
)
from ccparser.money import (
    AmountParseResult,
    is_money_shaped,
    parse_amount,
)
from ccparser.normalization_dates import (
    ConversionDateExtraction,
    DateColumnKind,
    accepted_conversion_date_atom_ids,
    extract_conversion_date,
    extract_dates,
    structural_date_column_kinds,
)
from ccparser.normalization_description import (
    derive_merchant,
    extract_description,
    is_description_continuation,
)
from ccparser.normalization_fields import (
    FieldDisposition,
    extract_billed_fields,
    extract_installment_fields,
)
from ccparser.normalization_semantics import (
    assignment_diagnostics,
    explicit_category_unknown_columns,
    role_contract_diagnostics,
    validate_transaction_semantics,
)
from ccparser.original_amount import extract_original_amount
from ccparser.reconcile import ReconciliationOutcome, reconciliation_outcome
from ccparser.semantic_evidence import EvidenceClaim, EvidenceLedger, SemanticOwner
from ccparser.text_tokens import contains_token_sequence, normalize_text


class _ImmutableNormalizationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


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
    reconciliation: ReconciliationOutcome
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _RowNormalizationAttempt:
    """One internal row result paired with its explicit emission disposition."""

    result: RowNormalizationResult
    disposition: FieldDisposition


@dataclass(slots=True)
class _RowNormalizationContext:
    """Stable row provenance and ordered diagnostics for result construction."""

    rows: tuple[Row, ...]
    evidence: tuple[EvidenceReference, ...]
    raw_text: str
    diagnostics: list[str]

    @property
    def row(self) -> Row:
        return self.rows[0]

    def rejected_attempt(
        self,
        *,
        diagnostics: tuple[str, ...] | None = None,
    ) -> _RowNormalizationAttempt:
        result = RowNormalizationResult(
            page_number=self.row.page_number,
            bbox=self.row.bbox,
            raw_text=self.raw_text,
            evidence=self.evidence,
            confidence=0.0,
            diagnostics=tuple(self.diagnostics) if diagnostics is None else diagnostics,
        )
        return _RowNormalizationAttempt(result, FieldDisposition.REJECT_ROW)

    def ignored_attempt(
        self,
        *,
        confidence: float,
        diagnostics: tuple[str, ...],
    ) -> _RowNormalizationAttempt:
        result = RowNormalizationResult(
            page_number=self.row.page_number,
            bbox=self.row.bbox,
            raw_text=self.raw_text,
            evidence=self.evidence,
            confidence=confidence,
            diagnostics=diagnostics,
        )
        return _RowNormalizationAttempt(result, FieldDisposition.IGNORE_ROW)

    def completed_attempt(
        self,
        *,
        transaction: Transaction,
        confidence: float,
    ) -> _RowNormalizationAttempt:
        result = RowNormalizationResult(
            page_number=self.row.page_number,
            bbox=self.row.bbox,
            raw_text=self.raw_text,
            evidence=self.evidence,
            transaction=transaction,
            confidence=confidence,
            diagnostics=transaction.ambiguities,
        )
        return _RowNormalizationAttempt(result, FieldDisposition.ACCEPT)


def _assign_semantic_atom_ids(
    claims: Sequence[EvidenceClaim],
    owner: SemanticOwner,
    atom_ids: frozenset[int],
) -> list[EvidenceClaim]:
    if not atom_ids:
        return list(claims)
    reassigned = [
        EvidenceClaim(claim.owner, remaining_ids)
        for claim in claims
        if (remaining_ids := claim.atom_ids - atom_ids)
    ]
    reassigned.append(EvidenceClaim(owner, atom_ids))
    return reassigned


_CATEGORY_VOCABULARY: tuple[tuple[TransactionCategory, tuple[str, ...]], ...] = (
    (TransactionCategory.REFUND, ("credit", "refund", "זיכוי", "החזר")),
    (TransactionCategory.INTEREST, ("interest", "ריבית")),
    (TransactionCategory.FEE, ("commission", "fee", "עמלה", "דמי")),
    (TransactionCategory.ADJUSTMENT, ("adjustment", "correction", "התאמה", "תיקון")),
    (TransactionCategory.PURCHASE, ("purchase", "purchased", "רכישה", "קנייה", "עסקה")),
)


def _normalized_text(text: str) -> str:
    return normalize_text(text)


def _contains_marker(text: str, markers: Iterable[str]) -> bool:
    return contains_token_sequence(text, markers)


def _cells_for_column(row: Row, column: ColumnSpec) -> tuple[Cell, ...]:
    return cells_in_column(row.cells, column)


def _role_columns(region: TableRegion, role: ColumnRole) -> tuple[ColumnSpec, ...]:
    return columns_for_role(region.table_schema, role)


def _row_evidence(rows: Sequence[Row]) -> tuple[EvidenceReference, ...]:
    return tuple(
        EvidenceReference(page_number=cell.page_number, bbox=cell.bbox, raw_text=cell.text)
        for row in rows
        for cell in row.cells
    )


def _row_text(rows: Sequence[Row]) -> str:
    return _normalized_text(" ".join(cell.text for row in rows for cell in row.cells))


def _category(description: str | None, has_installment: bool) -> TransactionCategory:
    if has_installment:
        return TransactionCategory.INSTALLMENT
    normalized = description or ""
    for category, markers in _CATEGORY_VOCABULARY:
        if _contains_marker(normalized, markers):
            return category
    return TransactionCategory.UNKNOWN


def _category_sign_contradiction(category: TransactionCategory, kind: TransactionKind) -> bool:
    if category is TransactionCategory.REFUND:
        return kind is not TransactionKind.CREDIT
    if category in {
        TransactionCategory.PURCHASE,
        TransactionCategory.FEE,
        TransactionCategory.INTEREST,
        TransactionCategory.INSTALLMENT,
    }:
        return kind is not TransactionKind.CHARGE
    return False


def _explicit_category(
    row: Row,
    region: TableRegion,
) -> tuple[TransactionCategory, tuple[str, ...]]:
    columns = tuple(
        column
        for column in _role_columns(region, ColumnRole.UNKNOWN)
        if column.index in explicit_category_unknown_columns(region)
    )
    if len(columns) > 1:
        return TransactionCategory.UNKNOWN, ("multiple_category_columns",)
    if not columns:
        return TransactionCategory.UNKNOWN, ()
    cells = _cells_for_column(row, columns[0])
    if len(cells) > 1:
        return TransactionCategory.UNKNOWN, ("multiple_category_cells",)
    if not cells:
        return TransactionCategory.UNKNOWN, ()
    return _category(cells[0].text, False), ()


def _resolved_category(
    description: str | None,
    has_installment: bool,
    row: Row,
    region: TableRegion,
) -> tuple[TransactionCategory, tuple[str, ...]]:
    description_category = _category(description, has_installment)
    explicit_category, diagnostics = _explicit_category(row, region)
    if (
        description_category is not TransactionCategory.UNKNOWN
        and explicit_category is not TransactionCategory.UNKNOWN
        and description_category is not explicit_category
    ):
        return description_category, (*diagnostics, "conflicting_category_semantics")
    if description_category is not TransactionCategory.UNKNOWN:
        return description_category, diagnostics
    return explicit_category, diagnostics


def _normalize_row(
    *,
    row: Row,
    continuation_rows: Sequence[Row],
    region: TableRegion,
    group: StatementGroupDiscovery,
    year_context: DiscoveredDateYearContext | None,
    date_column_kinds: Mapping[int, DateColumnKind],
    transaction_id: str,
) -> _RowNormalizationAttempt:
    rows = (row, *continuation_rows)
    ledger = EvidenceLedger.from_rows(rows)
    context = _RowNormalizationContext(
        rows=rows,
        evidence=_row_evidence(rows),
        raw_text=_row_text(rows),
        diagnostics=[],
    )
    diagnostics = context.diagnostics
    contract_diagnostics = role_contract_diagnostics(region)
    if contract_diagnostics:
        diagnostics.extend(assignment_diagnostics(row, region, ledger, year_context=year_context))
        diagnostics.extend(contract_diagnostics)
        return context.rejected_attempt()

    billed = extract_billed_fields(
        row=row,
        region=region,
        printed_currency=group.printed_total.currency,
    )
    if billed.disposition is FieldDisposition.REJECT_ROW:
        if billed.amount_cell is not None:
            return context.rejected_attempt(diagnostics=billed.diagnostics)
        diagnostics.extend(assignment_diagnostics(row, region, ledger, year_context=year_context))
        diagnostics.extend(billed.diagnostics)
        return context.rejected_attempt()
    if billed.disposition is FieldDisposition.IGNORE_ROW:
        return context.ignored_attempt(
            confidence=billed.confidence,
            diagnostics=billed.diagnostics,
        )
    if billed.amount is None or billed.currency is None or billed.amount_cell is None:
        raise RuntimeError("accepted billed fields must contain complete source values")

    date_extraction = extract_dates(
        row,
        region,
        year_context,
        date_column_kinds,
        ledger=ledger,
    )
    transaction_date = date_extraction.transaction_date
    posting_date = date_extraction.posting_date
    conversion_date = date_extraction.conversion_date
    unresolved_conversion_cells = date_extraction.unresolved_conversion_cells
    explicit_conversion_atom_ids = accepted_conversion_date_atom_ids(
        row,
        region,
        ledger,
        year_context,
        explicit_conversion_date=conversion_date,
        semantic_extraction=ConversionDateExtraction(None, (), frozenset(), frozenset()),
    )
    accepted_conversion_atom_ids = explicit_conversion_atom_ids
    conversion_ownership_stable = False
    for iteration in range(3):
        description_extraction = extract_description(
            rows,
            region,
            year_context,
            ledger,
            excluded_atom_ids=accepted_conversion_atom_ids,
        )
        semantic_claims = _assign_semantic_atom_ids(
            description_extraction.claims,
            SemanticOwner.CONVERSION_DATE,
            accepted_conversion_atom_ids,
        )
        original_extraction = extract_original_amount(
            row=row,
            continuation_rows=continuation_rows,
            region=region,
            ledger=ledger,
            billed=billed,
            description=description_extraction.value,
            initial_claims=semantic_claims,
        )
        semantic_claims.extend(original_extraction.claims)
        conversion_extraction = extract_conversion_date(
            row,
            region,
            ledger,
            year_context,
            original_currency=original_extraction.currency,
            billing_currency=billed.currency,
            transaction_date=transaction_date,
            existing_conversion_date=conversion_date,
        )
        next_atom_ids = accepted_conversion_date_atom_ids(
            row,
            region,
            ledger,
            year_context,
            explicit_conversion_date=conversion_date,
            semantic_extraction=conversion_extraction,
        )
        if next_atom_ids == accepted_conversion_atom_ids:
            conversion_ownership_stable = True
            break
        if iteration < 2:
            accepted_conversion_atom_ids = next_atom_ids

    description = original_extraction.description
    original_amount = original_extraction.amount
    original_currency = original_extraction.currency
    conversion_resolution_diagnostics: list[str] = []
    if not conversion_ownership_stable:
        conversion_resolution_diagnostics.append("unstable_conversion_evidence_ownership")
    if conversion_date is None:
        conversion_date = conversion_extraction.value
    elif conversion_extraction.value is not None and conversion_extraction.value != conversion_date:
        conversion_resolution_diagnostics.append("conflicting_conversion_date_evidence")
    if any(cell not in conversion_extraction.source_cells for cell in unresolved_conversion_cells):
        conversion_resolution_diagnostics.append("invalid_conversion_date")

    foreign_exchange_extraction = extract_foreign_exchange(
        rows=rows,
        region=region,
        ledger=ledger,
        original_currency=original_currency,
        billing_currency=billed.currency,
        excluded_atom_ids=accepted_conversion_atom_ids,
        original_amount=original_amount,
        billed_amount=billed.amount,
    )
    semantic_claims.extend(foreign_exchange_extraction.claims)
    diagnostics.extend(
        assignment_diagnostics(
            row,
            region,
            ledger,
            accepted_conversion_date_atom_ids=accepted_conversion_atom_ids,
            year_context=year_context,
        )
    )
    diagnostics.extend(date_extraction.diagnostics)
    diagnostics.extend(description_extraction.diagnostics)
    diagnostics.extend(original_extraction.diagnostics)
    diagnostics.extend(conversion_extraction.diagnostics)
    diagnostics.extend(conversion_resolution_diagnostics)
    diagnostics.extend(foreign_exchange_extraction.diagnostics)

    installment = extract_installment_fields(row=row, region=region)
    diagnostics.extend(installment.diagnostics)
    installment_current = installment.current
    installment_total = installment.total

    semantic_validation = validate_transaction_semantics(
        rows=rows,
        region=region,
        ledger=ledger,
        initial_claims=semantic_claims,
        amount_cell=billed.amount_cell,
        billing_currency=billed.currency,
        original_currency=original_currency,
        description=description,
        transaction_date=transaction_date,
        posting_date=posting_date,
        conversion_date=conversion_date,
        year_context=year_context,
        date_column_kinds=date_column_kinds,
        accepted_conversion_date_atom_ids=accepted_conversion_atom_ids,
    )
    semantic_claims = list(semantic_validation.claims)
    diagnostics.extend(semantic_validation.diagnostics)
    merchant, merchant_diagnostics = derive_merchant(description=description)
    diagnostics.extend(merchant_diagnostics)

    kind = TransactionKind.CREDIT if billed.amount < 0 else TransactionKind.CHARGE
    category, category_diagnostics = _resolved_category(
        description,
        installment_current is not None,
        row,
        region,
    )
    diagnostics.extend(category_diagnostics)
    if _category_sign_contradiction(category, kind):
        diagnostics.append("category_sign_contradiction")
    transaction = Transaction(
        transaction_id=transaction_id,
        kind=kind,
        billed_amount=billed.amount,
        billing_currency=billed.currency,
        reconciliation_group_ids=(group.group_id,),
        ambiguities=tuple(dict.fromkeys(diagnostics)),
        transaction_date=transaction_date,
        posting_date=posting_date,
        conversion_date=conversion_date,
        merchant=merchant,
        description=description,
        category=category,
        original_amount=original_amount,
        original_currency=original_currency,
        foreign_exchange=foreign_exchange_extraction.details,
        installment_current=installment_current,
        installment_total=installment_total,
        evidence=context.evidence,
    )
    confidence_values = [row.confidence, billed.confidence]
    confidence_values.extend(continuation.confidence for continuation in continuation_rows)
    return context.completed_attempt(
        transaction=transaction,
        confidence=statistics.mean(confidence_values),
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


def _is_printed_total_row(row: Row, group: StatementGroupDiscovery) -> bool:
    evidence = (
        group.printed_total.label_evidence,
        group.printed_total.value_evidence,
    )
    return all(
        item.page_number == row.page_number
        and any(_bbox_center_inside(item.bbox, cell.bbox) for cell in row.cells)
        for item in evidence
    )


def _compatible_cross_page_region_geometry(
    previous: TableRegion,
    current: TableRegion,
) -> bool:
    previous_columns = previous.table_schema.columns
    current_columns = current.table_schema.columns
    return (
        current.page_number == previous.page_number + 1
        and len(previous_columns) == len(current_columns)
        and all(
            previous_column.role is current_column.role
            and abs(previous_column.relative_x0 - current_column.relative_x0) <= 0.05
            and abs(previous_column.relative_x1 - current_column.relative_x1) <= 0.05
            for previous_column, current_column in zip(
                previous_columns,
                current_columns,
                strict=True,
            )
        )
    )


def _cross_page_leading_detail_handoffs(
    regions: Sequence[TableRegion],
    group: StatementGroupDiscovery,
) -> tuple[dict[int, tuple[Row, ...]], frozenset[int]]:
    handoffs: dict[int, tuple[Row, ...]] = {}
    owned_leading_rows: set[int] = set()
    for previous_region, current_region in pairwise(regions):
        if not _compatible_cross_page_region_geometry(previous_region, current_region):
            continue
        current_rows = tuple(
            sorted(current_region.rows, key=lambda item: (item.bbox[1], item.bbox[0]))
        )
        leading_rows = tuple(
            row for row in current_rows if has_row_tag(row, RowTag.LEADING_SUBORDINATE_DETAIL)
        )
        if not leading_rows or current_rows[: len(leading_rows)] != leading_rows:
            continue
        following_rows = current_rows[len(leading_rows) :]
        if not following_rows:
            continue
        previous_rows = tuple(
            sorted(previous_region.rows, key=lambda item: (item.bbox[1], item.bbox[0]))
        )
        previous_base_rows: list[Row] = []
        previous_index = 0
        while previous_index < len(previous_rows):
            previous_row = previous_rows[previous_index]
            if _is_printed_total_row(previous_row, group):
                previous_index += 1
                continue
            previous_base_rows.append(previous_row)
            continuation_index = previous_index + 1
            continuation_previous = previous_row
            while continuation_index < len(previous_rows) and is_description_continuation(
                previous_rows[continuation_index],
                continuation_previous,
                previous_region,
            ):
                continuation_previous = previous_rows[continuation_index]
                continuation_index += 1
            previous_index = continuation_index
        if not previous_base_rows:
            continue
        previous_row = previous_base_rows[-1]
        following_row = following_rows[0]
        previous_billed_column = proven_region_billed_amount_column(previous_region)
        current_billed_column = proven_region_billed_amount_column(current_region)
        if previous_billed_column is None or current_billed_column is None:
            continue
        previous_billed_cells = _cells_for_column(previous_row, previous_billed_column)
        following_billed_cells = _cells_for_column(following_row, current_billed_column)
        previous_billed = (
            parse_amount(
                previous_billed_cells[0].text,
                currency_hint=group.printed_total.currency,
            )
            if len(previous_billed_cells) == 1
            else None
        )
        if (
            len(previous_billed_cells) != 1
            or not is_money_shaped(previous_billed_cells[0].text)
            or previous_billed is None
            or previous_billed.amount in {None, Decimal("0")}
            or len(following_billed_cells) != 1
            or not is_money_shaped(following_billed_cells[0].text)
        ):
            continue
        handoffs[id(previous_row)] = tuple(
            row.model_copy(
                update={
                    "diagnostics": tuple(
                        "subordinate_detail_continuation"
                        if diagnostic == "leading_subordinate_detail_continuation"
                        else diagnostic
                        for diagnostic in row.diagnostics
                    )
                }
            )
            for row in leading_rows
        )
        owned_leading_rows.update(id(row) for row in leading_rows)
    return handoffs, frozenset(owned_leading_rows)


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
        ordered_regions = tuple(
            sorted(
                group.table_regions,
                key=lambda item: (item.page_number, item.bbox[1], item.bbox[0]),
            )
        )
        cross_page_handoffs, owned_leading_rows = _cross_page_leading_detail_handoffs(
            ordered_regions,
            group,
        )
        for region in ordered_regions:
            date_column_kinds = structural_date_column_kinds(
                region,
                discovery.date_year_context,
            )
            rows = tuple(sorted(region.rows, key=lambda item: (item.bbox[1], item.bbox[0])))
            index = 0
            while index < len(rows):
                row = rows[index]
                if has_row_tag(row, RowTag.LEADING_SUBORDINATE_DETAIL):
                    if id(row) in owned_leading_rows:
                        index += 1
                        continue
                    row_ordinal += 1
                    row_results.append(
                        RowNormalizationResult(
                            page_number=row.page_number,
                            bbox=row.bbox,
                            raw_text=_row_text((row,)),
                            evidence=_row_evidence((row,)),
                            confidence=row.confidence,
                            diagnostics=("unowned_leading_subordinate_detail_continuation",),
                        )
                    )
                    rows_not_emitted += 1
                    index += 1
                    continue
                row_ordinal += 1
                if _is_printed_total_row(row, group):
                    row_results.append(
                        RowNormalizationResult(
                            page_number=row.page_number,
                            bbox=row.bbox,
                            raw_text=_row_text((row,)),
                            evidence=_row_evidence((row,)),
                            confidence=row.confidence,
                            diagnostics=("printed_total_row",),
                        )
                    )
                    index += 1
                    continue
                continuations: list[Row] = []
                continuation_index = index + 1
                previous = row
                while continuation_index < len(rows) and is_description_continuation(
                    rows[continuation_index], previous, region
                ):
                    continuations.append(rows[continuation_index])
                    previous = rows[continuation_index]
                    continuation_index += 1
                continuations.extend(cross_page_handoffs.get(id(row), ()))
                transaction_id = f"{group.group_id}-p{row.page_number:03d}-r{row_ordinal:04d}"
                attempt = _normalize_row(
                    row=row,
                    continuation_rows=continuations,
                    region=region,
                    group=group,
                    year_context=discovery.date_year_context,
                    date_column_kinds=date_column_kinds,
                    transaction_id=transaction_id,
                )
                row_result = attempt.result
                row_results.append(row_result)
                if row_result.transaction is None:
                    if attempt.disposition is FieldDisposition.REJECT_ROW:
                        rows_not_emitted += 1
                else:
                    transactions.append(row_result.transaction)
                for continuation in continuations:
                    row_ordinal += 1
                    continuation_diagnostic = (
                        "merged_subordinate_detail_continuation"
                        if has_row_tag(continuation, RowTag.SUBORDINATE_DETAIL)
                        else "merged_auxiliary_continuation"
                        if has_row_tag(continuation, RowTag.AUXILIARY_CONTINUATION)
                        else "merged_description_continuation"
                    )
                    row_results.append(
                        RowNormalizationResult(
                            page_number=continuation.page_number,
                            bbox=continuation.bbox,
                            raw_text=_row_text((continuation,)),
                            evidence=_row_evidence((continuation,)),
                            confidence=continuation.confidence,
                            diagnostics=(continuation_diagnostic,),
                        )
                    )
                index = continuation_index
    if rows_not_emitted:
        diagnostics.append(f"rows_not_emitted:{rows_not_emitted}")
    reconciliation = reconciliation_outcome(transactions, totals)
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
