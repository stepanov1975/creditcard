# Merchant Spacing Retention-Reason Measurement

**Status:** COMPLETE — STOP; the reason-separation hypothesis is falsified.

Authority was committed at `f1f6b18` before measurement. All six incorrect
separators share `unsupported_direction` with four required control separators;
six errors and three of those controls involve punctuation. All 48 scores
reproduce. See the [result report](../../experiments/row-extraction-merchant-spacing-reasons-report.md).

The user's “proceed” approves the whitespace-location report's recommendation
to compare the recorded spacing reasons at six errors with 17 exact controls.

```text
Scope answer: YES — measures why the spacing rule retained six incorrect separators and its overlap with correct control boundaries
Experiment: row-profiles
Extraction hypothesis: At least one recorded retention reason occurs at an incorrect separator but at no required separator in the 17 exact control cases
Measurement: error/control counts by recorded retention reason, required versus redundant control separators, and unresolved boundary attribution
Fixed inputs: six known separator errors in two digital cases, 17 exact controls, 48 saved scores, 135 saved rows/proposals, and recorded spacing decisions
Smallest allowed files: docs/superpowers/specs/2026-09-19-merchant-spacing-reasons-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-spacing-reasons-report.md; artifacts/merchant-spacing-reasons-v1/**
Required output: quantified retention-reason overlap and a supported, falsified or unresolved hypothesis
Stop condition: stop after the fixed error/control comparison or saved-result reproduction failure; no candidate, threshold tuning, source extraction or label changes
```

## Selection and prerequisite

Reproduce all 48 saved baseline/candidate scores and the unchanged 17/24 exact
result. Fix the six extra inserted gaps in the same two digital cases from the
completed location measurement. Select the 17 cases exact in both saved views;
exclude the other five failures. These are training controls, not held-out data.

Reconstruct outputs from saved proposals or assembled atom order and the recorded
separator decisions. Confirm source evidence, ownership and case membership using
the same 135 row records. Existing spacing functions may be called only to verify
saved boundary decisions; no changed decision or candidate output may be produced.
No source PDF, pixels, new text extraction, OCR or model access is authorized.

## Boundary attribution

Map each recorded atom boundary to the ordinal gap in its NFC non-whitespace
character sequence. Require per-atom NFC plus recorded separators to equal NFC
of the raw saved string, and output/reference non-whitespace sequences to match.
Use only the two error cases and 17 exact controls. Preserve unresolved attribution
for cross-atom normalization, duplicate source observations or inconsistent text.

The public diagnostic seam returns boundary index, gap position and role:

- **Incorrect inserted separator:** a unique internal boundary contributes
  whitespace where the reference has none, with no source whitespace at that gap.
- **Required control separator:** a unique internal retained boundary supplies
  the only whitespace at a gap where the exact reference has whitespace.
- **Redundant control separator:** source whitespace at the same gap would
  preserve reference whitespace if the inserted separator were removed.
- **Removed separator:** the saved candidate already emits no separator there.
- **Edge separator:** before the first or after the last non-whitespace character;
  ignored by existing scoring.
- **Shared or unresolved:** multiple atom boundaries contribute at one gap, or
  source/normalization evidence does not support a unique classification.

The six error gap positions must match the prior saved location records. Report
unmapped/shared error gaps rather than silently substituting boundaries. Count all
control boundaries and all zero-boundary controls so every selected case is visible.
Do not label redundant control separators as necessary correct spaces.

## Predeclared comparison

Cross-tabulate the saved first-return spacing reasons against six error boundaries
and each control-boundary role. Keep the original reason taxonomy unchanged:
`invalid_geometry`, `explicit_or_empty_text`, `unsupported_direction`,
`different_source`, `different_line`, `overlap_or_order`, `wide_gap`, `joined`.
Record boundary counts and distinct case counts, including digital/OCR slices.

As a fixed descriptive breakdown of `unsupported_direction`, count edge pairs as
letter/letter with mixed strong direction, letter/number, number/letter,
number/number, punctuation-involving, or other. Use Unicode Letter/Number/Punctuation
categories and the existing strong-direction definitions. This breakdown does not
define a new candidate or change the hypothesis's reason-only comparison.

Report which error reasons also occur at required control separators and how many
control cases they touch. A reason absent from required controls is only a possible
research lead, not evidence that blindly removing its separators is safe elsewhere.
The sample is small, correlated and already used for training diagnostics.

The hypothesis is supported if at least one mapped error reason is absent from
required controls and no shared/unresolved boundary with that reason could hide
a required control. If attribution is complete and every error reason also occurs
at a required control, it is falsified. Otherwise report unresolved, plus the
known counts. No counterfactual merchant outputs, accuracy gains or new thresholds.

## Verification and stop

Commit authority before private measurement. Use focused invented-input red/green
tests for required/error/redundant/edge/shared boundaries, removed separators,
normalization uncertainty and Unicode edge categories. Independently check all
boundary-to-gap mappings, recorded reasons, selection, counts and case denominators.
Keep scripts and private results under ignored `artifacts/merchant-spacing-reasons-v1/`;
publish aggregates only. Run all four repository gates before tracked commits.

Stop after this comparison or a reproduction failure. No second support task,
new spacing rule, threshold tuning, broader sample, label changes, review, held-out
access, shared evaluator/controller/schema/CLI or production integration is authorized.
