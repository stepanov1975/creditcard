# Bounded Lexical Memoization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reuse repeated phrase tokenization and monetary lexical parsing so conversion performs less pure Python work without changing parser behavior or canonical output.

**Architecture:** Keep both existing interfaces and algorithms intact, inserting bounded process-local LRU caches only at pure functions with immutable results. `phrase_tokens()` delegates to a private cache keyed by text and acronym-quote policy; `_parse_lexical()` is cached by text and currency hint. Existing callers, worker scheduling, OCR behavior, and serialization remain unchanged.

**Tech Stack:** Python 3.13, `functools.lru_cache`, Pydantic, `Decimal`, pytest, Ruff, mypy.

## Global Constraints

- Use Python 3.13 and the repository virtual environment at `.venv`.
- Follow red-green-refactor for every production change and capture the expected failing output before implementation.
- The phrase-token cache limit is exactly 8,192 entries; its key includes the complete text and `ignore_acronym_quotes`.
- The monetary lexical cache limit is exactly 4,096 entries; its key includes the complete text and optional currency hint.
- Preserve normalization, token boundaries, Hebrew handling, amount parsing, diagnostics, `Decimal` values, extraction, discovery, reconciliation, JSON, and CSV behavior exactly.
- Return only immutable cached values and keep all cache state bounded, process-local, and memory-only.
- Do not change worker selection, OCR behavior, public signatures, filenames, paths, document policies, or corpus-gate behavior.
- Do not add filename-, path-, hash-, date-, merchant-, amount-, total-, or document-specific branches.
- Before every commit run `.venv/bin/ruff format --check .`, `.venv/bin/ruff check .`, `.venv/bin/mypy src`, and `.venv/bin/pytest -q`.
- Never claim corpus acceptance without a successful formal private `verify` run from the clean reviewed commit with protected pins and `performance_checked=true`.

---

### Task 1: Cache phrase tokenization by complete policy input

**Files:**
- Modify: `tests/test_text_tokens.py`
- Modify: `src/ccparser/text_tokens.py`

**Interfaces:**
- Consumes: `normalize_text(text: str) -> str` and the existing `TokenSequence` alias.
- Produces: unchanged `phrase_tokens(text: str, *, ignore_acronym_quotes: bool = False) -> TokenSequence` backed by an 8,192-entry private LRU cache.
- Preserves: `compile_token_phrases()`, string-wrapper short-circuiting, explicit acronym-quote behavior, Unicode/control handling, token ordering, and module exports.

- [ ] **Step 1: Add a focused repeated-work test**

Add this test after `test_acronym_quote_policy_is_explicit()` in `tests/test_text_tokens.py`:

```python
def test_phrase_tokens_reuses_each_policy_specific_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = 'Memoized A"B 90210'
    calls: list[str] = []
    original = text_tokens_module.normalize_text

    def counting_normalize_text(text: str) -> str:
        calls.append(text)
        return original(text)

    monkeypatch.setattr(text_tokens_module, "normalize_text", counting_normalize_text)

    assert phrase_tokens(source) == ("memoized", "a", "b", "90210")
    assert phrase_tokens(source) == ("memoized", "a", "b", "90210")
    assert phrase_tokens(source, ignore_acronym_quotes=True) == (
        "memoized",
        "ab",
        "90210",
    )
    assert phrase_tokens(source, ignore_acronym_quotes=True) == (
        "memoized",
        "ab",
        "90210",
    )
    assert calls == [source, source]
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_text_tokens.py::test_phrase_tokens_reuses_each_policy_specific_result
```

Expected: FAIL because `normalize_text()` is called four times instead of once per policy-specific key.

- [ ] **Step 3: Add the bounded private token cache**

In `src/ccparser/text_tokens.py`, import `lru_cache`:

```python
from functools import lru_cache
```

After the token type aliases, add the cache limit:

```python
_PHRASE_TOKEN_CACHE_SIZE = 8_192
```

Replace the existing `phrase_tokens()` body with a private cached implementation and unchanged public wrapper:

```python
@lru_cache(maxsize=_PHRASE_TOKEN_CACHE_SIZE)
def _cached_phrase_tokens(
    text: str,
    ignore_acronym_quotes: bool,
) -> TokenSequence:
    normalized = normalize_text(text).casefold()
    canonical: list[str] = []
    for index, char in enumerate(normalized):
        if char in TOKEN_JOIN_CONTROLS:
            continue
        between_letters = (
            0 < index < len(normalized) - 1
            and normalized[index - 1].isalpha()
            and normalized[index + 1].isalpha()
        )
        if ignore_acronym_quotes and char in ACRONYM_QUOTES and between_letters:
            continue
        canonical.append(char if char.isalnum() else " ")
    return tuple("".join(canonical).split())


def phrase_tokens(
    text: str,
    *,
    ignore_acronym_quotes: bool = False,
) -> TokenSequence:
    return _cached_phrase_tokens(text, ignore_acronym_quotes)
```

