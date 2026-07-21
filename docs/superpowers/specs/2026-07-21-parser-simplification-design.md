# Behavior-Preserving Parser Simplification Design

## Goal

Simplify and generalize the parser without weakening its conservative extraction,
evidence, or reconciliation guarantees. Remove duplicated mechanisms, make hidden
state explicit, and centralize financial correctness rules while preserving every
current public JSON/CSV field and diagnostic string.

The work is deliberately staged. Shared correctness primitives come first; larger
orchestration changes consume those primitives only after their behavior is fixed by
focused characterization tests.

## Constraints

- Use Python 3.13 and the repository `.venv`.
- Develop every production behavior test-first and run the repository verification
  gates before each task is considered complete.
- Keep all financial arithmetic in `Decimal` and make it independent of the active
  Decimal context.
- Do not add document-, issuer-, filename-, path-, hash-, merchant-, date-, amount-,
  or total-specific production branches.
- Preserve public model fields, JSON keys, CSV columns and ordering, diagnostic
  strings, transaction ordering, source evidence, and deterministic output.
- Keep private documents and derived financial data local and outside Git.
- Keep the public `strict` parsing parameter as a compatibility surface; the CLI
  continues to own strict exit-code behavior.

## Considered Approaches

### Mechanical cleanup only

Delete unused helpers and move repeated formulas into utility modules without
changing orchestration. This is low risk, but it leaves the context-sensitive
Decimal defect, duplicate result construction, string-encoded row state, and large
implicit region scanner untouched.

### Layered behavior-preserving refactor

First introduce shared exact arithmetic, lexical, date, geometry, column-association,
and path primitives. Then replace duplicate orchestration representations and hidden
row state behind typed internal outcomes. Each step retains existing public output and
has its own red-green test cycle.

This is the selected approach. It removes the most duplication without a parser
rewrite and gives every later structural change a stable, tested foundation.

### Parser rewrite

Replace discovery, layout scanning, and normalization with a new declarative rule
engine in one change. This could reduce apparent line count, but it would discard a
large body of carefully bounded negative rules and make corpus regressions difficult
to localize. It is rejected.

## Phase 1: Correctness and Shared Foundations

### Exact Decimal core

Create a dependency-neutral internal module that owns:

- finite Decimal validation;
- exact context-independent sum and difference;
- exact minor-unit divisibility;
- canonical plain-decimal formatting.

Reconciliation, FX derivation and validation, discovery singleton matching, public
model serializers, and CSV output must use these functions. Large coefficients and a
low active Decimal precision must produce exactly the same values as the default
context. The change must fix the current case where a rounded derived fee can be
accepted while the mathematically exact fee is rejected.

### Text and phrase matching

Create shared NFC whitespace normalization, phrase tokenization, and contiguous token
sequence matching. Money parsing, normalization, and FX cue recognition use the
shared token policy. Discovery retains its acronym-quote behavior through an explicit
normalization option rather than a silent semantic difference.

Substring matches are not semantic matches: words such as `coffee` and `corporate`
must not satisfy the cues `fee` and `rate`.

### Date-token policy

Move the lexical date layer into a neutral module:

- `DateTokenStyle`;
- the six day-first/year-first separator configurations;
- generated full- and short-year token patterns;
- supported full-year bounds;
- pure suffix-to-year mapping validation.

Discovery continues to infer year context; normalization continues to assign semantic
date roles; layout and OCR continue to choose their own explicit acceptance policies.
The shared module must not make an unanchored short date authoritative.

### Geometry and column association

Create pure bbox helpers for width, height, center, union, intersection-over-union,
intersection-over-smaller, vertical overlap, and center containment. Preserve current
behavior for degenerate boxes during the mechanical migration.

Expose one deterministic center-in-column association helper and one role-based
column selector. Migrate repeated formulas without merging intentionally different
line-clustering algorithms or proof thresholds.

Add finite and ordered geometry validation only after tests characterize current
synthetic and extracted evidence. Page containment remains tolerant because rotated
or degraded evidence may extend slightly beyond page bounds.

### Filesystem primitives

Create one path module for safe relative POSIX paths, resolved containment/overlap,
and deterministic regular-PDF walking. Parser and audit retain their own exception
translation and pass their different exclusion policies explicitly. Walk errors must
not silently omit an audit subtree.

### Mechanical cleanup

