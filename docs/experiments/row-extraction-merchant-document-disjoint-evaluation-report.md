# Document-disjoint merchant evaluation

**Updated:** 2026-09-21

**Status:** AWAITING_HUMAN_REVIEW — reference review is complete; the remaining
step is prediction-evidence ownership review. All three frozen views match
**49/89 reference strings**, with zero paired gains/losses and identical output
strings on every reference case. Ownership-verified accuracy remains **NOT MEASURED**;
the full eligibility decision is **INCONCLUSIVE** pending the required audit.

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

## Corrected merchant-field review — preparation history, 2026-09-21

The user clarified that the task extracts **all printed text in the merchant
position**, not a true business name separated from reference codes. Authority
`bd4910d` updates the domain definition, repository instructions and evaluation
design. The previous AI draft made a semantic-trimming error; that draft and its
packet remain preserved as superseded history. No human-confirmed reference or
accepted gold had been frozen, and no scoring had occurred.

Packet v2 contains the same **89 proposed transaction starts** on six pages
(7, 9, 11, 12, 27 and 23), with **29 field values corrected**. Restored text includes
reference codes and merchant-field continuation lines containing URLs or locations.
A printed transfer description is now present field text rather than an inferred
merchant absence. All 89 draft fields are nonblank; these are unconfirmed source
readings, not accepted metric denominators.

Only geometric field boundaries and transaction ownership determine what belongs
in the field. Other table columns and distinct full-width explanatory rows remain
separate. No text inside the merchant field is dropped because it looks like a
code, location, payment processor or service description. Historical scores keep
their original reference definitions; they do not establish complete-field accuracy.

**Nine attention flags** remain for scanned-character transcription, spelling,
mixed direction or wrapped text. The prior warnings asking the user to separate
business names from reference codes have been removed. All cases and all six page
censuses remain unconfirmed. The sample and extraction predictions are unchanged;
no saved prediction strings or boxes were read to make this correction.

Private result files are in ignored `artifacts/merchant-document-disjoint-v1/merchant-field-review/`:

- `merchant-review-prefilled-v2.zip`: corrected local worksheet, source documents
  and images, draft JSON and CSV.
- `review.html`: prefilled editable review with complete merchant text/regions.
- `merchant-review-draft.json` and `merchant-review.csv`: the same corrected entries.

Extract v2 and open `review.html`. Correct transcription or ownership, add missed
starts, then confirm each page and save the v2 answer JSON. Its distinct reviewer
identifier prevents loading an old packet's answer file accidentally. Earlier
files and any separately saved user edits remain intact; old answers are not
silently treated as confirmations of the corrected contract.

This remains an AI-assisted, single-human-reviewed pilot under amendment
`1f90c55`, with possible anchoring from suggestions. The user must check the whole
page, including omissions, before reference freezing, ownership audit and scoring.
No production parser changes or integration are part of this correction.

## Returned human references and fixed text comparison

The user returned the v2 answer JSON with all **89 entries and six page censuses
explicitly confirmed**. No merchant values, source regions, ownership labels or
case membership changed from the v2 draft. All references are present and marked
billed, with clear reference ownership: **N = P = 89, A = U = 0**. The nine AI
attention notes remain provenance, not unresolved human reference statuses.

The worksheet exporter left its old pending-review tier label unchanged. The
original attachment bytes are preserved; a separate freeze record captures the
explicit confirmations and the **AI-assisted, single-human-reviewed** tier. This
is not independent certification or accepted-gold promotion. The reference bytes
and denominator were frozen before prediction comparison. All nine frozen
prediction-file hashes remain unchanged; no extractor was rerun or tuned.

The original geometry-only matcher assigns **85/89** references uniquely. Four
have no qualifying row overlap; there are no ties or duplicate-assignment
collisions. All 85 assigned cases have one nonempty output in every view. Among
104 saved output owners, **19 remain unassigned**; 29 of 114 discovered rows are
unassigned. Unassigned output owners are reported separately, not automatically
classified as false positives.

| Document alias | Observed evidence | Reference starts | Text exact, each view |
| --- | --- | ---: | ---: |
| p01 | OCR | 7 | 6 |
| p02 | OCR | 9 | 4 |
| p03 | Digital | 11 | 0 |
| p04 | Digital | 12 | 0 |
| p05 | Digital | 27 | 22 |
| p06 | Digital | 23 | 17 |
| **All six** | | **89** | **49** |

