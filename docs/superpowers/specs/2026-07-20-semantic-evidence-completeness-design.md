# Semantic Evidence Completeness Design

## Goal

Make transaction normalization semantically lossless for merchant descriptions and
conversion dates without weakening exact monetary extraction or reconciliation. A
strict parse must fail whenever meaningful transaction evidence cannot be assigned
unambiguously, even when billed amounts happen to sum to the printed total.

This design addresses Issues 1–3 from the 2026-07-20 independent review. Structured
FX rates and fees are explicitly deferred to a separate schema change.

## Constraints

- Production behavior derives from positioned evidence, inferred column roles,
  repeated row structure, and issuer-independent semantic rules.
- No filename, path, hash, date, merchant, amount, total, account, card, or issuer
  allowlist may influence extraction.
- Every financial value continues to use `Decimal`.
- Existing transaction capture, billed and original amounts, currencies, totals,
  deterministic output, and born-digital parsing remain unchanged.
- Public transaction and output schemas remain unchanged in this work.
- Private PDFs and derived financial output remain local and out of Git.

## Architecture

### Transaction evidence ledger

Add a focused internal module, `src/ccparser/semantic_evidence.py`, which turns the
cells belonging to one base transaction row and its accepted continuation rows into
a deterministic set of evidence atoms.

An atom is the smallest positioned unit that can be owned independently:

1. a non-whitespace glyph when glyph evidence exists;
2. otherwise a positioned word;
3. otherwise a normalized cell-text fragment for degraded or synthetic evidence.

Overlapping cells may contain the same source glyph. The ledger deduplicates those
copies using a stable identity built from page, geometry, origin, character, font,
and evidence source. Word and cell fallbacks use their corresponding stable page,
geometry, text, and source identity. Sequence indexes only break otherwise exact
ties, so output remains deterministic.

Each meaningful atom receives one disposition:

- an emitted transaction field such as description or conversion date;
- recognized ancillary evidence such as category, location, processor reference,
  or an FX detail deferred to the later schema change;
- a narrowly proven layout artifact;
- unresolved semantic evidence.

Claims record the owning semantic role and the evidence supporting the decision.
One atom may not be claimed by incompatible roles. Extracted values must have at
least one supporting claim. The ledger never treats an `unknown` column as harmless
merely because its text is non-financial.

### Integration boundary

`normalize.py` remains the transaction orchestrator but delegates evidence
accounting and spatial text operations to the new module. Existing amount,
installment, category, and reconciliation code is retained wherever it already has
the correct behavior. These extractors register claims for the atoms they consume;
they do not need to duplicate layout logic.

The ledger operates only on rows already proven to belong to a transaction table.
Headers, totals, page furniture, and unrelated document text remain outside its
scope.

## Description Reconstruction

Description extraction selects atoms rather than whole cells.

1. Start with atoms inside the inferred description band.
2. Inspect same-line atoms at its shared boundaries. A fragment is included only
   when baseline alignment, glyph/word spacing, and direction-aware ordering connect
   it to the merchant text more strongly than to the neighboring column.
3. Inspect accepted continuation rows. Include only the horizontally aligned span
   connected to the merchant span; independently aligned category or auxiliary text
   is assigned its own ancillary disposition.
4. Rebuild logical text from the selected positioned words and glyphs. Original
   word boxes are authoritative for spaces; a geometry-derived gap is used only
   when word evidence is unavailable. Existing RTL-aware ordering remains the
   canonical renderer.
5. Numeric processor references, phone-like identifiers, location values, category
   text, transaction types, and separate processor/location columns are not merchant
   atoms. Their classification must be supported by their column header/profile or
   consistent separation from the merchant span, not by a literal value allowlist.

If exactly one reconstruction is geometrically supported, it is emitted. Competing
reconstructions add `ambiguous_description_continuation`. High-confidence alphabetic
boundary atoms left without a valid disposition add
`unconsumed_description_boundary_text`.

## Fragmented Conversion Dates

Conversion-date extraction builds candidates from positioned digit and separator
atoms inside a proven `conversion_date` column or its geometrically overlapping
cell evidence.

