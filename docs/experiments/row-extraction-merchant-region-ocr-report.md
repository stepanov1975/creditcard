# Merchant-Region OCR Experiment Report

**Date:** 2026-09-12  
**Status:** `COMPLETE — STOP`  
**Authority:** [Design](../superpowers/specs/2026-09-12-merchant-region-ocr-design.md),
[plan](../superpowers/plans/2026-09-12-merchant-region-ocr.md), and charter amendment
committed at `edff31a` before private recognition.

OCR confined to extractor-selected merchant regions scored **8/24 exact merchants**,
compared with **10/24** for the saved deterministic reading-order descriptions.
It produced **zero gains and two losses** of previously exact matches. The positive
net-gain hypothesis is falsified on this fixed training seed. Retain 10/24 as the
best measured comparator; this OCR candidate does not justify replacement.

## Fixed comparison

The candidate rendered the union of each description proposal's selected atom
boxes, applying page rotation and requiring full page containment. It used the
frozen OCR recognizer at 300 DPI, PSM 6, zero padding, internal Otsu, OEM 1, and
its pinned Hebrew/English model packs, including the existing three-stream fusion.
The already fixed directional-run rule ordered new OCR atoms before rendering.

All 108 saved description proposals on the selected six training pages were
processed. Recognition read existing extractor geometry and source copies; human
text, human regions, alignment, and case scores were confined to scoring. No
answer-based crop, output selection, parameter sweep, or retry with changed settings
was used. This measures the fixed regional OCR pipeline against deterministic
reading-order descriptions; it does not isolate the causal effect of crop size.

| Measurement | Deterministic reading order | Merchant-region OCR |
| --- | ---: | ---: |
| Exact merchants, all references | 10/24 (41.7%) | 8/24 (33.3%) |
| Exact merchants, aligned references | 10/20 (50.0%) | 8/20 (40.0%) |
| Unique-description coverage | 18/24 | 18/24 |
| Digital-page exact merchants | 7/16 | 5/16 |
| OCR-page exact merchants | 3/8 | 3/8 |
| Alignment failures | 4 | 4 |
| Omissions | 1 | 1 |
| Ambiguous owned outputs | 1 | 1 |
| Partial-text mismatches | 2 | 1 |
| Other text mismatches | 6 | 9 |
| Extra-text mismatches | 0 | 0 |

The net delta is -2 exact merchants, or -8.3 percentage points over all 24 cases.
Both losses occurred on digital pages. OCR-page exact matches stayed at 3/8, and
no previously non-exact case became exact. Four alignment failures remain in the
denominator under the unchanged rule.

## Availability and interpretation

Of 108 proposals, **106 produced text and two returned empty OCR**. All crops
were valid and rendered successfully; no recognition invocation failed. All **20
proposals owned by reviewed transactions produced text**, including the two
separate proposals behind one ambiguous owner. The two empty OCR results occur
outside the reviewed slots and do not explain the measured regressions.

The remaining 19 frozen observations had no original description and were not
sent to OCR. There were 325 OCR subprocesses including one version query and
three baseline recognition streams per crop. All original transaction
classifications, financial decisions, reasons, and proposal ownership were
preserved. Empty slots retain ownership, so an OCR failure cannot remove a
competing proposal to turn ambiguity into an apparent match.

This fixed crop/recognition approach does not improve the seed result. The counts
do not establish whether the lost matches arise from character recognition,
serialization, or fusion. No additional error analysis or rescue candidate was
launched. Historical OCR validation status remains stopped.

This is a small, single-reviewer training seed already used to develop hypotheses.
It is calibration evidence, not independent gold verification, a validation
estimate, production transaction accuracy, or private-corpus acceptance.

## Verification

An empty implementation failed six focused checks as expected. The completed
helpers pass **10 invented-input tests** covering selected-atom union, page
rotation, invalid/outside geometry, no crop expansion, new evidence rendering,
empty outputs, and retained transaction ownership and ambiguity.

All source copies matched their frozen document identities, and the OCR model
packs matched the frozen baseline pins. The OCR checkout retained its pinned SHA
and clean tracked state before and after recognition. Recognition preserved all
input bytes and never read human reference files. The scorer reproduced every
saved baseline output and category, then independently rebuilt candidate strings
from saved OCR atoms without the renderer/collector and checked every category
and paired gain/loss. Original references, alignment, predictions, and submitted
answers remained unchanged.

Final verification passed: Ruff format/check, mypy over `src`, and **3,766
repository tests**, plus the **10 focused tests**. All four private Python files
pass Ruff format/check and strict mypy in their respective frozen import contexts.
Production parser code was not changed, no private corpus gate was run, and no
corpus-acceptance claim is made. Private scripts,
crops, cached OCR streams, detailed predictions, and scores stay ignored under
`artifacts/merchant-region-ocr-v1/`; only aggregate documentation is committed.

## Next experiment recommendation

Quantify why the four reviewed transactions have no matching frozen rows,
distinguishing coordinate/alignment failure from missing row extraction using
the existing geometry. This would clarify an unresolved extraction-coverage
limit before another merchant-recognition change. The recommendation is separate
from this completed experiment and has not begun.

```text
Scope: YES — measured merchant-focused OCR against the fixed extraction comparator
Experiment: row-ocr
Measurement: merchant exact matches, paired gains/losses, coverage, and crop/recognition failures
Result: hypothesis falsified on the fixed seed; 10/24 to 8/24 exact, zero gains and two losses; coverage unchanged at 18/24, with no reviewed-proposal recognition failure
Next extraction task: STOP
```
