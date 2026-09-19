# Merchant Punctuation-Aware Spacing Experiment

**Status:** APPROVED — preparing one candidate and fixed comparison.

The user's “proceed” approves the completed punctuation-geometry report's
recommendation to test one spacing candidate across all 24 frozen seed cases.

```text
Scope answer: YES — tests punctuation-aware merchant spacing in the row-profiles extractor
Experiment: row-profiles
Extraction hypothesis: Punctuation-aware spacing increases exact merchant matches without losing any of the 17 existing matches
Measurement: exact merchant match, paired gains/losses, coverage, changed outputs, removed separators and spacing-only errors
Fixed inputs: 24 v3 training references, 135 saved rows/proposals, frozen ownership and atom order, fixed alignment and saved spacing outputs
Smallest allowed files: docs/superpowers/specs/2026-09-19-merchant-punctuation-spacing-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-punctuation-spacing-report.md; artifacts/merchant-punctuation-spacing-v1/**
Required output: one runnable candidate and its fixed 24-case metric delta
Stop condition: stop after this candidate comparison or baseline reproduction failure; no tuning, second candidate, label changes, expansion or production integration
```

## Fixed rule

The public test seam is `render_punctuation_spacing(atoms)`, returning text and
boundary decisions. It receives only already selected atoms in recorded order.
Preserve the previous geometry-spacing rule at every boundary except those
returning `unsupported_direction` where at least one touching character has a
Unicode Punctuation category. Explicit source whitespace, empty text, invalid
boxes and all non-punctuation decisions retain their previous behavior.

For eligible punctuation boundaries, use the already measured context and
geometry rule without modification:

- Scan outward through this owner's unchanged atom sequence for the nearest
  strong Unicode Letter on each side. Bidi L means LTR; R/AL means RTL. Both
  sides must resolve to the same direction; unknown or mixed direction retains
  the inserted separator.
- Require finite positive rectangles, equal evidence-source kind and positive
  estimated character counts. Counts exclude whitespace and Unicode Mark/Other
  categories; punctuation counts toward width as before.
- Require at least 80% vertical overlap relative to the smaller height, a
  nonnegative gap in inferred reading direction, and a gap at most 20% of the
  smaller estimated character width. Use the same Decimal geometry diagnostic.
- Remove only the inserted separator when those checks pass. Otherwise retain
  it. Do not edit source text, reorder atoms or change ownership/multiplicity.

Do not select boundaries by case identity, merchant, source path, reviewed label,
script, attachment category or earlier error membership. No threshold fitting,
punctuation-character exceptions or within-atom normalization/editing is allowed.

## Generation and measurement

Commit authority before private generation. The generator reads only the six
saved evidence/assembly inputs used by the original spacing experiment: original
and additional rows, proposals, assembly outputs, statuses and assembled atom
order. Reconstruct all baseline owner outputs first. Apply the candidate to all
comparable unique-output owner groups, preserving the existing document/page/
render/convention comparability checks and ambiguous/empty fallbacks. No source
PDFs, images, new extraction, OCR or model calls are authorized.

Save every generated output and boundary decision before opening references,
alignment or case diagnostics. This avoids using labels in the generation
process; the design remains informed by previous training-seed diagnostics.

Then reproduce all 48 saved scores from the original v3 and prior spacing views,
both 17/24 exact with two partial-text errors, five other mismatches and full
alignment/unique-output coverage. Score the new candidate against the same 24
references and assignments. Report overall and digital/OCR slices, paired
gains/losses against both prior views, category transitions, changed outputs,
removed separators and spacing-only errors. Independently verify all generated
boundary decisions, source selection/order, outputs, scores and aggregates.

The hypothesis is supported only if exact count increases above 17 with zero
exact-match losses and unchanged coverage. Otherwise it is falsified. Report
outcomes without a second candidate or post-result change. This is training-seed
evidence, not independent validation or private-corpus acceptance.

## Verification and stop

Use invented-input red/green tests at the renderer seam for narrow punctuation,
retained wide gaps, inclusive thresholds, RTL/LTR and nearest-letter context,
mixed/unknown direction, invalid/overlapping boxes, line/source mismatch,
explicit whitespace and exact source-character preservation. Check previous
non-punctuation behavior as well. Reuse existing read-only scoring and geometry
helpers where sufficient; all new scripts and private results belong only in
ignored `artifacts/merchant-punctuation-spacing-v1/`.

Run all four repository gates before tracked commits. Stop after this single
comparison or a saved-result reproduction failure. No frozen checkout edits,
reference changes, new review, wider sample, held-out access, shared controller/
schema/CLI, production integration, merge or push is authorized.
