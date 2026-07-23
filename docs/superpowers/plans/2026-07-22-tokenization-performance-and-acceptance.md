# Tokenization Performance and Corpus Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove repeated static-vocabulary tokenization from header and discovery hot paths, prove the optimization deterministically, and accept the repaired parser only after clean-revision corpus record and verification runs reconcile all 104 retained documents.

**Architecture:** `text_tokens.py` exposes immutable compiled phrase tuples and a matcher that operates on pre-tokenized source text. Column inference compiles header policy at module construction and tokenizes each observed header once; discovery does the same for its fixed marker sets and reuses each cell's token tuple. Unit tests enforce tokenization call counts, a same-process microbenchmark supplies diagnostic evidence, and `verify-corpus` remains the authoritative correctness, determinism, quarantine, provenance, and same-toolchain runtime gate.

**Tech Stack:** Python 3.13, typed tuple aliases, Unicode NFC/casefold normalization, pytest 9, standard-library `timeit`, Ruff, mypy, Typer corpus gate.

## Global Constraints

- Use Python 3.13 and `/root/creditcard/.venv`.
- Follow red-green-refactor for every production behavior.
- Preserve exact token-boundary behavior, acronym-quote policy, and the explicit Hebrew first-token clitic option from the strict extraction recovery plan.
- Do not add filename-, path-, hash-, document-, issuer-, merchant-, date-, amount-, total-, or corpus-index-specific behavior.
- Do not weaken reconciliation, ambiguity, evidence, provenance, quarantine, or deterministic-output checks.
- Keep corpus inputs, outputs, hashes, manifests, timings, and derived financial data private and out of Git.
- Do not change files outside `/root/creditcard`.
- Before any test or command that may use system temporary storage, run `export TMPDIR="$PWD/.superpowers/private/tmp"` and `mkdir -p "$TMPDIR"`; every temporary file must stay inside this worktree.
- Timing measurements are diagnostic; deterministic call-count tests and the same-toolchain corpus runtime tolerance are the pass/fail controls.

## File Structure

- Modify `src/ccparser/text_tokens.py`: define compiled-token aliases, phrase compilation, and matching over pre-tokenized input.
- Modify `tests/test_text_tokens.py`: prove wrapper parity, empty-candidate filtering, clitic preservation, and zero tokenization during compiled matching.
- Modify `src/ccparser/layout/columns.py`: compile static header terms once and operate on one tokenized representation per observed header.
- Modify `tests/layout/test_columns.py`: prove `_header_scores()` tokenization calls equal observed-header count even when compiled vocabulary grows.
- Modify `src/ccparser/discovery.py`: compile fixed discovery marker sets once and reuse tokenized cell text in total-marker signatures.
- Modify `tests/test_discovery.py`: prove total-marker signatures tokenize each source cell once while preserving compact Hebrew aliases.
- Use `.superpowers/private/tokenization-benchmark/`: ignored before/after microbenchmark output.
- Use `.superpowers/private/corpus-membership.json`, a unique ignored
  `.superpowers/private/corpus-candidate.*/baseline.json` promotion candidate,
  and unique ignored `.superpowers/private/corpus-record.*` /
  `.superpowers/private/corpus-verify.*` work directories for private final
  acceptance state. Verify the reviewed candidate only with its separately
  protected `APPROVED_CORPUS_BASELINE_SHA256` pin.

---

### Task 1: Add the compiled token API without changing matching semantics

**Files:**
- Modify: `src/ccparser/text_tokens.py`
- Modify: `tests/test_text_tokens.py`

**Interfaces:**
- Consumes: `phrase_tokens(text: str, *, ignore_acronym_quotes: bool = False) -> TokenSequence` and the strict-recovery `_first_token_matches()` policy.
- Produces: `TokenSequence`, `CompiledTokenPhrases`, `compile_token_phrases()`, and `contains_compiled_token_sequence()`.
- Preserves: `contains_token_sequence()` as the string-based compatibility wrapper, including `allow_hebrew_clitic_prefix`.

- [ ] **Step 1: Add failing compiled-API tests**

Replace the import at the top of `tests/test_text_tokens.py` and append these tests:

