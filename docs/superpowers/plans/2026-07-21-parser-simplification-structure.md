# Parser Structural Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace contradictory internal result models, diagnostic-string control flow, heterogeneous continuation returns, and the monolithic row-normalization path with explicit typed state while preserving every established public parser result.

**Architecture:** Build internal models around concepts the pipeline already has—reconciliation membership, row tags, continuation matches, scan state, and field extraction outcomes. Migrate one behavior cluster at a time behind characterization tests. Keep corpus-tuned semantic detectors distinct and keep public DTOs and diagnostics unchanged.

**Tech Stack:** Python 3.13, Pydantic 2, PyMuPDF, Typer, pytest 9, Ruff, mypy strict.

## Global Constraints

- Complete and verify `docs/superpowers/plans/2026-07-21-parser-simplification-foundations.md` first; this plan consumes its shared Decimal, token, date, geometry, column-association, path, and summary modules.
- Use Python 3.13 and the repository `.venv`.
- Develop every production behavior test-first and run focused tests after each red/green cycle.
- Preserve public `StatementResult`, `Transaction`, discovery summary, row summary, JSON, and CSV schemas.
- Preserve transaction ordering, reconciliation group ordering, diagnostic strings and ordering, semantic claims, source evidence, and confidence calculations.
- Do not loosen bounded continuation detectors or merge their domain-specific negative checks.
- Do not add document-, issuer-, filename-, path-, hash-, merchant-, date-, amount-, or total-specific production branches.
- Keep the public `strict` parsing parameter intact as a compatibility surface.
- Keep all financial arithmetic in the shared exact `Decimal` module.
- A move is incomplete until the old implementation has been removed and `rg` proves there is one owner.

---

### Task 1: Internal Reconciliation Outcome and Single Public Result Assembly

**Files:**
- Modify: `src/ccparser/reconcile.py`
- Modify: `src/ccparser/normalize.py:48-75,3500-3530`
- Modify: `src/ccparser/parser.py:286-304,376-422`
- Test: `tests/test_reconcile.py`
- Test: `tests/test_normalize.py`
- Test: `tests/test_parser.py`

**Interfaces:**
- Produces: `RejectedTransaction`
- Produces: `ReconciliationOutcome`
- Produces: `reconciliation_outcome(transactions, printed_totals) -> ReconciliationOutcome`
- Preserves: `reconcile(transactions, printed_totals) -> StatementResult`

- [ ] **Step 1: Characterize accepted and rejected membership explicitly**

Add focused cases for duplicate transaction IDs, zero group memberships, multiple group
memberships, unknown groups, currency mismatch, transaction ambiguity, duplicate totals,
and no totals. For each case assert:

- public `reconcile()` returns exactly the same status, emitted transactions, groups, and
  diagnostic strings as today;
- accepted transactions retain input order;
- every rejected occurrence records its transaction ID and exact rejection diagnostic;
- a duplicate ID does not become ambiguous merely because IDs alone cannot distinguish
  two occurrences.

Add a parser regression that captures the complete `StatementResult` for the existing
case where `normalization.transactions` includes a transaction rejected from direct
reconciliation membership. Assert canonical JSON bytes before and after the migration.

- [ ] **Step 2: Run the new outcome tests and verify the interface is missing**

Run: `.venv/bin/pytest -q tests/test_reconcile.py tests/test_parser.py -k 'outcome or rejected_membership or unfiltered'`

Expected: FAIL because `ReconciliationOutcome` and `reconciliation_outcome` do not exist.

- [ ] **Step 3: Implement the internal immutable models**

Use frozen Pydantic models so normalization can retain its current `model_copy` update
style and all fields remain typed:

```python
class RejectedTransaction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    transaction_id: str
    input_index: int = Field(ge=0)
    diagnostic: str


class ReconciliationOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Status
    accepted_transaction_ids: tuple[str, ...]
    accepted_transaction_indices: tuple[int, ...]
    rejected_transactions: tuple[RejectedTransaction, ...]
    groups: tuple[ReconciliationGroup, ...]
    diagnostics: tuple[str, ...]
```

Move the current reconciliation algorithm to a private tuple-based implementation used
by `reconciliation_outcome`. Record an accepted input index or a rejection at the exact
branch that currently emits or skips the transaction. Do not infer acceptance from
transaction IDs after the loop; duplicate occurrences must remain distinguishable.

- [ ] **Step 4: Preserve direct reconciliation as a thin compatibility wrapper**

