# Row Extraction Comparison and Cascade Implementation Plan

> **SUSPENDED — HISTORICAL ONLY.** Unchecked tasks in this plan are historical records, not
> authorized work. Task 6 and marker-first projection are not authorized. Controller commit
> `409dbcd7994ba1532fcbe8b165f12ebcc1c37cd4` is preserved read-only. Only a user-approved
> charter amendment can reactivate locked comparison work; see the
> [focus-lock authority](../specs/2026-07-30-row-extraction-focus-lock-design.md) and
> [live program status](../../experiments/row-extraction-program-status.md).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compare the accepted baselines and all four required experiment dispositions fairly,
run every frozen-eligible lane on locked data, preserve every validation-stopped result in the
error analysis, and evaluate a validation-selected abstention-first cascade without creating
a fifth experiment.

**Architecture:** A comparison package validates lane handoffs against the frozen foundation, joins predictions by fixed document/row identity, computes common metrics and paired document-level uncertainty, and generates private detailed plus privacy-safe aggregate reports. A separate cascade consumes only already-frozen predictions, applies a validation-frozen evidence/confidence policy, and uses reconciliation only as terminal rejection. Production `src/` remains read-only.

**Tech Stack:** Python 3.13, shared Pydantic contracts/codecs/metrics/runner, `Decimal`, pytest, Ruff, and mypy; no new model runtime.

## Global Constraints

- Before every task, complete the charter scope block with comparison or cascade and a named metric/invariant.
- This plan starts only after the shared foundation and all four experiment lanes have clean committed handoffs, each marked frozen-eligible or validation-stopped.
- The four required experiment IDs are `row-ocr`, `row-profiles`, `row-text`, and `row-vision`; a missing lane is a hard failure, while a typed validation stop remains a required reported disposition.
- Accepted and whole-page OCR controls are baselines, and the cascade is comparison infrastructure; none is a fifth experiment.
- Consume immutable fixed rows, gold labels, splits, metrics, lane configurations, artifacts, and predictions; do not retune any lane.
- Do not open locked-test metrics until all four lane dispositions, applicable configurations/calibrators/thresholds/runtime identities, and validation predictions are frozen.
- Resample and aggregate by document, never treating rows as independent uncertainty units.
- Compare financial amounts with `Decimal`; do not average field correctness into a misleading easy-field score.
- Every accepted cascade field must have exact evidence atoms and pass shared deterministic validation.
- Reconciliation may only reject the cascade result; it may not rank, select, add, remove, or repair candidates.
- Detailed reports remain private and ignored. Tracked code/tests/templates contain synthetic data only.
- Production `src/` is read-only. A measured recommendation may propose a later integration design but cannot implement one.
- Do not introduce another model, OCR engine, row detector, security/controller task, private-gate redesign, or release/toolchain work.

Before every commit in this plan, run this exact gate in addition to the task's focused RED/GREEN commands:

```bash
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/mypy experiments/row_extraction/comparison
/root/creditcard/.venv/bin/pytest -q
/root/creditcard/.venv/bin/pytest -q --ignore=tests/test_corpus_gate.py
```

Ruff, both mypy runs, and the extraction-relevant pytest run must pass. The full suite must
either pass after an upstream fix or reproduce exactly the established five inherited
out-of-scope sandbox/controller failures. Any new or changed failure stops the task.

---

## File Structure

