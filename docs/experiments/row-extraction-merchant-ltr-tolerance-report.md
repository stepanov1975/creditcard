# Merchant LTR Tolerance Candidate Report

**Status:** COMPLETE — STOP.

**Date:** 2026-09-20.

**Authority:** The [design](../superpowers/specs/2026-09-20-merchant-ltr-tolerance-design.md)
was committed at `14b7a80` before implementation or generation.

## Result

**Exact accuracy remains 19/24, with zero gains and zero losses against all
three saved baselines.** Coverage remains 24/24. The improvement hypothesis is
falsified.

| Training-seed slice | Punctuation spacing | Glyph correction | Strict block order | Tolerance candidate |
| --- | ---: | ---: | ---: | ---: |
| All reviewed cases | 19/24 | 19/24 | 19/24 | 19/24 |
| Digital | 13/16 | 13/16 | 13/16 | 13/16 |
| OCR | 6/8 | 6/8 | 6/8 | 6/8 |

All score transitions are unchanged: 19 exact, two partial-text and three other
mismatches. Two reviewed strings still differ from punctuation spacing because
they retain glyph correction; none differs from either later saved candidate.

## Why the candidate has no effect

The seven groups previously rejected for overlap all pass the source-consistency
checks, but **their recorded order already equals increasing horizontal order**.
They now receive `unchanged_order`. The fixed candidate preserves saved spacing
when order is unchanged, so no group reaches its tolerance-aware renderer.

| Decision | Owner groups |
| --- | ---: |
| Strong directions are not exclusively LTR | 52 |
| Already in the proposed order | 41 |
| Fewer than two occurrences | 2 |
| Contains OCR evidence | 18 |
| Total | 113 |

There are **zero reordered groups, zero changed outputs and zero tolerance
joins**. All 373 selected occurrences and their saved corrected text remain
unchanged. No source guard or excessive-overlap rejection remains among the
seven formerly blocked groups.

The earlier diagnostic established a matching intact-block arrangement when
whitespace is ignored. It did not report whether that arrangement differed from
the recorded order. Treating it as evidence that a new horizontal order was
needed was an unsupported assumption. This candidate exposes that assumption;
it does not test spacing changes in already ordered groups.

Whether the two changed digital outputs now have only whitespace differences
is not measured in this phase. It must not be presented as an established cause
or a reason to claim that a spacing change will improve accuracy.

## Verification

The generator reconstructs all 113 saved glyph outputs from 373 decisions and
applies the same source-only rule to every group. It reads saved native evidence,
but no references, saved scores, diagnostic selections or witness orders.
The full candidate is saved before scoring. There is one generation and one
evaluation, with no post-score tuning or second candidate.

All 120 previous scores reproduce. Independent ordering/source checks and
rational tolerance calculations agree on all 113 decisions and outputs, all
144 score records, and all three slices against all three baselines. Existing
positive-gap spacing behavior is shared unchanged; new source/tolerance logic
is replayed separately.

Twelve invented-input scenarios pass against both implementations: **24 focused
test cases**. New behavior was developed through focused red/green cycles.
The seven private Python files pass Ruff and strict mypy. All four repository
gates pass, including all 3,766 tests.

Twenty existing saved input files, the candidate output and the frozen checkout
remain unchanged during verification. No PDFs, new extraction, OCR or models
were used. Private code, predictions and logs stay in ignored
`artifacts/merchant-ltr-tolerance-v1/`. These are training-seed results, with no
validation, production or private-corpus acceptance claim.

## Recommendation

Before another candidate, classify the **two reviewed digital outputs changed
by glyph correction** using their current saved strings and fixed references.
Measure whether they match after removing whitespace, and whether their saved
unique corrected-block witness is the recorded identity order. This will
distinguish remaining spacing errors from residual character-order errors
without changing predictions or choosing a rule from reference text.

That diagnostic is unexecuted. This candidate is complete and stopped.

```text
Scope: YES — tests consistent coordinate tolerance in merchant ordering and spacing
Experiment: row-profiles
Measurement: exact merchant matches, paired gains/losses and coverage
Result: hypothesis falsified; 19/24 remains 19/24 with zero gains/losses and 24/24 coverage; all seven formerly blocked groups are already ordered
Next extraction task: STOP
```
