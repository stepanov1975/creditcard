"""Geometry-bounded OCR repair for damaged numeric table evidence."""

from __future__ import annotations

import hashlib
import math
import re
import statistics
from collections.abc import Sequence
from decimal import Decimal

from ccparser.evidence.models import DocumentEvidence, PageEvidence, Word
from ccparser.evidence.provider import OcrProvider
from ccparser.geometry import (
    BBox,
    center_inside,
)
from ccparser.geometry import (
    bbox_center_y as _center_y,
)
from ccparser.geometry import (
    bbox_height as _height,
)
from ccparser.layout.columns import (
    cells_in_column,
    columns_for_role,
    explicit_billed_amount_column,
    is_date_shaped,
)
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableSchema
from ccparser.layout.regions import (
    _candidate_schema,
    _is_total_row,
    _literal_header_role_count,
    _merged_header_bands,
    _plausible_header,
    _project_row_to_header_bands,
    _row_intersects_horizontal_band,
    logical_rows,
)
from ccparser.layout.text import logical_text_for_evidence
from ccparser.money import canonical_currency, is_currency_shaped, parse_amount

_DECIMAL_AMOUNT_PATTERN = re.compile(r"[.,]\d{1,2}(?!\d)")


def _clip_key(clip: BBox) -> BBox:
    return (
        round(clip[0], 6),
        round(clip[1], 6),
        round(clip[2], 6),
        round(clip[3], 6),
    )


def _sole_billed_column(schema: TableSchema) -> ColumnSpec | None:
    explicit = explicit_billed_amount_column(schema.columns, schema.header_cells)
    if explicit is not None:
        return explicit
    amount_columns = columns_for_role(schema, ColumnRole.AMOUNT)
    return amount_columns[0] if len(amount_columns) == 1 else None


def _header_cell_for_column(header: Row, column: ColumnSpec) -> Cell | None:
    cells = cells_in_column(header.cells, column)
    return cells[0] if len(cells) == 1 else None


def _transaction_context_cells(
    row: Row,
    schema: TableSchema,
    billed_column: ColumnSpec,
) -> tuple[Cell, ...] | None:
    date_columns = columns_for_role(schema, ColumnRole.DATE)
    description_columns = columns_for_role(schema, ColumnRole.DESCRIPTION)
    if len(date_columns) != 1 or len(description_columns) > 1:
        return None
    date_cells = cells_in_column(row.cells, date_columns[0])
    description_cells = (
        cells_in_column(row.cells, description_columns[0])
        if description_columns
        else tuple(
            cell
            for cell in row.cells
            if any(char.isalpha() for char in cell.text)
            and cell not in date_cells
            and cell not in cells_in_column(row.cells, billed_column)
        )
    )
    if (
        len(date_cells) != 1
        or not is_date_shaped(date_cells[0].text)
        or len(description_cells) != 1
        or not any(char.isalpha() for char in description_cells[0].text)
    ):
        return None
    return date_cells[0], description_cells[0]


def _representative_vertical_clip(
    page: PageEvidence,
    context_cells: Sequence[Cell],
    amount_header: Cell,
) -> BBox:
    center = statistics.median(_center_y(cell.bbox) for cell in context_cells)
    typical_height = statistics.median(_height(cell.bbox) for cell in context_cells)
    vertical_padding = typical_height * 0.4
    horizontal_padding = max(_height(amount_header.bbox), typical_height)
    return (
        max(0.0, amount_header.bbox[0] - horizontal_padding * 0.2),
        max(0.0, center - typical_height / 2 - vertical_padding),
        min(page.width, amount_header.bbox[2] + horizontal_padding * 0.3),
        min(page.height, center + typical_height / 2 + vertical_padding),
    )


def _amount_cell_clip(
    page: PageEvidence,
    amount_header: Cell,
    amount_cell: Cell,
) -> BBox:
    typical_height = _height(amount_cell.bbox)
    horizontal_padding = max(_height(amount_header.bbox), typical_height)
    vertical_padding = typical_height * 0.55
    return (
        max(0.0, amount_header.bbox[0] - horizontal_padding * 0.25),
        max(0.0, amount_cell.bbox[1] - vertical_padding),
        min(page.width, amount_header.bbox[2] + horizontal_padding * 0.4),
        min(page.height, amount_cell.bbox[3] + vertical_padding),
    )


def _unique_currency_hint(currency_hints: Sequence[str]) -> str | None:
    canonical = {
        currency for hint in currency_hints if (currency := canonical_currency(hint)) is not None
    }
    return next(iter(canonical)) if len(canonical) == 1 else None