- `experiments/row_extraction/comparison/__init__.py`: exports handoff, comparison, and cascade interfaces.
- `experiments/row_extraction/comparison/handoffs.py`: exact foundation/lane artifact and row-universe validation.
- `experiments/row_extraction/comparison/statistics.py`: paired document bootstrap and confidence intervals.
- `experiments/row_extraction/comparison/errors.py`: frozen error-taxonomy assignment and disagreements.
- `experiments/row_extraction/comparison/compare.py`: baseline/four-lane metric table and Pareto analysis.
- `experiments/row_extraction/comparison/cascade.py`: validation-selected fail-closed cascade policy.
- `experiments/row_extraction/comparison/recommend.py`: evidence-backed winner/no-change decision record.
- `experiments/row_extraction/comparison/cli.py`: private handoff validation, comparison, cascade, and report commands.
- `docs/experiments/row-extraction-comparison-runbook.md`: exact execution order and privacy rules.
- `docs/experiments/row-extraction-comparison-report-template.md`: required report sections without private values.
- `tests/experiments/row_extraction/comparison/`: focused synthetic tests.

### Task 1: Validate the complete baseline/four-experiment handoff

```text
Scope answer: YES
Program component: comparison
Measured effect: every result is scored on the identical locked row universe with the frozen foundation and no missing experiment
Fixed inputs: foundation identity, split/label/bundle identities, accepted baselines, four lane handoffs
Allowed files: comparison handoff validator and tests
Stop condition: stop on any identity, row-universe, split, runtime, artifact, or lane mismatch
```

**Files:**
- Create: `experiments/row_extraction/comparison/__init__.py`
- Create: `experiments/row_extraction/comparison/handoffs.py`
- Create: `tests/experiments/row_extraction/comparison/__init__.py`
- Test: `tests/experiments/row_extraction/comparison/test_handoffs.py`

**Interfaces:**
- Consumes: `ComparisonManifest`, baseline and lane `ArtifactIdentity` values, frozen
  validation-prediction JSONL paths, exact factory loaders, runtime identities, disjoint
  model/dependency inventories, worker/cache policies, and the locked fixed-row ID set without
  labels.
- Produces: `FrozenRunInputs(arm_manifest, runtime_identity, model_inventory,
  dependency_inventory, worker_count, factory_loader)`,
  `ValidatedHandoffs(foundation_sha: str, dispositions: Mapping[str, LaneDisposition],
  run_inputs: Mapping[str, FrozenRunInputs], validation_predictions: Mapping[str, Path],
  locked_row_ids: frozenset[tuple[str, str]])`, and
  `validate_handoffs(manifest: ComparisonManifest) -> ValidatedHandoffs`, using the shared
  `LaneDisposition.FROZEN_ELIGIBLE` and `LaneDisposition.VALIDATION_STOPPED` values rather than
  a comparison-local status enum.

- [ ] **Step 1: Write failing missing-lane and row-universe tests**

```python
def test_handoff_requires_exactly_four_experiment_ids(tmp_path: Path) -> None:
    manifest = comparison_manifest(tmp_path, experiment_ids=("row-ocr", "row-text"))
    with pytest.raises(HandoffError, match="missing required experiment handoff"):
        validate_handoffs(manifest)


def test_handoff_rejects_one_extra_or_missing_validation_row(tmp_path: Path) -> None:
    manifest = comparison_manifest_with_validation_row_mismatch(tmp_path)
    with pytest.raises(HandoffError, match="validation prediction row universe mismatch"):
        validate_handoffs(manifest)
```

- [ ] **Step 2: Run the handoff tests to verify RED**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/comparison/test_handoffs.py`

Expected: collection fails because `handoffs.py` does not exist.

- [ ] **Step 3: Implement closed identity validation**

Require exactly the public baseline IDs and four charter experiment IDs, one typed disposition
per lane, one frozen config for every eligible lane, matching foundation/bundle/split/label
SHA fields, matching public runtime identity,
complete unique validation row IDs, an untouched locked-row identity set, and canonical file
hashes matching the manifest. Require each lane's typed frozen-arm loader to reproduce its
validation prediction digest before it is eligible for the central run. Reject unknown
experiment IDs instead of ignoring them. A validation-stopped lane must carry its exact
predeclared stop reason and complete validation metrics; it has no locked arm manifest. Return
paths and opaque IDs only; never read field values into error messages. No locked prediction
exists yet at this stage.

For every baseline and frozen-eligible lane, verify that the factory's experiment/config/arm
identity matches the handoff, the model/dependency inventories are canonical and disjoint, the
runtime is exact, and `worker_count=1`. A validation-stopped lane has no loadable run inputs.

- [ ] **Step 4: Run handoff tests and mypy**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/comparison/test_handoffs.py`

