# Residual Merchant Error Analysis Plan

> **For agentic workers:** Execute this single fixed diagnostic inline.

**Goal:** Separate evidence access/ownership failures from text mismatches on the
current 13/24 merchant comparison.

**Spec:** `docs/superpowers/specs/2026-09-12-merchant-residual-errors-design.md`.

## Task 1: Diagnose the 11 fixed residual cases

```text
Scope answer: YES — quantifies residual merchant text, selection, and ownership errors on the fixed seed
Experiment: row-profiles
Extraction hypothesis: At least one omission or ambiguous-output case retains strongly located alphabetic merchant evidence or a strongly supported proposal that the single-output contract does not expose
Measurement: retained-evidence support, proposal ownership conflicts, omission gates, text-error signatures, and character error rate
Fixed inputs: 11 non-exact pre-filter cases, 24 unchanged references, 135 saved row/prediction records, candidate alignment, and selected source-page geometry
Smallest allowed files: docs/superpowers/specs/2026-09-12-merchant-residual-errors-design.md; docs/superpowers/plans/2026-09-12-merchant-residual-errors.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-residual-errors-report.md; artifacts/merchant-residual-errors-v1/**
Required output: quantified residual error categories and supported or falsified retained-evidence hypothesis
Stop condition: stop after the fixed 11-case analysis; no new prediction, label change, alternate extraction, or support subsystem
```

- [x] Commit the approved scope and sole active phase after repository gates.
- [x] Add focused invented-input tests, confirm expected failures, implement the
  smallest private analysis, and pass focused tests/Ruff/mypy.
- [x] Reproduce the 24 scores, diagnose only the 11 fixed failures, and quantify
  geometry, ownership, omission gates, and text signatures without new predictions.
- [x] Verify original inputs unchanged, report measured causes and uncertainty,
  return live status to STOP, and commit aggregate documentation.
