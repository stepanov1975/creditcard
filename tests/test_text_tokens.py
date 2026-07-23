from collections.abc import Iterator

import pytest

import ccparser.text_tokens as text_tokens_module
from ccparser.text_tokens import (
    TokenSequence,
    compile_token_phrases,
    contains_compiled_token_sequence,
    contains_token_sequence,
    normalize_text,
    phrase_tokens,
)


def test_text_tokenization_is_nfc_casefolded_and_boundary_aware() -> None:
    assert normalize_text("  Cafe\u0301   SHOP ") == "Café SHOP"
    assert phrase_tokens("Foreign-currency FEE") == ("foreign", "currency", "fee")
    assert contains_token_sequence("foreign currency fee", ("currency fee",))
    assert not contains_token_sequence("Coffee amount", ("fee",))
    assert not contains_token_sequence("Corporate date", ("rate",))


def test_normalize_text_ignores_format_controls_at_token_boundaries() -> None:
    assert normalize_text("\u2066  Foreign currency  \u2069") == "Foreign currency"


@pytest.mark.parametrize("format_control", ("\u061c", "\u200e", "\ufeff"))
def test_normalize_text_ignores_format_controls_without_losing_content(
    format_control: str,
) -> None:
    assert normalize_text(f"  Con{format_control}verted  ₪  12.34  ") == "Converted ₪ 12.34"


def test_normalize_text_preserves_zero_width_word_boundary() -> None:
    assert normalize_text("foreign\u200bcurrency") == "foreign currency"
    assert normalize_text("25/0\u200b6/26") == "25/0 6/26"


@pytest.mark.parametrize("format_control", ("\u00ad", "\u2060"))
def test_normalize_text_ignores_explicit_lexical_layout_controls(
    format_control: str,
) -> None:
    assert normalize_text(f"Con{format_control}verted") == "Converted"


@pytest.mark.parametrize("operator", ("\u2061", "\u2062", "\u2063", "\u2064"))
def test_normalize_text_preserves_invisible_mathematical_operators(operator: str) -> None:
    assert normalize_text(f"2{operator}5") == f"2{operator}5"
    assert normalize_text(f"2{operator}5") != "25"


def test_normalize_text_preserves_joiners_but_phrase_tokens_ignore_them() -> None:
    assert normalize_text("Con\u200dverted") == "Con\u200dverted"
    assert phrase_tokens("Con\u200dverted") == ("converted",)


def test_normalize_text_preserves_unknown_format_controls_by_default() -> None:
    assert normalize_text("a\u0600b") == "a\u0600b"


def test_phrase_tokens_do_not_join_words_across_zero_width_space() -> None:
    assert phrase_tokens("foreign\u200bcurrency fee") == ("foreign", "currency", "fee")


def test_acronym_quote_policy_is_explicit() -> None:
    assert phrase_tokens('סה"כ', ignore_acronym_quotes=True) == ("סהכ",)
    assert phrase_tokens('סה"כ') == ("סה", "כ")


def test_hebrew_clitic_prefix_is_an_explicit_first_token_policy() -> None:
    assert contains_token_sequence(
        "בשער המרה",
        ("שער המרה",),
        allow_hebrew_clitic_prefix=True,
    )
    assert not contains_token_sequence("בשער המרה", ("שער המרה",))
    assert not contains_token_sequence(
        "מילהשאינהשער המרה",
        ("שער המרה",),
        allow_hebrew_clitic_prefix=True,
    )
    assert not contains_token_sequence(
        "בשער להמרה",
        ("שער המרה",),
        allow_hebrew_clitic_prefix=True,
    )
    assert not contains_token_sequence(
        "צשער המרה",
        ("שער המרה",),
        allow_hebrew_clitic_prefix=True,
    )
    assert not contains_token_sequence(
        "ובשער המרה",
        ("שער המרה",),
        allow_hebrew_clitic_prefix=True,
    )
    assert not contains_token_sequence(
        "corporate date",
        ("rate",),
        allow_hebrew_clitic_prefix=True,
    )


def test_compiled_phrases_filter_empty_candidates_and_preserve_order() -> None:
    assert compile_token_phrases(("", "currency fee", "---", "exchange rate")) == (
        ("currency", "fee"),
        ("exchange", "rate"),
    )


def test_compiled_matcher_matches_string_wrapper_policies() -> None:
    phrases = ("currency fee", "שער המרה")
    compiled = compile_token_phrases(phrases)

    assert contains_compiled_token_sequence(phrase_tokens("foreign currency fee"), compiled)
    assert contains_compiled_token_sequence(
        phrase_tokens("בשער המרה"),
        compiled,
        allow_hebrew_clitic_prefix=True,
    )
    assert not contains_compiled_token_sequence(phrase_tokens("בשער המרה"), compiled)
    assert not contains_compiled_token_sequence(phrase_tokens("Coffee amount"), compiled)


@pytest.mark.parametrize(
    "quote",
    ('"', "'", "\u2018", "\u2019", "\u201c", "\u201d", "\u05f3", "\u05f4"),
)
def test_compiled_matcher_preserves_all_acronym_quote_code_points(
    quote: str,
) -> None:
    phrases = (f"סה{quote}כ",)
    compiled = compile_token_phrases(phrases, ignore_acronym_quotes=True)
    source = phrase_tokens("סהכ", ignore_acronym_quotes=True)

    assert contains_compiled_token_sequence(source, compiled)
    assert contains_token_sequence("סהכ", phrases, ignore_acronym_quotes=True)
    assert not contains_token_sequence("סהכ", phrases)


def test_compiled_matcher_preserves_single_token_boundaries() -> None:
    phrases = ("fee", "rate")
    compiled = compile_token_phrases(phrases)

    for text in ("Coffee amount", "Corporate date"):
        assert not contains_compiled_token_sequence(phrase_tokens(text), compiled)
        assert not contains_token_sequence(text, phrases)


def test_compiled_matcher_performs_no_tokenization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = phrase_tokens("foreign currency fee")
    compiled = compile_token_phrases(("currency fee", "exchange rate"))
    calls: list[str] = []
    original = text_tokens_module.phrase_tokens

    def counting_phrase_tokens(
        text: str,
        *,
        ignore_acronym_quotes: bool = False,
    ) -> TokenSequence:
        calls.append(text)
        return original(text, ignore_acronym_quotes=ignore_acronym_quotes)

    monkeypatch.setattr(text_tokens_module, "phrase_tokens", counting_phrase_tokens)

    assert contains_compiled_token_sequence(source, compiled)
    assert calls == []


def test_string_wrapper_stops_consuming_phrases_after_the_first_match() -> None:
    def guarded_phrases() -> Iterator[str]:
        yield "fee"
        raise AssertionError("phrases after a match must not be consumed")

    assert contains_token_sequence("foreign currency fee", guarded_phrases())
