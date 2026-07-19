"""Relative column-band clustering and financial semantic inference."""

from __future__ import annotations

import math
import re
import statistics
import unicodedata
from calendar import monthrange
from collections import defaultdict
from collections.abc import Iterable, Sequence
from itertools import pairwise

from ccparser.evidence.models import BBox, VectorRule
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableSchema
from ccparser.money import is_money_shaped

_THREE_COMPONENT_DATE_PATTERN = re.compile(
    r"(?<!\d)(\d{1,4})\s*([-/\.])\s*(\d{1,2})\s*\2\s*(\d{1,4})(?!\d)"
)
_TWO_COMPONENT_SLASH_PATTERN = re.compile(r"(?<!\d)(\d{1,3})\s*/\s*(\d{1,3})(?!\d)")
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
    ColumnRole.CONVERSION_DATE: frozenset(
        {
            "conversion date",
            "date of conversion",
            "exchange date",
            "תאריך המרה",
            "תאריך ההמרה",
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
            "שם בית העסק",
            "תיאור",
        }
    ),
    ColumnRole.LOCATION: frozenset({"city", "location", "עיר"}),
    ColumnRole.AMOUNT: frozenset(
        {
            "amount",
            "amount charged",
            "billed amount",
            "charge amount",
            "סכום",
            "סכום חיוב",
            "סכום החיוב",
            "סכום לחיוב",
        }
    ),
    ColumnRole.AUXILIARY_AMOUNT: frozenset(
        {
            "commission amount",
            "fee amount",
            "surcharge amount",
            "סכום עמלה",
            "סכום העמלה",
            "סכוםעמלה",
            "סכוםהעמלה",
        }
    ),
    ColumnRole.ORIGINAL_AMOUNT: frozenset(
        {
            "original amount",
            "transaction amount",
            "סכום במקור",
            "סכום עסקה",
            "סכום העסקה",
            "סכום עסקה מקורי",
        }
    ),
    ColumnRole.EXCHANGE_RATE: frozenset(
        {
            "conversion rate",
            "exchange rate",
            "שער המרה",
            "שער ההמרה",
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
    frozenset({ColumnRole.DATE, ColumnRole.CONVERSION_DATE}),
    frozenset(
        {
            ColumnRole.AMOUNT,
            ColumnRole.AUXILIARY_AMOUNT,
            ColumnRole.EXCHANGE_RATE,
            ColumnRole.ORIGINAL_AMOUNT,
        }
    ),
    frozenset(
        {
            ColumnRole.CURRENCY,
            ColumnRole.BILLING_CURRENCY,
            ColumnRole.ORIGINAL_CURRENCY,
        }
    ),
)
_GENERIC_FAMILY_ROLES = frozenset({ColumnRole.AMOUNT, ColumnRole.CURRENCY, ColumnRole.DATE})
_EXACT_HEADER_ONLY_ROLES = frozenset({ColumnRole.LOCATION})
_GENERIC_AMOUNT_HEADER_TERMS = frozenset({"amount", "סכום"})
_AUXILIARY_AMOUNT_MODIFIERS = frozenset({"commission", "fee", "surcharge", "עמלה"})
_BILLING_AMOUNT_MODIFIERS = frozenset(
    {"bill", "billed", "billing", "charge", "charged", "חיוב", "לחיוב"}
)
_ORIGINAL_AMOUNT_MODIFIERS = frozenset({"original", "מקור", "מקורי"})
_EXCHANGE_RATE_HEADER_TERMS = tuple(_HEADER_VOCABULARY[ColumnRole.EXCHANGE_RATE])
_CONVERSION_DATE_HEADER_TERMS = tuple(
    (*_HEADER_VOCABULARY[ColumnRole.CONVERSION_DATE], "conversion", "exchange", "המרה")
)


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


def _is_hebrew_phrase(text: str) -> bool:
    return any("\u0590" <= char <= "\u05ff" for char in text)


def _header_match_score(text: str, term: str) -> float:
    if text == term:
        return 1.0
    if _is_hebrew_phrase(term):
        compact_text = text.replace(" ", "")
        compact_term = term.replace(" ", "")
        if compact_text == compact_term:
            return 1.0
        if compact_term in compact_text:
            return 0.82
    if _contains_token_phrase(text, term):
        return 0.82
    return 0.0


def _compatible_profile_alternative(
    selected: ColumnRole,
    alternative: ColumnRole,
    header_scores: dict[ColumnRole, float],
    profile_scores: dict[ColumnRole, float],
) -> bool:
    return _same_semantic_family(selected, alternative) and (
        (
            header_scores.get(selected, 0.0) == 1.0
            and alternative in _GENERIC_FAMILY_ROLES
            and header_scores.get(alternative, 0.0) <= 0.82
        )
        or (
            header_scores.get(alternative, 0.0) < 0.65
            and profile_scores.get(alternative, 0.0) >= 0.65
        )
    )


def _contains_header_concept(text: str, terms: Iterable[str]) -> bool:
    compact_text = text.replace(" ", "")
    return any(
        _contains_token_phrase(text, term) or term.replace(" ", "") in compact_text
        for term in terms
    )


def _header_evidence_texts(cells: Sequence[Cell]) -> tuple[str, ...]:
    texts: list[str] = []
    for cell in cells:
        logical_words = cell.text.split()
        texts.append(cell.text)
        if _is_hebrew_phrase(cell.text):
            texts.extend(
                (
                    cell.text[::-1],
                    " ".join(word[::-1] for word in logical_words),
                    " ".join(reversed(logical_words)),
                )
            )
        if cell.words:
            source_words = tuple(word.text for word in cell.words)
            source_text = " ".join(source_words)
            texts.append(source_text)
            if _is_hebrew_phrase(source_text):
                texts.append(" ".join(reversed(source_words)))
    return tuple(dict.fromkeys(text for text in texts if text.strip()))


def _header_scores(texts: Sequence[str]) -> dict[ColumnRole, float]:
    scores: dict[ColumnRole, float] = {}
    for text in texts:
        normalized = _normalized_header(text)
        composed_roles: set[ColumnRole] = set()
        if _contains_header_concept(
            normalized, _GENERIC_AMOUNT_HEADER_TERMS
        ) and _contains_header_concept(normalized, _ORIGINAL_AMOUNT_MODIFIERS):
            composed_roles.add(ColumnRole.ORIGINAL_AMOUNT)
        if _contains_header_concept(
            normalized, _GENERIC_AMOUNT_HEADER_TERMS
        ) and _contains_header_concept(normalized, _AUXILIARY_AMOUNT_MODIFIERS):
            composed_roles.add(ColumnRole.AUXILIARY_AMOUNT)
        if _contains_header_concept(normalized, _EXCHANGE_RATE_HEADER_TERMS):
            composed_roles.add(ColumnRole.EXCHANGE_RATE)
        if _contains_header_concept(
            normalized, _HEADER_VOCABULARY[ColumnRole.DATE]
        ) and _contains_header_concept(normalized, _CONVERSION_DATE_HEADER_TERMS):
            composed_roles.add(ColumnRole.CONVERSION_DATE)
        exact_roles = {
            role
            for role, terms in _HEADER_VOCABULARY.items()
            if any(_header_match_score(normalized, term) == 1.0 for term in terms)
        } | composed_roles
        exact_specific_role = (
            next(iter(exact_roles))
            if len(exact_roles) == 1 and next(iter(exact_roles)) not in _GENERIC_FAMILY_ROLES
            else None
        )
        for role, terms in _HEADER_VOCABULARY.items():
            for term in terms:
                match_score = _header_match_score(normalized, term)
                if match_score == 1.0:
                    scores[role] = max(scores.get(role, 0.0), 1.0)
                elif match_score:
                    if (
                        exact_specific_role is not None
                        and role in _GENERIC_FAMILY_ROLES
                        and _same_semantic_family(exact_specific_role, role)
                    ):
                        continue
                    scores[role] = max(scores.get(role, 0.0), match_score)
        for role in composed_roles:
            scores[role] = 1.0
    exact_specific_roles = tuple(
        role for role, score in scores.items() if score == 1.0 and role not in _GENERIC_FAMILY_ROLES
    )
    if len(exact_specific_roles) == 1:
        specific_role = exact_specific_roles[0]
        scores = {
            role: score
            for role, score in scores.items()
            if not (role in _GENERIC_FAMILY_ROLES and _same_semantic_family(specific_role, role))
        }
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


def _is_exact_date_shaped(text: str) -> bool:
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


def isolated_date_token(text: str) -> str | None:
    """Return one valid date token with at most one standalone letter around it."""

    normalized = unicodedata.normalize("NFC", text).strip()
    candidate_matches = tuple(_THREE_COMPONENT_DATE_PATTERN.finditer(normalized))
    if not candidate_matches:
        candidate_matches = tuple(_TWO_COMPONENT_SLASH_PATTERN.finditer(normalized))
    valid_matches = tuple(
        match for match in candidate_matches if _is_exact_date_shaped(match.group(0))
    )
    if len(valid_matches) != 1:
        return None
    match = valid_matches[0]
    remainder = normalized[: match.start()] + normalized[match.end() :]
    if any(char.isdigit() for char in remainder):
        return None
    if sum(char.isalpha() for char in remainder) > 1:
        return None
    return match.group(0)


def contains_date_token(text: str) -> bool:
    """Return whether text contains at least one complete valid calendar date."""

    normalized = unicodedata.normalize("NFC", text)
    return any(
        _is_exact_date_shaped(match.group(0))
        for match in _THREE_COMPONENT_DATE_PATTERN.finditer(normalized)
    )


def is_date_shaped(text: str) -> bool:
    """Return whether text is one valid date with only a tiny standalone annotation."""

    return isolated_date_token(text) is not None


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


def explicit_billed_amount_column(
    columns: Sequence[ColumnSpec],
    header_cells: Sequence[Cell],
) -> ColumnSpec | None:
    """Return the sole amount column with an explicit billed/charged qualifier."""

    candidates = []
    for column in columns:
        if column.role is not ColumnRole.AMOUNT:
            continue
        texts = _header_evidence_texts(_cells_for_column(header_cells, column))
        if any(
            _contains_header_concept(_normalized_header(text), _GENERIC_AMOUNT_HEADER_TERMS)
            and _contains_header_concept(_normalized_header(text), _BILLING_AMOUNT_MODIFIERS)
            and not _contains_header_concept(_normalized_header(text), _AUXILIARY_AMOUNT_MODIFIERS)
            and not _contains_header_concept(_normalized_header(text), _ORIGINAL_AMOUNT_MODIFIERS)
            for text in texts
        ):
            candidates.append(column)
    return candidates[0] if len(candidates) == 1 else None


def proven_billed_amount_column(
    schema: TableSchema,
    rows: Sequence[Row],
) -> ColumnSpec | None:
    """Select billed evidence without retyping empty secondary amount bands."""

    amount_columns = tuple(column for column in schema.columns if column.role is ColumnRole.AMOUNT)
    if len(amount_columns) == 1:
        return amount_columns[0]
    explicit_column = explicit_billed_amount_column(
        schema.columns,
        schema.header_cells,
    )
    if explicit_column is None:
        return None
    secondary_columns = tuple(column for column in amount_columns if column is not explicit_column)
    if any(
        is_money_shaped(cell.text)
        for row in rows
        for column in secondary_columns
        for cell in _cells_for_column(row.cells, column)
    ):
        return None
    return explicit_column


def _header_anchored_columns(
    header_cells: Sequence[Cell],
    sample_cells: Sequence[Cell],
) -> tuple[ColumnSpec, ...]:
    ordered_headers = tuple(sorted(header_cells, key=lambda cell: _center_x(cell.bbox)))
    all_cells = (*header_cells, *sample_cells)
    table_bbox = _union_bbox(tuple(cell.bbox for cell in all_cells))
    table_width = _width(table_bbox)
    boundaries = [table_bbox[0]]
    boundaries.extend(
        (_center_x(first.bbox) + _center_x(second.bbox)) / 2
        for first, second in pairwise(ordered_headers)
    )
    boundaries.append(table_bbox[2])
    columns: list[ColumnSpec] = []
    for index, (header, left, right) in enumerate(
        zip(ordered_headers, boundaries[:-1], boundaries[1:], strict=True)
    ):
        samples = tuple(
            cell
            for cell in sample_cells
            if left <= _center_x(cell.bbox) < right
            or (index == len(ordered_headers) - 1 and _center_x(cell.bbox) == right)
        )
        columns.append(
            ColumnSpec(
                index=index,
                page_number=header.page_number,
                bbox=(left, table_bbox[1], right, table_bbox[3]),
                relative_x0=(left - table_bbox[0]) / table_width,
                relative_x1=(right - table_bbox[0]) / table_width,
                source_cells=(header, *samples),
                confidence=1.0,
                diagnostics=("header_anchor_support",),
            )
        )
    return tuple(columns)


def infer_column_roles(header_cells: Sequence[Cell], sample_cells: Sequence[Cell]) -> TableSchema:
    """Combine general financial header vocabulary with typed value profiles."""

    if not header_cells:
        raise ValueError("at least one header cell is required")
    all_cells = (*header_cells, *sample_cells)
    page_numbers = {cell.page_number for cell in all_cells}
    if len(page_numbers) != 1:
        raise ValueError("semantic inference requires cells from one page")
    bands = _header_anchored_columns(header_cells, sample_cells)
    semantic_columns: list[ColumnSpec] = []
    ambiguous_indexes: list[int] = []
    for column in bands:
        headers = _cells_for_column(header_cells, column)
        samples = _cells_for_column(sample_cells, column)
        header_scores = _header_scores(_header_evidence_texts(headers))
        profile_scores = _profile_scores(tuple(cell.text for cell in samples))
        scores = dict(header_scores)
        exact_header_roles = tuple(role for role, score in header_scores.items() if score == 1.0)
        strongest_header_score = max(header_scores.values(), default=0.0)
        tied_header_roles = tuple(
            role
            for role, score in header_scores.items()
            if score == strongest_header_score and score >= 0.82
        )
        profile_supported_tied_roles = tuple(
            role for role in tied_header_roles if profile_scores.get(role, 0.0) >= 0.5
        )
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
        elif len(tied_header_roles) > 1 and len(profile_supported_tied_roles) == 1:
            top_role = profile_supported_tied_roles[0]
            top_score = strongest_header_score
            diagnostics.append(
                "alternative_role:"
                + next(role.value for role in tied_header_roles if role is not top_role)
            )
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
            exact_header_missing = (
                candidate in _EXACT_HEADER_ONLY_ROLES and header_scores.get(candidate, 0.0) < 1.0
            )
            if (
                not exact_header_missing
                and candidate_score >= 0.65
                and candidate_score - second_score >= 0.13
            ):
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
