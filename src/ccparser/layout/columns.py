"""Relative column-band clustering and financial semantic inference."""

from __future__ import annotations

import math
import re
import statistics
import unicodedata
from calendar import monthrange
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from types import MappingProxyType

from ccparser.evidence.models import VectorRule
from ccparser.geometry import (
    BBox,
    horizontal_overlap,
)
from ccparser.geometry import (
    bbox_center_x as _center_x,
)
from ccparser.geometry import (
    bbox_height as _height,
)
from ccparser.geometry import (
    bbox_width as _width,
)
from ccparser.geometry import (
    union_bbox as _union_bbox,
)
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableRegion, TableSchema
from ccparser.layout.row_tags import RowTag, has_row_tag, is_structural_continuation
from ccparser.money import canonical_currency, is_currency_shaped, is_money_shaped
from ccparser.text_tokens import (
    TokenSequence,
    contains_compiled_token_sequence,
    normalize_text,
    phrase_tokens,
)


@dataclass(frozen=True, slots=True)
class _TokenizedHeader:
    normalized: str
    tokens: TokenSequence
    compact: str
    is_hebrew: bool


def _tokenized_header(text: str) -> _TokenizedHeader:
    tokens = phrase_tokens(text)
    normalized = " ".join(tokens)
    return _TokenizedHeader(
        normalized=normalized,
        tokens=tokens,
        compact="".join(tokens),
        is_hebrew=any("\u0590" <= char <= "\u05ff" for char in normalized),
    )


def _compile_header_terms(terms: Iterable[str]) -> tuple[_TokenizedHeader, ...]:
    return tuple(_tokenized_header(term) for term in sorted(terms))


_THREE_COMPONENT_DATE_PATTERN = re.compile(
    r"(?<!\d)(\d{1,4})\s*([-/\.])\s*(\d{1,2})\s*\2\s*(\d{1,4})(?!\d)"
)
_TWO_COMPONENT_SLASH_PATTERN = re.compile(r"(?<!\d)(\d{1,3})\s*/\s*(\d{1,3})(?!\d)")
_LOCATION_IDENTIFIER_PATTERN = re.compile(r"^\d{10}$")
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
_OCR_DESCRIPTION_HEADER_ANCHORS = frozenset({"merchant", "בית", "עסק"})
_MAXIMUM_OCR_SLIVER_HEADER_CONFIDENCE = 0.8
_MAXIMUM_OCR_SLIVER_HEADER_ASPECT_RATIO = 0.2
_POLARITY_HEADER_MARKERS = frozenset({"+", "-", "\N{MINUS SIGN}", "\N{PLUS-MINUS SIGN}"})

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
            "עמלת מט ח",
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
_DESCRIPTION_NAME_HEADER_TERMS = frozenset({"merchant name", "שם בית עסק", "שם בית העסק"})
_EXCHANGE_RATE_HEADER_TERMS = tuple(_HEADER_VOCABULARY[ColumnRole.EXCHANGE_RATE])
_CONVERSION_DATE_HEADER_TERMS = tuple(
    (*_HEADER_VOCABULARY[ColumnRole.CONVERSION_DATE], "conversion", "exchange", "המרה")
)

_COMPILED_HEADER_VOCABULARY: Mapping[ColumnRole, tuple[_TokenizedHeader, ...]] = MappingProxyType(
    {role: _compile_header_terms(terms) for role, terms in _HEADER_VOCABULARY.items()}
)
_COMPILED_DESCRIPTION_NAME_HEADER_TERMS = _compile_header_terms(_DESCRIPTION_NAME_HEADER_TERMS)
_COMPILED_GENERIC_AMOUNT_HEADER_TERMS = _compile_header_terms(_GENERIC_AMOUNT_HEADER_TERMS)
_COMPILED_AUXILIARY_AMOUNT_MODIFIERS = _compile_header_terms(_AUXILIARY_AMOUNT_MODIFIERS)
_COMPILED_BILLING_AMOUNT_MODIFIERS = _compile_header_terms(_BILLING_AMOUNT_MODIFIERS)
_COMPILED_ORIGINAL_AMOUNT_MODIFIERS = _compile_header_terms(_ORIGINAL_AMOUNT_MODIFIERS)
_COMPILED_EXCHANGE_RATE_HEADER_TERMS = _compile_header_terms(_EXCHANGE_RATE_HEADER_TERMS)
_COMPILED_CONVERSION_DATE_HEADER_TERMS = _compile_header_terms(_CONVERSION_DATE_HEADER_TERMS)