```python
import ccparser.text_tokens as text_tokens_module
from ccparser.text_tokens import (
    TokenSequence,
    compile_token_phrases,
    contains_compiled_token_sequence,
    contains_token_sequence,
    normalize_text,
    phrase_tokens,
)


def test_compiled_phrases_filter_empty_candidates_and_preserve_order() -> None:
    assert compile_token_phrases(("", "currency fee", "---", "exchange rate")) == (
        ("currency", "fee"),
        ("exchange", "rate"),
    )


def test_compiled_matcher_matches_string_wrapper_policies() -> None:
    phrases = ("currency fee", "שער המרה")
    compiled = compile_token_phrases(phrases)

    assert contains_compiled_token_sequence(
        phrase_tokens("foreign currency fee"), compiled
    )
    assert contains_compiled_token_sequence(
        phrase_tokens("בשער המרה"),
        compiled,
        allow_hebrew_clitic_prefix=True,
    )
    assert not contains_compiled_token_sequence(
        phrase_tokens("בשער המרה"), compiled
    )
    assert not contains_compiled_token_sequence(
        phrase_tokens("Coffee amount"), compiled
    )


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
```

Add `import pytest` because the new test uses `pytest.MonkeyPatch`.

- [ ] **Step 2: Run the focused tests and confirm the API is absent**

Run:

```bash
.venv/bin/pytest -q tests/test_text_tokens.py
```

Expected: collection fails because `TokenSequence`, `compile_token_phrases`, and `contains_compiled_token_sequence` are not defined.

- [ ] **Step 3: Implement immutable compilation and compiled matching**

In `src/ccparser/text_tokens.py`, add the aliases after `ACRONYM_QUOTES`, retain the strict-recovery `_first_token_matches()` helper, and replace the matching implementation with:

```python
type TokenSequence = tuple[str, ...]
type CompiledTokenPhrases = tuple[TokenSequence, ...]


def compile_token_phrases(
    phrases: Iterable[str],
    *,
    ignore_acronym_quotes: bool = False,
) -> CompiledTokenPhrases:
    compiled: list[TokenSequence] = []
    for phrase in phrases:
        candidate = phrase_tokens(
            phrase,
            ignore_acronym_quotes=ignore_acronym_quotes,
        )
        if candidate:
            compiled.append(candidate)
    return tuple(compiled)


def _token_window_matches(
    window: TokenSequence,
    candidate: TokenSequence,
    *,
    allow_hebrew_clitic_prefix: bool,
) -> bool:
    return (
        len(window) == len(candidate)
        and _first_token_matches(
            window[0],
            candidate[0],
            allow_hebrew_clitic_prefix=allow_hebrew_clitic_prefix,
        )
        and window[1:] == candidate[1:]
    )


def contains_compiled_token_sequence(
    tokens: TokenSequence,
    phrases: CompiledTokenPhrases,
    *,
    allow_hebrew_clitic_prefix: bool = False,
) -> bool:
    return any(
        _token_window_matches(
            tokens[index : index + len(candidate)],
            candidate,
            allow_hebrew_clitic_prefix=allow_hebrew_clitic_prefix,
        )
        for candidate in phrases
        if candidate
        for index in range(len(tokens) - len(candidate) + 1)
    )


def contains_token_sequence(
    text: str,
    phrases: Iterable[str],
    *,
    ignore_acronym_quotes: bool = False,
    allow_hebrew_clitic_prefix: bool = False,
) -> bool:
    tokens = phrase_tokens(text, ignore_acronym_quotes=ignore_acronym_quotes)
    compiled = compile_token_phrases(
        phrases,
        ignore_acronym_quotes=ignore_acronym_quotes,
    )
    return contains_compiled_token_sequence(
        tokens,
        compiled,
        allow_hebrew_clitic_prefix=allow_hebrew_clitic_prefix,
    )
```

Set the module export list exactly to:

```python
__all__ = [
    "CompiledTokenPhrases",
    "TokenSequence",
    "compile_token_phrases",
    "contains_compiled_token_sequence",
    "contains_token_sequence",
    "normalize_text",
    "phrase_tokens",
]
```

- [ ] **Step 4: Run focused lexical and FX cue tests**

Run:

```bash
.venv/bin/ruff format src/ccparser/text_tokens.py tests/test_text_tokens.py
.venv/bin/pytest -q tests/test_text_tokens.py tests/test_fx.py -k 'token or cue or clitic or prefix or substring'
.venv/bin/ruff check src/ccparser/text_tokens.py tests/test_text_tokens.py
.venv/bin/mypy src/ccparser/text_tokens.py
```

Expected: all commands pass; the string wrapper retains exact boundaries and opt-in Hebrew clitic behavior.

- [ ] **Step 5: Commit the compiled-token contract**

```bash
git add src/ccparser/text_tokens.py tests/test_text_tokens.py
git commit -m "perf: add compiled token phrase matching"
```

### Task 2: Tokenize header policy once and each observed header once

