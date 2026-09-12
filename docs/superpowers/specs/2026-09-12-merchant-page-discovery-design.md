# New One-Page Merchant Discovery Diagnostic

**Status:** Approved by the user's “proceed” on 2026-09-12 following the concrete
recommendation for a new one-page local discovery diagnostic. This is a new run,
not reconstruction or recovery of the missing original discovery snapshot.
Commit this authority before private source extraction.

```text
Scope answer: YES — measures new page-discovery coverage of four unresolved merchant-seed transaction regions
Experiment: shared evaluation
Extraction hypothesis: A new native-text discovery run produces an eligible table row for at least one of the four unmatched references
Measurement: transaction-region coverage at native evidence, logical-row, and discovered-table-row stages
Fixed inputs: one affected digital training page, its 38 frozen rows, four unchanged reference regions, and the frozen deterministic checkout
Smallest allowed files: docs/superpowers/specs/2026-09-12-merchant-page-discovery-design.md; docs/superpowers/plans/2026-09-12-merchant-page-discovery.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-page-discovery-report.md; artifacts/merchant-page-discovery-v1/**
Required output: covered-reference counts, coverage delta against frozen rows, and supported or falsified hypothesis
Stop condition: stop after one fixed one-page discovery diagnostic; no tuning, replacement run, rematching, or support subsystem
```

## Fixed method

Use the four saved null alignments on the one affected digital training page and
its 38 frozen rows. Verify the selected local source copy against its existing
identity. Use the unchanged deterministic checkout at
`a2ed73aa58a4e4d8c76f918657d083fa922537d4` and the repository Python 3.13 environment.
Read only the selected source page's native glyphs, words, vector rules, and image
metadata through the frozen PDF evidence helpers. Preserve its actual page number
and rotated display geometry. Include existing document metadata but no evidence
from other pages. No page copy, new rendering, OCR, or external service is needed.

Construct a one-page `DocumentEvidence`, call the frozen `logical_rows` and
`discover_statement` functions, and retain the new evidence, logical rows, and
discovery privately. Do not call the whole-document parser, normalization,
reconciliation, currency OCR, or numeric repair. The absence of other-page context
and OCR makes this a native-text coverage diagnostic, not parser replay or
production acceptance. Record whether the existing quality rule requests OCR.

The four reference regions are used only after extraction for geometry scoring;
they must not select evidence, crop the page, or influence discovery. Read no
merchant strings in tool output and never view private page pixels.

## Measurements

For each of the four fixed transaction regions, count native word/glyph boxes,
logical rows, and discovered table rows with positive-area overlap. Also count
rows satisfying the unchanged alignment eligibility rule: positive horizontal
overlap and vertical overlap of at least half the row's height. A bounding-box
intersection measures geometric coverage only, not transaction or merchant
correctness. Do not create new assignments or change saved scores.

Primary metric: references with at least one eligible discovered table row, out
of four. The frozen comparator is zero out of four. At least one covered reference
supports the hypothesis; zero falsifies it on this fixed native-text diagnostic.
Record raw-word and glyph support against merchant regions as secondary geometry
counts, without transcribing or comparing their text.

Report the first absent stage per case: no native evidence, native evidence but
no eligible logical row, eligible logical row but no eligible discovered row,
or eligible discovered row. For native evidence, positive-area overlap of either
words or glyphs counts as present. Report positive-area coverage separately so
partial overlap cannot be confused with alignment eligibility.

Compare the discovered and frozen row-box multisets for this page, with counts
for shared, new-only, and frozen-only rows. These are new-run differences, not
historical rows lost during freezing. Count table regions and evidence records,
and preserve the full four-case denominator even if some stages return no rows.

## Boundary and validation

Only disposable private page-extraction/geometry code and invented-input tests
under ignored `artifacts/merchant-page-discovery-v1/` may be added. Use focused
failing tests for one-page isolation, original page-number preservation, coordinate
normalization, overlap boundaries, and stage attribution before implementation.
Reuse existing geometry/scoring functions where possible; add no shared API,
controller, schema family, CLI, receipts, or archive machinery.

Keep source contents, native text, identities, coordinates, and diagnostics local
and out of Git and tool output. Emit only aggregate counts. Verify original seed,
rows, references, alignment, and merchant scores remain unchanged. Run required
repository checks before tracked commits. Stop after the single diagnostic,
including a reported failure if it cannot execute; do not tune or substitute a run.

No frozen-tree edits, new labels, reference repair, sample expansion, gold
promotion, validation/test access, or production integration is authorized.
The best measured merchant comparator remains 10/24 until a separately authorized
merchant comparison actually establishes a different score.
