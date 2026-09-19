# Merchant Punctuation Attachment and Geometry Results

**Status:** COMPLETE — STOP, 2026-09-19.

Authority: [measurement design](../superpowers/specs/2026-09-19-merchant-punctuation-geometry-design.md),
committed at `0aaec40` before private measurement.

## Finding

The unchanged geometry thresholds separate this fixed sample: **all six incorrect
spaces pass the narrow-gap checks; none of the three required spaces passes**.
The three controls have wide gaps. All nine boundaries resolve to valid geometry
and matching context directions. The declared hypothesis is **supported**.

The existing spacing rule returns `unsupported_direction` at punctuation before
evaluating gap geometry. This measurement inferred direction from the nearest
strong letters on each side, then applied the existing requirements: at least
80% vertical overlap, a nonnegative gap in reading direction, and a gap no larger
than 20% of the smaller estimated character width. No thresholds were fitted.

## Attachment and geometry counts

The selection is fixed to six erroneous punctuation boundaries in two cases and
three required punctuation boundaries in three exact controls. All are digital
training cases. Entries below are **boundaries / distinct cases**; feature rows
overlap and their case counts must not be added.

| Observation | Incorrect spaces | Required control spaces |
| --- | ---: | ---: |
| Narrow gap, passes fixed checks | 6 / 2 | 0 / 0 |
| Wide gap | 0 / 0 | 3 / 3 |
| All other geometry outcomes, including unresolved | 0 / 0 | 0 / 0 |
| Left atom contains text; right atom is punctuation-only | 3 / 2 | 0 / 0 |
| Left atom is punctuation-only; right atom contains text | 3 / 2 | 0 / 0 |
| Both atoms contain letters or numbers | 0 / 0 | 3 / 3 |
| Both context directions RTL | 6 / 2 | 0 / 0 |
| Both context directions LTR | 0 / 0 | 3 / 3 |

All six errors surround punctuation-only atoms. At all three controls, the right
atom starts with punctuation but also contains text. These attachment categories
describe saved atom segmentation, not independently verified linguistic rules.

The fixed Unicode edge-category counts are:

| Left/right general categories | Incorrect spaces | Required control spaces |
| --- | ---: | ---: |
| Other letter / dash punctuation (`Lo/Pd`) | 2 / 2 | 0 / 0 |
| Dash punctuation / other letter (`Pd/Lo`) | 2 / 2 | 0 / 0 |
| Other letter / other punctuation (`Lo/Po`) | 1 / 1 | 0 / 0 |
| Other punctuation / other letter (`Po/Lo`) | 1 / 1 | 0 / 0 |
| Uppercase letter / other punctuation (`Lu/Po`) | 0 / 0 | 3 / 3 |

## Verification and limits

All 48 saved scores reproduce; ten output strings for the five selected cases
reconstruct from saved atoms, order and separators. An independent calculation
using rational arithmetic agrees on all nine geometry outcomes, attachment and
direction features, reference-gap roles and both cohort summaries. All 20 saved
inputs checked before and after remain unchanged, as does the frozen checkout.

Fifteen invented-input tests pass, including fixed threshold boundaries,
punctuation-only context, RTL gaps, invalid geometry and unresolved directions.
The core behaviors were implemented after expected failing tests. Ruff formatting
and lint, strict typing of four private scripts, repository mypy and all 3,766
repository tests pass. Detailed results and scripts stay ignored under
`artifacts/merchant-punctuation-geometry-v1/`.

**No changed merchant outputs were generated or scored.** Saved accuracy remains
**17/24 exact**, with 24 aligned unique outputs. This is a diagnostic observation,
not a demonstrated extraction gain or private-corpus acceptance. No source PDFs,
images, new extraction, OCR, model calls or label updates were used.

The sample is small and already used for training diagnostics. In particular,
all errors are RTL and all controls LTR; direction, segmentation and gap size
vary together. This measurement does not establish performance on required RTL
punctuation spaces, erroneous LTR spaces, OCR, or unseen documents. The v3 seed
uses repeat reads by the same reviewer, not independent held-out annotation.

## Recommendation and stop

The next proposed extraction task is **one punctuation-aware spacing candidate**:
infer context direction at punctuation boundaries, retain the existing geometry
thresholds, and compare merchant exact match across all 24 frozen seed cases.
Generate the candidate without reference labels and check all existing exact
controls for regressions. The candidate is recommended for an experiment only;
it has not been implemented or evaluated here.

This measurement stops here. No follow-on phase, threshold tuning, wider sample,
held-out evaluation or production integration is active.

```text
Scope: YES — measures punctuation attachment and geometry at incorrect and required separators
Experiment: row-profiles
Measurement: fixed geometry-pass counts and punctuation attachment categories
Result: hypothesis supported; 6/6 incorrect boundaries pass and 0/3 required controls pass, with zero unresolved boundaries
Next extraction task: STOP
```
