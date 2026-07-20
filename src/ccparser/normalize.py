"""Pure monetary parsing and geometry-driven transaction normalization."""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from decimal import Decimal
from itertools import pairwise

from pydantic import BaseModel, ConfigDict, Field

from ccparser.discovery import (
    DateTokenStyle,
    DiscoveredDateYearContext,
    StatementDiscovery,
    StatementGroupDiscovery,
)
from ccparser.evidence.models import BBox, Glyph, Word
from ccparser.layout.columns import isolated_date_token, proven_billed_amount_column
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableRegion
from ccparser.layout.text import logical_text_for_evidence
from ccparser.models import (
    EvidenceReference,
    PrintedTotal,
    StatementResult,
    Status,
    Transaction,
    TransactionCategory,
    TransactionKind,
)
from ccparser.money import (
    AmountParseResult,
    canonical_currency,
    currencies_in_text,
    is_currency_shaped,
    is_money_shaped,
    parse_amount,
)
from ccparser.reconcile import reconcile
from ccparser.semantic_evidence import (
    DescriptionExtraction,
    EvidenceClaim,
    EvidenceCluster,
    EvidenceLedger,
    SemanticOwner,
)


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
    reconciliation: StatementResult
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()


_CATEGORY_VOCABULARY: tuple[tuple[TransactionCategory, tuple[str, ...]], ...] = (
    (TransactionCategory.REFUND, ("credit", "refund", "זיכוי", "החזר")),
    (TransactionCategory.INTEREST, ("interest", "ריבית")),
    (TransactionCategory.FEE, ("commission", "fee", "עמלה", "דמי")),
    (TransactionCategory.ADJUSTMENT, ("adjustment", "correction", "התאמה", "תיקון")),
    (TransactionCategory.PURCHASE, ("purchase", "purchased", "רכישה", "קנייה", "עסקה")),
)
_DATE_PATTERN = re.compile(r"^(\d{1,4})\s*([./-])\s*(\d{1,2})\s*\2\s*(\d{1,4})$")
_DATE_TOKEN_PATTERN = re.compile(
    r"(?<!\d)\d{1,4}\s*(?P<separator>[./-])\s*\d{1,2}\s*"
    r"(?P=separator)\s*\d{1,4}(?!\d)"
)
_MIN_SUPPORTED_FULL_DATE_YEAR = 1900
_MAX_SUPPORTED_FULL_DATE_YEAR = 2100
_SHORT_DATE_TOKEN_PATTERNS: dict[DateTokenStyle, re.Pattern[str]] = {
    DateTokenStyle.DAY_FIRST_SLASH: re.compile(
        r"(?<!\d)(?P<day>\d{1,2})\s*/\s*(?P<month>\d{1,2})\s*/\s*(?P<year>\d{2})(?!\d)"
    ),
    DateTokenStyle.DAY_FIRST_DOT: re.compile(
        r"(?<!\d)(?P<day>\d{1,2})\s*\.\s*(?P<month>\d{1,2})\s*\.\s*(?P<year>\d{2})(?!\d)"
    ),
    DateTokenStyle.DAY_FIRST_DASH: re.compile(
        r"(?<!\d)(?P<day>\d{1,2})\s*-\s*(?P<month>\d{1,2})\s*-\s*(?P<year>\d{2})(?!\d)"
    ),
    DateTokenStyle.YEAR_FIRST_SLASH: re.compile(
        r"(?<!\d)(?P<year>\d{2})\s*/\s*(?P<month>\d{1,2})\s*/\s*(?P<day>\d{1,2})(?!\d)"
    ),
    DateTokenStyle.YEAR_FIRST_DOT: re.compile(
        r"(?<!\d)(?P<year>\d{2})\s*\.\s*(?P<month>\d{1,2})\s*\.\s*(?P<day>\d{1,2})(?!\d)"
    ),
    DateTokenStyle.YEAR_FIRST_DASH: re.compile(
        r"(?<!\d)(?P<year>\d{2})\s*-\s*(?P<month>\d{1,2})\s*-\s*(?P<day>\d{1,2})(?!\d)"
    ),
}
_INSTALLMENT_PATTERN = re.compile(r"^(\d{1,3})\s*/\s*(\d{1,3})$")
_LOCATION_IDENTIFIER_PATTERN = re.compile(r"^\d{10}$")
_CARD_IDENTIFIER_PATTERN = re.compile(r"^\d{4,10}$")
_CARD_IDENTIFIER_MARKERS = ("card id", "card identifier", "מזהה כרטיס")
_MIN_DESCRIPTION_SPILL_OVERLAP = 0.2
_MIN_DATE_DESCRIPTION_CELL_OVERLAP = 0.08
_HEBREW_GERSHAYIM_PATTERN = re.compile(r'(?<=[\u0590-\u05ff])\s*"\s*(?=[\u0590-\u05ff])')
_SINGLE_RTL_PARENTHETICAL_PATTERN = re.compile(r"^[()]\s*([\u0590-\u05ff])$")


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


def _center_x(bbox: BBox) -> float:
    return (bbox[0] + bbox[2]) / 2


def _bbox_center_inside(candidate: BBox, container: BBox) -> bool:
    center_x = (candidate[0] + candidate[2]) / 2
    center_y = (candidate[1] + candidate[3]) / 2
    return container[0] <= center_x <= container[2] and container[1] <= center_y <= container[3]


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


