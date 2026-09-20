# Document-disjoint merchant evaluation

**Updated:** 2026-09-20

**Status:** AWAITING_HUMAN_REVIEW — the user requested AI-prefilled source readings
followed by their own corrections. The prefilled result files are ready. Accuracy
and paired improvement are **NOT MEASURED** until human review and scoring finish.

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

## AI-assisted source review and result files

Amendment `1f90c55`, committed before drafting labels, records the user's change
from two independent blank-first reviews to AI suggestions followed by their own
corrections. The tier is **AI-assisted, single-human-reviewed pilot**. The original
blank packets remain historical artifacts; frozen sampling and predictions are
unchanged. The assistant did not read saved prediction strings or boxes to draft
these references.

The assistant visually inspected all six selected source pages, rendered enlarged
merchant-column details, checked native glyph spelling/geometry after visual
inspection, and inspected marked transaction/merchant regions on every page.
There are **89 proposed transaction starts**, distributed 7, 9, 11, 12, 27 and 23
across the six anonymous sample pages. Draft statuses are 88 present merchants and
one absence; **22 cases carry attention flags** for reference-code boundaries,
spelling, mixed direction, a transfer without a visible payee, or wrapped text.
These are unconfirmed draft counts, not measured accuracy or accepted denominators.

Private files are under ignored `artifacts/merchant-document-disjoint-v1/assisted-review/`:

- `merchant-review-prefilled.zip`: complete local review packet, including sources.
- `review.html`: worksheet with AI suggestions loaded automatically, editable text
  and regions, attention flags, next-transaction navigation, and explicit page review.
- `merchant-review-draft.json`: preserved initial suggestions for this handoff.
- `merchant-review.csv`: readable table of the same suggestions and review notes.

The user extracts the ZIP and opens `review.html`. They can correct/remove entries,
add missed transaction starts and adjust evidence regions. After inspecting a
whole page, **Confirm page review** confirms its valid entries and census in one
explicit action. It never converts unresolved ambiguity into a clear reference.
Save answers downloads the corrected JSON; Load answers resumes it. All 89 cases
and all six page censuses start unconfirmed. The saved human answer file remains
separate from the preserved AI draft.

Reference-like suffixes were tentatively excluded where separately identifiable;
those choices are flagged for human review. Second-line billing URLs, locations
and fee narratives were excluded from merchant spans. Human corrections may alter
these proposed boundaries before reference freezing. No accepted gold was changed.

The user must still check all six complete pages, including possible omissions.
AI-prefilling introduces anchoring risk and is not independent human agreement.
Freeze the corrected reference before revealing method differences, then perform
the ownership audit and paired comparison. No scores were computed from AI drafts.

## Verification and continuation

The assisted packet passed ZIP integrity checks; embedded worksheet state, JSON
and CSV agree on all 89 suggestions, and every source asset and control resolves.
All confirmations start false. Six focused JavaScript tests check explicit page
acceptance, invalid-entry rejection, preserved draft state, correction/download
round-trip, and census invalidation after adding a missed transaction. The tested
worksheet runs in a DOM test harness; a graphical browser was unavailable.
Annotated source regions were visually checked on all six pages.

Final verification passed: repository Ruff format/lint, mypy and **3,766 tests**
(100.29 seconds), plus private Ruff and strict mypy for the five assisted-review
Python scripts. All 13 local links across the current design, live status and
report resolve. Earlier adapter and blank-packet verification remains preserved
in local logs. Source contents, annotations and result files remain ignored and
local. This is not a private-corpus acceptance attestation.

The next dependency is the user's corrected answer JSON and six confirmed page
censuses. Continue reference freezing, ownership review and fixed three-view
scoring when they arrive, without another approval. Production integration and
private-corpus acceptance remain outside this evaluation.
