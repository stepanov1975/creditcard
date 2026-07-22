"""Original transaction-value extraction and bounded recovery."""

from __future__ import annotations

import statistics
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from ccparser.geometry import (
    bbox_center_x,
    bbox_center_y,
    bbox_height,
    center_inside,
    union_bbox,
    vertical_overlap,
)
from ccparser.layout.columns import (
    cells_in_column,
    columns_for_role,
    is_location_identifier,
    proven_billed_amount_column,
)
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableRegion
from ccparser.layout.row_tags import RowTag, has_row_tag
from ccparser.layout.text import cell_has_ocr_evidence
from ccparser.money import (
    AmountParseResult,
    canonical_currency,
    currencies_in_text,
    is_currency_shaped,
    is_money_shaped,
    parse_amount,
)
from ccparser.normalization_fields import BilledFields, is_installment_shaped
from ccparser.semantic_evidence import EvidenceClaim, EvidenceLedger, SemanticOwner
from ccparser.text_tokens import normalize_text, phrase_tokens

_MIN_DESCRIPTION_SPILL_OVERLAP = 0.2


@dataclass(frozen=True, slots=True)
class OriginalAmountExtraction:
    """An original value, description correction, and newly owned evidence."""

    amount: Decimal | None
    currency: str | None
    description: str | None
    claims: tuple[EvidenceClaim, ...]
    diagnostics: tuple[str, ...]


def _amount_from_exact_words_between_boundary_glyphs(
    cell: Cell,
    column: ColumnSpec,
    currency_hint: str | None,
) -> AmountParseResult | None:
    if (
        not 1 <= len(cell.words) <= 2
        or any(word.source != "digital" for word in cell.words)
        or not cell.glyphs
    ):
        return None
    word_bbox = union_bbox(word.bbox for word in cell.words)
    if not (column.bbox[0] <= word_bbox[0] and word_bbox[2] <= column.bbox[2]):
        return None
    word_text = " ".join(word.text for word in cell.words)
    parsed = parse_amount(word_text, currency_hint=currency_hint)
    if parsed.amount is None or parsed.currency is None:
        return None
    compact_cell = "".join(normalize_text(cell.text).split())
    compact_words = "".join(normalize_text(word_text).split())
    if compact_cell.count(compact_words) != 1:
        return None
    boundary_glyphs = tuple(
        glyph
        for glyph in cell.glyphs
        if not glyph.char.isspace() and not center_inside(glyph.bbox, word_bbox)
    )
    if not boundary_glyphs or any(glyph.source != "digital" for glyph in boundary_glyphs):
        return None
    if any(
        not (glyph.bbox[0] < column.bbox[0] or glyph.bbox[2] > column.bbox[2])
        for glyph in boundary_glyphs
    ):
        return None
    return parsed


def _proven_implicit_original_currency(
    region: TableRegion,
    billing_currency: str,
) -> str | None:
    original_columns = columns_for_role(region.table_schema, ColumnRole.ORIGINAL_AMOUNT)
    transaction_rows = tuple(
        row for row in region.rows if not has_row_tag(row, RowTag.SUBORDINATE_DETAIL)
    )
    billed_column = proven_billed_amount_column(region.table_schema, transaction_rows)
    if (
        len(original_columns) != 1
        or columns_for_role(region.table_schema, ColumnRole.ORIGINAL_CURRENCY)
        or billed_column is None
    ):
        return None
    transaction_rows = tuple(
        row for row in transaction_rows if len(cells_in_column(row.cells, billed_column)) == 1
    )
    has_conversion_evidence = any(
        columns_for_role(region.table_schema, role)
        for role in (
            ColumnRole.CONVERSION_DATE,
            ColumnRole.EXCHANGE_RATE,
            ColumnRole.CURRENCY,
        )
    )
    minimum_proven_rows = 2 if has_conversion_evidence else 1
    proven_row_count = 0
    for row in transaction_rows:
        original_cells = cells_in_column(row.cells, original_columns[0])
        billed_cells = cells_in_column(row.cells, billed_column)
        if len(original_cells) != 1 or currencies_in_text(original_cells[0].text):
            return None
        original = parse_amount(original_cells[0].text, currency_hint=billing_currency)
        if original.amount is None or original.currency is None:
            recovered = _amount_from_exact_words_between_boundary_glyphs(
                original_cells[0],
                original_columns[0],
                billing_currency,
            )
            if recovered is not None:
                original = recovered
        billed = parse_amount(billed_cells[0].text, currency_hint=billing_currency)
        if billed.amount is None or billed.currency is None:
            continue
        if original.amount is None or original.currency is None:
            continue
        if abs(original.amount) != abs(billed.amount):
            return None
        proven_row_count += 1
    return canonical_currency(billing_currency) if proven_row_count >= minimum_proven_rows else None


