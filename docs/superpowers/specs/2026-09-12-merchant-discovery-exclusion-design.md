# Merchant Discovery Exclusion Trace

**Status:** Approved by the user's “proceed” on 2026-09-12 following the concrete
recommendation to trace the exclusion rule for the four fixed reference regions.
Commit this authority before private execution.

```text
Scope answer: YES — quantifies the discovery decisions excluding four fixed transaction-reference regions
Experiment: shared evaluation
Extraction hypothesis: At least one unmatched reference is covered by a candidate table removed by an explicit future-billing or transaction-history filter
Measurement: reference coverage before and after discovery filters, with exclusion-rule case counts
Fixed inputs: saved one-page native evidence, logical rows and discovery, four unchanged training references, and the frozen deterministic checkout
Smallest allowed files: docs/superpowers/specs/2026-09-12-merchant-discovery-exclusion-design.md; docs/superpowers/plans/2026-09-12-merchant-discovery-exclusion.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-discovery-exclusion-report.md; artifacts/merchant-discovery-exclusion-v1/**
Required output: supported or falsified filter hypothesis and quantified exclusion decisions or unresolved cases
Stop condition: stop after one unchanged discovery trace and analysis of its saved decisions; no rule changes, alternate runs, or support subsystem
```

## Fixed diagnostic

Use the already saved one-page native evidence, 81 logical rows, and 38 discovered
rows from `artifacts/merchant-page-discovery-v1/`, and the unchanged four unmatched
training references. Use the frozen deterministic checkout at
`a2ed73aa58a4e4d8c76f918657d083fa922537d4`. No PDF reading, text extraction,
rendering, OCR, other-page evidence, normalization, or model calls are needed.

Execute the unchanged discovery function once on the saved evidence with a
process-local observer of existing function returns. Observe initial candidate
regions, header and inherited-region scan outcomes, their explicit stop calls,
future-billing predicates, singleton candidates, and the transaction-history
predicate. Do not patch returns, change arguments, edit historical code, or feed
references into discovery. Require the resulting discovery object to equal the
saved one-page result before attributing any decisions.

Measure each reference using the existing geometric eligibility rule. Record
coverage in initial candidate regions, candidates marked as future billing,
singletons, and final discovered rows. A reference has evidence of explicit
semantic filtering only if it overlaps a candidate on which that filter fired;
a page-level predicate alone is insufficient. The hypothesis is supported if at
least one of four meets this criterion, otherwise falsified when the trace is
complete and reproduces the saved output.

If coverage is already absent before semantic filtering, measure accepted rows
in rejected scans, scans stopping on an eligible target row, and unrecognized
header attempts on target rows. Preserve the exact existing stop reason and
source-code decision site privately. Do not infer a missing header solely from
an arbitrary nearest preceding row. Retain unresolved cases where the observation
does not establish a specific cause.

Predeclared categories: explicit future-billing filtering; transaction-history
filtering of an overlapping candidate; singleton candidate not attached;
accepted rows in an insufficient scan; scan stopped on a target row; initial
candidate absent without an attributable stop; initial candidate missing from
final output for an unresolved reason; and unexpectedly retained final coverage.
These describe observed extractor decisions, not independently verified semantic
truth. Distinguish evidence for an intended rule from proof that the rule or
human target is correct. Do not silently change references or their eligibility.

## Minimal implementation and boundary

Only a disposable local observer, case-count analysis, and invented-input tests
under ignored `artifacts/merchant-discovery-exclusion-v1/` may be added. Test the
case attribution before implementation, including a filter firing on unrelated
regions and unresolved outcomes. Reuse existing models and overlap functions.
This allowance creates no shared controller, schema, CLI, tracing library,
provenance subsystem, or reusable workflow.

Keep all private contents, coordinates, identities, and financial values local
and out of Git and tool output. Publish aggregate counts and general code rules
only. Check original artifacts, references, alignment, and merchant scores remain
unchanged. Run the four required repository checks before tracked commits.

Stop after the single trace and its attribution, even if cases remain unresolved.
No tuning, rule fix, counterfactual extraction, rematching, reference correction,
new labels, sample expansion, gold promotion, validation/test access, or production
integration is authorized. The 10/24 merchant comparator is unchanged.