**Files:**
- Modify: `src/ccparser/layout/columns.py:18-160,368-505,746-920`
- Modify: `tests/layout/test_columns.py`
- Private output: `.superpowers/private/tokenization-benchmark/header-before.txt`
- Private output: `.superpowers/private/tokenization-benchmark/header-after.txt`

**Interfaces:**
- Consumes: `TokenSequence`, `CompiledTokenPhrases`, `compile_token_phrases()`, `contains_compiled_token_sequence()`.
- Produces: immutable `_TokenizedHeader`, module-compiled header vocabularies, and `_header_scores()` whose calls to `phrase_tokens()` equal the number of observed header strings.
- Preserves: all `ColumnRole` scores, exact/partial score values, compact-Hebrew matching, semantic-family disambiguation, and public `infer_column_roles()` behavior.

- [ ] **Step 1: Add the deterministic vocabulary-independent call-count test**

Add `import ccparser.layout.columns as columns_module` to `tests/layout/test_columns.py`, then add:

```python
def test_header_scores_tokenize_each_observed_header_once_independent_of_vocabulary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extra_terms = tuple(
        columns_module._tokenized_header(f"synthetic header term {index}")
        for index in range(200)
    )
    expanded = dict(columns_module._COMPILED_HEADER_VOCABULARY)
    expanded[ColumnRole.DESCRIPTION] = (
        *expanded[ColumnRole.DESCRIPTION],
        *extra_terms,
    )
    monkeypatch.setattr(columns_module, "_COMPILED_HEADER_VOCABULARY", expanded)

    calls: list[str] = []
    original = columns_module.phrase_tokens

    def counting_phrase_tokens(text: str) -> tuple[str, ...]:
        calls.append(text)
        return original(text)

    monkeypatch.setattr(columns_module, "phrase_tokens", counting_phrase_tokens)
    headers = ("Original amount", "Billed amount", "Exchange rate")

    scores = columns_module._header_scores(headers)

    assert calls == list(headers)
    assert scores[ColumnRole.ORIGINAL_AMOUNT] == 1.0
    assert scores[ColumnRole.AMOUNT] == 1.0
    assert scores[ColumnRole.EXCHANGE_RATE] == 1.0
```

- [ ] **Step 2: Confirm the current implementation retokenizes vocabulary terms**

Run:

```bash
.venv/bin/pytest -q tests/layout/test_columns.py::test_header_scores_tokenize_each_observed_header_once_independent_of_vocabulary
```

Expected: fail before the new private types exist, or fail because tokenization calls contain static vocabulary terms in addition to the three observed headers.

- [ ] **Step 3: Capture the pre-change same-process microbenchmark privately**

Run:

```bash
mkdir -p .superpowers/private/tokenization-benchmark
PYTHONPATH=src .venv/bin/python -m timeit -r 7 -n 2000 \
  -s 'from ccparser.layout.columns import _header_scores; headers=("Original amount", "Billed amount", "Exchange rate", "תאריך המרה")' \
  '_header_scores(headers)' \
  > .superpowers/private/tokenization-benchmark/header-before.txt
```

Expected: exit 0. The timing file remains ignored and is used only as local diagnostic evidence.

- [ ] **Step 4: Add one immutable representation for observed and static header text**

Import `dataclass` and the compiled-token API, then add this code before the compiled constants:

```python
from dataclasses import dataclass

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
```

After the final raw header-policy constant, compile every static term set once:

```python
_COMPILED_HEADER_VOCABULARY = {
    role: _compile_header_terms(terms)
    for role, terms in _HEADER_VOCABULARY.items()
}
_COMPILED_DESCRIPTION_NAME_HEADER_TERMS = _compile_header_terms(
    _DESCRIPTION_NAME_HEADER_TERMS
)
_COMPILED_GENERIC_AMOUNT_HEADER_TERMS = _compile_header_terms(
    _GENERIC_AMOUNT_HEADER_TERMS
)
_COMPILED_AUXILIARY_AMOUNT_MODIFIERS = _compile_header_terms(
    _AUXILIARY_AMOUNT_MODIFIERS
)
_COMPILED_BILLING_AMOUNT_MODIFIERS = _compile_header_terms(
    _BILLING_AMOUNT_MODIFIERS
)
_COMPILED_ORIGINAL_AMOUNT_MODIFIERS = _compile_header_terms(
    _ORIGINAL_AMOUNT_MODIFIERS
)
_COMPILED_EXCHANGE_RATE_HEADER_TERMS = _compile_header_terms(
    _EXCHANGE_RATE_HEADER_TERMS
)
_COMPILED_CONVERSION_DATE_HEADER_TERMS = _compile_header_terms(
    _CONVERSION_DATE_HEADER_TERMS
)
```

