# Merchant-Region OCR Plan

> **For agentic workers:** Use superpowers:executing-plans to execute this single measurement task inline.

**Goal:** Measure one merchant-focused OCR candidate against the fixed 10/24
reading-order comparator.

**Architecture:** A private OCR script uses the frozen OCR checkout to read
proposal geometry and local source copies. A separate local scorer uses the
existing deterministic-checkout helper to compare saved outputs with references.
Keep all historical and production code read-only.

**Tech Stack:** Python 3.13 in `.venv`, existing PyMuPDF/Pydantic and local Tesseract.

**Spec:** `docs/superpowers/specs/2026-09-12-merchant-region-ocr-design.md`.

## Task 1: Run and score one fixed merchant-region OCR candidate

```text
Scope answer: YES — measures whether merchant-focused OCR improves extraction
Experiment: row-ocr
Extraction hypothesis: OCR of extractor-selected merchant regions yields a positive net exact-match gain over 10/24
Measurement: merchant exact matches, paired gains/losses, coverage, and crop/recognition failures
Fixed inputs: 24 training references, saved alignment, 127 rows, 108 description proposals, six source pages, frozen OCR settings
Smallest allowed files: docs/superpowers/specs/2026-09-12-merchant-region-ocr-design.md; docs/superpowers/plans/2026-09-12-merchant-region-ocr.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-region-ocr-report.md; artifacts/merchant-region-ocr-v1/**
Required output: paired exact-match delta and hypothesis result
Stop condition: stop after one fixed comparison, without tuning, new labels, or sample expansion
```

- [x] Commit the approved design, charter amendment, and sole active phase after
  the four required repository verification gates pass.
- [x] Add focused invented-input tests for union/invalid/rotated/outside boxes,
  OCR evidence replacement, empty results, reading order, and original ownership
  and multi-proposal ambiguity. Confirm expected failure before implementation.
- [x] Implement private crop/recognition helpers using the frozen OCR functions
  and the existing reading-order rule. Pass focused tests, Ruff, and strict mypy.
- [x] Verify source/model/config bindings, apply OCR once to all 108 proposals,
  and save private evidence and failure categories. Recognition reads no references.
- [x] Reproduce all saved baseline case outputs/scores, score all 24 candidates,
  and independently verify scores, paired counts, and unchanged original inputs.
- [x] Publish only aggregate results, return the phase to STOP, run the four
  required gates, and commit only the allowed documentation.
