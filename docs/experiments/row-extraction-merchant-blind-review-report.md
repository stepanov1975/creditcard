# Merchant Blind Repeat-Transcription Audit

**Status:** COMPLETE — STOP.

**Authority:** The user's “proceed” on 2026-09-13 approved the preceding
recommendation for this fixed review. The
[design](../superpowers/specs/2026-09-13-merchant-blind-review-design.md) and
charter allowance were committed at `c149fcd` before private preparation.

## Result

The user submitted all **11 confirmed second readings**. **Seven repeat the
original merchant text exactly under NFC plus collapsed-whitespace equality**;
**four differ**. Repeat agreement is **7/11 (63.6%)**. The predeclared hypothesis
that at least one reference is inconsistent or uncertain is **supported** by the
four changed transcriptions.

All 11 second readings are marked present with no reported source issue. There
are zero absent, ambiguous, missing, or unreviewed cases and no explanatory notes.
Four different present readings establish inconsistent supervision; they do not
prove that four original labels were wrong or that the second reading is correct.

| Fixed slice | Cases | Exact repeats | Changed text | Merchant regions changed | Transaction regions changed |
| --- | ---: | ---: | ---: | ---: | ---: |
| Digital | 6 | 5/6 (83.3%) | 1 | 0 | 0 |
| OCR | 5 | 2/5 (40.0%) | 3 | 5 | 5 |
| Total | 11 | 7/11 (63.6%) | 4 | 5 | 5 |

The five changed merchant-region sets and five changed transaction-region sets
belong to the same five OCR cases. Region comparison ignores rectangle list
order and retains multiplicity. These are annotation changes, not independently
verified boundary or ownership errors; the reviewer did not report such issues.

Text and region changes overlap in three cases. Their union is **six cases**:
three with changed text and regions, two with changed regions only, and one
with changed text only. No automatic adjudication or label replacement occurred.
The preserved extraction score remains **13/24** against the original references;
no predictions were rescored against the second submission.

## Prepared review

The local worksheet contains exactly the **11 nonmatching merchant cases** from
the completed merchant-region alignment comparison: **six digital and five OCR
cases**. Five existing full-page source images are reused without rendering or
recognition. Original transaction and merchant regions identify the targets;
the reviewer may adjust them and flag boundary, ownership, or legibility issues.

At handoff, all transcription, description, and note fields started blank. Statuses were
unreviewed and confirmations were false. Previous answers, model outputs, scores,
and mismatch categories are absent from the packet. Fresh review case numbers
map privately to the original cases. The original reference and all extraction
artifacts remain unchanged, with the preserved score at **13/24 exact**.

The worksheet reuses the original local review form's zoom, region marking,
confirmation, and draft save/load. It exports `merchant-blind-review-answers.json`.
A reported issue, ambiguity, or missing target requires an explanatory note.
It rejects original seed answer files, preventing accidental display of the
first-pass answers. It has no network resources or network submission.

Private materials remain in ignored `artifacts/merchant-blind-review-v1/`;
the worksheet links only to the existing local source copies for broader context.
No private document content, source identity, geometry, answer, or output is
recorded in Git.

## Handoff verification

- All 24 preserved candidate exact/nonexact outcomes reproduce; the 11-case
  selection agrees with the saved mismatch set.
- All 11 target-region sets agree with the original annotations. Five embedded
  page images match the original bytes and dimensions, and all local source
  links resolve. All five source copies match their selected identities.
- All 11 review entries are blank and unconfirmed. The packet contains only
  whitelisted page and target-location fields, with no answer or prediction field.
- Eight invented-input form tests pass. Six exposed the expected missing
  repeat-review behavior before adaptation; two preserved checks already passed.
  They cover blank defaults, independent region editing, partial-draft round
  trips, incompatible original answer files, explicit uncertainty notes, and
  invalid confirmed records.
- Local packet checks verify blank-draft round trips, control IDs, resource
  locality, and the connection-blocking content security policy. JavaScript
  syntax, Python formatting/lint, and strict Python type checks pass.
- All 16 inputs read or identity-checked during preparation remain unchanged.

A separate read-only review found no actionable packet or interface defects.
Repository verification before handoff passed: Ruff format (195 files), Ruff
lint, mypy (48 source files), and **3,766 tests in 101.29 seconds**. No tracked
production behavior changed. These checks are not private-corpus acceptance;
no production verification, merge, or push was performed.

Interactive browser behavior has not been exercised in a real browser in this
environment. The worksheet was queued in the Codex file panel; opening a remote
workspace `file:` URL directly in the local browser is unsupported. The HTML
contains its source-page images and can be opened locally in a browser.

## Submitted-answer measurement and verification

The uploaded bytes are retained unchanged in the ignored review directory. The
existing worksheet answer validator accepts all 11 records against the fixed
targets, including identities, statuses, confirmations, and region geometry.
The original answers, references, target mapping, worksheet, saved alignment,
scores, and assembly outputs remain unchanged across the measurement: ten
protected inputs. No source page, OCR output, or new prediction is generated.

Nineteen focused invented-input tests failed at the unimplemented measurement
helper and then passed. They verify NFC/whitespace-only equality, preserved word
order/punctuation/case differences, draft exclusion, non-present categories,
incomplete-review handling, and the predeclared hypothesis. All five private
Python files pass formatting, lint, and strict type checks.

An independent normalization and region-multiset check agrees with all **11 text
comparisons and 22 region comparisons**, the digital/OCR exact counts, and the
six-case union. It also verifies that the retained second submission matches the
uploaded bytes. The required repository gates pass: Ruff format (195 files),
Ruff lint, mypy (48 source files), and **3,766 tests in 99.43 seconds**. No tracked
production behavior changed; these checks are not private-corpus acceptance.

A separate read-only code review found no actionable measurement defects and
confirmed that region changes are kept separate from reported ownership issues.

Private per-case results and aggregate measurement files remain under ignored
`artifacts/merchant-blind-review-v1/`. Only aggregate documentation is tracked.

## Golden-dataset implication and next recommendation

This targeted same-reviewer repeat reading, with previous region marks visible,
measures consistency conditional on those targets. The 11 cases were selected
because extraction disagreed with the original answer; this is not an unbiased
estimate of reference accuracy or dataset-wide label quality. Seven repeating
readings are not independent gold certification, and changed text must not be
replaced automatically by either another human reading or a model answer.

The recommended next task is **source adjudication of the six cases with changed
text or regions**, showing both human transcriptions and both region annotations
alongside the existing source, with model outputs hidden. Resolve the intended
transaction, merchant span, and text or retain explicit uncertainty. Record any
adjudicated result separately before considering a reviewed label revision or
dataset expansion. This recommendation has not been executed; no new packet or
adjudicated label has been created.

The authorized repeatability measurement is complete. **STOP**. No adjudication,
label replacement, extraction tuning, expansion, validation/test access, or
production integration is authorized by this completed task.

```text
Scope: YES — measures reference inconsistency among merchant extraction disagreements
Experiment: shared evaluation
Measurement: repeat-transcription exact agreement, changed-reference count, ambiguity count, and ownership/boundary issue count
Result: 7/11 exact repeats; four changed transcriptions; zero reported ambiguities or source issues; five cases with changed regions; reference-inconsistency hypothesis supported
Next extraction task: STOP
```