Digital text equality is **39/73** and OCR **10/16**. Overall text equality is
**49/89 (55.06%)**, with all four unmatched references retained in the denominator.
There are 36 aligned text mismatches. Against both comparators the candidate has
**0 gains, 0 losses and 0 net text-exact change**, including zero changed output
strings on all 89 reference cases. There are no document-level text gains/losses
and no coverage differences. The frozen spacing transformation adds no text gain
on this pilot; these are not measurements of production fix `be8bbe7`.

The source-evidence precheck finds 62 assigned cases whose selected atoms lie
inside the reviewed merchant regions and 23 with selected evidence outside those
regions. There are 238 strongly supported selected atoms and 23 outside atoms;
no boundary-only atoms. These geometry checks are review suggestions, not verified
ownership judgments. No case has been marked human-audited automatically.

Private outputs under `artifacts/merchant-document-disjoint-v1/evaluation/`:

- `human-answers.json` and `reference-freeze.json`: original uploaded answers and
  frozen-reference metadata;
- `alignment.json`, `case-results.json`, `case-results.csv` and
  `text-comparison-summary.json`: the common assignment, complete comparison and
  aggregate counts;
- `ownership-review.html` and `merchant-ownership-review.zip`: source images with
  locked references, anonymous common output and selected-evidence overlays.

The ownership worksheet includes all 89 references, prioritizes the 23 geometric
flags visually, and leaves every confirmation false. Four unmatched cases have
no ownership decision and remain omissions. Correct or accept the suggestions
only after inspecting the evidence, confirm each page and return
`merchant-ownership-audit-v1-answers.json`. Per the committed design, reviewers
must inspect selected evidence with method names hidden and reference text locked.
The existing field-transcription review did not display that prediction evidence.

An independent calculation in native page coordinates reproduces all 89 geometry
assignments, while a separate arithmetic check reproduces all 267 text comparisons
and zero paired changes. Six synthetic checks cover normalization, ties/collisions,
missed-row denominators, absent/ambiguous fields, ownership failures and multiple or
empty outputs. Eight worksheet checks cover explicit confirmation, edits, pin
mismatches, duplicate/incomplete answers, uncertainty, missing outputs and locked
anonymous packet data. Private Python scripts pass Ruff and strict mypy. A graphical
browser remains unavailable; worksheet checks use Node and script compilation.
Repository formatting, lint, mypy and all **3,766 tests** pass (100.40 seconds).
Only aggregate documentation is tracked; answers, source evidence and results
remain local and ignored. This is not private-corpus acceptance.

## Earlier preparation verification

V2 passed ZIP integrity checks; worksheet state, JSON and CSV agree on all 89
entries, including multiline values. All confirmations remain false. The 29
changed field values, nine remaining flags and unchanged transaction-start
geometry were independently checked against the preserved draft. All 23 expanded
native fields matched the source PDF words in their marked regions. Source images
were reread for the scanned suffixes and native continuations; the enlarged
continuation regions were also visually inspected.

Seven JavaScript checks cover draft validation, explicit page acceptance,
invalid-entry rejection, correction/download round-trip, census invalidation and
rejection of superseded-contract answer files. These use a DOM test harness;
a graphical browser remains unavailable in the workspace.

Final repository Ruff format/lint and mypy passed, along with **3,766 tests**
(101.14 seconds). The three private v2 Python scripts pass Ruff and strict mypy.
All checked local documentation links resolve. Earlier verification
and the superseded packet remain preserved; no private data is tracked. This is
not private-corpus acceptance.

A code read at the reference-correction stage identified processor-reference separation in
[`extract_description`](../../src/ccparser/normalization_description.py) and its
helpers. The user subsequently requested a production fix on 2026-09-21. The
parser now preserves the full field and owned continuations; synthetic tests
cover codes, repeated references, mixed evidence kinds, output and reconciliation.
This separately authorized code correction does not change the frozen experiment
predictions or references. The fixed experiment must expose any omissions against
the corrected human-reviewed fields; it must not tune away failures before scoring.

The next dependency is the completed ownership-audit answer JSON. Resume the same
fixed comparison when it arrives, without another approval. Reference review is
complete; do not request it again or change frozen references after seeing scores.
Production integration and private-corpus acceptance remain outside this evaluation.