- [ ] **Step 4: Verify GREEN and the lexical behavior boundary**

Run:

```bash
.venv/bin/pytest -q tests/test_text_tokens.py
.venv/bin/ruff check src/ccparser/text_tokens.py tests/test_text_tokens.py
.venv/bin/mypy src/ccparser/text_tokens.py
```

Expected: all commands pass; repeated calls hit the cache while every existing lexical policy remains green.

- [ ] **Step 5: Run repository verification and commit**

Run:

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
git add src/ccparser/text_tokens.py tests/test_text_tokens.py
git commit -m "perf: cache bounded phrase tokenization"
```

Expected: all verification commands pass and the commit contains only Task 1 files.

### Task 2: Cache monetary lexical parsing by text and hint

**Files:**
- Modify: `tests/test_normalize.py`
- Modify: `src/ccparser/money.py`

**Interfaces:**
- Consumes: existing `_parse_lexical(text: str, currency_hint: str | None) -> _LexicalAmount` inputs and frozen return type.
- Produces: the same private function with a 4,096-entry LRU cache keyed by both arguments.
- Preserves: all public `is_money_shaped()`, `parse_amount()`, credit/charge marker, sign, grouping, currency, confidence, diagnostic, and `Decimal` behavior.

- [ ] **Step 1: Add a focused text-and-hint cache-key test**

Add `import ccparser.money as money_module` beside the other module imports in `tests/test_normalize.py`, then add this test after `test_parse_amount_supports_structurally_unambiguous_formats_and_credit_markers()`:

```python
def test_monetary_lexical_cache_reuses_text_and_separates_currency_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = "987654321.09"
    calls: list[str] = []
    original = money_module._canonical_number

    def counting_canonical_number(text: str) -> tuple[str | None, str | None]:
        calls.append(text)
        return original(text)

    monkeypatch.setattr(money_module, "_canonical_number", counting_canonical_number)

    usd_first = money_module.parse_amount(raw, currency_hint="USD")
    usd_second = money_module.parse_amount(raw, currency_hint="USD")
    eur_first = money_module.parse_amount(raw, currency_hint="EUR")
    eur_second = money_module.parse_amount(raw, currency_hint="EUR")

    assert (usd_first.amount, usd_first.currency) == (Decimal(raw), "USD")
    assert usd_second == usd_first
    assert (eur_first.amount, eur_first.currency) == (Decimal(raw), "EUR")
    assert eur_second == eur_first
    assert calls == [raw, raw]
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/test_normalize.py::test_monetary_lexical_cache_reuses_text_and_separates_currency_hints
```

Expected: FAIL because `_canonical_number()` is called four times instead of once for each distinct hint.

- [ ] **Step 3: Add the bounded monetary lexical cache**

In `src/ccparser/money.py`, import `lru_cache`:

```python
from functools import lru_cache
```

Add the cache limit beside the fixed marker policy:

```python
_LEXICAL_AMOUNT_CACHE_SIZE = 4_096
```

Decorate the existing pure parser without changing its body or signature:

```python
@lru_cache(maxsize=_LEXICAL_AMOUNT_CACHE_SIZE)
def _parse_lexical(text: str, currency_hint: str | None) -> _LexicalAmount:
```

- [ ] **Step 4: Verify GREEN and the amount behavior boundary**

Run:

```bash
.venv/bin/pytest -q tests/test_normalize.py -k 'parse_amount or currency_detection'
.venv/bin/pytest -q tests/test_text_tokens.py tests/test_fx.py tests/test_normalization_fields.py
.venv/bin/ruff check src/ccparser/money.py tests/test_normalize.py
.venv/bin/mypy src/ccparser/money.py
```

Expected: all commands pass; same text/hint pairs reuse the frozen lexical result, distinct hints remain independent, and financial outputs are unchanged.

- [ ] **Step 5: Run repository verification and commit**

Run:

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
git add src/ccparser/money.py tests/test_normalize.py
git commit -m "perf: cache bounded monetary lexing"
```

Expected: all verification commands pass and the commit contains only Task 2 files.

## Final verification

After both reviewed task commits:

1. Rerun the ignored representative profiling harness from the candidate source tree and require value-equal discovery and normalization results.
2. Compare pre-change and post-change stage timings without adding private inputs or outputs to Git.
3. Run all four required tracked gates again from the final candidate.
4. Confirm the worktree contains no debug instrumentation or tracked private data.
5. Report the change as not corpus-verified unless the formal protected private gate succeeds from the final clean committed SHA.
