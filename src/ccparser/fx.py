"""Geometry-bounded foreign-exchange value extraction."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from itertools import pairwise

from ccparser.decimal_math import exact_difference, exact_product, exact_sum
from ccparser.evidence.models import Glyph
from ccparser.geometry import (
    bbox_center_y,
    bbox_height,
    center_inside,
    union_bbox,
    vertical_overlap,
)
from ccparser.layout.columns import (
    cells_in_column,
    is_installment_shaped,
    source_or_center_cells,
)
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableRegion
from ccparser.layout.row_tags import RowTag, has_row_tag
from ccparser.layout.text import logical_text_for_evidence
from ccparser.models import (
    EvidenceReference,
    ExtractedDecimal,
    ExtractedMoney,
    ForeignExchangeDetails,
)
from ccparser.money import (
    canonical_currency,
    contains_credit_marker,
    currencies_in_text,
    parse_amount,
)
from ccparser.normalization_dates import proven_conversion_rate_residual_atom_ids
from ccparser.semantic_evidence import (
    EvidenceAtom,
    EvidenceClaim,
    EvidenceLedger,
    PositionedDecimalCandidate,
    PositionedNumberCandidate,
    PositionedPercentageCandidate,
    SemanticOwner,
)
from ccparser.text_tokens import (
    HEBREW_CLITIC_PREFIXES,
    contains_token_sequence,
    normalize_text,
    phrase_tokens,
)


@dataclass(frozen=True, slots=True)
class ForeignExchangeExtraction:
    """Structured FX values plus exact evidence ownership and diagnostics."""

    details: ForeignExchangeDetails | None = None
    claims: tuple[EvidenceClaim, ...] = ()
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _FxValues:
    exchange_rate: ExtractedDecimal | None = None
    fee_percentage: ExtractedDecimal | None = None
    gross_fee: ExtractedMoney | None = None
    fee_discount: ExtractedMoney | None = None
    net_fee: ExtractedMoney | None = None
    claims: tuple[EvidenceClaim, ...] = ()
    diagnostics: tuple[str, ...] = ()
    ambiguous_owners: frozenset[SemanticOwner] = frozenset()
    unowned_monetary_evidence: bool = False


@dataclass(frozen=True, slots=True)
class _ProjectedDiscountEvidence:
    """Exact projected evidence for a separately stated discount percentage."""

    percentage_atom_ids: frozenset[int] = frozenset()
    ancillary_atom_ids: frozenset[int] = frozenset()


_RATE_HEADER_CUES = (
    "conversion rate",
    "exchange rate",
    "representative rate",
    "שער המרה",
    "שער ההמרה",
    "שער יציג",
    "שער",
)
_FEE_HEADER_CUES = (
    "commission",
    "fee",
    "surcharge",
    "עמלה",
    "עמלת",
)
_GROSS_FEE_CUES = (
    "gross fee",
    "fee amount",
    "commission amount",
    "charged fee",
    "עמלה בסך",
    "עמלת מט ח בסך",
)
_DISCOUNT_CUES = (
    "discount",
    "הנחה",
    "מופחתת",
)
_DISCOUNT_COLLISION_CUES = (
    "discount",
    "הנחה",
)
_REDUCED_FEE_MODIFIERS = (
    "reduced",
    "מופחתת",
)
_NET_FEE_MODIFIERS = (
    "net",
    "נטו",
)
_NET_FEE_NOUN_CUES = (
    *_FEE_HEADER_CUES,
    "amount",
    "סכום",
)
_RATE_COMPONENT_INCOMPATIBLE_CUES = (
    *_FEE_HEADER_CUES,
    *_GROSS_FEE_CUES,
    *_DISCOUNT_CUES,
    *_REDUCED_FEE_MODIFIERS,
    *_NET_FEE_MODIFIERS,
)
_PERCENTAGE_COMPONENT_INCOMPATIBLE_CUES = (
    *_RATE_HEADER_CUES,
    *_GROSS_FEE_CUES,
    *_DISCOUNT_CUES,
    *_REDUCED_FEE_MODIFIERS,
    *_NET_FEE_MODIFIERS,
)
_GROSS_COMPONENT_INCOMPATIBLE_CUES = (
    *_RATE_HEADER_CUES,
    *_NET_FEE_MODIFIERS,
)
_DISCOUNT_COMPONENT_INCOMPATIBLE_CUES = (
    *_RATE_HEADER_CUES,
    *_GROSS_FEE_CUES,
    *_NET_FEE_MODIFIERS,
)
_BOUND_NET_FEE_CUES = tuple(
    f"{modifier} {noun}"
    for modifier in (*_REDUCED_FEE_MODIFIERS, *_NET_FEE_MODIFIERS)
    for noun in _FEE_HEADER_CUES
) + tuple(
    f"{noun} {modifier}"
    for noun in _FEE_HEADER_CUES
    for modifier in (*_REDUCED_FEE_MODIFIERS, *_NET_FEE_MODIFIERS)
)
_CURRENCYLESS_MONEY_WRAPPERS = frozenset(
    ".,'\N{RIGHT SINGLE QUOTATION MARK}+-()%\N{MINUS SIGN}\N{EN DASH}\N{EM DASH}"
)
_MONEY_CONTEXT_PHRASES = (
    *_RATE_HEADER_CUES,
    *_FEE_HEADER_CUES,
    *_GROSS_FEE_CUES,
    *_DISCOUNT_CUES,
    *_REDUCED_FEE_MODIFIERS,
    *_NET_FEE_MODIFIERS,
    "foreign currency",
    "billing currency",
    "local currency",
    "auxiliary amount",
    "net amount",
    "gross amount",
    "calculated at",
    "converted on",
    "converted at",
    "conversion date",
    "date of conversion",
    "discount follows",
    "from this fee a discount is subtracted",
    "under arrangement",
    "and",
    "of",
    "the",
    "to",
    "on",
    "note",
    "fx",
    "מטבע זר",
    "מטבע מקומי",
    "סכום",
    "חיוב",
    "תאריך המרה",
    "תאריך ההמרה",
    "הומר בתאריך",
)
_MONEY_CONTEXT_TOKENS = frozenset(
    token
    for phrase in _MONEY_CONTEXT_PHRASES
    for token in phrase_tokens(phrase, ignore_acronym_quotes=True)
)
_DATE_ONLY_SOURCE_TOKENS = frozenset(
    token
    for phrase in (
        "converted on",
        "converted at",
        "conversion date",
        "date of conversion",
        "תאריך המרה",
        "תאריך ההמרה",
        "הומר בתאריך",
    )
    for token in phrase_tokens(phrase, ignore_acronym_quotes=True)
)
_NONFINANCIAL_IDENTIFIER_CUES = (
    "card",
    "card identifier",
    "card number",
    "reference",
    "identifier",
    "terminal",
    "authorization",
    "approval",
    "voucher",
    "merchant identifier",
    "כרטיס",
    "מזהה",
    "אסמכתא",
    "מסוף",
    "אישור",
    "שובר",
)
_COMPETING_PERCENT_METADATA_CUES = (
    *_RATE_HEADER_CUES,
    *_FEE_HEADER_CUES,
    *_GROSS_FEE_CUES,
    *_DISCOUNT_CUES,
    *_REDUCED_FEE_MODIFIERS,
    *_NET_FEE_MODIFIERS,
    "interest",
    "markup",
    "tax",
    "vat",
)
_UNSUPPORTED_CURRENCY_CODES = frozenset(
    re.findall(
        r"[A-Z]{3}",
        """
        AED AFN ALL AMD ANG AOA ARS AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BOV BRL BSD BTN
        BWP BYN BZD CDF CLF CLP CNY COP COU CRC CUC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB FJD
        FKP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HTG HUF IDR INR IQD IRR ISK JMD JOD KES KGS KHR
        KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR
        MWK MXN MXV MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD
        RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SLL SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND
        TOP TRY TTD TWD TZS UAH UGX USN UYI UYU UYW UZS VED VES VND VUV WST XAF XAG XAU XBA XBB
        XBC XBD XCD XCG XDR XOF XPD XPF XPT XSU XTS XUA XXX YER ZAR ZMW ZWL
        """,
    )
)
_UNSUPPORTED_CURRENCY_NAMES = frozenset(
    {
        "krona",
        "krone",
        "renminbi",
        "rouble",
        "ruble",
        "rupee",
        "yuan",
        "元",
        "円",
    }
)


def _is_recognized_context_token(token: str) -> bool:
    return token in _MONEY_CONTEXT_TOKENS or (
        len(token) > 1
        and token[0] in HEBREW_CLITIC_PREFIXES
        and token[1:] in _MONEY_CONTEXT_TOKENS
        and any("\u0590" <= char <= "\u05ff" for char in token[1:])
    )


def _has_only_recognized_money_context(text: str) -> bool:
    if any(
        unicodedata.category(char) == "Sc" and canonical_currency(char) is None for char in text
    ):
        return False

    def is_clean_money_token(token: str) -> bool:
        parsed = parse_amount(token)
        return parsed.amount is not None and parsed.currency is not None and not parsed.diagnostics

    return all(
        (any(char.isdigit() for char in token) and not any(char.isalpha() for char in token))
        or is_clean_money_token(token)
        or canonical_currency(token) is not None
        or _is_recognized_context_token(token)
        for token in phrase_tokens(text, ignore_acronym_quotes=True)
    )


def _has_valid_typed_decimal_context(
    source_texts: Sequence[str],
    original_currency: str,
    billing_currency: str,
) -> bool:
    allowed_currencies = frozenset(
        currency
        for value in (original_currency, billing_currency)
        if (currency := canonical_currency(value)) is not None
    )
    return all(
        _has_only_recognized_money_context(source_text)
        and set(currencies_in_text(source_text)) <= allowed_currencies
        for source_text in source_texts
    )


def _has_bounded_numeric_context(
    source_texts: Sequence[str],
    billing_currency: str,
) -> bool:
    return canonical_currency(billing_currency) in currencies_in_text(
        " ".join(source_texts)
    ) or all(_has_only_recognized_money_context(source) for source in source_texts)


def _has_unsupported_header_currency(text: str) -> bool:
    if any(
        unicodedata.category(char) == "Sc" and canonical_currency(char) is None for char in text
    ):
        return True
    for token in phrase_tokens(text, ignore_acronym_quotes=True):
        upper = token.upper()
        if upper in _UNSUPPORTED_CURRENCY_CODES or token in _UNSUPPORTED_CURRENCY_NAMES:
            return True
        if len(upper) > 3 and len(upper) % 3 == 0 and upper.isalpha():
            chunks = tuple(upper[index : index + 3] for index in range(0, len(upper), 3))
            if all(
                canonical_currency(chunk) is not None or chunk in _UNSUPPORTED_CURRENCY_CODES
                for chunk in chunks
            ) and any(chunk in _UNSUPPORTED_CURRENCY_CODES for chunk in chunks):
                return True
    return False


def _header_phrase(column: ColumnSpec, header_cells: Sequence[Cell]) -> str:
    return " ".join(cell.text for cell in source_or_center_cells(header_cells, column))


def _contains_cue(phrase: str, cues: Iterable[str]) -> bool:
    return contains_token_sequence(
        phrase,
        cues,
        allow_hebrew_clitic_prefix=True,
    )


def _has_explicit_net_fee_semantics(phrase: str) -> bool:
    return _contains_cue(phrase, (*_REDUCED_FEE_MODIFIERS, *_NET_FEE_MODIFIERS)) and _contains_cue(
        phrase, _NET_FEE_NOUN_CUES
    )


def _has_net_fee_semantics(phrase: str) -> bool:
    return _contains_cue(phrase, _REDUCED_FEE_MODIFIERS) or (
        _contains_cue(phrase, _NET_FEE_MODIFIERS) and _has_explicit_net_fee_semantics(phrase)
    )


def _has_bound_net_fee_semantics(phrase: str) -> bool:
    return _contains_cue(phrase, _BOUND_NET_FEE_CUES)


def _has_unbound_net_fee_modifier(phrase: str) -> bool:
    return _contains_cue(phrase, _NET_FEE_MODIFIERS) and not _contains_cue(
        phrase,
        _NET_FEE_NOUN_CUES,
    )


def _has_conflicting_net_fee_semantics(phrase: str) -> bool:
    return _contains_cue(phrase, (*_RATE_HEADER_CUES, *_GROSS_FEE_CUES)) or (
        _contains_cue(phrase, _DISCOUNT_COLLISION_CUES) and not _has_bound_net_fee_semantics(phrase)
    )


def _is_fee_column(column: ColumnSpec, header_cells: Sequence[Cell]) -> bool:
    phrase = _header_phrase(column, header_cells)
    return column.role is ColumnRole.AUXILIARY_AMOUNT and (
        _contains_cue(phrase, _FEE_HEADER_CUES) or _has_net_fee_semantics(phrase)
    )


def _is_rate_column(column: ColumnSpec, header_cells: Sequence[Cell]) -> bool:
    return column.role is ColumnRole.EXCHANGE_RATE or (
        column.role is ColumnRole.CONVERSION_DATE
        and _contains_cue(_header_phrase(column, header_cells), _RATE_HEADER_CUES)
    )


def _field_evidence(cells: Iterable[Cell]) -> tuple[EvidenceReference, ...]:
    references = (
        EvidenceReference(page_number=cell.page_number, bbox=cell.bbox, raw_text=cell.text)
        for cell in cells
    )
    return tuple(dict.fromkeys(references))


def _positioned_cell_text(cell: Cell) -> str:
    if cell.glyphs:
        lines: list[list[Glyph]] = []
        for glyph in sorted(
            cell.glyphs,
            key=lambda item: (bbox_center_y(item.bbox), item.bbox[0], item.bbox[2]),
        ):
            line = next(
                (
                    candidate
                    for candidate in lines
                    if abs(bbox_center_y(candidate[0].bbox) - bbox_center_y(glyph.bbox))
                    <= min(
                        bbox_height(candidate[0].bbox),
                        bbox_height(glyph.bbox),
                    )
                    * 0.5
                ),
                None,
            )
            if line is None:
                lines.append([glyph])
            else:
                line.append(glyph)
        return " ".join(
            "".join(glyph.char for glyph in sorted(line, key=lambda item: item.bbox[0]))
            for line in lines
        )
    return " ".join(word.text for word in cell.words)


def _positioned_cell_source_texts(cell: Cell) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            filter(
                None,
                (
                    logical_text_for_evidence(cell.glyphs, cell.words),
                    _positioned_cell_text(cell),
                ),
            )
        )
    )


def _has_compatible_positioned_money_context(cell: Cell) -> bool:
    source_texts = _positioned_cell_source_texts(cell)
    return not source_texts or any(
        _has_only_recognized_money_context(source_text) for source_text in source_texts
    )


def _cell_source_texts(cell: Cell) -> tuple[str, ...]:
    return tuple(dict.fromkeys(filter(None, (cell.text, *_positioned_cell_source_texts(cell)))))


def _all_cell_source_text(cell: Cell) -> str:
    return " ".join(_cell_source_texts(cell))


def _is_fully_owned_date_only_source(
    cell: Cell,
    ledger: EvidenceLedger,
    excluded_atom_ids: frozenset[int],
) -> bool:
    cell_atom_ids = ledger.atoms_for_cell(cell)
    date_atom_ids = ledger.fragmented_date_atom_ids(cell_atom_ids)
    if not date_atom_ids or not date_atom_ids <= excluded_atom_ids:
        return False
    remaining_ids = cell_atom_ids - excluded_atom_ids
    if any(any(char.isdigit() for char in ledger.atoms[atom_id].text) for atom_id in remaining_ids):
        return False
    source_text = _all_cell_source_text(cell)
    if _contains_cue(source_text, (*_RATE_HEADER_CUES, *_FEE_HEADER_CUES)):
        return False
    return all(
        token.isdigit() or token in _DATE_ONLY_SOURCE_TOKENS
        for token in phrase_tokens(cell.text, ignore_acronym_quotes=True)
    )


def _row_text(row: Row) -> str:
    return " ".join(cell.text for cell in row.cells)


_TRAILING_DECIMAL_FRAGMENT_PATTERN = re.compile(r"\d+(?:[.,]\d*)?$")
_LEADING_DECIMAL_FRAGMENT_PATTERN = re.compile(r"(?:\d*[.,])?\d+")
_COMPLETE_DECIMAL_PATTERN = re.compile(r"\d+[.,]\d{1,6}")


def _has_joined_decimal_boundary(
    left_cell: Cell,
    left_source: str,
    right_cell: Cell,
    right_source: str,
) -> bool:
    if (
        left_cell.page_number != right_cell.page_number
        or abs(bbox_center_y(left_cell.bbox) - bbox_center_y(right_cell.bbox))
        > min(bbox_height(left_cell.bbox), bbox_height(right_cell.bbox)) * 0.5
        or right_cell.bbox[0] - left_cell.bbox[2]
        > min(bbox_height(left_cell.bbox), bbox_height(right_cell.bbox)) * 0.6
    ):
        return False
    left_match = _TRAILING_DECIMAL_FRAGMENT_PATTERN.search(left_source.rstrip())
    right_match = _LEADING_DECIMAL_FRAGMENT_PATTERN.match(right_source.lstrip())
    return (
        left_match is not None
        and right_match is not None
        and _COMPLETE_DECIMAL_PATTERN.fullmatch(f"{left_match.group()}{right_match.group()}")
        is not None
    )


def _join_row_sources(row: Row, sources: Sequence[str]) -> str:
    if not sources:
        return ""
    joined = sources[0]
    for left_cell, left_source, right_cell, right_source in zip(
        row.cells[:-1],
        sources[:-1],
        row.cells[1:],
        sources[1:],
        strict=True,
    ):
        separator = (
            ""
            if _has_joined_decimal_boundary(
                left_cell,
                left_source,
                right_cell,
                right_source,
            )
            else " "
        )
        joined = f"{joined}{separator}{right_source}"
    return joined


def _row_source_texts(row: Row) -> tuple[str, ...]:
    positioned_sources = tuple(_positioned_cell_source_texts(cell) for cell in row.cells)
    rendering_count = max((len(sources) for sources in positioned_sources), default=0)
    renderings = [_join_row_sources(row, tuple(cell.text for cell in row.cells))]
    for index in range(rendering_count):
        renderings.append(
            _join_row_sources(
                row,
                tuple(
                    sources[min(index, len(sources) - 1)] if sources else cell.text
                    for cell, sources in zip(row.cells, positioned_sources, strict=True)
                ),
            )
        )
    return tuple(dict.fromkeys(filter(None, renderings)))


def _row_evidence(row: Row) -> tuple[EvidenceReference, ...]:
    return _field_evidence(row.cells)


def _row_atom_ids(row: Row, ledger: EvidenceLedger) -> frozenset[int]:
    return frozenset(atom_id for cell in row.cells for atom_id in ledger.atoms_for_cell(cell))


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", "."))
    except InvalidOperation:
        return None


_TEXT_MONEY_NUMBER_PATTERN = re.compile(
    r"(?<![\d.,])(?:[+-]\s*)?(?:\d{1,3}(?:[ ,'\N{RIGHT SINGLE QUOTATION MARK}]\d{3})+|\d+)"
    r"(?:[.,]\d+)?(?![\d.,])"
)


def _is_percent_bound_rendered_number(text: str, match: re.Match[str]) -> bool:
    left = text[: match.start()].rstrip()
    right = text[match.end() :].lstrip()
    return left.endswith("%") or right.startswith("%")


def _rendered_decimal_values(
    text: str,
    *,
    percent_bound: bool,
) -> tuple[Decimal, ...] | None:
    values: list[Decimal] = []
    for match in _TEXT_MONEY_NUMBER_PATTERN.finditer(text):
        if _is_percent_bound_rendered_number(text, match) is not percent_bound:
            continue
        normalized = (
            match.group()
            .replace(" ", "")
            .replace("'", "")
            .replace("\N{RIGHT SINGLE QUOTATION MARK}", "")
        )
        value = _decimal(normalized)
        if value is None:
            return None
        values.append(value)
    return tuple(sorted(values))


def _decimal_renderings_match(
    source_texts: Sequence[str],
    expected_value: Decimal,
    *,
    percent_bound: bool,
) -> bool:
    renderings = tuple(
        _rendered_decimal_values(source_text, percent_bound=percent_bound)
        for source_text in source_texts
    )
    if any(rendering is None for rendering in renderings):
        return False
    proven = tuple(rendering for rendering in renderings if rendering)
    return (
        bool(proven)
        and all(rendering == proven[0] for rendering in proven[1:])
        and (expected_value in proven[0])
    )


def _rendered_money_values(
    text: str,
    expected_currency: str,
) -> tuple[tuple[Decimal, ...], str] | None:
    currency = canonical_currency(expected_currency)
    if currency is None or contains_credit_marker(text):
        return None
    currencies = currencies_in_text(text)
    if len(currencies) > 1 or (currencies and currencies[0] != currency):
        return None
    amounts: list[Decimal] = []
    for match in _TEXT_MONEY_NUMBER_PATTERN.finditer(text):
        if _is_percent_bound_rendered_number(text, match):
            continue
        parsed = parse_amount(match.group(), currency_hint=currency)
        if parsed.amount is None or parsed.amount < 0 or parsed.diagnostics:
            return None
        amounts.append(parsed.amount)
    if not amounts:
        return None
    return tuple(amounts), currency


def _money_renderings_match(
    source_texts: Sequence[str],
    expected_amount: Decimal,
    expected_currency: str,
) -> bool:
    numeric_sources = tuple(
        source_text for source_text in source_texts if any(char.isdigit() for char in source_text)
    )
    renderings = tuple(
        _rendered_money_values(source_text, expected_currency) for source_text in numeric_sources
    )
    if not renderings or any(rendering is None for rendering in renderings):
        return False
    proven = tuple(rendering for rendering in renderings if rendering is not None)
    return all(rendering == proven[0] for rendering in proven[1:]) and (
        expected_amount in proven[0][0] and proven[0][1] == canonical_currency(expected_currency)
    )


def _one_positive_decimal(
    atom_ids: Iterable[int], ledger: EvidenceLedger
) -> tuple[Decimal, frozenset[int]] | None:
    return _one_decimal(atom_ids, ledger, allow_zero=False, reject_typed_wrappers=True)


_SIGNED_OR_ACCOUNTING_WRAPPERS = frozenset("+-()\N{MINUS SIGN}\N{EN DASH}\N{EM DASH}")
_TYPED_NUMERIC_WRAPPERS = _SIGNED_OR_ACCOUNTING_WRAPPERS | frozenset("%")


def _has_typed_numeric_wrapper(
    candidate: PositionedNumberCandidate,
    selected_ids: frozenset[int],
    ledger: EvidenceLedger,
    *,
    wrappers: frozenset[str] = _TYPED_NUMERIC_WRAPPERS,
) -> bool:
    candidate_atoms = tuple(ledger.atoms[atom_id] for atom_id in candidate.atom_ids)
    if any(char in wrappers for atom in candidate_atoms for char in atom.text):
        return True
    candidate_bbox = union_bbox(atom.bbox for atom in candidate_atoms)
    page_number = candidate_atoms[0].page_number
    same_line_atoms = tuple(
        atom
        for atom in ledger.atoms
        if atom.atom_id in selected_ids
        and atom.atom_id not in candidate.atom_ids
        and atom.page_number == page_number
        and abs(bbox_center_y(atom.bbox) - bbox_center_y(candidate_bbox))
        <= min(bbox_height(atom.bbox), bbox_height(candidate_bbox)) * 0.5
    )
    candidate_center_x = (candidate_bbox[0] + candidate_bbox[2]) / 2
    for atom in same_line_atoms:
        if not any(char in wrappers for char in atom.text):
            continue
        atom_center_x = (atom.bbox[0] + atom.bbox[2]) / 2
        intervening = tuple(
            other
            for other in same_line_atoms
            if other.atom_id != atom.atom_id
            and min(atom_center_x, candidate_center_x)
            < (other.bbox[0] + other.bbox[2]) / 2
            < max(atom_center_x, candidate_center_x)
        )
        chain = tuple(
            sorted(
                (atom.bbox, *(item.bbox for item in intervening), candidate_bbox),
                key=lambda bbox: (bbox[0] + bbox[2]) / 2,
            )
        )
        if any(
            right[0] - left[2] > min(bbox_height(left), bbox_height(right)) * 0.6
            for left, right in pairwise(chain)
        ):
            continue
        if not intervening:
            return True
        if not any(char in _SIGNED_OR_ACCOUNTING_WRAPPERS for char in atom.text):
            continue
        semantic_intervening = tuple(
            item for item in intervening if not item.text or set(item.text) != {"%"}
        )
        if not semantic_intervening:
            return True
        ordered_text = tuple(
            item.text for item in sorted(semantic_intervening, key=lambda item: item.bbox[0])
        )
        compact_text = "".join(ordered_text)
        currency_code_parts = tuple(re.findall(r"[^\W\d_]+", compact_text))
        unsupported_currency_shape = (
            all(
                char.isalpha() or unicodedata.category(char) in {"Cf", "Sc"} or char in "/"
                for char in compact_text
            )
            and (
                any(unicodedata.category(char) == "Sc" for char in compact_text)
                or (
                    bool(currency_code_parts)
                    and all(len(part) >= 3 and len(part) % 3 == 0 for part in currency_code_parts)
                )
            )
            and not _is_recognized_context_token(compact_text.casefold())
        )
        if (
            any(
                canonical_currency(currency_text) is not None
                for currency_text in ("".join(ordered_text), " ".join(ordered_text))
            )
            or unsupported_currency_shape
        ):
            return True
    return False


def _one_decimal(
    atom_ids: Iterable[int],
    ledger: EvidenceLedger,
    *,
    allow_zero: bool,
    reject_typed_wrappers: bool = False,
    reject_three_fraction_digits: bool = False,
) -> tuple[Decimal, frozenset[int]] | None:
    selected_ids = frozenset(atom_ids)
    candidates = ledger.positioned_decimal_candidates(selected_ids)
    if len(candidates) != 1:
        return None
    candidate = candidates[0]
    candidate_atom_ids = frozenset(
        atom_id for candidate in candidates for atom_id in candidate.atom_ids
    )
    date_atom_ids = ledger.fragmented_date_atom_ids(selected_ids)
    candidate_atoms = tuple(ledger.atoms[atom_id] for atom_id in candidate.atom_ids)
    candidate_bbox = union_bbox(atom.bbox for atom in candidate_atoms)

    def is_currency_separated_annotation(atom: EvidenceAtom) -> bool:
        if (
            atom.page_number != candidate_atoms[0].page_number
            or abs(bbox_center_y(atom.bbox) - bbox_center_y(candidate_bbox))
            > min(bbox_height(atom.bbox), bbox_height(candidate_bbox)) * 0.5
        ):
            return False
        atom_center_x = (atom.bbox[0] + atom.bbox[2]) / 2
        candidate_center_x = (candidate_bbox[0] + candidate_bbox[2]) / 2
        if atom_center_x >= candidate_center_x:
            return False
        intervening = tuple(
            item
            for item in sorted(ledger.atoms, key=lambda item: item.bbox[0])
            if item.atom_id in selected_ids - candidate_atom_ids - {atom.atom_id}
            and item.page_number == atom.page_number
            and atom_center_x < (item.bbox[0] + item.bbox[2]) / 2 < candidate_center_x
        )
        if (
            not intervening
            or intervening[0].bbox[0] - atom.bbox[2]
            > min(bbox_height(atom.bbox), bbox_height(intervening[0].bbox)) * 0.05
        ):
            return False
        intervening_text = tuple(item.text for item in intervening)
        return any(
            canonical_currency(text) is not None
            for text in ("".join(intervening_text), " ".join(intervening_text))
        )

    has_unbound_integer = any(
        atom.atom_id in selected_ids - candidate_atom_ids - date_atom_ids
        and any(char.isdigit() for char in atom.text)
        and not is_currency_separated_annotation(atom)
        for atom in ledger.atoms
    )
    if has_unbound_integer:
        return None
    if reject_typed_wrappers and _has_typed_numeric_wrapper(
        candidate,
        selected_ids,
        ledger,
    ):
        return None
    if (
        reject_three_fraction_digits
        and len(candidate.text.replace(",", ".").split(".", maxsplit=1)[1]) == 3
    ):
        return None
    value = _decimal(candidate.text)
    if value is None or not (value >= 0 if allow_zero else value > 0):
        return None
    return value, candidate.atom_ids


def _percent_bound_decimal_candidates(
    atom_ids: Iterable[int],
    ledger: EvidenceLedger,
) -> tuple[tuple[PositionedNumberCandidate, int], ...]:
    return tuple(
        (candidate.number, candidate.marker_count)
        for candidate in ledger.positioned_percentage_candidates(atom_ids)
    )


def _one_percent_bound_decimal(
    atom_ids: Iterable[int],
    ledger: EvidenceLedger,
) -> tuple[Decimal, PositionedPercentageCandidate] | None:
    selected_ids = frozenset(atom_ids)
    candidates = ledger.positioned_percentage_candidates(selected_ids)
    if len(candidates) != 1:
        return None
    candidate = candidates[0]
    if candidate.marker_count != 1 or _has_typed_numeric_wrapper(
        candidate.number,
        selected_ids,
        ledger,
        wrappers=_SIGNED_OR_ACCOUNTING_WRAPPERS,
    ):
        return None
    value = _decimal(candidate.text)
    return (value, candidate) if value is not None and value >= 0 else None


def _one_non_percentage_money_decimal(
    atom_ids: Iterable[int],
    ledger: EvidenceLedger,
) -> tuple[Decimal, frozenset[int]] | None:
    selected_ids = frozenset(atom_ids)
    percent_bound_atom_ids = _percent_bound_numeric_atom_ids(selected_ids, ledger)
    return _one_decimal(
        selected_ids - percent_bound_atom_ids,
        ledger,
        allow_zero=True,
        reject_typed_wrappers=True,
        reject_three_fraction_digits=True,
    )


def _percent_bound_numeric_atom_ids(
    atom_ids: Iterable[int],
    ledger: EvidenceLedger,
) -> frozenset[int]:
    return frozenset(
        atom_id
        for candidate in ledger.positioned_percentage_candidates(atom_ids)
        for atom_id in candidate.numeric_atom_ids
    )


def _non_percentage_numeric_atom_ids(
    atom_ids: Iterable[int],
    ledger: EvidenceLedger,
) -> frozenset[int]:
    selected_ids = frozenset(atom_ids)
    percent_bound_atom_ids = _percent_bound_numeric_atom_ids(selected_ids, ledger)
    remaining_ids = selected_ids - percent_bound_atom_ids
    candidate_atom_ids = frozenset(
        atom_id
        for candidate in ledger.positioned_decimal_candidates(remaining_ids)
        for atom_id in candidate.atom_ids
    )
    scalar_atom_ids = frozenset(
        atom.atom_id
        for atom in ledger.atoms
        if atom.atom_id in remaining_ids
        if (
            ((atom.glyph is not None or atom.word is not None) and atom.text.isdigit())
            or (
                atom.word is not None
                and "%" not in atom.text
                and parse_amount(atom.text).amount is not None
            )
        )
    )
    return candidate_atom_ids | scalar_atom_ids


def _has_non_percentage_numeric_evidence(
    atom_ids: Iterable[int],
    ledger: EvidenceLedger,
) -> bool:
    return bool(_non_percentage_numeric_atom_ids(atom_ids, ledger))


def _one_word_money(
    atom_ids: Iterable[int],
    ledger: EvidenceLedger,
    expected_currency: str,
) -> tuple[Decimal, str, frozenset[int]] | None:
    selected_ids = frozenset(atom_ids)
    currency = canonical_currency(expected_currency)
    if currency is None:
        return None
    date_atom_ids = ledger.fragmented_date_atom_ids(selected_ids)
    numeric_atoms = tuple(
        atom
        for atom in ledger.atoms
        if atom.atom_id in selected_ids
        and atom.word is not None
        and atom.atom_id not in date_atom_ids
        and any(char.isdigit() for char in atom.text)
    )
    if len(numeric_atoms) != 1:
        return None
    atom = numeric_atoms[0]
    candidate = PositionedDecimalCandidate(
        text=atom.text,
        atom_ids=frozenset((atom.atom_id,)),
    )
    if _has_typed_numeric_wrapper(candidate, selected_ids, ledger):
        return None
    parsed = parse_amount(atom.text, currency_hint=expected_currency)
    if (
        parsed.amount is None
        or parsed.amount < 0
        or parsed.currency != currency
        or parsed.diagnostics
    ):
        return None
    return parsed.amount, currency, candidate.atom_ids


def _has_lossless_indivisible_ocr_currency_word(
    cell: Cell,
    ledger: EvidenceLedger,
    atom_ids: frozenset[int],
    expected_amount: Decimal,
    expected_currency: str,
) -> bool:
    """Recognize one RTL OCR Word whose currency symbol splits a thousands group."""

    cell_atom_ids = ledger.atoms_for_cell(cell)
    if atom_ids != cell_atom_ids or len(cell_atom_ids) != 1 or len(cell.words) != 1 or cell.glyphs:
        return False
    atom = ledger.atoms[next(iter(cell_atom_ids))]
    word = cell.words[0]
    currency = canonical_currency(expected_currency)
    source_texts = _cell_source_texts(cell)
    if (
        atom.word is None
        or atom.word.source != "ocr"
        or word.source != "ocr"
        or min(atom.confidence, word.confidence, cell.confidence) < 0.8
        or currency is None
        or len(source_texts) != 1
        or normalize_text(source_texts[0]) != normalize_text(word.text)
        or normalize_text(cell.text) != normalize_text(word.text)
    ):
        return False
    significant = tuple(
        char
        for char in normalize_text(word.text)
        if not char.isspace() and unicodedata.category(char) != "Cf"
    )
    marker_indexes = tuple(index for index, char in enumerate(significant) if not char.isdigit())
    if len(marker_indexes) != 1 or currencies_in_text(word.text) != (currency,):
        return False
    currency_index = marker_indexes[0]
    marker = significant[currency_index]
    if not (
        (unicodedata.category(marker) == "Sc" and canonical_currency(marker) == currency)
        or (marker == "{" and currency == "ILS")
    ):
        return False
    leading = "".join(significant[:currency_index])
    trailing = "".join(significant[currency_index + 1 :])
    parsed = parse_amount(word.text, currency_hint=currency)
    return (
        1 <= len(leading) <= 3
        and len(trailing) == 3
        and leading.isdigit()
        and trailing.isdigit()
        and parsed.amount == expected_amount
        and parsed.currency == currency
        and not parsed.diagnostics
    )


def _indivisible_ocr_currency_word(
    cell: Cell,
    ledger: EvidenceLedger,
    expected_currency: str,
) -> tuple[Decimal, str, frozenset[int], int, bool] | None:
    cell_atom_ids = ledger.atoms_for_cell(cell)
    currency = canonical_currency(expected_currency)
    if currency is None or len(cell_atom_ids) != 1 or len(cell.words) != 1 or cell.glyphs:
        return None
    atom = ledger.atoms[next(iter(cell_atom_ids))]
    word = cell.words[0]
    source_texts = _cell_source_texts(cell)
    if (
        atom.word is None
        or atom.word.source != "ocr"
        or word.source != "ocr"
        or min(atom.confidence, word.confidence, cell.confidence) < 0.5
        or len(source_texts) != 1
        or normalize_text(source_texts[0]) != normalize_text(word.text)
        or normalize_text(cell.text) != normalize_text(word.text)
    ):
        return None
    significant = tuple(
        char
        for char in normalize_text(word.text)
        if not char.isspace() and unicodedata.category(char) != "Cf"
    )
    markers = tuple(char for char in significant if not char.isdigit())
    source_currencies = currencies_in_text(word.text)
    has_explicit_currency = source_currencies == (currency,)
    has_decimal_separator = not source_currencies and len(markers) == 1 and markers[0] in ".,"
    has_currency_marker = (
        len(markers) == 1
        and has_explicit_currency
        and (
            (
                unicodedata.category(markers[0]) == "Sc"
                and canonical_currency(markers[0]) == currency
            )
            or (markers[0] == "{" and currency == "ILS")
        )
    )
    if source_currencies not in {(), (currency,)} or not (
        has_decimal_separator or has_currency_marker
    ):
        return None
    parsed = parse_amount(word.text, currency_hint=currency)
    if (
        parsed.amount is None
        or parsed.amount < 0
        or parsed.currency != currency
        or parsed.diagnostics
    ):
        return None
    return (
        parsed.amount,
        currency,
        cell_atom_ids,
        sum(char.isdigit() for char in significant),
        has_explicit_currency,
    )


def _repeated_indivisible_ocr_currency_fee(
    column: ColumnSpec,
    region: TableRegion,
    cell: Cell,
    ledger: EvidenceLedger,
    expected_currency: str,
) -> tuple[Decimal, str, frozenset[int]] | None:
    resolved: list[tuple[Cell, Decimal, str, frozenset[int], int, bool, bool]] = []
    for row in region.rows:
        column_cells = cells_in_column(row.cells, column)
        if len(column_cells) > 1:
            return None
        for candidate_cell in column_cells:
            candidate_ledger = (
                ledger if candidate_cell is cell else EvidenceLedger.from_rows((row,))
            )
            candidate = _indivisible_ocr_currency_word(
                candidate_cell,
                candidate_ledger,
                expected_currency,
            )
            if candidate is None:
                return None
            amount, currency, atom_ids, digit_count, has_explicit_currency = candidate
            rendered = _money_renderings_match(
                _cell_source_texts(candidate_cell),
                amount,
                currency,
            )
            resolved.append(
                (
                    candidate_cell,
                    amount,
                    currency,
                    atom_ids,
                    digit_count,
                    rendered,
                    has_explicit_currency,
                )
            )
    if (
        len(resolved) < 2
        or len({amount for _, amount, _, _, _, _, _ in resolved}) < 2
        or len({currency for _, _, currency, _, _, _, _ in resolved}) != 1
        or len({digit_count for _, _, _, _, digit_count, _, _ in resolved}) != 1
        or not any(rendered for _, _, _, _, _, rendered, _ in resolved)
        or not any(explicit for _, _, _, _, _, _, explicit in resolved)
    ):
        return None
    current = tuple(item for item in resolved if item[0] is cell)
    if len(current) != 1:
        return None
    _, amount, currency, atom_ids, _, _, _ = current[0]
    return amount, currency, atom_ids


def _one_money(
    cell: Cell,
    ledger: EvidenceLedger,
    expected_currency: str,
) -> tuple[Decimal, str, frozenset[int]] | None:
    evidence_text = _all_cell_source_text(cell)
    if (
        contains_credit_marker(evidence_text)
        or not _has_only_recognized_money_context(cell.text)
        or not _has_compatible_positioned_money_context(cell)
    ):
        return None
    currencies = currencies_in_text(evidence_text)
    if len(currencies) != 1 or currencies[0] != canonical_currency(expected_currency):
        return None
    parsed_money: tuple[Decimal, str, frozenset[int]] | None
    parsed = _one_non_percentage_money_decimal(ledger.atoms_for_cell(cell), ledger)
    if parsed is not None:
        amount, atom_ids = parsed
        parsed_money = (amount, currencies[0], atom_ids)
    else:
        parsed_money = _one_word_money(ledger.atoms_for_cell(cell), ledger, expected_currency)
    if parsed_money is None:
        return None
    amount, currency, atom_ids = parsed_money
    return (
        parsed_money
        if _money_renderings_match(_cell_source_texts(cell), amount, currency)
        or _has_lossless_indivisible_ocr_currency_word(
            cell,
            ledger,
            atom_ids,
            amount,
            currency,
        )
        else None
    )


def _ordered_compact_text(text: str) -> str:
    return "".join(normalize_text(text).split())


def _bound_currency_annotation_fee(
    cell: Cell,
    ledger: EvidenceLedger,
    expected_currency: str,
) -> tuple[str, Decimal, str, frozenset[int]] | None:
    cell_atom_ids = ledger.atoms_for_cell(cell)
    candidates = ledger.positioned_decimal_candidates(cell_atom_ids)
    currency = canonical_currency(expected_currency)
    if len(candidates) != 1 or currency is None:
        return None
    candidate = candidates[0]
    normalized_candidate = candidate.text.replace(",", ".")
    if "." not in normalized_candidate or len(normalized_candidate.rsplit(".", 1)[1]) != 2:
        return None
    value = _decimal(candidate.text)
    if (
        value is None
        or value < 0
        or _has_typed_numeric_wrapper(candidate, cell_atom_ids, ledger)
        or _percent_bound_numeric_atom_ids(cell_atom_ids, ledger)
    ):
        return None
    residual_atoms = tuple(
        atom for atom in ledger.atoms if atom.atom_id in cell_atom_ids - candidate.atom_ids
    )
    annotations = tuple(
        atom for atom in residual_atoms if atom.text.isdigit() and atom.glyph is not None
    )
    currency_atoms = tuple(
        atom for atom in residual_atoms if canonical_currency(atom.text) == currency
    )
    if len(annotations) != 1 or len(currency_atoms) != 1:
        return None
    annotation = annotations[0]
    currency_atom = currency_atoms[0]
    if any(
        any(char.isdigit() for char in atom.text)
        for atom in residual_atoms
        if atom not in annotations
    ):
        return None
    candidate_atoms = tuple(ledger.atoms[atom_id] for atom_id in candidate.atom_ids)
    candidate_bbox = union_bbox(atom.bbox for atom in candidate_atoms)
    annotation_center = (annotation.bbox[0] + annotation.bbox[2]) / 2
    currency_center = (currency_atom.bbox[0] + currency_atom.bbox[2]) / 2
    candidate_center = (candidate_bbox[0] + candidate_bbox[2]) / 2
    if not annotation_center < currency_center < candidate_center:
        return None
    expected_text = normalize_text(f"{annotation.text}{currency_atom.text} {candidate.text}")
    source_texts = _cell_source_texts(cell)
    if (
        _ordered_compact_text(cell.text) != _ordered_compact_text(expected_text)
        or not source_texts
        or any(
            _ordered_compact_text(source) != _ordered_compact_text(expected_text)
            for source in source_texts
        )
        or not _money_renderings_match(source_texts, value, currency)
    ):
        return None
    return annotation.text, value, currency, candidate.atom_ids


def _repeated_bound_currency_annotation_fee(
    column: ColumnSpec,
    region: TableRegion,
    cell: Cell,
    ledger: EvidenceLedger,
    billing_currency: str,
) -> tuple[Decimal, str, frozenset[int]] | None:
    resolved: list[tuple[Cell, str, Decimal, str, frozenset[int]]] = []
    for row in region.rows:
        column_cells = cells_in_column(row.cells, column)
        if len(column_cells) > 1:
            return None
        for candidate_cell in column_cells:
            candidate_ledger = (
                ledger if candidate_cell is cell else EvidenceLedger.from_rows((row,))
            )
            candidate = _bound_currency_annotation_fee(
                candidate_cell,
                candidate_ledger,
                billing_currency,
            )
            if candidate is None:
                return None
            annotation, amount, currency, atom_ids = candidate
            resolved.append((candidate_cell, annotation, amount, currency, atom_ids))
    if (
        len(resolved) < 2
        or len({annotation for _, annotation, _, _, _ in resolved}) != 1
        or len({amount for _, _, amount, _, _ in resolved}) < 2
        or len({currency for _, _, _, currency, _ in resolved}) != 1
    ):
        return None
    current = tuple(item for item in resolved if item[0] is cell)
    if len(current) != 1:
        return None
    _, _, amount, currency, atom_ids = current[0]
    return amount, currency, atom_ids


def _one_table_fee(
    column: ColumnSpec,
    header_cells: Sequence[Cell],
    cell: Cell,
    ledger: EvidenceLedger,
    billing_currency: str,
    region: TableRegion,
) -> tuple[Decimal, str, frozenset[int]] | None:
    source_texts = _cell_source_texts(cell)
    source_text = " ".join(source_texts)
    source_has_conflicting_semantics = any(
        _has_conflicting_net_fee_semantics(source) for source in source_texts
    )
    header_phrase = _header_phrase(column, header_cells)
    header_currencies = currencies_in_text(header_phrase)
    header_has_conflicting_semantics = _has_conflicting_net_fee_semantics(header_phrase)
    currency = canonical_currency(billing_currency)
    if (
        contains_credit_marker(source_text)
        or source_has_conflicting_semantics
        or header_has_conflicting_semantics
        or any(char.isdigit() for char in header_phrase)
        or _has_unsupported_header_currency(header_phrase)
        or any(candidate != currency for candidate in header_currencies)
    ):
        return None
    if parsed_money := _one_money(cell, ledger, billing_currency):
        return parsed_money
    if repeated_word := _repeated_indivisible_ocr_currency_fee(
        column,
        region,
        cell,
        ledger,
        billing_currency,
    ):
        return repeated_word
    if repeated_annotation := _repeated_bound_currency_annotation_fee(
        column,
        region,
        cell,
        ledger,
        billing_currency,
    ):
        return repeated_annotation
    if currencies_in_text(cell.text):
        return None
    evidence_text = _all_cell_source_text(cell)
    has_only_numeric_syntax = all(
        char.isdigit()
        or char.isspace()
        or char in _CURRENCYLESS_MONEY_WRAPPERS
        or unicodedata.category(char) == "Cf"
        for char in evidence_text
    )
    if currency is None or not has_only_numeric_syntax:
        return None
    parsed = _one_non_percentage_money_decimal(ledger.atoms_for_cell(cell), ledger)
    if parsed is None:
        return None
    amount, atom_ids = parsed
    return (
        (amount, currency, atom_ids)
        if _money_renderings_match(_cell_source_texts(cell), amount, currency)
        else None
    )


def _one_row_money(
    row: Row,
    ledger: EvidenceLedger,
    expected_currency: str,
) -> tuple[Decimal, str, frozenset[int]] | None:
    atom_ids = _row_atom_ids(row, ledger)
    raw_text = " ".join(_all_cell_source_text(cell) for cell in row.cells)
    if (
        contains_credit_marker(raw_text)
        or not _has_only_recognized_money_context(_row_text(row))
        or any(not _has_compatible_positioned_money_context(cell) for cell in row.cells)
    ):
        return None
    currencies = currencies_in_text(raw_text)
    if len(currencies) != 1 or currencies[0] != canonical_currency(expected_currency):
        return None
    parsed_money: tuple[Decimal, str, frozenset[int]] | None
    parsed = _one_non_percentage_money_decimal(atom_ids, ledger)
    if parsed is not None:
        amount, atom_ids = parsed
        parsed_money = (amount, currencies[0], atom_ids)
    else:
        parsed_money = _one_word_money(atom_ids, ledger, expected_currency)
    if parsed_money is None:
        return None
    amount, currency, _ = parsed_money
    return (
        parsed_money if _money_renderings_match(_row_source_texts(row), amount, currency) else None
    )


def _table_fx_values(
    row: Row,
    region: TableRegion,
    ledger: EvidenceLedger,
    original_currency: str,
    billing_currency: str,
    excluded_atom_ids: frozenset[int],
) -> _FxValues:
    claims: list[EvidenceClaim] = []
    diagnostics: list[str] = []
    ambiguous_owners: set[SemanticOwner] = set()
    exchange_rate: ExtractedDecimal | None = None
    net_fee: ExtractedMoney | None = None

    header_cells = region.table_schema.header_cells
    rate_columns = tuple(
        column for column in region.table_schema.columns if _is_rate_column(column, header_cells)
    )
    rate_sources = tuple(
        (column, cell)
        for column in rate_columns
        for cell in cells_in_column(row.cells, column)
        if not _is_fully_owned_date_only_source(cell, ledger, excluded_atom_ids)
    )
    if rate_sources:
        parsed_rate_cells = tuple(
            (parsed_rate, column, cell)
            for column, cell in rate_sources
            for parsed_rate in (
                (
                    None
                    if any(
                        _contains_cue(
                            source,
                            (*_FEE_HEADER_CUES, *_GROSS_FEE_CUES, *_DISCOUNT_CUES),
                        )
                        for source in _cell_source_texts(cell)
                    )
                    or not _has_valid_typed_decimal_context(
                        _cell_source_texts(cell),
                        original_currency,
                        billing_currency,
                    )
                    else _one_positive_decimal(
                        ledger.atoms_for_cell(cell) - excluded_atom_ids,
                        ledger,
                    )
                ),
            )
        )
        parsed_rate_cells = tuple(
            (
                parsed_rate
                if parsed_rate is not None
                and (
                    _decimal_renderings_match(
                        _cell_source_texts(cell),
                        parsed_rate[0],
                        percent_bound=False,
                    )
                    or parsed_rate[1]
                    == proven_conversion_rate_residual_atom_ids(
                        ledger,
                        cell,
                        column,
                        region,
                        excluded_atom_ids,
                    )
                )
                else None,
                column,
                cell,
            )
            for parsed_rate, column, cell in parsed_rate_cells
        )
        parsed_rates = tuple(
            parsed_rate for parsed_rate, _, _ in parsed_rate_cells if parsed_rate is not None
        )
        rate_values = {value for value, _ in parsed_rates}
        if len(parsed_rates) == len(rate_sources) and len(rate_values) == 1:
            value = next(iter(rate_values))
            atom_ids = frozenset(
                atom_id for _, candidate_ids in parsed_rates for atom_id in candidate_ids
            )
            exchange_rate = ExtractedDecimal(
                value=value,
                evidence=_field_evidence(cell for _, cell in rate_sources),
            )
            claims.append(EvidenceClaim(SemanticOwner.EXCHANGE_RATE, atom_ids))
        else:
            diagnostics.append("unparsed_exchange_rate_candidate")
            ambiguous_owners.add(SemanticOwner.EXCHANGE_RATE)

    fee_columns = tuple(
        column for column in region.table_schema.columns if _is_fee_column(column, header_cells)
    )
    fee_cells = tuple(
        (column, cell) for column in fee_columns for cell in cells_in_column(row.cells, column)
    )
    if fee_cells:
        parsed_fee_cells = tuple(
            (parsed_money, cell)
            for column, cell in fee_cells
            for parsed_money in (
                _one_table_fee(
                    column,
                    header_cells,
                    cell,
                    ledger,
                    billing_currency,
                    region,
                ),
            )
        )
        parsed_fees = tuple(
            parsed_money for parsed_money, _ in parsed_fee_cells if parsed_money is not None
        )
        fee_values = {(amount, currency) for amount, currency, _ in parsed_fees}
        if len(parsed_fees) == len(fee_cells) and len(fee_values) == 1:
            amount, currency = next(iter(fee_values))
            atom_ids = frozenset(
                atom_id for _, _, candidate_ids in parsed_fees for atom_id in candidate_ids
            )
            net_fee = ExtractedMoney(
                amount=amount,
                currency=currency,
                evidence=_field_evidence(cell for _, cell in fee_cells),
            )
            claims.append(EvidenceClaim(SemanticOwner.NET_FX_FEE, atom_ids))
        else:
            diagnostics.append("unparsed_foreign_currency_fee_candidate")
            ambiguous_owners.add(SemanticOwner.NET_FX_FEE)

    return _FxValues(
        exchange_rate=exchange_rate,
        net_fee=net_fee,
        claims=tuple(claims),
        diagnostics=tuple(dict.fromkeys(diagnostics)),
        ambiguous_owners=frozenset(ambiguous_owners),
    )


def _has_exact_digital_positioned_backing(
    atom_ids: frozenset[int],
    ledger: EvidenceLedger,
) -> bool:
    atoms = tuple(ledger.atoms[atom_id] for atom_id in atom_ids)
    return bool(atoms) and all(
        atom.glyph is not None and atom.glyph.source == "digital" and atom.confidence == 1.0
        for atom in atoms
    )


def _positioned_row_money(
    row: Row,
    ledger: EvidenceLedger,
    billing_currency: str,
) -> tuple[Decimal, str, frozenset[int]] | None:
    currency = canonical_currency(billing_currency)
    source_texts = _row_source_texts(row)
    currencies = frozenset(currencies_in_text(" ".join(source_texts)))
    parsed = _one_non_percentage_money_decimal(_row_atom_ids(row, ledger), ledger)
    if (
        currency is None
        or currencies != {currency}
        or parsed is None
        or not _has_exact_digital_positioned_backing(parsed[1], ledger)
    ):
        return None
    return parsed[0], currency, parsed[1]


def _source_character_signature(text: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            char
            for char in normalize_text(text)
            if not char.isspace() and unicodedata.category(char) != "Cf"
        )
    )


def _has_lossless_reordered_row_sources(row: Row) -> bool:
    sources = _row_source_texts(row)
    return len(sources) >= 2 and len({_source_character_signature(text) for text in sources}) == 1


def _projected_band_index(cell: Cell) -> int | None:
    indexes: list[int] = []
    for diagnostic in cell.diagnostics:
        if not diagnostic.startswith("projected_header_band:"):
            continue
        try:
            index = int(diagnostic.removeprefix("projected_header_band:"))
        except ValueError:
            return None
        if index < 0:
            return None
        indexes.append(index)
    return indexes[0] if len(indexes) == 1 else None


def _candidate_cells(
    row: Row,
    ledger: EvidenceLedger,
    atom_ids: frozenset[int],
) -> tuple[Cell, ...]:
    return tuple(cell for cell in row.cells if ledger.atoms_for_cell(cell) & atom_ids)


def _has_partial_digital_word_coverage(
    row: Row,
    ledger: EvidenceLedger,
    atom_ids: frozenset[int],
) -> bool:
    atoms = tuple(ledger.atoms[atom_id] for atom_id in atom_ids)
    words = tuple(
        word
        for cell in row.cells
        for word in cell.words
        if word.source == "digital" and word.confidence == 1.0
    )
    return (
        bool(atoms)
        and bool(words)
        and all(
            atom.glyph is not None
            and atom.glyph.source == "digital"
            and atom.confidence == 1.0
            and any(center_inside(atom.bbox, word.bbox) for word in words)
            for atom in atoms
        )
        and _has_uncontested_full_span_word_renderings(row, ledger, atom_ids)
    )


def _has_exact_component_source_contract(
    row: Row,
    ledger: EvidenceLedger,
    atom_ids: frozenset[int],
    *,
    percentage: bool,
    incompatible_cues: Sequence[str] = (),
) -> bool:
    row_atom_ids = _row_atom_ids(row, ledger)
    percent_bound_atom_ids = _percent_bound_numeric_atom_ids(row_atom_ids, ledger)
    percentage_candidates = ledger.positioned_percentage_candidates(row_atom_ids)
    percentage_marker_atom_ids = frozenset(
        atom.atom_id for atom in ledger.atoms if atom.atom_id in row_atom_ids and "%" in atom.text
    )
    row_numeric_atom_ids = (
        _non_percentage_numeric_atom_ids(
            row_atom_ids,
            ledger,
        )
        | percent_bound_atom_ids
    )
    return (
        _has_lossless_reordered_row_sources(row)
        and _has_exact_digital_positioned_backing(atom_ids, ledger)
        and _has_exact_digital_positioned_backing(row_atom_ids, ledger)
        and row_numeric_atom_ids == atom_ids
        and percent_bound_atom_ids == (atom_ids if percentage else frozenset())
        and (
            len(percentage_candidates) == 1
            and percentage_candidates[0].marker_count == 1
            and percentage_marker_atom_ids <= percentage_candidates[0].marker_atom_ids
            if percentage
            else not percentage_marker_atom_ids
        )
        and not any(_contains_cue(source, incompatible_cues) for source in _row_source_texts(row))
    )


def _has_uncontested_full_span_word_renderings(
    row: Row,
    ledger: EvidenceLedger,
    atom_ids: frozenset[int],
) -> bool:
    candidates = ledger.positioned_decimal_candidates(atom_ids)
    if len(candidates) != 1:
        return False
    expected = _decimal(candidates[0].text)
    if expected is None:
        return False
    atoms = tuple(ledger.atoms[atom_id] for atom_id in atom_ids)
    for word in (word for cell in row.cells for word in cell.words):
        if not all(center_inside(atom.bbox, word.bbox) for atom in atoms):
            continue
        renderings = tuple(
            rendered
            for percent_bound in (False, True)
            if (
                rendered := _rendered_decimal_values(
                    word.text,
                    percent_bound=percent_bound,
                )
            )
        )
        if not renderings or any(rendered != (expected,) for rendered in renderings):
            return False
    return True


def _single_projected_component_band(
    row: Row,
    ledger: EvidenceLedger,
    atom_ids: frozenset[int],
    *,
    percentage: bool = False,
    incompatible_cues: Sequence[str] = (),
) -> int | None:
    cells = _candidate_cells(row, ledger, atom_ids)
    if (
        len(cells) != 1
        or not _has_exact_component_source_contract(
            row,
            ledger,
            atom_ids,
            percentage=percentage,
            incompatible_cues=incompatible_cues,
        )
        or not _has_uncontested_full_span_word_renderings(row, ledger, atom_ids)
    ):
        return None
    return _projected_band_index(cells[0])


def _projected_rate_bands(
    row: Row,
    ledger: EvidenceLedger,
    atom_ids: frozenset[int],
) -> frozenset[int]:
    cells = _candidate_cells(row, ledger, atom_ids)
    if (
        len(cells) != 2
        or not _has_exact_component_source_contract(
            row,
            ledger,
            atom_ids,
            percentage=False,
            incompatible_cues=_RATE_COMPONENT_INCOMPATIBLE_CUES,
        )
        or not _has_partial_digital_word_coverage(row, ledger, atom_ids)
    ):
        return frozenset()
    indexes = tuple(_projected_band_index(cell) for cell in cells)
    if any(index is None for index in indexes):
        return frozenset()
    concrete_indexes = tuple(index for index in indexes if index is not None)
    if len(set(concrete_indexes)) != 2 or abs(concrete_indexes[0] - concrete_indexes[1]) != 1:
        return frozenset()
    component_boxes = tuple(
        union_bbox(ledger.atoms[atom_id].bbox for atom_id in ledger.atoms_for_cell(cell) & atom_ids)
        for cell in cells
    )
    left, right = sorted(component_boxes, key=lambda bbox: bbox[0])
    gap = max(0.0, right[0] - left[2])
    if (
        vertical_overlap(left, right) < 0.8
        or gap > min(bbox_height(left), bbox_height(right)) * 0.6
    ):
        return frozenset()
    return frozenset(concrete_indexes)


def _has_only_alpha_flanked_other_punctuation(text: str) -> bool:
    normalized = normalize_text(text)
    return all(
        unicodedata.category(char) == "Po"
        and index > 0
        and index + 1 < len(normalized)
        and normalized[index - 1].isalpha()
        and normalized[index + 1].isalpha()
        for index, char in enumerate(normalized)
        if not char.isalnum() and not char.isspace() and unicodedata.category(char) != "Cf"
    )


def _is_proven_nonfinancial_identifier_row(row: Row, ledger: EvidenceLedger) -> bool:
    sources = _row_source_texts(row)
    if not _has_lossless_reordered_row_sources(row):
        return False
    if any(_projected_band_index(cell) is None for cell in row.cells):
        return False
    row_atom_ids = _row_atom_ids(row, ledger)
    if not _has_exact_digital_positioned_backing(row_atom_ids, ledger):
        return False
    if not any(_contains_cue(source, _NONFINANCIAL_IDENTIFIER_CUES) for source in sources):
        return False
    if any(ledger.fragmented_date_candidates(cell) for cell in row.cells):
        return False
    for source in sources:
        if (
            currencies_in_text(source)
            or "%" in source
            or any(unicodedata.category(char) == "Sc" for char in source)
            or any(is_installment_shaped(token) for token in normalize_text(source).split())
            or _contains_cue(
                source,
                (*_RATE_HEADER_CUES, *_FEE_HEADER_CUES, *_GROSS_FEE_CUES, *_DISCOUNT_CUES),
            )
        ):
            return False
        material = tuple(
            char
            for char in normalize_text(source)
            if not char.isspace() and unicodedata.category(char) != "Cf"
        )
        if (
            not any(char.isalpha() for char in material)
            or not any(char.isdigit() for char in material)
            or not _has_only_alpha_flanked_other_punctuation(source)
        ):
            return False
    return not ledger.positioned_decimal_candidates(row_atom_ids)


def _is_proven_split_band_nonfinancial_identifier_row(
    row: Row,
    ledger: EvidenceLedger,
) -> bool:
    sources = _row_source_texts(row)
    row_atom_ids = _row_atom_ids(row, ledger)
    numeric_atom_ids = _non_percentage_numeric_atom_ids(row_atom_ids, ledger)
    numeric_cells = _candidate_cells(row, ledger, numeric_atom_ids)
    numeric_bands = tuple(_projected_band_index(cell) for cell in numeric_cells)
    if (
        not _has_lossless_reordered_row_sources(row)
        or any(_projected_band_index(cell) is None for cell in row.cells)
        or not _has_exact_digital_positioned_backing(row_atom_ids, ledger)
        or not numeric_atom_ids
        or _percent_bound_numeric_atom_ids(row_atom_ids, ledger)
        or ledger.positioned_decimal_candidates(row_atom_ids)
        or any(ledger.fragmented_date_candidates(cell) for cell in row.cells)
        or any(index is None for index in numeric_bands)
    ):
        return False
    concrete_bands = {index for index in numeric_bands if index is not None}
    if len(concrete_bands) != 2 or max(concrete_bands) - min(concrete_bands) != 1:
        return False
    if not any(
        ledger.atoms_for_cell(cell) & numeric_atom_ids
        and any(
            _contains_cue(source, _NONFINANCIAL_IDENTIFIER_CUES)
            for source in _cell_source_texts(cell)
        )
        for cell in numeric_cells
    ):
        return False
    for source in sources:
        if (
            currencies_in_text(source)
            or "%" in source
            or any(unicodedata.category(char) == "Sc" for char in source)
            or any(is_installment_shaped(token) for token in normalize_text(source).split())
            or _contains_cue(
                source,
                (*_RATE_HEADER_CUES, *_FEE_HEADER_CUES, *_GROSS_FEE_CUES, *_DISCOUNT_CUES),
            )
        ):
            return False
    material = tuple(
        char
        for source in sources
        for char in normalize_text(source)
        if not char.isspace() and unicodedata.category(char) != "Cf"
    )
    return any(char.isalpha() for char in material) and any(char.isdigit() for char in material)


def _proven_projected_identifier_atom_ids(
    rows: Sequence[Row],
    ledger: EvidenceLedger,
    component_bands: frozenset[int],
) -> frozenset[int] | None:
    cells_by_band: dict[int, list[Cell]] = {}
    for row in rows:
        for cell in row.cells:
            band = _projected_band_index(cell)
            if band is None:
                if _non_percentage_numeric_atom_ids(ledger.atoms_for_cell(cell), ledger):
                    return None
                continue
            if band not in component_bands:
                cells_by_band.setdefault(band, []).append(cell)

    proven_atom_ids: set[int] = set()
    for cells in cells_by_band.values():
        numeric_atom_ids = frozenset(
            atom_id
            for cell in cells
            for atom_id in _non_percentage_numeric_atom_ids(
                ledger.atoms_for_cell(cell),
                ledger,
            )
        )
        if not numeric_atom_ids:
            continue
        if (
            not _has_exact_digital_positioned_backing(numeric_atom_ids, ledger)
            or ledger.positioned_decimal_candidates(numeric_atom_ids)
            or any(ledger.fragmented_date_candidates(cell) for cell in cells)
            or not any(
                not (
                    _non_percentage_numeric_atom_ids(ledger.atoms_for_cell(cell), ledger)
                    or _percent_bound_numeric_atom_ids(ledger.atoms_for_cell(cell), ledger)
                )
                and any(
                    _contains_cue(source, _NONFINANCIAL_IDENTIFIER_CUES)
                    for source in _cell_source_texts(cell)
                )
                for cell in cells
            )
        ):
            return None
        for cell in cells:
            for source in _cell_source_texts(cell):
                if (
                    currencies_in_text(source)
                    or "%" in source
                    or any(unicodedata.category(char) == "Sc" for char in source)
                    or any(is_installment_shaped(token) for token in normalize_text(source).split())
                    or _contains_cue(
                        source,
                        (
                            *_RATE_HEADER_CUES,
                            *_FEE_HEADER_CUES,
                            *_GROSS_FEE_CUES,
                            *_DISCOUNT_CUES,
                        ),
                    )
                ):
                    return None
        proven_atom_ids.update(numeric_atom_ids)
    return frozenset(proven_atom_ids)


def _row_in_projected_band(row: Row, band: int) -> Row | None:
    cells = tuple(cell for cell in row.cells if _projected_band_index(cell) == band)
    if not cells:
        return None
    return row.model_copy(
        update={
            "bbox": union_bbox(cell.bbox for cell in cells),
            "cells": cells,
        }
    )


def _percentage_explains_amount(
    percentage: Decimal,
    basis: Decimal,
    amount: Decimal,
) -> bool:
    if not all(value.is_finite() for value in (percentage, basis, amount)) or basis == 0:
        return False
    percentage_exponent = percentage.as_tuple().exponent
    amount_exponent = amount.as_tuple().exponent
    if not isinstance(percentage_exponent, int) or not isinstance(amount_exponent, int):
        return False
    percentage_unit = Decimal((0, (1,), percentage_exponent))
    amount_unit = Decimal((0, (1,), amount_exponent))
    percentage_half_unit = exact_product((percentage_unit, Decimal("0.5")))
    amount_half_unit = exact_product((amount_unit, Decimal("0.5")))
    percentage_lower = max(
        Decimal("0"),
        exact_difference(percentage.copy_abs(), percentage_half_unit),
    )
    percentage_upper = exact_sum((percentage.copy_abs(), percentage_half_unit))
    amount_lower = max(
        Decimal("0"),
        exact_difference(amount.copy_abs(), amount_half_unit),
    )
    amount_upper = exact_sum((amount.copy_abs(), amount_half_unit))
    rate_lower_scaled = exact_product((basis.copy_abs(), percentage_lower))
    rate_upper_scaled = exact_product((basis.copy_abs(), percentage_upper))
    amount_lower_scaled = exact_product((amount_lower, Decimal("100")))
    amount_upper_scaled = exact_product((amount_upper, Decimal("100")))
    return rate_lower_scaled < amount_upper_scaled and amount_lower_scaled < rate_upper_scaled


def _fuse_intraword_punctuation(text: str) -> str:
    fused: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if not (unicodedata.category(char).startswith("P") and char != "%"):
            fused.append(char)
            index += 1
            continue
        end = index + 1
        while end < len(text):
            next_char = text[end]
            if not (unicodedata.category(next_char).startswith("P") and next_char != "%"):
                break
            end += 1
        if index > 0 and end < len(text) and text[index - 1].isalnum() and text[end].isalnum():
            index = end
            continue
        fused.extend(text[index:end])
        index = end
    return "".join(fused)


def _semantic_screen_forms(text: str) -> tuple[str, ...]:
    compatible = unicodedata.normalize("NFKC", text)
    without_format_controls = "".join(
        char for char in compatible if unicodedata.category(char) != "Cf"
    )
    fused = _fuse_intraword_punctuation(without_format_controls)
    separated = "".join(
        " " if unicodedata.category(char).startswith("P") and char != "%" else char
        for char in without_format_controls
    )
    return tuple(dict.fromkeys(normalize_text(form) for form in (fused, separated)))


def _has_unsupported_percent_sign(text: str) -> bool:
    return any(char != "%" and "PERCENT SIGN" in unicodedata.name(char, "") for char in text)


def _has_competing_projected_percentage_semantics(
    source: str,
    *,
    allow_ascii_percent: bool,
) -> bool:
    return _has_unsupported_percent_sign(source) or any(
        (not allow_ascii_percent and "%" in semantic_source)
        or _contains_cue(semantic_source, _COMPETING_PERCENT_METADATA_CUES)
        or bool(currencies_in_text(semantic_source))
        or any(unicodedata.category(char) == "Sc" for char in semantic_source)
        or any(is_installment_shaped(token) for token in normalize_text(semantic_source).split())
        for semantic_source in _semantic_screen_forms(source)
    )


def _cell_has_lossless_digital_sources(cell: Cell, ledger: EvidenceLedger) -> bool:
    atom_ids = ledger.atoms_for_cell(cell)
    sources = _cell_source_texts(cell)
    return (
        cell.confidence == 1.0
        and _has_exact_digital_positioned_backing(atom_ids, ledger)
        and bool(sources)
        and len({_source_character_signature(source) for source in sources}) == 1
    )


def _percentage_annotation_material(text: str) -> str:
    normalized = normalize_text(text)
    return "".join(
        char
        for char in normalized
        if not char.isalpha()
        and not char.isspace()
        and unicodedata.category(char) != "Cf"
        and not (unicodedata.category(char) == "Po" and char != "%")
    )


def _proven_projected_discount_evidence(
    rows: Sequence[Row],
    region: TableRegion,
    ledger: EvidenceLedger,
    component_bands: frozenset[int],
    *,
    primary_percentage: Decimal,
    gross_amount: Decimal,
    discount_amount: Decimal,
    billed_amount: Decimal,
) -> _ProjectedDiscountEvidence | None:
    outside_cells_by_band: dict[int, list[tuple[int, Cell]]] = {}
    for row_index, row in enumerate(rows):
        for cell in row.cells:
            band = _projected_band_index(cell)
            if any(_has_unsupported_percent_sign(source) for source in _cell_source_texts(cell)):
                return None
            if band is None:
                if ledger.positioned_percentage_candidates(ledger.atoms_for_cell(cell)):
                    return None
                continue
            if band not in component_bands:
                outside_cells_by_band.setdefault(band, []).append((row_index, cell))

    percentage_bands = tuple(
        band
        for band, indexed_cells in outside_cells_by_band.items()
        if any(
            ledger.positioned_percentage_candidates(ledger.atoms_for_cell(cell))
            for _, cell in indexed_cells
        )
    )
    if not percentage_bands:
        return _ProjectedDiscountEvidence()
    if len(percentage_bands) != 1:
        return None
    band = percentage_bands[0]
    columns = tuple(column for column in region.table_schema.columns if column.index == band)
    indexed_cells = tuple(outside_cells_by_band[band])
    header_sources = tuple(
        source
        for column in columns
        for cell in column.source_cells
        for source in _cell_source_texts(cell)
    )
    if (
        len(columns) != 1
        or columns[0].role is not ColumnRole.UNKNOWN
        or not header_sources
        or any(
            _has_competing_projected_percentage_semantics(
                source,
                allow_ascii_percent=False,
            )
            for source in header_sources
        )
        or len(indexed_cells) < 4
        or len({row_index for row_index, _ in indexed_cells}) != len(indexed_cells)
        or any(not _cell_has_lossless_digital_sources(cell, ledger) for _, cell in indexed_cells)
        or any(ledger.fragmented_date_candidates(cell) for _, cell in indexed_cells)
    ):
        return None

    anchor_indexes = tuple(
        row_index
        for row_index, cell in indexed_cells
        if not (
            _non_percentage_numeric_atom_ids(ledger.atoms_for_cell(cell), ledger)
            or ledger.positioned_percentage_candidates(ledger.atoms_for_cell(cell))
        )
        and any(
            _contains_cue(source, _NONFINANCIAL_IDENTIFIER_CUES)
            for source in _cell_source_texts(cell)
        )
    )
    percentage_cells = tuple(
        (row_index, cell, candidates[0])
        for row_index, cell in indexed_cells
        if (candidates := ledger.positioned_percentage_candidates(ledger.atoms_for_cell(cell)))
        if len(candidates) == 1
    )
    if len(anchor_indexes) != 1 or len(percentage_cells) != 1:
        return None
    percentage_index, percentage_cell, percentage_candidate = percentage_cells[0]
    if (
        percentage_candidate.marker_count != 1
        or not re.fullmatch(r"(?:[1-9]\d?|100)", percentage_candidate.text)
        or anchor_indexes[0] >= percentage_index
        or percentage_index - anchor_indexes[0] > 2
    ):
        return None
    percentage_value = _decimal(percentage_candidate.text)
    if percentage_value is None or percentage_value == primary_percentage:
        return None

    percentage_sources = _cell_source_texts(percentage_cell)
    canonical_renderings = {
        f"{percentage_candidate.text}%",
        f"%{percentage_candidate.text}",
    }
    if (
        any(
            _percentage_annotation_material(source) not in canonical_renderings
            or sum(
                unicodedata.category(char) == "Po" and char != "%"
                for char in normalize_text(source)
            )
            > 1
            for source in percentage_sources
        )
        or min(
            (
                sum(
                    any(char.isalpha() for char in token)
                    for token in phrase_tokens(source, ignore_acronym_quotes=True)
                )
                for source in percentage_sources
            ),
            default=0,
        )
        < 2
        or _has_typed_numeric_wrapper(
            percentage_candidate.number,
            ledger.atoms_for_cell(percentage_cell),
            ledger,
            wrappers=_SIGNED_OR_ACCOUNTING_WRAPPERS,
        )
        or any(
            _has_competing_projected_percentage_semantics(
                source,
                allow_ascii_percent=True,
            )
            for source in percentage_sources
        )
    ):
        return None

    nonnumeric_cells = tuple(
        cell
        for _, cell in indexed_cells
        if cell is not percentage_cell
        and not _non_percentage_numeric_atom_ids(ledger.atoms_for_cell(cell), ledger)
        and not ledger.positioned_percentage_candidates(ledger.atoms_for_cell(cell))
    )
    if len(nonnumeric_cells) != len(indexed_cells) - 1 or len(nonnumeric_cells) < 3:
        return None
    if any(
        not any(char.isalpha() for source in _cell_source_texts(cell) for char in source)
        or any(
            _has_competing_projected_percentage_semantics(
                source,
                allow_ascii_percent=False,
            )
            for source in _cell_source_texts(cell)
        )
        for cell in nonnumeric_cells
    ):
        return None

    net_amount = exact_difference(gross_amount, discount_amount)
    explained_relationships = frozenset(
        relationship
        for relationship, basis, amount in (
            ("billed_to_gross", billed_amount, gross_amount),
            ("billed_to_discount", billed_amount, discount_amount),
            ("billed_to_net", billed_amount, net_amount),
            ("gross_to_discount", gross_amount, discount_amount),
            ("gross_to_net", gross_amount, net_amount),
        )
        if _percentage_explains_amount(percentage_value, basis, amount)
    )
    if explained_relationships != {"billed_to_discount"}:
        return None
    band_atom_ids = frozenset(
        atom_id for _, cell in indexed_cells for atom_id in ledger.atoms_for_cell(cell)
    )
    percentage_atom_ids = percentage_candidate.semantic_atom_ids
    if not percentage_atom_ids <= band_atom_ids:
        return None
    return _ProjectedDiscountEvidence(
        percentage_atom_ids=percentage_atom_ids,
        ancillary_atom_ids=band_atom_ids - percentage_atom_ids,
    )


def _has_only_proven_projected_discount_ancillary(
    row: Row,
    ledger: EvidenceLedger,
    component_band: int,
    identifier_atom_ids: frozenset[int],
    discount_percentage_atom_ids: frozenset[int],
) -> bool:
    outside_cells = tuple(
        cell for cell in row.cells if _projected_band_index(cell) != component_band
    )
    if not outside_cells:
        return True
    if any(_projected_band_index(cell) is None for cell in outside_cells):
        return False
    outside_atom_ids = frozenset(
        atom_id for cell in outside_cells for atom_id in ledger.atoms_for_cell(cell)
    )
    non_percentage_atom_ids = _non_percentage_numeric_atom_ids(
        outside_atom_ids,
        ledger,
    )
    percentage_atom_ids = frozenset(
        atom_id
        for candidate in ledger.positioned_percentage_candidates(outside_atom_ids)
        for atom_id in candidate.semantic_atom_ids
    )
    return (
        non_percentage_atom_ids <= identifier_atom_ids
        and percentage_atom_ids <= discount_percentage_atom_ids
    )


def _has_proven_positioned_fx_geometry(
    bounded_rows: Sequence[Row],
    ledger: EvidenceLedger,
    *,
    rate_index: int,
    percentage_index: int,
    gross_index: int,
    discount_index: int,
    rate_atom_ids: frozenset[int],
    percentage_atom_ids: frozenset[int],
    gross_atom_ids: frozenset[int],
    discount_atom_ids: frozenset[int],
) -> bool:
    rate_row = bounded_rows[rate_index]
    percentage_row = bounded_rows[percentage_index]
    gross_row = bounded_rows[gross_index]
    discount_row = bounded_rows[discount_index]
    rate_bands = _projected_rate_bands(rate_row, ledger, rate_atom_ids)
    percentage_band = _single_projected_component_band(
        percentage_row,
        ledger,
        percentage_atom_ids,
        percentage=True,
        incompatible_cues=_PERCENTAGE_COMPONENT_INCOMPATIBLE_CUES,
    )
    gross_band = _single_projected_component_band(
        gross_row,
        ledger,
        gross_atom_ids,
        incompatible_cues=_GROSS_COMPONENT_INCOMPATIBLE_CUES,
    )
    discount_band = _single_projected_component_band(
        discount_row,
        ledger,
        discount_atom_ids,
        incompatible_cues=_DISCOUNT_COMPONENT_INCOMPATIBLE_CUES,
    )
    split_rate_geometry = (
        len(rate_bands) == 2
        and percentage_band is not None
        and gross_band is not None
        and discount_band is not None
        and percentage_band != gross_band
        and rate_bands == {percentage_band, gross_band}
        and discount_band == gross_band
    )
    single_rate_band = _single_projected_component_band(
        rate_row,
        ledger,
        rate_atom_ids,
        incompatible_cues=_RATE_COMPONENT_INCOMPATIBLE_CUES,
    )
    single_rate_geometry = (
        single_rate_band is not None
        and percentage_band is not None
        and gross_band is not None
        and discount_band is not None
        and abs(single_rate_band - percentage_band) == 1
        and gross_band == discount_band
        and gross_band in {single_rate_band, percentage_band}
    )
    if not (split_rate_geometry or single_rate_geometry):
        return False
    if (
        rate_index + 1 != percentage_index
        or percentage_index + 1 != gross_index
        or gross_index + 1 != discount_index
    ):
        return False
    component_rows = (rate_row, percentage_row, gross_row, discount_row)
    component_boxes = tuple(
        union_bbox(ledger.atoms[atom_id].bbox for atom_id in atom_ids)
        for atom_ids in (
            rate_atom_ids,
            percentage_atom_ids,
            gross_atom_ids,
            discount_atom_ids,
        )
    )
    if any(
        previous_row.page_number != current_row.page_number
        or previous_box[3] > current_box[1]
        or max(0.0, current_box[1] - previous_box[3])
        > min(bbox_height(previous_box), bbox_height(current_box)) * 1.5
        for (previous_row, current_row), (previous_box, current_box) in zip(
            pairwise(component_rows),
            pairwise(component_boxes),
            strict=True,
        )
    ):
        return False
    component_indexes = {rate_index, percentage_index, gross_index, discount_index}
    return all(
        _is_proven_nonfinancial_identifier_row(row, ledger)
        or _is_proven_split_band_nonfinancial_identifier_row(row, ledger)
        for index, row in enumerate(bounded_rows)
        if index not in component_indexes
    )


def _proven_expanded_positioned_fx_detail_block(
    rows: Sequence[Row],
    region: TableRegion,
    ledger: EvidenceLedger,
    original_currency: str,
    billing_currency: str,
    original_amount: Decimal,
    billed_amount: Decimal,
) -> _FxValues | None:
    bounded_rows = tuple(
        sorted(
            (row for row in rows if has_row_tag(row, RowTag.FOREIGN_CONVERSION_DETAIL)),
            key=lambda item: (item.page_number, item.bbox[1]),
        )
    )
    if len(bounded_rows) < 4 or original_amount == 0 or billed_amount == 0:
        return None
    source_texts = tuple(_row_source_texts(row) for row in bounded_rows)
    rate_indexes = tuple(
        index
        for index, sources in enumerate(source_texts)
        if any(_contains_cue(source, _RATE_HEADER_CUES) for source in sources)
    )
    percentage_indexes = tuple(
        index
        for index, sources in enumerate(source_texts)
        if any(_contains_cue(source, _FEE_HEADER_CUES) and "%" in source for source in sources)
    )
    if len(rate_indexes) != 1 or len(percentage_indexes) != 1:
        return None
    rate_index = rate_indexes[0]
    percentage_index = percentage_indexes[0]
    if percentage_index != rate_index + 1 or percentage_index + 2 >= len(bounded_rows):
        return None
    gross_index = percentage_index + 1
    discount_index = gross_index + 1
    gross_sources = source_texts[gross_index]
    if not any(
        _contains_cue(source, (*_GROSS_FEE_CUES, *_DISCOUNT_CUES)) for source in gross_sources
    ):
        return None

    rate_row = bounded_rows[rate_index]
    percentage_row = bounded_rows[percentage_index]
    gross_row = bounded_rows[gross_index]
    discount_row = bounded_rows[discount_index]
    allowed_currencies = frozenset(
        currency
        for value in (original_currency, billing_currency)
        if (currency := canonical_currency(value)) is not None
    )
    if any(
        _has_unsupported_header_currency(source)
        or not set(currencies_in_text(source)) <= allowed_currencies
        for row in (rate_row, percentage_row)
        for source in _row_source_texts(row)
    ):
        return None
    rate = _one_positive_decimal(_row_atom_ids(rate_row, ledger), ledger)
    percentage = _one_percent_bound_decimal(_row_atom_ids(percentage_row, ledger), ledger)
    gross = _positioned_row_money(gross_row, ledger, billing_currency)
    if rate is None or percentage is None or gross is None:
        return None
    rate_value, rate_atom_ids = rate
    percentage_value, percentage_candidate = percentage
    percentage_atom_ids = percentage_candidate.numeric_atom_ids
    percentage_evidence_atom_ids = percentage_candidate.semantic_atom_ids
    gross_amount, gross_currency, gross_atom_ids = gross
    rate_bands = _projected_rate_bands(rate_row, ledger, rate_atom_ids)
    percentage_band = _single_projected_component_band(
        percentage_row,
        ledger,
        percentage_atom_ids,
        percentage=True,
        incompatible_cues=_PERCENTAGE_COMPONENT_INCOMPATIBLE_CUES,
    )
    gross_band = _single_projected_component_band(
        gross_row,
        ledger,
        gross_atom_ids,
        incompatible_cues=_GROSS_COMPONENT_INCOMPATIBLE_CUES,
    )
    single_rate_band = _single_projected_component_band(
        rate_row,
        ledger,
        rate_atom_ids,
        incompatible_cues=_RATE_COMPONENT_INCOMPATIBLE_CUES,
    )
    split_rate_geometry = (
        len(rate_bands) == 2
        and percentage_band is not None
        and gross_band is not None
        and percentage_band != gross_band
        and rate_bands == {percentage_band, gross_band}
    )
    single_rate_geometry = (
        single_rate_band is not None
        and percentage_band is not None
        and gross_band is not None
        and abs(single_rate_band - percentage_band) == 1
        and gross_band in {single_rate_band, percentage_band}
    )
    if not (split_rate_geometry or single_rate_geometry) or gross_band is None:
        return None
    component_bands = frozenset(
        band
        for band in (*rate_bands, single_rate_band, percentage_band, gross_band)
        if band is not None
    )
    identifier_atom_ids = _proven_projected_identifier_atom_ids(
        bounded_rows,
        ledger,
        component_bands,
    )
    if identifier_atom_ids is None:
        return None

    discount_geometry_row = discount_row
    discount = _positioned_row_money(discount_row, ledger, billing_currency)
    projected_discount_row = _row_in_projected_band(discount_row, gross_band)
    projection_excludes_cells = projected_discount_row is not None and len(
        projected_discount_row.cells
    ) != len(discount_row.cells)
    if projection_excludes_cells:
        if projected_discount_row is None:
            return None
        projected_discount = _positioned_row_money(
            projected_discount_row,
            ledger,
            billing_currency,
        )
        if projected_discount is None:
            return None
        discount_geometry_row = projected_discount_row
        discount = projected_discount
    if discount is None:
        return None
    discount_amount, discount_currency, discount_atom_ids = discount
    projected_discount_evidence = _proven_projected_discount_evidence(
        bounded_rows,
        region,
        ledger,
        component_bands,
        primary_percentage=percentage_value,
        gross_amount=gross_amount,
        discount_amount=discount_amount,
        billed_amount=billed_amount,
    )
    if projected_discount_evidence is None or (
        projection_excludes_cells
        and not _has_only_proven_projected_discount_ancillary(
            discount_row,
            ledger,
            gross_band,
            identifier_atom_ids,
            projected_discount_evidence.percentage_atom_ids,
        )
    ):
        return None
    if not (
        _has_exact_digital_positioned_backing(rate_atom_ids, ledger)
        and _has_exact_digital_positioned_backing(percentage_atom_ids, ledger)
        and Decimal("0") < percentage_value <= Decimal("100")
        and gross_currency == discount_currency
        and Decimal("0") <= discount_amount <= gross_amount
    ):
        return None
    geometry_rows = list(bounded_rows)
    geometry_rows[discount_index] = discount_geometry_row
    if not _has_proven_positioned_fx_geometry(
        geometry_rows,
        ledger,
        rate_index=rate_index,
        percentage_index=percentage_index,
        gross_index=gross_index,
        discount_index=discount_index,
        rate_atom_ids=rate_atom_ids,
        percentage_atom_ids=percentage_atom_ids,
        gross_atom_ids=gross_atom_ids,
        discount_atom_ids=discount_atom_ids,
    ):
        return None

    absolute_original = original_amount.copy_abs()
    absolute_billed = billed_amount.copy_abs()
    rate_delta = exact_difference(
        exact_product((rate_value, absolute_original)),
        absolute_billed,
    ).copy_abs()
    if rate_delta > exact_product((absolute_billed, Decimal("0.05"))):
        return None
    percentage_basis = exact_product((absolute_billed, percentage_value))
    gross_delta = exact_difference(
        exact_product((Decimal("100"), gross_amount)),
        percentage_basis,
    ).copy_abs()
    gross_tolerance = max(
        Decimal("1"),
        exact_product((percentage_basis, Decimal("0.05"))),
    )
    if gross_delta > gross_tolerance:
        return None

    gross_evidence = _row_evidence(gross_row)
    discount_evidence = _row_evidence(discount_geometry_row)
    net_amount = exact_difference(gross_amount, discount_amount)
    return _FxValues(
        exchange_rate=ExtractedDecimal(
            value=rate_value,
            evidence=_row_evidence(rate_row),
        ),
        fee_percentage=ExtractedDecimal(
            value=percentage_value,
            evidence=_row_evidence(percentage_row),
        ),
        gross_fee=ExtractedMoney(
            amount=gross_amount,
            currency=gross_currency,
            evidence=gross_evidence,
        ),
        fee_discount=ExtractedMoney(
            amount=discount_amount,
            currency=discount_currency,
            evidence=discount_evidence,
        ),
        net_fee=ExtractedMoney(
            amount=net_amount,
            currency=gross_currency,
            evidence=tuple(dict.fromkeys((*gross_evidence, *discount_evidence))),
            derivation="gross_fee_minus_discount",
        ),
        claims=(
            EvidenceClaim(SemanticOwner.EXCHANGE_RATE, rate_atom_ids),
            EvidenceClaim(
                SemanticOwner.FX_FEE_PERCENTAGE,
                percentage_evidence_atom_ids,
            ),
            EvidenceClaim(SemanticOwner.GROSS_FX_FEE, gross_atom_ids),
            EvidenceClaim(
                SemanticOwner.FX_FEE_DISCOUNT,
                discount_atom_ids | projected_discount_evidence.percentage_atom_ids,
            ),
            *(
                (
                    EvidenceClaim(
                        SemanticOwner.ANCILLARY,
                        projected_discount_evidence.ancillary_atom_ids,
                    ),
                )
                if projected_discount_evidence.ancillary_atom_ids
                else ()
            ),
        ),
    )


def _single_compact_component_band(
    row: Row,
    ledger: EvidenceLedger,
    atom_ids: frozenset[int],
) -> int | None:
    cells = _candidate_cells(row, ledger, atom_ids)
    if (
        len(cells) != 1
        or not _has_exact_digital_positioned_backing(atom_ids, ledger)
        or not _has_uncontested_full_span_word_renderings(row, ledger, atom_ids)
    ):
        return None
    return _projected_band_index(cells[0])


def _compact_component_bands(
    row: Row,
    ledger: EvidenceLedger,
    atom_ids: frozenset[int],
) -> frozenset[int]:
    cells = _candidate_cells(row, ledger, atom_ids)
    indexes = tuple(_projected_band_index(cell) for cell in cells)
    if not cells or any(index is None for index in indexes):
        return frozenset()
    return frozenset(index for index in indexes if index is not None)


def _has_uncontested_compact_combined_word_renderings(
    row: Row,
    ledger: EvidenceLedger,
    percentage_atom_ids: frozenset[int],
    gross_atom_ids: frozenset[int],
) -> bool:
    percentage_candidates = ledger.positioned_decimal_candidates(percentage_atom_ids)
    gross_candidates = ledger.positioned_decimal_candidates(gross_atom_ids)
    if len(percentage_candidates) != 1 or len(gross_candidates) != 1:
        return False
    percentage_value = _decimal(percentage_candidates[0].text)
    gross_value = _decimal(gross_candidates[0].text)
    if percentage_value is None or gross_value is None:
        return False
    percentage_atoms = tuple(ledger.atoms[atom_id] for atom_id in percentage_atom_ids)
    gross_atoms = tuple(ledger.atoms[atom_id] for atom_id in gross_atom_ids)
    for word in (word for cell in row.cells for word in cell.words):
        covers_percentage = all(center_inside(atom.bbox, word.bbox) for atom in percentage_atoms)
        covers_gross = all(center_inside(atom.bbox, word.bbox) for atom in gross_atoms)
        if not (covers_percentage or covers_gross):
            continue
        percentage_rendering = _rendered_decimal_values(word.text, percent_bound=True)
        gross_rendering = _rendered_decimal_values(word.text, percent_bound=False)
        if (
            percentage_rendering is None
            or gross_rendering is None
            or (percentage_rendering and percentage_rendering != (percentage_value,))
            or (gross_rendering and gross_rendering != (gross_value,))
        ):
            return False
    return True


def _has_exact_compact_row_contract(
    row: Row,
    ledger: EvidenceLedger,
    expected_numeric_atom_ids: frozenset[int],
) -> bool:
    row_atom_ids = _row_atom_ids(row, ledger)
    numeric_atom_ids = _non_percentage_numeric_atom_ids(
        row_atom_ids,
        ledger,
    ) | _percent_bound_numeric_atom_ids(row_atom_ids, ledger)
    return (
        _has_lossless_reordered_row_sources(row)
        and _has_exact_digital_positioned_backing(row_atom_ids, ledger)
        and numeric_atom_ids == expected_numeric_atom_ids
        and not any(ledger.fragmented_date_candidates(cell) for cell in row.cells)
    )


def _component_evidence_is_vertically_ordered(
    first_row: Row,
    first_atom_ids: frozenset[int],
    second_row: Row,
    second_atom_ids: frozenset[int],
    ledger: EvidenceLedger,
) -> bool:
    first_bbox = union_bbox(ledger.atoms[atom_id].bbox for atom_id in first_atom_ids)
    second_bbox = union_bbox(ledger.atoms[atom_id].bbox for atom_id in second_atom_ids)
    return (
        first_row.page_number == second_row.page_number
        and first_bbox[3] <= second_bbox[1]
        and max(0.0, second_bbox[1] - first_bbox[3])
        <= min(bbox_height(first_bbox), bbox_height(second_bbox)) * 1.5
    )


def _is_proven_nonfinancial_annotation_row(
    row: Row,
    ledger: EvidenceLedger,
    allowed_currencies: frozenset[str] = frozenset(),
) -> bool:
    sources = _row_source_texts(row)
    atom_ids = _row_atom_ids(row, ledger)
    if (
        not _has_lossless_reordered_row_sources(row)
        or any(_projected_band_index(cell) is None for cell in row.cells)
        or not _has_exact_digital_positioned_backing(atom_ids, ledger)
        or any(ledger.fragmented_date_candidates(cell) for cell in row.cells)
        or _non_percentage_numeric_atom_ids(atom_ids, ledger)
        or _percent_bound_numeric_atom_ids(atom_ids, ledger)
    ):
        return False
    for source in sources:
        if (
            not set(currencies_in_text(source)) <= allowed_currencies
            or _has_unsupported_header_currency(source)
            or "%" in source
            or any(unicodedata.category(char) == "Sc" for char in source)
            or any(is_installment_shaped(token) for token in normalize_text(source).split())
            or _contains_cue(
                source,
                (*_RATE_HEADER_CUES, *_FEE_HEADER_CUES, *_GROSS_FEE_CUES, *_DISCOUNT_CUES),
            )
            or not any(char.isalpha() for char in source)
        ):
            return False
    return True


def _is_proven_nonfinancial_identifier_label_row(
    row: Row,
    ledger: EvidenceLedger,
    allowed_currencies: frozenset[str] = frozenset(),
) -> bool:
    return _is_proven_nonfinancial_annotation_row(
        row,
        ledger,
        allowed_currencies,
    ) and any(
        _contains_cue(source, _NONFINANCIAL_IDENTIFIER_CUES) for source in _row_source_texts(row)
    )


def _is_proven_split_nonfinancial_identifier(
    label_row: Row,
    value_row: Row,
    ledger: EvidenceLedger,
    allowed_currencies: frozenset[str] = frozenset(),
) -> bool:
    if not _is_proven_nonfinancial_identifier_label_row(
        label_row,
        ledger,
        allowed_currencies,
    ):
        return False
    value_atom_ids = _row_atom_ids(value_row, ledger)
    value_sources = _row_source_texts(value_row)
    label_bands = {
        band for cell in label_row.cells if (band := _projected_band_index(cell)) is not None
    }
    value_bands = tuple(_projected_band_index(cell) for cell in value_row.cells)
    if (
        len(value_row.cells) != 1
        or not value_sources
        or (len(value_sources) > 1 and not _has_lossless_reordered_row_sources(value_row))
        or len(value_bands) != 1
        or value_bands[0] not in label_bands
        or not value_atom_ids
        or not _has_exact_digital_positioned_backing(value_atom_ids, ledger)
        or not _non_percentage_numeric_atom_ids(value_atom_ids, ledger)
        or ledger.positioned_decimal_candidates(value_atom_ids)
        or any(ledger.fragmented_date_candidates(cell) for cell in value_row.cells)
    ):
        return False
    for source in value_sources:
        if (
            not any(char.isdigit() for char in source)
            or currencies_in_text(source)
            or "%" in source
            or any(unicodedata.category(char) == "Sc" for char in source)
            or any(is_installment_shaped(token) for token in normalize_text(source).split())
            or _contains_cue(
                source,
                (*_RATE_HEADER_CUES, *_FEE_HEADER_CUES, *_GROSS_FEE_CUES, *_DISCOUNT_CUES),
            )
        ):
            return False
    label_atom_ids = _row_atom_ids(label_row, ledger)
    return _component_evidence_is_vertically_ordered(
        label_row,
        label_atom_ids,
        value_row,
        value_atom_ids,
        ledger,
    )


def _has_only_proven_nonfinancial_ancillary_rows(
    rows: Sequence[Row],
    ledger: EvidenceLedger,
    allowed_currencies: frozenset[str] = frozenset(),
) -> bool:
    index = 0
    while index < len(rows):
        if _is_proven_nonfinancial_identifier_row(rows[index], ledger):
            index += 1
            continue
        if index + 1 < len(rows) and _is_proven_split_nonfinancial_identifier(
            rows[index],
            rows[index + 1],
            ledger,
            allowed_currencies,
        ):
            index += 2
            continue
        if _is_proven_nonfinancial_annotation_row(
            rows[index],
            ledger,
            allowed_currencies,
        ):
            index += 1
            continue
        return False
    return True


def _positioned_compact_gross_money(
    row: Row,
    ledger: EvidenceLedger,
    billing_currency: str,
) -> tuple[Decimal, str, frozenset[int]] | None:
    explicit = _positioned_row_money(row, ledger, billing_currency)
    if explicit is not None:
        return explicit
    currency = canonical_currency(billing_currency)
    source_texts = _row_source_texts(row)
    parsed = _one_non_percentage_money_decimal(_row_atom_ids(row, ledger), ledger)
    if (
        currency is None
        or currencies_in_text(" ".join(source_texts))
        or contains_credit_marker(" ".join(source_texts))
        or parsed is None
        or not _has_exact_digital_positioned_backing(parsed[1], ledger)
    ):
        return None
    return parsed[0], currency, parsed[1]


def _proven_compact_positioned_fx_detail_block(
    rows: Sequence[Row],
    ledger: EvidenceLedger,
    original_currency: str,
    billing_currency: str,
    original_amount: Decimal,
    billed_amount: Decimal,
) -> _FxValues | None:
    bounded_rows = tuple(
        sorted(
            (row for row in rows if has_row_tag(row, RowTag.FOREIGN_CONVERSION_DETAIL)),
            key=lambda item: (item.page_number, item.bbox[1]),
        )
    )
    if len(bounded_rows) < 3 or original_amount == 0 or billed_amount == 0:
        return None
    rate_row, combined_row, discount_row = bounded_rows[:3]
    rate = _one_positive_decimal(_row_atom_ids(rate_row, ledger), ledger)
    percentage = _one_percent_bound_decimal(_row_atom_ids(combined_row, ledger), ledger)
    gross = _positioned_compact_gross_money(combined_row, ledger, billing_currency)
    discount = _positioned_row_money(discount_row, ledger, billing_currency)
    if rate is None or percentage is None or gross is None or discount is None:
        return None
    rate_value, rate_atom_ids = rate
    percentage_value, percentage_candidate = percentage
    percentage_atom_ids = percentage_candidate.numeric_atom_ids
    percentage_evidence_atom_ids = percentage_candidate.semantic_atom_ids
    gross_amount, gross_currency, gross_atom_ids = gross
    discount_amount, discount_currency, discount_atom_ids = discount
    allowed_currencies = frozenset(
        currency
        for value in (original_currency, billing_currency)
        if (currency := canonical_currency(value)) is not None
    )
    component_rows = (rate_row, combined_row, discount_row)
    component_sources = tuple(_row_source_texts(row) for row in component_rows)
    if (
        not Decimal("0") < percentage_value <= Decimal("100")
        or gross_currency != discount_currency
        or not Decimal("0") <= discount_amount <= gross_amount
        or any(
            _has_unsupported_header_currency(source)
            or not set(currencies_in_text(source)) <= allowed_currencies
            for sources in component_sources
            for source in sources
        )
        or any(
            _contains_cue(
                source,
                (*_GROSS_FEE_CUES, *_DISCOUNT_CUES),
            )
            or _has_net_fee_semantics(source)
            for source in component_sources[0]
        )
        or any(
            _contains_cue(source, (*_RATE_HEADER_CUES, *_DISCOUNT_CUES))
            or _has_net_fee_semantics(source)
            for source in component_sources[1]
        )
        or not any(_contains_cue(source, _DISCOUNT_CUES) for source in component_sources[2])
        or any(
            _contains_cue(source, (*_RATE_HEADER_CUES, *_GROSS_FEE_CUES))
            for source in component_sources[2]
        )
        or not _has_exact_compact_row_contract(rate_row, ledger, rate_atom_ids)
        or not _has_exact_compact_row_contract(
            combined_row,
            ledger,
            percentage_atom_ids | gross_atom_ids,
        )
        or not _has_exact_compact_row_contract(
            discount_row,
            ledger,
            discount_atom_ids,
        )
    ):
        return None

    rate_band = _single_compact_component_band(rate_row, ledger, rate_atom_ids)
    percentage_bands = _compact_component_bands(
        combined_row,
        ledger,
        percentage_atom_ids,
    )
    gross_bands = _compact_component_bands(combined_row, ledger, gross_atom_ids)
    discount_band = _single_compact_component_band(
        discount_row,
        ledger,
        discount_atom_ids,
    )
    percentage_bbox = union_bbox(ledger.atoms[atom_id].bbox for atom_id in percentage_atom_ids)
    gross_bbox = union_bbox(ledger.atoms[atom_id].bbox for atom_id in gross_atom_ids)
    if (
        rate_band is None
        or len(gross_bands) != 1
        or discount_band is None
        or not _has_uncontested_compact_combined_word_renderings(
            combined_row,
            ledger,
            percentage_atom_ids,
            gross_atom_ids,
        )
        or percentage_bands not in ({rate_band}, {rate_band, *gross_bands})
        or rate_band in gross_bands
        or next(iter(gross_bands)) != discount_band
        or abs(rate_band - next(iter(gross_bands))) != 1
        or vertical_overlap(percentage_bbox, gross_bbox) < 0.8
        or not _component_evidence_is_vertically_ordered(
            rate_row,
            rate_atom_ids,
            combined_row,
            percentage_atom_ids,
            ledger,
        )
        or not _component_evidence_is_vertically_ordered(
            combined_row,
            gross_atom_ids,
            discount_row,
            discount_atom_ids,
            ledger,
        )
        or not _has_only_proven_nonfinancial_ancillary_rows(
            bounded_rows[3:],
            ledger,
            allowed_currencies,
        )
    ):
        return None

    absolute_original = original_amount.copy_abs()
    absolute_billed = billed_amount.copy_abs()
    rate_delta = exact_difference(
        exact_product((rate_value, absolute_original)),
        absolute_billed,
    ).copy_abs()
    percentage_basis = exact_product((absolute_billed, percentage_value))
    gross_delta = exact_difference(
        exact_product((Decimal("100"), gross_amount)),
        percentage_basis,
    ).copy_abs()
    gross_tolerance = max(
        Decimal("1"),
        exact_product((percentage_basis, Decimal("0.05"))),
    )
    if (
        rate_delta > exact_product((absolute_billed, Decimal("0.05")))
        or gross_delta > gross_tolerance
    ):
        return None

    gross_evidence = _row_evidence(combined_row)
    discount_evidence = _row_evidence(discount_row)
    return _FxValues(
        exchange_rate=ExtractedDecimal(value=rate_value, evidence=_row_evidence(rate_row)),
        fee_percentage=ExtractedDecimal(
            value=percentage_value,
            evidence=_row_evidence(combined_row),
        ),
        gross_fee=ExtractedMoney(
            amount=gross_amount,
            currency=gross_currency,
            evidence=gross_evidence,
        ),
        fee_discount=ExtractedMoney(
            amount=discount_amount,
            currency=discount_currency,
            evidence=discount_evidence,
        ),
        net_fee=ExtractedMoney(
            amount=exact_difference(gross_amount, discount_amount),
            currency=gross_currency,
            evidence=tuple(dict.fromkeys((*gross_evidence, *discount_evidence))),
            derivation="gross_fee_minus_discount",
        ),
        claims=(
            EvidenceClaim(SemanticOwner.EXCHANGE_RATE, rate_atom_ids),
            EvidenceClaim(
                SemanticOwner.FX_FEE_PERCENTAGE,
                percentage_evidence_atom_ids,
            ),
            EvidenceClaim(SemanticOwner.GROSS_FX_FEE, gross_atom_ids),
            EvidenceClaim(SemanticOwner.FX_FEE_DISCOUNT, discount_atom_ids),
        ),
    )


def _proven_positioned_fx_detail_block(
    rows: Sequence[Row],
    region: TableRegion,
    ledger: EvidenceLedger,
    original_currency: str,
    billing_currency: str,
    original_amount: Decimal,
    billed_amount: Decimal,
) -> _FxValues | None:
    expanded = _proven_expanded_positioned_fx_detail_block(
        rows,
        region,
        ledger,
        original_currency,
        billing_currency,
        original_amount,
        billed_amount,
    )
    if expanded is not None:
        return expanded
    return _proven_compact_positioned_fx_detail_block(
        rows,
        ledger,
        original_currency,
        billing_currency,
        original_amount,
        billed_amount,
    )


def _continuation_fx_values(
    rows: Sequence[Row],
    ledger: EvidenceLedger,
    original_currency: str,
    billing_currency: str,
    excluded_atom_ids: frozenset[int],
) -> _FxValues:
    claims: list[EvidenceClaim] = []
    diagnostics: list[str] = []
    exchange_rate: ExtractedDecimal | None = None
    fee_percentage: ExtractedDecimal | None = None
    gross_fee: ExtractedMoney | None = None
    fee_discount: ExtractedMoney | None = None
    net_fee: ExtractedMoney | None = None
    rate_seen = False
    rate_ambiguous = False
    percentage_seen = False
    percentage_ambiguous = False
    gross_seen = False
    gross_ambiguous = False
    discount_seen = False
    discount_ambiguous = False
    net_ambiguous = False
    pending_gross = False
    pending_discount = False
    component_bound_atom_ids: set[int] = set()

    bounded_rows = tuple(
        sorted(
            (row for row in rows if has_row_tag(row, RowTag.FOREIGN_CONVERSION_DETAIL)),
            key=lambda item: (item.page_number, item.bbox[1]),
        )
    )
    bounded_source_texts = tuple(_row_source_texts(row) for row in bounded_rows)
    for row, source_texts in zip(bounded_rows, bounded_source_texts, strict=True):
        raw_text = " ".join(source_texts)
        atom_ids = _row_atom_ids(row, ledger)
        evidence = _row_evidence(row)
        is_rate = any(_contains_cue(source, _RATE_HEADER_CUES) for source in source_texts)
        is_percentage = any(
            _contains_cue(source, _FEE_HEADER_CUES) and "%" in source for source in source_texts
        )
        has_gross_cue = any(_contains_cue(source, _GROSS_FEE_CUES) for source in source_texts)
        has_discount_cue = any(_contains_cue(source, _DISCOUNT_CUES) for source in source_texts)
        has_net_fee_cue = any(_has_net_fee_semantics(source) for source in source_texts)
        has_unbound_net_fee_modifier = any(
            _has_unbound_net_fee_modifier(source) for source in source_texts
        )
        has_net_fee_source = has_net_fee_cue or has_unbound_net_fee_modifier
        has_conflicting_net_semantics = any(
            _has_conflicting_net_fee_semantics(source) for source in source_texts
        )
        if is_rate or has_gross_cue or has_discount_cue or has_net_fee_source:
            component_bound_atom_ids.update(
                _non_percentage_numeric_atom_ids(atom_ids - excluded_atom_ids, ledger)
            )
        if is_rate and (is_percentage or has_gross_cue or has_discount_cue or has_net_fee_source):
            rate_seen = True
            rate_ambiguous = True
            exchange_rate = None
            diagnostics.append("unparsed_exchange_rate_candidate")
            if is_percentage:
                percentage_seen = True
                percentage_ambiguous = True
                fee_percentage = None
                diagnostics.append("unparsed_foreign_currency_fee_percentage_candidate")
            if has_gross_cue:
                gross_seen = True
                gross_ambiguous = True
                gross_fee = None
                diagnostics.append("unparsed_foreign_currency_fee_candidate")
            if has_discount_cue and not has_net_fee_source:
                discount_seen = True
                discount_ambiguous = True
                fee_discount = None
                diagnostics.append("unparsed_foreign_currency_fee_discount_candidate")
            elif has_net_fee_source:
                net_ambiguous = True
                net_fee = None
                diagnostics.append("unparsed_foreign_currency_fee_candidate")
            pending_gross = False
            pending_discount = False
            continue
        row_money = _one_row_money(row, ledger, billing_currency)
        is_gross = not has_net_fee_source and (
            has_gross_cue
            or (
                pending_gross
                and not is_rate
                and not is_percentage
                and canonical_currency(billing_currency) in currencies_in_text(raw_text)
                and row_money is not None
            )
        )
        is_discount = has_discount_cue and not has_net_fee_source and not is_gross
        if is_gross or (pending_discount and not is_rate and not is_percentage):
            component_bound_atom_ids.update(
                _non_percentage_numeric_atom_ids(atom_ids - excluded_atom_ids, ledger)
            )
        is_ambiguous_pending_gross = (
            pending_gross
            and not is_gross
            and not is_rate
            and not is_percentage
            and not has_discount_cue
            and not has_net_fee_source
            and _has_only_recognized_money_context(_row_text(row))
            and _has_non_percentage_numeric_evidence(atom_ids - excluded_atom_ids, ledger)
        )
        if is_ambiguous_pending_gross:
            component_bound_atom_ids.update(
                _non_percentage_numeric_atom_ids(atom_ids - excluded_atom_ids, ledger)
            )
            gross_seen = True
            gross_ambiguous = True
            gross_fee = None
            pending_gross = False
            diagnostics.append("unparsed_foreign_currency_fee_candidate")
            continue

        if is_rate:
            parsed_rate = _one_positive_decimal(atom_ids - excluded_atom_ids, ledger)
            if parsed_rate is not None and (
                not _has_valid_typed_decimal_context(
                    source_texts,
                    original_currency,
                    billing_currency,
                )
                or not _decimal_renderings_match(
                    source_texts,
                    parsed_rate[0],
                    percent_bound=False,
                )
            ):
                parsed_rate = None
            if rate_seen or parsed_rate is None:
                rate_ambiguous = True
                exchange_rate = None
                diagnostics.append("unparsed_exchange_rate_candidate")
            else:
                value, value_atom_ids = parsed_rate
                exchange_rate = ExtractedDecimal(value=value, evidence=evidence)
                claims.append(EvidenceClaim(SemanticOwner.EXCHANGE_RATE, value_atom_ids))
            rate_seen = True

        if is_percentage:
            parsed_percentage = _one_percent_bound_decimal(atom_ids, ledger)
            if parsed_percentage is not None and (
                not _has_valid_typed_decimal_context(
                    source_texts,
                    original_currency,
                    billing_currency,
                )
                or not _decimal_renderings_match(
                    source_texts,
                    parsed_percentage[0],
                    percent_bound=True,
                )
            ):
                parsed_percentage = None
            if percentage_ambiguous or parsed_percentage is None:
                percentage_ambiguous = True
                fee_percentage = None
                diagnostics.append("unparsed_foreign_currency_fee_percentage_candidate")
            else:
                value, percentage_candidate = parsed_percentage
                value_atom_ids = percentage_candidate.semantic_atom_ids
                if fee_percentage is None:
                    if percentage_seen:
                        percentage_ambiguous = True
                        diagnostics.append("unparsed_foreign_currency_fee_percentage_candidate")
                    else:
                        fee_percentage = ExtractedDecimal(value=value, evidence=evidence)
                        claims.append(
                            EvidenceClaim(SemanticOwner.FX_FEE_PERCENTAGE, value_atom_ids)
                        )
                        pending_gross = True
                elif fee_percentage.value != value:
                    percentage_ambiguous = True
                    fee_percentage = None
                    diagnostics.append("unparsed_foreign_currency_fee_percentage_candidate")
                else:
                    fee_percentage = ExtractedDecimal(
                        value=value,
                        evidence=tuple(dict.fromkeys((*fee_percentage.evidence, *evidence))),
                    )
                    for index, claim in enumerate(claims):
                        if claim.owner is SemanticOwner.FX_FEE_PERCENTAGE:
                            claims[index] = EvidenceClaim(
                                claim.owner,
                                claim.atom_ids | value_atom_ids,
                            )
                            break
                    pending_gross = True
            percentage_seen = True

        if has_net_fee_source:
            if pending_discount:
                discount_seen = True
                discount_ambiguous = True
                fee_discount = None
                diagnostics.append("unparsed_foreign_currency_fee_discount_candidate")
            parsed_net = row_money
            if (
                net_ambiguous
                or has_unbound_net_fee_modifier
                or has_conflicting_net_semantics
                or parsed_net is None
            ):
                net_ambiguous = True
                net_fee = None
                diagnostics.append("unparsed_foreign_currency_fee_candidate")
            else:
                amount, currency, value_atom_ids = parsed_net
                candidate = ExtractedMoney(
                    amount=amount,
                    currency=currency,
                    evidence=evidence,
                )
                if net_fee is None:
                    net_fee = candidate
                elif net_fee.amount != amount or net_fee.currency != currency:
                    net_ambiguous = True
                    net_fee = None
                    diagnostics.append("unparsed_foreign_currency_fee_candidate")
                else:
                    net_fee = _merge_equal_money(net_fee, candidate)
                claims.append(EvidenceClaim(SemanticOwner.NET_FX_FEE, value_atom_ids))
            pending_gross = False
            pending_discount = False
            continue

        if is_gross:
            parsed_gross = row_money
            if gross_seen or parsed_gross is None:
                gross_ambiguous = True
                gross_fee = None
                diagnostics.append("unparsed_foreign_currency_fee_candidate")
            else:
                amount, currency, value_atom_ids = parsed_gross
                gross_fee = ExtractedMoney(
                    amount=amount,
                    currency=currency,
                    evidence=evidence,
                )
                claims.append(EvidenceClaim(SemanticOwner.GROSS_FX_FEE, value_atom_ids))
            gross_seen = True
            pending_gross = False
            pending_discount = has_discount_cue
            continue

        if is_discount or (pending_discount and not is_rate and not is_percentage):
            parsed_discount = row_money
            if discount_seen or parsed_discount is None:
                discount_ambiguous = True
                fee_discount = None
                diagnostics.append("unparsed_foreign_currency_fee_discount_candidate")
            else:
                amount, currency, value_atom_ids = parsed_discount
                fee_discount = ExtractedMoney(
                    amount=amount,
                    currency=currency,
                    evidence=evidence,
                )
                claims.append(EvidenceClaim(SemanticOwner.FX_FEE_DISCOUNT, value_atom_ids))
            discount_seen = True
            pending_discount = False

    if pending_discount:
        discount_ambiguous = True
        diagnostics.append("unparsed_foreign_currency_fee_discount_candidate")

    if gross_fee is not None and fee_discount is not None:
        amount = exact_difference(gross_fee.amount, fee_discount.amount)
        if gross_fee.currency != fee_discount.currency or amount < 0:
            net_ambiguous = True
            net_fee = None
            diagnostics.append("inconsistent_foreign_currency_fee_derivation")
        elif not net_ambiguous:
            derived_net_fee = ExtractedMoney(
                amount=amount,
                currency=gross_fee.currency,
                evidence=tuple(dict.fromkeys((*gross_fee.evidence, *fee_discount.evidence))),
                derivation="gross_fee_minus_discount",
            )
            if net_fee is None:
                net_fee = derived_net_fee
            elif net_fee.amount != amount or net_fee.currency != gross_fee.currency:
                net_ambiguous = True
                net_fee = None
                diagnostics.append("inconsistent_foreign_currency_fee_derivation")
            else:
                net_fee = _merge_equal_money(net_fee, derived_net_fee)

    ambiguous_before_unowned_percentage = {
        owner
        for ambiguous, owner in (
            (rate_ambiguous, SemanticOwner.EXCHANGE_RATE),
            (percentage_ambiguous, SemanticOwner.FX_FEE_PERCENTAGE),
            (gross_ambiguous, SemanticOwner.GROSS_FX_FEE),
            (discount_ambiguous, SemanticOwner.FX_FEE_DISCOUNT),
            (net_ambiguous, SemanticOwner.NET_FX_FEE),
        )
        if ambiguous
    }
    accepted_before_unowned_percentage = frozenset(
        atom_id
        for claim in claims
        if claim.owner not in ambiguous_before_unowned_percentage
        for atom_id in claim.atom_ids
    )
    unowned_percentage_evidence = any(
        _has_bounded_numeric_context(source_texts, billing_currency)
        and bool(
            _percent_bound_numeric_atom_ids(
                _row_atom_ids(row, ledger) - excluded_atom_ids - accepted_before_unowned_percentage,
                ledger,
            )
        )
        for row, source_texts in zip(bounded_rows, bounded_source_texts, strict=True)
    )
    if unowned_percentage_evidence:
        percentage_ambiguous = True
        fee_percentage = None
        diagnostics.append("unparsed_foreign_currency_fee_percentage_candidate")

    ambiguous_owners = {
        owner
        for ambiguous, owner in (
            (rate_ambiguous, SemanticOwner.EXCHANGE_RATE),
            (percentage_ambiguous, SemanticOwner.FX_FEE_PERCENTAGE),
            (gross_ambiguous, SemanticOwner.GROSS_FX_FEE),
            (discount_ambiguous, SemanticOwner.FX_FEE_DISCOUNT),
            (net_ambiguous, SemanticOwner.NET_FX_FEE),
        )
        if ambiguous
    }
    accepted_atom_ids = frozenset(
        atom_id
        for claim in claims
        if claim.owner not in ambiguous_owners
        for atom_id in claim.atom_ids
    )
    unowned_monetary_evidence = any(
        _has_bounded_numeric_context(source_texts, billing_currency)
        and _has_non_percentage_numeric_evidence(
            _row_atom_ids(row, ledger)
            - excluded_atom_ids
            - accepted_atom_ids
            - component_bound_atom_ids,
            ledger,
        )
        for row, source_texts in zip(bounded_rows, bounded_source_texts, strict=True)
    )
    return _FxValues(
        exchange_rate=exchange_rate,
        fee_percentage=fee_percentage,
        gross_fee=gross_fee,
        fee_discount=fee_discount,
        net_fee=net_fee,
        claims=tuple(claim for claim in claims if claim.owner not in ambiguous_owners),
        diagnostics=tuple(dict.fromkeys(diagnostics)),
        ambiguous_owners=frozenset(ambiguous_owners),
        unowned_monetary_evidence=unowned_monetary_evidence,
    )


def _merge_equal_decimals(
    first: ExtractedDecimal | None,
    second: ExtractedDecimal | None,
) -> ExtractedDecimal | None:
    if first is None:
        return second
    if second is None:
        return first
    if first.value != second.value:
        return None
    return ExtractedDecimal(
        value=first.value,
        evidence=tuple(dict.fromkeys((*first.evidence, *second.evidence))),
    )


def _merge_equal_money(
    first: ExtractedMoney | None,
    second: ExtractedMoney | None,
) -> ExtractedMoney | None:
    if first is None:
        return second
    if second is None:
        return first
    if first.amount != second.amount or first.currency != second.currency:
        return None
    return ExtractedMoney(
        amount=first.amount,
        currency=first.currency,
        evidence=tuple(dict.fromkeys((*first.evidence, *second.evidence))),
        derivation=first.derivation,
    )


def _consolidate_claims(claims: Iterable[EvidenceClaim]) -> tuple[EvidenceClaim, ...]:
    atom_ids_by_owner: dict[SemanticOwner, set[int]] = {}
    owner_order: list[SemanticOwner] = []
    for claim in claims:
        if claim.owner not in atom_ids_by_owner:
            atom_ids_by_owner[claim.owner] = set()
            owner_order.append(claim.owner)
        atom_ids_by_owner[claim.owner].update(claim.atom_ids)
    return tuple(EvidenceClaim(owner, frozenset(atom_ids_by_owner[owner])) for owner in owner_order)


def _merge_values(table: _FxValues, continuation: _FxValues) -> _FxValues:
    rate_ambiguous = SemanticOwner.EXCHANGE_RATE in {
        *table.ambiguous_owners,
        *continuation.ambiguous_owners,
    }
    rate_conflict = (
        table.exchange_rate is not None
        and continuation.exchange_rate is not None
        and table.exchange_rate.value != continuation.exchange_rate.value
    )
    net_fee_conflict = (
        table.net_fee is not None
        and continuation.net_fee is not None
        and (
            table.net_fee.amount != continuation.net_fee.amount
            or table.net_fee.currency != continuation.net_fee.currency
        )
    )
    net_fee_ambiguous = SemanticOwner.NET_FX_FEE in {
        *table.ambiguous_owners,
        *continuation.ambiguous_owners,
    }
    merged_net_fee = (
        None
        if net_fee_ambiguous or net_fee_conflict
        else _merge_equal_money(table.net_fee, continuation.net_fee)
    )
    gross_net_conflict = (
        continuation.gross_fee is not None
        and merged_net_fee is not None
        and continuation.gross_fee.currency == merged_net_fee.currency
        and merged_net_fee.amount > continuation.gross_fee.amount
    )
    unowned_net_conflict = continuation.unowned_monetary_evidence and merged_net_fee is not None
    ambiguous_owners = {
        *table.ambiguous_owners,
        *continuation.ambiguous_owners,
    }
    ambiguous_owners.update(
        owner
        for conflict, owner in (
            (rate_ambiguous or rate_conflict, SemanticOwner.EXCHANGE_RATE),
            (
                net_fee_ambiguous or net_fee_conflict or gross_net_conflict or unowned_net_conflict,
                SemanticOwner.NET_FX_FEE,
            ),
        )
        if conflict
    )
    diagnostics = [*table.diagnostics, *continuation.diagnostics]
    if rate_conflict:
        diagnostics.append("unparsed_exchange_rate_candidate")
    if net_fee_conflict:
        diagnostics.append("inconsistent_foreign_currency_fee_derivation")
    if gross_net_conflict:
        diagnostics.append("inconsistent_foreign_currency_fee_derivation")
    if continuation.unowned_monetary_evidence:
        diagnostics.append("unparsed_foreign_currency_fee_candidate")
    claims = _consolidate_claims(
        claim
        for claim in (*table.claims, *continuation.claims)
        if claim.owner not in ambiguous_owners
    )
    return _FxValues(
        exchange_rate=(
            None
            if rate_ambiguous or rate_conflict
            else _merge_equal_decimals(table.exchange_rate, continuation.exchange_rate)
        ),
        fee_percentage=continuation.fee_percentage,
        gross_fee=continuation.gross_fee,
        fee_discount=continuation.fee_discount,
        net_fee=(None if SemanticOwner.NET_FX_FEE in ambiguous_owners else merged_net_fee),
        claims=claims,
        diagnostics=tuple(dict.fromkeys(diagnostics)),
        ambiguous_owners=frozenset(ambiguous_owners),
    )


def _finish_extraction(values: _FxValues) -> ForeignExchangeExtraction:
    details = (
        ForeignExchangeDetails(
            exchange_rate=values.exchange_rate,
            fee_percentage=values.fee_percentage,
            gross_fee=values.gross_fee,
            fee_discount=values.fee_discount,
            net_fee=values.net_fee,
        )
        if any(
            value is not None
            for value in (
                values.exchange_rate,
                values.fee_percentage,
                values.gross_fee,
                values.fee_discount,
                values.net_fee,
            )
        )
        else None
    )
    return ForeignExchangeExtraction(
        details=details,
        claims=values.claims,
        diagnostics=values.diagnostics,
    )


def extract_foreign_exchange(
    *,
    rows: Sequence[Row],
    region: TableRegion,
    ledger: EvidenceLedger,
    original_currency: str | None,
    billing_currency: str,
    excluded_atom_ids: frozenset[int] = frozenset(),
    original_amount: Decimal | None = None,
    billed_amount: Decimal | None = None,
) -> ForeignExchangeExtraction:
    """Extract unambiguous FX values from one proven foreign transaction row."""

    if original_currency is None or original_currency == billing_currency or not rows:
        return ForeignExchangeExtraction()
    table_values = _table_fx_values(
        rows[0],
        region,
        ledger,
        original_currency,
        billing_currency,
        excluded_atom_ids,
    )
    continuation_values = _continuation_fx_values(
        rows[1:],
        ledger,
        original_currency,
        billing_currency,
        excluded_atom_ids,
    )
    if (
        continuation_values.diagnostics
        and original_amount is not None
        and billed_amount is not None
        and (
            proven_values := _proven_positioned_fx_detail_block(
                rows[1:],
                region,
                ledger,
                original_currency,
                billing_currency,
                original_amount,
                billed_amount,
            )
        )
        is not None
    ):
        continuation_values = proven_values
    return _finish_extraction(_merge_values(table_values, continuation_values))


__all__ = ["ForeignExchangeExtraction", "extract_foreign_exchange"]
