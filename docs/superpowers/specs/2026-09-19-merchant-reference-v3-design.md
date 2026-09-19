# Fully Reviewed Merchant Reference v3 Comparison

**Status:** COMPLETE — STOP. The separate reference and fixed comparison are
recorded in the [report](../../experiments/row-extraction-merchant-reference-v3-report.md).

The user's “proceed” approves the completed remaining-adjudication report's
recommendation to create a separate v3 reference and rescore the same outputs.

## Mandatory task contract

```text
Scope answer: YES — measures saved merchant extraction against the completed human review
Experiment: shared evaluation
Extraction hypothesis: Corrected merchant text or source regions change at least one exact-match outcome for the same saved outputs
Measurement: exact merchant match, alignment coverage, unique-output coverage, and paired gains/losses with text-first then alignment attribution
Fixed inputs: 24 training cases, four remaining adjudications, v2 reference, 135 saved rows, unchanged assembly outputs, and existing matcher
Smallest allowed files: docs/superpowers/specs/2026-09-19-merchant-reference-v3-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-reference-v3-report.md; artifacts/merchant-gold-seed-v3/**
Required output: separate fully reviewed 24-case reference and quantified saved-output comparison
Stop condition: stop after the fixed three-view comparison, or if the saved v2 baseline cannot be reproduced
```

## Reference update

Validate the four remaining adjudications using the existing answer contract.
Require confirmed present merchants, source checks, reasons and valid merchant
and transaction regions. Apply the existing projection helper to v2: replace
only merchant text and the two region fields for the four mapped identities.
Preserve all other fields, order, document/page identities and training membership.
Preserve the other 20 v2 record lines byte for byte. Keep v1, v2 and every human
submission unchanged. Original record metadata retains its original meaning;
the separate directory identifies the new reference version.

Write only under ignored `artifacts/merchant-gold-seed-v3/`. Update the existing
simple case-to-review-depth mapping to 14 agreeing repeat readings and ten source
adjudications, with zero single readings. Check the two repeat audits partition
the 24 cases and the two adjudication sets are disjoint and exactly cover their
disagreements. All 24 have a second reading, but by the same reviewer: this is a
fully reviewed training seed, not independent certification or held-out gold.
Retain decisions and notes in their existing answer files.

## Fixed three-view comparison

Use the same 127 original rows, eight additional diagnostic rows and saved
primary/continuation assembly outputs. Do not run extraction, classification,
assembly, OCR, discovery, rendering or models.

1. Reproduce all 24 saved v2 assignments and case scores: 17 exact, two partial
   text and five other mismatches, with 24 aligned and 24 unique outputs.
2. Score v3 text with those same v2 assignments for the text-reference effect.
3. Recompute assignments from v3 regions using the unchanged merchant-region
   matcher, then score v3 text for the conditional alignment effect.

Preserve existing NFC/whitespace normalization, scorer, merchant evidence
eligibility, transaction-overlap ranking, tie/collision abstention and coverage
definitions. Matcher inputs exclude reference text and predicted merchant text.
Report exact match, alignment and unique-output coverage, error categories,
assignment changes, transitions and paired gains/losses for all three views,
overall and by digital/OCR slice. The hypothesis is supported if either
consecutive comparison changes any exact/nonexact outcome; otherwise falsified.
Text-first attribution is ordered accounting, not independent causal estimation
or an extractor improvement.

## Verification and stop

Commit this authority and charter allowance before private materialization.
Reuse the tested projection helper; any new behavior needs focused invented-input
tests. Independently check the four projections, 20 preserved lines, all review
depths, assignments, scores and aggregates. Selected PDF copies may be read only
for identity and page geometry. Do not expose pixels, source strings, identities,
coordinates or financial values in tool output or Git. Preserve the frozen
deterministic checkout. Run all four repository gates before committing reports.

If the v2 baseline cannot be reproduced, stop without input substitution or
matcher tuning. Stop after the comparison. No reusable evaluator, controller,
CLI, schema family, prediction changes, new labels, expansion, further review,
validation/test access, accepted-gold promotion or production integration is
authorized.
