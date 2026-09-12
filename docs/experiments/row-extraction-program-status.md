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

## Active phase: STOP

No extraction task is active. The approved primary/continuation merchant assembly
comparison below is complete. Its recommendation to trace the remaining omission
through saved alignment and classification has not been executed or authorized
by the completed comparison.

Next extraction task: STOP.

## Completed phase: merchant primary/continuation assembly

**Status:** `COMPLETE — STOP`. The user's “proceed” on 2026-09-12 approved the
fixed assembly comparison. Authority was committed at `4b9a14a` before candidate
generation under the
[design](../superpowers/specs/2026-09-12-merchant-continuation-assembly-design.md).

The [report](row-extraction-merchant-continuation-assembly-report.md) records
**13/24 exact merchants versus 13/24**, with **zero gains and zero losses**.
Unique-output coverage increases from **22/24 to 23/24**. The ambiguous reviewed
case becomes a single text mismatch; all other 23 reviewed outputs are unchanged.
The exact-accuracy hypothesis is falsified. Digital exact matches remain 10/16
and OCR exact matches remain 3/8.

Across 113 saved owner groups, the candidate assembles three eligible groups and
preserves 110 singletons. All 15 selected atom occurrences in the three assembled
groups are retained. Candidate generation precedes reference access. Labels,
alignment, original predictions, ownership, and billing decisions are unchanged.
The best exact merchant score remains **13/24**; the assembly candidate records
23/24 unique-output coverage without an exact-match improvement.

All 3,766 repository tests and 17 focused tests pass, alongside Ruff and mypy.
Independent score/evidence checks agree and code review found no actionable
defects. No tuning, new extraction, labels, expansion, validation/test access,
or production integration is authorized by this completed comparison.

## Completed phase: residual merchant error analysis

**Status:** `COMPLETE — STOP`. The user's “proceed” on 2026-09-12 approved the
analysis of the remaining 11 non-exact cases. Authority was committed at
`cf781cc` before private measurement under the
[design](../superpowers/specs/2026-09-12-merchant-residual-errors-design.md).

The [report](row-extraction-merchant-residual-errors-report.md) records **nine
in-region text mismatches, one multiple-proposal output, and one omission with
retained alphabetic evidence**. All 35 selected atom occurrences are strongly
supported by both marked regions. The ambiguous case has two supported
primary/continuation proposals with no shared positioned observations; neither
alone is exact. The omission
is gated by ambiguous row type and has four strongly located alphabetic records
in other saved rows. The retained-evidence hypothesis is supported.

Among the nine text mismatches, conditional character error rate is 73/160
(45.625%); one digital case is spacing-only and all other tested text signatures
count zero. Two text cases retain four unselected strongly located owner-row
records. Geometry alone does not certify text or reference correctness.

All 24 scores reproduce and the best merchant diagnostic stays **13/24**.
Predictions, references, alignment, and billing decisions are unchanged.
All 3,766 repository tests and 28 focused tests pass, alongside Ruff and mypy;
independent geometry and edit checks agree. No candidate generation, new labels,
expansion, validation/test access, or production integration is authorized by
this completed analysis.

## Completed phase: merchant comparison before future-billing exclusion

**Status:** `COMPLETE — STOP`. The user's “proceed” on
2026-09-12 approved this fixed merchant comparison. Authority was committed at
`33953e7` before private candidate generation under the
[design](../superpowers/specs/2026-09-12-merchant-prefilter-comparison-design.md).

The [report](row-extraction-merchant-prefilter-comparison-report.md) records
**13/24 exact merchants versus 10/24**, with **three gains and zero losses**.
Candidate alignment covers all 24 references and unique-output coverage rises
from 18/24 to 22/24. The four previously filtered cases yield three exact
merchants and one text mismatch. All 20 previously aligned cases are unchanged.
The positive-net-gain hypothesis is supported on this fixed training seed.

The eight additional rows retain billing exclusion. Original rows, predictions,
references, alignment, and the historical 10/24 score remain unchanged. The best
measured merchant diagnostic is now 13/24; no production or held-out improvement
is claimed. Eleven cases remain non-exact: nine text mismatches, one omission,
and one ambiguous output.