Implement `reconcile()` by materializing the input iterable once, calling the same
private outcome implementation once, and selecting transactions by
`accepted_transaction_indices` into `StatementResult`. The public
`reconciliation_outcome()` wrapper also materializes once. Run all reconciliation tests
and compare the old and new result dumps in the new matrix.

- [ ] **Step 5: Use the internal outcome through normalization and parser orchestration**

- Change `StatementNormalization.reconciliation` to `ReconciliationOutcome`.
- Call `reconciliation_outcome` from normalization and retain the current behavior that
  normalization diagnostics force unreconciled status and are appended to outcome
  diagnostics.
- Change `_is_exact_unambiguous` to inspect the outcome and
  `normalization.transactions`, not a partially public result.
- Build the public `StatementResult` once, in parser, from
  `normalization.transactions`, the outcome groups, and the existing merged diagnostics.
- Keep the not-statement and unsupported early results unchanged.

- [ ] **Step 6: Run focused and full verification**

Run: `.venv/bin/pytest -q tests/test_reconcile.py tests/test_normalize.py tests/test_parser.py tests/test_output.py`

Expected: all tests pass and canonical JSON/CSV output is unchanged.

Run: `.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy src && .venv/bin/pytest -q`

Expected: all commands exit 0.

- [ ] **Step 7: Commit single-result reconciliation**

```bash
git add src/ccparser/reconcile.py src/ccparser/normalize.py src/ccparser/parser.py tests/test_reconcile.py tests/test_normalize.py tests/test_parser.py tests/test_output.py
git commit -m "refactor: model internal reconciliation outcomes"
```

### Task 2: Exact Typed Row Tags Without Diagnostic Substrings

**Files:**
- Create: `src/ccparser/layout/row_tags.py`
- Create: `tests/layout/test_row_tags.py`
- Modify: `src/ccparser/discovery.py`
- Modify: `src/ccparser/normalize.py`
- Modify: `src/ccparser/fx.py`
- Test: `tests/test_discovery.py`
- Test: `tests/test_normalize.py`
- Test: `tests/test_fx.py`

**Interfaces:**
- Produces: `RowTag(StrEnum)`
- Produces: `row_tags(row: Row) -> frozenset[RowTag]`
- Produces: `has_row_tag(row: Row, tag: RowTag) -> bool`
- Produces: `is_structural_continuation(row: Row) -> bool`

- [ ] **Step 1: Add the exact diagnostic-to-tag contract**

Cover these existing diagnostics and no others:

```python
class RowTag(StrEnum):
    DESCRIPTION_CONTINUATION = "description_continuation"
    SUBORDINATE_DETAIL = "subordinate_detail_continuation"
    AUXILIARY_CONTINUATION = "subordinate_auxiliary_continuation"
    LEADING_SUBORDINATE_DETAIL = "leading_subordinate_detail_continuation"
    FOREIGN_CONVERSION_DETAIL = "foreign_conversion_detail_block"
    CARD_IDENTIFIER_DETAIL = "bounded_card_identifier_detail_block"
    HEBREW_NOTE_DETAIL = "bounded_hebrew_note_detail"
```

`DESCRIPTION_CONTINUATION` is structural state produced while scanning and deliberately
has no legacy diagnostic mapping. Assert duplicate diagnostics produce one tag, unrelated diagnostics produce none, and
diagnostics such as `continuation`, `not_a_continuation`,
`ambiguous_description_continuation`, and `continuation_rows:2` do not become tags.

- [ ] **Step 2: Add the broad-substring regression**

Create a billed row with an unrelated diagnostic containing `continuation`. Assert it
still contributes to discovery's billed amounts and normalization's stable-unknown
analysis. This should fail at the two current `any("continuation" in diagnostic ...)`
checks.

- [ ] **Step 3: Implement the adapter and run its unit tests**

Run before implementation: `.venv/bin/pytest -q tests/layout/test_row_tags.py`

Expected: FAIL during collection with `ModuleNotFoundError`.

Implement an explicit legacy-diagnostic mapping table, ignoring unknown strings. Define
`is_structural_continuation` as exactly subordinate detail, auxiliary continuation, or
leading subordinate detail; the descriptive/foreign/card/note tags do not broaden that
legacy predicate. Keep tags derived rather than adding a serialized `Row` field, so the
public layout model and diagnostic output stay unchanged.

- [ ] **Step 4: Migrate all structural consumers**

