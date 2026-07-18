"""Relative column-band clustering and financial semantic inference."""

from __future__ import annotations

import math
import re
import statistics
import unicodedata
from calendar import monthrange
from collections import defaultdict
from collections.abc import Sequence
from itertools import pairwise

from ccparser.evidence.models import BBox, VectorRule
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableSchema

_THREE_COMPONENT_DATE_PATTERN = re.compile(r"(\d{1,4})\s*([-/\.])\s*(\d{1,2})\s*\2\s*(\d{1,4})")
_TWO_COMPONENT_SLASH_PATTERN = re.compile(r"(\d{1,3})\s*/\s*(\d{1,3})")
_MONEY_PATTERN = re.compile(
    r"(?:[-+]?\s*(?:[$€£₪]\s*)?|\(\s*)(?:\d{1,3}(?:[, ]\d{3})+|\d+)"
    r"(?:[.,]\d{2,3})(?:\s*[$€£₪])?\s*\)?"
)
_CURRENCY_VALUES = frozenset(
    {
        "AED",
        "AUD",
        "CAD",
        "CHF",
        "CNY",
        "EUR",
        "GBP",
        "ILS",
        "JPY",
        "NIS",
        "USD",
        "$",
        "€",
        "£",
        "₪",
        "שח",
        "ש ח",
    }
)

_HEADER_VOCABULARY: dict[ColumnRole, frozenset[str]] = {
    ColumnRole.DATE: frozenset(
        {
            "date",
            "posting date",
            "transaction date",
            "תאריך",
            "תאריך חיוב",
            "תאריך עסקה",
        }
    ),
    ColumnRole.DESCRIPTION: frozenset(
        {
            "description",
            "details",
            "merchant",
            "merchant name",
            "בית עסק",
            "פרטי עסקה",
            "שם בית עסק",
            "תיאור",
        }
    ),
    ColumnRole.AMOUNT: frozenset(
        {
            "amount",
            "amount charged",
            "billed amount",
            "charge amount",
            "סכום",
            "סכום חיוב",
            "סכום לחיוב",
        }
    ),
    ColumnRole.ORIGINAL_AMOUNT: frozenset(
        {
            "original amount",
            "transaction amount",
            "סכום במקור",
            "סכום עסקה",
            "סכום עסקה מקורי",
        }
    ),
    ColumnRole.CURRENCY: frozenset({"currency", "currency code", "מטבע"}),
    ColumnRole.BILLING_CURRENCY: frozenset(
        {
            "billed currency",
            "billing currency",
            "charge currency",
            "מטבע חיוב",
        }
    ),
    ColumnRole.ORIGINAL_CURRENCY: frozenset(
        {
            "original currency",
            "purchase currency",
            "transaction currency",
            "מטבע עסקה",
            "מטבע מקור",
        }
    ),
    ColumnRole.INSTALLMENT: frozenset(
        {"installment", "installments", "payment number", "מספר תשלום", "תשלומים"}
    ),
}

_SEMANTIC_FAMILIES: tuple[frozenset[ColumnRole], ...] = (
    frozenset({ColumnRole.AMOUNT, ColumnRole.ORIGINAL_AMOUNT}),
    frozenset(
        {
            ColumnRole.CURRENCY,
            ColumnRole.BILLING_CURRENCY,
            ColumnRole.ORIGINAL_CURRENCY,
        }
    ),
)
_GENERIC_FAMILY_ROLES = frozenset({ColumnRole.AMOUNT, ColumnRole.CURRENCY})


def _width(bbox: BBox) -> float:
    return max(0.0, bbox[2] - bbox[0])


def _height(bbox: BBox) -> float:
    return max(0.0, bbox[3] - bbox[1])


def _center_x(bbox: BBox) -> float:
    return (bbox[0] + bbox[2]) / 2


def _center_y(bbox: BBox) -> float:
    return (bbox[1] + bbox[3]) / 2