def cells_in_column(cells: Iterable[Cell], column: ColumnSpec) -> tuple[Cell, ...]:
    """Return cells whose centers lie within the column's inclusive x band."""

    return tuple(cell for cell in cells if column.bbox[0] <= _center_x(cell.bbox) <= column.bbox[2])


def source_or_center_cells(cells: Iterable[Cell], column: ColumnSpec) -> tuple[Cell, ...]:
    """Prefer matching source cells, falling back to inclusive center membership."""

    candidates = tuple(cells)
    associated = tuple(cell for cell in candidates if cell in column.source_cells)
    return associated if associated else cells_in_column(candidates, column)


def columns_for_role(schema: TableSchema, role: ColumnRole) -> tuple[ColumnSpec, ...]:
    """Return schema columns with the requested semantic role in schema order."""

    return tuple(column for column in schema.columns if column.role is role)


def has_stable_unknown_profile(region: TableRegion, column: ColumnSpec) -> bool:
    """Return whether a headed unknown column has a repeated value-shape profile."""

    if column.role is not ColumnRole.UNKNOWN:
        return False
    header_text = normalize_text(
        " ".join(
            cell.text for cell in source_or_center_cells(region.table_schema.header_cells, column)
        )
    )
    values = tuple(
        cell
        for row in region.rows
        if not is_structural_continuation(row)
        for cell in cells_in_column(row.cells, column)
        if any(char.isalnum() for char in cell.text)
    )
    if not header_text or not any(char.isalnum() for char in header_text) or len(values) < 2:
        return False
    profiles: dict[str, int] = {}
    for cell in values:
        text = normalize_text(cell.text)
        profile = (
            "money"
            if is_money_shaped(text)
            else "date"
            if isolated_date_token(text) is not None
            else "numeric"
            if all(char.isdigit() or char.isspace() for char in text)
            else "alphabetic"
            if any(char.isalpha() for char in text) and not any(char.isdigit() for char in text)
            else "mixed"
        )
        profiles[profile] = profiles.get(profile, 0) + 1
    return max(profiles.values()) * 2 >= len(values)


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
    return _tokenized_header(text).normalized


def _same_semantic_family(first: ColumnRole, second: ColumnRole) -> bool:
    return any(first in family and second in family for family in _SEMANTIC_FAMILIES)


def _header_match_score(text: _TokenizedHeader, term: _TokenizedHeader) -> float:
    if text.normalized == term.normalized:
        return 1.0
    if term.is_hebrew:
        if text.compact == term.compact:
            return 1.0
        if term.compact in text.compact:
            return 0.82
        if (
            len(term.tokens) >= 3
            and len(text.tokens) == len(term.tokens)
            and text.tokens[:-1] == term.tokens[:-1]
            and any("\u0590" <= char <= "\u05ff" for char in term.tokens[-1])
            and any(char.isalpha() for char in text.tokens[-1])
            and not any("\u0590" <= char <= "\u05ff" for char in text.tokens[-1])
        ):
            return 0.82
    if contains_compiled_token_sequence(text.tokens, (term.tokens,)):
        return 0.82
    return 0.0


