# Strict Extraction Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve semantic-evidence strictness while resolving every retained-corpus ambiguity through general, evidenced FX/date/semantic extraction rules until all 104 statements reconcile.

**Architecture:** Repair the four observed ambiguity classes at their extraction source: non-negative fee values, percent-bound decimals, attached Hebrew cue prefixes, and unified conversion-date/rate evidence. Each repair creates exact `EvidenceClaim` ownership and retains conservative ambiguity for absent, conflicting, or multiply supported values.

**Tech Stack:** Python 3.13, `Decimal`, Pydantic models, positioned glyph/word evidence, pytest 9.

## Global Constraints

- Use Python 3.13 and `/root/creditcard/.venv`.
- Follow red-green-refactor for every production behavior.
- Never remove a diagnostic without proving a unique value or a legitimate typed evidence disposition.
- Do not add filename-, path-, hash-, document-, issuer-, merchant-, date-, amount-, total-, or corpus-index-specific behavior.
- Preserve all public fields, transaction ordering, diagnostic strings, and exact provenance.
- Keep corpus inputs, outputs, hashes, values, and aggregate recovery reports private and out of Git.
- Do not change files outside `/root/creditcard`.
- Before any test or command that may use system temporary storage, run `export TMPDIR="$PWD/.superpowers/private/tmp"` and `mkdir -p "$TMPDIR"`; every temporary file must stay inside this worktree.

## File Structure

- Modify `src/ccparser/fx.py`: non-negative fee parsing, percent-bound selection, repeated-evidence merging, and cue policy use.
- Modify `src/ccparser/text_tokens.py`: explicit Hebrew single-letter clitic policy while retaining exact token boundaries.
- Modify `src/ccparser/normalization_dates.py`: unify equivalent fragmented and cross-cell conversion-date evidence.
- Modify `src/ccparser/normalize.py`: consume the unified conversion source set without weakening invalid-source checks.
- Modify `tests/test_fx.py`, `tests/test_text_tokens.py`, `tests/test_normalization_dates.py`, and `tests/test_normalize.py`: minimized behavior and integration regressions.
- Modify `tests/test_output.py`: structured FX value and provenance serialization guard.

---

### Task 1: Extract explicit zero-valued FX fees

**Files:**
- Modify: `src/ccparser/fx.py:119-177`
- Modify: `tests/test_fx.py`

**Interfaces:**
- Consumes: `EvidenceLedger.positioned_decimal_candidates()` and proven fee-column/row context.
- Produces: evidenced `ExtractedMoney` with `amount=Decimal("0.00")`, the proven billing currency, and the matching fee owner claim.

- [ ] **Step 1: Add failing zero-fee tests**

```python
def test_explicit_zero_table_fee_is_evidenced_without_ambiguity() -> None:
    row = _foreign_row().model_copy(
        update={
            "cells": tuple(
                cell.model_copy(
                    update={"text": "₪0.00", "glyphs": _glyphs("₪0.00", 50.0, 30.0)}
                )
                if index == 1
                else cell
                for index, cell in enumerate(_foreign_row().cells)
            )
        }
    )
    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )
    assert extraction.details is not None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.00")
    assert extraction.diagnostics == ()
    assert any(claim.owner is SemanticOwner.NET_FX_FEE for claim in extraction.claims)


def test_zero_without_proven_billing_currency_remains_unparsed() -> None:
    row = _foreign_row().model_copy(
        update={"cells": (_cell("0.00", 1, 30.0, glyphs=_glyphs("0.00", 50.0, 30.0)),)}
    )
    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )
    assert "unparsed_foreign_currency_fee_candidate" in extraction.diagnostics
```

Also add zero gross-fee and zero discount continuation tests. Preserve the existing multiple-decimal and discount-larger-than-gross negative cases.

- [ ] **Step 2: Verify the focused failures**

Run:

```bash
.venv/bin/pytest -q tests/test_fx.py -k zero
```

Expected: table/gross/discount zero tests fail because `_one_positive_decimal()` rejects zero.

- [ ] **Step 3: Permit zero only for fee money**

Change `_one_money()` and `_one_row_money()` to call `_one_decimal()` with `allow_zero=True`. Keep exchange rates on `_one_positive_decimal()`. Keep the exact expected-currency requirement unchanged:

