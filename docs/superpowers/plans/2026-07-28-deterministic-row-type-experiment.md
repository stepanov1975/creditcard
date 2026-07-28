# Deterministic Row-Type Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure whether a closed deterministic row-type classifier and type-specific evidence extraction improve exact transaction fields under frozen row detection.

**Architecture:** A lane-owned arm derives only general text-shape, geometry, column-occupancy, and neighboring-row signals from `FrozenRow`. It classifies each row into the charter vocabulary, delegates to small type-specific extractors that return exact atom-backed proposals, and abstains whenever more than one structural interpretation survives. Shared contracts, labels, splits, metrics, runner, and production `src/` are read-only.

**Tech Stack:** Python 3.13, Pydantic 2 shared contracts, repository date/money/currency parsers, `Decimal`, pytest, Ruff, and mypy; no learned dependency.

## Global Constraints

- Before every task, complete the charter scope block with experiment 2 and a named row/field metric.
- Consume the exact frozen foundation commit; do not change shared contracts, row identities, boxes, labels, splits, metrics, or baselines.
- Own only `experiments/row_extraction/arms/profiles/` and `tests/experiments/row_extraction/arms/profiles/`.
- Production `src/` is read-only.
- Use only issuer-neutral text shape, Unicode script/category, fixed geometry, inferred column occupancy, typed date/money/currency/installment shapes, source confidence, and neighboring fixed-row structure; `FrozenRow.baseline_type` is forbidden input because this lane must predict row type independently.
- Never use or learn a filename, path, document/hash identity, merchant string, exact date, exact amount, printed total, template identity, or corpus membership.
- Parse financial numbers with `Decimal`; charge/credit remains deterministically derived from sign.
- Every emitted field is backed by nonempty `FieldProposal.atom_ids` found in `RowPrediction.evidence_atoms`.
- Ambiguous classification or field ownership produces `Decision.ABSTAIN` or `Decision.REJECT`, never a best guess.
- Reconciliation is not an input to classification or extraction.
- Keep private predictions/configuration sweeps in ignored paths; commit only code, synthetic tests, and privacy-safe documentation.
- Stop rather than add a corpus-specific rule.

Before every commit in this plan, run this exact gate in addition to the task's focused RED/GREEN commands:

```bash
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/mypy experiments/row_extraction/arms/profiles
/root/creditcard/.venv/bin/pytest -q
/root/creditcard/.venv/bin/pytest -q --ignore=tests/test_corpus_gate.py
```

Ruff, both mypy runs, and the extraction-relevant pytest run must pass. The full suite must
either pass after an upstream fix or reproduce exactly the established five inherited
out-of-scope sandbox/controller failures. Any new or changed failure stops the task.

---

## File Structure

- `experiments/row_extraction/arms/profiles/__init__.py`: exports the experiment arm and frozen configuration.
- `experiments/row_extraction/arms/profiles/features.py`: closed general feature extraction.
- `experiments/row_extraction/arms/profiles/classifier.py`: deterministic row-type proofs and ambiguity.
- `experiments/row_extraction/arms/profiles/extractors.py`: primary, continuation, and structural proposal builders.
- `experiments/row_extraction/arms/profiles/arm.py`: shared-contract adapter and abstention policy.
- `experiments/row_extraction/arms/profiles/freeze.py`: validation-only configuration selection and immutable handoff metadata.
- `experiments/row_extraction/arms/profiles/checkpoint.py`: exact eight-section privacy-safe lane checkpoint.
- `tests/experiments/row_extraction/arms/profiles/`: focused synthetic tests for each module.

### Task 1: Extract a closed, value-independent feature profile

```text
Scope answer: YES
Program component: experiment 2
Measured effect: row-type macro F1 can be attributed to general structural evidence rather than memorized field contents
Fixed inputs: FrozenRow geometry, atoms, columns, and neighbor gaps
Allowed files: profiles feature module and tests
Stop condition: stop if a desired feature requires an exact merchant/date/amount value or document identity
```

**Files:**
- Create: `experiments/row_extraction/arms/profiles/__init__.py`
- Create: `experiments/row_extraction/arms/profiles/features.py`
- Create: `tests/experiments/row_extraction/arms/profiles/__init__.py`
- Test: `tests/experiments/row_extraction/arms/profiles/test_features.py`