def _compatible_profile_alternative(
    selected: ColumnRole,
    alternative: ColumnRole,
    header_scores: dict[ColumnRole, float],
    profile_scores: dict[ColumnRole, float],
) -> bool:
    return (
        selected is ColumnRole.ORIGINAL_AMOUNT
        and alternative is ColumnRole.CURRENCY
        and header_scores.get(selected, 0.0) == 1.0
    ) or (
        _same_semantic_family(selected, alternative)
        and (
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
    )


def _contains_header_concept(
    text: _TokenizedHeader,
    terms: tuple[_TokenizedHeader, ...],
) -> bool:
    return any(
        contains_compiled_token_sequence(text.tokens, (term.tokens,))
        or term.compact in text.compact
        for term in terms
    )


def _has_header_concept(
    text: str,
    terms: tuple[_TokenizedHeader, ...],
) -> bool:
    return _contains_header_concept(_tokenized_header(text), terms)


def _is_explicit_billed_amount_header(text: str) -> bool:
    header = _tokenized_header(text)
    return (
        _contains_header_concept(header, _COMPILED_GENERIC_AMOUNT_HEADER_TERMS)
        and _contains_header_concept(header, _COMPILED_BILLING_AMOUNT_MODIFIERS)
        and not _contains_header_concept(header, _COMPILED_AUXILIARY_AMOUNT_MODIFIERS)
        and not _contains_header_concept(header, _COMPILED_ORIGINAL_AMOUNT_MODIFIERS)
    )


def _is_unqualified_generic_amount_header(text: str) -> bool:
    header = _tokenized_header(text)
    return (
        _contains_header_concept(header, _COMPILED_GENERIC_AMOUNT_HEADER_TERMS)
        and not _contains_header_concept(header, _COMPILED_BILLING_AMOUNT_MODIFIERS)
        and not _contains_header_concept(header, _COMPILED_AUXILIARY_AMOUNT_MODIFIERS)
        and not _contains_header_concept(header, _COMPILED_ORIGINAL_AMOUNT_MODIFIERS)
    )


def _header_evidence_texts(cells: Sequence[Cell]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(cell.text for cell in cells if cell.text.strip()))


def _header_scores(texts: Sequence[str]) -> dict[ColumnRole, float]:
    scores: dict[ColumnRole, float] = {}
    explicit_description_name = False
    for raw_text in texts:
        text = _tokenized_header(raw_text)
        composed_roles: set[ColumnRole] = set()
        if _contains_header_concept(text, _COMPILED_DESCRIPTION_NAME_HEADER_TERMS):
            composed_roles.add(ColumnRole.DESCRIPTION)
            explicit_description_name = True
        if _contains_header_concept(
            text, _COMPILED_GENERIC_AMOUNT_HEADER_TERMS
        ) and _contains_header_concept(text, _COMPILED_ORIGINAL_AMOUNT_MODIFIERS):
            composed_roles.add(ColumnRole.ORIGINAL_AMOUNT)
        if _contains_header_concept(
            text, _COMPILED_GENERIC_AMOUNT_HEADER_TERMS
        ) and _contains_header_concept(text, _COMPILED_AUXILIARY_AMOUNT_MODIFIERS):
            composed_roles.add(ColumnRole.AUXILIARY_AMOUNT)
        if _contains_header_concept(text, _COMPILED_EXCHANGE_RATE_HEADER_TERMS):
            composed_roles.add(ColumnRole.EXCHANGE_RATE)
        if _contains_header_concept(
            text, _COMPILED_HEADER_VOCABULARY[ColumnRole.DATE]
        ) and _contains_header_concept(text, _COMPILED_CONVERSION_DATE_HEADER_TERMS):
            composed_roles.add(ColumnRole.CONVERSION_DATE)
        exact_roles = {
            role
            for role, terms in _COMPILED_HEADER_VOCABULARY.items()
            if any(_header_match_score(text, term) == 1.0 for term in terms)
        } | composed_roles
        exact_specific_role = (
            next(iter(exact_roles))
            if len(exact_roles) == 1 and next(iter(exact_roles)) not in _GENERIC_FAMILY_ROLES
            else None
        )
        for role, terms in _COMPILED_HEADER_VOCABULARY.items():
            for term in terms:
                match_score = _header_match_score(text, term)
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
    if explicit_description_name:
        scores.pop(ColumnRole.LOCATION, None)
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


def is_location_identifier(text: str) -> bool:
    """Return whether normalized text is exactly a ten-digit location identifier."""

    return _LOCATION_IDENTIFIER_PATTERN.fullmatch(normalize_text(text)) is not None


def original_currency_spilled_into_location(
    cell: Cell,
    region: TableRegion,
) -> str | None:
    """Return an original currency proven to have spilled into a location cell."""

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
    original_on_left = _center_x(original_columns[0].bbox) < _center_x(location_columns[0].bbox)
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
    residual_edge_center = _center_x(_union_bbox(word.bbox for word in residual_words))
    currency_on_original_edge = (
        _center_x(currency_word.bbox) < residual_edge_center
        if original_on_left
        else _center_x(currency_word.bbox) > residual_edge_center
    )
    return canonical_currency(currency_word.text) if currency_on_original_edge else None


def _is_bounded_ocr_date_profile_cell(cell: Cell) -> bool:
    if not cell.words or any(word.source != "ocr" for word in cell.words):
        return False
    normalized = unicodedata.normalize("NFC", cell.text).strip()
    matches = tuple(
        match
        for match in _THREE_COMPONENT_DATE_PATTERN.finditer(normalized)
        if _is_exact_date_shaped(match.group(0))
    )
    if len(matches) == 1:
        match = matches[0]
        residual = normalized[: match.start()] + normalized[match.end() :]
        residual_alnum = tuple(char for char in residual if char.isalnum())
        return len(residual_alnum) <= 1 or (
            (match.start() == 0 or match.end() == len(normalized))
            and bool(residual_alnum)
            and not any(char.isdigit() for char in residual_alnum)
        )
    positioned_dates = tuple(
        word
        for word in cell.words
        if _is_exact_date_shaped(unicodedata.normalize("NFC", word.text).strip())
    )
    return len(positioned_dates) == 1 and sum(char.isalnum() for char in normalized) <= 1


def _profile_scores(cells: Sequence[Cell]) -> dict[ColumnRole, float]:
    if not cells:
        return {}
    matches: defaultdict[ColumnRole, int] = defaultdict(int)
    for cell in cells:
        text = cell.text
        stripped = unicodedata.normalize("NFC", text).strip()
        raw_currency = stripped.upper()
        compact_currency = _normalized_header(stripped).upper()
        if is_date_shaped(stripped) or _is_bounded_ocr_date_profile_cell(cell):
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
        fraction = count / len(cells)
        ceiling = 0.55 if role is ColumnRole.DESCRIPTION else 0.92
        scores[role] = ceiling * fraction
    return scores


def _is_corrupted_ocr_description_header(
    headers: Sequence[Cell],
    header_scores: dict[ColumnRole, float],
    profile_scores: dict[ColumnRole, float],
) -> bool:
    if (
        len(headers) != 1
        or max(header_scores.values(), default=0.0) >= 0.65
        or profile_scores.get(ColumnRole.DESCRIPTION, 0.0) < 0.4
    ):
        return False
    header = headers[0]
    if not header.words or any(word.source != "ocr" for word in header.words):
        return False
    tokens = _normalized_header(header.text).split()
    return 2 <= len(tokens) <= 4 and bool(set(tokens).intersection(_OCR_DESCRIPTION_HEADER_ANCHORS))


def explicit_billed_amount_column(
    columns: Sequence[ColumnSpec],
    header_cells: Sequence[Cell],
) -> ColumnSpec | None:
    """Return the sole amount column with an explicit billed/charged qualifier."""

    candidates = []
    for column in columns:
        if column.role is not ColumnRole.AMOUNT:
            continue
        texts = _header_evidence_texts(source_or_center_cells(header_cells, column))
        if any(_is_explicit_billed_amount_header(text) for text in texts):
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
        for cell in source_or_center_cells(row.cells, column)
    ):
        return None
    return explicit_column


