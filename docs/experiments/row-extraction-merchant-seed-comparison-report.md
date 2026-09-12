# Merchant Seed Comparison Report

**Date:** 2026-09-12
**Status:** `COMPLETE — STOP`

The existing row-OCR baseline produced 8 exact merchant matches among the fixed
24 human-reviewed cases. The stored accepted-parser projection and frozen
deterministic profile produced none. The predeclared improvement hypothesis is
**supported for this diagnostic seed comparison**: OCR gained 8 exact matches and
lost 0 against the stored baseline. This is not a validation win or a production
acceptance result.

The [design](../superpowers/specs/2026-09-12-merchant-seed-comparison-design.md),
[plan](../superpowers/plans/2026-09-12-merchant-seed-comparison.md), and charter
amendment were committed at `2bbbd92` before private execution. The 24 references
from the [completed seed](row-extraction-merchant-gold-seed-report.md) were not
changed or promoted.

## Inputs and alignment

The comparison used six training pages from six documents: two OCR pages with
8 reference cases and four digital-only pages with 16 reference cases. All six
local source copies and original source files matched their frozen identities.
The selected pages contain 127 original frozen rows. Available arms received all
127 unchanged observations so their existing continuation ownership remained
available; only the 24 human-reviewed cases were scored.

| Geometry measurement | Count |
| --- | ---: |
| Reviewed transactions matched to a frozen row | 20/24 |
| OCR-page references matched | 8/8 |
| Digital-page references matched | 12/16 |
| No row satisfying the predeclared overlap rule | 4 |
| Equal best candidate ties | 0 |
| Two reference cases assigned to the same row | 0 |

The four unmatched cases are on one digital page. They remain in the 24-case
success denominator, but are not asserted to contain wrong merchant text. Their
geometry does not meet the fixed rule; this alone does not establish whether the
cause is row detection, coordinate representation, or the human owner rectangles.
No box, threshold, match, or annotation was changed to improve the result.

## Merchant results

Exact matching uses NFC and collapsed Unicode whitespace only, preserving case,
punctuation, and reading order. Existing description proposals are scored as
merchant candidates without trimming or correction. Only accepted predictions
contribute proposals, and an owner must have exactly one description proposal.

| Method | Exact / 24 | Exact / 20 aligned | Unique descriptions emitted | Omissions among aligned cases | Ambiguous outputs | Alignment failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Stored accepted-parser evidence projection | 0 (0%) | 0 (0%) | 5 | 15 | 0 | 4 |
| Frozen deterministic profile, `tight` | 0 (0%) | 0 (0%) | 1 | 19 | 0 | 4 |
| Existing row-OCR baseline | 8 (33.3%) | 8 (40%) | 18 | 1 | 1 | 4 |

The stored baseline is the historical accepted-anchor **evidence projection**,
not a new end-to-end run of the released production parser. Its projection can
omit fields that it cannot ground exactly. These zero scores must not be described
as zero merchant accuracy for the current production release.

Unique-description coverage is 5/24 (20.8%) for the stored projection, 1/24 (4.2%)
for profiles, and 18/24 (75%) for OCR. The 127-row runs completed for both invoked
arms; the OCR run reported no `ocr_failure` reason.

| Method | Exact on 8 OCR-page cases | Exact on 16 digital-page cases | Paired gains vs baseline | Paired losses | Net exact matches |
| --- | ---: | ---: | ---: | ---: | ---: |
| Stored accepted-parser evidence projection | 0 | 0 | — | — | — |
| Frozen deterministic profile | 0 | 0 | 0 | 0 | 0 |
| Existing row-OCR baseline | 4 | 4 | 8 | 0 | +8 |

The OCR delta is +33.3 percentage points on the fixed 24-case denominator. On
digital pages, four cases were unaligned for every method. This small clustered
training seed does not justify a population estimate or significance claim.

