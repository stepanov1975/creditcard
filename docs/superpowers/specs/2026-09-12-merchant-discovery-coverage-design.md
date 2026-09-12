# Merchant Discovery-to-Frozen Coverage Trace

**Status:** Approved by the user's “proceed” on 2026-09-12 following the concrete
recommendation to compare original discovery metadata with the affected page's
frozen rows. Commit this authority before the targeted private availability check.

```text
Scope answer: YES — measures discovery-to-frozen row coverage loss for the four unmatched references
Experiment: shared evaluation
Extraction hypothesis: At least one original discovery row overlapping an unmatched reference was omitted during freezing
Measurement: original-discovery availability, discovery/frozen row differences, and reference-region coverage
Fixed inputs: one affected training page, its 38 frozen rows, four unchanged reference regions, and any retained original discovery snapshot
Smallest allowed files: docs/superpowers/specs/2026-09-12-merchant-discovery-coverage-design.md; docs/superpowers/plans/2026-09-12-merchant-discovery-coverage.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-discovery-coverage-report.md; artifacts/merchant-discovery-coverage-v1/**
Required output: measured coverage-loss stage or quantified original-discovery unavailability
Stop condition: stop after the fixed trace; if the original snapshot is unavailable, report no verdict without rerunning extraction
```

## Fixed trace and eligible evidence

Use the four saved null alignments on their one selected training page and its
38 unchanged frozen rows. First locate a retained original discovery snapshot
from the bundle preparation, using existing artifact inventory and historical
source code. Inspect filenames/metadata without opening unrelated statement
contents, old reviewer labels, validation/test records, or page pixels.

The source trace includes `prepare_bundle`, `rows_from_statement`, and the parser
called by bundle preparation at the historical foundation revision. Read them as
code evidence only; do not execute extraction or treat code alone as an independent
historical discovery snapshot.

A snapshot is eligible only when existing evidence binds it to the original
bundle-preparation discovery result for the same source identity. A separately
run control, corpus gate output, OCR cache, accepted-prediction projection, or
reconstruction from the frozen rows is not a substitute. Do not create a new
provenance system or parse unrelated documents to infer such a binding.

Preflight located 18 `results.json` files in separate control/corpus run output
roots and no discovery-named JSON file under the local artifact root. The bundle
builder's declared output contains rows, predictions, and crops; it does not
serialize the full discovery object. Verify the original snapshot's availability
for the fixed page before any row-set comparison.

## Measurement and stop rules

If an eligible original snapshot exists, locally compare the page's discovery-row
(page, bbox) multiset with its frozen-row multiset, reporting missing/extra rows.
Measure positive-area overlap of original discovery row boxes with the four
unchanged human transaction regions using the previously verified coordinate
mapping. Do not use merchant strings to match, create new row assignments, or
change the scores.

Support the hypothesis if an overlapping original discovery row is absent from
the frozen rows. Falsify it only when an eligible complete original snapshot shows
no such loss. A missing or unbound snapshot yields **NOT MEASURED** for the
historical coverage-loss hypothesis, with original-discovery availability **0/1
pages**, four unresolved cases, and the existing 38 rows recorded as counts.

Stop immediately after quantified unavailability; do not add a second support
task, reconstruct original metadata, run a later parser, or build a snapshot
archive/controller. Report any inference from the historical code separately
from measured historical evidence. Retain the four alignment failures and 10/24
best merchant score.

## Privacy and allowed work

A one-off local availability check may write only under ignored
`artifacts/merchant-discovery-coverage-v1/`. No production behavior is added or
changed. Tests for new geometry comparison behavior are necessary only if a bound
snapshot exists and requires a new comparison helper; an inventory-only stop does
not require tests that mirror filenames or implementation text.

Keep all private identities and source/reference content local and out of tool
output and Git. Do not read result payloads belonging to other runs merely because
they exist. Check original target inputs remain unchanged. Run the four repository
gates before tracked commits and publish aggregate findings only.

No new extraction, OCR, source rendering, label change, sample expansion,
validation/test access, gold promotion, reusable infrastructure, or production
integration is authorized. This is a diagnosis of a fixed training-seed coverage
limit, not a production acceptance task.