- [ ] **Step 5: Replace hot matching with tuple-only helpers**

Replace `_normalized_header()`, `_contains_token_phrase()`, `_header_match_score()`, and `_contains_header_concept()` with:

```python
def _normalized_header(text: str) -> str:
    return _tokenized_header(text).normalized


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


def _contains_header_concept(
    text: _TokenizedHeader,
    terms: tuple[_TokenizedHeader, ...],
) -> bool:
    return any(
        contains_compiled_token_sequence(text.tokens, (term.tokens,))
        or term.compact in text.compact
        for term in terms
    )
```

The existing `_is_hebrew_phrase()` is no longer called and must be removed.

- [ ] **Step 6: Update `_header_scores()` to tokenize an observed string once**

Use this complete implementation:

```python
def _header_scores(texts: Sequence[str]) -> dict[ColumnRole, float]:
    scores: dict[ColumnRole, float] = {}
    explicit_description_name = False
    for raw_text in texts:
        text = _tokenized_header(raw_text)
        composed_roles: set[ColumnRole] = set()
        if _contains_header_concept(
            text, _COMPILED_DESCRIPTION_NAME_HEADER_TERMS
        ):
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
            if len(exact_roles) == 1
            and next(iter(exact_roles)) not in _GENERIC_FAMILY_ROLES
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
        role
        for role, score in scores.items()
        if score == 1.0 and role not in _GENERIC_FAMILY_ROLES
    )
    if len(exact_specific_roles) == 1:
        specific_role = exact_specific_roles[0]
        scores = {
            role: score
            for role, score in scores.items()
            if not (
                role in _GENERIC_FAMILY_ROLES
                and _same_semantic_family(specific_role, role)
            )
        }
    return scores
```

- [ ] **Step 7: Convert cold header-policy call sites to the same compiled terms**

Add these predicates next to `_contains_header_concept()`:

```python
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
        and not _contains_header_concept(
            header, _COMPILED_AUXILIARY_AMOUNT_MODIFIERS
        )
        and not _contains_header_concept(header, _COMPILED_ORIGINAL_AMOUNT_MODIFIERS)
    )


def _is_unqualified_generic_amount_header(text: str) -> bool:
    header = _tokenized_header(text)
    return (
        _contains_header_concept(header, _COMPILED_GENERIC_AMOUNT_HEADER_TERMS)
        and not _contains_header_concept(header, _COMPILED_BILLING_AMOUNT_MODIFIERS)
        and not _contains_header_concept(
            header, _COMPILED_AUXILIARY_AMOUNT_MODIFIERS
        )
        and not _contains_header_concept(header, _COMPILED_ORIGINAL_AMOUNT_MODIFIERS)
    )
```

Apply these exact substitutions in the four downstream selectors:

```python
# explicit_billed_amount_column()
if any(_is_explicit_billed_amount_header(text) for text in texts):
    candidates.append(column)

# _disambiguate_qualified_original_amount(), billed_columns comprehension
_has_header_concept(text, _COMPILED_BILLING_AMOUNT_MODIFIERS)

# _disambiguate_qualified_original_amount(), qualified comprehension
_has_header_concept(text, _COMPILED_ORIGINAL_AMOUNT_MODIFIERS)

# _disambiguate_qualified_original_amount(), intermediate guard
if not any(_is_unqualified_generic_amount_header(text) for text in intermediate_texts):
    return tuple(columns)

# _disambiguate_generic_original_peer(), peer guard
if not any(_is_unqualified_generic_amount_header(text) for text in peer_texts):
    return tuple(columns)
```

No raw `_HEADER_VOCABULARY` or raw modifier set may be passed into a runtime phrase matcher after this step.

- [ ] **Step 8: Run focused tests, capture the post-change benchmark, and compare**

Run:

```bash
.venv/bin/ruff format src/ccparser/layout/columns.py tests/layout/test_columns.py
.venv/bin/pytest -q tests/layout/test_columns.py tests/layout/test_regions.py tests/test_discovery.py
PYTHONPATH=src .venv/bin/python -m timeit -r 7 -n 2000 \
  -s 'from ccparser.layout.columns import _header_scores; headers=("Original amount", "Billed amount", "Exchange rate", "תאריך המרה")' \
  '_header_scores(headers)' \
  > .superpowers/private/tokenization-benchmark/header-after.txt
.venv/bin/ruff check src/ccparser/layout/columns.py tests/layout/test_columns.py
.venv/bin/mypy src/ccparser/layout/columns.py
```

Expected: all quality commands pass; the deterministic test records exactly three calls. Inspect both private timing files with:

