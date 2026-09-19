# Adjudicated Merchant Reference v2 Comparison

**Status:** COMPLETE — STOP. The separate reference and fixed comparison are
recorded in the [report](../../experiments/row-extraction-merchant-reference-v2-report.md).

The user's “proceed” approves the recommendation to create a separate 24-case
training reference using the six source adjudications and re-score the same
saved extraction outputs. The original version remains immutable.

## Mandatory task contract

```text
Scope answer: YES — measures saved merchant extraction against adjudicated reference text and regions
Experiment: shared evaluation
Extraction hypothesis: Corrected merchant text or source regions change at least one exact-match outcome for the same saved outputs
Measurement: exact merchant match, alignment coverage, unique-output coverage, and paired gains/losses with text-first then alignment attribution
Fixed inputs: 24 training cases, six confirmed adjudications, 135 saved rows, unchanged assembly outputs, and existing merchant-region alignment
Smallest allowed files: docs/superpowers/specs/2026-09-19-merchant-reference-v2-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-reference-v2-report.md; artifacts/merchant-gold-seed-v2/**
Required output: separate 24-case adjudicated reference version and a quantified saved-output score comparison
Stop condition: stop after the fixed three-view comparison; no extractor tuning, new predictions, new labels, expansion, or production promotion
```

## Reference update

Validate the six saved adjudications with the existing answer contract. Require
confirmed present merchants, source-check confirmations, reasons, and valid
merchant/transaction regions, as recorded in the completed adjudication audit.
Use the existing private case mapping. Do not infer or supply a new human answer.

Write `artifacts/merchant-gold-seed-v2/human-reference.jsonl` using the existing
reference shape. Change only merchant text and merchant/transaction regions for
the six adjudicated identities. Preserve every other field, case order, document,
page, and training membership. Carry forward the other 18 original record lines
byte for byte. Do not overwrite v1, any answer file, or any accepted corpus gold.

A small private case-to-review-depth mapping accompanies the reference: 13
single-read cases, five agreeing repeat-read cases with unchanged regions, and
six source-adjudicated cases. The dataset remains a training calibration seed
with one human reviewer, not independently certified or held-out gold.
This mapping describes annotation depth; it is not a new workflow or provenance
envelope. Keep original human decisions and notes in their existing private files.

## Fixed three-view comparison

Use all 24 cases and the unchanged saved primary/continuation assembly outputs.
Use exactly 127 original rows plus eight approved pre-filter diagnostic rows.
Do not rerun extraction, classification, assembly, OCR, discovery, or any model.

1. Reproduce the saved original merchant-region assignments and all 24 saved
   scores, including 13/24 exact and 24/24 unique-output coverage.
2. Score the adjudicated merchant text with those same original assignments.
   This measures the text-reference effect with output selection held fixed.
3. Reapply the existing merchant-region matcher to all 24 v2 references, using
   their corrected regions and the same saved evidence. Score the same outputs
   against v2 text. Compare this view to step 2 for the conditional region/
   alignment effect and to step 1 for the total reference-update effect.

The existing matcher requires strongly located alphabetic source evidence, ranks
by transaction overlap, and abstains on ties or owner collisions without a
second-choice fallback. Its thresholds, scorer, NFC/whitespace normalization,
coverage definitions, and duplicate-output treatment remain unchanged. Matcher
inputs exclude expected merchant strings and predicted merchant outputs.

Report exact match, alignment coverage, unique-output coverage, case categories,
assignment changes, and paired exact gains/losses for the three views, including
digital/OCR slices. Attribute effects in the stated text-first order; this is
ordered accounting for a reference change, not an independent causal estimate
or extractor improvement. The hypothesis is supported if either consecutive
comparison changes at least one exact/nonexact outcome; otherwise it is falsified.

## Verification and stop

Commit this design and charter allowance before private materialization. Keep
the deterministic frozen checkout unchanged. Selected source copies may be read
for identity and page geometry only, using the original coordinate conventions
for the original and additional rows. Never expose source strings, pixels,
identities, or financial data in tool output or Git.

Check six-decision projection, 18 unchanged record lines, preserved identity/
membership, review-depth counts, and independent assignment/exact-score agreement.
Use focused invented-input tests for any new reference-update logic. Run all
four repository verification gates before committing aggregate documentation.

If original assignments or scores do not reproduce, stop without substituting
different inputs or tuning the matcher. Report the failure; do not create a
second support task. After the fixed comparison, report the metrics and STOP.
No reusable evaluator, controller, CLI, schema family, new predictions, reference
retuning, new review, expansion, validation/test access, accepted-gold promotion,
or production integration is authorized.