```python
def _one_money(
    cell: Cell,
    ledger: EvidenceLedger,
    expected_currency: str,
) -> tuple[Decimal, str, frozenset[int]] | None:
    currencies = currencies_in_text(cell.text)
    if len(currencies) != 1 or currencies[0] != canonical_currency(expected_currency):
        return None
    parsed = _one_decimal(ledger.atoms_for_cell(cell), ledger, allow_zero=True)
    if parsed is None:
        return None
    amount, atom_ids = parsed
    return amount, currencies[0], atom_ids
```

Apply the same non-negative policy to `_one_row_money()`. In the pending-gross continuation classifier, replace its positive-only probe with `_one_decimal(atom_ids, ledger, allow_zero=True)` so an uncued explicit zero gross fee can enter the already proven pending-gross role. Do not relax any currency or cue requirement.

- [ ] **Step 4: Run focused, normalization, and reconciliation tests**

```bash
.venv/bin/pytest -q tests/test_fx.py tests/test_normalize.py tests/test_reconcile.py
```

Expected: pass.

- [ ] **Step 5: Commit the zero-fee repair**

```bash
git add src/ccparser/fx.py tests/test_fx.py
git commit -m "fix: preserve evidenced zero FX fees"
```

### Task 2: Select decimals bound to a percent sign

**Files:**
- Modify: `src/ccparser/fx.py:256-330`
- Modify: `tests/test_fx.py`

**Interfaces:**
- Consumes: positioned decimal candidates and percent glyph atoms within one bounded FX detail row.
- Produces: `_percentage_candidate()` returning one `(Decimal, atom_ids)` only when the percent-bound value is unique.

- [ ] **Step 1: Add failing mixed-value and repeated-evidence tests**

```python
def test_percentage_selects_percent_bound_decimal_when_money_is_on_same_row() -> None:
    base = _base_row_without_fx_values()
    detail = _bounded_continuation(
        _positioned_cell(
            "foreign-currency fee 3.00% ILS 0.88",
            "foreign-currency fee 3.00% ILS 0.88",
            50.0,
            40.0,
        )
    )
    extraction = extract_foreign_exchange(
        rows=(base, detail),
        region=_region(base, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows((base, detail)),
        original_currency="USD",
        billing_currency="ILS",
    )
    assert extraction.details is not None
    assert extraction.details.fee_percentage is not None
    assert extraction.details.fee_percentage.value == Decimal("3.00")
    assert "unparsed_foreign_currency_fee_percentage_candidate" not in extraction.diagnostics


def test_repeated_identical_percentages_merge_provenance() -> None:
    base = _base_row_without_fx_values()
    details = tuple(
        _bounded_continuation(
            _positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, y)
        )
        for y in (40.0, 50.0)
    )
    extraction = extract_foreign_exchange(
        rows=(base, *details),
        region=_region(base, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows((base, *details)),
        original_currency="USD",
        billing_currency="ILS",
    )
    assert extraction.details is not None
    assert extraction.details.fee_percentage is not None
    assert len(extraction.details.fee_percentage.evidence) == 2
    assert extraction.diagnostics == ()
```

Add a conflicting repeated-percentage test that remains ambiguous.

- [ ] **Step 2: Confirm the intended failures**

Run `.venv/bin/pytest -q tests/test_fx.py -k percentage`.

Expected: mixed-value and identical-repeat tests fail under whole-row cardinality logic.

- [ ] **Step 3: Implement geometric percent binding and equivalent merge**

Add a helper that selects decimal candidates whose bounding box is on the same line and directly adjacent to a `%` glyph. Use atom geometry, not raw substring slicing:

```python
def _percentage_candidate(
    atom_ids: frozenset[int],
    ledger: EvidenceLedger,
) -> tuple[Decimal, frozenset[int]] | None:
    percent_atoms = tuple(
        atom for atom in ledger.atoms if atom.atom_id in atom_ids and atom.text == "%"
    )
    candidates = tuple(
        candidate
        for candidate in ledger.positioned_decimal_candidates(atom_ids)
        if _candidate_is_adjacent_to_one_percent(candidate, percent_atoms, ledger)
    )
    parsed = tuple(
        (value, candidate.atom_ids)
        for candidate in candidates
        if (value := _decimal(candidate.text)) is not None and value >= 0
    )
    return parsed[0] if len(parsed) == 1 else None
```

When another explicit percentage is encountered, merge evidence and claims if its value equals the first; otherwise clear the value and block the owner as today.

- [ ] **Step 4: Run FX and semantic-ledger suites**

