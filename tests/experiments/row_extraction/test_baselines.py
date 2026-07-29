from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import ValidationError

from experiments.row_extraction.baselines import (
    AcceptedBaselineArm,
    AcceptedBaselineArmFactory,
    BaselineContractError,
    ConditionalPageOcrArm,
    ConditionalPageOcrArmFactory,
    ForcedPageOcrArm,
    ForcedPageOcrArmFactory,
    PageEvidenceRecord,
    PageWord,
)
from experiments.row_extraction.codecs import _canonical_record_bytes, write_jsonl
from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    ColumnBand,
    DatasetSplit,
    Decision,
    FieldRole,
    FrozenRow,
    RowPrediction,
    RowType,
)
from tests.experiments.row_extraction.factories import frozen_row

_DOCUMENT_ID = "0" * 64


def _artifact(
    artifact_type: str = "runtime",
    *,
    version: str = "synthetic-v1",
    marker: str = "a",
) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_type=artifact_type,
        sha256=marker * 64,
        version=version,
        byte_size=1,
    )


def _runtime(marker: str = "a") -> ArtifactIdentity:
    return _artifact(marker=marker)


def _inventory(marker: str) -> ArtifactIdentity:
    return _artifact(
        "resource-inventory",
        version="row-resource-inventory-v1",
        marker=marker,
    )


def _row_sequence_identity(rows: Sequence[FrozenRow]) -> ArtifactIdentity:
    contents = tuple(_canonical_record_bytes(row) for row in rows)
    payload = b"".join(contents)
    return ArtifactIdentity(
        artifact_type="frozen-row-sequence",
        sha256=hashlib.sha256(payload).hexdigest(),
        version="canonical-jsonl-v1",
        byte_size=len(payload),
    )


def _manifest(
    tmp_path: Path,
    records: Sequence[RowPrediction | PageEvidenceRecord],
) -> ArtifactIdentity:
    path = tmp_path / f"manifest-{len(tuple(tmp_path.iterdir()))}.jsonl"
    return write_jsonl(path, records)


def _accepted_prediction(
    row: FrozenRow,
    *,
    experiment_id: str = "accepted-baseline",
    config_id: str = "accepted-anchor",
) -> RowPrediction:
    return RowPrediction(
        experiment_id=experiment_id,
        config_id=config_id,
        document_id=row.document_id,
        row_id=row.row_id,
        predicted_type=row.baseline_type,
        evidence_atoms=(),
        proposals=(),
        exact_row_confidence=None,
        decision=(Decision.IGNORE if row.baseline_type is RowType.STRUCTURAL else Decision.ABSTAIN),
        reasons=("synthetic_baseline",),
    )


def _band(
    index: int,
    role: FieldRole | None,
    bbox: tuple[float, float, float, float],
) -> ColumnBand:
    return ColumnBand(index=index, role=role, bbox=bbox)


def _row(
    *,
    row_id: str = "row-1",
    bbox: tuple[float, float, float, float] = (0.0, 10.0, 200.0, 40.0),
    row_type: RowType = RowType.PRIMARY_TRANSACTION,
    bands: tuple[ColumnBand, ...] = (),
    previous_row_id: str | None = None,
    page_number: int = 1,
    split: DatasetSplit = DatasetSplit.TRAIN,
) -> FrozenRow:
    return frozen_row(
        row_id=row_id,
        bbox=bbox,
        baseline_type=row_type,
        page_number=page_number,
        split=split,
        atoms=(),
    ).model_copy(
        update={
            "column_bands": bands,
            "previous_row_id": previous_row_id,
        }
    )


def _word(
    ordinal: int,
    text: str,
    bbox: tuple[float, float, float, float],
    *,
    source: str = "ocr",
    confidence: float = 0.9,
) -> PageWord:
    return PageWord(
        ordinal=ordinal,
        text=text,
        bbox=bbox,
        source=source,
        confidence=confidence,
    )


def _page(
    words: tuple[PageWord, ...],
    *,
    mode: str = "forced-page-ocr",
    config_id: str = "synthetic-config-v1",
    runtime_identity: ArtifactIdentity | None = None,
    page_number: int = 1,
) -> PageEvidenceRecord:
    return PageEvidenceRecord(
        document_id=_DOCUMENT_ID,
        page_number=page_number,
        page_bbox=(0.0, 0.0, 300.0, 500.0),
        mode=mode,
        evidence_version="fixed-page-evidence-v1",
        config_id=config_id,
        runtime_identity=runtime_identity or _runtime(),
        words=words,
    )


