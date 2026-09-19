# Merchant Source-Adjudication Design

**Status:** COMPLETE — STOP. On 2026-09-19, all six confirmed source adjudications
were submitted and measured. All six resolve a present merchant and match the
second reading's text and regions. The all-six-resolution hypothesis is supported;
the original reference remains unchanged. See the
[report](../../experiments/row-extraction-merchant-adjudication-report.md).

The user's “proceed” approves the preceding recommendation to adjudicate the six
cases with changed merchant text or source regions in the completed repeat-reading
audit. This is one bounded reference-resolution measurement using the existing
local form, source-page images, and both preserved human submissions.

## Mandatory task contract

```text
Scope answer: YES — resolves measured merchant-reference text and region disagreements
Experiment: shared evaluation
Extraction hypothesis: Source adjudication resolves a unique merchant and transaction ownership for all six disputed training cases
Measurement: resolved-reference count, unresolved ambiguity count, and adjudicated text/region agreement with each prior reading
Fixed inputs: six cases with text or region changes in the completed repeat-reading audit, both preserved human submissions, and existing source-page images
Smallest allowed files: docs/superpowers/specs/2026-09-13-merchant-adjudication-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-adjudication-report.md; artifacts/merchant-adjudication-v1/**
Required output: separately retained human adjudications and quantified resolved/unresolved reference counts
Stop condition: pause for six human decisions, then measure resolution without replacing original labels, rescoring predictions, or expanding the dataset
```

## Fixed inputs and review

Select exactly the union of four changed transcriptions and five changed region
sets: six cases, with three text-and-region changes, two region-only changes,
and one text-only change. This is five OCR cases and one digital case, all from
the existing training seed. Verify selection against the saved repeat audit and
both submissions; no new sampling or prediction access is needed.

Show the first and second human merchant readings side by side. The shared
full-page viewer provides independently toggleable overlays for their merchant
and transaction regions, plus the adjudicator's draft regions. Distinguish the
two prior versions without presenting either as preferred. No model answer,
extraction score, or automatically chosen final reading enters the packet.

Final text and region fields start blank, status is unreviewed, and confirmation
is false. Explicit buttons may copy either prior reading and its regions into
an editable draft. This never confirms a decision. The reviewer may instead
enter a third reading, redraw regions, or mark unresolved ambiguity, absence,
or a missing target. They must check the actual source, confirm that check, and
give a short reason for each decision. A copied reading remains a draft until
those requirements and the existing valid-region checks pass.

Use the existing merchant definition: the minimal printed merchant identity,
including owned continuation text when necessary. Preserve spelling, punctuation,
and Hebrew/Latin order. Exclude separately identifiable location, category,
reference, installment, fee, and exchange-rate material. Do not resolve aliases,
correct spelling, or transliterate. If the intended transaction, span, or reading
is not defensible, record uncertainty instead of guessing or substituting a
different transaction.

Reuse full-page images and local source links without rendering, OCR, source-text
extraction, or model calls. Retain local save/load and export a separate
`merchant-adjudication-answers.json`. The adaptation is disposable and confined
to the ignored artifact directory; no reusable annotation subsystem is authorized.

## Measurement after the human response

Retain submitted decisions separately; never overwrite either prior submission
or the original reference. With the fixed denominator six, report confirmed
present references, confirmed absence, unresolved ambiguity, missing targets,
and unreviewed cases. A resolved present reference requires nonempty merchant
text, valid merchant and transaction regions, a source-check confirmation, and
a reason. Absence is reported separately from unique merchant resolution.

Report text agreement with each prior version using the unchanged NFC plus
collapsed-whitespace equality. Compare merchant and transaction region multisets
separately with each prior version, ignoring list order and preserving duplicate
multiplicity. Count newly supplied text/regions and declared source issues without
equating coordinate changes with proven ownership errors.

The hypothesis is supported only if all six cases have confirmed unique merchant
readings and transaction ownership. A complete submission with any absent,
ambiguous, or missing target falsifies that all-six hypothesis; an incomplete
submission leaves it pending. Resolution is based on the human's source decision,
not independent semantic certification or model agreement.

## Verification and handoff

Commit the authority and charter allowance before private preparation. Verify
the six-case selection, exact prior-reading/region projection, original-image
bytes, blank defaults, unconfirmed draft copying, confirmation requirements,
and save/load on invented inputs. Keep private content out of tools' printed
output and Git. Run all four repository gates before committing tracked changes.

At handoff set the sole active phase to `AWAITING_HUMAN_ADJUDICATION`; resolution
and hypothesis remain `NOT MEASURED` until decisions arrive. Stop after that
measurement. No reference promotion, extractor change, prediction rescoring,
dataset expansion, validation/test access, or production integration is authorized.