def _union_bbox(boxes: Sequence[BBox]) -> BBox:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _horizontal_overlap(first: BBox, second: BBox) -> float:
    overlap = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    smaller_width = min(_width(first), _width(second))
    return overlap / smaller_width if smaller_width else 0.0


def _table_context(rows: Sequence[Row]) -> tuple[int, BBox]:
    if not rows:
        raise ValueError("at least one row is required")
    page_numbers = {row.page_number for row in rows}
    if len(page_numbers) != 1:
        raise ValueError("column inference requires rows from one page")
    boxes = tuple(cell.bbox for row in rows for cell in row.cells)
    if not boxes:
        raise ValueError("at least one cell is required")
    return rows[0].page_number, _union_bbox(boxes)


def _vertical_separator_positions(
    vector_rules: Sequence[VectorRule], table_bbox: BBox
) -> tuple[float, ...]:
    positions = sorted(
        _center_x(rule.bbox)
        for rule in vector_rules
        if _height(rule.bbox) > max(_width(rule.bbox) * 3, 0.0)
        and table_bbox[0] < _center_x(rule.bbox) < table_bbox[2]
        and rule.bbox[3] >= table_bbox[1]
        and rule.bbox[1] <= table_bbox[3]
    )
    unique: list[float] = []
    tolerance = max(_width(table_bbox) * 0.002, 1e-9)
    for position in positions:
        if not unique or abs(position - unique[-1]) > tolerance:
            unique.append(position)
    return tuple(unique)


def _separator_columns(
    rows: Sequence[Row], page_number: int, table_bbox: BBox, positions: Sequence[float]
) -> tuple[ColumnSpec, ...]:
    boundaries = (table_bbox[0], *positions, table_bbox[2])
    columns: list[ColumnSpec] = []
    table_width = _width(table_bbox)
    for left, right in pairwise(boundaries):
        sources = tuple(
            cell for row in rows for cell in row.cells if left <= _center_x(cell.bbox) <= right
        )
        if not sources:
            continue
        support = len(
            {
                row_index
                for row_index, row in enumerate(rows)
                if any(cell in sources for cell in row.cells)
            }
        )
        columns.append(
            ColumnSpec(
                index=len(columns),
                page_number=page_number,
                bbox=(left, table_bbox[1], right, table_bbox[3]),
                relative_x0=(left - table_bbox[0]) / table_width,
                relative_x1=(right - table_bbox[0]) / table_width,
                source_cells=sources,
                confidence=support / len(rows),
                diagnostics=("vector_separator_support",),
            )
        )
    return tuple(columns)


def _clustered_columns(
    rows: Sequence[Row], page_number: int, table_bbox: BBox
) -> tuple[ColumnSpec, ...]:
    table_width = _width(table_bbox)
    clusters: list[list[tuple[int, Cell]]] = []
    for row_index, row in enumerate(rows):
        for cell in sorted(row.cells, key=lambda value: (_center_x(value.bbox), value.text)):
            candidates: list[tuple[float, list[tuple[int, Cell]]]] = []
            for cluster in clusters:
                if any(existing_row == row_index for existing_row, _ in cluster):
                    continue
                cluster_cells = tuple(existing for _, existing in cluster)
                center = statistics.median(_center_x(existing.bbox) for existing in cluster_cells)
                representative_width = statistics.median(
                    _width(existing.bbox) for existing in cluster_cells
                )
                normalized_distance = abs(_center_x(cell.bbox) - center) / table_width
                normalized_width = max(_width(cell.bbox), representative_width) / table_width
                tolerance = max(0.025, min(0.08, normalized_width * 0.3))
                representative_bbox = _union_bbox(
                    tuple(existing.bbox for existing in cluster_cells)
                )
                if (
                    normalized_distance <= tolerance
                    or _horizontal_overlap(cell.bbox, representative_bbox) >= 0.25
                ):
                    candidates.append((normalized_distance, cluster))
            if candidates:
                min(candidates, key=lambda candidate: candidate[0])[1].append((row_index, cell))
            else:
                clusters.append([(row_index, cell)])

    ordered_clusters = sorted(
        clusters,
        key=lambda cluster: statistics.median(_center_x(cell.bbox) for _, cell in cluster),
    )
    columns: list[ColumnSpec] = []
    for cluster in ordered_clusters:
        sources = tuple(
            cell
            for _, cell in sorted(
                cluster, key=lambda item: (item[0], item[1].bbox[0], item[1].text)
            )
        )
        source_bbox = _union_bbox(tuple(cell.bbox for cell in sources))
        support = len({row_index for row_index, _ in cluster})
        diagnostics = () if support >= min(2, len(rows)) else ("weak_repeated_x_support",)
        columns.append(
            ColumnSpec(
                index=len(columns),
                page_number=page_number,
                bbox=(source_bbox[0], table_bbox[1], source_bbox[2], table_bbox[3]),
                relative_x0=(source_bbox[0] - table_bbox[0]) / table_width,
                relative_x1=(source_bbox[2] - table_bbox[0]) / table_width,
                source_cells=sources,
                confidence=support / len(rows),
                diagnostics=diagnostics,
            )
        )
    return tuple(columns)