Expected: PASS.

Run: `/root/creditcard/.venv/bin/mypy experiments/row_extraction/comparison/handoffs.py`

Expected: `Success: no issues found`.

- [ ] **Step 5: Commit handoff validation**

```bash
git add experiments/row_extraction/comparison/__init__.py \
  experiments/row_extraction/comparison/handoffs.py \
  tests/experiments/row_extraction/comparison/__init__.py \
  tests/experiments/row_extraction/comparison/test_handoffs.py
git commit -m "feat: validate row experiment handoffs"
```

### Task 2: Compute paired document-level uncertainty and frozen error categories

```text
Scope answer: YES
Program component: comparison
Measured effect: comparative exactness and error claims include document-level uncertainty and one stable cause taxonomy
Fixed inputs: common MetricReport outputs and charter error taxonomy
Allowed files: statistics/error modules and tests
Stop condition: stop if a calculation resamples rows independently or adds post-test categories to favor a lane
```

**Files:**
- Create: `experiments/row_extraction/comparison/statistics.py`
- Create: `experiments/row_extraction/comparison/errors.py`
- Test: `tests/experiments/row_extraction/comparison/test_statistics.py`
- Test: `tests/experiments/row_extraction/comparison/test_errors.py`

**Interfaces:**
- Consumes: per-document exact metric contributions, gold rows, and predictions.
- Produces: `PairedInterval(effect: Decimal, low: Decimal, high: Decimal, samples: int)`, `paired_document_bootstrap(first, second, seed, samples)`, `ErrorCategory`, `ErrorAssignment`, and `classify_error(gold: GoldRow, prediction: RowPrediction) -> ErrorAssignment`.

- [ ] **Step 1: Write failing document-bootstrap and taxonomy tests**

```python
def test_paired_bootstrap_samples_complete_documents() -> None:
    interval = paired_document_bootstrap(
        first={"doc-a": Decimal("1"), "doc-b": Decimal("0")},
        second={"doc-a": Decimal("0"), "doc-b": Decimal("0")},
        seed="comparison-v1",
        samples=1000,
    )
    assert interval.effect == Decimal("0.5")
    assert interval.samples == 1000


def test_extra_accepted_description_is_hallucination() -> None:
    assignment = classify_error(
        gold_row_without_description(),
        accepted_description_prediction(),
    )
    assert assignment.primary is ErrorCategory.UNSUPPORTED_FIELD_HALLUCINATION
```

- [ ] **Step 2: Run the tests to verify RED**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/comparison/test_statistics.py tests/experiments/row_extraction/comparison/test_errors.py`

Expected: collection fails because `statistics.py` and `errors.py` do not exist.

- [ ] **Step 3: Implement deterministic paired bootstrap and closed taxonomy**

Use `random.Random(sha256(seed).digest())`, sample document IDs with replacement, compute
paired document-macro effects with `Decimal`, sort samples, and select predeclared percentile
indices. The error classifier follows the charter priority: annotation ambiguity; evidence
contract; row type; OCR edit/segmentation; crop/box/column; continuation ownership; merchant
span; date; amount/sign/kind/currency; optional field; calibration false accept; correct
abstention. Return stable reason codes without values.

- [ ] **Step 4: Run statistics and error tests twice**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/comparison/test_statistics.py tests/experiments/row_extraction/comparison/test_errors.py`

Expected: PASS and byte-identical serialized intervals/assignments on repetition.

- [ ] **Step 5: Commit uncertainty and errors**

