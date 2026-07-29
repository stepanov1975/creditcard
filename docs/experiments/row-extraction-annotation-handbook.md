# Transaction-Row Annotation Handbook

**Handbook version:** `row-extraction-annotations-v2`

**Status:** Authoritative annotation semantics for the four fixed-row extraction
experiments.

## Authority and boundary

This handbook defines how a reviewer turns one frozen row and its source image into a
`GoldRow` and, when the printing is legible enough for OCR scoring, optional
`OcrReference` records. It is subordinate to the approved transaction-row experiment
charter and applies to every train, validation, and locked-test label.

The accepted parser output is a proposal, not gold. A reviewer may use it to navigate the
source, but must decide the row type, fields, and source support from the frozen source row.
The accepted `baseline_type` is never an annotation criterion and disagreements with it are
valid review outcomes.

All examples below are invented. They illustrate semantics only and are not lookup values,
templates, or extraction rules.

## Unit of review and identity

The unit is one exact frozen row. Its opaque `document_id`, `row_id`, page, bounding box,
and adjacency are fixed before annotation. Reviewers do not move, split, merge, add, or
remove rows.

Every frozen `(document_id, row_id)` receives exactly one `GoldRow` with the same identity.
Duplicate, missing, or unknown identities invalidate the annotation set. Values such as
source filenames, document ordinals, merchants, dates, amounts, and totals must never be
used to create or interpret an identity.

## Row-type decision

Choose exactly one closed row type.

### Primary transaction

A primary transaction row starts a transaction and has unique reviewed values for its
billed amount, billing currency, and charge/credit kind. Those three fields are required;
every other field is recorded only when present and uniquely supported.

Synthetic example: a row prints `2026-04-03`, `SYNTHETIC BOOKSHOP`, `USD`, and `12.34`.
The annotation is primary, with the printed date and description plus the required billed
amount, currency, and `charge` kind. The example values have no predictive meaning.

### Continuation

A continuation row prints evidence owned by the exact fixed predecessor rather than
starting a new transaction. Its `previous_row_id` must identify the preceding fixed row in
the same opaque document, the predecessor must point back with `next_row_id`, and the
predecessor annotation must itself have transaction ownership (primary or continuation).
Following predecessor ownership through any continuation chain must be acyclic and must
terminate at a primary transaction in that same frozen document. A self-loop or a chain
consisting only of continuations is invalid ownership.

A continuation may carry any field role printed on that row. It is not limited to merchant
text. For example, one synthetic continuation may print `SYNTHETIC CONTINUATION`, an
original `EUR 10.20`, a conversion date `2026-04-05`, installment `2/6`, and FX rate
`1.2098`. Each uniquely supported field is annotated on the continuation; ownership by the
fixed predecessor is implied by the continuation row type and validated adjacency.

A continuation must contain at least one uniquely supported field. It must not be used to
repair an unrelated row or to attach evidence across a nonreciprocal or cross-document
boundary.

### Structural or nontransaction

A structural row is a header, separator, printed total, or other nontransaction row. It has
no transaction fields. A printed value on a structural row does not become a transaction
amount merely because it resembles money.

Synthetic example: `SYNTHETIC SECTION TOTAL USD 99.99` remains structural and fieldless.
The printed total is not copied into a transaction label.

### Ambiguous

Use ambiguous when the source does not uniquely determine a row type or any applicable
field value. Set both `row_type=ambiguous` and `ambiguous=true`, and provide no unique
fields. Conversely, primary, continuation, and structural rows use `ambiguous=false`.

Ambiguity is not a convenient label for hard OCR, and it must not be coerced into a primary
transaction for training coverage. Under version 2, field-level uncertainty makes the row
explicitly ambiguous and fieldless; the contract does not retain selected clear fields from
the same uncertain row.

## Absent versus ambiguous

An **absent** field is not printed, not applicable, or not part of the transaction. Omit the
field from an otherwise unambiguous primary or continuation row. Absence does not mean an
empty string and does not create an `OcrReference`.

An **ambiguous** field has source evidence but no single defensible value or ownership. Mark
the row ambiguous under the rule above. Do not choose the accepted parser value, a balancing
value, or the most convenient training target.

Synthetic examples:

- A clear primary row without an installment prints no installment field: installment is
  absent.
- A blurred mark could be either `1/6` or `4/6`: the row is ambiguous; neither value is
  asserted.
- A description is clearly absent on a valid amount-only primary: description is absent,
  while the required billed fields remain annotated.

## Canonical field rules

Every field role occurs at most once in a row. Canonical values are typed independently of
accepted output and follow these rules:

- `transaction_date`, `posting_date`, and `conversion_date` are complete, context-free ISO
  dates such as synthetic `2026-04-03`. A short date requiring an invented year is invalid.
