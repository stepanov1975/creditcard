# Merchant Alignment-Error Diagnosis Report

**Date:** 2026-09-12  
**Status:** `COMPLETE — STOP`  
**Authority:** [Design](../superpowers/specs/2026-09-12-merchant-alignment-errors-design.md),
[plan](../superpowers/plans/2026-09-12-merchant-alignment-errors.md), and charter
amendment committed at `403eeca` before private measurement.

All **four unmatched transactions are vertically separate from every frozen row
on their page**. Their transaction and merchant regions contain **no frozen atom
evidence**, including partial overlaps. The hypothesis that at least one failure
retains strongly supported transaction atoms is falsified on these four cases.

The saved coordinate calculation reproduces all 24 assignments and agrees with
an independent inverse calculation. The failure is therefore a measured gap in
frozen evidence coverage under the supplied reference regions. This does not
establish whether upstream discovery omitted valid transactions or the human
regions identify a different source area; no new source text or pixels were
examined.

## Failure categories and coverage

The four failures occur on one digital page with **38 frozen rows and 411 atom
records**. The diagnosis used the original 24 reference regions and 127 frozen
rows from six pages, preserving all matches and extraction outcomes.

| Predeclared failure category | Cases |
| --- | ---: |
| Vertical separation | 4 |
| Half-row-height exclusion | 0 |
| Horizontal separation | 0 |
| No overlap in either axis / no rows | 0 |
| Tie or collision | 0 |
| Coordinate disagreement | 0 |
| Unusable geometry | 0 |

For every failed transaction, some row boxes overlap horizontally, but none has
positive vertical overlap. No row can satisfy the original half-height threshold.
Relaxing that threshold alone would not create a positive-area match.

| Frozen-atom support for the four failed cases | Transaction regions | Merchant regions |
| --- | ---: | ---: |
| Cases with strongly supported atoms | 0/4 | 0/4 |
| Strongly supported atom records | 0 | 0 |
| Boundary / partial-overlap atom records | 0 | 0 |
| Unusable atom records | 0 | 0 |
| Outside-region comparisons | 1,644 | 1,644 |

The 1,644 count is **411 atom records compared against each of four references**,
not 1,644 distinct atoms. There is no evidence stranded outside its own frozen row
that could explain these four failures. No merchant string was inspected, changed,
reconstructed, or scored under a different alignment.

## Coordinate checks

- All **24/24 saved assignments** were reproduced, including the four nulls.
- The independent calculation scales reference regions into page points and
  reverses page rotation, comparing against original row boxes. It found **zero
  candidate-eligibility disagreements and zero final-assignment disagreements**.
- All **six review-image headers** match the expected 300-DPI full-page dimensions.
  None of the selected pages has nonzero rotation or a crop-box origin offset.
- All **127 row boxes and 1,474 atom boxes** are finite, nonempty, and inside the
  page. No atom extends outside its own row box.

The worksheet's existing coordinate code normalizes pointer positions against the
full-page overlay; preparation renders the whole source page. These checks found
no inconsistency in the saved mapping or page extent. They do not independently
certify the human region placement, upstream coordinates, or semantic ownership.

A separate local check scaled the four reference regions directly to page points
and used PyMuPDF rectangle intersections against the original rows and atoms.
It independently confirmed zero row vertical intersections and zero atom
intersections for either region type, without the analysis support classifier
or forward coordinate mapper.

## Consequence and next recommendation

The frozen row input does not represent the four marked transaction areas. Merchant
recognition changes restricted to those frozen rows cannot recover their missing
source evidence. Keep these four cases visible as alignment failures in the
24-case denominator. The best measured merchant result remains **10/24**; no
accuracy or coverage improvement is claimed by this diagnosis.

Recommended next measurement: compare the affected page's original discovery
rows with its 38 frozen rows and the four reference regions, to locate whether
coverage was lost during discovery or freezing. This requires a separately
approved read-only diagnosis and has not begun. The present result does not
justify rematching, moving reference boxes, or expanding the seed.

## Verification and limits

The initial stub failed 12 geometry checks as expected. The implementation passes
**15 invented-input tests** covering exclusion categories, the inclusive half-height
boundary, inverse coordinates and quarter-turn axes, ties/collisions, and evidence
inside a reference region but outside its source row.

The private analysis passes Ruff and strict mypy. Selected source copies match
their frozen identities; original references, rows, alignment, submitted answers,
and saved merchant summaries remained byte-identical. Review-image headers were
read without reading or displaying pixels. No extraction, OCR, rendering, label
edit, new match, or private content transmission occurred.

Final verification passed: Ruff format/check, mypy over `src`, and **3,766
repository tests**, plus the **15 focused geometry tests**. This is a single-reviewer
training-seed diagnosis, not independent gold verification or production acceptance. Production
code was not changed and the private corpus gate was not run. Detailed private
geometry and diagnostics stay ignored under `artifacts/merchant-alignment-errors-v1/`.

```text
Scope: YES — quantified the four unresolved row-alignment failures
Experiment: shared evaluation
Measurement: alignment-failure categories, coordinate-consistency checks, and frozen-atom coverage
Result: hypothesis falsified; all four cases are vertically separate from frozen rows with zero overlapping atoms; all 24 saved assignments and independent coordinate checks agree; merchant score remains 10/24
Next extraction task: STOP
```