```bash
git add experiments/row_extraction/comparison/statistics.py \
  experiments/row_extraction/comparison/errors.py \
  tests/experiments/row_extraction/comparison/test_statistics.py \
  tests/experiments/row_extraction/comparison/test_errors.py
git commit -m "feat: compare row experiments by document"
```

### Task 3: Build the common comparison and Pareto report

```text
Scope answer: YES
Program component: comparison
Measured effect: all required exactness, calibration, abstention, latency, memory, size, determinism, row-type, and error metrics are visible side by side
Fixed inputs: validated handoffs, common metrics, paired intervals, frozen error taxonomy
Allowed files: comparison module, report template, and tests
Stop condition: stop if a summary hides a required field regression, lane disposition, or privacy-unsafe slice
```

**Files:**
- Create: `experiments/row_extraction/comparison/compare.py`
- Create: `docs/experiments/row-extraction-comparison-report-template.md`
- Test: `tests/experiments/row_extraction/comparison/test_compare.py`

**Interfaces:**
- Consumes: `ValidatedHandoffs`, typed `LockedResultSet`, gold JSONL, and optional reviewed
  OCR-reference JSONL.
- Produces: `LockedArmResult(experiment_id, config_id, predictions_path,
  predictions_identity, measurements: RunMeasurements, repeat_predictions_path,
  repeat_predictions_identity, repeat_measurements: RunMeasurements,
  error_assignments_path, error_assignments_identity)`,
  `LockedResultSet(rows_path, row_sequence_identity,
  results: Mapping[str, LockedArmResult])`, `ResultBasis(LOCKED_TEST, VALIDATION_STOP)`,
  `ExperimentResult`, `ComparisonReport`, `compare_handoffs(handoffs, locked_results, gold,
  ocr_references=()) -> ComparisonReport`, and
  `pareto_front(results: Sequence[ExperimentResult]) -> tuple[str, ...]`.

- [ ] **Step 1: Write a failing complete-report test**

```python
def test_comparison_requires_every_metric_family_and_lane() -> None:
    report = compare_handoffs(
        validated_synthetic_handoffs(), synthetic_locked_results(), synthetic_gold()
    )
    assert set(report.experiment_ids) == {
        "accepted-baseline",
        "conditional-page-ocr",
        "forced-page-ocr",
        "row-ocr",
        "row-profiles",
        "row-text",
        "row-vision",
    }
    assert report.required_metric_families == (
        "row_exact",
        "merchant",
        "typed_fields",
        "omission_hallucination",
        "ocr_error",
        "calibration_abstention",
        "resources_determinism",
        "row_type_errors",
    )
```

- [ ] **Step 2: Run the comparison test to verify RED**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/comparison/test_compare.py`

Expected: collection fails because `compare.py` does not exist.

- [ ] **Step 3: Implement full metric preservation and Pareto dominance**

Compute each arm through shared `score_predictions`; attach document-macro paired intervals;
include every required field role separately; report omissions and hallucinations separately;
include full risk-coverage and resource values; and include error-category counts. Resource
comparison must preserve `preparation_ns`, fixed-row `total_ns`, `end_to_end_ns`, cold start,
p50/p95, throughput, process-tree peak RSS, disjoint model/dependency/cache bytes, subprocess
and worker counts, measurement protocol, runtime identity, and prediction determinism. Never
compare a page adapter's extraction-only time with row OCR's end-to-end time under one latency
label. Define Pareto dominance only across predeclared axes: more exact rows/merchant
matches/coverage, fewer wrong required fields/hallucinations, lower selective risk, lower
phase-matched latency/RSS/model bytes, and deterministic output. Do not collapse axes to one
unreviewed weighted score.

The accepted control remains in every accuracy/error table, but its resource basis is the
materialized prediction adapter rather than the production extraction phase. Label those
numbers explicitly and exclude accepted-baseline from every resource-dominance statement and
Pareto axis. Only results with `resource_basis="end-to-end-method"` may be compared on resource
axes.

Every `ExperimentResult` records its `ResultBasis`. A validation-stopped lane retains its
validation metrics and stop reason, has no locked interval, is excluded from the locked Pareto
front/cascade, and cannot be recommended as a production winner. It remains visible in all
completeness/error tables so a stopped experiment is never mistaken for a missing one.

`compare_handoffs` requires one locked result for all three baselines and every frozen-eligible
lane, none for validation-stopped lanes, and no unknown result. It verifies the locked row-
sequence identity against every `RunMeasurements`, prediction identity, experiment/config,
runtime/arm/model/dependency binding, byte-identical repeat identity, distinct cache/resource
inventory outputs, and error-assignment identity before scoring. Reopen the fixed
row stream per result; never reuse an exhausted iterator.

The tracked report template lists every table and required limitation but contains no private
counts or values.

- [ ] **Step 4: Run comparison and common metric tests**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/comparison/test_compare.py tests/experiments/row_extraction/test_metrics.py`