- `description` and `ancillary` are nonempty NFC text with normalized whitespace. Case and
  punctuation are preserved.
- `billed_amount`, `original_amount`, and `fx_rate` are finite base-10 `Decimal` values in
  plain canonical form. Binary floating point is never used. Nonfinite values and alternate
  spellings such as a redundant trailing zero are invalid canonical labels.
- `billing_currency` and `original_currency` are canonical supported currency codes, such
  as synthetic `USD` or `EUR`, not symbols or aliases.
- `kind` is exactly `charge` or `credit`. It uses the exact billed-amount support and agrees
  with the nonzero billed-amount sign: positive is charge and negative is credit.
- `installment` is canonical `current/total`, with both integers positive and current no
  greater than total.

Original amount and original currency are a pair: record both or neither. A primary row
always contains billed amount, billing currency, and kind. A continuation may contain any
uniquely printed field role, subject to the same typing and pairing rules.

## Source support and ownership

Each present `GoldField` cites at least one exact same-row support form: one or more unique
evidence atom IDs, or a bounded image `source_region`. Region-only support is required when
the printing is legible but the frozen digital/OCR stream missed it; omitting such a field
would hide exactly the recognition failures these experiments measure. Atom order follows
source order. An atom cannot support independent fields at the same time. The sole intentional
overlap is `kind`, which derives from and must cite exactly the same atom IDs and optional
source region as `billed_amount`.

When a reviewer records a `source_region`, it must be finite, nonempty, and wholly inside
the exact fixed row. If atom IDs are also recorded, the region must intersect every declared
atom. A field with neither atom IDs nor a source region is invalid.
Independent field regions must not overlap. The billed-amount/kind pair may share its
identical region. Evidence from another row is never copied into the current row label;
continuation ownership is expressed by the validated predecessor relationship.

Evidence identifies where the reviewer saw the field. Its extracted token text is not
automatically authoritative: a reviewer can correct an OCR substitution by inspecting the
source while keeping the exact supporting atom/region. Reconciliation and accepted totals
may reject a later prediction, but they never choose or repair an annotation.

## OCR reference eligibility

`OcrReference` is optional and exists only for CER/WER scoring. Create it by manually
transcribing a source region whose printing is sufficiently legible to support one exact
verbatim reading.

Each OCR reference:

- uses an existing frozen `(document_id, row_id)`;
- names a role already present in that row's reviewed fields;
- has a unique `(document_id, row_id, role, source_region)` identity;
- has a finite, nonempty region wholly inside the exact fixed row; and
- equals the field's declared source region when one exists, or otherwise intersects the
  geometry of at least one atom declared for that role; and
- preserves the reviewed source transcription without canonicalizing it into a date,
  amount, currency, installment, or merchant value.

The transcription is validated independently of the field's canonical value. For example,
an OCR reference may preserve visible spacing or glyphs that the canonical field normalizes.
Never synthesize an OCR reference from accepted OCR, a canonical field, a model prediction,
or surrounding context. If the region is illegible or has two defensible readings, omit the
reference; do not force a transcript.

## Review procedure

1. Open the exact fixed-row crop and, when necessary, the same bounded source-page context.
2. Ignore accepted output as an authority and choose the row type from source evidence.
3. Record every uniquely present field in the closed role vocabulary and omit truly absent
   fields.
4. Attach exact same-row atom IDs, a bounded source region, or both. Use region-only support
   for legible printing absent from the frozen atoms.
5. Apply the canonical type, pairing, ownership, and ambiguity rules above.
6. Add OCR references only for independently legible regions.
7. Run `validate_annotations` and correct every value-free identity or contract violation.

A predeclared document-disjoint sample is reviewed independently by two reviewers and then
adjudicated. Agreement is reported by row type and field role using privacy-safe aggregate
counts. Reviewers must not see locked-test experiment scores before adjudication is frozen.

## Error-analysis categories

After annotation is frozen, wrong or abstained predictions use the charter taxonomy: OCR
substitution/insertion/deletion/segmentation; crop truncation or neighboring-row
contamination; mixed-direction or Unicode order; word-box or column drift; row-type error;
continuation ownership; description boundary or typed-nondescription; date/year-context;
amount/separator/sign/kind/currency; optional-field ownership; calibration false acceptance;
correct abstention on ambiguous evidence; or annotation ambiguity/defect.

Categories may be clarified before locked-test access. They are not added after viewing
locked results to favor an experiment.

## Versioning

Any semantic change to row types, ambiguity, field ownership, canonical typing, or OCR
eligibility requires a new handbook version and revalidation of every affected label.
Changing gold-label semantics after locked-test access requires the charter amendment
procedure and explicit user approval.

Version 2 adds region-only gold support for legible printing absent from frozen atoms and
requires revalidation of every label and OCR reference created under version 1. No locked-test
labels or results existed when this correction was made.
