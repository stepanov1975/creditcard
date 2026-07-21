from ccparser.text_tokens import contains_token_sequence, normalize_text, phrase_tokens


def test_text_tokenization_is_nfc_casefolded_and_boundary_aware() -> None:
    assert normalize_text("  Cafe\u0301   SHOP ") == "Café SHOP"
    assert phrase_tokens("Foreign-currency FEE") == ("foreign", "currency", "fee")
    assert contains_token_sequence("foreign currency fee", ("currency fee",))
    assert not contains_token_sequence("Coffee amount", ("fee",))
    assert not contains_token_sequence("Corporate date", ("rate",))


def test_acronym_quote_policy_is_explicit() -> None:
    assert phrase_tokens('סה"כ', ignore_acronym_quotes=True) == ("סהכ",)
    assert phrase_tokens('סה"כ') == ("סה", "כ")
