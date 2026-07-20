# Semantic Evidence Completeness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make merchant and conversion-date extraction lossless and make unresolved transaction semantics prevent strict success without changing financial arithmetic or the public output schema.

**Architecture:** Build a deterministic row evidence ledger from glyph, word, and cell fallbacks; have semantic extractors return explicit ownership claims; then validate that every meaningful transaction-row atom is emitted, classified as ancillary evidence, proven noise, or reported as unresolved. Description and conversion-date recovery operate on positioned atoms rather than whole-cell strings.

**Tech Stack:** Python 3.13, Pydantic 2, PyMuPDF evidence models, Typer, pytest, Ruff, mypy.

## Global Constraints

- Follow red-green-refactor for every production behavior.
- Use `Decimal` for all financial arithmetic; never use binary floating point for transaction values or totals.
- Do not branch on filenames, paths, hashes, dates, merchants, amounts, totals, accounts, card numbers, or issuers.
- Keep the `Transaction`, JSON, and CSV schemas unchanged; FX rates and fees remain a separate change.
- Preserve complete transaction capture, exact billed/original values, exact totals, deterministic output, and born-digital parsing.
- Keep private documents and derived financial output out of Git.

---

### Task 1: Deterministic evidence ledger

**Files:**
- Create: `src/ccparser/semantic_evidence.py`
- Create: `tests/test_semantic_evidence.py`

**Interfaces:**
- Consumes: `Sequence[Row]`, positioned `Glyph`/`Word`, and existing `logical_text_for_evidence`.
- Produces: `EvidenceLedger.from_rows(rows)`, `EvidenceClaim`, `SemanticOwner`, `atoms_for_cell(cell)`, `render(atom_ids)`, and `validate_claims(claims)`.

- [ ] **Step 1: Write failing atomization and deduplication tests**

Create overlapping synthetic cells which contain the same positioned glyphs and
assert that `EvidenceLedger.from_rows()` emits one atom per unique source glyph.
Also assert word fallback when glyphs are absent and cell-text fallback only when
both glyphs and words are absent.

```python
def test_ledger_deduplicates_overlapping_source_glyphs() -> None:
    glyphs = _glyphs("AB", 10.0, 20.0)
    first = _cell("AB", (10.0, 20.0, 20.0, 30.0), glyphs=glyphs)
    duplicate = _cell("AB", (10.0, 20.0, 20.0, 30.0), glyphs=glyphs)

    ledger = EvidenceLedger.from_rows((_row(first, duplicate),))

    assert tuple(atom.text for atom in ledger.atoms) == ("A", "B")
    assert ledger.atoms_for_cell(first) == ledger.atoms_for_cell(duplicate)
```

- [ ] **Step 2: Run the focused tests and confirm the expected import failure**

Run: `.venv/bin/pytest -q tests/test_semantic_evidence.py`

Expected: collection fails because `ccparser.semantic_evidence` does not exist.

- [ ] **Step 3: Implement immutable atom and claim models plus deterministic construction**

Use frozen, slotted dataclasses. Deduplicate glyphs by page, bbox, origin, character,
font, and source; retain the maximum confidence and all containing cells. Sort atoms
by page, line position, x position, evidence kind, and text before assigning integer
IDs. Do not use Python object hashes in persisted or ordered behavior.

```python
class SemanticOwner(StrEnum):
    DESCRIPTION = "description"
    TRANSACTION_DATE = "transaction_date"
    POSTING_DATE = "posting_date"
    CONVERSION_DATE = "conversion_date"
    BILLED_VALUE = "billed_value"
    ORIGINAL_VALUE = "original_value"
    INSTALLMENT = "installment"
    CATEGORY = "category"
    LOCATION = "location"
    PROCESSOR_REFERENCE = "processor_reference"
    ANCILLARY = "ancillary"
    LAYOUT_NOISE = "layout_noise"


@dataclass(frozen=True, slots=True)
class EvidenceClaim:
    owner: SemanticOwner
    atom_ids: frozenset[int]


@dataclass(frozen=True, slots=True)
class ClaimValidation:
    unclaimed_atom_ids: frozenset[int]
    diagnostics: tuple[str, ...]
```

