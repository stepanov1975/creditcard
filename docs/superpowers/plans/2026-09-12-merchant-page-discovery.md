# One-Page Merchant Discovery Plan

> **For agentic workers:** Execute this single bounded measurement inline.

**Goal:** Measure where native-text extraction loses geometric coverage of four
unmatched training references in one new discovery run.

**Architecture:** Selected-page native evidence through frozen helpers, then
existing logical-row/discovery functions and fixed geometry scoring. Private
artifacts only; aggregate tracked report.

**Spec:** `docs/superpowers/specs/2026-09-12-merchant-page-discovery-design.md`.

## Task 1: Run and measure the fixed page diagnostic

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

- [ ] Commit approved design, charter amendment, and sole active phase after the
  four required repository gates.
- [ ] Add invented-input tests; confirm expected failure; implement the smallest
  selected-page reader and coverage measurement; pass focused tests and checks.
- [ ] Run once on the fixed page without reference-guided extraction; measure
  four-case stage coverage and new/frozen row differences.
- [ ] Verify fixed inputs unchanged, publish aggregate result and limitations,
  return live status to STOP, and commit permitted documentation.
