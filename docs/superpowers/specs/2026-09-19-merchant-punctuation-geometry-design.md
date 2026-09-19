# Merchant Punctuation Attachment and Geometry Measurement

**Status:** COMPLETE — STOP; the fixed-geometry hypothesis is supported.

Authority was committed at `0aaec40` before measurement. All six incorrect
punctuation boundaries pass the unchanged geometry checks; all three required
controls have wide gaps, with zero unresolved boundaries. No changed prediction
was generated. See the [report](../../experiments/row-extraction-merchant-punctuation-geometry-report.md).

The user's “proceed” approves the completed retention-reason report's
recommendation to compare punctuation attachment and geometry using saved atoms.

```text
Scope answer: YES — measures punctuation context and geometry at incorrect and required merchant separators
Experiment: row-profiles
Extraction hypothesis: Resolving punctuation direction from adjacent strong letters makes at least one error pass the existing narrow-gap geometry checks while none of the three required controls passes
Measurement: punctuation attachment categories and fixed geometry-pass counts for six errors versus three required controls
Fixed inputs: nine saved digital boundaries in five training cases, frozen atoms and order, v3 references, and 48 saved scores
Smallest allowed files: docs/superpowers/specs/2026-09-19-merchant-punctuation-geometry-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-punctuation-geometry-report.md; artifacts/merchant-punctuation-geometry-v1/**
Required output: attachment and geometry counts with a supported, falsified or unresolved hypothesis
Stop condition: stop after the fixed nine-boundary comparison or saved-result reproduction failure; no candidate, threshold tuning, source extraction or label changes
```

## Fixed selection and prerequisites

Select precisely the six error boundaries and three required control boundaries
whose saved edge category is `punctuation_involving` in the completed reason
comparison. All nine are digital and cover five training cases. Preserve the
case, atom order, boundary index and reference-gap role. Reproduce the 48 saved
scores and unchanged 17/24 exact result before measuring geometry. Reconstruct
the selected saved outputs and confirm their atoms against the original row and
proposal evidence. Independently verify selection, features and aggregate counts.

No source PDFs, images, new extraction, OCR, model calls, output generation,
reference updates or additional cases are authorized. Prior artifacts and the
frozen checkout are read-only. Only aggregate category counts enter Git.

## Predeclared features

The disposable diagnostic seam is `describe_boundary(atoms, boundary_index)`.
It returns these observations without emitting merchant text or changing a space:

- Punctuation side: left edge, right edge, or both edges. Record Unicode general
  categories for the two edge characters, without publishing the characters.
- Atom attachment: for each adjacent atom, classify non-whitespace contents as
  `punctuation_only`, `contains_letter_or_number`, or `other`. These describe the
  saved atom segmentation, not verified linguistic attachment.
- Context direction: scan outward in the unchanged owner's atom sequence on
  each side of the boundary for the nearest Unicode Letter whose bidi class is
  L, R or AL. L means LTR; R/AL means RTL. Both sides must yield the same known
  direction. Mixed or absent direction is unresolved, not guessed. Do not change
  atom order or inspect other owners.
- Geometry: reject invalid/nonfinite rectangles or differing evidence sources.
  Keep the existing vertical overlap requirement of at least 80% of the smaller
  atom height. Use the same signed gap in inferred reading direction and require
  it to be nonnegative. Estimate each atom's character width as its box width
  divided by its number of non-whitespace characters outside Unicode Mark and
  Other categories; punctuation counts as in the existing rule. The unchanged
  narrow threshold is gap at most 20% of the smaller estimated character width.

Use Decimal conversions of saved coordinates to avoid threshold-rounding drift.
Retain private overlap and signed normalized gap values, but publish only the
fixed outcome categories: `invalid_geometry`, `different_source`,
`unresolved_direction`, `different_line`, `overlap_or_order`, `wide_gap`, or
`narrow_gap`. Zero character counts are invalid geometry. Do not sweep, adjust
or fit thresholds. Cross-tabulate attachment and geometry by error/control
cohort, with boundary counts and distinct case counts. All counts describe these
saved boxes; inferred direction and approximate widths need not reflect glyph
layout perfectly.

## Hypothesis and stop

Support requires at least one erroneous boundary with `narrow_gap`, zero required
controls with `narrow_gap`, and no unresolved/invalid control that could conceal a
pass. A required control with `narrow_gap` falsifies the hypothesis. If all error
boundaries resolve and none passes, it is also falsified. Otherwise the result
is unresolved unless the support condition already holds. Report all failures
and unknowns. No separator removal or merchant accuracy gain may be claimed.

Commit this authority before private measurement. Use invented-input red/green
tests at the stated diagnostic seam for attachment, direction and fixed geometry
categories. Keep the diagnostic, tests and private results in ignored
`artifacts/merchant-punctuation-geometry-v1/`. Run all repository gates before
tracked commits. Stop after this comparison or saved-result reproduction failure;
no follow-on task, new candidate, review, wider sample, held-out access, reusable
controller/schema/CLI or production integration is active.