def proven_region_billed_amount_column(region: TableRegion) -> ColumnSpec | None:
    """Select a billed column while excluding exact subordinate-detail rows."""

    transaction_rows = tuple(
        row for row in region.rows if not has_row_tag(row, RowTag.SUBORDINATE_DETAIL)
    )
    return proven_billed_amount_column(region.table_schema, transaction_rows)


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


def _has_strong_column_evidence(header: Cell, column: ColumnSpec) -> bool:
    if max(_header_scores(_header_evidence_texts((header,))).values(), default=0.0) >= 0.82:
        return True
    profile_scores = sorted(
        _profile_scores(tuple(cell for cell in column.source_cells if cell is not header)).values(),
        reverse=True,
    )
    return (
        bool(profile_scores)
        and profile_scores[0] >= 0.8
        and (len(profile_scores) == 1 or profile_scores[0] - profile_scores[1] >= 0.13)
    )


def _has_meaningful_symbol_header(text: str) -> bool:
    normalized = unicodedata.normalize("NFC", text).strip()
    return (
        canonical_currency(normalized) is not None
        or "%" in normalized
        or normalized in _POLARITY_HEADER_MARKERS
        or any(unicodedata.category(char) == "Sc" for char in normalized)
    )


def _has_aligned_positioned_sample(header: Cell, column: ColumnSpec) -> bool:
    return any(
        bool(cell.words or cell.glyphs)
        and _height(cell.bbox) > 0.0
        and abs(_center_x(cell.bbox) - _center_x(header.bbox)) <= _height(cell.bbox) * 0.5
        for cell in column.source_cells
        if cell is not header
    )


