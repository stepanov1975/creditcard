# Merchant Seed Comparison Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to execute this single measurement task inline. Steps use checkbox syntax for tracking.

**Goal:** Measure existing merchant output against the 24 human-reviewed seed
references and identify the next useful extraction question.

**Architecture:** Read the frozen training-page observations, align source-reviewed
transactions by fixed geometry, invoke existing arms without changes, and score
their existing description proposals locally. Keep all private material ignored.

**Tech Stack:** Python 3.13 in `.venv`, standard library, existing PyMuPDF,
Pydantic, and local Tesseract; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-12-merchant-seed-comparison-design.md`.

## Global constraints

- Fixed sample: 24 reviewed references, six training pages, six documents.
- No private text or pixels enter model tools, external services, or Git.
- Use existing methods and configurations exactly as listed in the design.
- No extractor edits, annotation edits, tuning, resampling, or validation/test access.
- Private output root: `artifacts/merchant-seed-comparison-v1/`.
- Match transaction geometry without merchant text; use NFC and whitespace only
  for exact merchant scoring. Unavailable methods are not scored as zero.

## Task 1: Fixed merchant comparison

```text
Scope answer: YES — measures existing merchant extraction against the reviewed seed
Experiment: shared evaluation
Extraction hypothesis: At least one existing local extraction method produces more exact merchant matches than the accepted parser baseline on the 24 seed cases
Measurement: normalized merchant exact-match rate, coverage, omissions, row-alignment failures, and paired exact-match delta
Fixed inputs: the 24 reviewed training references, their six frozen source pages, and existing unmodified extraction methods
Smallest allowed files: docs/superpowers/specs/2026-09-12-merchant-seed-comparison-design.md; docs/superpowers/plans/2026-09-12-merchant-seed-comparison.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-seed-comparison-report.md; artifacts/merchant-seed-comparison-v1/**
Required output: merchant scores and paired differences, or quantified method/input eligibility failures
Stop condition: stop after the fixed comparison; do not tune methods, change labels, expand the sample, or access validation/test data
```

**Consumes:** Existing frozen row observations and accepted projections for the
six selected training pages; the unchanged private human reference; the fixed
profile and OCR arms and OCR language packs.

**Produces:** Private alignment and prediction records, private per-case scores,
and aggregate merchant metrics with paired gains/losses and availability limits.

- [ ] Record and review the approved design, charter amendment, and sole active
  phase. Run all four repository gates and commit authority before private runs.
- [ ] Add focused invented-input checks for the one-off measurement: a perfect
  geometric match, disjoint rows, tied best rows, two references claiming one row,
  accepted owned continuations, abstentions carrying proposals, multiple proposals,
  NFC/whitespace equality, case-sensitive inequality, and paired gain/loss counts.
  Confirm the focused tests fail before implementing their measurement functions.
- [ ] Implement only the geometry, description projection, and score rules in
  the design. Use the existing `FrozenRow` and `RowPrediction` contracts; no new
  shared schema. Run the focused tests before opening the private comparisons.
- [ ] Verify the historical checkout heads and absence of tracked edits. Read only
  selected training observations, check six source identities, and save the fixed
  alignment privately before invoking methods. Do not tune failed alignment.
- [ ] Replay accepted projections, invoke the frozen `tight` profile, and invoke
  the existing OCR baseline. Capture all outputs and failure detail privately.
  Record text/vision as unavailable because no eligible frozen candidate exists.
- [ ] Score the fixed 24 references once under the predeclared rules. Independently
  recompute aggregate totals from per-case scores; verify unchanged seed answers.
- [ ] Write the aggregate report, mark the phase complete with `STOP`, run the
  four required gates, and commit only the permitted documentation. Report the
  hypothesis result and one recommended next extraction task without starting it.