def original_currency_spilled_into_location(
    cell: Cell,
    region: TableRegion,
) -> str | None:
    original_columns = columns_for_role(region.table_schema, ColumnRole.ORIGINAL_AMOUNT)
    location_columns = columns_for_role(region.table_schema, ColumnRole.LOCATION)
    if (
        len(original_columns) != 1
        or len(location_columns) != 1
        or abs(original_columns[0].index - location_columns[0].index) != 1
        or len(cell.words) < 2
        or any(word.source != "digital" for word in cell.words)
    ):
        return None
    currency_words = tuple(
        word
        for word in cell.words
        if not any(char.isdigit() for char in word.text)
        and canonical_currency(word.text) is not None
    )
    if len(currency_words) != 1:
        return None
    currency_word = currency_words[0]
    residual_words = tuple(word for word in cell.words if word is not currency_word)
    residual_text = normalize_text(" ".join(word.text for word in residual_words))
    has_proven_location_value = (
        len(residual_words) == 1 and is_location_identifier(residual_text)
    ) or (
        any(char.isalpha() for char in residual_text)
        and not any(char.isdigit() for char in residual_text)
        and not is_money_shaped(residual_text)
        and not is_currency_shaped(residual_text)
    )
    if not has_proven_location_value:
        return None
    compact_cell = "".join(normalize_text(cell.text).split())
    compact_words = "".join(
        "".join(normalize_text(word.text).split())
        for word in sorted(cell.words, key=lambda word: word.bbox[0])
    )
    original_on_left = bbox_center_x(original_columns[0].bbox) < bbox_center_x(
        location_columns[0].bbox
    )
    description_columns = columns_for_role(region.table_schema, ColumnRole.DESCRIPTION)
    glyph_only_residual = (
        compact_cell[len(compact_words) :]
        if original_on_left and compact_cell.startswith(compact_words)
        else (
            compact_cell[: -len(compact_words)]
            if not original_on_left and compact_cell.endswith(compact_words)
            else ""
        )
    )
    description_on_outer_edge = (
        len(description_columns) == 1
        and description_columns[0].index
        == location_columns[0].index + (1 if original_on_left else -1)
        and max(
            0.0,
            min(cell.bbox[2], description_columns[0].bbox[2])
            - max(cell.bbox[0], description_columns[0].bbox[0]),
        )
        > 0
    )
    if compact_cell != compact_words and not (
        glyph_only_residual
        and all(char.isalpha() for char in glyph_only_residual)
        and description_on_outer_edge
    ):
        return None
    residual_edge_center = bbox_center_x(union_bbox(word.bbox for word in residual_words))
    currency_on_original_edge = (
        bbox_center_x(currency_word.bbox) < residual_edge_center
        if original_on_left
        else bbox_center_x(currency_word.bbox) > residual_edge_center
    )
    return canonical_currency(currency_word.text) if currency_on_original_edge else None


def _bounded_note_original_amounts(rows: Sequence[Row]) -> frozenset[tuple[Decimal, str]]:
    corroborated: set[tuple[Decimal, str]] = set()
    for row in rows:
        if not has_row_tag(row, RowTag.HEBREW_NOTE_DETAIL):
            continue
        words = tuple(word for cell in row.cells for word in cell.words)
        currencies = {
            currency for word in words if (currency := canonical_currency(word.text)) is not None
        }
        if len(currencies) != 1:
            continue
        currency = next(iter(currencies))
        amounts = {
            parsed.amount
            for word in words
            if (parsed := parse_amount(word.text, currency_hint=currency)).amount is not None
        }
        if len(amounts) == 1:
            corroborated.add((next(iter(amounts)), currency))
    return frozenset(corroborated)


