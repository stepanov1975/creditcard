# Merchant v3 Residual Error Analysis

**Status:** COMPLETE — STOP. Results are recorded in the
[report](../../experiments/row-extraction-merchant-v3-error-analysis-report.md).

The user's “proceed” approves the completed v3 comparison's recommendation to
diagnose its seven remaining mismatches using saved evidence.

```text
Scope answer: YES — quantifies the seven residual merchant extraction errors against v3
Experiment: shared evaluation
Extraction hypothesis: At least one remaining mismatch has exact merchant text in strongly located saved evidence, indicating a selection or assembly failure
Measurement: counts of selection/assembly failure, source-text mismatch, missing source evidence, and unresolved attribution
Fixed inputs: seven v3 mismatches, all 24 saved v3 scores, 135 saved rows, fixed assignments, assembly outputs, and source page geometry
Smallest allowed files: docs/superpowers/specs/2026-09-19-merchant-v3-error-analysis-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-v3-error-analysis-report.md; artifacts/merchant-v3-errors-v1/**
Required output: seven-case error counts, digital/OCR slices, and a supported or falsified extraction hypothesis
Stop condition: stop after the fixed error count or if v3 baseline scores cannot be reproduced; no extractor changes or new predictions
```

## Fixed inputs and prerequisite

Reproduce all 24 v3 case scores with the unchanged scorer, saved assignments and
assembly outputs: 17 exact, two partial texts and five other mismatches, with
24 aligned unique outputs. Select exactly the seven nonexact cases: five digital
and two OCR. Use 127 original rows plus eight saved diagnostic rows, existing
proposals, assembly statuses and saved assembled atom order. Trace the selected
atoms back to unchanged row evidence and reconstruct the saved output text from
that recorded order, without rerunning extraction or assembly decisions.

Keep the v3 reference, all earlier versions, submissions, predictions, assignments
and outputs unchanged. Read selected PDF copies only for identity, dimensions and
rotation; never read new text or pixels, render, run OCR or call models.

## Predeclared error categories

Use the existing merchant-region support rule: atom center inside a marked region
and maximum single-region overlap covering at least half its area means strong;
positive lesser overlap means boundary; zero overlap means outside. Invalid boxes
are unusable. Use the original/additional row coordinate conventions unchanged.

Search for exact diagnostic witnesses only in strongly supported atoms that are
not also strongly supported by another reviewed merchant on the same page. Use
the existing geometry/Hebrew reading-order helper without modification. Search
contiguous whole-atom spans within each row's ordered eligible atoms, plus one
page-wide ordered stream of eligible observations deduplicated by identical text,
normalized box, source and confidence. Do not reverse characters, permute words,
split atoms, borrow outside text, normalize punctuation, or tune thresholds.
Compare spans using the existing NFC/collapsed-whitespace normalization.

The public classification seam takes reference text, fixed evidence streams,
all nonempty strong/boundary atom texts, and geometry completeness. Apply this
disjoint precedence:

1. **Unresolved attribution:** unusable nonempty page evidence or an unusable
   reference region prevents a complete geometry check.
2. **Selection/assembly failure:** an exact whole-atom witness exists under the
   fixed search above while the saved output is nonexact. Report whether witness
   atoms were selected for the aligned output, partly selected or unselected,
   and whether their records come from the aligned or other rows. This proves
   recoverability in the saved representation conditional on the human regions;
   it does not independently prove that the evaluation assignment is correct.
3. **Missing source evidence:** no nonempty strong or boundary atom exists in the
   marked merchant regions among saved page rows. This is absence from the saved
   representation, not proof of a blank source page.
4. **Source-text mismatch:** no exact witness and the reference requires more of
   at least one non-whitespace NFC code point than all strong/boundary records
   together contain. Count raw records, including duplicates, to form a generous
   availability upper bound. This proves missing/incorrect characters relative
   to v3 within the saved region evidence; it does not distinguish recognition,
   evidence omission or residual annotation error.
5. **Unresolved attribution:** all other cases, including sufficient character
   inventory without an exact witness. Failure of the bounded span search alone
   is never called a recognition error.

Report disjoint counts and overlapping witness-selection, selected-atom support
and existing word-order/spacing/control-character signatures, overall and by
digital/OCR mode. Expected text is used only for diagnostic queries, never to
write a candidate output or change a score. The hypothesis is supported if any
case has a valid exact witness, falsified if none do and all geometry is usable,
otherwise unresolved. A falsified result concerns this fixed witness search.

## Verification and stop

Commit authority before measurement. Use focused invented-input red/green tests
at the classification seam for whole-atom spans, normalization, incomplete
geometry, missing evidence, missing characters and unresolved ordering. Reuse
existing geometry and reading-order helpers. Independently check saved output
reconstruction, geometry support, witness strings, category counts and slices.
Keep all data and disposable scripts under ignored `artifacts/merchant-v3-errors-v1/`;
publish aggregates only. Run the four repository gates before tracked commits.

Stop on baseline disagreement without retuning or substituting inputs. Stop after
the seven-case counts. No new extractor, predictions, label changes, review,
sample expansion, validation/test access, shared evaluator/controller/schema/CLI,
production integration or private-corpus acceptance is authorized.
