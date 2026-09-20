# Merchant Corrected-Output Spacing Diagnostic Report

**Status:** COMPLETE — STOP.

**Date:** 2026-09-20.

**Authority:** The
[design](../superpowers/specs/2026-09-20-merchant-corrected-spacing-design.md)
was committed at `6bda406` before measurement.

## Result

**Both changed reviewed digital outputs have whitespace-only errors, and each
unique matching block arrangement is the recorded order.** The predeclared
hypothesis is supported. No residual non-whitespace sequence difference remains
in these two saved corrected outputs.

| Predeclared category | Cases |
| --- | ---: |
| Non-exact output equals reference after NFC and whitespace removal | 2/2 |
| Unique witness equals recorded occurrence order | 2/2 |
| Unique witness requires a different order | 0/2 |
| Multiple matching orders | 0/2 |
| No matching order | 0/2 |
| Unresolved witness | 0/2 |

The same two cases satisfy both properties. Thirty occurrence permutations are
checked across the two cases, without normalization failures. All blocks and
occurrences are preserved. The result identifies spacing as the remaining error
category for these two cases; it does not establish which separator changes a
source-only extractor should make.

This resolves the earlier interpretation error: the matching arrangement did
not require reordering. The previous tolerance candidate preserved spacing when
order was unchanged, so its zero gain did not test spacing repair here.

## Verification and limits

All **144 saved scores** reproduce, and independent regex-based scoring agrees
on every record. All 113 glyph outputs reconstruct from 373 saved atom decisions;
the strict-order and tolerance outputs equal those saved glyph outputs. Both
saved witnesses reproduce exactly. Independent regex whitespace projection,
subset counting and normalization audits agree with the classifications and
identity-order findings.

The existing classifier and witness suites pass all **29 focused tests**. The
single disposable diagnostic module passes Ruff and strict mypy. All four
repository gates pass, including all **3,766 tests**. Twenty-one saved input files
and the frozen checkout remain unchanged. No native pages, PDFs, new extraction,
OCR or models are used. Private code and records stay in ignored
`artifacts/merchant-corrected-spacing-v1/`.

Exact merchant accuracy remains **19/24**, with **24/24 aligned unique outputs**.
No predictions or labels changed. These are two selected errors from the reviewed
training seed, not a validation estimate or a claim about every merchant error.

## Recommendation

Test one source-only spacing candidate that applies the existing tolerance-aware
renderer to eligible groups even when their order is already correct. Preserve
saved glyph correction, ownership and occurrence order. Retain the existing
direction, line, source-evidence and coordinate-tolerance guards; apply the same
rule across all 113 groups, without reading reviewed membership or references
during generation. Save outputs before scoring the 24 fixed training references
for exact matches, paired gains/losses and coverage.

This candidate is unexecuted. The diagnostic is complete and stopped.

```text
Scope: YES — quantifies remaining merchant extraction errors after glyph correction
Experiment: row-profiles
Measurement: whitespace-only cases and unique identity-order witnesses
Result: hypothesis supported; both cases are whitespace-only and already correctly ordered, with zero unresolved cases; exact accuracy remains 19/24
Next extraction task: STOP
```