```bash
.venv/bin/pytest -q tests/test_fx.py tests/test_semantic_evidence.py
```

Expected: pass.

- [ ] **Step 5: Commit percent-bound extraction**

```bash
git add src/ccparser/fx.py tests/test_fx.py
git commit -m "fix: bind FX percentages to percent evidence"
```

### Task 3: Support explicit Hebrew clitic prefixes without substring matching

**Files:**
- Modify: `src/ccparser/text_tokens.py`
- Modify: `src/ccparser/fx.py:68-95`
- Modify: `tests/test_text_tokens.py`
- Modify: `tests/test_fx.py`
- Modify: `tests/test_normalize.py`
- Modify: `tests/test_output.py`

**Interfaces:**
- Consumes: exact token tuples.
- Produces: `contains_token_sequence()` with `allow_hebrew_clitic_prefix=True` used explicitly by FX cues.

- [ ] **Step 1: Add failing positive and negative lexical tests**

```python
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
        "corporate date",
        ("rate",),
        allow_hebrew_clitic_prefix=True,
    )
```

Add an FX extraction test whose conversion-date header contains the attached-prefix cue and assert rate value plus evidence. In the same red step, construct a `TableRegion` with that supported attached-prefix combined header, normalize it, build a `BatchResult`, and assert the nested exchange-rate value, non-empty evidence, and the CSV source page/bounding-box columns.

- [ ] **Step 2: Confirm exact-token matching rejects the positive case**

Run:

```bash
.venv/bin/pytest -q tests/test_text_tokens.py tests/test_fx.py tests/test_normalize.py tests/test_output.py -k 'clitic or prefix'
```

Expected: the lexical, FX, normalization, and output positive cases fail because exact-token matching rejects the attached prefix; existing substring-negative cases remain green.

- [ ] **Step 3: Implement the opt-in lexical policy**

Use the closed Hebrew single-letter clitic set and apply it only to the first cue token:

```python
HEBREW_CLITIC_PREFIXES = frozenset("ובכלמהש")


def _first_token_matches(source: str, candidate: str, *, allow_hebrew_clitic_prefix: bool) -> bool:
    if source == candidate:
        return True
    return (
        allow_hebrew_clitic_prefix
        and len(source) > len(candidate)
        and source[0] in HEBREW_CLITIC_PREFIXES
        and source[1:] == candidate
        and any("\u0590" <= char <= "\u05ff" for char in candidate)
    )
```

All subsequent cue tokens remain exact. Pass the option from `fx._contains_cue()`; do not change unrelated callers.

- [ ] **Step 4: Verify normalization-to-output provenance coverage**

The integration test written in Step 1 asserts:

```python
assert transaction.foreign_exchange.exchange_rate.value == Decimal("2.9660")
assert transaction.foreign_exchange.exchange_rate.evidence
assert b"exchange_rate_source_page" in transactions_csv_bytes(batch)
assert b"exchange_rate_source_bbox" in transactions_csv_bytes(batch)
```

Run:

```bash
.venv/bin/pytest -q tests/test_text_tokens.py tests/test_fx.py tests/test_normalize.py tests/test_output.py
```

Expected: pass, including the integration assertions and existing coffee/corporate substring negatives.

- [ ] **Step 5: Commit cue and provenance recovery**

```bash
git add src/ccparser/text_tokens.py src/ccparser/fx.py tests/test_text_tokens.py tests/test_fx.py tests/test_normalize.py tests/test_output.py
git commit -m "fix: recover prefixed Hebrew FX cues"
```

### Task 4: Unify equivalent conversion-date evidence and isolate rates

**Files:**
- Modify: `src/ccparser/normalization_dates.py:1102-1172`
- Modify: `src/ccparser/normalize.py:330-365`
- Modify: `src/ccparser/fx.py`
- Modify: `tests/test_normalization_dates.py`
- Modify: `tests/test_normalize.py`
- Modify: `tests/test_fx.py`

**Interfaces:**
- Consumes: fragmented same-cell candidates and parsed cross-cell evidence.
- Produces: one `ConversionDateExtraction` with the union of source cells and source atom IDs when every raw candidate parses to the same date; FX parsing excludes those date atoms so date/rate claims are disjoint.

- [ ] **Step 1: Add failing equivalent-source integration tests**

Create a synthetic foreign row whose logical conversion field contains both a fragmented date representation and a cross-cell representation of the same date adjacent to one exchange-rate decimal. Assert:

