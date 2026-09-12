# Merchant Proposals Before Row Rejection

**Status:** Approved by the user's “proceed” on 2026-09-12 in response to the
concrete recommendation to measure merchant extraction before whole-row rejection.
Commit this design and charter amendment before the private measurement.

```text
Scope answer: YES — measures merchant evidence hidden by deterministic row rejection
Experiment: row-profiles
Extraction hypothesis: Evaluating the existing description rule before financial-field rejection exposes at least one additional exact merchant match on the fixed seed
Measurement: pre-rejection merchant exact matches, proposal coverage, omissions, ambiguity, and paired gains/losses against frozen profile output
Fixed inputs: the same 24 human references, frozen 20/24 row alignment, 127 selected-page observations, and tight-profile classification
Smallest allowed files: docs/superpowers/specs/2026-09-12-merchant-pre-rejection-design.md; docs/superpowers/plans/2026-09-12-merchant-pre-rejection.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-pre-rejection-report.md; artifacts/merchant-pre-rejection-v1/**
Required output: exact-match and coverage deltas, with counts of merchant proposals hidden by row rejection
Stop condition: stop after this diagnostic measurement; do not alter extraction rules, accepted transactions, labels, alignment, or sample size
```

## Fixed probe

The [previous comparison](../../experiments/row-extraction-merchant-seed-comparison-report.md)
found that 19 of 20 matched profile owner rows abstained because of nonunique
currency evidence, and one because of ambiguous row type. It did not establish
whether bypassing the financial early exits would expose correct merchant text.

Use the unmodified deterministic checkout at
`a2ed73aa58a4e4d8c76f918657d083fa922537d4`. Reuse the prior private comparison's
127 `FrozenRow` observations and corresponding `tight` profile predictions. The
stored predicted types preserve the original classification and configuration.
Reuse the prior 24 references and saved alignment exactly, including its four
failures. Do not rematch regions, reopen source pages, rerun OCR, or read old gold.

For a primary transaction or continuation, call the existing `_description_atoms`
rule directly, before any whole-row financial validation. Keep its column choice,
typed-residual filtering, ambiguity handling, and atom order unchanged. Use its
existing `_proposal` helper and evidence renderer. A primary owns its proposal;
a continuation retains `previous_row_id` ownership and remains unavailable if
that owner is missing. Structural and ambiguous row classifications remain
ineligible. The probe does not relax classification or merchant-specific rules.

Preserve every original prediction decision and reason. Store any observed
description proposal as diagnostic evidence on a separate private record; do not
convert an abstention into an accepted transaction. The diagnostic scorer can
inspect these proposals regardless of the original financial decision, whereas
the control uses the original accepted-proposal scorer. Both use identical text
rendering and owner aggregation. Multiple proposals for one owner remain ambiguous;
do not concatenate, deduplicate, or select a proposal using reference text.

Reference text and human regions never enter the proposal probe. Only the scorer
reads the unchanged merchant references. No alias mapping, reversal, trimming,
case folding, spelling repair, or new merchant extraction rule is authorized.

## Measurements

Reuse the previous exact-match rule (NFC and collapsed Unicode whitespace only),
case categories, fixed 24-case denominator, and aligned 20-case denominator.
Report exact matches, unique-proposal coverage, omissions, ambiguous outputs,
extra-text/partial-text/other mismatches, and paired gains/losses versus the
unchanged profile control. Report OCR-page and digital-page slices separately.

Also count pre-rejection description availability or rejection reasons on the
20 matched owner rows, especially the fixed 19 currency-blocked owners. Distinguish
availability on an owner row from the final aggregate for that owner: a continuation
can contribute another proposal and make the aggregate ambiguous.

The hypothesis is supported only by a strictly positive net exact-match count.
Greater proposal coverage alone is not merchant accuracy. A nonpositive delta
falsifies the hypothesis for this seed; unavailable required inputs yield a
quantified eligibility failure and no accuracy verdict. Do not tune after scoring.

## Execution boundary

This is a read-only diagnostic invocation of an existing extraction rule. A small
private probe and invented-input tests may live under ignored
`artifacts/merchant-pre-rejection-v1/`. Reuse the existing local scoring functions;
do not build an alternate scorer, shared framework, controller, CLI, or schema family.
All private evidence and results remain local; no private text or pixels enter
model tools, external services, or Git. No production or historical source file
changes are needed.

Test that a financial rejection can retain a diagnostic merchant proposal without
changing its decision, that continuation ownership is preserved, and that ambiguous
descriptions, ambiguous row types, and missing owners remain unresolved. Verify
atom order and multiple-proposal ambiguity. Run the focused tests before the
private measurement and all four repository gates before tracked commits.

Publish aggregates and return the phase to `STOP`. This diagnostic seed cannot
select a production change, promote gold, authorize sample expansion, or open
validation/test data. A result may recommend one separately scoped next task.
