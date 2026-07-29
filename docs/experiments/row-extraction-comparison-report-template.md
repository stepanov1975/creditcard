# Row-extraction comparison report template

This tracked file defines the privacy-safe shape of a comparison report. Populate a copy only
in an ignored private location. Do not add document names or identities, row text, merchant
text, dates, amounts, currencies, source paths, per-document values, private aggregate values,
or artifact digests to this file.

## Run identity and completeness

Record the reviewed comparison identity, full foundation revision, locked row-sequence
identity, gold-label identity, optional OCR-reference identity, measurement protocol, runtime
identity per arm, worker count, and report-generation revision in the private copy. Require the
seven fixed result IDs: accepted baseline, conditional page OCR, forced page OCR, row OCR, row
profiles, row text, and row vision.

| Result ID | Config ID | Result basis | Lane disposition | Closed stop reason | Metrics identity | Prediction identity | Error identity |
| --- | --- | --- | --- | --- | --- | --- | --- |

A validation-stopped lane remains in every applicable accuracy, completeness, and error table
with `validation_stop` as its result basis. It has no locked-test interval, locked-test resource
claim, Pareto membership, cascade eligibility, or production-winner eligibility. Never replace
its preserved validation measurements with zeros or locked-test placeholders.

## Exact rows and merchant extraction

| Result ID | Basis | Rows | Exact rows | Exact-row rate | Merchant eligible | Merchant exact | Merchant exact rate | Merchant normalized | Merchant normalized rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

The accepted baseline must appear in this table and every accuracy/error table. Merchant is
the `description` field role under the versioned normalization policy; normalized agreement
does not replace exact agreement.

## Typed fields, omissions, and hallucinations

Emit one row for every result ID and every closed field role: transaction date, posting date,
conversion date, description, billed amount, billing currency, original amount, original
currency, kind, installment, FX rate, and ancillary.

| Result ID | Basis | Field role | Eligible rows | Exact matches | Exact rate | Normalized matches | Normalized rate | Omissions | Omission rate | Hallucinations | Hallucination rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

Do not merge omissions with hallucinations. Also report unsupported evidence and ownership
collisions separately; neither is an alias for a wrong typed value.

| Result ID | Basis | Accepted rows | Abstained rows | Rejected rows | Ignored rows | Unsupported evidence | Ownership collisions |
| --- | --- | --- | --- | --- | --- | --- | --- |

## OCR error

| Result ID | Basis | Reviewed OCR-reference coverage | Character error rate | Word error rate | Limitation code |
| --- | --- | --- | --- | --- | --- |

OCR character and word error rates are present only when reviewed OCR references cover the
applicable locked or validation observations. Mark unavailable evidence explicitly; never use
zero as an unavailable value.

## Calibration, abstention, and risk coverage

| Result ID | Basis | Brier score | Log loss | Expected calibration error | Area under risk-coverage | Accepted coverage | Selective risk |
| --- | --- | --- | --- | --- | --- | --- | --- |

| Result ID | Basis | Calibration-bin lower | Calibration-bin upper | Bin count | Mean confidence | Empirical exact-row accuracy |
| --- | --- | --- | --- | --- | --- | --- |

| Result ID | Basis | Confidence threshold | Coverage | Selective risk | Accepted rows |
| --- | --- | --- | --- | --- | --- |

| Result ID | Basis | Predeclared target risk | Coverage at target risk |
| --- | --- | --- | --- |

Confidence is for the event that the complete emitted row is exactly correct. Preserve the
full reliability bins, full tie-grouped risk-coverage curve, and every predeclared target-risk
coverage point. Do not substitute OCR confidence, token scores, or a single chosen threshold.

## Row types and closed error taxonomy

| Result ID | Basis | Row type | Precision | Recall | F1 | Support |
| --- | --- | --- | --- | --- | --- | --- |

| Result ID | Basis | Gold row type | Predicted row type | Count |
| --- | --- | --- | --- | --- |

| Result ID | Basis | Error category | Primary count | Secondary count |
| --- | --- | --- | --- | --- |

Emit every cell of the closed row-type confusion matrix and every category in the frozen error
taxonomy, including zero-count cells. The error table must distinguish primary from secondary
assignments and remain bound to its reviewed error artifact identity. Do not add categories
after locked results are opened.

## Paired document-level effects