Replace exact literals and substring checks in discovery, normalization, FX, and
cross-page handoff with tag checks. Keep diagnostic creation in `layout/regions.py`
unchanged. When handoff converts a leading tag to a subordinate tag, continue rewriting
the existing diagnostic value so emitted diagnostics remain identical.

Use `is_structural_continuation` only for the former broad checks. Keep geometric
description-continuation detection in normalization because it has no diagnostic tag.

- [ ] **Step 5: Prove raw strings no longer drive structural decisions**

Run:

```bash
rg -n '"continuation" in diagnostic|"subordinate_detail_continuation" (in|not in) .*diagnostics|"subordinate_auxiliary_continuation" (in|not in) .*diagnostics|"leading_subordinate_detail_continuation" (in|not in) .*diagnostics' src/ccparser
```

Expected: no consumer matches. Diagnostic emission and exact rewrite sites may remain.

- [ ] **Step 6: Run focused and full verification**

Run: `.venv/bin/pytest -q tests/layout/test_row_tags.py tests/test_discovery.py tests/test_normalize.py tests/test_fx.py tests/test_parser.py`

Expected: all focused tests pass with unchanged serialized diagnostics.

Run: `.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy src && .venv/bin/pytest -q`

Expected: all commands exit 0.

- [ ] **Step 7: Commit typed row tags**

```bash
git add src/ccparser/layout/row_tags.py src/ccparser/discovery.py src/ccparser/normalize.py src/ccparser/fx.py tests/layout/test_row_tags.py tests/test_discovery.py tests/test_normalize.py tests/test_fx.py tests/test_parser.py
git commit -m "refactor: replace diagnostic substring state with row tags"
```

### Task 3: One Continuation-Match Contract

**Files:**
- Create: `src/ccparser/layout/continuations.py`
- Create: `tests/layout/test_continuations.py`
- Modify: `src/ccparser/layout/regions.py:1540-2130,2650-2810`
- Test: `tests/layout/test_regions.py`

**Interfaces:**
- Produces: `ContinuationKind(StrEnum)`
- Produces: `DetailContinuationPolicy(StrEnum)`
- Produces: `ContinuationMatch`
- Produces: `single_row_match(...) -> ContinuationMatch`

- [ ] **Step 1: Add model tests for the common return contract**

```python
class ContinuationKind(StrEnum):
    DESCRIPTION = "description"
    LEADING_DETAIL = "leading_detail"
    CARD_IDENTIFIER_BLOCK = "card_identifier_block"
    CARD_IDENTIFIER_TAIL = "card_identifier_tail"
    FOREIGN_CONVERSION_BLOCK = "foreign_conversion_block"
    HEBREW_NOTE = "hebrew_note"
    AUXILIARY_FRAGMENT = "auxiliary_fragment"
    MARKED_DETAIL = "marked_detail"


class DetailContinuationPolicy(StrEnum):
    PRESERVE = "preserve"
    DISALLOW = "disallow"


@dataclass(frozen=True, slots=True)
class ContinuationMatch:
    rows: tuple[Row, ...]
    consumed_through: int
    kind: ContinuationKind
    row_tags: frozenset[RowTag]
    detail_policy: DetailContinuationPolicy
    skipped_outside_rows: int = 0
```

Test nonempty rows, nonnegative skipped count, `consumed_through >= start_index`, exact
row tags, each detail policy, and the single-row constructor. Invalid values must raise
`ValueError` at construction. Description continuations carry
`RowTag.DESCRIPTION_CONTINUATION` with `PRESERVE`; bounded detail matches carry their
exact tags and `DISALLOW`.

- [ ] **Step 2: Run model tests and verify the module is missing**

Run: `.venv/bin/pytest -q tests/layout/test_continuations.py`

Expected: FAIL during collection with `ModuleNotFoundError`.

- [ ] **Step 3: Characterize each bounded detector at its current boundary**

For leading detail, card identifier block/tail, foreign conversion block, Hebrew note,
auxiliary fragment, and marked detail, add or extend tests asserting the exact returned
rows, diagnostics, consumed index, and skipped-outside count. Include every existing
negative case: excessive gaps, foreign currency mismatch, extra shapes, ambiguous
single-cell markers, invalid card identifiers, and lookahead limits.

- [ ] **Step 4: Migrate detector returns one at a time**

Change each successful detector to return `ContinuationMatch`; keep `None` for no match.
For former single-row returns, set `consumed_through` to the current source index. For
former tuples, copy the existing index and skipped count without recalculation. Convert
the successful Boolean description/marked-detail branches into `single_row_match`
objects at the call site; their recognition predicates remain Boolean and distinct.
Run only that detector's tests after each migration.