Text and vision remain **unmeasured**: neither has a validation-eligible frozen
candidate. No rejected candidate was selected using the seed, and no new model
was trained. OCR's historical validation stop also remains unchanged; this run
uses its existing predeclared baseline as a diagnostic configuration.

## What the failures show

| Lexical category among unique emitted descriptions | Stored projection | Profiles | OCR |
| --- | ---: | ---: | ---: |
| Exact merchant | 0 | 0 | 8 |
| Reference is a proper substring of output: extra text | 0 | 0 | 1 |
| Output is a proper substring of reference: partial text | 0 | 0 | 0 |
| Other text mismatch | 5 | 1 | 9 |

These are string relationships, not adjudicated semantic causes. In particular,
the nine other OCR mismatches are not automatically hallucinations, recognition
errors, or wrong owners. Those distinctions require a separate error measurement.

The deterministic profile abstained on all 20 matched owner rows: 19 reported
`nonunique_billing_currency_evidence` and one reported `ambiguous_row_type`.
Therefore its merchant result is strongly limited by row-wide rejection. Its
one emitted description came from an accepted owned continuation. Similarly,
accepted continuation proposals can supply output for an abstaining baseline
owner; owner-abstention counts and description coverage are not disjoint measures.

The OCR arm had one nonaccepted matched owner, with `no_supported_ocr_evidence`.
Its existing acceptance behavior permits partial field proposals, whereas the
profile can reject the row because of another field. The measured comparison
therefore includes differing acceptance behavior; it does not isolate character
recognition quality.

## Recommended next task

Before expanding the dataset, measure **merchant proposal quality before
row-wide rejection in the deterministic arm** on these same 24 references. The
concrete trigger is currency-evidence ambiguity on 19 of 20 matched owner rows.
This would distinguish unavailable merchant evidence from usable merchant evidence
discarded because another field is uncertain. Keep accepted transaction behavior
unchanged during that diagnostic experiment.

This is a recommendation for a separately approved phase, not work started here.
The present comparison ends with `STOP`. The four alignment failures and ten OCR
text mismatches remain recorded for later investigation; they do not authorize
relabeling or expanding the sample automatically.

## Verification and limits

- Required repository gates passed: Ruff formatting and lint, mypy over `src`,
  and all 3,766 repository tests. These are tracked checks, not a private-corpus gate.
- Eleven invented-input tests passed for the immediate scorer, covering geometric
  matching, ties, collisions, threshold boundaries, proposal ownership, abstentions,
  ambiguous outputs, normalization, denominators, and paired gains/losses. The
  initial focused test run failed because the measurement module did not yet exist.
- The private scripts passed Ruff and strict mypy checks. Two narrow comments
  document unavailable PyMuPDF constructor typing; no extraction rule was suppressed.
- A separate local calculation verified exact-text counts, category totals,
  denominators, and paired gains/losses from the saved per-case results.
- The saved reference bytes and original user-answer bytes remain unchanged.
  Historical method checkouts stayed at their frozen heads without tracked edits.
- All source content, annotations, predictions, OCR caches, and per-case scores
  remain in ignored local paths. No private pixels or text entered model tools or
  external services. Tracked files contain only rules and aggregate findings.

The references remain a single-human-review calibration candidate. Geometry
matching is not an independent source audit, and mismatches may include alignment
or annotation differences. No old gold was read or changed, no validation/test
records were scored, no production code was changed, and no private-corpus
acceptance is claimed.

```text
Scope: YES — measured merchant extraction against the fixed human-reviewed seed
Experiment: shared evaluation
Measurement: normalized merchant exact-match rate, coverage, omissions, row-alignment failures, and paired exact-match delta
Result: OCR 8/24 exact versus 0/24 for the stored parser projection and frozen profiles; +8 gains, 0 losses; 20/24 references geometrically aligned; improvement hypothesis supported on this diagnostic seed
Next extraction task: STOP
```
