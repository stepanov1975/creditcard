# Row-Extraction Program Status

**Status:** Binding live record for the row-extraction experiment program.

**Updated:** 2026-09-12

**Authority:** [`AGENTS.md`](../../AGENTS.md), the
[experiment charter](../superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md),
and the
[focus-lock design](../superpowers/specs/2026-07-30-row-extraction-focus-lock-design.md).

Round 1 is frozen at the audited branch heads below. The held-out test remains unopened. No
tracked document, crop, label, output, cache, model artifact, private artifact identity, or
derived financial value is recorded here.

## Active phase: merchant evidence error analysis

**Status:** `AUTHORIZED — NOT YET MEASURED`. The user's “proceed” on 2026-09-12
approved analyzing the ten saved nonmatching merchant descriptions against the
existing human-marked merchant regions.

The [design](../superpowers/specs/2026-09-12-merchant-evidence-error-design.md)
fixes the ten-case selection, evidence-location categories, text signatures, and
character-error measurement. Source-page geometry may be read locally; no new
prediction, label, OCR, rendering, alignment, or extraction-rule change is allowed.
Commit authority before the private analysis.

Next allowed task: run the fixed evidence/text error analysis, publish aggregate
findings, and stop. Historical phases remain completed or stopped.

## Completed phase: merchant proposals before row rejection

**Status:** `COMPLETE — STOP`. The user's “proceed” on 2026-09-12
approved the concrete next measurement from the seed comparison: inspect merchant
proposals before the deterministic method rejects a whole row.

The [design](../superpowers/specs/2026-09-12-merchant-pre-rejection-design.md)
authorized direct invocation of the existing description helper on the same 127
observations, preserving the saved classifications, 24 references, 20/24 alignment,
merchant rules, and original transaction decisions. Authority was committed at
`7470f4d` before the private measurement.

The [report](row-extraction-merchant-pre-rejection-report.md) records 8/24 exact
merchants versus 0/24 in the frozen profile output, with 8 gains and 0 losses.
Unique-description coverage rose from 1/24 to 18/24. All 19 currency-blocked owners
had a description proposal under the unchanged merchant rule; eight matched the
human reference exactly. All original transaction decisions remained unchanged.

This measurement is complete. Its recommended evidence analysis is now separately
approved above. Rule changes, new labels, expansion, validation/test access, and
production integration remain outside that phase.

## Completed phase: merchant seed comparison

**Status:** `COMPLETE — STOP`. On 2026-09-12, the user explicitly approved
comparing existing extraction methods against the 24 reviewed references.
The [comparison design](../superpowers/specs/2026-09-12-merchant-seed-comparison-design.md)
defines the fixed methods, geometry alignment, and merchant metrics. Its authority
was committed at `2bbbd92` before private execution.

The [comparison report](row-extraction-merchant-seed-comparison-report.md) records
OCR at 8/24 exact merchant matches, versus 0/24 for both the stored accepted-parser
evidence projection and frozen profiles: 8 paired gains and 0 losses. Twenty
references matched frozen rows geometrically; four on one digital page did not
meet the predeclared overlap rule. Text and vision were unavailable for the frozen
comparison, not scored as zero. The training-only improvement hypothesis is
supported; this is not a validation win or current production-parser accuracy.

This comparison and its separately approved pre-rejection measurement above are
complete. Gold promotion, new labels, validation/test access, and production
integration remain outside their scope. Historical stopped phases stay stopped.

## Completed phase: human-reviewed merchant gold seed

**Status:** `COMPLETE — STOP` — the user submitted all 24 confirmed seed entries.
The private human-reviewed reference is preserved, with no promotion over existing
gold. The separately approved comparison above is also complete.

The binding [seed design](../superpowers/specs/2026-09-12-merchant-gold-seed-design.md)
authorizes one new training-only source-page sample: six pages from six documents,
two with OCR evidence and four with digital-only evidence, with four transaction
review slots per page. The actual transactions and merchant labels are determined
by the human from complete page evidence. Prior gold, reviewer labels, predictions,
validation, and held-out data remain closed.

The authority amendment was committed before private materialization. All six
selected source PDFs were available and identity-matched; all six complete pages
rendered at 300 DPI. All 24 submitted entries pass the existing answer contract
and contain a human-identified merchant, transaction owner, and valid source
regions. No merchant is marked absent or ambiguous, and no slot is missing.
The 20/24 reference-eligibility hypothesis is supported by the user's review;
independent semantic accuracy and extractor accuracy remain `NOT MEASURED`.

Geometry diagnostics found 7 merchant rectangles intersecting another owner
rectangle, but every merchant region overlaps its own owner more strongly. These
are recorded rectangle relationships, not established semantic errors or a new
rejection gate. The [aggregate seed report](row-extraction-merchant-gold-seed-report.md)
records the findings and the single-reviewer limitation.

The bounded seed preparation/review and comparison are complete. Gold promotion,
further labeling, and production integration remain outside their scope. The
historical phases below remain stopped.

## Frozen Round 1 status