| Result ID | Comparison control | Metric | Document-macro effect | Interval low | Interval high | Bootstrap samples | Result basis |
| --- | --- | --- | --- | --- | --- | --- | --- |

Use the accepted baseline as the fixed paired control and resample complete documents, never
individual rows. Report the deterministic sample count and practical effect alongside the
interval. Validation-stopped lanes have no locked interval.

## Resources and determinism

Keep preparation, fixed-row execution, and end-to-end method cost in separately named columns.
Never place a page adapter's extraction-only time and row OCR's end-to-end time under the same
latency label.

| Result ID | Resource basis | Preparation ns | Fixed-row total ns | End-to-end ns | Cold-start ns | Row p50 ns | Row p95 ns | Throughput rows/s | Process-tree peak RSS bytes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

| Result ID | Resource basis | Model bytes | Dependency bytes | Cache bytes | Subprocess count | Worker count | Measurement protocol | Runtime identity | Arm identity | Model inventory identity | Dependency inventory identity | Resource inventory identity |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

| Result ID | First prediction identity | Repeat prediction identity | Byte-identical predictions | First resource inventory identity | Repeat resource inventory identity | Distinct regular inventory outputs | Distinct empty-cache roots |
| --- | --- | --- | --- | --- | --- | --- | --- |

Model, dependency, and cache bytes are disjoint inventories and must not be collapsed into an
unlabeled size. The accepted baseline is labeled `materialized-adapter`: its replay numbers do
not represent production extraction cost and it is excluded from all resource-dominance and
Pareto statements. Only `end-to-end-method` locked results with byte-identical predictions may
enter resource Pareto comparison. Validation-stopped results have no locked resource row.
First and repeat resource-inventory content identities may be equal: deterministic resource
sets can produce identical canonical bytes. Independence is instead proved by distinct regular
inventory output paths and distinct empty-cache roots, with each output's bytes validated
against that run's measured inventory identity. Reusing either output path or cache root is a
fail-closed comparison error.

Accepted baseline uses `locked-materialized-input`: its locked measurement is bound to the
canonical, exact ordered prediction stream for the locked row universe, never the validation
prediction stream. Frozen row-lane measurements remain bound to their validated fixed arm
manifest. Conditional and forced page OCR use `locked-page-preparation`: each locked run is
bound to canonical page-evidence JSONL generated for exactly the locked document/page universe,
never validation-split page evidence. The two locked preparations must have identical content
identities from distinct cache entries, and each identity must occur in its run's verified
resource inventory.

## Pareto report

| Result ID | Locked and eligible | Deterministic | End-to-end resource basis | Exact rows | Merchant exact | Wrong required fields | Hallucinations | Coverage | Selective risk | Risk-target coverage | End-to-end latency | Peak RSS | Model bytes | Pareto member |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

Dominance uses only the predeclared axes shown above: more exact rows, merchant matches,
coverage, and target-risk coverage; fewer wrong required fields and hallucinations; lower
selective risk, area under risk-coverage, phase-matched end-to-end latency, process-tree peak
RSS, and model bytes; and deterministic output. Report tradeoffs directly. Do not calculate or
publish an unreviewed weighted score.

`Wrong required fields` counts only the primary-row roles declared required by the annotation
contract: billed amount, billing currency, and kind. Optional or ancillary field errors remain
fully visible in typed-field metrics, omissions, and hallucinations, but do not alter this
Pareto axis.

## Required limitations and decision boundary

The private report must state all applicable limitations:

- which results are locked-test measurements and which preserve validation-stop evidence;
- that stopped lanes were never opened on locked rows and cannot be production winners;
- that accepted-baseline resources are materialized-adapter measurements and are not
  extraction-cost or Pareto claims;
- any unavailable reviewed OCR reference evidence;
- any privacy-unsafe or insufficiently supported slice omitted from the report;
- that intervals resample documents and do not establish corpus-wide acceptance;
- that resource comparisons require the same measurement protocol, one-worker policy,
  new-empty cache policy, phase definition, row sequence, and identity-bound
  runtime/inventories;
- that prediction determinism requires byte-identical canonical first/repeat artifacts from
  independent empty-cache/resource outputs; and
- that a comparison report does not authorize production integration. Recommendation and any
  cascade design remain separate, closed consumers of the validated comparison.

Do not claim full-corpus acceptance from this report or tracked tests. The private corpus gate
and its independent pins, deterministic runs, toolchain checks, and performance checks remain
separate requirements.
