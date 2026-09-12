# Merchant Discovery Coverage Trace Plan

> **For agentic workers:** Execute this single read-only measurement inline.

**Goal:** Locate discovery-to-frozen coverage loss, or establish that the original
metadata needed for that historical comparison was not retained.

**Architecture:** Read existing historical code and artifact inventory, then check
original-snapshot eligibility for one page before any private row-set comparison.
Stop on missing original evidence without substituting a new parser run.

**Tech Stack:** Python 3.13 in `.venv`, existing contracts, standard library.

**Spec:** `docs/superpowers/specs/2026-09-12-merchant-discovery-coverage-design.md`.

## Task 1: Trace the affected page's original discovery evidence

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

- [ ] Commit the approved design, charter amendment, and active phase after the
  required repository checks pass.
- [ ] Verify the fixed four failures and affected page's 38 frozen rows, and
  locate an eligible original discovery snapshot using existing origin evidence.
- [ ] If available, compare original and frozen row multisets and reference
  coverage with focused tests for any new helper. If unavailable, record 0/1
  original snapshots and stop with historical loss NOT MEASURED.
- [ ] Preserve original references, alignment, rows, and merchant scores; publish
  the aggregate finding and distinguish code inference from historical evidence.
- [ ] Return live status to STOP, run required verification, and commit only the
  permitted documentation.