def infer_column_bands(
    rows: Sequence[Row], vector_rules: Sequence[VectorRule] = ()
) -> tuple[ColumnSpec, ...]:
    """Infer deterministic x bands normalized to the rows' bounding box."""

    if not rows:
        return ()
    page_number, table_bbox = _table_context(rows)
    if math.isclose(_width(table_bbox), 0.0):
        return ()
    separator_positions = _vertical_separator_positions(vector_rules, table_bbox)
    if separator_positions:
        separated = _separator_columns(rows, page_number, table_bbox, separator_positions)
        if len(separated) >= 2:
            return separated
    return _clustered_columns(rows, page_number, table_bbox)


def _normalized_header(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text).casefold()
    return " ".join("".join(char if char.isalnum() else " " for char in normalized).split())


def _contains_token_phrase(text: str, phrase: str) -> bool:
    text_tokens = text.split()
    phrase_tokens = phrase.split()
    phrase_length = len(phrase_tokens)
    return any(
        text_tokens[index : index + phrase_length] == phrase_tokens
        for index in range(len(text_tokens) - phrase_length + 1)
    )


def _same_semantic_family(first: ColumnRole, second: ColumnRole) -> bool:
    return any(first in family and second in family for family in _SEMANTIC_FAMILIES)


def _compatible_profile_alternative(
    selected: ColumnRole,
    alternative: ColumnRole,
    header_scores: dict[ColumnRole, float],
    profile_scores: dict[ColumnRole, float],
) -> bool:
    return (
        _same_semantic_family(selected, alternative)
        and header_scores.get(alternative, 0.0) < 0.65
        and profile_scores.get(alternative, 0.0) >= 0.65
    )


def _header_scores(texts: Sequence[str]) -> dict[ColumnRole, float]:
    scores: dict[ColumnRole, float] = {}
    for text in texts:
        normalized = _normalized_header(text)
        exact_roles = {role for role, terms in _HEADER_VOCABULARY.items() if normalized in terms}
        exact_specific_role = (
            next(iter(exact_roles))
            if len(exact_roles) == 1 and next(iter(exact_roles)) not in _GENERIC_FAMILY_ROLES
            else None
        )
        for role, terms in _HEADER_VOCABULARY.items():
            for term in terms:
                if normalized == term:
                    scores[role] = max(scores.get(role, 0.0), 1.0)
                elif _contains_token_phrase(normalized, term):
                    if (
                        exact_specific_role is not None
                        and role in _GENERIC_FAMILY_ROLES
                        and _same_semantic_family(exact_specific_role, role)
                    ):
                        continue
                    scores[role] = max(scores.get(role, 0.0), 0.82)
    return scores