```bash
sed -n '1,5p' .superpowers/private/tokenization-benchmark/header-before.txt
sed -n '1,5p' .superpowers/private/tokenization-benchmark/header-after.txt
```

The post-change result should be directionally faster. Do not fail or weaken behavior based on a noisy individual timing sample; Task 5 applies the accepted runtime gate.

- [ ] **Step 9: Commit header hot-path optimization**

```bash
git add src/ccparser/layout/columns.py tests/layout/test_columns.py
git commit -m "perf: compile column header vocabulary"
```

### Task 3: Remove duplicate discovery marker tokenization

**Files:**
- Modify: `src/ccparser/discovery.py:56,147-345,808-820`
- Modify: `tests/test_discovery.py:1-20,599-622`

**Interfaces:**
- Consumes: `CompiledTokenPhrases`, `TokenSequence`, `compile_token_phrases()`, and `contains_compiled_token_sequence()`.
- Produces: module-compiled discovery marker tuples and `_contains_compiled_phrase()` operating only on token tuples.
- Preserves: exact token matching, compact multi-token aliases, current Hebrew compact-prefix behavior, and `_row_total_marker_signature()` output.

- [ ] **Step 1: Add a failing source-cell call-count test**

Add `import ccparser.discovery as discovery_module` to `tests/test_discovery.py`, then add:

```python
def test_total_marker_signature_tokenizes_each_source_cell_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    words = (
        _word("סהכחיוב", 10.0, 60.0, 10.0),
        _word("₪30.00", 70.0, 110.0, 10.0),
    )
    row = Row(
        page_number=1,
        bbox=(10.0, 10.0, 110.0, 20.0),
        cells=tuple(
            Cell(
                page_number=1,
                bbox=word.bbox,
                text=word.text,
                words=(word,),
                confidence=1.0,
            )
            for word in words
        ),
        words=words,
        confidence=1.0,
    )
    calls: list[str] = []
    original = discovery_module.phrase_tokens

    def counting_phrase_tokens(
        text: str,
        *,
        ignore_acronym_quotes: bool = False,
    ) -> tuple[str, ...]:
        calls.append(text)
        return original(text, ignore_acronym_quotes=ignore_acronym_quotes)

    monkeypatch.setattr(discovery_module, "phrase_tokens", counting_phrase_tokens)

    signature = _row_total_marker_signature(row)

    assert "סהכחיוב" in signature
    assert calls == ["סהכחיוב", "₪30.00"]
```

- [ ] **Step 2: Run the focused discovery tests and confirm repeated calls**

Run:

```bash
.venv/bin/pytest -q \
  tests/test_discovery.py::test_total_marker_signature_tokenizes_each_source_cell_once \
  tests/test_discovery.py::test_total_marker_signature_canonicalizes_compact_hebrew_acronym_aliases
```

Expected: the new test fails because the current signature path tokenizes marker candidates for every source cell and repeats source tokenization after an exact-match miss.

- [ ] **Step 3: Compile all fixed discovery marker sets once**

Replace the text-token imports with:

```python
from ccparser.text_tokens import (
    CompiledTokenPhrases,
    TokenSequence,
    compile_token_phrases,
    contains_compiled_token_sequence,
    phrase_tokens,
)
```

After `_COMPOUND_TOTAL_AMOUNT_PATTERN`, add:

```python
def _compile_discovery_markers(markers: Iterable[str]) -> CompiledTokenPhrases:
    return compile_token_phrases(
        sorted(markers),
        ignore_acronym_quotes=True,
    )


_COMPILED_TOTAL_MARKERS = _compile_discovery_markers(_TOTAL_MARKERS)
_COMPILED_NO_ACTIVITY_MARKERS = _compile_discovery_markers(_NO_ACTIVITY_MARKERS)
_COMPILED_CONTINUATION_HEADING_MARKERS = _compile_discovery_markers(
    _CONTINUATION_HEADING_MARKERS
)
_COMPILED_TRANSACTION_HISTORY_TITLE_MARKERS = _compile_discovery_markers(
    _TRANSACTION_HISTORY_TITLE_MARKERS
)
_COMPILED_FUTURE_BILLING_HEADING_MARKERS = _compile_discovery_markers(
    _FUTURE_BILLING_HEADING_MARKERS
)
_COMPILED_POINTS_UNIT_MARKERS = _compile_discovery_markers(_POINTS_UNIT_MARKERS)
_COMPILED_FEE_SUMMARY_MARKERS = _compile_discovery_markers(_FEE_SUMMARY_MARKERS)
_COMPILED_PAID_FEE_SUMMARY_MARKERS = _compile_discovery_markers(
    _PAID_FEE_SUMMARY_MARKERS
)
_COMPILED_TAX_SUMMARY_MARKERS = _compile_discovery_markers(_TAX_SUMMARY_MARKERS)
_COMPILED_RATE_HEADER_MARKERS = _compile_discovery_markers(_RATE_HEADER_MARKERS)
_COMPILED_FORM_TITLES = _compile_discovery_markers(_FORM_TITLES)
_COMPILED_FORM_FIELDS = _compile_discovery_markers(_FORM_FIELDS)
_COMPILED_CANCELLATION_PURPOSES = _compile_discovery_markers(_CANCELLATION_PURPOSES)
```

