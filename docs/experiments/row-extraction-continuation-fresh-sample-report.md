# Fresh-sample continuation evaluation

Status: AWAITING_HUMAN_REVIEW. Authorized by the user's instruction to proceed on 2026-09-21.

```text
Scope answer: YES — measure complete merchant-field extraction and transaction discovery after the continuation fix
Experiment: row-profiles
Extraction hypothesis: The frozen continuation fix increases correctly owned exact merchant output without losing previously exact billed transactions
Measurement: paired exact merchant matches, matched/unique-output coverage, discovery omissions and ownership errors on source-reviewed billed starts
Fixed inputs: candidate f6e3e0a72b4ede7ae15d7651af35d8d39fe6bb88; comparator aa19181a9fa52fd4b09293136ed19558376e3c6c; six further training documents selected below
Smallest allowed files: this report, live status and knowledge links; artifacts/merchant-continuation-fresh-v1/**
Required output: fixed paired evaluation, or source-reviewed AI draft packet awaiting human corrections with quantified preparation
Stop condition: completed scoring or real human/input dependency; no tuning, resampling, validation/test access, gold promotion or merge
```

## Plan and boundaries fixed before new input access

1. Freeze source trees for the two commits. Use their ordinary `parse_statement`
   entry point, including normal document context and OCR repair, with identical
   installed dependencies and separate initially empty local OCR caches. Do not
   substitute the historical spacing experiment or alter extraction behavior.
2. Read existing training membership/source-mode metadata only. Exclude all
   documents recorded in earlier merchant `selection.json` files, including the
   six-document seed and six-document disjoint pilot, and byte-identical copies.
   The known inventory leaves one OCR-backed training document; select **one OCR
   and five digital-only documents**. Unknown-mode documents are ineligible.
3. Rank eligible identities by SHA-256 of UTF-8
   `merchant-continuation-fresh-v1`, NUL, document identity; break ties by identity.
   Take the first required identities per stratum. Rank every physical page by
   SHA-256 of UTF-8 `merchant-continuation-fresh-page-v1`, NUL, document identity,
   NUL, one-based page number, breaking ties by page number. Take one page per
   document. Check source hashes and freeze selection before rendering. Missing
   sources, insufficient membership or unverifiable exposure exclusions stop the
   task; do not replace selected documents/pages. Empty pages remain in scope.
4. Inspect selected source images and prepare complete merchant-field reference
   drafts independently of predictions. Same-document pages may resolve context;
   count only transaction starts on the selected page. Include billed, future and
   uncertain sections separately; preserve numeric codes, prefixes, URLs, location
   text and owned continuations inside the field. Native text can aid transcription
   only after visual inspection. Record unclear text rather than guess it.
5. Reuse the existing local editable worksheet with a distinct packet identity.
   Prefill AI source readings, provide CSV/JSON and page images, and leave all
   human confirmations false. The user corrects mistakes and confirms the census.
   This is an AI-assisted single-human-reviewed pilot, not independent gold.
6. Run both frozen parsers without reference inputs. Save complete outputs privately;
   do not inspect paired merchant differences or score until human references are
   frozen. Operational failures stop execution; normal unsupported/unreconciled
   results and empty outputs are valid outcomes. No post-score fixes are allowed.
7. After reference freezing, align each view independently to the same fixed
   transaction-start regions, using primary `row_results` rectangles: positive
   horizontal intersection, vertical intersection at least half the output-row
   height, then unique greatest IoU. Reject ties and duplicate assignments; do
   not rescue collisions or match on text. Candidate-dependent output geometry is
   an extraction result, not permission to change the reference or matching rule.
   Review ownership on source evidence with methods hidden. Never treat all
   transaction evidence as merchant evidence: it also includes dates and amounts.

## Metrics and decision

Primary scope is source-confirmed **billed** starts; future-billing transactions
are censused and reported separately because the production parser deliberately
excludes them. Uncertain billing scope remains unresolved rather than silently
included or dropped. Define N as billed starts, P as present unambiguous merchant
fields, A as confirmed absences, U as unresolved fields; require N = P + A + U.

For each version report source-page/document counts, observed OCR/digital mode,
alignment and unique-output coverage, missing/unmatched rows, ties/collisions,
null/empty merchant outputs, unassigned emissions, and ownership failures. Count
exact NFC plus collapsed-whitespace matches on P, with omissions retained in the
denominator. Report text-only equality separately from ownership-verified E/P and
E/N. Report correct abstention/false emission on A and unresolved outcomes on U.
Use Decimal for rates; empty denominators mean NOT MEASURED. Report per-document
counts and paired gains/losses rather than row-level statistical confidence.