def _ocr_original_amount_corroborated_by_billed(
    original_cell: Cell,
    parsed_original: AmountParseResult,
    original_currency_hint: str | None,
    billed: BilledFields,
) -> AmountParseResult | None:
    if (
        not cell_has_ocr_evidence(original_cell)
        or parsed_original.diagnostics != ("invalid_grouping_separator",)
        or billed.amount is None
        or billed.amount <= 0
        or billed.currency is None
        or original_currency_hint != billed.currency
        or any(char.isalpha() for char in original_cell.text)
        or any(char in "-+()" for char in original_cell.text)
    ):
        return None
    observed_digits = "".join(char for char in original_cell.text if char.isdigit())
    billed_digits = "".join(char for char in f"{billed.amount:.2f}" if char.isdigit())
    if observed_digits != billed_digits:
        return None
    return AmountParseResult(
        raw_text=original_cell.text,
        amount=billed.amount,
        currency=billed.currency,
        confidence=min(original_cell.confidence, billed.confidence),
    )


def _original_amount_from_subordinate_detail(
    original_cell: Cell,
    parsed_original: AmountParseResult,
    original_currency_hint: str | None,
    continuation_rows: Sequence[Row],
) -> AmountParseResult | None:
    if (
        not cell_has_ocr_evidence(original_cell)
        or parsed_original.amount is not None
        or not parsed_original.diagnostics
    ):
        return None
    pairs: set[tuple[Decimal, str]] = set()
    supporting_confidences: list[float] = []
    for row in continuation_rows:
        if not has_row_tag(row, RowTag.SUBORDINATE_DETAIL):
            continue
        words = tuple(word for cell in row.cells for word in cell.words)
        currencies = {
            currency for word in words if (currency := canonical_currency(word.text)) is not None
        }
        if len(currencies) != 1:
            continue
        currency = next(iter(currencies))
        amounts = {
            parsed.amount
            for word in words
            if (parsed := parse_amount(word.text, currency_hint=currency)).amount is not None
        }
        if len(amounts) == 1:
            pairs.add((next(iter(amounts)), currency))
            supporting_confidences.extend(word.confidence for word in words)
    if len(pairs) != 1:
        return None
    amount, currency = next(iter(pairs))
    main_currencies = currencies_in_text(original_cell.text)
    if currency not in main_currencies and original_currency_hint != currency:
        return None
    exact_main_amounts = {
        parsed.amount
        for word in original_cell.words
        if (parsed := parse_amount(word.text, currency_hint=currency)).amount is not None
    }
    if amount not in exact_main_amounts:
        return None
    return AmountParseResult(
        raw_text=original_cell.text,
        amount=amount,
        currency=currency,
        confidence=min(
            original_cell.confidence,
            *(supporting_confidences or [original_cell.confidence]),
        ),
    )


