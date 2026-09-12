# Merchant Gold Seed Report

**Date:** 2026-09-12
**Status:** `COMPLETE — STOP` — the fixed seed has 24 human-reviewed merchant
references. The seed is a private candidate; existing gold is not replaced.

The approved [seed design](../superpowers/specs/2026-09-12-merchant-gold-seed-design.md)
and charter amendment were committed before selection/materialization. The frozen
metadata selection used six distinct training documents and no label, baseline,
prediction, merchant text, or detected semantic role.

| Measurement | Result |
| --- | ---: |
| Selected training documents | 6 |
| Selected source pages | 6 |
| OCR-evidence pages | 2 |
| Digital-only pages | 4 |
| Selected source PDFs available | 6/6 |
| Source identities matching frozen document identities | 6/6 |
| Complete source pages rendered at 300 DPI | 6/6 |
| Source availability, identity, or page-render failures | 0 |
| Prepared transaction review slots | 24 |
| Human-reviewed slots received | 24 |

The source-availability measurements above preceded human review. The user then
submitted answers for all 24 slots, including the cases beyond the initial
four-case handoff. No sample expansion or resampling occurred.

The ignored private packet contains the fixed selection, six full-page images,
opaque source PDF copies, and one local HTML worksheet with blank defaults,
user-drawn source regions, and local answer export/import. No private page was
shown to a model or sent to an external service. The worksheet contains no
merchant suggestions and blocks network connections.

Verification checked complete render dimensions, six local source links, all
worksheet element references, blank initial records, and answer export/import,
including preservation of invented mixed Hebrew/Latin text and rejection of
invalid evidence regions or mismatched answer files. The answer checks used
invented data. No browser rendering or manual source-content audit is claimed.

All four repository checks passed before the handoff commit: Ruff formatting,
Ruff lint, mypy, and the full suite of 3,766 tests. A portable private ZIP was also
checked for complete worksheet/source membership and archive integrity. The
worksheet panel was requested in the app; local file links provide the handoff
even if the app defers opening the panel.

## Human-reference validation

The submitted file was treated solely as annotation data. Validation used the
worksheet's existing saved-answer contract and the fixed private selection.
All six local source copies still match their frozen document identities. The
original answer bytes were preserved privately, and 24 source-linked reference
records were written under the same ignored seed directory. Merchant text and
evidence coordinates were not corrected, inferred, or replaced. All supplied
merchant strings already satisfied NFC and layout-whitespace normalization.

| Measurement | Result |
| --- | ---: |
| Expected case identities present exactly once | 24/24 |
| Human-confirmed entries | 24/24 |
| Entries passing the existing answer contract | 24/24 |
| Human-identified transactions with an unambiguous merchant | 24/24 |
| Merchant absent | 0 |
| Merchant ambiguous | 0 |
| Missing transaction slots | 0 |
| Human-reported boundary/ownership/legibility notes | 0 |
| Valid merchant evidence regions | 24 |
| Valid transaction-owner regions | 24 |
| Exact duplicate owner regions between cases on the same page | 0 |
| Merchant-text normalization changes | 0 |

**Hypothesis result: `SUPPORTED_BY_HUMAN_REVIEW`.** The user identified 24
unambiguous merchants with ownership and evidence regions, exceeding the
predeclared target of 20 among 24 fixed slots. This is human-reviewed reference
eligibility, not 100% extractor accuracy or independently established semantic
accuracy. Distinct transaction identities follow the user's source decisions;
the structural checks do not independently prove that every visual owner was
identified correctly. No second human review or model source audit occurred.

## Geometry diagnostics

All regions are finite, nonempty, and within the selected source page. Additional
geometry comparisons were diagnostic only; they introduced no new acceptance
threshold and did not modify any answer:

- 10 merchant rectangles are not completely contained within their own transaction
  rectangle: 7 extend by at most 5% of merchant-region area and 3 by 5–25%.
- 7 merchant rectangles intersect another reviewed transaction's rectangle: 3 by
  at most 5% of merchant-region area and 4 by 5–25%.
- 4 pairs of transaction rectangles overlap. No pair is identical, and no two
  cases duplicate their complete region sets.
- Every merchant rectangle overlaps its own transaction more strongly than any
  other reviewed transaction; none is disjoint from its own transaction.

These are rectangle relationships, not confirmed merchant-boundary or ownership
errors. Hand-drawn margins can overlap without the text being misattributed. Keep
these observations with the reference so later evaluation does not assume that
the rectangles form disjoint, exact text segments. Source transcription and
transaction attribution have not been independently re-audited.

## Completion boundary

The private candidate now contains the user's 24 merchant references plus their
source links and unchanged evidence. Previous authoritative gold, previous pilot
streams, parser outputs, and validation/held-out data remain untouched. No
extractor was run, no learned label was generated, and no corpus acceptance is
claimed. This bounded seed phase is complete and the program returns to `STOP`.
Gold promotion, method comparisons, and additional labeling require a separate
approved phase; these annotations do not authorize those actions automatically.

```text
Scope: YES — validated the human-created merchant calibration references
Experiment: shared evaluation
Measurement: reference eligibility, ambiguity, source-region validity, and ownership geometry diagnostics
Result: 24/24 human-confirmed unambiguous merchant references pass the existing contract; the 20/24 hypothesis is supported by human review; 7 merchant regions overlap neighboring owner rectangles diagnostically; independent semantic accuracy and extractor accuracy are NOT MEASURED
Next extraction task: STOP
```