- [ ] **Step 5: Centralize scan-side application without centralizing recognition**

Add one private `_apply_continuation_match` that extends accepted rows, advances the
consumed index, updates the correct diagnostic counter by `kind`, applies the explicit
detail policy, adds skipped rows, and returns the new previous row. The bounded detectors
retain all current semantic and geometric checks.

- [ ] **Step 6: Run focused and full verification**

Run: `.venv/bin/pytest -q tests/layout/test_continuations.py tests/layout/test_regions.py tests/test_discovery.py tests/test_normalize.py tests/test_fx.py`

Expected: all tests pass with identical `TableRegion` values and diagnostic ordering.

Run: `.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy src && .venv/bin/pytest -q`

Expected: all commands exit 0.

- [ ] **Step 7: Commit the match contract**

```bash
git add src/ccparser/layout/continuations.py src/ccparser/layout/regions.py tests/layout/test_continuations.py tests/layout/test_regions.py tests/test_discovery.py tests/test_normalize.py tests/test_fx.py
git commit -m "refactor: standardize continuation matches"
```

### Task 4: Explicit Region Scan State

**Files:**
- Modify: `src/ccparser/layout/regions.py:2417-2910`
- Create: `tests/layout/test_region_scan_state.py`
- Modify: `tests/layout/test_regions.py`
- Test: `tests/test_discovery.py`

**Interfaces:**
- Produces internally: `_RegionScanCounters`
- Produces internally: `_RegionScanState`
- Preserves: `_detect_from_header(...) -> tuple[TableRegion | None, int]`
- Preserves: `_inherited_region_after_total(...) -> tuple[TableRegion | None, int]`

- [ ] **Step 1: Snapshot public region behavior before changing the scanner**

Parameterize representative cases for ordinary rows, description continuations,
leading details, each bounded detail detector, preambles, outside-band rows, OCR overlays,
spilled currency, complementary rows, ambiguous leading rows, points ledgers, structural
gaps, new headers, totals, page-end continuation, and inherited post-total regions.
Serialize each resulting `TableRegion` with a deterministic test-only tuple containing
its bbox, rows, schema, confidence, diagnostics, and returned stop index.

- [ ] **Step 2: Add state transition unit tests before implementing state**

Assert these transitions independently:

- ignore increments only the named counter and leaves `previous` unchanged when current
  behavior does;
- accepting regular rows updates accepted/regular rows and permits one detail match;
- accepting a detail match consumes through its index, disables detail matching, and
  chooses its last row as previous;
- stopping records the first reason/index and cannot be overwritten;
- diagnostic projection preserves today's fixed ordering, regardless of transition order.

Run: `.venv/bin/pytest -q tests/layout/test_region_scan_state.py`

Expected: FAIL because `_RegionScanState` does not exist.

- [ ] **Step 3: Introduce state as a behaviorless representation first**

Create frozen `_RegionScanCounters` with explicit increment methods and mutable-slotted
`_RegionScanState` for scan progress. Its methods should encode only assignments already
performed by the loops: `ignore`, `accept_regular`, `accept_description`,
`accept_continuation`, and `stop`. Do not put recognition predicates into the state.

- [ ] **Step 4: Refactor `_detect_from_header` in ordered blocks**

Replace local variables with state in this order, running snapshot tests after each
block: boundary stops, projection/ignores, preamble, bounded continuation matches,
description/marked continuation, spilled currency/complementary rows, regular-row
acceptance, final strength checks, and diagnostic construction. Keep handler order exact;
the first matching rule remains authoritative.

- [ ] **Step 5: Apply the same state to compatible inherited scanning**

Use the state for shared counters and transitions in `_inherited_region_after_total`,
while keeping its stronger date/shape checks, total-overlay behavior, and success proof
separate. Do not force both scanners into one configurable function.

- [ ] **Step 6: Compare every snapshot and remove superseded locals**

Run: `.venv/bin/pytest -q tests/layout/test_region_scan_state.py tests/layout/test_regions.py`

Expected: every serialized region and stop index matches its pre-refactor fixture. Use
`rg` to confirm the duplicate counter-update blocks have been removed.

- [ ] **Step 7: Run full verification and commit**

Run: `.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy src && .venv/bin/pytest -q`

Expected: all commands exit 0.

