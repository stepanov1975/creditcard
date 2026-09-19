# Remaining Merchant Seed Blind Repeat-Reading Design

**Status:** COMPLETE — STOP. All 13 confirmed readings were measured: 12 exact
repeats, one changed OCR transcription, and four cases with changed regions.
The reference-inconsistency hypothesis is supported. See the
[report](../../experiments/row-extraction-merchant-remaining-blind-review-report.md).

The user's “proceed” approves the completed v2 reference comparison's concrete
recommendation: a blind second reading of the remaining 13 single-read training
cases. This completes repeat-reading coverage of the existing seed without
expanding it. The previous 11-case repeat audit and six adjudications stay closed.

## Mandatory task contract

```text
Scope answer: YES — measures reference inconsistency in merchant extraction evaluation
Experiment: shared evaluation
Extraction hypothesis: At least one of the 13 single-read cases changes transcription or reveals ambiguity, absence, missing ownership, or a boundary/ownership issue on repeat review
Measurement: repeat-transcription exact agreement, changed-reference count, uncertainty count, and ownership/boundary issue count
Fixed inputs: 13 single-read cases from the 24-case v2 training reference, prior regions, and existing source-page images
Smallest allowed files: docs/superpowers/specs/2026-09-19-merchant-remaining-blind-review-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-remaining-blind-review-report.md; artifacts/merchant-remaining-blind-review-v1/**
Required output: quantified repeat consistency after 13 human answers
Stop condition: pause for the fixed human review, then report agreement without replacing labels, tuning extraction, or expanding the sample
```

## Fixed selection and review

Select exactly the 13 `single_read` entries in the existing private v2 review-depth
mapping. Check that this set is the original 24-case seed minus the previous
11-case blind-review mapping, and that their v1/v2 reference lines are unchanged.
Keep seed order. The fixed cases comprise ten digital and three OCR references.
Do not read predictions, outputs, saved scores, or error categories for selection
or display. All cases retain their original training documents and pages.

Reuse the existing disposable blind-review worksheet, changing only its identity,
case count, and fixed packet preparation/checks. Give this review a distinct
answer-file version and filename so earlier submissions cannot load accidentally.
Use new opaque review IDs and keep the original case mapping outside the HTML.
Every text field starts blank, every status unreviewed, and every confirmation
false. The packet includes only page resources and target-locator fields.

Reuse the already rendered complete source-page images byte for byte. Original
merchant and transaction regions locate each target; they may be corrected and
are not asserted correct. Retain source zoom, editable regions, explicit
uncertainty statuses and notes, confirmation, and partial-draft save/load.
Local links provide broader PDF context. No rendering, OCR, source-text
extraction, model call, hosted service, dependency, or reusable review subsystem
is needed. Keep all source contents, identities, geometry and answers local.

Use the original merchant labeling rule: the smallest printed span identifying
the merchant, including owned continuation text when needed. Preserve spelling,
punctuation and Hebrew/Latin reading order. Exclude separately identifiable
location, category, reference, installment, fee and exchange-rate text. Do not
normalize merchant identities, correct spelling, transliterate or guess. Report
ambiguity or a missing target rather than substituting another transaction.

## Measurement after the human response

Retain the new submission separately and validate it with the existing worksheet
contract. Compare confirmed second-pass merchant text to the preserved first
reading, using unchanged NFC plus collapsed-whitespace equality. Keep the fixed
denominator of 13 and report digital/OCR slices. Report exact repeats, changed
present transcriptions, absent/ambiguous/missing/unreviewed counts, explicit
boundary/ownership issues, and merchant/transaction region changes. Region
comparisons ignore rectangle order while preserving multiplicity.

The hypothesis is supported by any confirmed changed normalized transcription,
absence, ambiguity, missing target, or a boundary/ownership/multiple-issue flag. It is
falsified only after all 13 are confirmed present with matching text and no such
issues. Incomplete responses remain pending. Region changes alone are recorded
annotation changes, not proven ownership errors. Do not use model agreement to
resolve a disagreement or replace any reference automatically.

This is a same-reviewer repeatability measurement conditional on earlier target
marks. It cannot establish independent reviewer agreement, semantic accuracy,
unbiased corpus label-error prevalence, or validation performance. Both reference
versions, review-depth metadata, and the saved 17/24 v2 score remain unchanged.
No adjudication, reference update, prediction rescoring or dataset promotion is
part of this task.

## Verification and human pause

Commit this design and charter allowance before preparing the private packet.
Check all 13 identities and target-region sets, blank defaults, exact image reuse,
source identity, absence of answer/prediction fields, local resources, and draft
export/import. Reuse the existing invented-input form tests, including rejection
of prior answer-file versions. Run all four repository gates before committing
aggregate documentation. Do not add production behavior.

At handoff leave this sole active phase `AWAITING_HUMAN_REVIEW`; agreement and
hypothesis remain `NOT MEASURED`. That is a pause within the authorized human
measurement, not a completed extraction result or authority for another task.
After the answers are measured, report the Metric-or-Stop result and stop. No
label promotion, further review/adjudication, sample expansion, extractor tuning,
validation/test access or production integration is authorized.