def _original_amount_with_description_spill(
    row: Row,
    region: TableRegion,
    original_cell: Cell,
    currency_hint: str | None,
    corroborated_amounts: frozenset[tuple[Decimal, str]],
) -> tuple[AmountParseResult, str, bool, bool] | None:
    description_columns = columns_for_role(region.table_schema, ColumnRole.DESCRIPTION)
    original_columns = columns_for_role(region.table_schema, ColumnRole.ORIGINAL_AMOUNT)
    if len(description_columns) != 1 or len(original_columns) != 1:
        return None
    description_cells = cells_in_column(row.cells, description_columns[0])
    if len(description_cells) != 1 or not original_cell.words or not description_cells[0].words:
        return None
    words = tuple(sorted(original_cell.words, key=lambda word: word.bbox[0]))
    description_words = tuple(sorted(description_cells[0].words, key=lambda word: word.bbox[0]))
    if any(word.source != "digital" for word in (*words, *description_words)):
        return None
    description_on_right = bbox_center_x(description_columns[0].bbox) > bbox_center_x(
        original_columns[0].bbox
    )
    candidates: list[tuple[AmountParseResult, str, bool, bool]] = []
    word_amount_text = " ".join(word.text for word in words)
    word_amount = parse_amount(word_amount_text, currency_hint=currency_hint)
    compact_cell_text = "".join(normalize_text(original_cell.text).split())
    compact_word_amount = "".join(normalize_text(word_amount_text).split())
    residual_text = ""
    if description_on_right and compact_cell_text.startswith(compact_word_amount):
        residual_text = compact_cell_text[len(compact_word_amount) :]
    elif not description_on_right and compact_cell_text.endswith(compact_word_amount):
        residual_text = compact_cell_text[: -len(compact_word_amount)]
    description_cell = description_cells[0]
    horizontal_overlap = max(
        0.0,
        min(original_cell.bbox[2], description_cell.bbox[2])
        - max(original_cell.bbox[0], description_cell.bbox[0]),
    )
    if (
        word_amount.amount is not None
        and word_amount.currency is not None
        and residual_text
        and any(char.isalpha() for char in residual_text)
        and not is_money_shaped(residual_text)
        and not is_currency_shaped(residual_text)
        and not is_installment_shaped(residual_text)
        and horizontal_overlap > 0
        and vertical_overlap(original_cell.bbox, description_cell.bbox) > 0
    ):
        candidates.append((word_amount, residual_text, description_on_right, False))
    for split in range(1, len(words)):
        amount_words, residual_words = (
            (words[:split], words[split:])
            if description_on_right
            else (words[split:], words[:split])
        )
        amount_text = " ".join(word.text for word in amount_words)
        parsed = parse_amount(amount_text, currency_hint=currency_hint)
        residual_text = normalize_text(" ".join(word.text for word in residual_words))
        if (
            parsed.amount is None
            or parsed.currency is None
            or not any(char.isalpha() for char in residual_text)
            or is_money_shaped(residual_text)
            or is_currency_shaped(residual_text)
            or is_installment_shaped(residual_text)
        ):
            continue
        if description_on_right:
            residual_edge = max(word.bbox[2] for word in residual_words)
            description_edge = min(word.bbox[0] for word in description_words)
            gap = description_edge - residual_edge
        else:
            residual_edge = min(word.bbox[0] for word in residual_words)
            description_edge = max(word.bbox[2] for word in description_words)
            gap = residual_edge - description_edge
        typical_height = statistics.median(
            bbox_height(word.bbox) for word in (*residual_words, *description_words)
        )
        residual_left = min(word.bbox[0] for word in residual_words)
        residual_right = max(word.bbox[2] for word in residual_words)
        residual_width = residual_right - residual_left
        description_band = description_columns[0].bbox
        overlap = max(
            0.0,
            min(residual_right, description_band[2]) - max(residual_left, description_band[0]),
        )
        spills_into_description_band = (
            residual_width > 0 and overlap / residual_width >= _MIN_DESCRIPTION_SPILL_OVERLAP
        )
        is_geometrically_adjacent = typical_height > 0 and 0 <= gap <= typical_height * 0.6
        has_same_line_description_adjacency = typical_height > 0 and any(
            abs(bbox_center_y(residual_word.bbox) - bbox_center_y(description_word.bbox))
            <= typical_height * 0.2
            and (
                (
                    description_on_right
                    and 0
                    <= description_word.bbox[0] - residual_word.bbox[2]
                    <= typical_height * 0.6
                )
                or (
                    not description_on_right
                    and 0
                    <= residual_word.bbox[0] - description_word.bbox[2]
                    <= typical_height * 0.6
                )
            )
            for residual_word in residual_words
            for description_word in description_words
        )
        residual_top = min(word.bbox[1] for word in residual_words)
        has_shared_wrapped_description_origin = (
            typical_height > 0
            and horizontal_overlap > 0
            and vertical_overlap(original_cell.bbox, description_cell.bbox) > 0
            and (
                (
                    description_on_right
                    and residual_left < description_band[0]
                    and residual_right <= description_band[0] + typical_height * 0.2
                    and any(
                        abs(word.bbox[0] - residual_left) <= typical_height * 0.2
                        and word.bbox[1] >= residual_top + typical_height * 0.5
                        for word in description_words
                    )
                )
                or (
                    not description_on_right
                    and residual_right > description_band[2]
                    and residual_left >= description_band[2] - typical_height * 0.2
                    and any(
                        abs(word.bbox[2] - residual_right) <= typical_height * 0.2
                        and word.bbox[1] >= residual_top + typical_height * 0.5
                        for word in description_words
                    )
                )
            )
        )
        residual_signature = tuple(
            (
                unicodedata.normalize("NFC", word.text).casefold(),
                word.source,
                word.confidence,
            )
            for word in residual_words
            if any(char.isalnum() for char in word.text)
        )
        description_signature = tuple(
            (
                unicodedata.normalize("NFC", word.text).casefold(),
                word.source,
                word.confidence,
            )
            for word in description_words
            if any(char.isalnum() for char in word.text)
        )
        duplicate_is_separate = (
            residual_right < min(word.bbox[0] for word in description_words)
            if description_on_right
            else residual_left > max(word.bbox[2] for word in description_words)
        )
        has_exact_distant_duplicate = (
            bool(residual_signature)
            and residual_signature == description_signature
            and duplicate_is_separate
        )
        has_bounded_note_corroboration = (
            parsed.amount,
            parsed.currency,
        ) in corroborated_amounts
        if (
            not is_geometrically_adjacent
            and not has_same_line_description_adjacency
            and not spills_into_description_band
            and not has_shared_wrapped_description_origin
            and not has_exact_distant_duplicate
            and not has_bounded_note_corroboration
        ):
            continue
        candidates.append(
            (parsed, residual_text, description_on_right, has_exact_distant_duplicate)
        )
    unique = {
        (
            candidate[0].amount,
            candidate[0].currency,
            candidate[1],
            candidate[2],
            candidate[3],
        ): candidate
        for candidate in candidates
    }
    return next(iter(unique.values())) if len(unique) == 1 else None