| Lane | Audited branch head | Frozen validation disposition and outcome |
| --- | --- | --- |
| evaluation/controller | `409dbcd7994ba1532fcbe8b165f12ebcc1c37cd4` | Read-only anchor for the completed Round 1 comparison/controller work. |
| OCR | `9bc582c6876d4e2adba7e19cf2ba1968c5ab2625` | `VALIDATION_STOPPED`, `ocr_stage_validation_failed`, zero exact matches, with hallucinated or unsupported fields. |
| deterministic profiles | `a2ed73aa58a4e4d8c76f918657d083fa922537d4` | `FROZEN_ELIGIBLE`, all validation rows abstained, zero exact matches. |
| text | `d573b7f8d5239ca3ff92cbc7bf5475f5ced2ab0a` | `VALIDATION_STOPPED`, `no_text_candidate_met_validation_gate`, single-label supervision cannot represent overlapping evidence ownership, all abstained, zero exact matches. |
| vision | `40f748395c07bb4d2da6658b92087be471681264` | `VALIDATION_STOPPED`, `no_pixel_gain`, zero eligible validation rows under the frozen contract, diagnostic output all abstained, zero exact matches. |

Accepted baseline: zero exact matches with partial acceptance; page-OCR controls abstained. These
are privacy-safe validation outcomes, not held-out measurements and not private-corpus acceptance.

## Stopped phase: merchant context sufficiency

**Status:** `STOP` — the first and only materialization attempt failed atomically before an
independent reference or any extraction arm was created.

The binding design is
[`2026-08-07-merchant-context-sufficiency-design.md`](../superpowers/specs/2026-08-07-merchant-context-sufficiency-design.md).
It reuses exactly the 100 frozen pilot row identities as opaque anchors without using either
reviewer's labels. An independent transaction reference must be frozen from source evidence before
any arm runs. Current gold, accepted parser output, previous reviewer values, experiment
predictions, validation, and held-out data remain closed.

The committed Task 3 implementation selected a unique frozen training population with
`population_count=2503`, `selected_count=100`, and `split=train`. The first and only materialization
attempt stopped with the sanitized error `merchant context geometry unavailable` and left no
private artifact tree. Aggregate read-only diagnosis found 17 materializable anchors and 83
anchors with unavailable geometry.

Visibility failures were 0 for `C0`, `C1`, `C2`, `C3`, and `C5`. For `C4`, 79 anchors failed
visibility because row and atom bounds fell outside the declared detected table region, 4 were
missing required `C2` rows, and 38 were not a superset of `C3`. These categories overlap; their
union is 83 anchors. Continuing would truncate or omit declared context, so the binding
fail-closed stop condition applies.

No independent reference was created. No extraction arm ran, no predictions or error labels were
created, and the scorer invocation count was 0. The merchant-attribution hypothesis result is
`NOT MEASURED`; the smallest best safe context tier and recommended tier are `NOT MEASURED`.

The aggregate report is
[`row-extraction-merchant-context-report.md`](row-extraction-merchant-context-report.md).

```text
Scope: YES — quantified whether the declared nested source contexts could be materialized without truncation for transaction-level merchant attribution
Experiment: shared evaluation
Measurement: transaction-level merchant-attribution accuracy, exact merchant-bearing-text rate, omission rate, wrong-merchant count, hallucination count, ownership-error count, and paired accuracy delta by context tier — NOT MEASURED
Result: Aggregate pre-arm STOP — population_count=2503, selected_count=100, split=train; context-materialization eligibility=17/100, declared-context truncation count=83/100, and geometry unavailable=83/100; no reference, arm, or score was produced, so hypothesis result and smallest/recommended tier are NOT MEASURED
Next extraction task: STOP
```

No reusable controller, CLI family, schema family, receipt chain, workflow subsystem, replacement
pilot, validation run, held-out access, or production integration is authorized.

## Completed visual-gold pilot stop

**Status:** Historical `STOP` — the visual-gold v2 100-row training pilot failed its binding
pre-adjudication field-exact agreement gate.

**Aggregate result:** annotation validity was 100%; row-type agreement was 98/100 (`0.98`) and
passed; field-exact agreement was 386/473 (`0.8160676532769556025369978858`) and failed the
inclusive `0.90` gate. Diagnostic atom-support agreement was 384/414
(`0.9275362318840579710144927536`), and source-region agreement was 376/414
(`0.9082125603864734299516908213`).

The binding stop occurred before adjudication and before current-gold inspection. No labels,
thresholds, prompts, canonicalization, comparison logic, or extractors may be changed to rescue
this pilot, and no replacement pilot or support task may be launched under the current authority.

The pilot remains stopped. The stopped context-sufficiency experiment does not adjudicate, relabel,
rescue, or continue it.

The aggregate pilot report is
[`row-extraction-visual-gold-v2-pilot-report.md`](row-extraction-visual-gold-v2-pilot-report.md).

## Frozen side work

Preserve, but do not continue:

- all four Round 1 lane implementations, configurations, handoffs, and artifacts at the audited
  heads above;
- locked-comparison controller or CLI architecture and provenance-envelope or handoff re-freezing
  work;
- receipts, replay prevention, attestations, and path/inode/cache-independence machinery;
- marker-first or other locked-input projection features;
- cascade execution and locked-test orchestration, including charter Stages 4-6;
- private-corpus controller redesign and repository acceptance-gate work; and
- production integration or integration design.

Historical branches, plans, runbooks, and artifacts are read-only evidence. An unchecked task or
an existing implementation does not reactivate it. An infrastructure exception requires direct
user approval followed by a committed charter amendment.

The repository private-corpus acceptance policy is a separate production acceptance gate. It is
not an experiment task, extraction measurement, or substitute for the Metric-or-Stop Rule.