- [ ] **Step 4: Match one source token tuple against compiled markers**

Keep `_normalized_phrase()` for metadata parsing, and replace `_contains_phrase()` with both helpers below:

```python
def _contains_compiled_phrase(
    tokens: TokenSequence,
    phrases: CompiledTokenPhrases,
) -> bool:
    if contains_compiled_token_sequence(tokens, phrases):
        return True
    for candidate in phrases:
        compact_phrase = "".join(candidate)
        if len(candidate) > 1 and compact_phrase in tokens:
            return True
        candidate_is_hebrew = any(
            "\u0590" <= char <= "\u05ff"
            for token in candidate
            for char in token
        )
        if candidate_is_hebrew and any(
            token.startswith(compact_phrase) for token in tokens
        ):
            return True
    return False


def _contains_phrase(text: str, phrases: CompiledTokenPhrases) -> bool:
    tokens = phrase_tokens(text, ignore_acronym_quotes=True)
    return _contains_compiled_phrase(tokens, phrases)
```

Replace raw marker arguments at every `_contains_phrase()` call using this exact mapping:

```text
_TOTAL_MARKERS                         -> _COMPILED_TOTAL_MARKERS
_NO_ACTIVITY_MARKERS                   -> _COMPILED_NO_ACTIVITY_MARKERS
_CONTINUATION_HEADING_MARKERS          -> _COMPILED_CONTINUATION_HEADING_MARKERS
_TRANSACTION_HISTORY_TITLE_MARKERS     -> _COMPILED_TRANSACTION_HISTORY_TITLE_MARKERS
_FUTURE_BILLING_HEADING_MARKERS        -> _COMPILED_FUTURE_BILLING_HEADING_MARKERS
_POINTS_UNIT_MARKERS                   -> _COMPILED_POINTS_UNIT_MARKERS
_FEE_SUMMARY_MARKERS                   -> _COMPILED_FEE_SUMMARY_MARKERS
_PAID_FEE_SUMMARY_MARKERS              -> _COMPILED_PAID_FEE_SUMMARY_MARKERS
_TAX_SUMMARY_MARKERS                   -> _COMPILED_TAX_SUMMARY_MARKERS
_RATE_HEADER_MARKERS                   -> _COMPILED_RATE_HEADER_MARKERS
_FORM_TITLES                           -> _COMPILED_FORM_TITLES
_FORM_FIELDS                           -> _COMPILED_FORM_FIELDS
_CANCELLATION_PURPOSES                 -> _COMPILED_CANCELLATION_PURPOSES
```

- [ ] **Step 5: Tokenize row cells once in total-marker signatures**

Replace `_row_total_marker_signature()` with:

```python
def _row_total_marker_signature(row: Row) -> tuple[str, ...]:
    cell_tokens = tuple(
        phrase_tokens(cell.text, ignore_acronym_quotes=True)
        for cell in row.cells
    )
    return tuple(
        sorted(
            {
                "".join(marker)
                for marker in _COMPILED_TOTAL_MARKERS
                if any(
                    _contains_compiled_phrase(tokens, (marker,))
                    for tokens in cell_tokens
                )
            }
        )
    )
```

This produces the same canonical compact signatures without re-normalizing static markers or source cells inside the marker loop.

- [ ] **Step 6: Run discovery, layout, and classification regressions**

Run:

```bash
.venv/bin/ruff format src/ccparser/discovery.py tests/test_discovery.py
.venv/bin/pytest -q tests/test_discovery.py tests/layout/test_regions.py tests/test_normalize.py
.venv/bin/ruff check src/ccparser/discovery.py tests/test_discovery.py
.venv/bin/mypy src/ccparser/discovery.py
```

Expected: all commands pass; compact Hebrew aliases remain equivalent and the call-count test reports exactly one tokenization per source cell.

- [ ] **Step 7: Commit discovery token reuse**