def _page_arm(
    tmp_path: Path,
    rows: Sequence[FrozenRow],
    pages: Sequence[PageEvidenceRecord],
    *,
    mode: str = "forced-page-ocr",
) -> ForcedPageOcrArm | ConditionalPageOcrArm:
    identity = _manifest(tmp_path, pages)
    if mode == "forced-page-ocr":
        return ForcedPageOcrArm(rows, pages, identity)
    return ConditionalPageOcrArm(rows, pages, identity)


def test_page_contracts_are_frozen_and_forbid_unknown_fields() -> None:
    word = _word(0, "SYNTHETIC", (1.0, 1.0, 2.0, 2.0))
    page = _page((word,))

    with pytest.raises(ValidationError):
        word.ordinal = 2
    with pytest.raises(ValidationError):
        PageEvidenceRecord.model_validate({**page.model_dump(), "unknown": "value"})


def test_accepted_baseline_returns_the_exact_materialized_projection(tmp_path: Path) -> None:
    row = _row(row_type=RowType.STRUCTURAL)
    prediction = _accepted_prediction(row)
    arm = AcceptedBaselineArm((row,), (prediction,), _manifest(tmp_path, (prediction,)))

    assert arm.experiment_id == "accepted-baseline"
    assert arm.config_id == "accepted-anchor"
    assert arm.predict(row) is prediction


def test_accepted_baseline_allows_table_height_fixed_column_bands(tmp_path: Path) -> None:
    row = _row(
        bands=(
            _band(
                0,
                FieldRole.DESCRIPTION,
                (20.0, 0.0, 180.0, 500.0),
            ),
        )
    )
    prediction = _accepted_prediction(row)

    arm = AcceptedBaselineArm((row,), (prediction,), _manifest(tmp_path, (prediction,)))

    assert arm.predict(row) is prediction


def test_accepted_baseline_allows_fixed_columns_without_row_content_overlap(
    tmp_path: Path,
) -> None:
    row = _row(bands=(_band(0, FieldRole.DESCRIPTION, (220.0, 0.0, 260.0, 500.0)),))
    prediction = _accepted_prediction(row)

    arm = AcceptedBaselineArm((row,), (prediction,), _manifest(tmp_path, (prediction,)))

    assert arm.predict(row) is prediction


def test_accepted_baseline_rejects_invalid_fixed_column_geometry(tmp_path: Path) -> None:
    row = _row(bands=(_band(0, FieldRole.DESCRIPTION, (20.0, 0.0, 20.0, 500.0)),))
    prediction = _accepted_prediction(row)

    with pytest.raises(BaselineContractError, match="invalid fixed column geometry"):
        AcceptedBaselineArm((row,), (prediction,), _manifest(tmp_path, (prediction,)))


def test_accepted_baseline_rejects_duplicate_fixed_column_indexes(tmp_path: Path) -> None:
    row = _row(
        bands=(
            _band(0, FieldRole.DESCRIPTION, (20.0, 0.0, 100.0, 500.0)),
            _band(0, FieldRole.BILLED_AMOUNT, (100.0, 0.0, 180.0, 500.0)),
        )
    )
    prediction = _accepted_prediction(row)

    with pytest.raises(BaselineContractError, match="duplicate fixed column index"):
        AcceptedBaselineArm((row,), (prediction,), _manifest(tmp_path, (prediction,)))


def test_accepted_baseline_verifies_complete_artifact_then_selects_requested_split(
    tmp_path: Path,
) -> None:
    train_row = _row(row_id="train-row", split=DatasetSplit.TRAIN)
    validation_row = _row(row_id="validation-row", split=DatasetSplit.VALIDATION)
    train_prediction = _accepted_prediction(train_row)
    validation_prediction = _accepted_prediction(validation_row)
    complete_predictions = (train_prediction, validation_prediction)
    complete_identity = _manifest(tmp_path, complete_predictions)

    arm = AcceptedBaselineArm(
        (validation_row,),
        complete_predictions,
        complete_identity,
    )

    assert arm.artifact_identity == complete_identity
    assert arm.predict(validation_row) is validation_prediction


