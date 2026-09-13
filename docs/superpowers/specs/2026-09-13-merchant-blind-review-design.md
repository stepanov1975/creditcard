# Merchant Blind Repeat-Transcription Design

**Status:** AWAITING_HUMAN_REVIEW — private packet prepared; human answers pending.

The user's “proceed” on 2026-09-13 approves the preceding recommendation for a
blind second transcription of the 11 merchant disagreements. This is one bounded
reference-consistency measurement. It reuses the existing private seed worksheet,
source-page images, and source-region annotations.

## Mandatory task contract

```text
Scope answer: YES — measures reference inconsistency among merchant extraction disagreements
Experiment: shared evaluation
Extraction hypothesis: At least one of the 11 disagreements has an unstable or ambiguous human transcription
Measurement: repeat-transcription exact agreement, changed-reference count, ambiguity count, and ownership/boundary issue count
Fixed inputs: 11 nonmatching cases from the completed 24-case training comparison, original references, marked regions, and existing review pages
Smallest allowed files: docs/superpowers/specs/2026-09-13-merchant-blind-review-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-blind-review-report.md; artifacts/merchant-blind-review-v1/**
Required output: measured repeat-transcription agreement and quantified reference uncertainty after human answers
Stop condition: pause for the 11 human answers, then report consistency without replacing labels, tuning extraction, or expanding the dataset
```

## Fixed selection and review

Select exactly the 11 nonexact cases in the saved merchant-region alignment
comparison: six digital and five OCR cases. Check selection against all 24 saved
candidate outcomes and the preserved references; do not recompute predictions,
change alignment, or select additional cases. Use the existing full-page review
images, with original transaction and merchant regions marking each target.
Show no previous transcription, extracted answer, mismatch category, or score.
Use new worksheet case numbers and a private mapping to the original cases.

Adapt the existing disposable local HTML worksheet, retaining source zoom,
region editing, confirmation, and answer save/load. Every text field is blank,
every status is unreviewed, and every confirmation is false initially. Regions
are target locators from the first pass, not an asserted correct boundary; the
reviewer can correct them and explain ownership, boundary, or legibility issues.
The full existing source PDF remains available locally for context. No new
rendering, OCR, source-text extraction, model proposal, dependency, hosted service,
or reusable review application is needed.

Use the original labeling rule: the minimal source-supported printed merchant
identity, including owned continuation text when necessary. Preserve spelling,
Hebrew/Latin reading order, and punctuation. Exclude separately identifiable
location, category, reference, installment, fee, and exchange-rate text. Do not
normalize identities, correct spelling, or transliterate. Record uncertainty
explicitly instead of guessing. A missing target or changed ownership must be
reported, not replaced by a different transaction.

## Measurement after the human response

Preserve both submissions separately. Compare confirmed second-pass merchant
text to the original using the existing NFC plus collapsed-whitespace equality.
Report exact repeats, different present transcriptions, absent/ambiguous/missing
statuses, unreviewed cases, region-change counts, and explicit ownership/boundary
issues. Keep the fixed denominator of 11 and report the digital/OCR slices.
Changed text means inconsistent transcription, not a proven original-label error.

The hypothesis is supported if any confirmed case changes normalized text or
reports absence, ambiguity, missing ownership, or a boundary/ownership issue.
It is falsified only if all 11 are confirmed present with matching text and no
such issues. Incomplete responses leave the result pending. Do not substitute
model agreement for human adjudication or silently promote the second answer.
Any unresolved ambiguity is reported explicitly; label replacement and further
adjudication are outside this task.

This is a targeted, same-reviewer repeatability audit, conditional on previously
marked target regions. It cannot establish independent reviewer agreement,
unbiased reference accuracy, dataset-wide label-error prevalence, or validation
performance. The preserved 24-case extraction score remains 13/24 throughout.

## Verification and pause

Keep private sources, geometry, mappings, and answers under ignored local paths.
Only aggregate documentation is tracked. Verify the exact 11-case selection,
image reuse, blank defaults, resource locality, and answer export/import using
invented inputs. Run all four repository gates before committing tracked changes.

Commit this authority and its charter allowance before preparing the private
packet. At handoff leave this sole active phase `AWAITING_HUMAN_REVIEW` and all
agreement measurements `NOT MEASURED`. This is a pause inside the authorized
measurement, not a completed extraction result or authority for support work.
After the submitted answers are measured, report the Metric-or-Stop result and
stop. No label promotion, expansion, extraction tuning, validation/test access,
or production integration is authorized.
