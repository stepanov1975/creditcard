# Merchant Block-Overlap Report

**Status:** COMPLETE — STOP.

**Date:** 2026-09-20.

**Authority:** The [design](../superpowers/specs/2026-09-20-merchant-block-overlap-design.md)
was committed at `0abe1a4` before implementation or measurement.

## Result

**All seven rejected groups have consistent source ordering despite very small
box overlaps.** Left-edge, center and right-edge orders agree strictly in every
group, with resolved native-word matches and disjoint glyph evidence. Both
reviewed groups meet these conditions. The predeclared hypothesis is supported.

| Measurement | Result |
| --- | ---: |
| Selected groups / reviewed groups | 7 / 2 |
| Atom occurrences | 45 |
| Occurrence pairs examined | 146 |
| Pairs with positive horizontal overlap | 22 |
| Crossing / nested / coincident intervals | 22 / 0 / 0 |
| Repeated atom / native-word pairs | 0 / 0 |
| Pairs sharing a glyph index | 0 |
| Unresolved groups | 0 |

Overlap is **0.00000455564–0.0000722798 of the smaller block width**, and
**0.00000903497–0.0000722798 of the smaller average character width**. Thus the
largest measured overlap is about **0.00723% of an average character width**.
Every ratio is defined; no new overlap cutoff was selected.

All 45 original atom-to-native-word matches resolve, accounting for 88 glyph
assignments. Each group's word assignments are distinct and glyph sets are
pairwise disjoint. One overlapping pair has equal text but distinct source
evidence; it is not treated as a duplicate or removed.

## Interpretation

The strict zero-overlap guard rejects these groups even though their three
geometric orders agree and their source evidence is independent. The very small
ratios are consistent with numerical-scale box overlap. This phase does not
establish the numerical cause, a universal tolerance or a corrected merchant
string. It also does not measure whether a spacing rule will handle the new
adjacencies correctly.

Exact merchant accuracy remains **19/24**, with **24/24** aligned unique outputs.
No predictions, source boxes, labels or extractor rules changed. Reference-matching
permutations were not loaded. This is a diagnosis on the existing training seed,
not a validation or production-acceptance result.

## Verification

All 113 saved owner decisions and output strings reproduce, including the seven
overlap rejections. All 120 saved scores reproduce. Selection uses the saved
decision category, independently replayed, without expanding the sample.

Exact rational measurements agree with independent decimal geometry and direct
native-word/glyph checks for all seven groups, 22 overlaps and 45 source matches.
The separate checker also verifies all scores and aggregate fields. Twenty saved
input files and the frozen checkout remain unchanged. Native-page snapshots
were read locally; no PDFs, pixels or new extraction were used.

Eleven invented-input tests pass, covering ratios, interval categories, strict
ordering, invalid geometry, word and glyph attribution, repeated identities,
shared evidence, equal-text occurrences and undefined character widths. New
diagnostic behavior was developed through focused red/green cycles. All five
private Python files pass Ruff and strict mypy. All four repository gates pass,
including all 3,766 tests.

Private measurements, code and logs stay in ignored
`artifacts/merchant-block-overlap-v1/`. Tracked reporting contains aggregates only.

## Recommendation

Test one tolerance-aware ordering-and-spacing candidate next. Reuse the existing
coordinate tolerance consistently for both overlap eligibility and new-neighbor
spacing, while retaining strict agreement of edge/center order and distinct
native-word/glyph evidence. Retain the saved glyph correction and ownership.
Freeze the exact rule before scoring; apply it to all
113 saved groups and compare all 24 reviewed cases with the existing baselines,
including regressions and coverage. Do not choose output order from references.

That recommendation is unexecuted. This diagnostic is complete and stopped.

```text
Scope: YES — quantifies merchant block overlap that prevented ordering
Experiment: row-profiles
Measurement: overlap ratios, interval categories, ordering agreement and source ambiguity
Result: hypothesis supported; all 7 groups have consistent independent source order, with 22 tiny crossing overlaps and no unresolved groups
Next extraction task: STOP
```