```bash
git add src/ccparser/layout/regions.py tests/layout/test_region_scan_state.py tests/layout/test_regions.py tests/test_discovery.py
git commit -m "refactor: make region scan state explicit"
```

### Task 5: Typed Row-Normalization Context and Simple Field Outcomes

**Files:**
- Create: `src/ccparser/normalization_fields.py`
- Create: `tests/test_normalization_fields.py`
- Modify: `src/ccparser/normalize.py:2750-3260`
- Test: `tests/test_normalize.py`
- Test: `tests/test_semantic_evidence.py`

**Interfaces:**
- Produces: `BilledFields`
- Produces: `InstallmentFields`
- Produces: `extract_billed_fields(...) -> BilledFields`
- Produces: `extract_installment_fields(...) -> InstallmentFields`
- Produces: `is_installment_shaped(text: str) -> bool`
- Produces internally: `_RowNormalizationContext`
- Produces internally: `_RowNormalizationAttempt`

- [ ] **Step 1: Characterize every early return in `_normalize_row`**

Parameterize missing/duplicate amount columns, missing/duplicate amount cells, generic
currency conflicts, missing/duplicate/unknown billing currency, unparseable billed
amount, and zero billed amount. For each case assert the complete
`RowNormalizationResult`: bbox, raw text, evidence order, confidence, transaction, and
diagnostics. Add installment cases for absent, duplicate, missing, multiple, malformed,
valid, and current-greater-than-total values.

- [ ] **Step 2: Add focused tests for typed extraction outcomes**

Use these contracts:

```python
@dataclass(frozen=True, slots=True)
class BilledFields:
    amount: Decimal | None
    currency: str | None
    amount_cell: Cell | None
    confidence: float
    diagnostics: tuple[str, ...]
    disposition: FieldDisposition


@dataclass(frozen=True, slots=True)
class InstallmentFields:
    current: int | None
    total: int | None
    diagnostics: tuple[str, ...]
```

`FieldDisposition` distinguishes `ACCEPT`, `REJECT_ROW`, and `IGNORE_ROW` so zero rows do
not rely on a magic diagnostic comparison. Run the new tests and confirm the module
import fails.

- [ ] **Step 3: Extract billed and installment logic with no behavior changes**

Move only role lookup, column association, currency validation, amount parsing, and
installment parsing needed by these two outcomes. Pass the group's printed currency as
an explicit input. Return diagnostics in existing order and retain the current billed
confidence source.

- [ ] **Step 4: Add a local row context to remove repeated result construction**

`_RowNormalizationContext` owns the base row tuple, evidence, raw text, and accumulated
diagnostics. Its `rejected_attempt`, `ignored_attempt`, and `completed_attempt` methods
construct an internal `_RowNormalizationAttempt(result, disposition)` using the exact
current confidence rules. It does not perform extraction and is not exported.

- [ ] **Step 5: Migrate `_normalize_row` to the outcomes and context**

Change `_normalize_row` to return `_RowNormalizationAttempt`; it is private and has one
production caller. Replace the repeated early-return blocks first, then installment extraction at the end.
Keep description, dates, original amount, FX, semantic claims, category, and transaction
construction in their current order. Update `normalize_statement` to use disposition
rather than comparing `("noncontributing_zero_billed_row",)` when counting unemitted
rows, and append `attempt.result` to the public row results; preserve the public row diagnostic.

- [ ] **Step 6: Run focused and full verification**

Run: `.venv/bin/pytest -q tests/test_normalization_fields.py tests/test_normalize.py tests/test_semantic_evidence.py tests/test_discovery.py tests/test_parser.py`

Expected: all focused tests pass and every characterized `RowNormalizationResult` is
unchanged.

Run: `.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy src && .venv/bin/pytest -q`

Expected: all commands exit 0.

- [ ] **Step 7: Commit typed simple-field extraction**

```bash
git add src/ccparser/normalization_fields.py src/ccparser/normalize.py tests/test_normalization_fields.py tests/test_normalize.py tests/test_semantic_evidence.py tests/test_discovery.py tests/test_parser.py
git commit -m "refactor: type row normalization outcomes"
```

### Task 6: Extract Original-Amount Normalization as One Focused Domain Module

**Files:**
- Create: `src/ccparser/original_amount.py`
- Create: `tests/test_original_amount.py`
- Modify: `src/ccparser/normalize.py:1700-2100,2820-3070`
- Test: `tests/test_normalize.py`
- Test: `tests/test_semantic_evidence.py`

**Interfaces:**
- Produces: `OriginalAmountExtraction`
- Produces: `extract_original_amount(...) -> OriginalAmountExtraction`