def _description_spill_atom_ids(
    ledger: EvidenceLedger,
    cell: Cell,
    text: str,
) -> frozenset[int]:
    normalized_target = " ".join(phrase_tokens(text))
    target_tokens = frozenset(normalized_target.split())
    return frozenset(
        atom_id
        for atom_id in ledger.atoms_for_cell(cell)
        if any(char.isalpha() for char in ledger.atoms[atom_id].text)
        and (
            (atom_text := " ".join(phrase_tokens(ledger.atoms[atom_id].text))) in target_tokens
            or atom_text in normalized_target
            or normalized_target in atom_text
        )
    )


def _new_description_claim(
    *,
    ledger: EvidenceLedger,
    cell: Cell,
    text: str,
    initial_claims: Sequence[EvidenceClaim],
) -> EvidenceClaim | None:
    already_claimed = frozenset(atom_id for claim in initial_claims for atom_id in claim.atom_ids)
    remaining = _description_spill_atom_ids(ledger, cell, text) - already_claimed
    return EvidenceClaim(SemanticOwner.DESCRIPTION, remaining) if remaining else None


def extract_original_amount(
    *,
    row: Row,
    continuation_rows: Sequence[Row],
    region: TableRegion,
    ledger: EvidenceLedger,
    billed: BilledFields,
    description: str | None,
    initial_claims: Sequence[EvidenceClaim],
) -> OriginalAmountExtraction:
    """Extract one original value while preserving bounded recovery precedence."""

    if billed.amount is None or billed.currency is None:
        raise RuntimeError("accepted billed fields must contain complete source values")

    diagnostics: list[str] = []
    claims: list[EvidenceClaim] = []
    amount: Decimal | None = None
    currency: str | None = None
    original_columns = columns_for_role(region.table_schema, ColumnRole.ORIGINAL_AMOUNT)
    if len(original_columns) > 1:
        diagnostics.append("multiple_original_amount_columns")
    elif len(original_columns) == 1:
        original_cells = cells_in_column(row.cells, original_columns[0])
        original_currency_columns = columns_for_role(
            region.table_schema,
            ColumnRole.ORIGINAL_CURRENCY,
        )
        if len(original_cells) != 1:
            negative_adjustment_without_original = (
                not original_cells and billed.amount < 0 and not original_currency_columns
            )
            if not negative_adjustment_without_original:
                diagnostics.append(
                    "missing_original_amount_cell"
                    if not original_cells
                    else "multiple_original_amount_cells"
                )
        else:
            original_currency_hint = _proven_implicit_original_currency(
                region,
                billed.currency,
            )
            if len(original_currency_columns) > 1:
                diagnostics.append("multiple_original_currency_columns")
            elif len(original_currency_columns) == 1:
                original_currency_cells = cells_in_column(
                    row.cells,
                    original_currency_columns[0],
                )
                if len(original_currency_cells) != 1:
                    diagnostics.append(
                        "missing_original_currency_cell"
                        if not original_currency_cells
                        else "multiple_original_currency_cells"
                    )
                else:
                    original_currency_hint = canonical_currency(original_currency_cells[0].text)
                    if original_currency_hint is None:
                        diagnostics.append("unknown_original_currency")
            elif original_currency_hint is None:
                location_columns = columns_for_role(
                    region.table_schema,
                    ColumnRole.LOCATION,
                )
                if len(location_columns) == 1:
                    location_cells = cells_in_column(row.cells, location_columns[0])
                    spilled_currencies = {
                        spilled
                        for cell in location_cells
                        if (
                            spilled := original_currency_spilled_into_location(
                                cell,
                                region,
                            )
                        )
                        is not None
                    }
                    if len(spilled_currencies) == 1:
                        original_currency_hint = next(iter(spilled_currencies))
            original = parse_amount(
                original_cells[0].text,
                currency_hint=original_currency_hint,
            )
            if original.amount is None or original.currency is None:
                corroborated = _ocr_original_amount_corroborated_by_billed(
                    original_cells[0],
                    original,
                    original_currency_hint,
                    billed,
                )
                if corroborated is not None:
                    original = corroborated
            if original.amount is None or original.currency is None:
                recovered_detail = _original_amount_from_subordinate_detail(
                    original_cells[0],
                    original,
                    original_currency_hint,
                    continuation_rows,
                )
                if recovered_detail is not None:
                    original = recovered_detail
            if original.amount is None or original.currency is None:
                recovered = _amount_from_exact_words_between_boundary_glyphs(
                    original_cells[0],
                    original_columns[0],
                    original_currency_hint,
                )
                if recovered is not None:
                    original = recovered
            if original.amount is None or original.currency is None:
                spill = _original_amount_with_description_spill(
                    row,
                    region,
                    original_cells[0],
                    original_currency_hint,
                    _bounded_note_original_amounts(continuation_rows),
                )
                if spill is not None:
                    original, spill_text, description_on_right, already_in_description = spill
                    claim = _new_description_claim(
                        ledger=ledger,
                        cell=original_cells[0],
                        text=spill_text,
                        initial_claims=(*initial_claims, *claims),
                    )
                    if claim is not None:
                        claims.append(claim)
                    if not already_in_description:
                        if description is None:
                            description = spill_text
                        elif description_on_right:
                            description = normalize_text(f"{spill_text} {description}")
                        else:
                            description = normalize_text(f"{description} {spill_text}")
            if original.amount is None or original.currency is None:
                diagnostics.extend(
                    f"original_amount:{diagnostic}" for diagnostic in original.diagnostics
                )
            else:
                amount = original.amount
                currency = original.currency

    return OriginalAmountExtraction(
        amount=amount,
        currency=currency,
        description=description,
        claims=tuple(claims),
        diagnostics=tuple(diagnostics),
    )


__all__ = [
    "OriginalAmountExtraction",
    "extract_original_amount",
    "original_currency_spilled_into_location",
]