def _has_neighbor_owned_sample(
    header: Cell,
    column: ColumnSpec,
    preceding: Cell,
    following: Cell,
) -> bool:
    midpoint = (_center_x(preceding.bbox) + _center_x(following.bbox)) / 2
    return any(
        _width(sample.bbox) > 0.0
        and horizontal_overlap(sample.bbox, neighbor.bbox) / _width(sample.bbox) >= 0.75
        and ((_center_x(sample.bbox) < midpoint) == is_preceding)
        for sample in column.source_cells
        if sample is not header
        for neighbor, is_preceding in ((preceding, True), (following, False))
    )


def _is_discardable_ocr_sliver_header(
    header: Cell,
    column: ColumnSpec,
    preceding: Cell,
    preceding_column: ColumnSpec,
    following: Cell,
    following_column: ColumnSpec,
) -> bool:
    return (
        bool(header.words)
        and all(word.source == "ocr" for word in header.words)
        and not header.glyphs
        and header.confidence < _MAXIMUM_OCR_SLIVER_HEADER_CONFIDENCE
        and _height(header.bbox) > 0.0
        and _width(header.bbox) / _height(header.bbox) <= _MAXIMUM_OCR_SLIVER_HEADER_ASPECT_RATIO
        and not any(char.isalnum() for char in normalize_text(header.text))
        and not _has_meaningful_symbol_header(header.text)
        and not _has_aligned_positioned_sample(header, column)
        and _has_strong_column_evidence(preceding, preceding_column)
        and _has_strong_column_evidence(following, following_column)
        and _has_neighbor_owned_sample(header, column, preceding, following)
    )


def _retained_header_cells(
    header_cells: Sequence[Cell],
    sample_cells: Sequence[Cell],
) -> tuple[tuple[Cell, ...], bool]:
    ordered = tuple(sorted(header_cells, key=lambda cell: _center_x(cell.bbox)))
    if len(ordered) < 3:
        return tuple(header_cells), False
    columns = _header_anchored_columns(ordered, sample_cells)
    discarded = frozenset(
        header
        for index, (header, column) in enumerate(zip(ordered, columns, strict=True))
        if 0 < index < len(ordered) - 1
        and _is_discardable_ocr_sliver_header(
            header,
            column,
            ordered[index - 1],
            columns[index - 1],
            ordered[index + 1],
            columns[index + 1],
        )
    )
    return tuple(cell for cell in header_cells if cell not in discarded), bool(discarded)


def _disambiguate_qualified_original_amount(
    columns: Sequence[ColumnSpec],
    header_cells: Sequence[Cell],
) -> tuple[ColumnSpec, ...]:
    original_columns = tuple(
        column for column in columns if column.role is ColumnRole.ORIGINAL_AMOUNT
    )
    billed_columns = tuple(
        column
        for column in columns
        if column.role is ColumnRole.AMOUNT
        and any(
            _has_header_concept(text, _COMPILED_BILLING_AMOUNT_MODIFIERS)
            for text in _header_evidence_texts(source_or_center_cells(header_cells, column))
        )
    )
    if len(original_columns) != 2 or len(billed_columns) != 1:
        return tuple(columns)
    qualified = tuple(
        column
        for column in original_columns
        if any(
            _has_header_concept(text, _COMPILED_ORIGINAL_AMOUNT_MODIFIERS)
            for text in _header_evidence_texts(source_or_center_cells(header_cells, column))
        )
    )
    if len(qualified) != 1:
        return tuple(columns)
    intermediate = next(column for column in original_columns if column is not qualified[0])
    intermediate_texts = _header_evidence_texts(source_or_center_cells(header_cells, intermediate))
    if not any(_is_unqualified_generic_amount_header(text) for text in intermediate_texts):
        return tuple(columns)
    return tuple(
        column.model_copy(
            update={
                "role": ColumnRole.AUXILIARY_AMOUNT,
                "diagnostics": tuple(
                    dict.fromkeys((*column.diagnostics, "role_evidence:qualified_original_peer"))
                ),
            }
        )
        if column is intermediate
        else column
        for column in columns
    )