- [ ] **Step 1: Build an exhaustive extraction matrix from existing scenarios**

Cover no original column, duplicate original columns, missing/multiple original cells,
negative adjustments without an original value, explicit and implicit currency columns,
currency spilled into location, unknown currency, direct parses, OCR corroboration,
subordinate-detail recovery, exact boundary-word recovery, description spill on both
sides, bounded-note recovery, conflicting candidates, and unparseable values. Assert:

- amount and currency;
- ordered diagnostics;
- description replacement/extension and direction;
- exact semantic evidence claims added for description spill.

First run these assertions through the current `_normalize_row` path to capture behavior.

- [ ] **Step 2: Add the focused return model tests and verify the import fails**

```python
@dataclass(frozen=True, slots=True)
class OriginalAmountExtraction:
    amount: Decimal | None
    currency: str | None
    description: str | None
    claims: tuple[EvidenceClaim, ...]
    diagnostics: tuple[str, ...]
```

Run: `.venv/bin/pytest -q tests/test_original_amount.py`

Expected: FAIL during collection because `ccparser.original_amount` does not exist.

- [ ] **Step 3: Move the cohesive recovery cluster, not callbacks**

Move the original-amount helpers and constants they exclusively need into
`original_amount.py`. Import shared geometry, column association, token, money, layout,
and semantic-evidence APIs directly. Do not make a generic callback bag back into
`normalize.py`; if a helper is genuinely shared, move it to the smallest neutral module
and test it there.

- [ ] **Step 4: Replace the inline block with one typed extraction call**

Pass the row, continuation rows, region, ledger, billing parse, current description, and
initial semantic claims explicitly. Merge returned claims and diagnostics in the same
position as today, then run conversion-date and FX extraction unchanged.

- [ ] **Step 5: Remove the old helper cluster and prove one owner remains**

Use `rg` on every moved helper name. Expected: one definition in
`original_amount.py`, imports/calls where intended, and no forwarding wrappers in
`normalize.py` unless a private test import is temporarily preserved and explicitly
scheduled for removal in this task.

- [ ] **Step 6: Run focused and full verification**

Run: `.venv/bin/pytest -q tests/test_original_amount.py tests/test_normalize.py tests/test_semantic_evidence.py tests/test_fx.py tests/test_discovery.py tests/test_parser.py`

Expected: all extraction matrix cases and integration tests pass.

Run: `.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy src && .venv/bin/pytest -q`

Expected: all commands exit 0.

- [ ] **Step 7: Commit original-amount extraction**

```bash
git add src/ccparser/original_amount.py src/ccparser/normalize.py tests/test_original_amount.py tests/test_normalize.py tests/test_semantic_evidence.py tests/test_fx.py tests/test_discovery.py tests/test_parser.py
git commit -m "refactor: isolate original amount normalization"
```

### Task 7: Typed Date and Description Extraction Boundaries

**Files:**
- Create: `src/ccparser/normalization_dates.py`
- Create: `src/ccparser/normalization_description.py`
- Create: `tests/test_normalization_dates.py`
- Create: `tests/test_normalization_description.py`
- Modify: `src/ccparser/normalize.py:623-1029,1214-1746,2063-2510,2919-3260`
- Test: `tests/test_normalize.py`
- Test: `tests/test_semantic_evidence.py`
- Test: `tests/test_discovery.py`

**Interfaces:**
- Produces: `DateExtraction`
- Produces: `ConversionDateExtraction`
- Produces: `extract_dates(...) -> DateExtraction`
- Produces: `extract_conversion_date(...) -> ConversionDateExtraction`
- Produces: `extract_description(...) -> DescriptionExtraction`
- Produces: `is_description_continuation(...) -> bool`

- [ ] **Step 1: Characterize date extraction as a complete typed value**

Build a focused matrix for full and short dates, all six supported styles, OCR-spaced
tokens, contaminated cells, overlapping boundary glyphs, two date columns, inferred
column kinds, unanchored dates, posting/transaction order, embedded conversion dates,
fragmented cross-cell dates, conflicting conversion evidence, and invalid dates. Assert
the current five `_dates` outputs and the three semantic conversion-date outputs,
including source-cell identity and ordered diagnostics.

- [ ] **Step 2: Add failing unit tests for date result models**