**Interfaces:**
- Consumes: `FrozenRow`, `FieldRole`, repository shape predicates, and Unicode categories.
- Produces: frozen `RowProfile` and `profile_row(row: FrozenRow) -> RowProfile`.

- [ ] **Step 1: Write a failing invariance test**

```python
def test_profile_does_not_encode_exact_merchant_or_amount() -> None:
    first = frozen_row_with_text(description="ALPHA SHOP", amount="10.00")
    second = frozen_row_with_text(description="OMEGA CAFE", amount="99.99")
    assert profile_row(first) == profile_row(second)


def test_profile_records_typed_column_occupancy_and_neighbor_gap() -> None:
    row = frozen_row_with_primary_shape(previous_row_id="previous", gap_before=4.0)
    profile = profile_row(row)
    assert profile.has_date_shape is True
    assert profile.has_money_in_billed_band is True
    assert profile.alphabetic_description_atoms == 1
    assert profile.has_previous_row is True
    assert profile.gap_before_in_row_heights == Decimal("0.5")
```

- [ ] **Step 2: Run the tests to verify RED**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/profiles/test_features.py`

Expected: collection fails because `features.py` does not exist.

- [ ] **Step 3: Implement the frozen profile**

```python
class RowProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    has_date_shape: bool
    has_money_shape: bool
    has_money_in_billed_band: bool
    has_currency_shape: bool
    has_installment_shape: bool
    has_previous_row: bool
    has_header_role_shape: bool
    has_structural_label_shape: bool
    alphabetic_description_atoms: int = Field(ge=0)
    occupied_roles: tuple[FieldRole, ...]
    source_modes: tuple[str, ...]
    script_classes: tuple[str, ...]
    gap_before_in_row_heights: Decimal | None
    gap_after_in_row_heights: Decimal | None
```

Derive normalized gaps from the fixed row height using `Decimal(str(value))` and record only
whether a fixed predecessor exists, never its ID. Reduce text to Unicode category/script counts
and existing issuer-neutral transaction-header/structural-label shape predicates; never retain
raw token text in `RowProfile`. Sort all set-like fields.

- [ ] **Step 4: Run focused tests and mypy**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/profiles/test_features.py`

Expected: PASS.

Run: `/root/creditcard/.venv/bin/mypy experiments/row_extraction/arms/profiles/features.py`

Expected: `Success: no issues found`.

- [ ] **Step 5: Commit value-independent profiles**

```bash
git add experiments/row_extraction/arms/profiles/__init__.py \
  experiments/row_extraction/arms/profiles/features.py \
  tests/experiments/row_extraction/arms/profiles/__init__.py \
  tests/experiments/row_extraction/arms/profiles/test_features.py
git commit -m "feat: profile frozen transaction rows"
```

### Task 2: Classify the closed deterministic row vocabulary

```text
Scope answer: YES
Program component: experiment 2
Measured effect: row-type precision/recall and primary-versus-continuation error rates
Fixed inputs: RowProfile and charter RowType vocabulary
Allowed files: deterministic classifier and tests
Stop condition: stop if multiple types remain proven or a new corpus-derived type is requested
```

**Files:**
- Create: `experiments/row_extraction/arms/profiles/classifier.py`
- Test: `tests/experiments/row_extraction/arms/profiles/test_classifier.py`

**Interfaces:**
- Consumes: `RowProfile`.
- Produces: `TypeProof(row_type: RowType, reasons: tuple[str, ...])`, `TypeClassification(proofs: tuple[TypeProof, ...], selected: RowType)`, and `classify_profile(profile: RowProfile) -> TypeClassification`.

- [ ] **Step 1: Write failing unique and ambiguous proof tests**

```python
def test_primary_requires_billed_money_and_transaction_shape() -> None:
    result = classify_profile(primary_profile())
    assert result.selected is RowType.PRIMARY_TRANSACTION
    assert result.proofs == (
        TypeProof(
            row_type=RowType.PRIMARY_TRANSACTION,
            reasons=("billed_money_and_transaction_shape",),
        ),
    )


def test_competing_primary_and_structural_proofs_abstain() -> None:
    result = classify_profile(competing_profile())
    assert result.selected is RowType.AMBIGUOUS
    assert tuple(proof.row_type for proof in result.proofs) == (
        RowType.PRIMARY_TRANSACTION,
        RowType.STRUCTURAL,
    )
```