- [ ] **Step 4: Add failing claim validation and rendering tests**

Assert incompatible double claims produce `conflicting_semantic_evidence_claim`,
unclaimed alphabetic/numeric atoms are returned, punctuation-only atoms are not
meaningful by themselves, and rendering selected atoms restores spaces from word
boxes and logical RTL order.

- [ ] **Step 5: Implement pure claim validation and selected-atom rendering**

`validate_claims()` must accept the ledger and an iterable of claims, reject an
unknown atom ID, report incompatible owners, and return meaningful unclaimed IDs.
`render()` must pass selected glyphs and fully covered word boxes to
`logical_text_for_evidence`; it must never synthesize spaces from string literals.

- [ ] **Step 6: Run focused and normalization suites**

Run: `.venv/bin/pytest -q tests/test_semantic_evidence.py tests/test_normalize.py`

Expected: all pass.

---

### Task 2: Atom-based description reconstruction

**Files:**
- Modify: `src/ccparser/semantic_evidence.py`
- Modify: `src/ccparser/normalize.py`
- Modify: `tests/test_semantic_evidence.py`
- Modify: `tests/test_normalize.py`

**Interfaces:**
- Consumes: an `EvidenceLedger`, transaction/continuation rows, `TableRegion`, and inferred column roles.
- Produces: `DescriptionExtraction(value, claims, diagnostics)` through
  `extract_description(ledger, rows, region)`.

- [ ] **Step 1: Add failing synthetic description regressions**

Add separate tests for:

Each test calls `normalize_statement()` with one synthetic region and asserts the
single emitted transaction's description exactly:

```python
assert result.transactions[0].description == "דלק מנטה עוקף חדרה"
assert result.transactions[0].description == 'חברת פרטנר תקשורת בע״מ (ה)'
assert result.transactions[0].description == "BACKBLAZE INC"
assert result.transactions[0].description == "PAYPAL *PRIVATEIN"
assert result.transactions[0].description == "OPENAI *CHATGPT S"
```

The fixtures must encode the relevant word/glyph gaps and column boundaries. The
reference/processor tests must prove exclusion by repeated geometric position or
column profile, not by the literal token value.

- [ ] **Step 2: Run each new test and confirm it fails with the current truncated or noisy description**

Run each node with `.venv/bin/pytest -q tests/test_normalize.py::<node>`.

Expected: the leading/suffix text is absent, word spacing is lost, or distant
processor text is retained exactly as described by the review.

- [ ] **Step 3: Implement spatial clusters and description claims**

Add immutable result types and helpers that:

- identify the primary cluster inside the description band;
- expand across the shared date/description boundary when same-baseline spacing is
  within a median glyph/word-height tolerance;
- split an adjacent cell at a large gap or at a repeated category token;
- include aligned description continuation fragments and exclude independently
  aligned continuation/category fragments;
- classify repeated distant suffix clusters as processor references;
- render only claimed description atoms.

```python
@dataclass(frozen=True, slots=True)
class DescriptionExtraction:
    value: str | None
    claims: tuple[EvidenceClaim, ...]
    diagnostics: tuple[str, ...]
```

- [ ] **Step 4: Integrate the extractor into `_normalize_row`**

Construct one ledger from `(row, *continuation_rows)`, replace `_description()`'s
whole-cell return with `extract_description()`, and append its diagnostics. Retain
the existing original-amount spill recovery only as a source of description atom
candidates; do not append residual strings outside the ledger.

- [ ] **Step 5: Add semantic failure tests for competing or unconsumed text**

Assert competing continuation clusters emit
`ambiguous_description_continuation`, high-confidence boundary text that cannot be
owned emits `unconsumed_description_boundary_text`, and either ambiguity makes the
transaction and reconciliation status non-successful while retaining the billed
transaction.