```python
@dataclass(frozen=True, slots=True)
class DateExtraction:
    transaction_date: date | None
    posting_date: date | None
    conversion_date: date | None
    diagnostics: tuple[str, ...]
    unresolved_conversion_cells: tuple[Cell, ...]


@dataclass(frozen=True, slots=True)
class ConversionDateExtraction:
    value: date | None
    diagnostics: tuple[str, ...]
    source_cells: frozenset[Cell]
```

Run: `.venv/bin/pytest -q tests/test_normalization_dates.py`

Expected: FAIL during collection because `ccparser.normalization_dates` does not exist.

- [ ] **Step 3: Move the cohesive date cluster behind the typed results**

Move date parsing, cell/OCR recovery, short-date proof, boundary completion, the
date/description boundary split (which itself depends on date parsing), structural
date-column classification, `_dates`, conversion-date semantic extraction, and
cross-cell date helpers to `normalization_dates.py`. Consume the shared date-token,
geometry, column-association, token, layout, and semantic-ledger APIs directly. Keep
year-context inference in discovery. Preserve every validation order and diagnostic.

- [ ] **Step 4: Characterize and extract description behavior**

Before moving code, cover ordinary descriptions, RTL/LTR ordering, boundary date splits,
continuation rows, processor references, adjacent unknown columns, competing clusters,
punctuation, empty descriptions, and semantic claims. Run the new tests first and verify
the description module import fails.

Move the remaining description-continuation geometry, clustering, processor-reference proof, and
`_description` implementation to `normalization_description.py`. Reuse the existing
`DescriptionExtraction` model rather than creating a second result vocabulary. Do not
move transaction category inference; it remains an orchestration step after installment
and sign are known. Import the supported boundary-split helper from
`normalization_dates` and the installment-shape predicate from `normalization_fields`, so
the two new modules have a one-way dependency and no duplicated regex.

- [ ] **Step 5: Replace tuple unpacking in `_normalize_row`**

Use `DateExtraction` and `ConversionDateExtraction` attributes explicitly. Call
`extract_description` in the same position as today, then merge claims and diagnostics
without reordering. Import `is_description_continuation` in continuation ownership code.

- [ ] **Step 6: Remove moved definitions and verify ownership**

Use `rg` on `_parse_date`, `_parse_cell_date`, `_dates`,
`_conversion_date_from_semantic_evidence`, `_cross_cell_date_tokens`, `_description`,
`_primary_description_cluster`, and `_is_boundary_description_continuation`. Expected:
one definition in the new focused module for each behavior, with no forwarding copy in
`normalize.py`.

- [ ] **Step 7: Run focused and full verification**

Run: `.venv/bin/pytest -q tests/test_normalization_dates.py tests/test_normalization_description.py tests/test_normalize.py tests/test_semantic_evidence.py tests/test_discovery.py tests/test_parser.py`

Expected: all focused tests pass and normalized transactions/row results are unchanged.

Run: `.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy src && .venv/bin/pytest -q`

Expected: all commands exit 0.

- [ ] **Step 8: Commit date and description boundaries**

```bash
git add src/ccparser/normalization_dates.py src/ccparser/normalization_description.py src/ccparser/normalize.py tests/test_normalization_dates.py tests/test_normalization_description.py tests/test_normalize.py tests/test_semantic_evidence.py tests/test_discovery.py tests/test_parser.py
git commit -m "refactor: isolate date and description normalization"
```

### Task 8: Typed Semantic-Claim Validation Boundary

**Files:**
- Create: `src/ccparser/normalization_semantics.py`
- Create: `tests/test_normalization_semantics.py`
- Modify: `src/ccparser/normalize.py:332-610,2288-2651,2919-3260`
- Test: `tests/test_semantic_evidence.py`
- Test: `tests/test_normalize.py`

**Interfaces:**
- Produces: `SemanticValidation`
- Produces: `assignment_diagnostics(...) -> tuple[str, ...]`
- Produces: `role_contract_diagnostics(...) -> tuple[str, ...]`
- Produces: `validate_transaction_semantics(...) -> SemanticValidation`

- [ ] **Step 1: Characterize semantic ownership and diagnostic order**

Extend the semantic-evidence matrix so every `SemanticOwner` is exercised and assert the
exact claim atom IDs, unclaimed high-confidence atoms, description-boundary atoms,
stable/unstable unknown columns, safe card identifiers, layout-noise cells, category and
ancillary unknown columns, fragmented conversion dates, and ordered diagnostics. Include
both valid and deliberately unresolved rows.

- [ ] **Step 2: Add the typed validation model test and verify the import fails**

