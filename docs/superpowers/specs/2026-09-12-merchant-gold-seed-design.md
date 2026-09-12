# Merchant Gold Seed Design

**Status:** Approved for the bounded seed by the user's “ok. proceed” on 2026-09-12,
following the cited assessment and the user's offer to review a small seed.
Private materialization starts only after this design and the charter/live-status
amendment are committed. No second design approval is required for this scope.

**Purpose:** Establish a small human-reviewed merchant calibration reference from
full source pages, independently of detected row/table geometry. This is a new
training-only phase; it does not repair or repeat either stopped pilot.

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

## Frozen selection

Use the existing source-document split inventory and row metadata. Metadata-only
preflight found 2,503 training rows, 78 training documents, and 120 represented
training pages: 9 with OCR atoms and 111 with digital-only atoms. All 78 source
PDF paths exist. These counts do not certify source readability or reference
quality. Only document identity, split, source path, page number, and atom source
mode may inform selection. Ignore baseline types, atom text, semantic column
roles, accepted output, and labels.

For each represented training page, compute SHA-256 over the UTF-8 string
`merchant-gold-seed-v1`, NUL, document identity, NUL, decimal page number.
Sort by this key, with document identity and page number as tie breakers. Select
the first two OCR pages from distinct documents, then the first four digital-only
pages from four further documents. Freeze these six identities privately before
rendering. Do not replace a selected page based on contents or rendering outcome.
Require row and inventory split membership to agree and each selected source
PDF's SHA-256 to match its frozen document identity. This uses the existing
identity boundary; no new provenance or receipt machinery is introduced.

Each page supplies four calibration slots: the first four complete transactions
that start on that page, in visible top-to-bottom reading order. If transaction
tables are side by side, use the right table first. A continuation of a transaction
counts with its owner and does not create an additional slot. A transaction that
started on a preceding page does not consume a slot. Fewer than four eligible
transactions is recorded as a missing slot, without replacement. Thus 24 is a
fixed review budget, not an assertion that 24 independent transactions exist.
All selected documents remain in training. This sample is for policy calibration,
not an unbiased population estimate or model selection.

## Source-only review packet

Render the six complete selected pages directly from their PDFs at 300 DPI using
the existing PyMuPDF dependency, without detected-table clipping, predicted row
markers, OCR text, or model merchant suggestions. Provide opaque, local copies of
the six source PDFs for document context. Keep all private identities, sources,
images, and answers under the ignored `artifacts/merchant-gold-seed-v1/` tree.

A single local HTML worksheet may display these fixed pages, zoom, accept merchant
text, collect user-drawn evidence regions, and export/import the user's answers.
It is a disposable packet for these 24 slots, with no server, external assets,
network requests, database, new package, reusable controller, or hosted service.
This narrowly authorizes the immediate review artifact needed for reference
eligibility measurement; it does not authorize an annotation product or framework.
No private pixels or text are sent to model tools or external services.

The initial values are blank. The user's first judgment is made independently of
parser/model outputs. For each available transaction, the user records:

- the printed merchant text, preserving Hebrew/Latin reading order and punctuation;
- a transaction region that identifies the owner and merchant region(s) supporting
  the text, allowing multiple lines without requiring frozen atom IDs;
- a status: present with one answer, merchant absent, merchant ambiguous, or no
  eligible transaction for the slot; and
- optional broader printed description and a boundary/ownership/legibility note.

The page image coordinate system defines the evidence rectangles, normalized to
the full page; these are geometry values, not financial arithmetic. Any copied
financial text is stored as text. Financial arithmetic, if later needed, uses
`Decimal`. Missing source and ambiguous evidence are not equivalent to absence.

The merchant is the minimal source-supported span identifying the printed
merchant, including its owned continuation when necessary. Exclude separately
identifiable location, category, installment, fee, exchange-rate, and processor
reference text. Include a suffix or processor payload only when inseparable from
the printed merchant identity. Do not perform alias mapping, entity resolution,
spelling correction, or transliteration. Record ambiguity when the rule does not
determine one defensible boundary or owner.

These are new calibration records, not mutations of historical `GoldRow` labels.
An uncertain merchant does not assert that other financial fields are uncertain.
The seed does not claim a complete financial reference or corpus acceptance.

## Measurements and handoff

Before handoff, report selected-source availability, source-identity agreement,
full-page rendering success, actual page/document counts, and blank review slots.
On a source failure, stop with its aggregate category; do not resample or build a
support task. A render success alone does not measure merchant eligibility.

After the user's saved answers are available, validate their coverage and source
regions, retain unresolved cases, and report unique transaction count, unambiguous
merchant count, absence, ambiguity, missing slots, and boundary/ownership issue
counts. The hypothesis requires at least 20 supported unambiguous merchant
references among the fixed 24 slots; a smaller result is reported without changing
the denominator. Until human review, the result is `NOT MEASURED`.

One human reviewer plus source checks is not independent human–human validation.
No automatic agreement measure may substitute for the human's source decisions.
Further independent review, automated label proposals, a 100–200-transaction
expansion, synthetic generation, extractor runs, validation/test access, and
production integration are outside this phase. Any later phase needs a concrete
new approval and authority update.

Run all four repository verification commands before committing tracked changes.
No production behavior is changed. Verify the private artifact's render dimensions,
blank defaults, local-only resources, and answer export/import on invented inputs.
The source-review handoff leaves the one active phase `AWAITING_HUMAN_REVIEW`.