def test_accepted_baseline_rejects_missing_selected_prediction(tmp_path: Path) -> None:
    selected_row = _row(row_id="validation-row", split=DatasetSplit.VALIDATION)
    other_row = _row(row_id="train-row", split=DatasetSplit.TRAIN)
    complete_predictions = (_accepted_prediction(other_row),)

    with pytest.raises(BaselineContractError, match="accepted prediction identity contract"):
        AcceptedBaselineArm(
            (selected_row,),
            complete_predictions,
            _manifest(tmp_path, complete_predictions),
        )


def test_accepted_baseline_rejects_duplicate_identity_anywhere_in_complete_artifact(
    tmp_path: Path,
) -> None:
    selected_row = _row(row_id="validation-row", split=DatasetSplit.VALIDATION)
    other_row = _row(row_id="train-row", split=DatasetSplit.TRAIN)
    selected = _accepted_prediction(selected_row)
    other = _accepted_prediction(other_row)
    complete_predictions = (selected, other, other)

    with pytest.raises(BaselineContractError, match="accepted prediction identity contract"):
        AcceptedBaselineArm(
            (selected_row,),
            complete_predictions,
            _manifest(tmp_path, complete_predictions),
        )


def test_accepted_baseline_rejects_unverified_extra_prediction(tmp_path: Path) -> None:
    selected_row = _row(row_id="validation-row", split=DatasetSplit.VALIDATION)
    unrelated_row = _row(row_id="unrelated-row", split=DatasetSplit.TRAIN)
    selected = _accepted_prediction(selected_row)
    with_unverified_extra = (selected, _accepted_prediction(unrelated_row))
    expected_complete_identity = _manifest(tmp_path, (selected,))

    with pytest.raises(BaselineContractError, match="accepted prediction artifact identity"):
        AcceptedBaselineArm(
            (selected_row,),
            with_unverified_extra,
            expected_complete_identity,
        )


def test_accepted_baseline_rejects_bad_complete_artifact_identity(tmp_path: Path) -> None:
    selected_row = _row(row_id="validation-row", split=DatasetSplit.VALIDATION)
    selected = _accepted_prediction(selected_row)
    identity = _manifest(tmp_path, (selected,)).model_copy(update={"sha256": "f" * 64})

    with pytest.raises(BaselineContractError, match="accepted prediction artifact identity"):
        AcceptedBaselineArm((selected_row,), (selected,), identity)


@pytest.mark.parametrize("case", ("experiment", "config", "row_type", "manifest"))
def test_accepted_baseline_rejects_wrong_projection_metadata(tmp_path: Path, case: str) -> None:
    row = _row()
    prediction = _accepted_prediction(row)
    identity = _manifest(tmp_path, (prediction,))
    if case == "experiment":
        prediction = _accepted_prediction(row, experiment_id="PRIVATE-EXPERIMENT")
        identity = _manifest(tmp_path, (prediction,))
    elif case == "config":
        prediction = _accepted_prediction(row, config_id="PRIVATE-CONFIG")
        identity = _manifest(tmp_path, (prediction,))
    elif case == "row_type":
        prediction = prediction.model_copy(update={"predicted_type": RowType.AMBIGUOUS})
        identity = _manifest(tmp_path, (prediction,))
    else:
        identity = identity.model_copy(update={"sha256": "f" * 64})

    with pytest.raises(BaselineContractError) as caught:
        AcceptedBaselineArm((row,), (prediction,), identity)

    assert "PRIVATE" not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    "case",
    ("missing", "extra", "duplicate", "wrong_mode", "config", "runtime", "ordinals"),
)
def test_page_arm_requires_a_complete_consistent_typed_page_stream(
    tmp_path: Path,
    case: str,
) -> None:
    rows = (_row(),)
    page = _page((_word(0, "SYNTHETIC", (10.0, 20.0, 20.0, 30.0)),))
    pages: tuple[PageEvidenceRecord, ...] = (page,)
    if case == "missing":
        pages = ()
    elif case == "extra":
        pages = (page, _page((), page_number=2))
    elif case == "duplicate":
        pages = (page, page)
    elif case == "wrong_mode":
        pages = (page.model_copy(update={"mode": "conditional-page-ocr"}),)
    elif case == "config":
        second_row = _row(row_id="row-2", page_number=2)
        rows = (*rows, second_row)
        pages = (page, _page((), page_number=2, config_id="PRIVATE-CONFIG"))
    elif case == "runtime":
        second_row = _row(row_id="row-2", page_number=2)
        rows = (*rows, second_row)
        pages = (page, _page((), page_number=2, runtime_identity=_runtime("b")))
    elif case == "ordinals":
        pages = (
            _page(
                (
                    _word(0, "FIRST", (10.0, 20.0, 20.0, 30.0)),
                    _word(2, "SECOND", (30.0, 20.0, 40.0, 30.0)),
                )
            ),
        )

    with pytest.raises(BaselineContractError) as caught:
        ForcedPageOcrArm(rows, pages, _manifest(tmp_path, pages))

    assert "PRIVATE" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_page_arm_rejects_a_forged_manifest_identity(tmp_path: Path) -> None:
    row = _row()
    page = _page(())
    identity = _manifest(tmp_path, (page,)).model_copy(update={"byte_size": 999})

    with pytest.raises(BaselineContractError, match="page evidence artifact identity"):
        ForcedPageOcrArm((row,), (page,), identity)


