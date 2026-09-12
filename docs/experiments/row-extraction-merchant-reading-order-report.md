# Merchant Reading-Order Experiment Report

**Date:** 2026-09-12  
**Status:** `COMPLETE — STOP`  
**Authority:** [Design](../superpowers/specs/2026-09-12-merchant-reading-order-design.md),
[plan](../superpowers/plans/2026-09-12-merchant-reading-order.md), and committed
charter amendment `1b32225` before candidate execution.

The fixed directional-run rule improved exact merchant matches from **8/24 to
10/24**, with **two gains and zero losses of previously exact matches**. Both
previously identified word-order cases became exact. The hypothesis of at least
two gains and zero losses is supported on this fixed training seed.

## Fixed comparison

All 24 human-reviewed references, the saved alignment with 20 matched owners and
four failures, and all 127 selected-page observations were reused unchanged. The
candidate reordered existing description atom IDs using geometry and Unicode
direction. It preserved atom text and membership, ownership, proposal regions and
scores, classifications, and original transaction decisions. No character reversal,
deduplication, new OCR, source extraction, or reference-driven order selection ran.

| Measurement | Saved pre-rejection descriptions | Directional-run candidate |
| --- | ---: | ---: |
| Exact merchants, all references | 8/24 (33.3%) | 10/24 (41.7%) |
| Exact merchants, aligned references | 8/20 (40.0%) | 10/20 (50.0%) |
| Unique-description coverage | 18/24 | 18/24 |
| Digital-page exact merchants | 5/16 | 7/16 |
| OCR-page exact merchants | 3/8 | 3/8 |
| Alignment failures | 4 | 4 |
| Omissions | 1 | 1 |
| Ambiguous owned outputs | 1 | 1 |
| Partial-text mismatches | 1 | 2 |
| Other text mismatches | 9 | 6 |
| Extra-text mismatches | 0 | 0 |

The net change is +2 exact merchants, or +8.3 percentage points across all 24
references. Both gains occur on digital pages. Four unmatched references remain
in the denominator; no alignment or sample membership was changed.

Of 108 description proposals across the selected pages, 52 had their atom order
changed. Five reviewed case outputs changed: two became exact, while three remain
non-exact. Character-level gains or regressions on those three were not measured
in this experiment. No proposal needed the invalid-geometry fallback. The count
of changed non-order prediction fields is zero across all 127 predictions.

## Interpretation and limits

This result supports an atom-order explanation for two failures and provides a
better deterministic merchant comparator for subsequent seed experiments. It
leaves eight unique but nonmatching descriptions, one omission, one ambiguous
owned output, and four alignment failures. OCR-page exact accuracy did not improve.

The seed has one human reviewer and already informed this hypothesis. The result
is calibration evidence, not an independent generalization estimate or golden-label
promotion. These are descriptions observed before financial rejection, so 10/24
is not a production transaction acceptance rate. The original financial and
row-type rejection behavior remains unchanged.

## Verification

The initial identity-only stub failed 15 invented-input checks as expected.
After implementation and correction of an invalid duplicate-ID test fixture,
all **21 focused tests passed**. They cover LTR/RTL and mixed runs, numeric and
neutral atoms, multiline ordering, the inclusive line threshold, stable physical
ties, repeated text, invalid geometry, and preservation of transaction decisions
and non-description proposals.

The saved comparator reproduced every original case score and output. An
independent check rendered saved candidate atoms without the candidate renderer
or scorer and reproduced all 48 before/after case scores, the 2/0 paired outcome,
the two corrected word-order cases, slice totals, and all 52 changed proposals.
All original input bytes remained unchanged, including the uploaded answers.
The frozen deterministic checkout retained its pinned SHA and clean tracked state.

Final verification passed: Ruff format/check, mypy over `src`, and **3,766
repository tests**. All four private Python files also pass Ruff format/check and
strict mypy. No production parsing code changed;
private-corpus verification was not run and no corpus-acceptance claim is made.
All private code, references, predictions, and detailed results remain local and
ignored under `artifacts/merchant-reading-order-v1/` and the earlier artifact roots.

## Next experiment recommendation

Test local OCR confined to the extractor-selected merchant evidence regions on
the same 24 cases, using 10/24 as the comparator and measuring paired exact-match
gains and losses. Region selection should use existing extractor evidence,
without human reference rectangles as prediction inputs. This would test whether
more focused recognition helps the remaining text errors. It is a separate
proposed extraction experiment and has not begun.

```text
Scope: YES — measured whether direction-aware ordering improves merchant extraction on fixed human references
Experiment: row-profiles
Measurement: merchant exact matches, paired gains/losses, coverage, and word-order errors resolved
Result: hypothesis supported on the fixed training seed; 8/24 to 10/24 exact, two gains and zero losses; both word-order cases resolved, coverage unchanged at 18/24
Next extraction task: STOP
```
