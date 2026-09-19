# Remaining Merchant Seed Blind Repeat-Reading Report

**Status:** AWAITING_HUMAN_REVIEW. Prepared on 2026-09-19.

**Authority:** The user's “proceed” approves the completed v2 comparison's
recommendation to repeat-read the remaining 13 single-read training cases. The
[design](../superpowers/specs/2026-09-19-merchant-remaining-blind-review-design.md)
and charter allowance were committed at `b66c7e7` before private preparation.

## Prepared review

The local worksheet contains exactly **13 cases: ten digital and three OCR**.
Selection uses the existing v2 review-depth mapping. It is independently checked
against the complement of the prior 11-case review, with zero overlap. All 13
selected v1/v2 reference lines are byte-identical, and all cases remain in their
original training documents and pages. No prediction or saved-score file is read.

Five existing full-page images are embedded byte for byte. The original
transaction and merchant regions locate each target; they remain editable and
are not asserted correct. All answer, description and note fields start blank,
all statuses are unreviewed, and all confirmations are false. The packet contains
only page resources and target-locator fields. Previous answers, extracted
answers, score categories, original case identities and the private mapping are
absent from the HTML data.

The existing local form retains zoom, region editing, uncertainty notes,
confirmation and partial-draft save/load. Its only script changes are the answer
version and exported filename; its template changes only the displayed case
count. It exports **`merchant-remaining-blind-review-answers.json`** and rejects
all earlier seed, blind-review and adjudication answer versions.

The private worksheet is
`artifacts/merchant-remaining-blind-review-v1/review.html`. It embeds the source
images and requires no network service. Links to broader PDF context use the
existing local workspace copies. The user should read each marked transaction
afresh, confirm each case, save the answers, and return that JSON file. Drafts
can be saved and reloaded; unsaved answers remain in the browser tab.

## Verification

- Separate preparation and packet checks agree on the 13-case selection, seed
  order, ten/three mode counts, zero overlap, unchanged reference lines and all
  original target-region sets.
- All five embedded images match the existing bytes and dimensions. All five
  source PDF identities match the selected documents; local PDF links resolve.
  No new rendering, recognition or source-text extraction occurs.
- All 13 blank drafts round-trip through export/import. Three prior answer-file
  versions are rejected even when supplied with matching target metadata.
- Ten invented-input form tests pass. The two new answer-identity tests fail
  against the unchanged earlier form and pass after its identity adaptation;
  the eight existing form checks pass throughout.
- Checks confirm the packet's allowed fields, exact template/script assembly,
  all referenced controls, empty answer controls, local resources and the
  connection-blocking content security policy.
- Preparation preserves 19 inputs, including the reused sources; packet
  verification preserves 22 inputs, with overlap between these sets. Existing
  references, mappings and form assets remain unchanged.
- Private Python formatting, lint and strict mypy pass. JavaScript syntax checks
  and the ten form tests pass. Required repository checks pass: Ruff formatting
  (195 files), Ruff lint, mypy (48 source files), and **3,766 tests in 100.43
  seconds**. Tracked production code is unchanged throughout this task.

Browser interactions have not been exercised in a real browser in this
environment. The HTML embeds its source-page images and can be opened in a
browser; broader PDF links depend on the existing local source copies.

Only aggregate documentation is tracked. Source contents, private identities,
regions, mappings and eventual answers stay under ignored local paths. There
is no private-corpus acceptance claim, production change, merge or push.

## Pending measurement

**Agreement, changed-reference count, uncertainty count, issue counts and
hypothesis are NOT MEASURED.** Zero human answers have been submitted for this
review. Preparing a valid worksheet does not support or falsify the hypothesis.

After the user submits the fixed 13 answers, preserve them separately, validate
them with the existing contract, and measure repeat consistency against the
first readings. Use unchanged NFC/whitespace equality and region multiset
comparison, with the fixed denominator and digital/OCR slices from the design.
Report disagreements and uncertainty without selecting a preferred answer.

Both reference versions, review-depth metadata and the saved **17/24 v2 score**
remain unchanged. This is a same-reviewer repeatability measurement conditional
on prior target marks, not independent semantic certification. Its selection
complements the earlier disagreement-selected audit; it is not a random corpus
sample or a held-out benchmark.

The sole active phase is paused at **AWAITING_HUMAN_REVIEW**. The next allowed
step is to receive and measure these answers, then STOP. No adjudication,
reference update, prediction rescoring, new extraction, sample expansion,
held-out access, accepted-gold promotion or production integration is authorized.