```bash
git add src/ccparser/discovery.py tests/test_discovery.py
git commit -m "perf: compile discovery marker vocabulary"
```

### Task 4: Run complete tracked verification from a committed revision

**Files:**
- Verify only: all tracked source and test files.

**Interfaces:**
- Consumes: completed strict extraction recovery, corpus gate, and tokenization commits.
- Produces: a clean revision passing every repository-required quality gate before private corpus work starts.

- [ ] **Step 1: Confirm every implementation change is committed**

Run:

```bash
test -z "$(git status --porcelain=v1 --untracked-files=all)"
git log -4 --oneline
```

Expected: the quiet cleanliness assertion exits 0. The log contains the
compiled-token, column-header, and discovery-marker commits plus the immediately
preceding recovery commit.

- [ ] **Step 2: Run formatting and static analysis**

Run:

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
```

Expected: all three commands exit 0 with no findings.

- [ ] **Step 3: Run the complete test suite**

Run:

```bash
.venv/bin/pytest -q
```

Expected: exit 0 with every test passing.

- [ ] **Step 4: Reconfirm the verification did not dirty the revision**

Run:

```bash
test -z "$(git status --porcelain=v1 --untracked-files=all)"
```

Expected: exit 0 with no output.

### Task 5: Record and verify final private corpus acceptance

**Files:**
- Private approved membership inventory: `.superpowers/private/corpus-membership.json`
- Independently protected inventory-file SHA-256 and reviewed commit SHA:
  private controller configuration exposed only as
  `APPROVED_MEMBERSHIP_INVENTORY_SHA256` and `EXPECTED_REVIEWED_SHA`.
- Private forward promotion candidate: an absent
  `.superpowers/private/corpus-candidate.*/baseline.json` path. After separate
  review, that immutable file is the accepted baseline and its SHA-256 is pinned
  in private controller configuration as `APPROVED_CORPUS_BASELINE_SHA256`.
- Private record work: unique `.superpowers/private/corpus-record.*` directory.
- Private verify work: unique `.superpowers/private/corpus-verify.*` directory.
- Read-only retained input: `/root/creditcard/documents`.
- Read-only quarantine input: `/root/creditcard/unrelated`.

**Interfaces:**
- Consumes: `ccparse verify-corpus`, the independently approved membership
  inventory and its separately pinned full-file SHA-256, the trusted
  independently pinned full reviewed commit SHA, the independently pinned
  accepted-baseline SHA-256 for verify, a clean committed Git revision, the
  retained corpus, the quarantine corpus, `jobs=4`, and
  `runtime_tolerance=Decimal("0.20")`.
- Produces: a new no-overwrite promotion candidate, a separately reviewed and
  pinned private accepted baseline, and a second independent verification
  attestation from the same revision/toolchain/worker count.
- Enforces: two distinct empty-cache strict retained runs, two distinct empty-cache non-strict quarantine runs, canonical JSON/CSV parity, structural/evidence/ambiguity parity, 104 reconciled retained documents, quarantine `not_statement` parity, and same-toolchain runtime tolerance.

- [ ] **Step 1: Validate clean revision and private path boundaries**

Run:

```bash
test -z "$(git status --porcelain=v1 --untracked-files=all)"
git check-ignore --quiet .superpowers/private/corpus-membership.json
git check-ignore --quiet .superpowers/private/corpus-candidate.example/baseline.json
test -f .superpowers/private/corpus-membership.json
test -d /root/creditcard/documents
test -d /root/creditcard/unrelated
test -n "${EXPECTED_REVIEWED_SHA:-}"
test -n "${APPROVED_MEMBERSHIP_INVENTORY_SHA256:-}"
test "$(git rev-parse --verify HEAD)" = "$EXPECTED_REVIEWED_SHA"
test -z "$(git status --porcelain=v1 --untracked-files=all)"
```

Expected: every quiet assertion exits 0. The independently pinned membership
inventory exists and matches the source multiset previously proven complete;
`record` must not generate or change it. A baseline pin is deliberately not
required yet: record is allowed to produce only an untrusted new candidate.

- [ ] **Step 2: Establish the explicit forward-performance boundary**

There is no trustworthy pre-refactor runtime reference produced by the current
structured-FX schema and the same toolchain, worker count, and approved corpus.
Do not claim a historical full-corpus runtime comparison. The deterministic
call-count regressions from Tasks 2-3 and the same-process header microbenchmark
are the evidence for this optimization. The two fresh retained runs in `record`
establish the forward runtime baseline; every subsequent `verify` must have the
same toolchain and worker count and must fail closed if runtime cannot be checked
or exceeds the recorded tolerance.

Expected: no unsupported historical performance claim is made. The record and
verify commands below use one exact clean revision, one toolchain fingerprint,
`jobs=4`, and the protected membership.

- [ ] **Step 3: Record the accepted optimized baseline from fresh private work**

Run as one shell block. The unique private directory exists, but the candidate
file itself must not exist before the gate publishes it:

```bash
mkdir -p .superpowers/private
corpus_record_work="$(mktemp -d -p .superpowers/private corpus-record.XXXXXX)"
corpus_candidate_dir="$(mktemp -d -p .superpowers/private corpus-candidate.XXXXXX)"
corpus_baseline_candidate="$corpus_candidate_dir/baseline.json"
test ! -e "$corpus_baseline_candidate"
PYTHONPATH="$PWD/src" .venv/bin/ccparse verify-corpus /root/creditcard/documents \
  --quarantine-dir /root/creditcard/unrelated \
  --membership-inventory .superpowers/private/corpus-membership.json \
  --membership-inventory-sha256 "$APPROVED_MEMBERSHIP_INVENTORY_SHA256" \
  --baseline "$corpus_baseline_candidate" \
  --work-dir "$corpus_record_work" \
  --mode record \
  --jobs 4 \
  --expected-commit-sha "$EXPECTED_REVIEWED_SHA" \
  --runtime-tolerance 0.20