def _target_amount_words(
    words: Sequence[Word],
    currency_hint: str,
) -> tuple[Word, ...] | None:
    candidates = []
    for word in words:
        parsed = parse_amount(word.text, currency_hint=currency_hint)
        if parsed.amount is not None and parsed.currency == currency_hint:
            candidates.append((word, parsed.amount))
    distinct_amounts = {amount for _, amount in candidates}
    if len(distinct_amounts) != 1:
        return None
    amount = next(iter(distinct_amounts))
    amount_word = max(
        (word for word, candidate_amount in candidates if candidate_amount == amount),
        key=lambda word: (word.confidence, -word.bbox[0], word.text),
    )
    currency_words = tuple(
        word
        for word in words
        if is_currency_shaped(word.text) and canonical_currency(word.text) == currency_hint
    )
    retained = (*currency_words, amount_word)
    return tuple(dict.fromkeys(sorted(retained, key=lambda word: (word.bbox[0], word.bbox[1]))))


def _corroborated_target_amount_words(
    provider: OcrProvider,
    pdf_bytes: bytes,
    source_sha256: str,
    page_index: int,
    clip: BBox,
    currency_hint: str,
) -> tuple[Word, ...] | None:
    variants = tuple(
        dict.fromkeys(
            (
                clip,
                (
                    float(math.ceil(clip[0])),
                    float(math.ceil(clip[1])),
                    float(math.floor(clip[2])),
                    float(math.floor(clip[3])),
                ),
                (
                    float(math.floor(clip[0])),
                    float(math.floor(clip[1])),
                    float(math.ceil(clip[2])),
                    float(math.ceil(clip[3])),
                ),
            )
        )
    )
    candidates: list[tuple[tuple[Word, ...], Decimal, float]] = []
    for variant in variants:
        if variant[0] >= variant[2] or variant[1] >= variant[3]:
            continue
        words = _target_amount_words(
            provider.extract_words(
                pdf_bytes,
                source_sha256,
                page_index,
                variant,
            ),
            currency_hint,
        )
        if words is None:
            continue
        parsed = parse_amount(
            logical_text_for_evidence((), words),
            currency_hint=currency_hint,
        )
        if parsed.amount is None or parsed.currency != currency_hint:
            continue
        numeric_confidence = max(
            word.confidence for word in words if any(char.isdigit() for char in word.text)
        )
        candidates.append((words, parsed.amount, numeric_confidence))
    if not candidates or len({amount for _, amount, _ in candidates}) != 1:
        return None
    selected = max(
        candidates,
        key=lambda item: (
            item[2],
            len(item[0]),
            tuple((word.text, word.bbox) for word in item[0]),
        ),
    )
    if selected[2] < 0.8 and len(candidates) < 2:
        return None
    return selected[0]


def _digit_count(text: str) -> int:
    return sum(char.isdigit() for char in text)


def _structural_improvement(
    old_text: str,
    target_words: Sequence[Word],
    currency_hint: str,
) -> bool:
    target_text = logical_text_for_evidence((), target_words)
    target = parse_amount(target_text, currency_hint=currency_hint)
    if target.amount is None or target.currency != currency_hint:
        return False
    old = parse_amount(old_text, currency_hint=currency_hint)
    if old.amount is None or old.currency is None:
        return True
    if old.amount == target.amount:
        return False
    return (
        _DECIMAL_AMOUNT_PATTERN.search(target_text) is not None
        and _DECIMAL_AMOUNT_PATTERN.search(old_text) is None
    ) or _digit_count(target_text) > _digit_count(old_text)


def _replace_words_in_clip(
    words: Sequence[Word],
    clip: BBox,
    replacements: Sequence[Word],
) -> tuple[Word, ...]:
    retained = tuple(
        word for word in words if not (word.source == "ocr" and center_inside(word.bbox, clip))
    )
    return (*retained, *replacements)


