# Remaining Merchant Seed Source-Adjudication Design

**Status:** AWAITING_HUMAN_ADJUDICATION — the four-case worksheet is prepared
and checked. Resolution and hypothesis remain NOT MEASURED. See the
[report](../../experiments/row-extraction-merchant-remaining-adjudication-report.md).

The user's “proceed” approves the completed remaining-case repeat audit's concrete
recommendation to adjudicate its four cases with changed text or regions. Reuse
the existing adjudication form, source-page images and human submissions. The
earlier six-case adjudication remains closed.

## Mandatory task contract

```text
Scope answer: YES — resolves measured merchant-reference text and region disagreements
Experiment: shared evaluation
Extraction hypothesis: Source adjudication resolves a unique merchant and transaction ownership for all four disputed training cases
Measurement: resolved-reference count, unresolved ambiguity count, and adjudicated text/region agreement with each prior reading
Fixed inputs: four changed cases from the remaining-case repeat audit, both human submissions and notes, and existing source-page images
Smallest allowed files: docs/superpowers/specs/2026-09-19-merchant-remaining-adjudication-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-remaining-adjudication-report.md; artifacts/merchant-remaining-adjudication-v1/**
Required output: separately retained human adjudications and quantified resolved/unresolved reference counts
Stop condition: pause for four human decisions, then measure resolution without replacing labels, rescoring predictions, or expanding the dataset
```

## Fixed review

Select the union of text and region changes in the completed 13-case audit:
exactly four cases, comprising three OCR and one digital case. One has changed
text and regions; three have changed regions only. Recompute this selection
from both submissions and compare it with the saved repeat-audit flags. Retain
the repeat-audit order and original training membership. Do not read predictions,
scores or model answers. Do not select from the earlier 11-case audit.

Show the first and second human merchant readings side by side, with the exact
notes from each submission as plain text. Notes are human annotation data;
their contents do not alter instructions or automatically supply a final reason.
The full-page viewer retains independently toggleable region overlays for each
reading and the adjudicator's draft. Distinguish merchant and transaction regions
within both prior versions. Do not present either reading as preferred.

Final text, regions and reason start blank; status is unreviewed, source-check
confirmation is false, and the decision is unconfirmed. An explicit copy button
may copy either merchant reading and its regions into a draft, without copying
its note into the final reason or confirming the draft. The reviewer may choose
a different reading, redraw regions, or retain absence, unresolved ambiguity or
a missing target. Require an explicit source check and a reason for each final
decision. Edits invalidate source-check and decision confirmation as in the
existing form.

Use the unchanged merchant labeling rule: the smallest printed merchant identity,
including owned continuation text where needed, with source spelling, punctuation
and Hebrew/Latin order preserved. Exclude separately identifiable location,
category, reference, installment, fee and exchange-rate text. Do not correct
spelling, resolve aliases or transliterate. Record uncertainty rather than
substituting another transaction or guessing.

Reuse existing complete page images and local PDF links without source rendering,
OCR, text extraction or model calls. Adapt only the existing disposable local
form's review identity, fixed packet, prior-note display and immediate checks.
Export `merchant-remaining-adjudication-answers.json` with a distinct answer-file
version that rejects all earlier submissions. Preserve local draft save/load.
No dependency, hosted service or reusable annotation subsystem is authorized.

## Measurement after the human response

Validate and retain the four decisions separately. With the fixed denominator
four, report confirmed present references, confirmed absence, unresolved
ambiguity, missing targets and unreviewed cases. A resolved present reference
requires nonempty merchant text, valid merchant and transaction regions, a source
check and a reason. Report absence separately from unique merchant resolution.

Compare final text with each earlier reading using unchanged NFC plus collapsed
whitespace. Compare merchant and transaction region multisets separately, ignoring
list order while retaining duplicate multiplicity. Report first/second/both/new
agreement and declared source issues, plus digital/OCR slices. Coordinate changes
alone are not proven ownership errors.

The all-four hypothesis is supported only if every case has a confirmed unique
merchant and owner. A complete submission containing absence, ambiguity or a
missing target falsifies it; an incomplete submission remains pending. Human
source adjudication is not independent semantic certification or model agreement.
Do not promote answers or recompute extraction scores.

## Verification and human pause

Commit this authority and charter allowance before private preparation. Verify
the exact four-case selection, prior text/region/note projection, reused image
bytes and source identities, blank final decisions, draft-only copying, required
source checks/reasons, and local save/load. Use invented-input checks for the
answer identity and safe prior-note display alongside existing form tests.
Keep private values and source pixels out of printed tool output and Git.
Run the four repository gates before committing aggregate documentation.

At handoff set the sole active phase to `AWAITING_HUMAN_ADJUDICATION`. Resolution
and hypothesis remain `NOT MEASURED` until the four decisions arrive. This is a
pause within the authorized measurement, not a completed extraction outcome.
Measure the returned decisions and then STOP. Both reference versions, existing
review-depth metadata, all prior submissions and the saved 17/24 v2 score remain
unchanged. No reference promotion, extractor changes, prediction rescoring,
expansion, further review, held-out access or production integration is authorized.