```

Expected: exit 0 with a privacy-safe passed attestation reporting `mode=record`,
`retained=104`, `reconciled=104`, and `quarantined=5`. The gate internally
completes both retained and both quarantine runs from distinct empty caches
before exclusively publishing the new candidate. It refuses to overwrite any
existing path.

- [ ] **Step 4: Review and independently pin the promotion candidate**

Review the candidate and its aggregate record attestation through the private
acceptance process. Store its full-file SHA-256 in protected controller
configuration, outside the candidate file, and expose it to the verification
shell only as `APPROVED_CORPUS_BASELINE_SHA256`. Do not derive and trust the pin
inside the same record invocation.

Run these quiet assertions after the independent pin has been supplied:

```bash
test -f "$corpus_baseline_candidate"
test -n "${APPROVED_CORPUS_BASELINE_SHA256:-}"
test "$(sha256sum -- "$corpus_baseline_candidate" | cut -d ' ' -f 1)" = \
  "$APPROVED_CORPUS_BASELINE_SHA256"
```

Expected: all assertions exit 0. From this point, the immutable candidate plus
the external pin is the accepted baseline.

- [ ] **Step 5: Verify the accepted baseline with a second fresh work tree**

Run:

```bash
corpus_verify_work="$(mktemp -d -p .superpowers/private corpus-verify.XXXXXX)"
PYTHONPATH="$PWD/src" .venv/bin/ccparse verify-corpus /root/creditcard/documents \
  --quarantine-dir /root/creditcard/unrelated \
  --membership-inventory .superpowers/private/corpus-membership.json \
  --membership-inventory-sha256 "$APPROVED_MEMBERSHIP_INVENTORY_SHA256" \
  --baseline "$corpus_baseline_candidate" \
  --baseline-sha256 "$APPROVED_CORPUS_BASELINE_SHA256" \
  --work-dir "$corpus_verify_work" \
  --mode verify \
  --jobs 4 \
  --expected-commit-sha "$EXPECTED_REVIEWED_SHA"
```

Expected: exit 0 with `status=passed`, `mode=verify`, `retained=104`,
`reconciled=104`, `quarantined=5`, and `performance_checked=true`. Because the
Git revision, toolchain fingerprint, and worker count match the recorded
baseline, runtime above the accepted tolerance would fail rather than be
skipped.

- [ ] **Step 6: Confirm quarantine, determinism, and baseline checks were authoritative**

Read the aggregate reason/status portion of the two command outputs retained in the terminal. Expected: no reason code for retained status, membership, counts, JSON, CSV, group/transaction structure, field presence, evidence provenance, ambiguity, quarantine status, determinism, or runtime. Do not print or copy per-document private data.

- [ ] **Step 7: Confirm private acceptance created no tracked change**

Run:

```bash
test "$(git rev-parse --verify HEAD)" = "$EXPECTED_REVIEWED_SHA"
test -z "$(git status --porcelain=v1 --untracked-files=all)"
git check-ignore --quiet "$corpus_baseline_candidate"
git check-ignore --quiet "$corpus_record_work"
git check-ignore --quiet "$corpus_verify_work"
```

Expected: every quiet assertion exits 0; the exact reviewed commit remains clean
and every private acceptance path is ignored.