```python
@dataclass(frozen=True, slots=True)
class SemanticValidation:
    claims: tuple[EvidenceClaim, ...]
    diagnostics: tuple[str, ...]
```

Run: `.venv/bin/pytest -q tests/test_normalization_semantics.py`

Expected: FAIL during collection because `ccparser.normalization_semantics` does not
exist.

- [ ] **Step 3: Move the semantic proof cluster as one responsibility**

Move assignment diagnostics, role-contract diagnostics, relevant/noise cell predicates,
stable and explicit unknown-column analysis, claim-addition helpers, financial/date atom
matching, and `_semantic_claims_and_diagnostics` to
`normalization_semantics.py`. Import date-source helpers from `normalization_dates` and
accept initial claims from prior description, original-amount, and FX extraction; do not
create an import of those field modules or a reverse import into `normalize.py`.

- [ ] **Step 4: Replace the discarded tuple return with explicit validation**

Call `validate_transaction_semantics`, append its diagnostics in the same location, and
retain its claims for testability even if transaction construction needs only the
diagnostics. `normalize.py` remains responsible for sequencing field extraction,
category/sign validation, transaction construction, confidence, group iteration, and
cross-page ownership.

- [ ] **Step 5: Remove old semantic helpers and check dependency direction**

Use `rg` and import smoke tests to inspect module direction. Expected dependency
direction is primitives/layout/semantic ledger → focused
normalization modules → `normalize.py`; no focused module imports `normalize.py`.

- [ ] **Step 6: Run focused and full verification**

Run: `.venv/bin/pytest -q tests/test_normalization_semantics.py tests/test_semantic_evidence.py tests/test_normalize.py tests/test_normalization_fields.py tests/test_original_amount.py tests/test_normalization_dates.py tests/test_normalization_description.py tests/test_parser.py`

Expected: all focused tests pass with identical transaction ambiguities and row
diagnostics.

Run: `.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy src && .venv/bin/pytest -q`

Expected: all commands exit 0.

- [ ] **Step 7: Commit the semantic boundary**

```bash
git add src/ccparser/normalization_semantics.py src/ccparser/normalize.py tests/test_normalization_semantics.py tests/test_semantic_evidence.py tests/test_normalize.py tests/test_parser.py
git commit -m "refactor: isolate transaction semantic validation"
```

### Task 9: End-to-End Behavior and Coverage Gate

**Files:**
- Modify only if a gap is found: focused tests under `tests/`
- Do not modify production code in this task unless a new red/green cycle is started

- [ ] **Step 1: Compare canonical public projections**

Run the parser/output characterization matrix for statement, ambiguous, not-statement,
multi-group, rejected membership, rollover year, FX details, cross-page continuation,
OCR repair, and audit cases. Compare complete Pydantic model equality, canonical JSON
bytes, and CSV header/value ordering against the fixtures recorded before both plans.

- [ ] **Step 2: Verify module ownership and absence of old patterns**

Run targeted `rg` checks for:

- private Decimal arithmetic and duplicate Decimal formatters;
- raw FX substring cue matching;
- duplicate date style/pattern maps;
- duplicate geometry formulas and column association;
- duplicate safe-relative-path/PDF walkers;
- diagnostic continuation substring control flow;
- heterogeneous bounded continuation tuple returns;
- parser-owned summary adapters;
- moved original-amount helpers in `normalize.py`;
- moved date, description, and semantic-claim helpers in `normalize.py`;
- the removed unused parameters and helpers.

Review every remaining match and document why it is a domain-specific rule rather than a
duplicate mechanic.

- [ ] **Step 3: Run coverage and inspect regressions**

Run: `.venv/bin/pytest --cov=ccparser --cov-report=term-missing -q`

Expected: all tests pass, total line coverage is at least the pre-change 93%, and no new
module has an untested behavior branch. Add focused tests—not exclusions—for any loss.

- [ ] **Step 4: Run the repository-required verification from a clean process**

Run each command separately and retain its exit code/output:

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
```

Expected: all four commands exit 0.

- [ ] **Step 5: Inspect the final diff for accidental scope**

Run: `git status --short && git diff --stat && git diff --check && git diff`

Confirm there are no private statement files, derived financial data, generated caches,
diagnostic/schema renames, threshold changes, or unrelated user edits.

- [ ] **Step 6: Commit only any final test hardening**

If this gate added tests, commit them separately:

```bash
git add tests
git commit -m "test: lock parser simplification behavior"
```

If no files changed, do not create an empty commit.