```python
extraction = extract_conversion_date(
    row,
    region,
    ledger,
    year_context,
    original_currency="USD",
    billing_currency="ILS",
    transaction_date=date(2026, 6, 19),
    existing_conversion_date=None,
)
assert extraction.value == date(2026, 6, 22)
assert extraction.diagnostics == ()
assert extraction.source_cells == frozenset(expected_date_cells)
assert extraction.source_atom_ids == frozenset(expected_date_atom_ids)
```

Normalize the same row and assert no `invalid_conversion_date`, `unparsed_conversion_date_candidate`, `unparsed_exchange_rate_candidate`, or `unconsumed_transaction_semantic_text`. Add conflicting-date and multiple-rate negatives that retain ambiguity.

- [ ] **Step 2: Confirm current cross-cell precedence fails**

```bash
.venv/bin/pytest -q tests/test_normalization_dates.py tests/test_normalize.py -k 'equivalent or combined'
```

Expected: equivalent-source tests fail because any simultaneous raw cross-cell and same-cell candidate is rejected.

- [ ] **Step 3: Resolve one unique date across all evidence forms**

Extend `ConversionDateExtraction` with `source_atom_ids: frozenset[int]`. Refactor `extract_conversion_date()` to create one tuple of `(parsed_date | None, source_cells, source_atom_ids)` candidates from every raw same-cell and cross-cell item. Accept only when every raw candidate parsed and all parsed candidates have one unique date. Deduplicate equal values and union their exact cells and atom IDs:

```python
resolved: dict[date, tuple[set[Cell], set[int]]] = {}
all_parsed = all(value is not None for value, _cells, _atom_ids in parsed_sources)
for value, source_cells, source_atom_ids in parsed_sources:
    if value is None:
        continue
    cells, atom_ids = resolved.setdefault(value, (set(), set()))
    cells.update(source_cells)
    atom_ids.update(source_atom_ids)
if parsed_sources and all_parsed and len(resolved) == 1:
    value, (source_cells, source_atom_ids) = next(iter(resolved.items()))
    return ConversionDateExtraction(
        value,
        (),
        frozenset(source_cells),
        frozenset(source_atom_ids),
    )
return ConversionDateExtraction(
    None,
    ("unparsed_conversion_date_candidate",) if raw_candidates else (),
    frozenset(),
    frozenset(),
)
```

Add an `excluded_atom_ids: frozenset[int] = frozenset()` keyword to `extract_foreign_exchange()` and thread it through table and continuation decimal selection. `normalize.py` passes `conversion_extraction.source_atom_ids`; rate extraction subtracts those IDs before selecting a positive decimal. `normalize.py` retains its exact unresolved-source subset check against the now-complete `source_cells` union. The conflicting-date negative must include one parseable and one unparseable raw candidate and remain ambiguous, proving that a single valid candidate cannot mask invalid evidence.

- [ ] **Step 4: Run date, FX, normalization, and semantic suites**

```bash
.venv/bin/pytest -q tests/test_normalization_dates.py tests/test_fx.py tests/test_normalize.py tests/test_normalization_semantics.py
```

Expected: pass.

- [ ] **Step 5: Commit combined semantic extraction**

```bash
git add src/ccparser/normalization_dates.py src/ccparser/normalize.py src/ccparser/fx.py tests/test_normalization_dates.py tests/test_normalize.py tests/test_fx.py
git commit -m "fix: separate conversion dates from FX rates"
```

### Task 5: Close any residual strict semantic ownership failure

**Files:**
- Modify only the extraction module that owns the residual typed role.
- Modify the matching focused test module.
- Private diagnostics: `.superpowers/private/strict-residual-*` only.

**Interfaces:**
- Consumes: strict parser ambiguity reason codes and semantic-ledger dispositions.
- Produces: either proof that Tasks 1-4 leave no residual ambiguity, or one minimized synthetic regression plus a general typed ownership repair.

- [ ] **Step 1: Run a private code-only diagnostic checkpoint**

Run a fresh-cache strict parse and project only aggregate status and the closed ambiguity-code vocabulary into a separate ignored diagnostic file. Raw parser output remains confined to the unique ignored run directory; the diagnostic projection itself must not contain source names, hashes, raw text, dates, merchants, amounts, totals, or per-document values:

