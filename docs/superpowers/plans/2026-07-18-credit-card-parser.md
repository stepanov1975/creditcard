# General Credit-Card Statement Parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Use superpowers:test-driven-development for every production behavior.

**Goal:** Build a general, offline PDF-to-transaction converter that parses and exactly reconciles every relevant statement in the supplied corpus without document-specific exceptions.

**Architecture:** Extract positioned PDF/OCR evidence, infer table structure and semantic column roles from content, normalize transaction records, and require exact reconciliation. Repeated layout fingerprints are learned from document structure, never filename/hash/value special cases.

**Tech Stack:** Python 3.13, PyMuPDF, Tesseract 5 (`heb+eng`), Pillow/OpenCV-headless, Pydantic, Typer, pytest.

## Global Constraints

- Production code must never branch on a source filename, path, hash, known date, known merchant, known transaction amount, or known statement total.
- Runtime processing and data remain local and CPU-only.
- Financial arithmetic uses `Decimal`; no binary floating-point amount arithmetic.
- Hebrew output is logical Unicode NFC without translation or transliteration; raw evidence is retained.
- Only current-cycle billed records are emitted; all emitted records belong to exactly one reconciliation group.
- A reconciled result requires exact equality at the currency minor unit and no unresolved row/amount ambiguity.
- Unknown or ambiguous structures return explicit non-success statuses; the parser never silently guesses.
- The implementation plan may be revised when corpus evidence disproves an approach, while preserving these constraints.

---

### Task 1: Package, domain models, and exact reconciliation

**Files:** Create `pyproject.toml`, `src/ccparser/models.py`, `src/ccparser/reconcile.py`, and focused unit tests.

**Interfaces:** Define immutable evidence references, transactions, reconciliation groups, statement/batch results, statuses, and `reconcile(transactions, printed_totals)`. Monetary serialization must be deterministic strings.

Implement with red-green TDD: first assert sign conventions, multi-group membership, exact Decimal totals, missing/duplicate membership failure, ambiguity status, and stable serialization; then add the minimum models and reconciliation code. Run the focused tests and the full suite before committing.

### Task 2: Positioned PDF evidence and OCR fallback

**Files:** Create focused modules under `src/ccparser/evidence/` and tests under `tests/evidence/`.

**Interfaces:** Produce `DocumentEvidence` containing per-page positioned glyphs/words, vector rules, images, metadata, and extraction-quality metrics. Provide a cacheable OCR provider returning the same coordinate model.

Test digital glyph extraction, page-coordinate stability, custom/unmapped glyph quality detection, image-only detection, deterministic OCR command construction, TSV parsing, and cache keys before implementation. Use PyMuPDF `rawdict`; render 300-DPI clips and invoke Tesseract `heb+eng --oem 1` only when measured quality or a region request requires it.

### Task 3: General RTL, geometry, table, and semantic inference

**Files:** Create focused modules under `src/ccparser/layout/` and unit/property tests.

**Interfaces:** Convert evidence into script-correct cell text, line/column clusters, table regions, semantic column roles, and typed row candidates with provenance.

Drive implementation from synthetic mixed Hebrew/Latin/numeric cases and anonymized structural samples. Infer direction per run/cell from Unicode classes and glyph x-coordinates. Infer columns from repeated x bands, vector separators, header anchors, and value profiles. Do not introduce document identity checks or literal values from the corpus.

### Task 4: Statement discovery, transaction normalization, and audit

**Files:** Create `src/ccparser/discovery.py`, `normalize.py`, `audit.py`, and their tests.

**Interfaces:** Discover issuer/account/card/date metadata, transaction tables, totals, and reconciliation groups from semantic regions; normalize rows into transactions; classify document type from positive evidence; implement idempotent dry-run/apply quarantine with a manifest.

Test purchases, refunds, fees, interest, adjustments, installments, wrapped merchants, foreign currency, multi-card statements, statement/non-statement classification, ambiguity, and atomic manifest behavior. Audit all corpus PDFs in dry-run mode, visually/OCR-review ambiguous classifications, then apply only evidence-backed moves.

### Task 5: End-to-end parser, CLI/API, and serialization

**Files:** Create `src/ccparser/parser.py`, `output.py`, `cli.py`, package exports, and integration tests.

**Interfaces:** Implement `parse_statement`, `parse_directory`, `audit_directory`, JSON/CSV writers, and the two CLI commands. Return complete diagnostics for failures; strict mode exits 2 for validation failures and 1 for runtime/input errors.

Test single-file and directory parsing, deterministic JSON and UTF-8-BOM CSV, concurrency ordering, privacy-safe logs, corrupt/unsupported inputs, and strict exit codes before implementation.

### Task 6: Full-corpus convergence and generalization audit

**Files:** Add private ignored corpus expectations/artifacts plus only generalized regression tests to tracked test modules.

Run every retained PDF through the end-to-end parser. For each failure, use systematic debugging: capture the smallest structural cause, write a failing generalized/synthetic regression test, then fix the responsible extraction/layout/semantic rule. Reject fixes keyed to document identity or known values. Repeat until all retained statements are supported and exactly reconciled, all Hebrew/Latin/date fields pass representative visual checks, and all unrelated moves have manifest evidence.

Finally run the full unit/integration suite, full-corpus acceptance command, static checks, deterministic repeat comparison, and a search/review for prohibited per-document constants. Commit only after fresh verification.
