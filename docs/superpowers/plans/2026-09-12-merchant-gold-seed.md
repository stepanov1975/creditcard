# Merchant Gold Seed Preparation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this one bounded task inline. Steps use checkbox syntax for tracking.

**Goal:** Prepare the approved 24-slot source-only merchant calibration packet and
quantify source availability before handing it to the human reviewer.

**Architecture:** Record the bounded authority change, select six training pages
from metadata, and render a disposable local worksheet directly from source PDFs.
Keep sources and answers private. The task ends at the human-review handoff.

**Tech Stack:** Repository Python 3.13 virtual environment, standard library,
existing PyMuPDF, and one local HTML document; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-12-merchant-gold-seed-design.md`.

## Global constraints

- Use Python 3.13 and `.venv`.
- Full selected-page renders are 300 DPI; never clip by detected tables.
- Fixed sample: two OCR and four digital-only pages from six training documents;
  four human-identified transaction slots per page.
- No source text, prior gold, reviewer labels, predictions, validation, or held-out
  data may inform selection. No private content may enter Git or external tools.
- Private output root: `artifacts/merchant-gold-seed-v1/`.
- No production module, new dependency, hosted tool, controller, or schema family.
- No resampling to rescue missing sources, geometry, or sparse selected pages.

## Task 1: Source eligibility measurement and human-review handoff

```text
Scope answer: YES — measures whether source-page review can establish merchant references independently of detected table geometry
Experiment: shared evaluation
Extraction hypothesis: Full-page source review can establish unambiguous merchant text and transaction ownership for at least 20 of 24 calibration cases
Measurement: reference eligibility, merchant ambiguity, source availability, and merchant-boundary/ownership disagreement counts
Fixed inputs: one frozen selection from existing training-document metadata; source PDFs only; prior gold, reviewer labels, predictions, validation, and held-out data remain closed
Smallest allowed files: docs/research/2026-09-12-golden-dataset-assessment.md; docs/superpowers/specs/2026-09-12-merchant-gold-seed-design.md; docs/superpowers/plans/2026-09-12-merchant-gold-seed.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-gold-seed-report.md; artifacts/merchant-gold-seed-v1/**
Required output: a private source-review packet, quantified source eligibility, and human-reviewed merchant references when user decisions are available
Stop condition: stop at the human-review handoff; do not infer labels or expand the sample without the review
```

**Consumes:** frozen training membership/row metadata and source PDFs, with exact
private locations discovered locally rather than written in tracked documentation.
**Produces:** private selection, full-page images, source PDF copies, blank local
review worksheet, and a privacy-safe aggregate report.

- [x] Record the approved design and charter amendment. Set this phase as the only
  active task in live status. Preserve both previous STOP reports.
- [x] Run `.venv/bin/ruff format --check .`, `.venv/bin/ruff check .`,
  `.venv/bin/mypy src`, and `.venv/bin/pytest -q`; inspect every exit code.
  Commit the reviewed authority documents before private materialization.
- [x] Apply the exact metadata selector in the design. Require six distinct
  training documents and matching source identities. Freeze selection privately
  before inspecting/rendering selected page contents.
- [x] Render complete source pages using `page.get_pixmap(dpi=300, alpha=False)`;
  create opaque local source copies for context. Record only aggregate success
  and failure counts publicly.
- [x] Create the fixed local worksheet with blank fields, region marking, and
  local answer export/import. Verify behavior using invented input only; keep real
  pixels and answers out of model tools. Do not build a reusable application.
- [x] Verify all six images have full-page dimensions, 24 blank slots exist, local
  links resolve, and the worksheet has no external resources or network calls.
- [x] Publish aggregate source eligibility and set live status to
  `AWAITING_HUMAN_REVIEW`. Run required checks before the report commit.
- [x] Request the local worksheet panel for the user and hand off the first four cases.
  No merchant accuracy or accepted gold is claimed until decisions are available.