def test_half_open_row_assignment_chooses_only_the_row_on_the_boundary(tmp_path: Path) -> None:
    left = _row(
        row_id="left",
        bbox=(0.0, 10.0, 100.0, 40.0),
        bands=(_band(0, FieldRole.DESCRIPTION, (0.0, 10.0, 100.0, 40.0)),),
    )
    right = _row(
        row_id="right",
        bbox=(100.0, 10.0, 200.0, 40.0),
        bands=(_band(0, FieldRole.DESCRIPTION, (100.0, 10.0, 200.0, 40.0)),),
    )
    page = _page((_word(0, "BOUNDARY", (99.0, 20.0, 101.0, 30.0)),))
    arm = _page_arm(tmp_path, (left, right), (page,))

    assert arm.predict(left).evidence_atoms == ()
    right_prediction = arm.predict(right)
    assert tuple(atom.text for atom in right_prediction.evidence_atoms) == ("BOUNDARY",)
    assert right_prediction.evidence_atoms[0].bbox == (100.0, 20.0, 101.0, 30.0)


def test_word_boxes_are_clipped_to_the_fixed_row_on_both_axes(tmp_path: Path) -> None:
    row = _row(
        bbox=(10.0, 10.0, 100.0, 40.0),
        bands=(_band(0, FieldRole.DESCRIPTION, (10.0, 10.0, 100.0, 40.0)),),
    )
    page = _page((_word(0, "CLIPPED", (5.0, 5.0, 50.0, 50.0)),))
    prediction = _page_arm(tmp_path, (row,), (page,)).predict(row)

    assert prediction.evidence_atoms[0].bbox == (10.0, 10.0, 50.0, 40.0)


def test_half_open_band_assignment_chooses_only_the_band_on_the_boundary(tmp_path: Path) -> None:
    row = _row(
        bands=(
            _band(0, FieldRole.ANCILLARY, (0.0, 10.0, 100.0, 40.0)),
            _band(1, FieldRole.DESCRIPTION, (100.0, 10.0, 200.0, 40.0)),
        )
    )
    page = _page((_word(0, "BOUNDARY", (99.0, 20.0, 101.0, 30.0)),))
    prediction = _page_arm(tmp_path, (row,), (page,)).predict(row)

    assert prediction.decision is Decision.ACCEPT
    assert tuple(proposal.role for proposal in prediction.proposals) == (FieldRole.DESCRIPTION,)
    assert prediction.evidence_atoms[0].column_index == 1


def test_band_assignment_ignores_independent_vertical_extent(tmp_path: Path) -> None:
    row = _row(bands=(_band(0, FieldRole.DESCRIPTION, (0.0, 100.0, 200.0, 500.0)),))
    page = _page((_word(0, "SYNTHETIC", (10.0, 20.0, 100.0, 30.0)),))

    prediction = _page_arm(tmp_path, (row,), (page,)).predict(row)

    assert prediction.decision is Decision.ACCEPT
    assert tuple(proposal.role for proposal in prediction.proposals) == (FieldRole.DESCRIPTION,)
    assert prediction.evidence_atoms[0].column_index == 0


