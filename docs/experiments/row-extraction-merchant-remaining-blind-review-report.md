# Remaining Merchant Seed Blind Repeat-Reading Report

**Status:** COMPLETE — STOP. Submitted readings measured on 2026-09-19.

**Authority:** The user's “proceed” approves the completed v2 comparison's
recommendation to repeat-read the remaining 13 single-read training cases. The
[design](../superpowers/specs/2026-09-19-merchant-remaining-blind-review-design.md)
and charter allowance were committed at `b66c7e7` before private preparation.

## Result

All **13 submitted readings are confirmed present** and pass the existing form
contract. **12/13 merchant texts repeat exactly (92.3%)** under unchanged NFC plus
collapsed-whitespace equality. **One OCR transcription differs** from the first
reading. The predeclared reference-inconsistency hypothesis is **supported**.

| Source mode | Cases | Exact repeats | Changed text | Merchant regions changed | Transaction regions changed |
| --- | ---: | ---: | ---: | ---: | ---: |
| Digital | 10 | 10/10 | 0 | 0 | 1 |
| OCR | 3 | 2/3 | 1 | 1 | 3 |
| Total | 13 | 12/13 | 1 | 1 | 4 |

Four cases have changed regions: all three OCR cases and one digital case. The
changed transcription belongs to this group, so the union of text or region
changes is **four cases**: one with changed text and regions and three with
changed regions only. Region comparisons ignore rectangle order and preserve
multiplicity. These are annotation changes, not independently proven ownership
or boundary errors.

There are **zero absent, ambiguous, missing or unreviewed cases**, and all 13
source-issue fields are `none`. Four cases include a human note: three OCR and
one digital. Those notes are retained privately as annotation data; no new issue
classification is inferred from them. A changed transcription establishes
inconsistency without proving which reading is correct.

The original and v2 references, the v2 review-depth snapshot and all earlier
submissions remain unchanged. The saved extraction score remains **17/24 against
v2**. No prediction is read or rescored and no second reading is promoted.

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
existing local workspace copies. At handoff the user was asked to read each
marked transaction afresh, confirm each case, save the answers, and return that
JSON file. Drafts can be saved and reloaded; unsaved answers remain in the browser tab.

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

## Submitted-answer measurement and verification

The upload is retained byte for byte as
`artifacts/merchant-remaining-blind-review-v1/merchant-remaining-blind-review-answers.json`.
The existing worksheet validator accepts all 13 submitted identities, statuses,
confirmations and region sets against the fixed targets. Selection still matches
the 13-case complement of the previous audit and the v2 single-read snapshot.
Every original merchant and target region is checked against the first human
submission; all 13 selected v1/v2 reference lines remain byte-identical.

The measurement reuses the existing equality, repeat-category, hypothesis and
aggregate-count helpers unchanged. Their **19 invented-input tests pass**;
the **ten existing form tests pass**. An independent computation using separately
expressed text normalization and Decimal coordinate multisets agrees with all
**13 text comparisons and 26 region comparisons**, the full aggregate fields
in all three slices, and the four-case union. The uploaded-byte equality check
also passes.

Measurement preserves 13 protected inputs, including both reference versions,
the review-depth snapshot, all prior answer submissions, and the review packet.
Independent verification preserves nine inputs, with overlap between those sets.
No source rendering, OCR, source-text extraction, model call, prediction access,
reference overwrite or review-depth update occurs. Private Python formatting,
lint and strict mypy checks pass. Required repository checks pass: Ruff formatting
(195 files), Ruff lint, mypy (48 source files), and **3,766 tests in 100.71 seconds**.
Tracked production code remains unchanged. These checks are not private-corpus
acceptance; no merge or push was performed.

## Golden-dataset implication and next recommendation

Together with the completed 11-case audit, **all 24 seed cases now have a second
human reading recorded**. They remain repeated readings by the same reviewer,
conditional on earlier target marks. Agreement is not independent semantic
certification; the sample is neither a random corpus sample nor a held-out
benchmark. The frozen v2 review-depth snapshot is preserved, while this review's
new evidence is recorded separately.

The next recommended task is **source adjudication of the four cases with changed
text or regions**, showing both human readings and region sets, their notes, and
the existing source page while keeping model outputs hidden. Resolve the intended
merchant text and transaction owner, or retain explicit uncertainty. Preserve
any decisions separately before considering another reference version.
This recommendation is not executed or authorized by the completed audit; no
adjudication worksheet or updated labels were created.

The fixed repeat-reading measurement is complete. **STOP**. No adjudication,
reference update, prediction rescoring, new extraction, expansion, held-out
access, accepted-gold promotion or production integration is active.

```text
Scope: YES — measures reference inconsistency in merchant extraction evaluation
Experiment: shared evaluation
Measurement: repeat-transcription exact agreement, changed-reference count, uncertainty count, and ownership/boundary issue count
Result: 12/13 exact repeats; one changed OCR transcription; four cases with changed regions; zero absent/ambiguous/missing statuses or issue flags; reference-inconsistency hypothesis supported
Next extraction task: STOP
```