def _proven_billed_amount_column(region: TableRegion) -> ColumnSpec | None:
    transaction_rows = tuple(
        row for row in region.rows if "subordinate_detail_continuation" not in row.diagnostics
    )
    return proven_billed_amount_column(region.table_schema, transaction_rows)


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
    word_bbox = (
        min(word.bbox[0] for word in cell.words),
        min(word.bbox[1] for word in cell.words),
        max(word.bbox[2] for word in cell.words),
        max(word.bbox[3] for word in cell.words),
    )
    if not (column.bbox[0] <= word_bbox[0] and word_bbox[2] <= column.bbox[2]):
        return None
    word_text = " ".join(word.text for word in cell.words)
    parsed = parse_amount(word_text, currency_hint=currency_hint)
    if parsed.amount is None or parsed.currency is None:
        return None
    compact_cell = "".join(_normalized_text(cell.text).split())
    compact_words = "".join(_normalized_text(word_text).split())
    if compact_cell.count(compact_words) != 1:
        return None
    boundary_glyphs = tuple(
        glyph
        for glyph in cell.glyphs
        if not glyph.char.isspace() and not _bbox_center_inside(glyph.bbox, word_bbox)
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
    original_columns = _role_columns(region, ColumnRole.ORIGINAL_AMOUNT)
    if (
        len(original_columns) != 1
        or _role_columns(region, ColumnRole.ORIGINAL_CURRENCY)
        or (billed_column := _proven_billed_amount_column(region)) is None
    ):
        return None
    transaction_rows = tuple(
        row
        for row in region.rows
        if "subordinate_detail_continuation" not in row.diagnostics
        and len(_cells_for_column(row, billed_column)) == 1
    )
    has_conversion_evidence = any(
        _role_columns(region, role)
        for role in (
            ColumnRole.CONVERSION_DATE,
            ColumnRole.EXCHANGE_RATE,
            ColumnRole.CURRENCY,
        )
    )
    minimum_proven_rows = 2 if has_conversion_evidence else 1
    if len(transaction_rows) < minimum_proven_rows:
        return None
    proven_row_count = 0
    for row in transaction_rows:
        original_cells = _cells_for_column(row, original_columns[0])
        billed_cells = _cells_for_column(row, billed_column)
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


def _is_relevant_cell(cell: Cell) -> bool:
    text = _normalized_text(cell.text)
    return (
        is_money_shaped(text)
        or is_currency_shaped(text)
        or _DATE_PATTERN.fullmatch(text) is not None
        or _INSTALLMENT_PATTERN.fullmatch(text) is not None
    )


def _is_safe_card_identifier_cell(row: Row, cell: Cell) -> bool:
    identifiers = tuple(
        candidate
        for candidate in row.cells
        if _CARD_IDENTIFIER_PATTERN.fullmatch(_normalized_text(candidate.text)) is not None
    )
    return (
        len(identifiers) == 1
        and identifiers[0] is cell
        and _contains_marker(
            " ".join(candidate.text for candidate in row.cells),
            _CARD_IDENTIFIER_MARKERS,
        )
    )


def _is_isolated_ocr_edge_artifact_cell(
    cell: Cell,
    column: ColumnSpec,
    region: TableRegion,
) -> bool:
    columns = region.table_schema.columns
    header_cells = tuple(
        candidate
        for candidate in region.table_schema.header_cells
        if candidate in column.source_cells
    )
    relevant_column_cells = tuple(
        candidate
        for candidate_row in region.rows
        for candidate in _cells_for_column(candidate_row, column)
        if _is_relevant_cell(candidate)
    )
    header_is_bounded_ocr_artifact = (
        len(header_cells) == 1
        and bool(header_cells[0].words)
        and all(word.source == "ocr" for word in header_cells[0].words)
        and not any(char.isdigit() for char in header_cells[0].text)
        and sum(char.isalpha() for char in header_cells[0].text) <= 5
    )
    return (
        column.role is ColumnRole.UNKNOWN
        and column.index
        in {min(item.index for item in columns), max(item.index for item in columns)}
        and len(header_cells) == 1
        and (
            not any(char.isalnum() for char in header_cells[0].text)
            or header_is_bounded_ocr_artifact
        )
        and bool(cell.words)
        and all(word.source == "ocr" for word in cell.words)
        and sum(char.isalnum() for char in cell.text) <= 1
        and relevant_column_cells == (cell,)
    )


def _original_currency_spilled_into_location(
    cell: Cell,
    region: TableRegion,
) -> str | None:
    original_columns = _role_columns(region, ColumnRole.ORIGINAL_AMOUNT)
    location_columns = _role_columns(region, ColumnRole.LOCATION)
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
    residual_text = _normalized_text(" ".join(word.text for word in residual_words))
    has_proven_location_value = (
        len(residual_words) == 1
        and _LOCATION_IDENTIFIER_PATTERN.fullmatch(residual_text) is not None
    ) or (
        any(char.isalpha() for char in residual_text)
        and not any(char.isdigit() for char in residual_text)
        and not is_money_shaped(residual_text)
        and not is_currency_shaped(residual_text)
        and _DATE_PATTERN.fullmatch(residual_text) is None
    )
    if not has_proven_location_value:
        return None
    compact_cell = "".join(_normalized_text(cell.text).split())
    compact_words = "".join(
        "".join(_normalized_text(word.text).split())
        for word in sorted(cell.words, key=lambda word: word.bbox[0])
    )
    original_on_left = _center_x(original_columns[0].bbox) < _center_x(location_columns[0].bbox)
    description_columns = _role_columns(region, ColumnRole.DESCRIPTION)
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
    residual_edge_center = _center_x(
        (
            min(word.bbox[0] for word in residual_words),
            min(word.bbox[1] for word in residual_words),
            max(word.bbox[2] for word in residual_words),
            max(word.bbox[3] for word in residual_words),
        )
    )
    currency_on_original_edge = (
        _center_x(currency_word.bbox) < residual_edge_center
        if original_on_left
        else _center_x(currency_word.bbox) > residual_edge_center
    )
    return canonical_currency(currency_word.text) if currency_on_original_edge else None


def _assignment_diagnostics(row: Row, region: TableRegion) -> tuple[str, ...]:
    diagnostics: list[str] = []
    for cell in row.cells:
        columns = tuple(
            column
            for column in region.table_schema.columns
            if column.bbox[0] <= _center_x(cell.bbox) <= column.bbox[2]
        )
        relevant = _is_relevant_cell(cell)
        if len(columns) != 1:
            diagnostics.append("unmatched_cell" if not columns else "multiply_assigned_cell")
            if relevant:
                diagnostics.append("unresolved_relevant_cell")
            continue
        column = columns[0]
        safe_card_identifier = column.role is ColumnRole.UNKNOWN and _is_safe_card_identifier_cell(
            row, cell
        )
        safe_edge_artifact = _is_isolated_ocr_edge_artifact_cell(cell, column, region)
        safe_location_identifier = column.role is ColumnRole.LOCATION and (
            _LOCATION_IDENTIFIER_PATTERN.fullmatch(_normalized_text(cell.text)) is not None
            or _original_currency_spilled_into_location(cell, region) is not None
        )
        has_alternative = any(
            value == "ambiguous_role" or value.startswith("alternative_role:")
            for value in column.diagnostics
        )
        if (
            relevant
            and column.role is ColumnRole.UNKNOWN
            and not safe_card_identifier
            and not safe_edge_artifact
        ):
            diagnostics.append(f"column:{column.index}:role_unknown")
        if relevant and column.role is ColumnRole.LOCATION and not safe_location_identifier:
            diagnostics.append(f"column:{column.index}:unexpected_location_value")
        if relevant and has_alternative and not safe_card_identifier and not safe_edge_artifact:
            diagnostics.extend(
                f"column:{column.index}:{value}"
                for value in column.diagnostics
                if value == "ambiguous_role" or value.startswith("alternative_role:")
            )
        if relevant and (
            (
                column.role is ColumnRole.UNKNOWN
                and not safe_card_identifier
                and not safe_edge_artifact
            )
            or (has_alternative and not safe_card_identifier and not safe_edge_artifact)
            or (column.role is ColumnRole.LOCATION and not safe_location_identifier)
        ):
            diagnostics.append("unresolved_relevant_cell")
    return tuple(dict.fromkeys(diagnostics))


def _role_contract_diagnostics(region: TableRegion) -> tuple[str, ...]:
    role_columns: dict[ColumnRole, tuple[ColumnSpec, ...]] = {
        role: _role_columns(region, role) for role in ColumnRole if role is not ColumnRole.UNKNOWN
    }
    diagnostics: list[str] = []
    maximums = {
        ColumnRole.DATE: 2,
        ColumnRole.CONVERSION_DATE: 1,
        ColumnRole.DESCRIPTION: 1,
        ColumnRole.LOCATION: 1,
        ColumnRole.AMOUNT: 1,
        ColumnRole.ORIGINAL_AMOUNT: 1,
        ColumnRole.CURRENCY: 1,
        ColumnRole.BILLING_CURRENCY: 1,
        ColumnRole.ORIGINAL_CURRENCY: 1,
        ColumnRole.INSTALLMENT: 1,
    }
    for role, maximum in maximums.items():
        if len(role_columns[role]) > maximum and not (
            role is ColumnRole.AMOUNT and _proven_billed_amount_column(region) is not None
        ):
            diagnostics.append(f"unsupported_role_cardinality:{role.value}")
    if role_columns[ColumnRole.ORIGINAL_CURRENCY] and not role_columns[ColumnRole.ORIGINAL_AMOUNT]:
        diagnostics.append("original_currency_without_original_amount")
    return tuple(diagnostics)


def _row_evidence(rows: Sequence[Row]) -> tuple[EvidenceReference, ...]:
    return tuple(
        EvidenceReference(page_number=cell.page_number, bbox=cell.bbox, raw_text=cell.text)
        for row in rows
        for cell in row.cells
    )


def _row_text(rows: Sequence[Row]) -> str:
    return _normalized_text(" ".join(cell.text for row in rows for cell in row.cells))


def _parse_date(
    text: str,
    year_context: DiscoveredDateYearContext | None = None,
) -> tuple[date | None, str | None]:
    normalized = _normalized_text(text)
    full_date_matches = tuple(_DATE_TOKEN_PATTERN.finditer(normalized))
    if len(full_date_matches) > 1:
        return None, "ambiguous_date_tokens"
    isolated_token = isolated_date_token(normalized)
    if isolated_token is not None:
        normalized = isolated_token
    elif len(full_date_matches) == 1:
        boundary_match = full_date_matches[0]
        residual = normalized[: boundary_match.start()] + normalized[boundary_match.end() :]
        residual_chars = tuple(char for char in residual if not char.isspace())
        if (
            (boundary_match.start() == 0 or boundary_match.end() == len(normalized))
            and residual_chars
            and any(char.isalpha() for char in residual_chars)
            and all(
                char.isalpha() or unicodedata.category(char)[0] in {"M", "P"}
                for char in residual_chars
            )
        ):
            normalized = boundary_match.group(0)
    if year_context is not None:
        short_matches = tuple(_SHORT_DATE_TOKEN_PATTERNS[year_context.style].finditer(normalized))
        if len(short_matches) == 1:
            short_match = short_matches[0]
            suffix = int(short_match.group("year"))
            year_mapping = dict(year_context.year_by_suffix)
            if not year_mapping and year_context.year is not None:
                year_mapping[year_context.year % 100] = year_context.year
            resolved_year = year_mapping.get(suffix)
            if resolved_year is None:
                return None, "date_year_context_mismatch"
            try:
                return date(
                    resolved_year,
                    int(short_match.group("month")),
                    int(short_match.group("day")),
                ), None
            except ValueError:
                return None, "invalid_date"
        if len(short_matches) > 1:
            return None, "ambiguous_date_tokens"
    match = _DATE_PATTERN.fullmatch(normalized)
    if match is None:
        if _INSTALLMENT_PATTERN.fullmatch(normalized) is not None:
            return None, "ambiguous_date_or_installment"
        if year_context is None:
            return None, "invalid_date"
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


def _cell_has_ocr_evidence(cell: Cell) -> bool:
    return any(word.source == "ocr" for word in cell.words) or any(
        glyph.source == "ocr" for glyph in cell.glyphs
    )


def _parse_ocr_contaminated_cell_date(
    cell: Cell,
    year_context: DiscoveredDateYearContext | None,
) -> tuple[date | None, str | None]:
    if year_context is None or not _cell_has_ocr_evidence(cell):
        return None, "invalid_date"
    normalized = _normalized_text(cell.text)
    matches = tuple(_DATE_TOKEN_PATTERN.finditer(normalized))
    if len(matches) != 1:
        return None, "invalid_date"
    match = _DATE_PATTERN.fullmatch(matches[0].group(0))
    if match is None:
        return None, "invalid_date"
    first, separator, second, third = match.groups()
    candidates: list[str] = []
    if year_context.style in {
        DateTokenStyle.DAY_FIRST_SLASH,
        DateTokenStyle.DAY_FIRST_DOT,
        DateTokenStyle.DAY_FIRST_DASH,
    }:
        if len(first) == 4:
            candidates.append(f"{first[-2:]}{separator}{second}{separator}{third}")
        if len(third) == 4:
            candidates.append(f"{first}{separator}{second}{separator}{third[:2]}")
    repaired = {
        parsed_date
        for candidate in candidates
        if (parsed_date := _parse_date(candidate, year_context)[0]) is not None
    }
    return (next(iter(repaired)), None) if len(repaired) == 1 else (None, "invalid_date")


def _parse_cell_date(
    cell: Cell,
    year_context: DiscoveredDateYearContext | None,
) -> tuple[date | None, str | None]:
    parsed = _parse_date(cell.text, year_context)
    parsed_year_out_of_range = (
        parsed[0] is not None
        and _cell_has_ocr_evidence(cell)
        and not _MIN_SUPPORTED_FULL_DATE_YEAR <= parsed[0].year <= _MAX_SUPPORTED_FULL_DATE_YEAR
    )
    if parsed_year_out_of_range or parsed[1] == "invalid_date":
        repaired = _parse_ocr_contaminated_cell_date(cell, year_context)
        if repaired[0] is not None:
            return repaired
    if parsed_year_out_of_range:
        return None, "invalid_date"
    if parsed[1] != "invalid_date":
        return parsed
    word_candidates = tuple(
        candidate
        for word in cell.words
        if (candidate := _parse_date(word.text, year_context))[0] is not None
        and candidate[1] is None
    )
    return word_candidates[0] if len(word_candidates) == 1 else parsed


def _short_date_tokens(cell: Cell) -> tuple[str, ...]:
    tokens: list[str] = []
    for text in (cell.text, *(word.text for word in cell.words)):
        normalized = _normalized_text(text)
        tokens.extend(match.group(0) for match in _DATE_TOKEN_PATTERN.finditer(normalized))
    return tuple(dict.fromkeys(tokens))


def _valid_short_date_token_for_style(
    token: str,
    style: DateTokenStyle,
) -> re.Match[str] | None:
    match = _SHORT_DATE_TOKEN_PATTERNS[style].fullmatch(_normalized_text(token))
    if match is None:
        return None
    try:
        date(2000, int(match.group("month")), int(match.group("day")))
    except ValueError:
        return None
    return match


def _proven_unanchored_short_date_style(
    region: TableRegion,
    column: ColumnSpec,
) -> DateTokenStyle | None:
    amount_column = _proven_billed_amount_column(region)
    if amount_column is None:
        return None
    transaction_rows = tuple(
        row
        for row in region.rows
        if len(_cells_for_column(row, amount_column)) == 1
        and is_money_shaped(_cells_for_column(row, amount_column)[0].text)
    )
    if len(transaction_rows) < 2:
        return None
    tokens_by_row: list[str] = []
    for row in transaction_rows:
        tokens = tuple(
            dict.fromkeys(
                token
                for cell in row.cells
                if _horizontal_overlap(cell.bbox, column.bbox) > 0
                for token in _short_date_tokens(cell)
            )
        )
        if len(tokens) != 1:
            return None
        tokens_by_row.append(tokens[0])
    candidates: list[DateTokenStyle] = []
    for style in DateTokenStyle:
        matches = tuple(_valid_short_date_token_for_style(token, style) for token in tokens_by_row)
        if any(match is None for match in matches):
            continue
        suffixes = {int(match.group("year")) for match in matches if match is not None}
        if len(suffixes) == 1:
            candidates.append(style)
    return candidates[0] if len(candidates) == 1 else None


def _has_proven_unanchored_short_date(
    cell: Cell,
    style: DateTokenStyle | None,
) -> bool:
    if style is None:
        return False
    tokens = _short_date_tokens(cell)
    return len(tokens) == 1 and _valid_short_date_token_for_style(tokens[0], style) is not None


def _parse_overlapping_boundary_date(
    row: Row,
    column: ColumnSpec,
    assigned_cell: Cell,
    year_context: DiscoveredDateYearContext | None,
) -> tuple[date | None, str | None]:
    column_width = column.bbox[2] - column.bbox[0]
    if column_width <= 0:
        return None, "invalid_date"
    column_center = _center_x(column.bbox)
    candidates: dict[date, tuple[date, None]] = {}
    for cell in row.cells:
        if cell is assigned_cell:
            continue
        overlap = max(0.0, min(cell.bbox[2], column.bbox[2]) - max(cell.bbox[0], column.bbox[0]))
        if overlap / column_width < 0.8:
            continue
        cell_center = _center_x(cell.bbox)
        if column.bbox[0] <= cell_center <= column.bbox[2]:
            continue
        clipped_glyphs = tuple(
            glyph
            for glyph in cell.glyphs
            if column.bbox[0] <= _center_x(glyph.bbox) <= column.bbox[2]
        )
        if clipped_glyphs:
            clipped_date, clipped_diagnostic = _parse_date(
                logical_text_for_evidence(clipped_glyphs, ()),
                year_context,
            )
            if clipped_date is not None and clipped_diagnostic is None:
                candidates[clipped_date] = (clipped_date, None)
        normalized = _normalized_text(cell.text)
        matches = tuple(_DATE_TOKEN_PATTERN.finditer(normalized))
        if len(matches) != 1:
            continue
        match = matches[0]
        if cell_center < column_center and match.end() != len(normalized):
            continue
        if cell_center > column_center and match.start() != 0:
            continue
        parsed_date, diagnostic = _parse_date(match.group(0), year_context)
        if parsed_date is not None and diagnostic is None:
            candidates[parsed_date] = (parsed_date, None)
    return next(iter(candidates.values())) if len(candidates) == 1 else (None, "invalid_date")


def _glyph_identity(glyph: Glyph) -> tuple[object, ...]:
    return (
        glyph.char,
        glyph.bbox,
        glyph.origin,
        glyph.font,
        glyph.size,
        glyph.source,
        glyph.confidence,
    )


type _BoundaryDateCompletion = tuple[date, Cell, Glyph]


def _adjacent_boundary_date_completion(
    row: Row,
    column: ColumnSpec,
    assigned_cell: Cell,
    year_context: DiscoveredDateYearContext | None,
) -> _BoundaryDateCompletion | None:
    base_glyphs = tuple(glyph for glyph in assigned_cell.glyphs if not glyph.char.isspace())
    if not base_glyphs:
        return None
    base_text = logical_text_for_evidence(base_glyphs, ())
    if (
        _normalized_text(base_text) != _normalized_text(assigned_cell.text)
        or _parse_date(base_text, year_context)[0] is not None
    ):
        return None
    sources = {glyph.source for glyph in base_glyphs}
    if len(sources) != 1:
        return None
    typical_width = statistics.median(
        max(0.0, glyph.bbox[2] - glyph.bbox[0]) for glyph in base_glyphs
    )
    if typical_width <= 0:
        return None
    base_left = min(glyph.bbox[0] for glyph in base_glyphs)
    base_right = max(glyph.bbox[2] for glyph in base_glyphs)
    candidates: list[_BoundaryDateCompletion] = []
    for cell in row.cells:
        if cell is assigned_cell or column.bbox[0] <= _center_x(cell.bbox) <= column.bbox[2]:
            continue
        clipped = tuple(
            glyph
            for glyph in cell.glyphs
            if not glyph.char.isspace()
            and column.bbox[0] <= _center_x(glyph.bbox) <= column.bbox[2]
        )
        if len(clipped) != 1:
            continue
        glyph = clipped[0]
        if not glyph.char.isdigit() or glyph.source not in sources:
            continue
        vertical_overlap = max(
            0.0,
            min(assigned_cell.bbox[3], glyph.bbox[3]) - max(assigned_cell.bbox[1], glyph.bbox[1]),
        )
        smaller_height = min(_height(assigned_cell.bbox), _height(glyph.bbox))
        if smaller_height <= 0 or vertical_overlap / smaller_height < 0.8:
            continue
        adjacency_tolerance = typical_width * 0.35
        if glyph.bbox[0] >= base_right - adjacency_tolerance:
            gap = max(0.0, glyph.bbox[0] - base_right)
        elif glyph.bbox[2] <= base_left + adjacency_tolerance:
            gap = max(0.0, base_left - glyph.bbox[2])
        else:
            continue
        if gap > adjacency_tolerance:
            continue
        candidate_text = logical_text_for_evidence((*base_glyphs, glyph), ())
        parsed_date, diagnostic = _parse_date(candidate_text, year_context)
        if parsed_date is not None and diagnostic is None:
            candidates.append((parsed_date, cell, glyph))
    return candidates[0] if len(candidates) == 1 else None


def _outside_glyphs_have_lossless_word_backing(
    outside: Sequence[Glyph],
    row: Row,
    column: ColumnSpec,
    assigned_cell: Cell,
) -> bool:
    words = tuple(
        word
        for cell in row.cells
        if cell is not assigned_cell
        and not column.bbox[0] <= _center_x(cell.bbox) <= column.bbox[2]
        for word in cell.words
    )
    assigned: list[list[Glyph]] = [[] for _ in words]
    for glyph in outside:
        owners = tuple(
            index for index, word in enumerate(words) if _bbox_center_inside(glyph.bbox, word.bbox)
        )
        if len(owners) != 1:
            return False
        assigned[owners[0]].append(glyph)
    return bool(words) and all(
        not glyphs
        or _normalized_text(word.text).casefold()
        == _normalized_text(logical_text_for_evidence(tuple(glyphs), (word,))).casefold()
        for word, glyphs in zip(words, assigned, strict=True)
    )


def _parse_date_without_duplicated_boundary_glyphs(
    row: Row,
    column: ColumnSpec,
    assigned_cell: Cell,
    year_context: DiscoveredDateYearContext | None,
) -> tuple[date | None, str | None]:
    if not assigned_cell.glyphs:
        return None, "invalid_date"
    outside = tuple(
        glyph
        for glyph in assigned_cell.glyphs
        if not column.bbox[0] <= _center_x(glyph.bbox) <= column.bbox[2]
    )
    if not outside:
        return None, "invalid_date"
    outside_sides = {
        "left" if _center_x(glyph.bbox) < column.bbox[0] else "right" for glyph in outside
    }
    if len(outside_sides) != 1:
        return None, "invalid_date"
    duplicated_evidence = {
        _glyph_identity(glyph)
        for cell in row.cells
        if cell is not assigned_cell
        and not column.bbox[0] <= _center_x(cell.bbox) <= column.bbox[2]
        for glyph in cell.glyphs
    }
    has_exact_duplicate_glyphs = bool(duplicated_evidence) and all(
        _glyph_identity(glyph) in duplicated_evidence for glyph in outside
    )
    if not has_exact_duplicate_glyphs and not _outside_glyphs_have_lossless_word_backing(
        outside,
        row,
        column,
        assigned_cell,
    ):
        return None, "invalid_date"
    remaining = tuple(glyph for glyph in assigned_cell.glyphs if glyph not in outside)
    if not remaining:
        return None, "invalid_date"
    parsed_date, diagnostic = _parse_date(
        logical_text_for_evidence(remaining, ()),
        year_context,
    )
    return (
        (parsed_date, None)
        if parsed_date is not None and diagnostic is None
        else (None, "invalid_date")
    )


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
    if _contains_marker(
        header,
        ("transaction date", "purchase date", "תאריך עסקה", "תאריך רכישה"),
    ):
        return "transaction"
    return None


def _structural_date_column_kinds(
    region: TableRegion,
    year_context: DiscoveredDateYearContext | None,
) -> dict[int, str]:
    columns = _role_columns(region, ColumnRole.DATE)
    if len(columns) != 2 or year_context is None:
        return {}
    header_kinds = tuple(_header_kind(column) for column in columns)
    labeled_indexes = tuple(index for index, kind in enumerate(header_kinds) if kind is not None)
    if len(labeled_indexes) == 1:
        labeled_index = labeled_indexes[0]
        labeled_kind = header_kinds[labeled_index]
        return {
            columns[1 - labeled_index].index: (
                "transaction" if labeled_kind == "posting" else "posting"
            )
        }
    if labeled_indexes:
        return {}
    amount_column = _proven_billed_amount_column(region)
    if amount_column is None:
        return {}
    transaction_rows = tuple(
        row
        for row in region.rows
        if len(_cells_for_column(row, amount_column)) == 1
        and is_money_shaped(_cells_for_column(row, amount_column)[0].text)
    )
    if len(transaction_rows) < 2:
        return {}
    parsed_by_column: list[tuple[date | None, ...]] = []
    for column in columns:
        parsed_values: list[date | None] = []
        for row in transaction_rows:
            cells = _cells_for_column(row, column)
            if len(cells) > 1:
                return {}
            if not cells:
                parsed_values.append(None)
                continue
            parsed_date, diagnostic = _parse_cell_date(cells[0], year_context)
            if diagnostic is not None or parsed_date is None:
                return {}
            parsed_values.append(parsed_date)
        parsed_by_column.append(tuple(parsed_values))
    complete_indexes = tuple(
        index
        for index, values in enumerate(parsed_by_column)
        if all(value is not None for value in values)
    )
    if len(complete_indexes) == 2:
        first_values = tuple(value for value in parsed_by_column[0] if value is not None)
        second_values = tuple(value for value in parsed_by_column[1] if value is not None)
        ordered_candidates: list[tuple[int, int]] = []
        if all(
            first <= second for first, second in zip(first_values, second_values, strict=True)
        ) and any(
            first < second for first, second in zip(first_values, second_values, strict=True)
        ):
            ordered_candidates.append((0, 1))
        if all(
            second <= first for first, second in zip(first_values, second_values, strict=True)
        ) and any(
            second < first for first, second in zip(first_values, second_values, strict=True)
        ):
            ordered_candidates.append((1, 0))
        if len(ordered_candidates) != 1:
            return {}
        transaction_index, posting_index = ordered_candidates[0]
        return {
            columns[transaction_index].index: "transaction",
            columns[posting_index].index: "posting",
        }
    if len(complete_indexes) != 1:
        return {}
    transaction_index = complete_indexes[0]
    posting_index = 1 - transaction_index
    posting_values = parsed_by_column[posting_index]
    if all(value is not None for value in posting_values):
        return {}
    paired = tuple(
        (transaction_value, posting_value)
        for transaction_value, posting_value in zip(
            parsed_by_column[transaction_index], posting_values, strict=True
        )
        if transaction_value is not None and posting_value is not None
    )
    if len(paired) < 2:
        return {}
    if not all(transaction <= posting for transaction, posting in paired):
        return {}
    if not any(transaction < posting for transaction, posting in paired):
        return {}
    return {
        columns[transaction_index].index: "transaction",
        columns[posting_index].index: "posting",
    }


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


def _horizontal_coverage(candidate: BBox, container: BBox) -> float:
    width = candidate[2] - candidate[0]
    if width <= 0:
        return 0.0
    overlap = max(0.0, min(candidate[2], container[2]) - max(candidate[0], container[0]))
    return overlap / width


def _is_boundary_description_continuation(
    row: Row,
    previous: Row,
    region: TableRegion,
) -> bool:
    if len(row.cells) != 1 or row.page_number != previous.page_number:
        return False
    cell = row.cells[0]
    text = _normalized_text(cell.text)
    if (
        not any(char.isalpha() for char in text)
        or is_money_shaped(text)
        or is_currency_shaped(text)
        or isolated_date_token(text) is not None
        or _INSTALLMENT_PATTERN.fullmatch(text) is not None
    ):
        return False
    billed_column = _proven_billed_amount_column(region)
    if billed_column is None:
        return False
    billed_cells = _cells_for_column(previous, billed_column)
    if len(billed_cells) != 1 or not is_money_shaped(billed_cells[0].text):
        return False
    merchant_cells = tuple(
        candidate
        for candidate in previous.cells
        if any(char.isalpha() for char in candidate.text)
        and not is_money_shaped(candidate.text)
        and not is_currency_shaped(candidate.text)
        and isolated_date_token(candidate.text) is None
    )
    ordered_merchant_cells = tuple(sorted(merchant_cells, key=lambda candidate: candidate.bbox[0]))
    typical_merchant_height = (
        statistics.median(_height(candidate.bbox) for candidate in ordered_merchant_cells)
        if ordered_merchant_cells
        else 0.0
    )
    contiguous_merchant_span = len(ordered_merchant_cells) >= 2 and all(
        following.bbox[0] - preceding.bbox[2] <= typical_merchant_height * 0.6
        for preceding, following in pairwise(ordered_merchant_cells)
    )
    merchant_span = (
        (
            ordered_merchant_cells[0].bbox[0],
            min(candidate.bbox[1] for candidate in ordered_merchant_cells),
            ordered_merchant_cells[-1].bbox[2],
            max(candidate.bbox[3] for candidate in ordered_merchant_cells),
        )
        if contiguous_merchant_span
        else None
    )
    if not (
        any(_horizontal_coverage(cell.bbox, candidate.bbox) >= 0.9 for candidate in merchant_cells)
        or (merchant_span is not None and _horizontal_coverage(cell.bbox, merchant_span) >= 0.9)
    ):
        return False
    typical_height = statistics.median(
        _height(candidate.bbox) for candidate in (*previous.cells, *row.cells)
    )
    gap = max(0.0, row.bbox[1] - previous.bbox[3])
    return gap <= typical_height * 1.5


def _is_continuation(row: Row, previous: Row, region: TableRegion) -> bool:
    if "subordinate_auxiliary_continuation" in row.diagnostics:
        billed_column = _proven_billed_amount_column(region)
        if billed_column is None or any(
            diagnostic in previous.diagnostics
            for diagnostic in (
                "subordinate_auxiliary_continuation",
                "subordinate_detail_continuation",
            )
        ):
            return False
        billed_cells = _cells_for_column(previous, billed_column)
        if (
            len(billed_cells) != 1
            or not is_money_shaped(billed_cells[0].text)
            or _cells_for_column(row, billed_column)
        ):
            return False
        typical_height = statistics.median(
            _height(candidate.bbox) for candidate in (*previous.cells, *row.cells)
        )
        gap = max(0.0, row.bbox[1] - previous.bbox[3])
        return gap <= typical_height * 1.5
    if "subordinate_detail_continuation" in row.diagnostics:
        billed_column = _proven_billed_amount_column(region)
        if billed_column is None:
            return False
        if "subordinate_detail_continuation" not in previous.diagnostics:
            billed_cells = _cells_for_column(previous, billed_column)
            if len(billed_cells) != 1 or not is_money_shaped(billed_cells[0].text):
                return False
        if _cells_for_column(row, billed_column):
            return False
        typical_height = statistics.median(
            _height(candidate.bbox) for candidate in (*previous.cells, *row.cells)
        )
        gap = max(0.0, row.bbox[1] - previous.bbox[3])
        return gap <= typical_height * 1.5
    if _is_boundary_description_continuation(row, previous, region):
        return True
    description_cells = _role_cells(row, region, ColumnRole.DESCRIPTION)
    has_transaction_fields = any(
        _role_cells(row, region, role)
        for role in (
            ColumnRole.DATE,
            ColumnRole.CONVERSION_DATE,
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


def _horizontal_overlap(first: BBox, second: BBox) -> float:
    return max(0.0, min(first[2], second[2]) - max(first[0], second[0]))


def _boundary_date_description_split(
    cell: Cell,
    date_column: ColumnSpec,
    description_column: ColumnSpec,
    year_context: DiscoveredDateYearContext | None,
    unanchored_style: DateTokenStyle | None,
) -> tuple[date | None, str] | None:
    cell_width = max(0.0, cell.bbox[2] - cell.bbox[0])
    if (
        cell_width <= 0
        or _horizontal_overlap(cell.bbox, date_column.bbox) <= 0
        or _horizontal_overlap(cell.bbox, date_column.bbox) / cell_width
        < _MIN_DATE_DESCRIPTION_CELL_OVERLAP
    ):
        return None
    normalized = _normalized_text(cell.text)
    matches = tuple(_DATE_TOKEN_PATTERN.finditer(normalized))
    if len(matches) != 1:
        return None
    match = matches[0]
    parsed_date, diagnostic = _parse_cell_date(cell, year_context)
    has_proven_unanchored_date = (
        (
            year_context is None
            and _valid_short_date_token_for_style(match.group(0), unanchored_style) is not None
        )
        if unanchored_style is not None
        else False
    )
    if (parsed_date is None or diagnostic is not None) and not has_proven_unanchored_date:
        return None
    residual = _normalized_text(normalized[: match.start()] + normalized[match.end() :])
    if (
        not residual
        or not any(char.isalpha() for char in residual)
        or any(char.isdigit() for char in residual)
    ):
        return None
    description_boundary = (
        description_column.bbox[2]
        if _center_x(description_column.bbox) < _center_x(date_column.bbox)
        else description_column.bbox[0]
    )
    residual_word_touches_boundary = any(
        any(char.isalpha() for char in word.text)
        and not any(char.isdigit() for char in word.text)
        and max(0.0, word.bbox[0] - description_boundary, description_boundary - word.bbox[2])
        <= _height(word.bbox) * 0.2
        for word in cell.words
    )
    if (
        _horizontal_overlap(cell.bbox, description_column.bbox) / cell_width
        < _MIN_DATE_DESCRIPTION_CELL_OVERLAP
        and not residual_word_touches_boundary
    ):
        return None
    return parsed_date, residual


def _boundary_date_description_splits(
    row: Row,
    region: TableRegion,
    year_context: DiscoveredDateYearContext | None,
) -> tuple[tuple[Cell, date | None, str], ...]:
    date_columns = _role_columns(region, ColumnRole.DATE)
    description_columns = _role_columns(region, ColumnRole.DESCRIPTION)
    if len(date_columns) != 1 or len(description_columns) != 1:
        return ()
    unanchored_style = (
        _proven_unanchored_short_date_style(region, date_columns[0])
        if year_context is None
        else None
    )
    candidates = tuple(
        (cell, parsed_date, residual)
        for cell in row.cells
        if (
            split := _boundary_date_description_split(
                cell,
                date_columns[0],
                description_columns[0],
                year_context,
                unanchored_style,
            )
        )
        for parsed_date, residual in (split,)
    )
    unique = {
        (candidate[0].bbox, candidate[1], candidate[2]): candidate for candidate in candidates
    }
    return tuple(unique.values())


def _text_direction(text: str) -> str:
    rtl = sum(unicodedata.bidirectional(char) in {"R", "AL"} for char in text)
    ltr = sum(unicodedata.bidirectional(char) == "L" for char in text)
    return "rtl" if rtl > ltr else "ltr"


def _cluster_lines(clusters: Sequence[EvidenceCluster]) -> tuple[tuple[EvidenceCluster, ...], ...]:
    lines: list[list[EvidenceCluster]] = []
    for cluster in sorted(clusters, key=lambda item: (item.bbox[1], item.bbox[0])):
        center_y = (cluster.bbox[1] + cluster.bbox[3]) / 2
        matching = next(
            (
                line
                for line in lines
                if abs(center_y - (line[0].bbox[1] + line[0].bbox[3]) / 2)
                <= min(_height(cluster.bbox), _height(line[0].bbox)) * 0.5
            ),
            None,
        )
        if matching is None:
            lines.append([cluster])
        else:
            matching.append(cluster)
    return tuple(tuple(sorted(line, key=lambda item: item.bbox[0])) for line in lines)


def _primary_description_cluster(
    clusters: Sequence[EvidenceCluster],
) -> EvidenceCluster:
    direction = _text_direction(" ".join(cluster.text for cluster in clusters))
    return (
        max(clusters, key=lambda cluster: cluster.bbox[2])
        if direction == "rtl"
        else min(clusters, key=lambda cluster: cluster.bbox[0])
    )


def _cluster_signature(cluster: EvidenceCluster) -> str:
    return _normalized_phrase(cluster.text)


def _repeated_distant_description_signatures(region: TableRegion) -> frozenset[str]:
    counts: dict[str, int] = {}
    for row in region.rows:
        row_ledger = EvidenceLedger.from_rows((row,))
        row_signatures: set[str] = set()
        for cell in _role_cells(row, region, ColumnRole.DESCRIPTION):
            for line in _cluster_lines(row_ledger.clusters_for_cell(cell)):
                if len(line) < 2:
                    continue
                primary = _primary_description_cluster(line)
                row_signatures.update(
                    signature
                    for cluster in line
                    if cluster is not primary and (signature := _cluster_signature(cluster))
                )
        for signature in row_signatures:
            counts[signature] = counts.get(signature, 0) + 1
    return frozenset(signature for signature, count in counts.items() if count >= 2)


def _is_numeric_processor_cluster(cluster: EvidenceCluster) -> bool:
    compact = "".join(cluster.text.split())
    return len(compact) >= 6 and compact.isdigit()


def _selected_description_cell_atoms(
    ledger: EvidenceLedger,
    cell: Cell,
    repeated_distant_signatures: frozenset[str],
) -> tuple[frozenset[int], frozenset[int]]:
    selected: set[int] = set()
    processor: set[int] = set()
    for line in _cluster_lines(ledger.clusters_for_cell(cell)):
        if not line:
            continue
        primary = _primary_description_cluster(line)
        selected.update(primary.atom_ids)
        for cluster in line:
            if cluster is primary:
                continue
            if _is_numeric_processor_cluster(cluster) or (
                any(char.isalpha() for char in cluster.text)
                and _cluster_signature(cluster) in repeated_distant_signatures
            ):
                processor.update(cluster.atom_ids)
            else:
                selected.update(cluster.atom_ids)
    return frozenset(selected), frozenset(processor)


def _adjacent_unknown_description_atoms(
    row: Row,
    region: TableRegion,
    ledger: EvidenceLedger,
) -> tuple[frozenset[int], frozenset[int]]:
    description_columns = _role_columns(region, ColumnRole.DESCRIPTION)
    if len(description_columns) != 1:
        return frozenset(), frozenset()
    description_column = description_columns[0]
    description_cells = _cells_for_column(row, description_column)
    if len(description_cells) != 1:
        return frozenset(), frozenset()
    description_cell = description_cells[0]
    selected: set[int] = set()
    ancillary: set[int] = set()
    for column in region.table_schema.columns:
        if (
            column.role is not ColumnRole.UNKNOWN
            or abs(column.index - description_column.index) != 1
        ):
            continue
        for cell in _cells_for_column(row, column):
            lines = _cluster_lines(ledger.clusters_for_cell(cell))
            if len(lines) != 1 or len(lines[0]) < 2:
                continue
            clusters = lines[0]
            cell_is_left = _center_x(cell.bbox) < _center_x(description_cell.bbox)
            boundary_cluster = (
                max(clusters, key=lambda cluster: cluster.bbox[2])
                if cell_is_left
                else min(clusters, key=lambda cluster: cluster.bbox[0])
            )
            gap = (
                description_cell.bbox[0] - boundary_cluster.bbox[2]
                if cell_is_left
                else boundary_cluster.bbox[0] - description_cell.bbox[2]
            )
            tolerance = min(_height(cell.bbox), _height(description_cell.bbox))
            if -tolerance * 0.2 <= gap <= tolerance * 0.6:
                selected.update(boundary_cluster.atom_ids)
                ancillary.update(
                    atom_id
                    for cluster in clusters
                    if cluster is not boundary_cluster
                    for atom_id in cluster.atom_ids
                )
    return frozenset(selected), frozenset(ancillary)


def _merchant_punctuation(text: str) -> str:
    normalized = _HEBREW_GERSHAYIM_PATTERN.sub("״", _normalized_text(text))
    compact = normalized.replace(" ", "")
    marker = _SINGLE_RTL_PARENTHETICAL_PATTERN.fullmatch(compact)
    return f"({marker.group(1)})" if marker is not None else normalized


def _description(
    rows: Sequence[Row],
    region: TableRegion,
    year_context: DiscoveredDateYearContext | None,
    ledger: EvidenceLedger,
) -> DescriptionExtraction:
    repeated_signatures = _repeated_distant_description_signatures(region)
    claims: list[EvidenceClaim] = []
    texts: list[str] = []
    eligible_rows = tuple(
        row for row in rows if "subordinate_detail_continuation" not in row.diagnostics
    )
    previous_row: Row | None = None
    for index, row in enumerate(eligible_rows):
        row_cells = _role_cells(row, region, ColumnRole.DESCRIPTION)
        if "subordinate_auxiliary_continuation" in row.diagnostics:
            row_cells = tuple(
                cell
                for cell in row_cells
                if _horizontal_overlap(
                    cell.bbox, _role_columns(region, ColumnRole.DESCRIPTION)[0].bbox
                )
                > 0
            )
        elif (
            not row_cells
            and index > 0
            and previous_row is not None
            and _is_boundary_description_continuation(row, previous_row, region)
        ):
            row_cells = row.cells
        selected_ids: set[int] = set()
        processor_ids: set[int] = set()
        fallback_texts: list[str] = []
        for cell in row_cells:
            selected, processor = _selected_description_cell_atoms(
                ledger,
                cell,
                repeated_signatures,
            )
            selected_ids.update(selected)
            processor_ids.update(processor)

        date_columns = _role_columns(region, ColumnRole.DATE)
        if len(date_columns) == 1:
            date_cells = _cells_for_column(row, date_columns[0])
            if (
                len(date_cells) == 1
                and (
                    completion := _adjacent_boundary_date_completion(
                        row,
                        date_columns[0],
                        date_cells[0],
                        year_context,
                    )
                )
                is not None
            ):
                _, source_cell, boundary_glyph = completion
                selected_ids.difference_update(
                    atom.atom_id
                    for atom in ledger.atoms
                    if atom.atom_id in ledger.atoms_for_cell(source_cell)
                    and atom.glyph == boundary_glyph
                )

        splits = _boundary_date_description_splits(row, region, year_context)
        if len(splits) == 1:
            split_cell, _, residual_text = splits[0]
            split_ids = ledger.atoms_for_cell(split_cell)
            selected_ids.difference_update(split_ids)
            residual_ids = frozenset(
                atom.atom_id
                for atom in ledger.atoms
                if atom.atom_id in split_ids
                and any(char.isalpha() for char in atom.text)
                and not any(char.isdigit() for char in atom.text)
            )
            if residual_ids:
                selected_ids.update(residual_ids)
            else:
                fallback_texts.append(residual_text)
        if index == 0:
            adjacent_ids, ancillary_ids = _adjacent_unknown_description_atoms(
                row,
                region,
                ledger,
            )
            selected_ids.update(adjacent_ids)
            if ancillary_ids:
                claims.append(EvidenceClaim(SemanticOwner.ANCILLARY, ancillary_ids))
        rendered = _merchant_punctuation(ledger.render(selected_ids)) if selected_ids else ""
        row_text = _normalized_text(" ".join((*fallback_texts, rendered)))
        if row_text:
            texts.append(_merchant_punctuation(row_text))
        if selected_ids:
            claims.append(EvidenceClaim(SemanticOwner.DESCRIPTION, frozenset(selected_ids)))
        if processor_ids:
            claims.append(
                EvidenceClaim(SemanticOwner.PROCESSOR_REFERENCE, frozenset(processor_ids))
            )
        previous_row = row

    diagnostics: list[str] = []
    if not texts:
        if _role_columns(region, ColumnRole.DESCRIPTION):
            diagnostics.append("missing_description_cell")
        return DescriptionExtraction(None, tuple(claims), tuple(diagnostics))
    return DescriptionExtraction(
        _normalized_text(" ".join(_merchant_punctuation(text) for text in texts)),
        tuple(claims),
        tuple(diagnostics),
    )


def _word_height(word: Word) -> float:
    return max(0.0, word.bbox[3] - word.bbox[1])


def _bounded_note_original_amounts(rows: Sequence[Row]) -> frozenset[tuple[Decimal, str]]:
    corroborated: set[tuple[Decimal, str]] = set()
    for row in rows:
        if "bounded_hebrew_note_detail" not in row.diagnostics:
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
    billed: AmountParseResult,
) -> AmountParseResult | None:
    if (
        not _cell_has_ocr_evidence(original_cell)
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
        not _cell_has_ocr_evidence(original_cell)
        or parsed_original.amount is not None
        or not parsed_original.diagnostics
    ):
        return None
    pairs: set[tuple[Decimal, str]] = set()
    supporting_confidences: list[float] = []
    for row in continuation_rows:
        if "subordinate_detail_continuation" not in row.diagnostics:
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
    description_columns = _role_columns(region, ColumnRole.DESCRIPTION)
    original_columns = _role_columns(region, ColumnRole.ORIGINAL_AMOUNT)
    if len(description_columns) != 1 or len(original_columns) != 1:
        return None
    description_cells = _cells_for_column(row, description_columns[0])
    if len(description_cells) != 1 or not original_cell.words or not description_cells[0].words:
        return None
    words = tuple(sorted(original_cell.words, key=lambda word: word.bbox[0]))
    description_words = tuple(sorted(description_cells[0].words, key=lambda word: word.bbox[0]))
    if any(word.source != "digital" for word in (*words, *description_words)):
        return None
    description_on_right = _center_x(description_columns[0].bbox) > _center_x(
        original_columns[0].bbox
    )
    candidates: list[tuple[AmountParseResult, str, bool, bool]] = []
    word_amount_text = " ".join(word.text for word in words)
    word_amount = parse_amount(word_amount_text, currency_hint=currency_hint)
    compact_cell_text = "".join(_normalized_text(original_cell.text).split())
    compact_word_amount = "".join(_normalized_text(word_amount_text).split())
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
    vertical_overlap = max(
        0.0,
        min(original_cell.bbox[3], description_cell.bbox[3])
        - max(original_cell.bbox[1], description_cell.bbox[1]),
    )
    if (
        word_amount.amount is not None
        and word_amount.currency is not None
        and residual_text
        and any(char.isalpha() for char in residual_text)
        and not is_money_shaped(residual_text)
        and not is_currency_shaped(residual_text)
        and _DATE_PATTERN.fullmatch(residual_text) is None
        and _INSTALLMENT_PATTERN.fullmatch(residual_text) is None
        and horizontal_overlap > 0
        and vertical_overlap > 0
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
        residual_text = _normalized_text(" ".join(word.text for word in residual_words))
        if (
            parsed.amount is None
            or parsed.currency is None
            or not any(char.isalpha() for char in residual_text)
            or is_money_shaped(residual_text)
            or is_currency_shaped(residual_text)
            or _DATE_PATTERN.fullmatch(residual_text) is not None
            or _INSTALLMENT_PATTERN.fullmatch(residual_text) is not None
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
            _word_height(word) for word in (*residual_words, *description_words)
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
            abs(
                (residual_word.bbox[1] + residual_word.bbox[3]) / 2
                - (description_word.bbox[1] + description_word.bbox[3]) / 2
            )
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
            and vertical_overlap > 0
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


def _dates(
    row: Row,
    region: TableRegion,
    year_context: DiscoveredDateYearContext | None,
    structural_kinds: Mapping[int, str],
) -> tuple[date | None, date | None, date | None, list[str]]:
    columns = _role_columns(region, ColumnRole.DATE)
    diagnostics: list[str] = []
    parsed: list[tuple[str | None, date | None, str | None]] = []
    for column in columns:
        cells = _cells_for_column(row, column)
        unanchored_style = (
            _proven_unanchored_short_date_style(region, column) if year_context is None else None
        )
        if len(cells) != 1:
            if cells:
                diagnostics.append("multiple_date_cells")
            elif structural_kinds.get(column.index) != "posting":
                boundary_splits = _boundary_date_description_splits(
                    row,
                    region,
                    year_context,
                )
                if len(columns) == 1 and len(boundary_splits) == 1:
                    parsed.append(
                        (
                            _header_kind(column) or structural_kinds.get(column.index),
                            boundary_splits[0][1],
                            None,
                        )
                    )
                else:
                    diagnostics.append("missing_date_cell")
            continue
        if _has_proven_unanchored_short_date(cells[0], unanchored_style):
            parsed_date, date_diagnostic = None, None
        else:
            parsed_date, date_diagnostic = _parse_cell_date(cells[0], year_context)
        if date_diagnostic == "invalid_date":
            parsed_date, date_diagnostic = _parse_date_without_duplicated_boundary_glyphs(
                row,
                column,
                cells[0],
                year_context,
            )
        if (
            date_diagnostic == "invalid_date"
            and (
                completion := _adjacent_boundary_date_completion(
                    row,
                    column,
                    cells[0],
                    year_context,
                )
            )
            is not None
        ):
            parsed_date, _, _ = completion
            date_diagnostic = None
        if date_diagnostic == "invalid_date":
            parsed_date, date_diagnostic = _parse_overlapping_boundary_date(
                row,
                column,
                cells[0],
                year_context,
            )
        if date_diagnostic is not None:
            boundary_splits = _boundary_date_description_splits(
                row,
                region,
                year_context,
            )
            if len(columns) == 1 and len(boundary_splits) == 1:
                parsed_date = boundary_splits[0][1]
                date_diagnostic = None
        parsed.append(
            (
                _header_kind(column) or structural_kinds.get(column.index),
                parsed_date,
                date_diagnostic,
            )
        )
    transaction_date: date | None = None
    posting_date: date | None = None
    conversion_date: date | None = None
    if len(columns) == 1 and parsed:
        transaction_date = parsed[0][1]
        if parsed[0][2] is not None:
            diagnostics.extend(("invalid_transaction_date", f"transaction_date:{parsed[0][2]}"))
    elif len(columns) > 1:
        kinds = tuple(
            _header_kind(column) or structural_kinds.get(column.index) for column in columns
        )
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
    conversion_columns = _role_columns(region, ColumnRole.CONVERSION_DATE)
    if len(conversion_columns) == 1:
        conversion_cells = _cells_for_column(row, conversion_columns[0])
        if len(conversion_cells) == 1:
            parsed_conversion_date, conversion_diagnostic = _parse_cell_date(
                conversion_cells[0], year_context
            )
            if conversion_diagnostic == "invalid_date":
                parsed_conversion_date, conversion_diagnostic = (
                    _parse_date_without_duplicated_boundary_glyphs(
                        row,
                        conversion_columns[0],
                        conversion_cells[0],
                        year_context,
                    )
                )
            if conversion_diagnostic == "invalid_date":
                parsed_conversion_date, conversion_diagnostic = _parse_overlapping_boundary_date(
                    row,
                    conversion_columns[0],
                    conversion_cells[0],
                    year_context,
                )
            if conversion_diagnostic is None:
                conversion_date = parsed_conversion_date
    return transaction_date, posting_date, conversion_date, diagnostics


def _normalize_row(
    *,
    row: Row,
    continuation_rows: Sequence[Row],
    region: TableRegion,
    group: StatementGroupDiscovery,
    year_context: DiscoveredDateYearContext | None,
    date_column_kinds: Mapping[int, str],
    transaction_id: str,
) -> RowNormalizationResult:
    rows = (row, *continuation_rows)
    ledger = EvidenceLedger.from_rows(rows)
    evidence = _row_evidence(rows)
    diagnostics = list(_assignment_diagnostics(row, region))
    role_contract_diagnostics = _role_contract_diagnostics(region)
    diagnostics.extend(role_contract_diagnostics)
    if role_contract_diagnostics:
        return RowNormalizationResult(
            page_number=row.page_number,
            bbox=row.bbox,
            raw_text=_row_text(rows),
            evidence=evidence,
            confidence=0.0,
            diagnostics=tuple(diagnostics),
        )
    amount_column = _proven_billed_amount_column(region)
    if amount_column is None:
        amount_columns = _role_columns(region, ColumnRole.AMOUNT)
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
    amount_cells = _cells_for_column(row, amount_column)
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
    generic_currency_columns = _role_columns(region, ColumnRole.CURRENCY)
    original_columns = _role_columns(region, ColumnRole.ORIGINAL_AMOUNT)
    billing_currency_columns = _role_columns(region, ColumnRole.BILLING_CURRENCY)
    if generic_currency_columns and original_columns:
        diagnostics.append("ambiguous_generic_currency_association")
    if generic_currency_columns and billing_currency_columns:
        diagnostics.append("ambiguous_generic_currency_association")
    currency_role = ColumnRole.BILLING_CURRENCY if billing_currency_columns else ColumnRole.CURRENCY
    currency_cells = _role_cells(row, region, currency_role)
    if len(currency_cells) > 1:
        diagnostics.append("multiple_currency_cells")
    elif _role_columns(region, currency_role) and not currency_cells:
        diagnostics.append("missing_currency_cell")
    elif len(currency_cells) == 1:
        row_currency = canonical_currency(currency_cells[0].text)
        if row_currency is None:
            diagnostics.append("unknown_billing_currency")
        elif row_currency != currency_hint:
            diagnostics.append("billing_currency_conflict")
        else:
            currency_hint = row_currency
    critical_currency_diagnostics = {
        "ambiguous_generic_currency_association",
        "billing_currency_conflict",
        "missing_currency_cell",
        "multiple_currency_cells",
        "unknown_billing_currency",
    }
    if critical_currency_diagnostics.intersection(diagnostics):
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
            confidence=amount_cells[0].confidence,
            diagnostics=("noncontributing_zero_billed_row",),
        )
    if "unresolved_relevant_cell" in diagnostics:
        return RowNormalizationResult(
            page_number=row.page_number,
            bbox=row.bbox,
            raw_text=_row_text(rows),
            evidence=evidence,
            confidence=0.0,
            diagnostics=tuple(diagnostics),
        )

    description_extraction = _description(rows, region, year_context, ledger)
    description = description_extraction.value
    diagnostics.extend(description_extraction.diagnostics)
    transaction_date, posting_date, conversion_date, date_diagnostics = _dates(
        row,
        region,
        year_context,
        date_column_kinds,
    )
    diagnostics.extend(date_diagnostics)

    original_amount: Decimal | None = None
    original_currency: str | None = None
    if len(original_columns) > 1:
        diagnostics.append("multiple_original_amount_columns")
    elif len(original_columns) == 1:
        original_cells = _cells_for_column(row, original_columns[0])
        original_currency_columns = _role_columns(region, ColumnRole.ORIGINAL_CURRENCY)
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
            original_currency_hint = _proven_implicit_original_currency(region, currency_hint)
            if len(original_currency_columns) > 1:
                diagnostics.append("multiple_original_currency_columns")
            elif len(original_currency_columns) == 1:
                original_currency_cells = _cells_for_column(row, original_currency_columns[0])
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
                location_columns = _role_columns(region, ColumnRole.LOCATION)
                if len(location_columns) == 1:
                    location_cells = _cells_for_column(row, location_columns[0])
                    spilled_currencies = {
                        currency
                        for cell in location_cells
                        if (currency := _original_currency_spilled_into_location(cell, region))
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
            spill = None
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
                    if not already_in_description:
                        if description is None:
                            description = spill_text
                        elif description_on_right:
                            description = _normalized_text(f"{spill_text} {description}")
                        else:
                            description = _normalized_text(f"{description} {spill_text}")
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

    unconsumed_role_diagnostics = {
        "missing_date_cell",
        "multiple_date_cells",
        "missing_description_cell",
        "multiple_description_cells",
        "missing_original_amount_cell",
        "multiple_original_amount_cells",
        "missing_original_currency_cell",
        "multiple_original_currency_cells",
        "missing_installment_cell",
        "multiple_installment_cells",
    }
    if unconsumed_role_diagnostics.intersection(diagnostics):
        return RowNormalizationResult(
            page_number=row.page_number,
            bbox=row.bbox,
            raw_text=_row_text(rows),
            evidence=evidence,
            confidence=0.0,
            diagnostics=tuple(diagnostics),
        )

    kind = TransactionKind.CREDIT if billed.amount < 0 else TransactionKind.CHARGE
    category = _category(description, installment_current is not None)
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
        description=description,
        category=category,
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
            row
            for row in current_rows
            if "leading_subordinate_detail_continuation" in row.diagnostics
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
            while continuation_index < len(previous_rows) and _is_continuation(
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
        previous_billed_column = _proven_billed_amount_column(previous_region)
        current_billed_column = _proven_billed_amount_column(current_region)
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
            date_column_kinds = _structural_date_column_kinds(
                region,
                discovery.date_year_context,
            )
            rows = tuple(sorted(region.rows, key=lambda item: (item.bbox[1], item.bbox[0])))
            index = 0
            while index < len(rows):
                row = rows[index]
                if "leading_subordinate_detail_continuation" in row.diagnostics:
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
                while continuation_index < len(rows) and _is_continuation(
                    rows[continuation_index], previous, region
                ):
                    continuations.append(rows[continuation_index])
                    previous = rows[continuation_index]
                    continuation_index += 1
                continuations.extend(cross_page_handoffs.get(id(row), ()))
                transaction_id = f"{group.group_id}-p{row.page_number:03d}-r{row_ordinal:04d}"
                row_result = _normalize_row(
                    row=row,
                    continuation_rows=continuations,
                    region=region,
                    group=group,
                    year_context=discovery.date_year_context,
                    date_column_kinds=date_column_kinds,
                    transaction_id=transaction_id,
                )
                row_results.append(row_result)
                if row_result.transaction is None:
                    if row_result.diagnostics != ("noncontributing_zero_billed_row",):
                        rows_not_emitted += 1
                else:
                    transactions.append(row_result.transaction)
                for continuation in continuations:
                    row_ordinal += 1
                    continuation_diagnostic = (
                        "merged_subordinate_detail_continuation"
                        if "subordinate_detail_continuation" in continuation.diagnostics
                        else "merged_auxiliary_continuation"
                        if "subordinate_auxiliary_continuation" in continuation.diagnostics
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