@pytest.mark.parametrize("collision", ("row", "band"))
def test_page_assignment_fails_closed_on_geometry_collisions(
    tmp_path: Path,
    collision: str,
) -> None:
    if collision == "row":
        rows = (
            _row(
                row_id="one",
                bands=(_band(0, FieldRole.DESCRIPTION, (0.0, 10.0, 200.0, 40.0)),),
            ),
            _row(
                row_id="two",
                bands=(_band(0, FieldRole.DESCRIPTION, (0.0, 10.0, 200.0, 40.0)),),
            ),
        )
    else:
        rows = (
            _row(
                bands=(
                    _band(0, FieldRole.DESCRIPTION, (0.0, 10.0, 150.0, 40.0)),
                    _band(1, FieldRole.ANCILLARY, (50.0, 10.0, 200.0, 40.0)),
                )
            ),
        )
    page = _page((_word(0, "COLLISION", (80.0, 20.0, 100.0, 30.0)),))

    with pytest.raises(BaselineContractError, match=f"page word {collision} collision"):
        _page_arm(tmp_path, rows, (page,))


def test_unassigned_words_are_ignored_and_words_have_unique_row_ownership(tmp_path: Path) -> None:
    first = _row(
        row_id="one",
        bbox=(0.0, 10.0, 100.0, 40.0),
        bands=(_band(0, FieldRole.DESCRIPTION, (0.0, 10.0, 100.0, 40.0)),),
    )
    second = _row(
        row_id="two",
        bbox=(100.0, 10.0, 200.0, 40.0),
        bands=(_band(0, FieldRole.DESCRIPTION, (100.0, 10.0, 200.0, 40.0)),),
    )
    page = _page(
        (
            _word(0, "FIRST", (10.0, 20.0, 20.0, 30.0)),
            _word(1, "SECOND", (110.0, 20.0, 120.0, 30.0)),
            _word(2, "OUTSIDE", (210.0, 20.0, 220.0, 30.0)),
        )
    )
    arm = _page_arm(tmp_path, (first, second), (page,))
    first_ids = {atom.atom_id for atom in arm.predict(first).evidence_atoms}
    second_ids = {atom.atom_id for atom in arm.predict(second).evidence_atoms}

    assert first_ids
    assert second_ids
    assert first_ids.isdisjoint(second_ids)
    assert all(
        atom.text != "OUTSIDE"
        for row in (first, second)
        for atom in arm.predict(row).evidence_atoms
    )


@pytest.mark.parametrize(
    ("row_type", "expected_decision", "expected_reason"),
    (
        (RowType.STRUCTURAL, Decision.IGNORE, "page_baseline_structural_row"),
        (RowType.AMBIGUOUS, Decision.ABSTAIN, "page_baseline_ambiguous_row"),
    ),
)
def test_nontransaction_page_rows_never_emit_proposals(
    tmp_path: Path,
    row_type: RowType,
    expected_decision: Decision,
    expected_reason: str,
) -> None:
    row = _row(
        row_type=row_type,
        bands=(_band(0, FieldRole.DESCRIPTION, (0.0, 10.0, 200.0, 40.0)),),
    )
    page = _page((_word(0, "SYNTHETIC", (10.0, 20.0, 20.0, 30.0)),))
    prediction = _page_arm(tmp_path, (row,), (page,)).predict(row)

    assert prediction.decision is expected_decision
    assert prediction.proposals == ()
    assert prediction.reasons == (expected_reason,)


@pytest.mark.parametrize(
    ("role", "text"),
    (
        (FieldRole.TRANSACTION_DATE, "2024-01-02"),
        (FieldRole.POSTING_DATE, "2024-01-02"),
        (FieldRole.CONVERSION_DATE, "2024-01-02"),
        (FieldRole.DESCRIPTION, "SYNTHETIC"),
        (FieldRole.BILLED_AMOUNT, "USD 12.30"),
        (FieldRole.BILLING_CURRENCY, "USD"),
        (FieldRole.ORIGINAL_AMOUNT, "EUR 10.00"),
        (FieldRole.ORIGINAL_CURRENCY, "EUR"),
        (FieldRole.KIND, "-12.30"),
        (FieldRole.INSTALLMENT, "2/12"),
        (FieldRole.FX_RATE, "1.23"),
        (FieldRole.ANCILLARY, "DETAIL"),
    ),
)
def test_page_resolver_accepts_each_supported_field_role(
    tmp_path: Path,
    role: FieldRole,
    text: str,
) -> None:
    row = _row(bands=(_band(0, role, (0.0, 10.0, 200.0, 40.0)),))
    page = _page((_word(0, text, (10.0, 20.0, 100.0, 30.0)),))
    prediction = _page_arm(tmp_path, (row,), (page,)).predict(row)

    assert prediction.decision is Decision.ACCEPT
    assert tuple(proposal.role for proposal in prediction.proposals) == (role,)
    assert prediction.exact_row_confidence is None
    assert prediction.reasons == ("page_baseline_supported_fields",)


