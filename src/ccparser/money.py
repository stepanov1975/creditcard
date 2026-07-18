"""Strict shared lexical grammar for monetary values and currencies."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field


class AmountParseResult(BaseModel):
    """A monetary parse or explicit ambiguity without a guessed value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_text: str
    amount: Decimal | None = None
    currency: str | None = None
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


@dataclass(frozen=True)
class _LexicalAmount:
    value: Decimal | None
    explicit_currency: str | None
    currency: str | None
    diagnostics: tuple[str, ...]


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
        escaped = re.escape(marker).replace(r"\ ", r"\s+")
        result = re.sub(
            rf"(?<!\w){escaped}(?!\w)",
            " ",
            result,
            flags=re.IGNORECASE,
        )
    return result


def canonical_currency(value: str | None) -> str | None:
    """Return an ISO currency for a complete known code, symbol, or Hebrew alias."""

    if value is None:
        return None
    stripped = _normalized_text(value)
    if stripped in _CURRENCY_ALIASES:
        return _CURRENCY_ALIASES[stripped]
    normalized_phrase = _normalized_phrase(stripped).upper()
    return _CURRENCY_ALIASES.get(stripped.upper()) or _CURRENCY_ALIASES.get(normalized_phrase)


def currencies_in_text(text: str) -> tuple[str, ...]:
    """Return distinct known currencies occurring in text, in source order."""

    found: list[str] = []
    for match in _CURRENCY_PATTERN.finditer(text):
        currency = canonical_currency(match.group())
        if currency is not None and currency not in found:
            found.append(currency)
    return tuple(found)


def is_currency_shaped(text: str) -> bool:
    """Return whether the entire cell is one supported currency token."""

    return canonical_currency(text) is not None


def _validate_grouped_integer(value: str, separator: str) -> str | None:
    groups = value.split(separator)
    if not groups or not 1 <= len(groups[0]) <= 3 or not all(group.isdigit() for group in groups):
        return None
    if any(len(group) != 3 for group in groups[1:]):
        return None
    return "".join(groups)


def _canonical_number(text: str) -> tuple[str | None, str | None]:
    compact = text.strip()
    if not compact or re.search(r"[^\d.,'\s]", compact):
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


def _sign_and_number(text: str) -> tuple[str, bool, bool, str | None]:
    stripped = text.strip()
    has_open = "(" in stripped
    has_close = ")" in stripped
    parenthesized = (
        stripped.startswith("(")
        and stripped.endswith(")")
        and stripped.count("(") == 1
        and stripped.count(")") == 1
    )
    if (has_open or has_close) and not parenthesized:
        return stripped, False, False, "invalid_sign_syntax"
    core = stripped[1:-1].strip() if parenthesized else stripped
    sign_positions = tuple(index for index, char in enumerate(core) if char in "+-")
    if (parenthesized and sign_positions) or len(sign_positions) > 1:
        return core, False, False, "invalid_sign_syntax"
    negative = parenthesized
    positive = False
    if sign_positions:
        index = sign_positions[0]
        if index not in {0, len(core) - 1}:
            return core, False, False, "invalid_sign_syntax"
        sign = core[index]
        negative = sign == "-"
        positive = sign == "+"
        core = (core[:index] + core[index + 1 :]).strip()
    return core, negative, positive, None


def _parse_lexical(text: str, currency_hint: str | None) -> _LexicalAmount:
    raw_text = unicodedata.normalize("NFC", text)
    diagnostics: list[str] = []
    explicit_currencies = currencies_in_text(raw_text)
    hint = canonical_currency(currency_hint)
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
    without_labels = _remove_markers(raw_text, (*_CREDIT_MARKERS, *_CHARGE_MARKERS))
    without_currency = _CURRENCY_PATTERN.sub(" ", without_labels)
    numeric_text, negative_sign, positive_sign, sign_diagnostic = _sign_and_number(without_currency)
    if sign_diagnostic is not None:
        diagnostics.append(sign_diagnostic)
    if (negative_sign and charge_marker) or (positive_sign and credit_marker):
        diagnostics.append("conflicting_sign_marker")
    canonical, numeric_diagnostic = _canonical_number(numeric_text)
    if numeric_diagnostic is not None:
        diagnostics.append(numeric_diagnostic)

    value: Decimal | None = None
    if canonical is not None:
        try:
            unsigned = Decimal(canonical)
        except InvalidOperation:
            diagnostics.append("invalid_amount_text")
        else:
            value = unsigned.copy_negate() if negative_sign or credit_marker else unsigned
    return _LexicalAmount(
        value=value,
        explicit_currency=explicit_currency,
        currency=currency,
        diagnostics=tuple(dict.fromkeys(diagnostics)),
    )


def is_money_shaped(text: str) -> bool:
    """Return whether an entire cell is one strict monetary lexeme."""

    parsed = _parse_lexical(text, None)
    return parsed.value is not None and set(parsed.diagnostics) <= {"unknown_currency"}


def parse_amount(text: str, *, currency_hint: str | None = None) -> AmountParseResult:
    """Parse one complete unambiguous monetary lexeme exactly."""

    raw_text = unicodedata.normalize("NFC", text)
    parsed = _parse_lexical(raw_text, currency_hint)
    if parsed.diagnostics or parsed.value is None or parsed.currency is None:
        return AmountParseResult(
            raw_text=raw_text,
            currency=(
                parsed.currency if "conflicting_currency" not in parsed.diagnostics else None
            ),
            confidence=0.0,
            diagnostics=parsed.diagnostics,
        )
    return AmountParseResult(
        raw_text=raw_text,
        amount=parsed.value,
        currency=parsed.currency,
        confidence=1.0 if parsed.explicit_currency is not None else 0.95,
    )


__all__ = [
    "AmountParseResult",
    "canonical_currency",
    "currencies_in_text",
    "is_currency_shaped",
    "is_money_shaped",
    "parse_amount",
]