```bash
residual_run=$(mktemp -d .superpowers/private/strict-residual.XXXXXX)
PYTHONPATH=src .venv/bin/ccparse parse /root/creditcard/documents \
  --output-dir "$residual_run/output" \
  --cache-dir "$residual_run/cache" \
  --jobs 4 --strict \
  >"$residual_run/parser.log" 2>&1
parse_status=$?
test "$parse_status" -eq 0 -o "$parse_status" -eq 2
.venv/bin/python -c '
from collections import Counter
from pathlib import Path
import sys
from ccparser.models import BatchResult

batch = BatchResult.model_validate_json(Path(sys.argv[1]).read_bytes())
codes = Counter(
    code
    for statement in batch.statements
    for transaction in statement.transactions
    for code in transaction.ambiguities
)
ambiguous = sum(
    bool(transaction.ambiguities)
    for statement in batch.statements
    for transaction in statement.transactions
)
code_text = ",".join(f"{code}:{count}" for code, count in sorted(codes.items()))
print(
    f"status={batch.status.value} documents={len(batch.statements)} "
    f"ambiguous_transactions={ambiguous} codes={code_text}"
)
' "$residual_run/output/results.json" >"$residual_run/ambiguity-codes.txt"
```

Expected: either all retained statements reconcile, or the private projection exposes a remaining closed ambiguity code without document content.

- [ ] **Step 2: Minimize any remaining general rule before editing production code**

If a code remains, identify its semantic role, column role, continuation relationship, and evidence geometry privately. Add `test_residual_typed_evidence_is_claimed` to the existing focused module for that owner (`tests/test_fx.py`, `tests/test_normalization_dates.py`, or `tests/test_normalization_semantics.py`). The test must use invented values and text, assert the exact field or `EvidenceClaim`, and initially assert the strict diagnostic is absent only after the intended typed claim exists.

Run the red test before editing production code:

```bash
.venv/bin/pytest -q tests/test_fx.py tests/test_normalization_dates.py tests/test_normalization_semantics.py -k residual_typed_evidence
```

Expected: the new test fails because the role is not yet extracted or claimed, and the current exact ambiguity is still present.

If no code remains, add no speculative production rule and proceed to Task 6.

- [ ] **Step 3: Implement the narrow typed owner and preserve conflict negatives**

Change only the extractor responsible for the proven role. Claim the exact supporting atom IDs and emit exact provenance. Do not add a generic ancillary claim or suppress `unconsumed_transaction_semantic_text`. Add a conflicting/unsupported negative that remains ambiguous.

- [ ] **Step 4: Run the focused and semantic suites**

```bash
.venv/bin/pytest -q tests/test_fx.py tests/test_normalization_dates.py tests/test_normalization_semantics.py tests/test_normalize.py
```

Expected: pass. If production changed, commit only the focused source and test files with message `fix: claim residual typed semantic evidence`.

### Task 6: Private strict corpus recovery checkpoint

**Files:**
- No tracked production changes are planned in this acceptance task.
- Private outputs: `.superpowers/private/strict-recovery-*` only.

**Interfaces:**
- Consumes: completed extraction repairs and `ccparse parse`.
- Produces: a private ambiguity inventory with no unresolved retained transactions.

- [ ] **Step 1: Commit or verify a clean worktree**

Run `git status --short`.

Expected: no output.

- [ ] **Step 2: Run a fresh-cache strict corpus parse**

```bash
recovery_run=$(mktemp -d .superpowers/private/strict-recovery.XXXXXX)
/usr/bin/time -f '%e' -o .superpowers/private/latest-recovery-runtime-seconds.txt \
  env PYTHONPATH=src .venv/bin/ccparse parse /root/creditcard/documents \
  --output-dir "$recovery_run/output" \
  --cache-dir "$recovery_run/cache" \
  --jobs 4 --strict \
  >"$recovery_run/parser.log" 2>&1
```

Expected: exit 0 and the aggregate private log reports all 104 retained documents reconciled.

- [ ] **Step 3: Check private ambiguity and field-presence invariants**

Use the gate projection code against the private `results.json` and the trusted ignored historical-reference projection. Expected: zero ambiguous transactions; the transaction-identity set is unchanged; each required structured-field count is at least its approved historical count; and every approved provenance entry is present exactly in the candidate. Hashes are compared only for equality between equivalent fresh runs—never described as “improved.” Do not print per-document data.

- [ ] **Step 4: Run repository gates**

```bash
.venv/bin/ruff format .
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
```

Expected: pass.
