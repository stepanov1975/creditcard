# Merchant Discovery Exclusion Trace Plan

> **For agentic workers:** Execute this single bounded diagnostic inline.

**Goal:** Attribute the four fixed coverage exclusions to existing discovery
rules, preserving uncertainty about their semantic correctness.

**Spec:** `docs/superpowers/specs/2026-09-12-merchant-discovery-exclusion-design.md`.

## Task 1: Trace and quantify existing exclusions

```text
Scope answer: YES — quantifies the discovery decisions excluding four fixed transaction-reference regions
Experiment: shared evaluation
Extraction hypothesis: At least one unmatched reference is covered by a candidate table removed by an explicit future-billing or transaction-history filter
Measurement: reference coverage before and after discovery filters, with exclusion-rule case counts
Fixed inputs: saved one-page native evidence, logical rows and discovery, four unchanged training references, and the frozen deterministic checkout
Smallest allowed files: docs/superpowers/specs/2026-09-12-merchant-discovery-exclusion-design.md; docs/superpowers/plans/2026-09-12-merchant-discovery-exclusion.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-discovery-exclusion-report.md; artifacts/merchant-discovery-exclusion-v1/**
Required output: supported or falsified filter hypothesis and quantified exclusion decisions or unresolved cases
Stop condition: stop after one unchanged discovery trace and analysis of its saved decisions; no rule changes, alternate runs, or support subsystem
```

- [ ] Commit approved authority and the sole active phase after repository gates.
- [ ] Add and fail focused attribution tests; implement the minimal observer and
  attribution; pass focused tests, Ruff, and strict mypy.
- [ ] Trace the unchanged discovery once on saved evidence, require output parity,
  and quantify four-case exclusion decisions without private content in output.
- [ ] Verify original inputs unchanged, record aggregate findings and limits,
  return status to STOP, and commit the permitted documentation.