Support the gain hypothesis only with positive verified exact delta, no previously
exact loss, no coverage decrease or added ownership/absence error, complete censuses,
U=0 and no unresolved ownership or billing scope. Require at least one billed
present case in each observed evidence mode for a two-mode conclusion. Regressions
falsify no-regression; an otherwise complete eligible zero-delta result falsifies
the gain hypothesis on this pilot. Missing review or insufficient eligible cases
means INCONCLUSIVE, not zero accuracy. No tuning on these pages follows scoring.

This is document-disjoint from earlier merchant work, within existing training
membership. Other older project work may have used these documents; unknown
near-duplicates remain a limitation. It is neither untouched held-out evaluation
nor private-corpus acceptance. The previous 89-case evaluation and its outstanding
ownership review remain frozen and independent.

## Verification and continuation

Reuse and check the existing worksheet and matching/metric logic rather than build
new infrastructure. Check fixed quotas/exclusions/source identities, output commit
provenance, JSON/CSV agreement, empty confirmations, worksheet save/load and ZIP
integrity. Run all repository gates before the result commit. Keep document text,
identities, financial data and detailed results in ignored local files only.
Resume scoring under this same objective when human answers arrive; no further
subtask approval is required.

## Preparation and source-review result

The committed rules selected six further documents from 78 training documents.
All 12 documents exposed in earlier merchant selections were excluded, leaving
one eligible OCR-backed and 65 digital-only documents. Nine prior selection files
were checked. The selected one OCR/five digital documents all passed byte-identity
checks. Selection and both source trees were frozen before rendering; no selected
page was replaced.

The assistant visually reviewed all six selected pages and a same-document context
page for billing/continuation scope. **Four pages have no transaction starts**:
notices, advertising or a fee-invoice summary rather than individual transactions.
The other two have **11 and five billed starts**, respectively. The AI draft thus
contains **16 present-field suggestions**, all with digital text and owned second
lines, and one attention note about an abbreviated printed ending. All 16 readings
were checked against enlarged source images and native PDF text after visual
inspection. These counts are suggestions, not a confirmed denominator.

The selected OCR-backed page has no suggested transaction starts. Therefore the
planned two-mode eligibility is **INCONCLUSIVE** on current source review, even if
the eventual digital comparison improves. Preserve that limitation; do not choose
a replacement page or infer an OCR result from the document stratum.

Both pinned parser versions completed all six full-document runs: **12 outputs**
are saved privately, with separate initially empty OCR caches and unchanged source
trees. Generation read source PDFs only, never draft references. No paired text
comparison or scoring has been performed. Outputs are kept outside the review
packet. Merchant accuracy and metric delta remain **NOT MEASURED**.

Private files under `artifacts/merchant-continuation-fresh-v1/`:

- `selection.json`, `freeze.json` and `versions/`: fixed sample and source trees;
- `reference-draft.json`, its hash and `merchant-review.csv`: preserved AI readings;
- `review-assets/review.html` and `merchant-continuation-fresh-review.zip`: editable
  source-only worksheet, six source PDFs, 14 page images and review instructions;
- `predictions/`: complete baseline/candidate outputs and their hash manifests;
- `selection-summary.json`, `packet-summary.json` and `verification-summary.json`:
  preparation counts and checks, with no claimed extraction accuracy.

The worksheet prefills merchant text, source regions, notes and billed section.
Every case and all six page censuses remain unconfirmed. The four suggested empty
pages also need explicit census confirmation. Correct readings or add/remove
starts as needed, then return
`merchant-continuation-fresh-human-field-v1-answers.json`. This is the real remaining
human dependency required by the repository reference policy and the plan above.
Resume this same evaluation after return; no new subtask approval is needed.

## Preparation verification

Two selection checks pass. Seven JavaScript checks cover pending confirmations,
explicit page acceptance, invalid suggestions, corrections/download, adding missing
starts and rejection of answers from the previous experiment. The local worksheet
runs in a DOM test harness; no graphical browser check was available.

All 16 CSV/JSON readings agree, all confirmations are false, all source and output
hashes validate, and both pinned source trees are unchanged. The ZIP is intact and
contains all expected assets without predictions. All seven private Python files
pass Ruff and strict mypy. No production code, protected membership, accepted gold,
baseline or historical experiment was changed; no private-corpus acceptance or
production merge is claimed.

Repository Ruff format/lint, mypy and all **3,802 tests** pass (101.01 seconds).
All changed documentation links resolve; detailed source/reference/output files
remain ignored and local.