All 3,766 repository tests and eight focused candidate tests pass, alongside
Ruff and mypy. This comparison and its separately approved residual-error
analysis above are complete. No tuning, new labels,
expansion, validation/test access, or production integration is authorized by
this completed comparison.

## Completed phase: merchant discovery exclusion trace

**Status:** `COMPLETE — STOP`. The user's “proceed” on 2026-09-12 approved the
fixed exclusion trace. Authority was committed at `290efb2` before private
execution under the
[design](../superpowers/specs/2026-09-12-merchant-discovery-exclusion-design.md).

The [report](row-extraction-merchant-discovery-exclusion-report.md) attributes
**4/4 exclusions to the explicit future-billing filter**. Initial discovery has
two tables and 46 rows; one eight-row candidate contains the four references
and is filtered, leaving the same 38 final rows. Singleton candidates are also
filtered. The saved discovery object reproduces exactly and the hypothesis is
supported. Independent strict-heading checks agree on both initial tables.

The seed instructions did not restrict printed transactions to current-cycle
billing. Retain all 24 merchant references and the historical 10/24 score; this
finding identifies a comparison-scope mismatch, not incorrect merchant labels.
All 3,766 repository tests, 11 focused attribution tests, and two frozen
future-billing regression cases pass, alongside Ruff and mypy.

This trace and its separately approved merchant comparison above are complete.
No rule change, label repair, expansion, validation/test access, or production
integration is authorized by this completed trace.

## Completed phase: new one-page merchant discovery diagnostic

**Status:** `COMPLETE — STOP`. The user's “proceed” on
2026-09-12 approved one new local diagnostic. Authority was committed at `4d8d1a1`
before source extraction under the
[design](../superpowers/specs/2026-09-12-merchant-page-discovery-design.md).

The [report](row-extraction-merchant-page-discovery-report.md) records native
word/glyph evidence and eligible logical rows for **4/4 regions**, but eligible
discovered rows for **0/4**. The 38 newly discovered row boxes match all 38 frozen
row boxes, with no difference. The recovery hypothesis is falsified and the
coverage gap is localized to logical rows becoming discovered table rows in this
new native-text, one-page diagnostic. That diagnostic alone did not distinguish
intended filtering from a missed transaction region; the trace above resolves
the observed exclusion rule.

No merchant score, label, or match changed; the best comparator remains 10/24.
This diagnostic and its separately approved exclusion trace above are complete.
All 3,766 repository tests and 20 focused diagnostic tests passed, alongside Ruff and mypy. No tuning, new labels, expansion,
validation/test access, or production integration is authorized by this
completed diagnostic.

## Completed phase: merchant discovery coverage trace

**Status:** `COMPLETE — STOP: original snapshot unavailable`. The user's
“proceed” on 2026-09-12 approved tracing original discovery coverage for the one
affected page. Authority was committed at `8675770` before the targeted check
under the [design](../superpowers/specs/2026-09-12-merchant-discovery-coverage-design.md).

The [report](row-extraction-merchant-discovery-coverage-report.md) records **0/1
required original discovery snapshots available**. The historical builder retains
rows, predictions, and crops, but not the full discovery result. Eighteen saved
result files belong to separate control/corpus runs; their payloads were not opened
or substituted. Historical rows lost during freezing are **NOT MEASURED**.

The code copies all discovered table rows without a selection filter, suggesting
an earlier discovery/region limitation; this is an inference, not a historical
row-set measurement. The four references and 38 frozen rows remain unchanged,
and the best measured merchant comparator stays 10/24.

This historical trace remains complete. The separately approved new one-page
diagnostic above does not substitute for its missing original snapshot. No
original reconstruction, labels, expansion, validation/test access, or production
integration is authorized by this completed trace.

## Completed phase: merchant alignment-error diagnosis

**Status:** `COMPLETE — STOP`. The user's “proceed” on 2026-09-12
approved diagnosing four reviewed transactions without matching frozen rows.
Authority was committed at `403eeca` before private measurement under the
[design](../superpowers/specs/2026-09-12-merchant-alignment-errors-design.md).

