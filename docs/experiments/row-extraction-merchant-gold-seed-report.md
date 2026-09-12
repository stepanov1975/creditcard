# Merchant Gold Seed Source-Review Report

**Date:** 2026-09-12
**Status:** `AWAITING_HUMAN_REVIEW`

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
| Blank transaction review slots | 24 |
| Human-reviewed slots | 0 |

This is a source-availability result, not merchant reference eligibility or
extraction accuracy. The reference hypothesis, unique represented transaction
count, merchant ambiguity, and boundary/ownership issues remain `NOT MEASURED`
until human source decisions are available. The four slots on each page are a
review budget; pages with fewer eligible transactions are recorded without
resampling.

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

The next action is the user's source review of the first four cases, followed by
validation of their locally saved answers. Do not run extractors, generate labels,
expand the set, change the selection, or create support work while awaiting that
review. The old pilot labels and all validation/held-out data remain closed.

```text
Scope: YES — measured source availability for an independent merchant calibration reference
Experiment: shared evaluation
Measurement: selected-source availability and complete-page materialization
Result: 6/6 sources available and identity-matched; 6/6 full pages rendered; 24 blank review slots; merchant reference eligibility NOT MEASURED pending human review
Next extraction task: human source review of the first four fixed calibration cases
```