- [ ] **Step 2: Run the tests to verify RED**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/profiles/test_classifier.py`

Expected: collection fails because `classifier.py` does not exist.

- [ ] **Step 3: Implement independent positive proofs and closed selection**

Implement separate pure predicates:

- primary: one billed-band money shape plus a supported date/description/typed transaction
  shape, with no structural contradiction;
- continuation: no billed money, at least one permitted continuation field/description atom,
  a preceding fixed row, and bounded normalized gap;
- structural: positive header/total/nontransaction typed shape already represented in fixed
  roles, never merely the absence of transaction fields;
- ambiguous: zero or multiple positive proofs.

Return proofs in `RowType` order. Do not use scores or fallback priority to break ties.

- [ ] **Step 4: Run classifier and profile tests**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/profiles/test_classifier.py tests/experiments/row_extraction/arms/profiles/test_features.py`

Expected: PASS.

- [ ] **Step 5: Commit deterministic type proofs**

```bash
git add experiments/row_extraction/arms/profiles/classifier.py \
  tests/experiments/row_extraction/arms/profiles/test_classifier.py
git commit -m "feat: classify frozen row types deterministically"
```

### Task 3: Build type-specific evidence proposal extractors

```text
Scope answer: YES
Program component: experiment 2
Measured effect: exact merchant/date/amount/currency/kind extraction and omission/hallucination rates by row type
Fixed inputs: selected unique RowType, FrozenRow atoms and column bands
Allowed files: type-specific extractor module and tests
Stop condition: stop on nonunique field ownership, unsupported syntax, or any need to synthesize text/value
```

**Files:**
- Create: `experiments/row_extraction/arms/profiles/extractors.py`
- Test: `tests/experiments/row_extraction/arms/profiles/test_extractors.py`

**Interfaces:**
- Consumes: `FrozenRow`, `RowType`, fixed evidence atoms/bands, and existing read-only parsers.
- Produces: `ExtractionOutcome(proposals: tuple[FieldProposal, ...], decision: Decision, reasons: tuple[str, ...])` and `extract_for_type(row: FrozenRow, row_type: RowType) -> ExtractionOutcome`.

- [ ] **Step 1: Write failing primary, continuation, and ambiguity tests**

```python
def test_primary_extractor_returns_exact_description_and_money_atoms() -> None:
    row = frozen_row_with_primary_shape()
    outcome = extract_for_type(row, RowType.PRIMARY_TRANSACTION)
    assert outcome.decision is Decision.ACCEPT
    assert {proposal.role for proposal in outcome.proposals} >= {
        FieldRole.DESCRIPTION,
        FieldRole.BILLED_AMOUNT,
        FieldRole.BILLING_CURRENCY,
        FieldRole.KIND,
    }
    assert all(proposal.atom_ids for proposal in outcome.proposals)


def test_continuation_targets_only_the_fixed_previous_row() -> None:
    row = frozen_description_continuation(previous_row_id="previous")
    outcome = extract_for_type(row, RowType.CONTINUATION)
    assert outcome.proposals[0].owner_row_id == "previous"


def test_two_billed_amount_candidates_abstain() -> None:
    outcome = extract_for_type(two_billed_amount_row(), RowType.PRIMARY_TRANSACTION)
    assert outcome.decision is Decision.ABSTAIN
    assert outcome.reasons == ("nonunique_billed_amount_evidence",)
```

- [ ] **Step 2: Run the extractor tests to verify RED**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/profiles/test_extractors.py`

Expected: collection fails because `extractors.py` does not exist.

- [ ] **Step 3: Implement small extractors by type**

For a primary row, require exactly one parseable billed amount in the billed band, derive kind
from its `Decimal` sign, parse each date/currency/installment candidate with existing read-only
helpers, and select description atoms as the unique supported alphabetic residual in the
description band after typed fields are claimed. Preserve source atom order.

For a continuation, permit only charter-supported description/ancillary/optional-field atoms,
require `previous_row_id`, and set `owner_row_id` on every proposal. A continuation never
creates billed amount or kind.

For structural rows, emit `Decision.IGNORE` only on a positive structural proof and no field
proposals. For ambiguous rows, emit `Decision.ABSTAIN`.

- [ ] **Step 4: Run extractor and existing parser-field tests**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/profiles/test_extractors.py tests/test_normalization_fields.py tests/test_normalization_description.py tests/test_normalization_dates.py`

Expected: PASS.

