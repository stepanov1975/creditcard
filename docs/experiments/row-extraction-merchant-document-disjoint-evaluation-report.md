# Document-disjoint merchant evaluation

**Updated:** 2026-09-20

**Status:** AWAITING_HUMAN_REVIEW — the objective remains authorized. Two independent
human reviewers are available; their readings, adjudication and ownership audit
are required before scoring. Accuracy and paired improvement are **NOT MEASURED**.

## Fixed experiment

The [design](../superpowers/specs/2026-09-20-merchant-document-disjoint-evaluation-design.md)
is binding. Authority commit `0ce4346` authorizes the full objective, including
routine adapters, preparation, tests, execution and reporting without per-subtask
approval. The [live status](row-extraction-program-status.md) records its dependency.

Compare the frozen unchanged-order spacing candidate against LTR tolerance
(primary) and punctuation spacing (secondary), using common proposals and a
reference census independent of discovery. Do not tune against this sample.

## Preparation and exposure

The adapter reproduced all 135 earlier proposals and all 113 output owners in
each of the three saved seed views before opening new sample pages. This is
reproduction of the earlier result, not an additional accuracy measurement.

Selection used metadata for 78 training documents and excluded the six documents
already exposed in merchant experiments. Eight saved merchant selections were
cross-checked. The eligible population contained three OCR-backed documents and
69 digital-only documents; none had unknown source mode. The committed hash
ranking selected two OCR-backed and four digital-only documents. These are
**document metadata strata**, not a claim that every selected page uses that mode.

One physical page per document was selected from all pages before source content
inspection; all six source identities verified. Empty pages remain eligible and
no replacements are permitted. These documents are disjoint from the merchant
seed, but remain part of the older row-model training pool: this is neither
validation nor an untouched project holdout.

## Predictions frozen before references

All six selected pages produced 114 saved row proposals and 104 output owners in
each of the three fixed views. No additional native pre-filter rows were found.
Original OCR evidence is retained when native detection finds no regions. When
the frozen detector retries after overlay handling, the adapter takes its final
pre-filter result rather than concatenating alternative detections. Detector,
classification, ownership and rendering rules remain frozen.

These are generated-output counts, **not reference transaction counts or coverage**.
No human references were read. Saved proposals, common owners, atom order and all
three renderings reproduce from saved evidence; private output hashes are intact.

## Independent human review

Private artifacts are in ignored `artifacts/merchant-document-disjoint-v1/`.
`reviewer-A.zip` and `reviewer-B.zip` contain separate blank worksheets, six source
PDFs and 16 page images at 300 DPI including supporting context. They contain no
suggested transactions, model predictions, prior merchant labels or answers.

Each reviewer extracts their ZIP and opens `review.html` locally. Reviewers must
work independently, enumerate every transaction start on all six census pages
(including future billing), mark transaction/merchant evidence and confirm each
page census. Other pages supply context only. An empty census requires explicit
confirmation; uncertainty must be recorded rather than guessed.

Each reviewer returns their own saved answer JSON privately. The worksheet can
save and reload drafts and rejects the other reviewer's answer file. Do not share
answers or predictions until both independent reviews finish. Adjudicate source
readings without predictions, freeze the reference census, then perform the
method-blinded ownership audit and paired scoring under the fixed design.

No reference census has been returned, so transaction counts, reference
eligibility, discovery omissions, ownership errors and all accuracy denominators
remain unknown. Missing discovery must count in the eventual census denominator.

## Verification and continuation

Source packets passed archive integrity and content checks: both expose the same
source pages, all assets and worksheet controls resolve, and network connections
are disabled by the worksheet policy. Synthetic checks cover blank/empty census,
confirmation invalidation, independent draft round-trip, invalid geometry and
reviewer identity, ambiguity/absence, selection exclusions, fixed rendering and
native detection retries. A graphical browser check was unavailable in this
workspace; packet structure and JavaScript syntax/state logic were checked.

Verification passed: repository Ruff format/lint, mypy and all **3,766 tests**
(102.49 seconds); private Ruff and strict mypy across 14 Python files; six focused
Python tests and six JavaScript review-state tests. All 22 local links checked in
the instructions, live status and this report resolve. Sensitive packet content,
source evidence and predictions remain ignored and local. This is not a
private-corpus acceptance attestation.

The next dependency is both independent human answer files. Continue adjudication,
reference eligibility checks, ownership review and three-view scoring within this
same approved objective when they arrive. No new permission or candidate tuning
is needed or implied. Production integration and corpus acceptance remain outside
this evaluation.
