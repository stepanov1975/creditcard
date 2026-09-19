# Merchant Whitespace Location Report

**Status:** COMPLETE — STOP. Measured on 2026-09-19.

**Authority:** The user's “proceed” approved the spacing experiment's concrete
recommendation. The [design](../superpowers/specs/2026-09-19-merchant-spacing-location-design.md)
and charter allowance were committed at `ef8e597` before private measurement.

## Result

The two spacing-only digital failures contain **six extra whitespace gaps**.
All six are **inserted separators between source atoms**. There are **zero
within-atom discrepancies, zero explicit-source-whitespace discrepancies and
zero unresolved attributions**. Both cases are representable with different
separator choices while keeping source text and selected atom order unchanged.

The previous spacing candidate leaves **all six discrepancies unchanged**:
zero removed, six remaining and zero introduced. Its changes elsewhere did not
address these two cases. The hypothesis that at least one remaining discrepancy
lies inside a source atom is **falsified**.

| Measurement for the two fixed cases | Saved v3 baseline | Saved spacing candidate |
| --- | ---: | ---: |
| Cases with only between-atom discrepancies | 2 | 2 |
| Cases with within-atom or mixed discrepancies | 0 | 0 |
| Unresolved cases | 0 | 0 |
| Extra whitespace gaps | 6 | 6 |
| Missing whitespace gaps | 0 | 0 |
| Gaps consisting only of inserted separators | 6 | 6 |
| Gaps containing source whitespace | 0 | 0 |
| Separator-only repairable cases | 2 | 2 |

All **48 saved scores reproduce**. The full seed stays **17/24 exact (70.8%)**
in both views, with 24 aligned unique outputs, two partial texts and five other
mismatches. This task did not generate a corrected output or claim an accuracy
gain. It identifies what the saved representation can express, conditional on
the reviewed v3 reference.

## Attribution method and meaning

The selection is exactly the same two spacing-only digital cases in the saved
baseline and candidate. Their four output strings reconstruct from the existing
proposal or assembly atom order and saved separator decisions. Selected atom
records match the original saved row evidence; ownership and source page match.

The diagnostic normalizes each atom to NFC while retaining its occurrence index,
and tags inserted separators separately. In all four case views, that construction
matches NFC of the raw saved output, with no cross-atom composition or duplicate
source-observation ambiguity. Output and reference have identical non-whitespace
character sequences. Each differing whitespace gap is located by ordinal position
in that shared sequence, without fuzzy matching or word rearrangement.

For all six differing positions, the flanking characters belong to different
atoms and the intervening whitespace comes entirely from inserted separators.
Changing those separator choices could express the reference. This is a
reference-guided diagnostic statement, not evidence that a geometry-only rule
can reliably choose the correct boundaries without labels.

Atom-box overlap was not used to infer character ownership or printed word
boundaries. No source PDF, pixel, glyph record, OCR or external service was read.
No new spacing rule, threshold, source extraction, annotation or prediction was
created. Baseline outputs, candidate outputs, references and frozen branches
remain unchanged.

## Verification

- Seventeen invented-input tests pass after the initial location and uncertainty
  behavior failed as expected and was implemented. They cover extra/missing gaps
  within/between atoms, explicit source-edge and mixed whitespace, repeated
  characters, Unicode whitespace, internal NFC, cross-atom composition, duplicate
  evidence, mixed case categories, whitespace-run/edge normalization and invalid
  separator contracts.
- Reproduced all **48 saved baseline/candidate scores** and the exact two-case
  selection; reconstructed **four selected-case output strings** from unchanged
  source atoms and recorded separators.
- A separate regex/character-offset calculation agrees on **12 discrepancy
  records**: the same six gaps checked in both views. It confirms all locations,
  directions, origins, case categories and separator-only repairability.
- Independent verification agrees on both aggregate views and all four
  before/after transition counts: removed, remaining, introduced and unresolved
  pairs.
- Fourteen measurement inputs and 14 verification inputs remain unchanged;
  these sets overlap. The frozen deterministic checkout is unchanged, and zero
  source documents were read.
- Private formatting, lint and strict mypy pass. Required repository gates pass:
  Ruff formatting, Ruff lint, mypy over 48 source files and **3,766 tests**.

All text, source identities, atom positions and per-case details remain in ignored
local artifacts. Only aggregate documentation is tracked. This remains a small
same-reviewer training-seed analysis, not independent label certification,
document-disjoint validation or production/private-corpus acceptance. No merge or
push was performed.

## Next recommendation

Quantify **which recorded spacing-rule conditions retained these six incorrect
separators**, and compare those same conditions with boundaries in the **17 exact
control cases**. Use the saved decisions and evidence without changing thresholds
or generating outputs. This would determine whether a specific general condition
deserves a new extractor experiment, rather than choosing another threshold
without evidence. The recommendation has not been executed or authorized here.

The fixed two-case location measurement is complete. **STOP**. No new candidate,
tuning, broader diagnosis, source extraction, label change, review, expansion or
held-out access is active.

```text
Scope: YES — located two merchant whitespace failures in saved source evidence
Experiment: shared evaluation
Measurement: within-atom/between-atom whitespace locations and separator-only repairability
Result: six extra inserted separators between atoms across two cases; zero within-atom or unresolved discrepancies; both cases separator-only repairable in principle; hypothesis falsified; score unchanged at 17/24
Next extraction task: STOP
```