def test_page_resolver_abstains_on_duplicate_roles_invalid_values_and_no_fields(
    tmp_path: Path,
) -> None:
    duplicate = _row(
        row_id="duplicate",
        bands=(
            _band(0, FieldRole.DESCRIPTION, (0.0, 10.0, 100.0, 40.0)),
            _band(1, FieldRole.DESCRIPTION, (100.0, 10.0, 200.0, 40.0)),
        ),
    )
    invalid = _row(
        row_id="invalid",
        bbox=(0.0, 50.0, 200.0, 80.0),
        bands=(_band(0, FieldRole.TRANSACTION_DATE, (0.0, 50.0, 200.0, 80.0)),),
    )
    empty = _row(row_id="empty", bbox=(0.0, 90.0, 200.0, 120.0))
    page = _page(
        (
            _word(0, "ONE", (10.0, 20.0, 20.0, 30.0)),
            _word(1, "TWO", (110.0, 20.0, 120.0, 30.0)),
            _word(2, "NOT-A-DATE", (10.0, 60.0, 100.0, 70.0)),
        )
    )
    arm = _page_arm(tmp_path, (duplicate, invalid, empty), (page,))

    assert arm.predict(duplicate).reasons == ("page_baseline_duplicate_role",)
    assert arm.predict(invalid).reasons == ("page_baseline_unresolved_proposal",)
    assert arm.predict(empty).reasons == ("page_baseline_no_supported_field",)
    assert all(
        arm.predict(row).decision is Decision.ABSTAIN and arm.predict(row).proposals == ()
        for row in (duplicate, invalid, empty)
    )


def test_continuation_requires_and_assigns_the_exact_fixed_predecessor(tmp_path: Path) -> None:
    missing = _row(
        row_id="missing",
        row_type=RowType.CONTINUATION,
        bands=(_band(0, FieldRole.DESCRIPTION, (0.0, 10.0, 200.0, 40.0)),),
    )
    owned = _row(
        row_id="owned",
        bbox=(0.0, 50.0, 200.0, 80.0),
        row_type=RowType.CONTINUATION,
        previous_row_id="primary",
        bands=(_band(0, FieldRole.DESCRIPTION, (0.0, 50.0, 200.0, 80.0)),),
    )
    page = _page(
        (
            _word(0, "MISSING", (10.0, 20.0, 100.0, 30.0)),
            _word(1, "OWNED", (10.0, 60.0, 100.0, 70.0)),
        )
    )
    arm = _page_arm(tmp_path, (missing, owned), (page,))

    assert arm.predict(missing).reasons == ("page_baseline_continuation_without_previous_row",)
    owned_prediction = arm.predict(owned)
    assert owned_prediction.decision is Decision.ACCEPT
    assert {proposal.owner_row_id for proposal in owned_prediction.proposals} == {"primary"}


def test_conditional_and_forced_ids_and_config_ids_are_exact(tmp_path: Path) -> None:
    row = _row()
    forced_page = _page(())
    conditional_page = _page((), mode="conditional-page-ocr")
    forced = _page_arm(tmp_path, (row,), (forced_page,))
    conditional = _page_arm(
        tmp_path,
        (row,),
        (conditional_page,),
        mode="conditional-page-ocr",
    )

    assert (forced.experiment_id, forced.config_id) == (
        "forced-page-ocr",
        "fixed-page-evidence-v1:synthetic-config-v1",
    )
    assert (conditional.experiment_id, conditional.config_id) == (
        "conditional-page-ocr",
        "fixed-page-evidence-v1:synthetic-config-v1",
    )


def _factory_kwargs(rows: Sequence[FrozenRow], tmp_path: Path) -> dict[str, object]:
    return {
        "row_sequence_identity": _row_sequence_identity(rows),
        "runtime_identity": _runtime(),
        "model_inventory_identity": _inventory("b"),
        "dependency_inventory_identity": _inventory("c"),
        "cache_root": tmp_path / "private-cache",
    }