- [ ] **Step 6: Run focused and full normalization tests**

Run: `.venv/bin/pytest -q tests/test_semantic_evidence.py tests/test_normalize.py`

Expected: all pass after deliberately updating the old test that treated arbitrary
text in a one-row `unknown` band as harmless; it must now expect a semantic
ambiguity unless the band has structural ancillary evidence.

---

### Task 3: Geometry-aware fragmented conversion dates

**Files:**
- Modify: `src/ccparser/semantic_evidence.py`
- Modify: `src/ccparser/normalize.py`
- Modify: `tests/test_semantic_evidence.py`
- Modify: `tests/test_normalize.py`

**Interfaces:**
- Consumes: physical-order digit/separator atoms, `DiscoveredDateYearContext`, role columns, and parsed original/billing currencies.
- Produces: unique `DateEvidenceCandidate(text, atom_ids)` values and conversion-date claims.

- [ ] **Step 1: Add failing candidate-builder tests for both observed spacing shapes**

Use glyph geometry whose logical cell text is `. ב 8/0 6/2 6 - לא` and
`. ב 2 5/0 6/2 6 - לא`. Assert physical-order candidates are `08/06/26` and
`25/06/26`, with exact digit/separator atom IDs.

- [ ] **Step 2: Add negative tests before implementation**

Assert no candidate for inconsistent separators, excessive inter-glyph gaps,
invalid calendar dates, a non-foreign row with an unrelated date note, and two
distinct valid dates in the same eligible region. The last case must yield
`unparsed_conversion_date_candidate` rather than choose the first date.

- [ ] **Step 3: Implement physical-line candidate construction**

Group atoms by baseline, sort each group by physical x, retain digit and `/.-`
atoms, split at gaps larger than the local median width/height tolerance, and
enumerate bounded subsequences containing exactly two consistent separators. Return
deduplicated candidates and their exact atom IDs; parsing and year-context
validation remain in `normalize.py`.

- [ ] **Step 4: Integrate conversion-date recovery after original-currency parsing**

Keep existing explicit `conversion_date` column parsing. If it fails, or if no such
role exists, inspect one residual candidate only when the row proves a foreign
transaction (`original_currency != billing_currency`) and the candidate lies outside
the transaction-date and amount/description claims. Require exactly one valid date
under the existing date style/year context. Claim its atoms as
`SemanticOwner.CONVERSION_DATE`; classify surrounding phrase evidence as ancillary.

- [ ] **Step 5: Ensure failed cues become transaction ambiguities**

If an eligible conversion-date region contains date separators/digits but yields no
unique valid date, append `unparsed_conversion_date_candidate`. Do not silently
return `None`.

- [ ] **Step 6: Run focused suites**

Run: `.venv/bin/pytest -q tests/test_semantic_evidence.py tests/test_normalize.py`

Expected: all pass, including existing normal and overlapping-boundary date tests.

---

### Task 4: Complete evidence dispositions and strict semantics

