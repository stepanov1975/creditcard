# Visual-Gold v2 100-Row Pilot Protocol

**Status:** Binding protocol for the approved 100-row training pilot.

**Date:** 2026-08-01

**Authority:** The
[visual-gold v2 candidate design](../superpowers/specs/2026-08-01-visual-gold-v2-candidate-design.md),
the
[row-extraction experiment charter](../superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md),
and the [program status](row-extraction-program-status.md).

## Purpose and boundary

This protocol measures whether two independent, crop-first visual reviews can reconstruct stable
extraction supervision for a fixed 100-row sample from the frozen 2,503-row training split. Current
gold remains authoritative. Learned visual reviewers produce only a parallel candidate; they do
not overwrite current gold, change any extractor, rescore an experiment, or authorize promotion.

The inputs are the frozen training rows, their existing immutable row crops, positioned atoms, row
geometry, role-free column boundaries, reciprocal adjacency, and bounded source-page renderings.
Validation and held-out rows remain unopened. Current gold, accepted parser values, semantic column
roles, source filenames, and every experiment prediction remain hidden from Reviewers A and B.

## Deterministic pilot selection

The selector version is `visual-gold-v2-pilot-v1`. It accepts all and only the 2,503 unique rows in
the frozen training split. Duplicate identities, nontraining rows, an incorrect population count,
empty atoms, or an atom with an unknown source fail selection before reviewer material is written.

A row is OCR-source when at least one frozen atom has `source="ocr"`. Otherwise every atom must have
the digital source. The selected population must contain exactly 10 OCR-source rows and 90
digital-source rows.

For each row, compute the stable order key as the SHA-256 digest of the UTF-8 encoding of
`version + "\\0" + document_id + "\\0" + row_id`. Sort first by this digest and then by
`(document_id, row_id)` as the collision tie-breaker.

Walk the stable order once for each stage below, selecting an otherwise-unselected eligible row
only when doing so keeps the document at no more than two selected rows. Non-OCR stages select
digital-source rows so that the exact source quota is preserved.

| Stage | Required rows |
| --- | ---: |
| structural | 1 |
| ambiguous | 1 |
| OCR primary | 10 |
| 1–3-atom continuation | 15 |
| 4–9-atom continuation | 10 |
| 4–9-atom digital primary | 14 |
| 10+-atom continuation | 23 |
| 10+-atom digital primary | 26 |

These stages yield exactly 50 hidden-baseline primary rows, 48 continuation rows, one structural
row, and one ambiguous row. Baseline row type is used only by this selector and is never serialized
into reviewer material. If any stage cannot meet its exact quota under the two-rows-per-document
cap, selection fails closed. The selector returns the 100 chosen rows in final stable-key order.

## Private artifact layout

All packets, images, contexts, review decisions, labels, disagreements, and derived financial
content stay under the existing ignored private row-experiment root with these exact relative
filenames:

```text
visual-gold-v2/
  pilot-v1/
    packets.jsonl
    crops/
    page-contexts/
    reviewer-a.jsonl
    reviewer-b.jsonl
    comparison.jsonl
    reviewer-c.jsonl
    adjudicated-gold.jsonl
    current-gold-defects.jsonl
```

The materializer must require a new or empty ignored `pilot-v1` directory. It writes the locked
packet stream once, renders the exact row crop and bounded page context, and must not accept or read
a gold or prediction path. Reviewer material may include opaque row identity, atoms and their
source/confidence/bounding boxes, fixed row geometry, role-free column boundaries, reciprocal
adjacency, and crop/context paths and digests. It must omit baseline type, semantic band roles,
current gold, accepted values, parser output, predictions, and source filenames.

## Blind Reviewer A and Reviewer B prompt

Reviewer A and Reviewer B run in separate clean contexts and receive the same prompt, substituting
only the reviewer name:

> You are Reviewer A (or Reviewer B), performing an independent blind visual review. Use only the
> supplied protocol, sanitized `packets.jsonl`, exact row crops, and pre-rendered page contexts. Do
> not search the repository for or inspect current gold, accepted parser values, baseline row type,
> semantic column roles, experiment predictions, source filenames, or the other reviewer's work.
> For each packet in locked order, inspect the exact crop at original resolution first. Open its
> page context only when crop evidence is insufficient to determine column meaning, currency, year,
> ownership, or contamination, and record that use as a boolean. Choose exactly one row type from
> `primary_transaction`, `continuation`, `structural`, or `ambiguous`; record every uniquely visible
> field in the existing closed field-role vocabulary with its typed canonical value and exact
> same-row atom-ID tuple, bounded source region, or both. If the allowed evidence still supports
> multiple readings, label the row `ambiguous` and fieldless. Missing or unreadable source evidence
> is a review failure, not an ambiguous label. Validate every decision before continuing.

