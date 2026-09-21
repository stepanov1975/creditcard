# Document-disjoint merchant evaluation

**Updated:** 2026-09-21

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

## Corrected merchant-field review — 2026-09-21

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

## Verification and continuation

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

The next dependency is the user's corrected v2 answer JSON and six confirmed page
censuses. Continue reference freezing, ownership review and fixed three-view
scoring when they arrive, without another approval. Production integration and
private-corpus acceptance remain outside this evaluation.