def _disambiguate_generic_original_peer(
    columns: Sequence[ColumnSpec],
    header_cells: Sequence[Cell],
) -> tuple[ColumnSpec, ...]:
    amount_columns = tuple(column for column in columns if column.role is ColumnRole.AMOUNT)
    if (
        len(amount_columns) != 2
        or any(column.role is ColumnRole.ORIGINAL_AMOUNT for column in columns)
        or (billed := explicit_billed_amount_column(columns, header_cells)) is None
    ):
        return tuple(columns)
    peer = next(column for column in amount_columns if column is not billed)
    peer_texts = _header_evidence_texts(source_or_center_cells(header_cells, peer))
    if not any(_is_unqualified_generic_amount_header(text) for text in peer_texts):
        return tuple(columns)
    return tuple(
        column.model_copy(
            update={
                "role": ColumnRole.ORIGINAL_AMOUNT,
                "diagnostics": tuple(
                    dict.fromkeys((*column.diagnostics, "role_evidence:generic_original_peer"))
                ),
            }
        )
        if column is peer
        else column
        for column in columns
    )


def infer_column_roles(header_cells: Sequence[Cell], sample_cells: Sequence[Cell]) -> TableSchema:
    """Combine general financial header vocabulary with typed value profiles."""

    if not header_cells:
        raise ValueError("at least one header cell is required")
    all_cells = (*header_cells, *sample_cells)
    page_numbers = {cell.page_number for cell in all_cells}
    if len(page_numbers) != 1:
        raise ValueError("semantic inference requires cells from one page")
    retained_headers, discarded_sliver_header = _retained_header_cells(
        header_cells,
        sample_cells,
    )
    bands = _header_anchored_columns(retained_headers, sample_cells)
    semantic_columns: list[ColumnSpec] = []
    ambiguous_indexes: list[int] = []
    for column in bands:
        headers = source_or_center_cells(retained_headers, column)
        samples = source_or_center_cells(sample_cells, column)
        header_scores = _header_scores(_header_evidence_texts(headers))
        profile_scores = _profile_scores(samples)
        recovered_ocr_description = _is_corrupted_ocr_description_header(
            headers,
            header_scores,
            profile_scores,
        )
        if recovered_ocr_description:
            header_scores[ColumnRole.DESCRIPTION] = 0.82
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
            if recovered_ocr_description and top_role is ColumnRole.DESCRIPTION:
                diagnostics.append("role_evidence:ocr_description_recovery")
        semantic_columns.append(
            column.model_copy(
                update={
                    "role": top_role,
                    "confidence": column.confidence * top_score,
                    "diagnostics": tuple(diagnostics),
                }
            )
        )

    semantic_columns = list(
        _disambiguate_qualified_original_amount(semantic_columns, retained_headers)
    )
    semantic_columns = list(_disambiguate_generic_original_peer(semantic_columns, retained_headers))

    bbox = _union_bbox(tuple(cell.bbox for cell in all_cells))
    known_fraction = (
        sum(column.role is not ColumnRole.UNKNOWN for column in semantic_columns)
        / len(semantic_columns)
        if semantic_columns
        else 0.0
    )
    schema_diagnostics = tuple(
        (
            *(
                ("ambiguous_columns:" + ",".join(str(index) for index in ambiguous_indexes),)
                if ambiguous_indexes
                else ()
            ),
            *(("discarded_ocr_sliver_header_anchor",) if discarded_sliver_header else ()),
        )
    )
    return TableSchema(
        page_number=header_cells[0].page_number,
        bbox=bbox,
        columns=tuple(semantic_columns),
        header_cells=retained_headers,
        sample_cells=tuple(sample_cells),
        confidence=known_fraction,
        diagnostics=schema_diagnostics,
    )