- [ ] **Step 5: Commit type-specific extraction**

```bash
git add experiments/row_extraction/arms/profiles/extractors.py \
  tests/experiments/row_extraction/arms/profiles/test_extractors.py
git commit -m "feat: extract fields by deterministic row type"
```

### Task 4: Expose the experiment arm and fail-closed decision policy

```text
Scope answer: YES
Program component: experiment 2
Measured effect: common runner can measure exact rows, abstention, evidence failures, latency, and determinism for this lane
Fixed inputs: shared ExperimentArm contract and Tasks 1-3
Allowed files: profiles arm adapter and tests
Stop condition: stop if an adapter would bypass shared evidence validation or convert ambiguity into acceptance
```

**Files:**
- Create: `experiments/row_extraction/arms/profiles/arm.py`
- Test: `tests/experiments/row_extraction/arms/profiles/test_arm.py`

**Interfaces:**
- Consumes: `FrozenRow`, `profile_row`, `classify_profile`, and `extract_for_type`.
- Produces: `ProfileConfig(version: str, max_continuation_gap: Decimal)`, `ProfileConfig.v1()`, `ProfileConfig.candidates()`, `DeterministicProfileArm`, and exact `ExperimentArm.predict(row: FrozenRow) -> RowPrediction` behavior.

- [ ] **Step 1: Write a failing end-to-end arm test**

```python
def test_arm_copies_only_supporting_atoms_and_preserves_identity() -> None:
    row = frozen_row_with_primary_shape()
    prediction = DeterministicProfileArm(ProfileConfig.v1()).predict(row)
    assert prediction.experiment_id == "row-profiles"
    assert prediction.document_id == row.document_id
    assert prediction.row_id == row.row_id
    supported = {atom_id for proposal in prediction.proposals for atom_id in proposal.atom_ids}
    assert {atom.atom_id for atom in prediction.evidence_atoms} == supported


def test_arm_abstains_on_competing_type_proofs() -> None:
    prediction = DeterministicProfileArm(ProfileConfig.v1()).predict(competing_row())
    assert prediction.decision is Decision.ABSTAIN
    assert prediction.exact_row_confidence is None
    assert prediction.reasons == ("ambiguous_row_type",)
```

- [ ] **Step 2: Run the arm test to verify RED**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/profiles/test_arm.py`

Expected: collection fails because `arm.py` does not exist.

- [ ] **Step 3: Implement the adapter**

Implement `ProfileConfig.v1()` as the default `Decimal("0.75")` continuation-gap bound and
`ProfileConfig.candidates()` as exactly `("tight", Decimal("0.50"))`,
`("default", Decimal("0.75"))`, and `("wide", Decimal("1.00"))`. The bound is measured in
fixed-row heights and is the only tuned rule in this lane. Use the selected versioned
deterministic config, copy only proposal-supporting atoms into the
prediction ledger, set `exact_row_confidence=None` because deterministic proof strength is not
a calibrated probability, and pass stable reasons through unchanged. Ensure config IDs contain
only policy versions, never private counts or values.

- [ ] **Step 4: Run the complete profiles lane and common runner tests**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/profiles tests/experiments/row_extraction/test_runner.py tests/experiments/row_extraction/test_metrics.py`

Expected: PASS.

Run: `/root/creditcard/.venv/bin/mypy experiments/row_extraction/arms/profiles`

Expected: `Success: no issues found`.

- [ ] **Step 5: Commit the common arm adapter**

```bash
git add experiments/row_extraction/arms/profiles/arm.py \
  tests/experiments/row_extraction/arms/profiles/test_arm.py
git commit -m "feat: expose deterministic row profile arm"
```

### Task 5: Select, freeze, and hand off the deterministic lane

```text
Scope answer: YES
Program component: experiment 2
Measured effect: one validation-selected deterministic configuration and frozen predictions are ready for fair locked comparison
Fixed inputs: private train/validation split, gold labels, common metrics, completed lane code
Allowed files: validation-freeze code and tests; private outputs remain ignored
Stop condition: stop before locked-test access, rule addition after errors, or production integration
```

**Files:**
- Create: `experiments/row_extraction/arms/profiles/freeze.py`
- Create: `experiments/row_extraction/arms/profiles/checkpoint.py`
- Test: `tests/experiments/row_extraction/arms/profiles/test_freeze.py`
- Test: `tests/experiments/row_extraction/arms/profiles/test_checkpoint.py`

