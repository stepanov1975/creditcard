# Merchant Blind Repeat-Transcription Handoff

**Status:** AWAITING_HUMAN_REVIEW — the consistency measurement is pending.

**Authority:** The user's “proceed” on 2026-09-13 approved the preceding
recommendation for this fixed review. The
[design](../superpowers/specs/2026-09-13-merchant-blind-review-design.md) and
charter allowance were committed at `c149fcd` before private preparation.

## Prepared review

The local worksheet contains exactly the **11 nonmatching merchant cases** from
the completed merchant-region alignment comparison: **six digital and five OCR
cases**. Five existing full-page source images are reused without rendering or
recognition. Original transaction and merchant regions identify the targets;
the reviewer may adjust them and flag boundary, ownership, or legibility issues.

All transcription, description, and note fields start blank. Statuses are
unreviewed and confirmations are false. Previous answers, model outputs, scores,
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

## Verification

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
Repository verification for this task passed: Ruff format (195 files), Ruff
lint, mypy (48 source files), and **3,766 tests in 101.29 seconds**. No tracked
production behavior changed. These checks are not private-corpus acceptance;
no production verification, merge, or push was performed.

Interactive browser behavior has not been exercised in a real browser in this
environment. The worksheet was queued in the Codex file panel; opening a remote
workspace `file:` URL directly in the local browser is unsupported. The HTML
contains its source-page images and can be opened locally in a browser.

## Pending measurement

**Zero second-pass cases have been submitted.** Exact repeat agreement, changed
transcription count, ambiguity, ownership/boundary issue counts, and the hypothesis
result are all **NOT MEASURED**. Preparation is a handoff inside the authorized
measurement, not its completion and not evidence of improved extraction.

After the human answers arrive, preserve them separately and compare against
the original references with the unchanged NFC/whitespace rule. Report all 11
cases, including unresolved or missing answers. Do not promote changed text into
the reference or tune an extractor against the new submission.

This targeted same-reviewer repeat reading, with previous region marks visible,
measures consistency conditional on those targets. It does not certify reference
correctness, independent reviewer agreement, or dataset-wide label quality.
The active phase remains paused for these answers; no support task, expansion,
label replacement, validation/test access, or production integration is active.
