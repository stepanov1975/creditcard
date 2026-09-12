# Merchant-Region Alignment Comparison

**Status:** Complete — STOP. Approved by the user's “proceed” on 2026-09-12 following
the concrete recommendation in the omission-routing report. Authority was
committed at `9601a1f` before private alignment and scoring; see the
[result report](../../experiments/row-extraction-merchant-region-alignment-report.md).

```text
Scope answer: YES — measures merchant recognition after correcting a documented alignment mismatch
Experiment: shared evaluation
Extraction hypothesis: Requiring strongly located alphabetic merchant evidence for alignment increases measured exact matches above 13/24 with no losses
Measurement: alignment coverage, exact merchant match, unique-output coverage, and paired gains/losses
Fixed inputs: 24 unchanged training references and marked regions, 135 saved rows, fixed assembly outputs, and original candidate alignment
Smallest allowed files: docs/superpowers/specs/2026-09-12-merchant-region-alignment-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-region-alignment-report.md; artifacts/merchant-region-alignment-v1/**
Required output: one alignment-comparison metric delta and supported or falsified measurement hypothesis
Stop condition: stop after the fixed 24-case comparison; no tuning, new predictions, label changes, or reusable evaluation infrastructure
```

## Immediate evaluation need

The completed trace reproduced a reference-to-row mismatch: the current matcher
selects a row with no merchant atoms or description, while four strongly located
merchant atoms already feed another primary owner's description. The existing
13/24 measurement therefore cannot determine that reference's merchant recognition
under an evidence-supported assignment. This authorization permits one disposable
eligibility predicate for that named measurement. It does not reopen shared
evaluation infrastructure, frozen arms, controllers, schemas, or workflows.

## One fixed rule

For each reference, consider only its selected training page's saved rows. Require
at least one source atom with an alphabetic character whose box has strong support
in an existing marked merchant region: center inside a region and at least half
its area inside any one region. Reuse the existing support rule without threshold
changes. Numeric-only, punctuation-only, boundary-only, invalid, or outside atoms
do not establish eligibility. A valid supporting atom suffices even if other row
atoms do not support the merchant region.

For eligible rows, preserve the original transaction-region overlap score,
including its half-row-height requirement. Ineligible or invalid row geometry
receives zero score. Use the existing unique-best and collision rule: ties or
multiple references choosing the same row become unaligned, with no fallback to
second choices. This eligibility filter applies to every reference, not only the
known omission. Do not filter by predicted type, emitted output, merchant equality,
filename, document identity, or financial values. Source text is used only to test
whether an atom contains an alphabetic character.

The matcher receives region geometry, row boxes, and source atoms; it receives no
expected merchant text, outputs, or predictions. Preserve all source atoms and
explicit output ownership. Do not aggregate atoms across rows for eligibility or
infer continuation ownership. Save a separate candidate alignment; never replace
the original alignment or any reference.

## Inputs, comparison, and limits

Use the 127 original plus eight diagnostic rows, unchanged assembly outputs, all
24 existing training references, and original candidate alignment. Source copies
may be opened only for identity and each selected page's dimensions and rotation.
Normalize original native-point geometry and new display-point geometry according
to their existing conventions. No source extraction, rendering, OCR, model call,
classification, new prediction, or assembly rerun is authorized.

First reproduce all 24 saved scores (13 exact, 23 unique outputs, one omission)
and all original assignments using the unfiltered geometric matcher. Stop with
a quantified reproduction disagreement if these do not agree. Then compute one
candidate alignment and score the same saved outputs with the unchanged
NFC/whitespace scorer and 24-case denominator.

Report alignment coverage, exact match, unique-output coverage, paired gains/losses,
category transitions, assignment changes, and digital/OCR slices. Support the
hypothesis only if exact matches exceed 13/24 and no previous exact match is lost.
Report gains as a measurement change, not improved recognition. Any losses,
unmatched cases, or collision effects stay in the denominator. No tuning or second
candidate follows, regardless of the outcome.

## Completion checklist

Use the current branch. Private code, invented-input tests, measurement, and
immediate independent checks may write only under ignored
`artifacts/merchant-region-alignment-v1/`. Reuse existing support, scoring, and
assignment helpers. This must not become a reusable evaluator or annotation tool.

- [x] Commit the approved scope and active phase after repository gates.
- [x] Observe focused failing tests for evidence eligibility, retained ranking,
  boundary/invalid inputs, ties, and collisions; implement the smallest helper
  and pass tests, Ruff, and strict mypy.
- [x] Reproduce the fixed baseline, compare the one candidate, and independently
  verify assignments and exact-match outcomes.
- [x] Verify original inputs unchanged, pass repository gates, publish aggregate
  findings, mark the live phase STOP, and commit documentation.

Keep private text, identities, geometry values, and financial data out of Git and
tool output. The 24 references remain a single-reviewer training seed, without
independent gold certification, held-out accuracy, or production acceptance.
Stop after this comparison. No new labels, reference repair, expansion, gold
promotion, validation/test access, or production integration is authorized.