Remove only demonstrably unused helpers and parameters. Reuse already-selected glyphs
and words instead of rescanning the same bbox. Move public-summary projection out of
parser orchestration without replacing explicit typed conversion with reflection.

## Phase 2: Explicit Pipeline Outcomes

### Reconciliation outcome

Replace the internal `StatementResult` returned by reconciliation with a frozen
`ReconciliationOutcome` containing:

- reconciliation groups;
- status and diagnostics;
- accepted transaction IDs;
- rejected transaction IDs and their reasons.

Normalization retains every recovered transaction for auditability. The public parser
assembles `StatementResult` once and preserves the current inspectable transaction
tuple, group contents, status, and diagnostics. A compatibility wrapper may preserve
the existing direct `reconcile()` return type if tests or external imports require it.

### Typed row state

Introduce a closed internal `RowTag` vocabulary for structural facts such as
description continuation, subordinate detail, auxiliary continuation, foreign detail,
and leading cross-page detail. Existing diagnostic strings remain unchanged and are
still serialized; structural decisions stop using substring checks over diagnostics.

During migration, a single adapter may derive tags from exact legacy diagnostic
values. No broad `"continuation" in diagnostic` rule remains after the phase.

### Region scan state

Keep the individual bounded semantic detectors and all their negative checks. Unify
only their traversal contract with a frozen match object carrying accepted rows,
consumed index, skipped outside-band count, row tags, and continuation state.

An explicit scan-state object owns counters, the previous row, the consumed boundary,
and stop reason. Header-driven and inherited-region scanners remain separate until
their genuinely shared mechanics are proven by characterization tests.

### Normalization decomposition

Keep `normalize.py` as the transaction orchestrator, but move billed/original amount,
date, description, installment, and evidence-claim steps behind small typed extraction
results. Do not introduce a permissive generic field extractor; field-specific proof
rules remain explicit.

## Data Flow

1. Evidence extraction emits validated positioned evidence.
2. Shared geometry and text primitives support layout without adding semantic policy.
3. Layout assigns explicit row tags and returns table regions.
4. Discovery associates regions and totals using shared date, currency, and exact
   Decimal primitives.
5. Normalization emits all recoverable transactions and a reconciliation outcome.
6. Parser constructs the public result exactly once.
7. Existing output adapters serialize the unchanged public schema deterministically.

## Error Handling and Compatibility

- Input and runtime exception types remain unchanged.
- Audit unreadable-subtree failures become explicit instead of silently incomplete.
- Existing diagnostic strings and ordering remain stable.
- Existing default-context outputs remain byte-identical unless they currently encode
  a context-rounded financial result, which is corrected to the exact value.
- OCR cache keys, command lines, and cache versions remain unchanged during plumbing
  cleanup.
- No public field is removed or replaced. New internal types are not exported from
  `ccparser.__init__`.

## Testing Strategy

Every task follows red-green-refactor:

1. Add a focused characterization or regression test and observe the intended
   failure where behavior changes.
2. Implement the smallest production change.
3. Run the focused test and the affected module suite.
4. Run the full repository verification gates before completion.

Required new coverage includes:

- low-precision Decimal contexts for FX validation, derivation, singleton matching,
  reconciliation, and formatting;
- negative token-boundary cases for fee and rate cues;
- all six date styles, suffix mappings, invalid calendar values, and OCR spacing;
- geometry degeneracy and inclusive column-boundary cases;
- parser/audit walker parity, symlinks, excluded roots, `.cache`, and walk errors;
- reconciliation accepted/rejected membership while public transactions remain
  inspectable;
- unrelated diagnostics containing `continuation` not affecting row ownership;
- every bounded continuation family and cross-page handoff;
- canonical JSON and CSV byte equality before and after each structural refactor.

Coverage should not fall below the current measured 93 percent line coverage. The OCR
repair fallback, currently the least-covered substantive module, receives targeted
negative tests before its private layout dependencies are changed.

## Acceptance Criteria

- Ruff format, Ruff lint, strict mypy, and all tests pass.
- Existing canonical JSON/CSV fixtures are byte-identical under the default Decimal
  context.
- Financial results are identical under low and default Decimal precision.
- No production decisions inspect filenames, paths, hashes, known documents, known
  merchants, or expected amounts.
- Public imports and parse call signatures remain compatible.
- Region and normalization behavior no longer depends on diagnostic substrings.
- Parser constructs the final public statement result once.
- The Git diff contains no private financial documents or generated parser output.