Expected: PASS.

- [ ] **Step 5: Commit common comparison behavior**

```bash
git add experiments/row_extraction/comparison/compare.py \
  docs/experiments/row-extraction-comparison-report-template.md \
  tests/experiments/row_extraction/comparison/test_compare.py
git commit -m "feat: report row experiment comparison"
```

### Task 4: Select and freeze an abstention-first cascade on validation data

```text
Scope answer: YES
Program component: cascade
Measured effect: incremental exact coverage at fixed or lower accepted-row error risk without hallucinated fields
Fixed inputs: frozen validation predictions from baselines and four lane handoffs; no lane retraining
Allowed files: cascade policy and tests
Stop condition: stop on locked-test access, unsupported evidence, uncalibrated learned output, or reconciliation-based candidate selection
```

**Files:**
- Create: `experiments/row_extraction/comparison/cascade.py`
- Test: `tests/experiments/row_extraction/comparison/test_cascade.py`

**Interfaces:**
- Consumes: row-aligned frozen validation predictions, baseline exactness state, shared evidence validator, and validation exact-row outcomes.
- Produces: `CascadeRule(arm_id: str, minimum_confidence: Decimal, requires_agreement: tuple[str, ...])`, `CascadePolicy(version: str, rules: tuple[CascadeRule, ...])`, `select_cascade_policy(validation) -> CascadePolicy`, and `apply_cascade(policy, candidates) -> RowPrediction`.

- [ ] **Step 1: Write failing preservation, grounding, and abstention tests**

```python
def test_cascade_preserves_exact_unambiguous_baseline() -> None:
    result = apply_cascade(policy(), candidates_with_exact_baseline())
    assert result.experiment_id == "accepted-baseline"


def test_cascade_rejects_high_confidence_missing_evidence() -> None:
    result = apply_cascade(policy(), candidates_with_missing_evidence())
    assert result.decision is Decision.ABSTAIN
    assert result.reasons == ("cascade_evidence_contract_failed",)


def test_cascade_does_not_use_reconciliation_to_choose_candidate() -> None:
    with pytest.raises(CascadePolicyError, match="reconciliation is rejection-only"):
        policy_with_reconciliation_ranker()
```

