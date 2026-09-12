# Merchant Evidence Error Analysis Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to execute this single measurement task inline.

**Goal:** Locate the remaining merchant mismatches relative to the human evidence
regions and quantify their text-error signatures.

**Architecture:** Select the ten saved nonmatching proposals, compare their atom
boxes with unchanged human regions, and analyze saved text without generating
new predictions. Keep private detail local and publish aggregate categories.

**Tech Stack:** Python 3.13 in `.venv`, standard library, existing Pydantic and
PyMuPDF; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-12-merchant-evidence-error-design.md`.

## Global constraints

- Exactly ten saved nonmatching pre-rejection cases; no resampling or expansion.
- No label, prediction, merchant-rule, alignment, or transaction-decision changes.
- Source PDF access is limited to identity and page geometry, with no rendering,
  new text extraction, OCR, or external content transmission.
- Use the design's fixed evidence support thresholds and text signatures.
- Private output root: `artifacts/merchant-evidence-errors-v1/`.
- Use `Decimal` for reported rates and any financial arithmetic.

## Task 1: Quantify evidence and text mismatch categories

```text
Scope answer: YES — quantifies the remaining merchant extraction errors against human-marked evidence
Experiment: row-profiles
Extraction hypothesis: At least one of the ten fixed mismatches includes selected evidence wholly outside the human-marked merchant regions
Measurement: merchant-region support categories, unselected in-region evidence counts, text-order/spacing/control-character signatures, and character error rate
Fixed inputs: the ten mismatching pre-rejection cases, unchanged human merchant regions/text, frozen proposals and row observations, and source-page geometry
Smallest allowed files: docs/superpowers/specs/2026-09-12-merchant-evidence-error-design.md; docs/superpowers/plans/2026-09-12-merchant-evidence-errors.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-evidence-error-report.md; artifacts/merchant-evidence-errors-v1/**
Required output: quantified evidence-location and text-mismatch categories that identify the next extraction task
Stop condition: stop after the fixed error analysis; do not change labels, predictions, extraction rules, alignment, or sample membership
```

**Consumes:** Saved pre-rejection case scores/proposals, original row evidence,
human merchant regions/text, saved alignment, and local source-page geometry.
**Produces:** Private case-level evidence/text diagnostics and an aggregate report.

- [ ] Commit the approved design, charter amendment, and active status after all
  four required verification gates pass.
- [ ] Add focused invented-input tests covering strong/outside/boundary/invalid
  boxes, 50% support, overlapping reference regions, case-category precedence,
  token-order/spacing/control-character signatures, and insertion/deletion/substitution
  edit distance. Confirm failure before implementing the measurement functions.
- [ ] Implement the smallest local analysis and pass focused tests, Ruff, and mypy.
- [ ] Freeze the ten existing mismatch identities, verify their unique saved
  proposals and input bindings, and run the predeclared analysis once.
- [ ] Independently verify aggregate totals and unchanged original inputs. Publish
  results, recommend one next extraction task, and return the phase to `STOP`.
- [ ] Run required verification and commit only the permitted documentation.
