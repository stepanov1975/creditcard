# Merchant Alignment-Error Diagnosis

**Status:** Approved by the user's “proceed” on 2026-09-12 following the concrete
recommendation to quantify the four reviewed transactions without matching frozen
rows. Commit this design and charter amendment before private measurement.

```text
Scope answer: YES — quantifies the cause of four unresolved row-alignment failures
Experiment: shared evaluation
Extraction hypothesis: At least one unmatched transaction retains frozen atoms strongly supported by its human-marked transaction region
Measurement: alignment-failure categories, coordinate-consistency checks, and frozen-atom coverage
Fixed inputs: four saved alignment failures, 24 reference regions, 127 frozen rows and atoms, six source-page geometries
Smallest allowed files: docs/superpowers/specs/2026-09-12-merchant-alignment-errors-design.md; docs/superpowers/plans/2026-09-12-merchant-alignment-errors.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-alignment-errors-report.md; artifacts/merchant-alignment-errors-v1/**
Required output: quantified failure categories and hypothesis result
Stop condition: stop after this fixed diagnosis, without rematching, changing labels, or rerunning extraction
```

## Fixed population

Select exactly the four null entries in the saved seed comparison alignment.
Use the 24 unchanged reference regions and all 127 selected training-page rows
as alignment controls; detailed failure analysis covers only the four null cases.
No resampling, new source rows, text-assisted matching, or reference changes.

Read the six existing source PDF copies for identity, page size, crop-box metadata,
and rotation only. Read only the PNG signature/IHDR dimensions from the six
existing review images to check their 300-DPI full-page extent. Do not render or
inspect pixels, extract new text, invoke OCR, or inspect unrelated documents.
The review worksheet's existing code can be read to trace coordinate conventions.
Do not rerun worksheet preparation or import, and do not expose private text,
identities, regions, or images through tools or external services.

## Coordinate checks and alignment reproduction

Reproduce the original alignment using its unchanged normalized full-page
rotation-aware mapping and the existing matching function. Require exact agreement
with every saved assignment, including nulls. Retain the original overlap rule:
positive horizontal intersection, at least half of row height vertically covered,
unique largest IoU, and no two references assigned to one row.

Independently calculate the same matches by scaling each human region into display
page points and applying the inverse page rotation to compare it with original
row boxes. Implement the corresponding horizontal/vertical axes in display space:
for quarter-turn pages, the half-height rule applies to the original row width.
Compute axis-aligned intersections and IoU without the forward mapper or existing
alignment helper. Report candidate-eligibility and final-assignment disagreements
separately, including potential numerical-boundary sensitivity; do not use a
second mapping to replace the saved match.

Report page-image dimension agreement, nonzero page rotation/crop-box offsets,
invalid/outside row and atom geometry, and atoms extending outside their own row.
These checks can establish consistency of the saved geometry pipeline; they
cannot prove that the human chose the correct source region or that the upstream
extractor's coordinates identify the intended transaction.

## Four-case failure categories

For each failed case, retain private per-row intersection diagnostics and publish
only counts. Apply this disjoint precedence:

1. **Unusable geometry:** invalid human/row/page geometry prevents comparison.
2. **Coordinate disagreement:** forward and independent inverse tests disagree.
3. **Tie/collision:** qualifying rows exist but the original uniqueness rule fails.
4. **Half-row-height exclusion:** at least one row positively intersects the
   transaction region in both axes, but none covers half of its own height.
5. **Horizontal separation:** no positive-area row intersection, but some row has
   positive vertical overlap with the transaction region.
6. **Vertical separation:** no preceding category, but some row has positive
   horizontal overlap with the transaction region.
7. **No row coverage:** no row or no overlap in either axis.

Keep overlapping raw flags and candidate counts as well as the disjoint category.
For half-height exclusions, retain the maximum covered fraction privately and
count intersecting rows whose box fully contains a human transaction region.
Do not relax thresholds, compute alternative merchant scores, or assign new rows.

## Frozen evidence coverage

For all atoms in rows on each failed case's page, apply the already defined
strong-support rule separately against its transaction and merchant regions:
the atom center is inside a region and maximum one-region intersection covers
at least 50% of the atom area. Count supported atom records, distinct source rows,
source row types, and supported atoms lying outside their own row box. Keep other
atoms as boundary/outside/unusable rather than declaring them absent semantically.
Use strict inclusive box containment; report floating-boundary sensitivity if
encountered instead of repairing geometry.

The hypothesis is supported if at least one failed case has a strongly supported
transaction atom and usable, consistent coordinates. It is falsified on the fixed
sample if all four have usable, consistent coordinates and none has such evidence.
Otherwise report unresolved coordinate/input cases. In-region evidence supports
an alignment/representation limitation rather than complete absence of frozen
evidence, but does not establish correct words, complete transactions, or semantic
ownership. Absence from the frozen records alone cannot distinguish missed source
extraction from reference placement; report that uncertainty explicitly.

## Execution and stop

Permit only disposable geometry analysis and invented-input tests under ignored
`artifacts/merchant-alignment-errors-v1/`. Reuse existing contracts and support
classification; no shared schema/controller/CLI/workflow or production changes.
Test half-height boundaries, horizontal/vertical separation, atom support outside
its own row, and independent rotated/unrotated coordinate calculations before
private execution. Use Decimal for any reported rates.

Verify all source/reference/row/alignment input bytes remain unchanged and existing
merchant scores are not recomputed under a new alignment. Publish the quantified
finding and return live status to STOP. No extraction run, geometry repair, label
change, sample expansion, validation/test access, gold promotion, or production
integration is authorized.