- [ ] **Step 2: Run cascade tests to verify RED**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/comparison/test_cascade.py`

Expected: collection fails because `cascade.py` does not exist.

- [ ] **Step 3: Implement the validation-only cascade**

Start with the exact accepted baseline. For unresolved rows, evaluate rules in a validation-
selected fixed order. A learned candidate requires non-null calibrated exact-row confidence at
or above its frozen threshold. A deterministic candidate without calibrated confidence can
support agreement but cannot alone override an unresolved required field. Require unique atom
support, deterministic field validation, no conflicting claims, and any predeclared independent
agreement. On any failure, abstain. After assembly, call a rejection-only reconciliation
adapter that can change `ACCEPT` to `REJECT` but cannot return a different candidate.

Construct candidate rules only for `FROZEN_ELIGIBLE` dispositions. A
`VALIDATION_STOPPED` lane is visible in the comparison report but cannot enter policy search,
agreement, fallback, or locked cascade execution.

Select policy by validation risk-coverage: first eliminate policies with unsupported fields,
accepted required-field errors beyond the predeclared bound, baseline overrides, or
nondeterminism; then maximize exact incremental coverage, minimize omissions, latency, and
policy complexity. Write the selected policy and artifact identities exclusively to the
ignored private comparison root; tracked files contain only the policy schema and selection
behavior.

- [ ] **Step 4: Run cascade, evidence, and metric tests**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/comparison/test_cascade.py tests/experiments/row_extraction/test_evidence.py tests/experiments/row_extraction/test_metrics.py`

Expected: PASS.

- [ ] **Step 5: Commit cascade policy behavior**

```bash
git add experiments/row_extraction/comparison/cascade.py \
  tests/experiments/row_extraction/comparison/test_cascade.py
git commit -m "feat: cascade grounded row predictions"
```

### Task 5: Produce the evidence-backed recommendation decision

```text
Scope answer: YES
Program component: comparison
Measured effect: the final recommendation is mechanically tied to locked measurements, regressions, uncertainty, resources, determinism, and abstention
Fixed inputs: locked ComparisonReport and locked cascade result
Allowed files: recommendation decision module and tests
Stop condition: stop before production design; return no-change if no approach passes the evidence gates
```

**Files:**
- Create: `experiments/row_extraction/comparison/recommend.py`
- Test: `tests/experiments/row_extraction/comparison/test_recommend.py`

**Interfaces:**
- Consumes: locked baseline/four-experiment/cascade results and paired intervals.
- Produces: `RecommendationKind(StrEnum)`, `Recommendation`, and `recommend(report: ComparisonReport) -> Recommendation`.

- [ ] **Step 1: Write failing winner and no-change tests**

```python
def test_recommendation_returns_no_change_on_required_field_regression() -> None:
    result = recommend(report_with_amount_regression())
    assert result.kind is RecommendationKind.NO_PRODUCTION_CHANGE
    assert "required_field_regression" in result.reasons


def test_recommendation_names_measured_pareto_winner() -> None:
    result = recommend(report_with_grounded_row_ocr_winner())
    assert result.kind is RecommendationKind.DESIGN_INTEGRATION
    assert result.selected_ids == ("row-ocr",)
```

- [ ] **Step 2: Run recommendation tests to verify RED**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/comparison/test_recommend.py`

Expected: collection fails because `recommend.py` does not exist.

- [ ] **Step 3: Implement the closed recommendation gate**

Return no-change for any accepted unsupported evidence, required amount/sign/currency/date
regression, higher false-accept risk at comparable coverage, nondeterminism, missing lane
disposition, or
unexplained protected slice regression. Otherwise choose only a Pareto result with a positive
paired document-level effect supported by its interval, report merchant/whole-row gains,
omissions/hallucinations, abstention, resources, and limitations, and authorize only a new
integration design—not code.

List every validation-stopped lane and its stop reason as a limitation. Such a disposition is
not by itself a veto on a different eligible winner, but it cannot supply locked evidence or
enter a recommended cascade.

- [ ] **Step 4: Run recommendation and comparison tests**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/comparison/test_recommend.py tests/experiments/row_extraction/comparison/test_compare.py`

Expected: PASS.

- [ ] **Step 5: Commit recommendation logic**

```bash
git add experiments/row_extraction/comparison/recommend.py \
  tests/experiments/row_extraction/comparison/test_recommend.py
git commit -m "feat: decide row extraction recommendation"
```

### Task 6: Run the locked comparison and cascade exactly once