def _valid_calendar_day(day: int, month: int, year: int | None = None) -> bool:
    if not 1 <= month <= 12 or day < 1:
        return False
    maximum = (
        monthrange(year, month)[1]
        if year is not None
        else (29 if month == 2 else monthrange(2001, month)[1])
    )
    return day <= maximum


def is_date_shaped(text: str) -> bool:
    """Return whether the complete text is a valid supported calendar date."""

    short_match = _TWO_COMPONENT_SLASH_PATTERN.fullmatch(text)
    if short_match is not None:
        day, month = (int(component) for component in short_match.groups())
        return _valid_calendar_day(day, month)

    match = _THREE_COMPONENT_DATE_PATTERN.fullmatch(text)
    if match is None:
        return False
    first, _, second, third = match.groups()
    if len(first) == 4:
        year, month, day = int(first), int(second), int(third)
    else:
        day, month, year = int(first), int(second), int(third)
    return 1 <= year <= 9999 and _valid_calendar_day(day, month, year)


def is_installment_shaped(text: str) -> bool:
    """Return whether the complete text is a valid current/total installment pair."""

    match = _TWO_COMPONENT_SLASH_PATTERN.fullmatch(text)
    if match is None:
        return False
    current, total = (int(component) for component in match.groups())
    return 1 <= current <= total


def _profile_scores(texts: Sequence[str]) -> dict[ColumnRole, float]:
    if not texts:
        return {}
    matches: defaultdict[ColumnRole, int] = defaultdict(int)
    for text in texts:
        stripped = unicodedata.normalize("NFC", text).strip()
        raw_currency = stripped.upper()
        compact_currency = _normalized_header(stripped).upper()
        if is_date_shaped(stripped):
            matches[ColumnRole.DATE] += 1
        if raw_currency in _CURRENCY_VALUES or compact_currency in _CURRENCY_VALUES:
            matches[ColumnRole.CURRENCY] += 1
        if is_installment_shaped(stripped):
            matches[ColumnRole.INSTALLMENT] += 1
        if _MONEY_PATTERN.fullmatch(stripped):
            matches[ColumnRole.AMOUNT] += 1
        letters = sum(char.isalpha() for char in stripped)
        if letters >= 4 and letters / max(len(stripped), 1) >= 0.6:
            matches[ColumnRole.DESCRIPTION] += 1

    scores: dict[ColumnRole, float] = {}
    for role, count in matches.items():
        fraction = count / len(texts)
        ceiling = 0.55 if role is ColumnRole.DESCRIPTION else 0.92
        scores[role] = ceiling * fraction
    return scores


def _cells_to_rows(cells: Sequence[Cell]) -> tuple[Row, ...]:
    groups: list[list[Cell]] = []
    for cell in sorted(cells, key=lambda value: (_center_y(value.bbox), value.bbox[0])):
        target: list[Cell] | None = None
        for group in groups:
            group_bbox = _union_bbox(tuple(item.bbox for item in group))
            overlap = max(0.0, min(cell.bbox[3], group_bbox[3]) - max(cell.bbox[1], group_bbox[1]))
            smaller_height = min(_height(cell.bbox), _height(group_bbox))
            overlap_ratio = overlap / smaller_height if smaller_height else 0.0
            tolerance = 0.45 * max(_height(cell.bbox), _height(group_bbox))
            if (
                overlap_ratio >= 0.3
                or abs(_center_y(cell.bbox) - _center_y(group_bbox)) <= tolerance
            ):
                target = group
                break
        if target is None:
            groups.append([cell])
        else:
            target.append(cell)
    return tuple(
        Row(
            page_number=group[0].page_number,
            bbox=_union_bbox(tuple(cell.bbox for cell in group)),
            cells=tuple(sorted(group, key=lambda cell: cell.bbox[0])),
            words=tuple(word for cell in group for word in cell.words),
            confidence=statistics.mean(cell.confidence for cell in group),
        )
        for group in groups
    )


