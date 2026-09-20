# Merchant Corrected-Block Ordering Witness Report

**Status:** COMPLETE — STOP.

**Date:** 2026-09-20.

**Authority:** The [design](../superpowers/specs/2026-09-20-merchant-corrected-order-witness-design.md)
was committed at `aea3b3f` before measurement.

## Result

**Both changed reviewed cases have exactly one matching corrected-block order.**
All seven atom occurrences remain intact, and no occurrence is omitted or reused.
The predeclared hypothesis is supported.

| Corrected blocks in case | Identity orders checked | Matching orders |
| --- | ---: | ---: |
| Four | 24 | 1 |
| Three | 6 | 1 |
| Total | 30 | 2 |

There are two single-witness cases, zero multiple-witness cases and zero cases
without a witness. No size, normalization or recorded-projection limit is reached.
Each query retains the existing nine-occurrence cap and NFC/Unicode-whitespace
projection, preserving every other code point and its within-block order.

The [earlier query on uncorrected atoms](row-extraction-merchant-atom-order-witness-report.md)
found no intact-block witness in either case. With the saved glyph correction,
both cases admit one. This supports combining within-block glyph correction with
block ordering; it does not establish a rule for choosing that order from source
evidence alone.

## Fixed data and verification

All **96 saved scores** reproduce. All **113 saved candidate outputs** reconstruct
from the **373 recorded atom decisions**, unchanged ownership, occurrence order
and separator decisions. Selection yields exactly the two changed digital
training cases, each still scored `other_mismatch`.

The existing exhaustive query and independent prefix/subset dynamic program agree
on both counts. The independent recursive normalization audit covers all 30 orders;
both saved representative index permutations use each original corrected block
once and match the reference projection. All aggregate fields agree. Sixteen
saved input files and the frozen checkout remain unchanged.

The 13 existing invented-input witness tests pass. Both new disposable scripts
pass Ruff and strict mypy. All four repository gates pass, including all 3,766
tests. Private scripts, index witnesses and logs are in ignored
`artifacts/merchant-corrected-order-witness-v1/`. No PDFs, pixels, new extraction,
OCR or models were used.

## Interpretation and next candidate

Exact merchant accuracy remains **19/24**, with 24/24 aligned unique outputs.
This diagnostic ignores whitespace and uses references to identify a matching
order. It generates no new extraction predictions and establishes neither a
21/24 score nor a validation gain. The reviewed seed is training data.

The recommended next task is one source-only candidate: order unambiguously LTR
blocks by horizontal geometry while retaining the saved glyph correction. Define
its eligibility and ambiguity guards before scoring, apply the same rule to all
113 saved owner groups, and save predictions before reading labels. Score all
24 reviewed cases against both existing views, including gains, losses and
coverage. A matching permutation from this diagnostic must never choose the
candidate's output. Spacing remains a separate exact-match requirement.

That recommendation is unexecuted. This phase ends here, with no production or
private-corpus acceptance claim.

```text
Scope: YES — measures whether corrected-block order explains two remaining merchant errors
Experiment: row-profiles
Measurement: intact corrected-block witness cases and matching identity-order counts
Result: hypothesis supported; 2/2 cases have one witness each across all 30 orders, with no unresolved cases
Next extraction task: STOP
```