```text
Scope answer: YES
Program component: comparison and cascade
Measured effect: final comparative results, error analysis, and recommendation across all required arms
Fixed inputs: clean committed comparison code, frozen handoffs/configurations/calibrators/policy inputs, locked rows and gold labels
Allowed files: comparison CLI/runbook; detailed results remain private and ignored
Stop condition: stop on dirty worktree, identity mismatch, missing lane disposition, changed split/labels, nondeterminism, or any attempt to retune from locked results
```

**Files:**
- Create: `experiments/row_extraction/comparison/cli.py`
- Create: `docs/experiments/row-extraction-comparison-runbook.md`
- Test: `tests/experiments/row_extraction/comparison/test_cli.py`

**Interfaces:**
- Consumes: private `ComparisonManifest`, frozen validation predictions, validated
  `FrozenRunInputs`, fixed locked rows and row-sequence identity, and private gold labels.
- Produces: Typer commands `validate-handoffs`, `compare-locked`, `select-cascade-validation`, `evaluate-cascade-locked`, and `recommend`; private detailed JSON/Markdown and privacy-safe aggregate output.

- [ ] **Step 1: Write a failing CLI gate test**

```python
def test_compare_locked_refuses_unfrozen_lane(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["compare-locked", "--manifest", str(unfrozen_manifest(tmp_path))],
    )
    assert result.exit_code == 1
    assert "experiment handoffs are not frozen" in result.stdout
```

- [ ] **Step 2: Run the CLI test to verify RED**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/comparison/test_cli.py`

Expected: collection fails because `comparison/cli.py` does not exist.

- [ ] **Step 3: Implement commands and the fail-closed runbook**

The runbook orders commands exactly: validate clean foundation/lane identities; select the
cascade only from validation predictions; write and reverify the exclusive private frozen
policy; from one clean comparison commit load each baseline/frozen arm and stream the fixed
locked rows through the shared runner. For conditional and forced page baselines, create two
independent locked `PreparationMeasurements` from new empty caches. For each of the three
baselines and every frozen-eligible lane, construct two static `ResourceSpec` values with the
same locked row sequence/split, arm/runtime/model/dependency identities and distinct new cache,
inventory, and prediction outputs; construct two fresh factories; call `run_arm` once per
factory/spec; and require byte-identical canonical predictions. The first call is the one
locked measured result and the second is solely its determinism repeat—there is no prior
resource-only prediction generation. Score the first output, attach each validation-stopped
disposition without opening it on locked data, and apply the already-frozen cascade over
eligible candidates without retuning. Then produce reports and the recommendation. No
experiment lane opens locked data itself. The
runbook forbids copying detailed reports into Git or logs and states that this is not production
integration or corpus acceptance.

- [ ] **Step 4: Run all comparison and repository verification**

Run:

```bash
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src experiments/row_extraction
/root/creditcard/.venv/bin/pytest -q
```

Expected: formatting, Ruff, mypy, and extraction-relevant tests pass. Record the inherited
sandbox-only controller failures without investigating them if they remain identical.

- [ ] **Step 5: Commit the locked-run commands before opening test results**

```bash
git add experiments/row_extraction/comparison/cli.py \
  docs/experiments/row-extraction-comparison-runbook.md \
  tests/experiments/row_extraction/comparison/test_cli.py
git commit -m "feat: run locked row experiment comparison"
```

- [ ] **Step 6: Execute the private locked run and report the decision**

From the clean committed revision, run the exact private commands in the runbook. Capture all
normal output privately. Require complete locked results for three baselines and every
frozen-eligible experiment, an explicit validation result/stop reason for every stopped lane,
exactly four total lane dispositions, and the cascade; also require byte-identical repeated
canonical predictions, complete error taxonomy, resource measurements, and a recommendation
record. Report privacy-safe aggregates only.

If the recommendation authorizes integration design, stop and ask for explicit approval of a
new design task. Do not edit `src/`, merge a lane, promote a private baseline, or claim corpus
acceptance in this plan.