def _repair_page(
    page: PageEvidence,
    pdf_bytes: bytes,
    source_sha256: str,
    provider: OcrProvider,
    currency_hint: str,
    expected_totals: frozenset[Decimal],
) -> PageEvidence:
    if not page.quality.requires_ocr:
        return page
    rows = _merged_header_bands(logical_rows(page))
    words = page.words
    repaired_keys: set[tuple[float, float, float, float]] = set()
    for header_index, header in enumerate(rows):
        schema = _candidate_schema(page.model_copy(update={"words": words}), rows, header_index)
        if not _plausible_header(schema):
            continue
        billed_column = _sole_billed_column(schema)
        if billed_column is None:
            continue
        amount_header = _header_cell_for_column(header, billed_column)
        if amount_header is None:
            continue
        for source_row in rows[header_index + 1 :]:
            if _is_total_row(source_row):
                current_page = page.model_copy(update={"words": words})
                projected_total = _project_row_to_header_bands(
                    current_page,
                    source_row,
                    header,
                )
                total_amount_cells = cells_in_column(projected_total.cells, billed_column)
                if len(total_amount_cells) == 1:
                    old_text = total_amount_cells[0].text
                    old = parse_amount(old_text, currency_hint=currency_hint)
                    if (
                        old.amount is None
                        or old.currency is None
                        or _DECIMAL_AMOUNT_PATTERN.search(old_text) is None
                    ):
                        clip = _amount_cell_clip(
                            current_page,
                            amount_header,
                            total_amount_cells[0],
                        )
                        clip_key = _clip_key(clip)
                        if clip_key not in repaired_keys:
                            repaired_keys.add(clip_key)
                            targeted = _corroborated_target_amount_words(
                                provider,
                                pdf_bytes,
                                source_sha256,
                                page.page_number - 1,
                                clip,
                                currency_hint,
                            )
                            if targeted is not None and _structural_improvement(
                                old_text,
                                targeted,
                                currency_hint,
                            ):
                                words = _replace_words_in_clip(words, clip, targeted)
                continue
            if _literal_header_role_count(source_row) >= 2:
                break
            if not _row_intersects_horizontal_band(source_row, header.bbox):
                continue
            current_page = page.model_copy(update={"words": words})
            projected = _project_row_to_header_bands(current_page, source_row, header)
            context_cells = _transaction_context_cells(projected, schema, billed_column)
            if context_cells is None:
                continue
            amount_cells = cells_in_column(projected.cells, billed_column)
            old_text = amount_cells[0].text if len(amount_cells) == 1 else ""
            old = parse_amount(old_text, currency_hint=currency_hint)
            if (
                old.amount is not None
                and old.currency is not None
                and _DECIMAL_AMOUNT_PATTERN.search(old_text) is not None
            ):
                continue
            clip = _representative_vertical_clip(current_page, context_cells, amount_header)
            clip_key = _clip_key(clip)
            if clip_key in repaired_keys:
                continue
            repaired_keys.add(clip_key)
            targeted = _corroborated_target_amount_words(
                provider,
                pdf_bytes,
                source_sha256,
                page.page_number - 1,
                clip,
                currency_hint,
            )
            if targeted is None or not _structural_improvement(
                old_text,
                targeted,
                currency_hint,
            ):
                continue
            words = _replace_words_in_clip(words, clip, targeted)
    if expected_totals:
        current_page = page.model_copy(update={"words": words})
        summary_rows = logical_rows(current_page)
        for row_index, row in enumerate(summary_rows):
            if not _is_total_row(row):
                continue
            for following in summary_rows[row_index + 1 :]:
                if following.bbox[1] - row.bbox[3] > current_page.height * 0.2:
                    break
                if _literal_header_role_count(following) >= 2:
                    break
                repaired_summary = False
                for word in following.words:
                    if word.source != "ocr" or _DECIMAL_AMOUNT_PATTERN.search(word.text) is None:
                        continue
                    old = parse_amount(word.text, currency_hint=currency_hint)
                    if old.amount in expected_totals and old.currency == currency_hint:
                        continue
                    padding = _height(word.bbox) * 0.15
                    clip = (
                        max(0.0, word.bbox[0] - padding),
                        max(0.0, word.bbox[1] - padding),
                        min(current_page.width, word.bbox[2] + padding),
                        min(current_page.height, word.bbox[3] + padding),
                    )
                    targeted = _corroborated_target_amount_words(
                        provider,
                        pdf_bytes,
                        source_sha256,
                        page.page_number - 1,
                        clip,
                        currency_hint,
                    )
                    if targeted is None:
                        continue
                    parsed = parse_amount(
                        logical_text_for_evidence((), targeted),
                        currency_hint=currency_hint,
                    )
                    if parsed.amount not in expected_totals or parsed.currency != currency_hint:
                        continue
                    words = _replace_words_in_clip(words, clip, targeted)
                    repaired_summary = True
                    break
                if repaired_summary:
                    current_page = page.model_copy(update={"words": words})
    return page.model_copy(update={"words": words})


def repair_table_numeric_ocr(
    evidence: DocumentEvidence,
    pdf_bytes: bytes,
    provider: OcrProvider,
    *,
    currency_hints: Sequence[str],
    expected_totals: Sequence[Decimal] = (),
) -> DocumentEvidence:
    """Retry only suspicious image-table amount cells in their proven header band."""

    if hashlib.sha256(pdf_bytes).hexdigest() != evidence.source_sha256:
        raise ValueError("source SHA-256 does not match document evidence")
    currency_hint = _unique_currency_hint(currency_hints)
    if currency_hint is None:
        return evidence
    canonical_expected_totals = frozenset(expected_totals)
    pages = tuple(
        _repair_page(
            page,
            pdf_bytes,
            evidence.source_sha256,
            provider,
            currency_hint,
            canonical_expected_totals,
        )
        for page in evidence.pages
    )
    return evidence if pages == evidence.pages else evidence.model_copy(update={"pages": pages})


__all__ = ["repair_table_numeric_ocr"]