**Files:**
- Modify: `src/ccparser/semantic_evidence.py`
- Modify: `src/ccparser/normalize.py`
- Modify: `tests/test_semantic_evidence.py`
- Modify: `tests/test_normalize.py`
- Modify: `tests/test_parser.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: all field claims plus table role/header/value profiles.
- Produces: final per-transaction semantic diagnostics through existing `Transaction.ambiguities`.

- [ ] **Step 1: Add failing ancillary classification tests**

Prove that stable, header-backed columns and row kinds can own category, transaction
type, location, card-present, note, auxiliary amount, exchange-rate, and deferred FX
atoms without adding them to the merchant. Prove that a singleton unexplained
`unknown` text band remains unresolved.

- [ ] **Step 2: Implement evidence dispositions for all existing semantic roles**

Claim exact parsed lexemes for date, amount, currency, and installment fields. Claim
known ancillary roles directly. For `unknown` columns, require a non-empty header
plus a repeated, geometrically stable column profile or an already-proven
continuation kind; never classify a value solely from its literal content.

- [ ] **Step 3: Run ledger validation at the end of `_normalize_row`**

Map unresolved boundary atoms to `unconsumed_description_boundary_text`, unresolved
conversion cues to `unparsed_conversion_date_candidate`, conflicting claims to
`conflicting_semantic_evidence_claim`, and other meaningful residuals to
`unconsumed_transaction_semantic_text`. Deduplicate diagnostics while preserving
deterministic order.

- [ ] **Step 4: Add reconciliation and CLI regressions**

Construct an exact-total transaction carrying one semantic ambiguity. Assert the
calculated and printed totals remain equal, the statement is `unreconciled`, normal
CLI mode still writes inspectable output with exit 0, strict mode exits 2, and an
input/runtime exception exits 1.

- [ ] **Step 5: Run parser-facing suites**

Run: `.venv/bin/pytest -q tests/test_reconcile.py tests/test_normalize.py tests/test_parser.py tests/test_cli.py tests/test_output.py`

Expected: all pass with the public JSON/CSV column lists unchanged.

---

### Task 5: Local-statement acceptance and generalized convergence

**Files:**
- Modify only generalized source/tests implicated by newly observed structural failures.
- Do not add private PDFs, output files, caches, or statement-specific expectations to Git.

**Interfaces:**
- Consumes: the two current local 2026-07 statements and the retained local corpus.
- Produces: clean strict output for the target statements with unchanged monetary baselines.

- [ ] **Step 1: Parse the two current local statements into a fresh temporary directory**

Run `.venv/bin/ccparse parse` for each current local PDF with a temporary output and
cache directory. Assert 12 and 34 transactions, 46 total date/amount pairs, one and
two reconciliation groups, and the same printed/calculated totals as the baseline.

- [ ] **Step 2: Check all fourteen descriptions and two conversion dates**

Compare the affected rows by transaction date plus billed amount against the review
expectations. Do not encode these values in production. Confirm Cal conversion dates
are `2026-06-08` and `2026-06-25`, and all affected transactions have no semantic
ambiguities.

- [ ] **Step 3: Investigate every remaining failure structurally**

For each mismatch, inspect only its cells, words, glyphs, roles, and continuation
diagnostics; write a minimized failing synthetic test; watch it fail; implement the
smallest general geometry/ownership correction; rerun focused tests. Stop and
reassess the architecture before a fourth failed fix attempt.

- [ ] **Step 4: Run a broader retained-corpus strict parse**

Use a fresh temporary output/cache directory. Treat new semantic failures as real
signals unless evidence proves a narrow artifact or ancillary classification. Never
add document identity branches to restore green status.

---

### Task 6: Final verification and documentation

**Files:**
- Modify: `README.md` only if diagnostic behavior needs user-facing clarification.

**Interfaces:**
- Produces: a fully verified repository and documented strict-mode semantics.

- [ ] **Step 1: Run format and static checks**

Run:

```bash
.venv/bin/ruff format .
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
```

Expected: all pass with no suppressions.

- [ ] **Step 2: Run the complete test suite**

Run: `.venv/bin/pytest -q`

Expected: all tests pass.

- [ ] **Step 3: Re-run target statements twice and compare deterministic output**

Use two fresh temporary directory/cache pairs and compare `results.json` and
`transactions.csv` byte-for-byte for each identical run. Confirm no OCR cache entry
is required for the two born-digital inputs.

- [ ] **Step 4: Audit prohibited specialization and repository cleanliness**

Search changed production code for target filenames, hashes, merchants, dates,
amounts, totals, issuers, account/card identifiers, and private paths. Inspect
`git diff --check` and `git status --short`; only source, generalized tests, and
documentation may be tracked.

- [ ] **Step 5: Commit only after fresh verification**

Stage the intentionally changed files and commit with a concise message describing
semantic evidence completeness.