def test_accepted_factory_matches_runner_protocol_and_builds_fresh_arms(tmp_path: Path) -> None:
    rows = (_row(),)
    prediction = _accepted_prediction(rows[0])
    manifest = _manifest(tmp_path, (prediction,))
    factory = AcceptedBaselineArmFactory(
        rows,
        (prediction,),
        manifest,
        **_factory_kwargs(rows, tmp_path),
    )

    assert factory.experiment_id == "accepted-baseline"
    assert factory.config_id == "accepted-anchor"
    assert factory.row_sequence_identity == _row_sequence_identity(rows)
    assert factory.expected_row_count == 1
    assert factory.split is DatasetSplit.TRAIN
    assert factory.arm_manifest_identity == manifest
    assert factory.resource_basis == "materialized-adapter"
    assert factory.worker_count == 1
    assert factory.subprocess_count == 0
    assert factory.build() is not factory.build()


def test_accepted_factory_keeps_complete_manifest_while_building_selected_split(
    tmp_path: Path,
) -> None:
    train_row = _row(row_id="train-row", split=DatasetSplit.TRAIN)
    validation_row = _row(row_id="validation-row", split=DatasetSplit.VALIDATION)
    train_prediction = _accepted_prediction(train_row)
    validation_prediction = _accepted_prediction(validation_row)
    complete_predictions = (train_prediction, validation_prediction)
    complete_manifest = _manifest(tmp_path, complete_predictions)
    factory = AcceptedBaselineArmFactory(
        (validation_row,),
        complete_predictions,
        complete_manifest,
        **_factory_kwargs((validation_row,), tmp_path),
    )

    assert factory.arm_manifest_identity == complete_manifest
    assert factory.expected_row_count == 1
    assert factory.split is DatasetSplit.VALIDATION
    assert factory.build().predict(validation_row) is validation_prediction


@pytest.mark.parametrize(
    ("factory_type", "mode"),
    (
        (ConditionalPageOcrArmFactory, "conditional-page-ocr"),
        (ForcedPageOcrArmFactory, "forced-page-ocr"),
    ),
)
def test_page_factories_match_runner_protocol_and_build_fresh_arms(
    tmp_path: Path,
    factory_type: type[ConditionalPageOcrArmFactory] | type[ForcedPageOcrArmFactory],
    mode: str,
) -> None:
    rows = (_row(),)
    page = _page((), mode=mode)
    manifest = _manifest(tmp_path, (page,))
    factory = factory_type(rows, (page,), manifest, **_factory_kwargs(rows, tmp_path))

    assert factory.experiment_id == mode
    assert factory.config_id == "fixed-page-evidence-v1:synthetic-config-v1"
    assert factory.resource_basis == "end-to-end-method"
    assert factory.worker_count == 1
    assert factory.subprocess_count == 0
    assert factory.build() is not factory.build()


@pytest.mark.parametrize(
    "case",
    ("row_sequence", "runtime", "model_inventory", "dependency_inventory", "split"),
)
def test_factories_reject_wrong_static_bindings_without_private_values(
    tmp_path: Path,
    case: str,
) -> None:
    rows = (_row(),)
    page = _page(())
    kwargs = _factory_kwargs(rows, tmp_path)
    if case == "row_sequence":
        kwargs["row_sequence_identity"] = _row_sequence_identity(rows).model_copy(
            update={"sha256": "f" * 64}
        )
    elif case == "runtime":
        kwargs["runtime_identity"] = _runtime("f")
    elif case == "model_inventory":
        kwargs["model_inventory_identity"] = _artifact(marker="f")
    elif case == "dependency_inventory":
        kwargs["dependency_inventory_identity"] = _artifact(marker="f")
    else:
        rows = (*rows, _row(row_id="PRIVATE-ROW", split=DatasetSplit.VALIDATION))
        kwargs["row_sequence_identity"] = _row_sequence_identity(rows)

    with pytest.raises(BaselineContractError) as caught:
        ForcedPageOcrArmFactory(
            rows,
            (page,),
            _manifest(tmp_path, (page,)),
            **kwargs,
        )

    assert "PRIVATE" not in str(caught.value)
    assert caught.value.__cause__ is None
