# Merchant Omission Alignment and Evidence-Routing Trace

**Status:** Approved by the user's “proceed” on 2026-09-12 following the concrete
recommendation to trace the remaining omission through saved alignment and
classification. Commit this authority before private measurement.

```text
Scope answer: YES — quantifies why the remaining merchant omission cannot reach retained evidence
Experiment: row-profiles
Extraction hypothesis: At least one strongly located merchant atom is already selected into a description owned by a different row than the reference alignment
Measurement: alignment ranking, classifier proof conflicts, merchant-evidence routing, and omission-gate counts
Fixed inputs: one unchanged omission, its selected training page and human regions, saved rows/predictions, assembly outputs, and frozen profile rules
Smallest allowed files: docs/superpowers/specs/2026-09-12-merchant-omission-routing-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-omission-routing-report.md; artifacts/merchant-omission-routing-v1/**
Required output: quantified omission cause and supported or falsified evidence-routing hypothesis
Stop condition: stop after one fixed omission trace; no rematching, new prediction, label change, or support subsystem
```

## Fixed case and alignment

Select the sole omission from the saved primary/continuation assembly comparison.
Reproduce all 24 saved scores from the saved assembly outputs and unchanged
candidate alignment: 13 exact matches and 23 unique descriptions. Other cases
are score controls, not a new error-analysis sample.

Use the saved 127 original plus eight diagnostic training rows, 135 predictions,
existing human transaction/merchant regions, saved probe gates, and selected-page
metadata. Open only the affected local source copy for identity and the selected
page's dimensions/rotation. Original rows use native-point normalization; additional
rows use display-point normalization. Do not extract text, render, or run OCR.

Reproduce the unchanged geometric matcher for the four references on that page,
including its unique-best and collision rules. Keep all assignments fixed. Count
the omission's positive-overlap candidate rows and best-score ties; record the
aligned row's rank and the ranks of rows containing strongly located merchant
atoms. Raw boxes, scores, margins, and identities remain private. A reproduction
disagreement is a measured limitation and stops the trace without rematching.

## Retained evidence and routing

Reuse the existing atom-support rule against the omission's merchant and
transaction regions. Count strongly located records, alphabetic records, distinct
positioned observations, their source rows, and containment in source-row boxes.
Keep duplicate records. Expected historical evidence is four alphabetic records
in other rows and none in the aligned row; report any reproduction disagreement.

For every strongly located merchant record, follow its exact source row and atom
ID through saved description proposals. Count records selected for the aligned
owner, selected for another owner, selected for multiple owners, or unselected in
the aligned/other row. Separately count whether those owners currently emit a
description and whether source rows are saved predecessor/successor neighbors of
the aligned row. Do not transfer evidence, infer new links, or select an owner
using merchant equality. Do not score alternative ownership.

Support the hypothesis if at least one strongly located record is selected by
a saved description proposal for another owner. Falsify only with complete
comparable geometry and no such routed record; otherwise report unresolved
geometry. Ownership here is the saved extractor's assignment, not certified
semantic transaction ownership.

## Classifier and gate trace

Recompute only the frozen value-independent profile and classifier proofs, with
the unchanged tight `Decimal("0.50")` continuation setting, for the aligned row,
merchant-bearing rows, and their directly named proposal owners on the same page.
Require reconstructed selected types to match saved types. Do not invoke the arm's
prediction method, field extraction, or the description probe.

Distinguish zero positive type proofs from conflicting proofs and a unique proof.
Report proof-type counts, existing closed reason codes, occupied roles, and
boolean shape/gap conditions explaining the aligned row's saved classification.
Read the saved probe gate and count description proposals received by the aligned
owner. Do not emit text values, numeric financial values, or raw geometry. A
classification mismatch stops attribution and is reported without changing rules.

## Completion checklist and stop

Use the existing `codex/merchant-gold-seed` branch. A disposable private trace,
invented-input tests for routing and proof categories, and immediate independent
checks may write only under ignored `artifacts/merchant-omission-routing-v1/`.
Reuse existing geometry, renderer/scorer, contracts, profile, and classifier
helpers. Do not build a general tracer, schema family, controller, CLI, or workflow.

- [ ] Commit the approved scope and active phase after repository gates.
- [ ] Observe focused failing invented-input tests, implement the smallest
  diagnostic categories, and pass focused tests, Ruff, and strict mypy.
- [ ] Trace the single omission, reproduce fixed scores/alignment/classification,
  and report routing counts plus the hypothesis result or measured disagreement.
- [ ] Check original inputs unchanged, pass repository gates, publish aggregate
  findings, return live status to STOP, and commit documentation.

The merchant score stays 13/24 and unique-output coverage stays 23/24. Stop after
the fixed trace. No candidate generation, rematching, rule change, reference repair,
new labels, expansion, gold promotion, validation/test access, or production
integration is authorized. Private contents, identities, geometry values, and
financial data remain local and out of tool output and Git.
