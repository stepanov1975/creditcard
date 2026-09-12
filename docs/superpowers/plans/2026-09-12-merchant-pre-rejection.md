# Merchant Pre-Rejection Measurement Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to execute this one measurement task inline.

**Goal:** Determine whether whole-row financial rejection hides exact merchant
proposals in the fixed deterministic method.

**Architecture:** Invoke the frozen description helper directly while preserving
stored classification and transaction decisions. Reuse the prior alignment and
scorer; save only private diagnostics and aggregate documentation.

**Tech Stack:** Python 3.13 in `.venv`, existing Pydantic and frozen local profile
code; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-12-merchant-pre-rejection-design.md`.

## Global constraints

- Fixed inputs: 24 references, 20 matched owners, four unchanged alignment failures,
  and 127 selected training-page rows with their frozen profile predictions.
- No merchant rule, classification, transaction decision, source geometry, label,
  sample membership, or production code changes.
- No private text or pixels enter model tools, external services, or Git.
- Private output root: `artifacts/merchant-pre-rejection-v1/`.
- Reuse the previous exact matcher and owner aggregation policy; use `Decimal`
  for rates and any financial arithmetic.

## Task 1: Measure proposals before financial rejection

```text
Scope answer: YES — measures merchant evidence hidden by deterministic row rejection
Experiment: row-profiles
Extraction hypothesis: Evaluating the existing description rule before financial-field rejection exposes at least one additional exact merchant match on the fixed seed
Measurement: pre-rejection merchant exact matches, proposal coverage, omissions, ambiguity, and paired gains/losses against frozen profile output
Fixed inputs: the same 24 human references, frozen 20/24 row alignment, 127 selected-page observations, and tight-profile classification
Smallest allowed files: docs/superpowers/specs/2026-09-12-merchant-pre-rejection-design.md; docs/superpowers/plans/2026-09-12-merchant-pre-rejection.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-pre-rejection-report.md; artifacts/merchant-pre-rejection-v1/**
Required output: exact-match and coverage deltas, with counts of merchant proposals hidden by row rejection
Stop condition: stop after this diagnostic measurement; do not alter extraction rules, accepted transactions, labels, alignment, or sample size
```

**Consumes:** The frozen profile checkout and previous private comparison's rows,
profile predictions, references, and alignment.
**Produces:** Private pre-rejection evidence, exact-match/coverage deltas, proposal
availability counts, and a privacy-safe report.

- [ ] Commit the approved design, charter amendment, and sole active phase after
  the four repository verification gates pass.
- [ ] Add invented-input tests for a merchant surviving a financial early exit,
  unchanged original decisions, preserved continuation ownership, missing owners,
  ambiguous descriptions and row types, atom order, and multiple-proposal ambiguity.
  Confirm the focused run fails before implementing the small probe.
- [ ] Implement only the direct description-rule invocation and diagnostic output
  collection. Reuse the previous scorer. Run focused tests, Ruff, and mypy.
- [ ] Verify the frozen checkout and load the exact saved inputs. Measure all
  127 rows and score the fixed 24 cases once, preserving original artifacts.
- [ ] Independently verify case totals, paired deltas, decision preservation, and
  unchanged reference/alignment bytes. Publish aggregates and set `STOP`.
- [ ] Run required verification and commit only the permitted documentation.