**Interfaces:**
- Consumes: exactly `ProfileConfig.candidates()`, validation `MetricReport` values, and `ArtifactIdentity` records.
- Produces: `FrozenProfileHandoff(disposition: LaneDisposition, config: ProfileConfig | None, stop_reason: str | None, validation_predictions: ArtifactIdentity, validation_metrics: ArtifactIdentity, validation_measurements: ArtifactIdentity, determinism: ArtifactIdentity, error_summary: ArtifactIdentity, test_accessed: Literal[False])`, `select_profile_config(candidates: Sequence[ProfileCandidate]) -> FrozenProfileHandoff`, and the charter's exact eight-section privacy-safe checkpoint.

- [ ] **Step 1: Write a failing deterministic selection test**

```python
def test_selection_uses_predeclared_exact_row_then_abstention_order() -> None:
    selected = select_profile_config(
        (
            profile_candidate("tight", exact_rows=8, hallucinations=0, coverage=Decimal("0.8")),
            profile_candidate("default", exact_rows=8, hallucinations=1, coverage=Decimal("0.9")),
        )
    )
    assert selected.disposition is LaneDisposition.FROZEN_ELIGIBLE
    assert selected.config is not None
    assert selected.config.version == "tight"


def test_checkpoint_has_exact_charter_sections_and_no_private_values() -> None:
    checkpoint = build_checkpoint(synthetic_profile_handoff())
    assert tuple(checkpoint) == (
        "scope",
        "hypothesis",
        "fixed_inputs_and_configuration",
        "files_changed",
        "tests_and_verification",
        "measurements",
        "errors_and_limitations",
        "next_action_or_stop",
    )
    assert "Synthetic Merchant" not in json.dumps(checkpoint, sort_keys=True)
```

- [ ] **Step 2: Run the selection test to verify RED**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/profiles/test_freeze.py`

Expected: collection fails because `freeze.py` does not exist.

- [ ] **Step 3: Implement the predeclared selection order**

Reject any config outside `ProfileConfig.candidates()`. Reject any candidate with accepted hallucinations, unsupported evidence, input mutation, or
nondeterministic repeated bytes. Among survivors, order by complete exact rows, merchant exact
rows, lower omissions, higher coverage, lower p95 latency, then lexical config ID only as a
deterministic final tie-break. Persist identities, not private values, in the frozen selection
artifact. An eligible handoff has `disposition=FROZEN_ELIGIBLE`, a non-null config, no stop
reason, and a frozen-arm manifest. If no candidate survives, write
`disposition=VALIDATION_STOPPED`, `config=None`, the stable reason
`no_profile_candidate_met_validation_gate`, complete validation
prediction/metric/resource/error identities, and no frozen-arm manifest. Both dispositions
require byte-identical-repeat evidence, `test_accessed=false`, and the exact eight-section
checkpoint; neither opens the locked test.

- [ ] **Step 4: Run lane verification and private validation**

Run:

```bash
/root/creditcard/.venv/bin/ruff format --check experiments/row_extraction/arms/profiles tests/experiments/row_extraction/arms/profiles
/root/creditcard/.venv/bin/ruff check experiments/row_extraction/arms/profiles tests/experiments/row_extraction/arms/profiles
/root/creditcard/.venv/bin/mypy experiments/row_extraction/arms/profiles
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/profiles tests/experiments/row_extraction
```

Expected: PASS.

Run the common runner on private train/validation rows only, twice, with outputs in the
lane-owned ignored directory. Require byte-identical predictions. Do not inspect locked-test
metrics.

- [ ] **Step 5: Commit selection behavior and return the handoff**

```bash
git add experiments/row_extraction/arms/profiles/freeze.py \
  experiments/row_extraction/arms/profiles/checkpoint.py \
  tests/experiments/row_extraction/arms/profiles/test_freeze.py \
  tests/experiments/row_extraction/arms/profiles/test_checkpoint.py
git commit -m "feat: freeze deterministic row profile experiment"
```

Return the clean full commit SHA, frozen config/artifact identities through the private handoff
manifest, privacy-safe validation summary, resource summary, deterministic-repeat result, and
error-category counts. Mark the handoff `FROZEN_ELIGIBLE` or `VALIDATION_STOPPED`; only the
central comparison stage may run an eligible arm on locked data. Do not propose production
integration or another experiment.
