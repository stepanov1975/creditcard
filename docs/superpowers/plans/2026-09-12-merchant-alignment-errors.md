# Merchant Alignment-Error Plan

> **For agentic workers:** Use superpowers:executing-plans to execute this single measurement task inline.

**Goal:** Distinguish alignment-rule and frozen-evidence coverage limits behind
four unmatched human-reviewed transactions.

**Architecture:** One private geometry analyzer reuses frozen observations and
human regions, independently checks the coordinate calculation, and publishes
only aggregate failure categories. Historical source and matches remain read-only.

**Tech Stack:** Python 3.13 in `.venv`, standard library, existing PyMuPDF/Pydantic.

**Spec:** `docs/superpowers/specs/2026-09-12-merchant-alignment-errors-design.md`.

## Task 1: Quantify the four unmatched references

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

- [x] Commit the approved design, charter amendment, and active phase after all
  four required repository verification gates pass.
- [x] Add invented-input tests for overlap/category precedence, inclusive half
  height, coordinate inversion and quarter-turn axes, and in-region atoms outside
  their own row. Confirm expected failure before implementing the new analysis.
- [x] Implement the smallest private geometry analysis; pass focused tests,
  Ruff, and strict mypy before accessing the fixed private measurement inputs.
- [x] Freeze the four saved failures, verify the image/page coordinate context,
  reproduce all 24 saved alignments, and run the independent inverse calculation.
- [x] Quantify the four failure categories and their transaction/merchant atom
  support, verifying all original inputs and saved merchant outcomes are unchanged.
- [x] Publish the aggregate result, return the phase to STOP, run the four required
  gates, and commit only allowed documentation.