- Spaces may be removed within a numeric component only when adjacent atoms remain
  on the same baseline and within the local spacing tolerance.
- Separators must remain explicit and consistent.
- The candidate must match the discovered date style and proven year-suffix context
  and construct a valid calendar date.
- Surrounding phrase or punctuation atoms remain exact evidence but are classified
  separately from the date value.
- Exactly one valid candidate is required. Multiple valid candidates remain
  ambiguous; no first-match rule is allowed.

When conversion-date cues exist but no unique valid date can be produced, the row
adds `unparsed_conversion_date_candidate`. A successful reconstruction claims the
exact atoms used and preserves their original cell in the transaction evidence.

## Semantic Completeness Validation

After all row fields have been normalized, validate the ledger before constructing
the final `Transaction`:

- reject incompatible or duplicate ownership;
- require provenance for every non-null extracted semantic field;
- reject high-confidence unclaimed alphabetic or numeric evidence at a proven field
  boundary;
- reject an unparsed required-role candidate, including conversion-date evidence;
- permit recognized ancillary values without adding public fields in this change;
- permit noise only through narrow geometry/source rules that identify a layout
  artifact.

Ledger failures become stable transaction ambiguity codes. They do not cause billed
rows to disappear, so monetary evidence and calculated totals remain inspectable.
The current reconciliation path already treats transaction ambiguities as
non-success, which makes `--strict` exit with validation status 2. Runtime and input
errors continue to use exit status 1. Arithmetic difference diagnostics and
transaction semantic ambiguity codes remain separately represented.

## Data Flow

1. Layout supplies a base row, continuation rows, column roles, words, and glyphs.
2. The ledger canonicalizes and deduplicates evidence atoms.
3. Existing financial extractors parse values and claim their supporting atoms.
4. description and date extractors claim spatial fragments and emit values or
   specific ambiguities.
5. ancillary classifiers claim proven category, location, processor, and deferred
   FX evidence.
6. completeness validation reports conflicting or unresolved evidence.
7. normalization builds the transaction with exact evidence and ambiguity codes.
8. reconciliation verifies exact monetary totals and rejects unresolved semantic
   ambiguities; strict CLI behavior follows the resulting statement status.

## Failure Behavior

- A uniquely recoverable description or conversion date is emitted without an
  ambiguity.
- A recoverable billed transaction with unresolved semantics remains in output with
  an ambiguity and makes the statement non-successful.
- A row whose billed amount or group membership is unresolved follows the existing
  non-emission path.
- Arbitrary text in an unknown column is no longer silently accepted. It must be
  classified from layout evidence or reported as unresolved.
- Low-confidence OCR artifacts do not become merchant text merely to satisfy the
  ledger.

## Testing

All production behavior is developed red-green-refactor with minimized synthetic
geometry fixtures.

Focused tests cover:

- a date cell containing a valid date plus a leading Hebrew merchant word;
- adjacent text containing both a merchant suffix and category text;
- a merchant suffix on a continuation line;
- English merchant words whose cell text lost a space but whose word/glyph geometry
  preserves it;
- processor/reference and location text excluded from descriptions;
- both observed fragmented conversion-date spacing shapes;
- ambiguous and invalid fragmented conversion dates;
- unconsumed boundary text and ambiguous continuations producing exact codes;
- exact arithmetic reconciliation coexisting with semantic failure;
- strict CLI exit 2 for semantic ambiguity and exit 1 for runtime/input errors;
- unchanged JSON/CSV schemas and deterministic serialization.

Regression verification includes the focused suites, the entire static/test gate,
the two local current statements, and the broader retained local corpus where
practical. Acceptance compares transaction counts, date/amount pairs, original
values, and all printed/calculated totals before checking corrected descriptions and
conversion dates.

## Non-goals

- Adding public exchange-rate, fee, fee-discount, or net-fee fields.
- Inferring merchant names from external databases or merchant allowlists.
- Adding issuer-specific adapters or document fingerprints.
- Changing financial sign, amount, grouping, or reconciliation arithmetic rules.
