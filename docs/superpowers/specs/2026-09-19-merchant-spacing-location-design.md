# Merchant Whitespace Location Measurement

**Status:** COMPLETE — STOP. Results are recorded in the
[report](../../experiments/row-extraction-merchant-spacing-location-report.md).

The user's “proceed” approves the spacing experiment's recommendation to locate
the two remaining spacing-only digital discrepancies in saved atom text.

```text
Scope answer: YES — locates the two remaining merchant whitespace errors in the saved evidence representation
Experiment: shared evaluation
Extraction hypothesis: At least one remaining whitespace discrepancy lies inside a saved source atom and cannot be fixed by changing only separators between atoms
Measurement: within-atom, between-atom, mixed and unresolved spacing-error counts; separator-only repairability
Fixed inputs: two spacing-only digital cases, v3 references, saved baseline and spacing-candidate outputs, recorded atom selections/order, and all 24 paired scores
Smallest allowed files: docs/superpowers/specs/2026-09-19-merchant-spacing-location-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-spacing-location-report.md; artifacts/merchant-spacing-location-v1/**
Required output: quantified whitespace locations and whether existing atom boundaries can express the reference spacing
Stop condition: stop after the two-case location measurement or baseline reproduction failure; no new candidate, tuning, source extraction, or label changes
```

## Fixed selection and prerequisite

Reproduce all 24 v3 baseline and 24 saved spacing-candidate scores using unchanged
references, alignment, outputs and normalization: 17 exact in each view, zero
gains/losses, full aligned unique-output coverage, and two spacing-only digital
cases in both. Select that exact same two-case set; no other failure analysis.

For the two cases, reconstruct baseline and candidate strings from recorded
proposal/assembly atom order and the saved separator decisions. Read the same
135 row records and saved proposals to confirm evidence identity and ownership.
Do not rerun the spacing rule, matcher, extractor, assembly decisions or OCR.
Do not read source PDFs or pixels, generate predictions, change labels or query
any external service. Earlier artifacts and the frozen checkout remain unchanged.

## Whitespace attribution

The public diagnostic seam accepts ordered atom strings, the recorded separators,
reference text and an evidence-uniqueness flag. It emits discrepancy locations,
origins and a case category; it never emits corrected merchant text.

Use NFC plus collapsed Unicode whitespace as in existing scoring. Normalize each
atom separately while retaining its occurrence index on every resulting code
point; tag inserted separator whitespace separately. Require this concatenation
to equal NFC of the raw reconstructed output before whitespace collapse. If NFC
combines across atom boundaries, do not guess ownership: mark attribution unresolved.
Also mark duplicate occurrences of the same source observation unresolved. Atom-box
overlap alone does not determine character ownership; this measures the recorded
text representation, not new glyph-level source truth.

After normalization, require identical non-whitespace character sequences in the
reference and output. Locate whitespace presence at each internal gap by its ordinal
position in that common character sequence. Repeated characters do not require a
fuzzy alignment. Ignore leading/trailing whitespace and distinguish presence, not
run length, consistent with the scorer.

For each differing gap record:

- **Extra whitespace** when present in output but absent in reference; **missing
  whitespace** for the reverse.
- **Within atom** when the two flanking non-whitespace characters belong to the
  same saved atom occurrence; **between atoms** otherwise.
- For extra whitespace, distinguish source-only whitespace, inserted-only
  whitespace and mixed source/inserted whitespace. Missing whitespace has no
  whitespace origin in the output.
- A discrepancy is **separator-only repairable** when it is between atoms and
  either a space is missing, or an extra space consists entirely of inserted
  separators. Source whitespace cannot be removed by a separator-only rule.

Disjoint case categories are within-atom only, between-atom only, mixed, unresolved
or no remaining discrepancy. A case is separator-only repairable only if every
discrepancy is so repairable and attribution is resolved. This is a representation
capability measurement against the human reference, not a candidate prediction or
an assertion that geometry can determine the correct decision without labels.

Report both baseline and candidate views, gap counts by location/direction/origin,
case categories, unresolved reasons, and separator-only repairability. Attribute
removed, remaining and introduced discrepant gap positions between views. The
hypothesis concerns the saved candidate: supported if any resolved within-atom
discrepancy exists; falsified if all cases resolve and none exists; otherwise
unresolved. No new transcription or reference adjustment is inferred.

## Verification and stop

Commit authority before private measurement. Use invented-input red/green tests
at the diagnostic seam for extra/missing whitespace within/between atoms, source
edge whitespace, mixed origins, repeated characters, Unicode whitespace, internal
NFC, cross-boundary composition and duplicate observations. Independently verify
gap locations from raw strings and atom boundaries, output reconstruction, all
48 saved scores and aggregates. All scripts and case data stay under ignored
`artifacts/merchant-spacing-location-v1/`; publish aggregates only. Run the four
repository gates before tracked commits.

Stop after this count or a baseline failure. No second spacing candidate,
threshold tuning, broader error analysis, source extraction, rendering, OCR,
review, label change, sample expansion, held-out access, reusable evaluation
infrastructure or production integration is authorized.
