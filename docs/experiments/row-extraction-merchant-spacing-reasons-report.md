# Merchant Spacing Retention-Reason Results

**Status:** COMPLETE — STOP, 2026-09-19.

Authority: [measurement design](../superpowers/specs/2026-09-19-merchant-spacing-reasons-design.md),
committed at `f1f6b18` before private measurement.

## Finding

All **six incorrect inserted spaces in two digital cases** reach the unchanged
`unsupported_direction` return. All six involve punctuation at an atom edge.
That same reason also retains **four required spaces in four exact controls**;
three of those boundaries involve punctuation. The declared hypothesis that an
error reason would be absent from required controls is **falsified**.

The reason name covers more than direction: the existing rule returns it when
either edge character is not a letter, before testing source, line or gap
geometry. These six errors therefore do not establish that its geometric gap
threshold is too strict. Reason-only removal, including blanket removal around
punctuation, would remove required control spaces.

## Fixed comparison

The selection contains the two previously identified spacing-only cases and the
17 cases exact in both saved views. The other five failures are excluded. All
48 saved scores reproduce. The six error gap positions match the prior location
measurement in both views and map uniquely to recorded atom boundaries.

The following entries are **boundary count / distinct case count**. A case may
appear under multiple reasons, so case counts must not be summed across rows.

| Recorded reason | Incorrect spaces | Required control spaces | Digital required controls | OCR required controls |
| --- | ---: | ---: | ---: | ---: |
| `unsupported_direction` | 6 / 2 | 4 / 4 | 4 / 4 | 0 / 0 |
| `wide_gap` | 0 / 0 | 26 / 16 | 16 / 10 | 10 / 6 |
| All other recorded reasons | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| **Total** | **6 / 2** | **30 / 17** | **20 / 11** | **10 / 6** |

All 30 control boundaries are required separators. There are zero redundant,
removed, edge, shared or unresolved control separators, and zero controls with
no boundaries. All six error boundaries are digital; there are no OCR cases in
the fixed spacing-error selection. This does not imply that OCR has no other
extraction errors.

The predeclared Unicode breakdown of `unsupported_direction` is:

| Edge category | Incorrect spaces | Required control spaces |
| --- | ---: | ---: |
| Punctuation-involving | 6 / 2 | 3 / 3 |
| Letter followed by number | 0 / 0 | 1 / 1 |
| Mixed-direction letters | 0 / 0 | 0 / 0 |
| Number followed by letter | 0 / 0 | 0 / 0 |
| Number followed by number | 0 / 0 | 0 / 0 |
| Other | 0 / 0 | 0 / 0 |

This descriptive breakdown does not supply a separating rule. No counterfactual
outputs or accuracy gains were generated or scored.

## Verification and limits

- Reconstructed 38 saved output strings for 19 selected cases from original
  atoms, ownership, recorded order and saved separators.
- Independently verified all 40 boundaries in those cases using character
  offsets/source spans and a separate decimal-geometry implementation of the
  unchanged reasons. The comparison uses six error boundaries plus 30 control
  boundaries; the four other boundaries in the two error cases are excluded.
- Independent checks agree on all six error gaps, the six cohort/source slices,
  reason and role counts, case denominators and the hypothesis result.
- Twenty-eight invented-input tests pass after their expected initial failures.
  Ruff formatting/lint, strict typing of the four private scripts, repository
  mypy and all 3,766 repository tests pass.
- All 16 protected saved inputs and the frozen checkout remain unchanged. No
  source documents, pixels, new OCR or model calls were used. Private scripts,
  inputs and detailed results remain local and ignored under
  `artifacts/merchant-spacing-reasons-v1/`.

Exact match remains **17/24 in both saved views**, with 24 aligned unique outputs,
two partial-text errors and five other mismatches. No production code changed;
this diagnostic is not a private-corpus acceptance result. The reference is a
small, correlated training seed with repeat reads by the same reviewer, not an
independent held-out estimate.

## Recommendation and stop

One possible next extraction task is to quantify **punctuation attachment and
bounding-box gap/order differences at the six error boundaries versus the three
punctuation-bearing required controls**, using only the saved atoms. That would
test whether a general distinction exists before defining another spacing rule.
It is a recommendation only and has not been executed. This comparison stops
here; there is no active follow-on task.

```text
Scope: YES — quantifies saved spacing-rule reasons at incorrect and required separators
Experiment: row-profiles
Measurement: retention-reason overlap and required versus redundant control separators
Result: hypothesis falsified; all six errors share a reason with four required controls, including three punctuation-bearing controls
Next extraction task: STOP
```