The [report](row-extraction-merchant-alignment-errors-report.md) records all four
failures as **vertical separation from frozen rows**, with **zero overlapping
transaction or merchant atoms**. The affected digital page has 38 frozen rows and
411 atom records. The retained-evidence hypothesis is falsified. All 24 saved
assignments reproduce, independent coordinate checks agree, and all six review
images have the expected full-page dimensions.

This establishes a gap in frozen evidence under the supplied reference regions;
it does not determine upstream discovery failure versus reference placement.
No match, label, extraction output, or merchant score changed. The best measured
merchant comparator remains 10/24.

This diagnosis and its separately approved discovery coverage trace above are
complete. No new extraction, rematching, labels, expansion, validation/test access,
or production integration is authorized.

## Completed phase: merchant-region OCR experiment

**Status:** `COMPLETE — STOP`. The user's “proceed” on 2026-09-12
approved one merchant-focused local OCR comparison. Authority was committed at
`edff31a` before private recognition; the [design](../superpowers/specs/2026-09-12-merchant-region-ocr-design.md)
fixed extractor-selected atom-union crops, baseline OCR settings, and reading order.

The [report](row-extraction-merchant-region-ocr-report.md) records **8/24 exact
merchants versus 10/24**, with **zero gains and two losses**, both on digital
pages. The positive net-gain hypothesis is falsified. Coverage remains 18/24;
OCR-page exact matches remain 3/8. Of 108 crops, 106 returned text and two were
empty; all 20 proposals associated with reviewed owners returned text.

Retain the deterministic reading-order descriptions at 10/24 as the best measured
comparator. Source inputs, human references, alignment, ownership, and original
transaction decisions were preserved. No OCR tuning or replacement candidate ran.

This comparison and its separately approved alignment-error diagnosis above are
complete. New labels, expansion, validation/test access, and production integration
remain outside their scope.

## Completed phase: merchant reading-order experiment

**Status:** `COMPLETE — STOP`. The user's “proceed” on 2026-09-12
approved one general Hebrew/Latin reading-order rule on the same evidence and all
24 references. Authority was committed at `1b32225` before private execution.

The [design](../superpowers/specs/2026-09-12-merchant-reading-order-design.md)
fixed the geometry/Unicode directional-run permutation. The
[report](row-extraction-merchant-reading-order-report.md) records **10/24 exact
merchants versus 8/24**, with **two gains and zero losses of previously exact
matches**. Both prior word-order cases became exact. Coverage stays 18/24;
digital-page exact matches rose from 5/16 to 7/16 and OCR stayed 3/8.

All 127 predictions preserved their original evidence, ownership, classification,
and transaction decisions; only atom order changed. The hypothesis is supported
on this fixed training seed, with no validation or production accuracy claim.

This experiment and its separately approved merchant-region OCR comparison above
are complete. New labels, expansion, validation/test access, and production
integration remain outside their scope.

## Completed phase: merchant evidence error analysis

**Status:** `COMPLETE — STOP`. The user's “proceed” on 2026-09-12
approved analyzing the ten saved nonmatching merchant descriptions against the
existing human-marked merchant regions.

The [design](../superpowers/specs/2026-09-12-merchant-evidence-error-design.md)
fixed the ten-case selection, evidence-location categories, text signatures, and
character-error measurement. Authority was committed at `a2f24b7` before the
private analysis. No prediction, label, OCR, rendering, alignment, or extraction
rule was changed.

The [report](row-extraction-merchant-evidence-error-report.md) records all 30
selected atoms across ten cases as strongly supported by the human merchant
regions, with no outside, boundary-sensitive, or unusable selected evidence. The
outside-selection hypothesis is falsified. Two digital-page cases have the correct
token multiset in a different order. Spacing/control-character signatures explain
none. Two cases have four additional unselected in-region evidence records, which
are possible omissions rather than confirmed omitted words.

This analysis and its separately approved reading-order experiment above are
complete. New labels, expansion, validation/test access, and production integration
remain outside their scope.

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

This measurement and its separately approved evidence analysis above are complete.
Rule changes, new labels, expansion, validation/test access, and production
integration remain outside their scope.

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
