# Merchant Reading-Order Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to execute this single measurement task inline.

**Goal:** Test whether a general directional-run rule improves merchant text on
the fixed seed without losing previously exact matches.

**Architecture:** A disposable private permutation of saved description atom IDs,
using the existing renderer and scorer. No production or historical source edits.

**Tech Stack:** Python 3.13 in `.venv`, standard library and existing Pydantic.

**Spec:** `docs/superpowers/specs/2026-09-12-merchant-reading-order-design.md`.

## Task 1: Score one fixed reading-order candidate

```text
Scope answer: YES — tests whether reading order improves extracted merchant text
Experiment: row-profiles
Extraction hypothesis: Direction-aware ordering adds at least two exact merchant matches with zero losses
Measurement: merchant exact matches, paired gains/losses, coverage, and word-order errors resolved
Fixed inputs: 24 human references, saved alignment, 127 frozen rows and pre-rejection predictions
Smallest allowed files: docs/superpowers/specs/2026-09-12-merchant-reading-order-design.md; docs/superpowers/plans/2026-09-12-merchant-reading-order.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-reading-order-report.md; artifacts/merchant-reading-order-v1/**
Required output: paired accuracy delta and hypothesis result
Stop condition: stop after this fixed comparison, without tuning against the answers
```

- [ ] Commit the design, charter amendment, and sole active phase after all four
  repository verification gates pass.
- [ ] Add invented-input tests for LTR, RTL, mixed runs, numbers, neutral atoms,
  multiline clustering, boundary/tie behavior, duplicate text and invalid boxes,
  and preservation of all non-order prediction fields. Confirm expected failure.
- [ ] Implement the smallest candidate and pass focused tests, Ruff, and mypy.
- [ ] Verify fixed input bindings, reproduce the saved comparator, and apply the
  fixed candidate once to all saved descriptions; score all 24 references.
- [ ] Independently check aggregate scores and unchanged inputs, publish the
  hypothesis result, and return the phase to STOP without tuning.
- [ ] Run all four repository verification gates and commit only permitted docs.