def _cells_for_column(cells: Sequence[Cell], column: ColumnSpec) -> tuple[Cell, ...]:
    associated = tuple(cell for cell in cells if cell in column.source_cells)
    if associated:
        return associated
    return tuple(cell for cell in cells if column.bbox[0] <= _center_x(cell.bbox) <= column.bbox[2])


def infer_column_roles(header_cells: Sequence[Cell], sample_cells: Sequence[Cell]) -> TableSchema:
    """Combine general financial header vocabulary with typed value profiles."""

    if not header_cells:
        raise ValueError("at least one header cell is required")
    all_cells = (*header_cells, *sample_cells)
    page_numbers = {cell.page_number for cell in all_cells}
    if len(page_numbers) != 1:
        raise ValueError("semantic inference requires cells from one page")
    rows = (*_cells_to_rows(header_cells), *_cells_to_rows(sample_cells))
    bands = infer_column_bands(rows)
    semantic_columns: list[ColumnSpec] = []
    ambiguous_indexes: list[int] = []
    for column in bands:
        headers = _cells_for_column(header_cells, column)
        samples = _cells_for_column(sample_cells, column)
        header_scores = _header_scores(tuple(cell.text for cell in headers))
        profile_scores = _profile_scores(tuple(cell.text for cell in samples))
        scores = dict(header_scores)
        exact_header_roles = tuple(role for role, score in header_scores.items() if score == 1.0)
        for role, score in profile_scores.items():
            scores[role] = max(scores.get(role, 0.0), score)
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0].value))
        top_role = ColumnRole.UNKNOWN
        top_score = 0.0
        diagnostics = list(column.diagnostics)
        if len(exact_header_roles) == 1:
            top_role = exact_header_roles[0]
            top_score = 1.0
            alternatives = tuple(
                (role, score)
                for role, score in ranked
                if role is not top_role
                and score >= 0.65
                and not _compatible_profile_alternative(
                    top_role,
                    role,
                    header_scores,
                    profile_scores,
                )
            )
            if alternatives:
                diagnostics.append(f"alternative_role:{alternatives[0][0].value}")
        elif ranked:
            candidate, candidate_score = ranked[0]
            competing = tuple(
                (role, score)
                for role, score in ranked[1:]
                if not _compatible_profile_alternative(
                    candidate,
                    role,
                    header_scores,
                    profile_scores,
                )
            )
            second_score = competing[0][1] if competing else 0.0
            if candidate_score >= 0.65 and candidate_score - second_score >= 0.13:
                top_role = candidate
                top_score = candidate_score
                if second_score >= 0.65:
                    diagnostics.append(f"alternative_role:{competing[0][0].value}")
            else:
                diagnostics.append("ambiguous_role")
        else:
            diagnostics.append("no_semantic_evidence")
        if top_role is ColumnRole.UNKNOWN:
            ambiguous_indexes.append(column.index)
        else:
            if header_scores.get(top_role, 0.0) >= 0.82:
                diagnostics.append("role_evidence:header")
            if profile_scores.get(top_role, 0.0) > 0.0:
                diagnostics.append("role_evidence:value_profile")
        semantic_columns.append(
            column.model_copy(
                update={
                    "role": top_role,
                    "confidence": column.confidence * top_score,
                    "diagnostics": tuple(diagnostics),
                }
            )
        )

    bbox = _union_bbox(tuple(cell.bbox for cell in all_cells))
    known_fraction = (
        sum(column.role is not ColumnRole.UNKNOWN for column in semantic_columns)
        / len(semantic_columns)
        if semantic_columns
        else 0.0
    )
    schema_diagnostics = (
        ("ambiguous_columns:" + ",".join(str(index) for index in ambiguous_indexes),)
        if ambiguous_indexes
        else ()
    )
    return TableSchema(
        page_number=header_cells[0].page_number,
        bbox=bbox,
        columns=tuple(semantic_columns),
        header_cells=tuple(header_cells),
        sample_cells=tuple(sample_cells),
        confidence=known_fraction,
        diagnostics=schema_diagnostics,
    )
