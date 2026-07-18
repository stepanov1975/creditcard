# General Credit-Card Statement Parser Design

## Goal

Create a local, CPU-only Python converter that extracts every currently billed
transaction from credit-card statement PDFs, restores logical Hebrew text, and
proves completeness by reconciling extracted billing amounts to every printed
statement total.

The supplied corpus is the acceptance dataset, not a source of document-specific
rules. Production logic must not branch on filenames, hashes, dates, known totals,
known merchants, or source paths. All behavior must derive from document content,
geometry, typography, repeated table structure, and issuer-independent financial
invariants.

## Architecture

1. A PDF evidence layer emits positioned characters, words, vector lines, images,
   fonts, and page metadata. Born-digital text is primary. OCR is a local fallback
   for image-only or objectively corrupt regions and preserves word boxes and
   confidence.
2. A geometry engine groups evidence into lines, columns, table regions, header
   bands, and row candidates. It uses script-aware ordering inside cells so Hebrew,
   Latin text, dates, and amounts remain logically correct.
3. A semantic engine assigns column roles from normalized headers and column value
   profiles. Layout fingerprints may cache inferred schemas for repeated templates,
   but must be content-derived and reusable across documents.
4. A transaction engine converts rows into typed records using Decimal arithmetic.
   It preserves dates, merchant text, original currency values, billing values,
   installments, credits, fees, and source evidence.
5. A reconciliation engine finds printed totals and subtotals, assigns transactions
   to reconciliation groups, and requires exact signed equality at currency minor
   units. It may choose among structurally valid extraction candidates but may not
   invent, edit, or discard amounts merely to balance.
6. A corpus auditor distinguishes statements from unrelated documents using positive
   document evidence. High-confidence non-statements can be moved to `unrelated/`
   with a hash/evidence manifest; ambiguous files remain and are reported.

## Interfaces

- `audit_directory(input_dir, quarantine_dir, apply=False) -> AuditReport`
- `parse_statement(path, strict=False) -> StatementResult`
- `parse_directory(path, output_dir, strict=False, jobs=None) -> BatchResult`
- CLI commands: `ccparse audit` and `ccparse parse`
- Statuses: `reconciled`, `unreconciled`, `unsupported`, `not_statement`
- Canonical UTF-8 JSON with Decimal values encoded as strings; UTF-8-BOM CSV as a
  flat transaction projection.

Charges are positive payable amounts and credits/refunds are negative. Only records
contributing to the current statement total are included. Future installment data
is metadata. Every output field retains page/bounding-box/raw-text provenance.

## Reliability and Privacy

All processing remains on-host. Unknown layouts fail visibly instead of being parsed
with a guessed schema. Logs redact sensitive descriptions and account numbers by
default. Tests include general synthetic cases, reusable layout-family fixtures,
and a private full-corpus acceptance sweep. Completion requires every retained
statement to reconcile exactly and every quarantined file to carry positive evidence.