Each reviewer processes ten fixed batches of ten rows in packet order. Each batch is validated and
frozen before proceeding. The combined `reviewer-a.jsonl` or `reviewer-b.jsonl` must contain exactly
one valid decision for each of the 100 selected identities, in packet order. Reviewer A is frozen
before Reviewer B begins, and Reviewer B receives no A output, summary, path contents, or decision.

## Canonicalization

Canonical text follows natural human reading order. Hebrew and other RTL text is not serialized by
increasing X coordinate. Mixed-direction numeric and Latin spans retain their visible internal
order. A visually continuous word or number is not given artificial spaces solely because frozen
atoms split it. Reviewers may not infer values from filenames, totals, reconciliation, current
gold, parser output, predictions, or another row.

## Pre-adjudication comparison and gates

Freeze both review streams before comparison. Require exact identity coverage and 100% annotation
validity for both streams. Validation fails closed on an unknown, missing, or duplicate identity;
invalid geometry or canonical value; evidence outside the same row or fixed crop; invalid ambiguity
state; or continuation ownership that does not follow the reciprocal frozen predecessor relation.

All agreement is computed before adjudication using `Decimal` arithmetic:

- **Row-type agreement:** the numerator is rows where A and B choose the same row type. The
  denominator is exactly 100. The inclusive gate is `Decimal("0.95")`.
- **Field exact agreement:** for each row, the eligible field slots are the union of roles asserted
  by A or B. A slot matches only when both reviewers assert the role and its typed canonical values
  are exactly equal. Missing-versus-present is a disagreement, and absent/absent roles add no slot.
  The inclusive gate is `Decimal("0.90")`.
- **Evidence-support agreement:** the denominator is the field roles present in both reviews.
  Exact atom-ID tuple agreement and exact serialized source-region agreement are measured and
  reported separately. These rates are diagnostic and cannot override a semantic or validity gate.

The private `comparison.jsonl` contains only opaque disagreement identities and categories for row
type, ambiguity, field presence, canonical value, atom support, or source region; it contains no A/B
values. The aggregate summary contains only counts, `Decimal` rates, booleans, and gate outcomes.
The pilot passes only when validity is 100%, row-type agreement meets its threshold, and field exact
agreement meets its threshold.

## Reviewer C disagreement-only prompt

Reviewer C starts in a fresh context only after every pre-adjudication gate passes. Exact A/B
agreements are copied without further review. For disagreement rows only, use this prompt:

> You are Reviewer C, independently adjudicating only frozen disagreements. Use the supplied
> protocol, sanitized source packet, exact crop, bounded page context when necessary, and the exact
> semantic/evidence differences between A and B. Do not inspect current gold, accepted parser
> values, experiment predictions, source filenames, or reviewer identities as quality signals. Do
> not default to A or B. Determine the uniquely source-supported label and evidence. If no unique
> answer exists, record `ambiguous` and fieldless. Missing or unreadable evidence stops the batch.
> Validate the decision before continuing.

`reviewer-c.jsonl` contains one decision for every and only disagreement identity. Merge exact A/B
agreements and C decisions in locked packet order into `adjudicated-gold.jsonl`; require exactly 100
valid records and complete disagreement coverage. Freeze the candidate before opening current gold.

## Failure and stop behavior

Selection, materialization, or review stops immediately on missing/unreadable evidence, a quota or
document-cap failure, leakage into reviewer material, an output outside the ignored private tree,
invalid or incomplete labels, identity/geometry/ownership/evidence failure, or any record count
other than 100. No later support task may be added to rescue a missing measurement.

If validity is below 100%, row-type agreement is below 95%, or field exact agreement is below 90%,
write only the privacy-safe aggregate pilot result, set program status to `STOP`, and end before
adjudication or current-gold comparison. Do not change labels, thresholds, prompts, model family,
canonicalization, comparison logic, or launch a replacement pilot to manufacture a pass. A protocol
revision requires a new user-approved task and a fresh predeclared pilot.

If every gate passes, adjudicate only disagreements, freeze the 100-row parallel candidate, and
only then compare it with matching current training gold. Record private defects only in
`current-gold-defects.jsonl` and publish aggregate predeclared counts for row type, field presence,
RTL/mixed-direction order, segmentation, other canonical-value differences, evidence support, and
ambiguity. Current gold remains authoritative, no experiment is rescored, and the remaining 2,403
training rows are not reviewed under this pilot.

## Required Metric-or-Stop report

At pilot completion, report exactly:

```text
Scope: YES — measured blind visual reconstruction of extraction supervision on the fixed training pilot
Experiment: shared evaluation
Measurement: row-type agreement, field exact agreement, evidence-support agreement, validity, ambiguity, and annotation-defect categories
Result: <aggregate gate result, rates, and defect counts from the committed report>
Next extraction task: <write the remaining-2,403-row plan, or STOP>
```

Tracked status and reports contain aggregate counts and rates only. They must contain no private row
or document identity, source name, filename, atom text, canonical value, transaction value, financial
data, image, crop, label, reviewer decision, prediction, or private artifact digest.
