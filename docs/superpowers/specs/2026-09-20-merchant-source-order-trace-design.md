# Merchant Source-Order Trace

**Status:** COMPLETE — STOP. All three reversals are present in native words and
persist unchanged downstream. Glyph positions yield the reference substrings for
all three. See the [report](../../experiments/row-extraction-merchant-source-order-trace-report.md).

The user's “proceed” approves the completed directional-signature report's
recommendation to trace where the three reverse-only LTR atoms acquire their order.

```text
Scope answer: YES — locates the stage carrying three measured reversed merchant atoms
Experiment: row-profiles
Extraction hypothesis: At least one reversed LTR atom already has its saved character order at the digital word-extraction boundary and retains it downstream
Measurement: first observed reversal stage and unchanged downstream atom counts
Fixed inputs: three reverse-only atoms in the same two digital training cases, frozen extractor, saved evidence and their source pages if needed
Smallest allowed files: docs/superpowers/specs/2026-09-20-merchant-source-order-trace-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-source-order-trace-report.md; artifacts/merchant-source-order-trace-v1/**
Required output: quantified stage attribution and a supported, falsified or unresolved hypothesis
Stop condition: stop after tracing the three atoms or a reproduction failure; do not fix extraction, generate merchant predictions, edit labels or expand the selected cases
```

## Inputs and trace

Commit authority before the private trace. Reproduce the 72 saved scores, previous
classifications, two whole-atom results and all seven directional signatures.
Select exactly the three `reverse_only` atom occurrences, using saved ordinal
identities and ownership. Retain the same two cases and their training split.

Read only their source pages from the existing local seed copies, verifying each
copy against the saved document identity. Extract native words and glyphs with
the frozen extractor, then replay its layout and row-to-atom projection functions.
No OCR, pixels, models, full-document parsing or extraction-rule changes are
authorized. Source PDF bytes may be read locally for this bounded trace; document
contents, glyphs, coordinates and identities remain private.

Locate native and canonical words by the saved atom bounding box, with a fixed
maximum coordinate difference of **0.0001 PDF points**. Require unique matches;
do not select by reference text. Match logical-row word evidence on the same
geometry, deduplicating identical word observations repeated in row and cell
provenance. Re-project that row with its saved row identity and column bands, and
require an exact saved atom match. Missing/ambiguous geometry or failed projection
is unresolved; never widen the tolerance or substitute evidence.

Compare native word text, canonical layout word text, logical-row word text,
replayed atom text, saved atom text and saved proposal evidence. Report the first
observed stage with the saved reversed sequence and whether every later stage is
unchanged. This trace identifies an observed boundary, not the original PDF authoring
or decoder cause. A current replay that fails to reproduce the saved atom is
unresolved, not evidence of a historical mutation.

The hypothesis is supported if at least one atom has its saved reverse-only
sequence already at native word extraction and preserves it through the verified
downstream path; falsified if all three trace successfully and none does; otherwise
unresolved. Report complete, changed-stage and unresolved counts separately.

## Glyph-order evidence

For each uniquely matched native word, select non-whitespace glyphs whose bounding
box centers lie inside it. Require each selected glyph to belong to exactly one
native word, contain one code point and have valid finite positive geometry.
Require the projected character inventory to equal the native word inventory.

Compare the glyph sequence in extraction order with the native word, saved atom
and reversed saved atom. Separately inspect increasing horizontal-center order
only if centers differ by more than 0.0001 points and all glyph boxes share a
vertical overlap of at least 80% of the smallest height. Report equality categories
and reference containment as diagnostic counts. Retain failed geometry/inventory
guards as unresolved, without changing the atom trace verdict.

The glyph query preserves all selected characters and does not assemble a merchant
or generate a prediction. Save only source evidence and comparison results privately;
do not save a corrected merchant string. No transformed combination search is active.

## Verification and stop

Use a local replay command that detects the original reverse-only symptom, then
trace the declared boundaries. Test the trace classifier and geometry guards with
invented inputs before relying on them. Independently check boundary equality,
geometry matching and aggregate counts. The extractor checkout and prior artifacts
remain unchanged. Keep all disposable code/results in ignored
`artifacts/merchant-source-order-trace-v1/` and publish aggregate findings only.

Run all four repository gates before tracked commits. This task ends after the
trace or a saved-result reproduction failure. Diagnostic phases apply; implementing
a fix and proving a repaired original reproduction are outside this task. No
second diagnostic, candidate, broader selection, held-out access, reusable
infrastructure or production integration is active.
