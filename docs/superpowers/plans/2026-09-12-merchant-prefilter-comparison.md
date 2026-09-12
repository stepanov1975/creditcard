# Merchant Pre-Filter Comparison Plan

> **For agentic workers:** Execute this single bounded comparison inline.

**Goal:** Measure merchant recognition before the existing future-billing
exclusion while preserving the original reference set and billing decisions.

**Spec:** `docs/superpowers/specs/2026-09-12-merchant-prefilter-comparison-design.md`.

## Task 1: Generate and compare the fixed merchant candidate

```text
Scope answer: YES — measures merchant recognition when saved future-billing candidate evidence is available before billing exclusion
Experiment: row-profiles
Extraction hypothesis: Adding merchant proposals from the saved pre-filter candidate table yields a positive net exact-match gain against 10/24 on the same references
Measurement: normalized merchant exact match, paired gains/losses, output coverage, alignment failures, omissions, and ambiguity
Fixed inputs: 24 unchanged training references, 127 frozen rows and reading-order predictions, one saved excluded eight-row candidate table, and the frozen tight profile rule
Smallest allowed files: docs/superpowers/specs/2026-09-12-merchant-prefilter-comparison-design.md; docs/superpowers/plans/2026-09-12-merchant-prefilter-comparison.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-prefilter-comparison-report.md; artifacts/merchant-prefilter-comparison-v1/**
Required output: paired merchant metric delta and supported or falsified positive-gain hypothesis
Stop condition: score the one fixed candidate on all 24 references and stop; no tuning, alternate candidates, label changes, or support subsystem
```

- [ ] Commit the approved design, charter amendment, and sole active phase after
  required repository verification.
- [ ] Write focused invented-input tests, observe expected failure, implement
  the smallest private candidate adapter, and pass focused tests/Ruff/mypy.
- [ ] Generate proposals for the saved excluded candidate rows without labels,
  then score all 24 references once against the saved 10/24 comparator.
- [ ] Verify original inputs and billing exclusions unchanged, publish aggregate
  results and limitations, return live status to STOP, and commit documentation.
