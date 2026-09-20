# Merchant LTR Block-Ordering Candidate Report

**Status:** COMPLETE — STOP.

**Date:** 2026-09-20.

**Authority:** The [design](../superpowers/specs/2026-09-20-merchant-ltr-block-order-design.md)
was committed at `d27bf83` before implementation or generation.

## Result

**Exact accuracy remains 19/24, with zero gains and zero losses against both
saved baselines.** The predeclared improvement hypothesis is falsified.

| Training-seed slice | Punctuation spacing | Glyph correction | Block-order candidate |
| --- | ---: | ---: | ---: |
| All reviewed cases | 19/24 | 19/24 | 19/24 |
| Digital | 13/16 | 13/16 | 13/16 |
| OCR | 6/8 | 6/8 | 6/8 |

Alignment and unique-output coverage stay **24/24**. All score transitions are
unchanged: 19 exact, two partial-text and three other mismatches. Two reviewed
strings differ from punctuation spacing because they retain the earlier glyph
correction; none differs from the saved glyph candidate.

## Generation outcome

The rule changes **zero of 113 owner orders and zero rendered outputs**. All
373 atom occurrences and their corrected text are preserved.

| Decision | Owner groups |
| --- | ---: |
| Strong directions are not exclusively LTR | 52 |
| Horizontal block boxes overlap | 7 |
| Fewer than two occurrences | 2 |
| Eligible and already in horizontal order | 34 |
| Contains OCR evidence | 18 |
| Total | 113 |

No group reaches a changed-order rendering decision. Seven groups fail the
predeclared non-overlap guard. This result does not establish whether those
overlaps make ordering ambiguous; their magnitude and source attribution were
not measured in this phase. The negative result applies to this fixed guarded
candidate, not to every possible geometric ordering rule.

Generation reconstructs all 113 saved glyph outputs before applying the rule.
It reads no references, previous scores, witness permutations, source PDFs or
glyph pages. The complete predictions are saved before scoring; there is one
generation and one evaluation, with no threshold changes or post-score tuning.

## Verification

All 96 earlier scores reproduce. Independent rational-geometry replay agrees
on all 113 ordering decisions and outputs. Separate score calculation agrees on
all 120 records and all three source slices against both baselines. The existing
spacing function is shared, unchanged; the source-order calculation is independent.

Thirteen invented-input tests pass at the complete candidate seam, covering
ordering, exact fallback output, repeated occurrences, eligibility, geometry,
existing spacing and normalization. New behavior was implemented through focused
red/green cycles. The seven private Python files pass Ruff and strict mypy.
All four repository gates pass, including all 3,766 tests.

The 16 existing saved input files, saved candidate output and frozen checkout
remain unchanged during verification. Code, predictions and logs stay in ignored
`artifacts/merchant-ltr-block-order-v1/`. No production or private-corpus
acceptance claim is made. These are training-seed results; held-out data remains
unopened.

## Recommendation

The next recommended task is to quantify the seven groups rejected for horizontal
overlap: measure overlap relative to block width and character width, distinguish
duplicate/nested evidence from overlapping word boxes, and determine whether
source positions still establish an unambiguous order. Keep reference-matching
orders diagnostic only. Do not relax the guard or generate another candidate
without that measurement.

This recommendation is unexecuted. The current candidate is complete and stopped.

```text
Scope: YES — tests a source-only merchant block-ordering candidate
Experiment: row-profiles
Measurement: exact merchant matches, paired gains/losses and coverage
Result: hypothesis falsified; 19/24 remains 19/24, zero gains/losses, 24/24 coverage and zero reordered groups
Next extraction task: STOP
```
