"""Fixed-row adapters for the accepted and whole-page evidence baselines."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, Never

from pydantic import Field, ValidationError

from experiments.row_extraction.codecs import _canonical_record_bytes
from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    BBox,
    DatasetSplit,
    Decision,
    EvidenceAtom,
    ExperimentArm,
    FieldProposal,
    FieldRole,
    FrozenRow,
    RowPrediction,
    RowType,
    _FrozenModel,
)
from experiments.row_extraction.evidence import EvidenceContractError, resolve_proposal

_ACCEPTED_EXPERIMENT_ID = "accepted-baseline"
_ACCEPTED_CONFIG_ID = "accepted-anchor"
_CONDITIONAL_EXPERIMENT_ID: Literal["conditional-page-ocr"] = "conditional-page-ocr"
_FORCED_EXPERIMENT_ID: Literal["forced-page-ocr"] = "forced-page-ocr"
_PAGE_EVIDENCE_VERSION = "fixed-page-evidence-v1"
_JSONL_ARTIFACT_TYPE = "jsonl"
_JSONL_VERSION = "canonical-jsonl-v1"
_ROW_SEQUENCE_ARTIFACT_TYPE = "frozen-row-sequence"
_RESOURCE_INVENTORY_TYPE = "resource-inventory"
_RESOURCE_INVENTORY_VERSION = "row-resource-inventory-v1"

type _Identity = tuple[str, str]
type _PageIdentity = tuple[str, int]
type _PageMode = Literal["conditional-page-ocr", "forced-page-ocr"]
type _ResourceBasis = Literal["end-to-end-method", "materialized-adapter"]


class BaselineContractError(ValueError):
    """Baseline input violates a fixed, privacy-safe experiment contract."""


class PageWord(_FrozenModel):
    """One positioned provider word in rotated top-left display coordinates."""

    ordinal: int = Field(ge=0)
    text: str = Field(min_length=1)
    bbox: BBox
    source: Literal["digital", "ocr"]
    confidence: float = Field(ge=0.0, le=1.0)


class PageEvidenceRecord(_FrozenModel):
    """Complete typed word evidence for one fixed-row-owning document page."""

    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_number: int = Field(gt=0)
    page_bbox: BBox
    mode: _PageMode
    evidence_version: Literal["fixed-page-evidence-v1"]
    config_id: str = Field(min_length=1)
    runtime_identity: ArtifactIdentity
    words: tuple[PageWord, ...]


def _fail(message: str) -> Never:
    raise BaselineContractError(message)


def _validated[Model: _FrozenModel](record: Model, model: type[Model], message: str) -> Model:
    try:
        return model.model_validate(record.model_dump(mode="python"))
    except (AttributeError, TypeError, ValidationError, ValueError):
        raise BaselineContractError(message) from None


def _valid_bbox(bbox: BBox) -> bool:
    x0, y0, x1, y1 = bbox
    return all(math.isfinite(value) for value in bbox) and x0 < x1 and y0 < y1


def _contains(outer: BBox, inner: BBox) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


def _center(bbox: BBox) -> tuple[float, float]:
    return (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2


def _center_inside(bbox: BBox, point: tuple[float, float]) -> bool:
    return bbox[0] <= point[0] < bbox[2] and bbox[1] <= point[1] < bbox[3]


def _horizontal_center_inside(bbox: BBox, x_center: float) -> bool:
    return bbox[0] <= x_center < bbox[2]


def _clip(bbox: BBox, outer: BBox) -> BBox:
    clipped = (
        max(bbox[0], outer[0]),
        max(bbox[1], outer[1]),
        min(bbox[2], outer[2]),
        min(bbox[3], outer[3]),
    )
    if not _valid_bbox(clipped):
        _fail("page word clipping contract")
    return clipped


def _identity(row: FrozenRow | RowPrediction) -> _Identity:
    return row.document_id, row.row_id


def _validated_rows(rows: Sequence[FrozenRow]) -> tuple[FrozenRow, ...]:
    if not rows:
        _fail("baseline rows must be nonempty")
    validated: list[FrozenRow] = []
    identities: set[_Identity] = set()
    splits: set[DatasetSplit] = set()
    for raw_row in rows:
        row = _validated(raw_row, FrozenRow, "invalid frozen row input")
        identity = _identity(row)
        if identity in identities:
            _fail("duplicate frozen row identity")
        identities.add(identity)
        splits.add(row.split)
        if not _valid_bbox(row.bbox):
            _fail("invalid frozen row geometry")
        band_indexes: set[int] = set()
        for band in row.column_bands:
            if band.index in band_indexes:
                _fail("duplicate fixed column index")
            band_indexes.add(band.index)
            if not _valid_bbox(band.bbox):
                _fail("invalid fixed column geometry")
        validated.append(row)
    if len(splits) != 1:
        _fail("baseline rows must use one split")
    return tuple(validated)


def _records_identity(records: Sequence[_FrozenModel], artifact_type: str) -> ArtifactIdentity:
    digest = hashlib.sha256()
    byte_size = 0
    for record in records:
        content = _canonical_record_bytes(record)
        digest.update(content)
        byte_size += len(content)
    return ArtifactIdentity(
        artifact_type=artifact_type,
        sha256=digest.hexdigest(),
        version=_JSONL_VERSION,
        byte_size=byte_size,
    )


def _validate_stream_identity(
    records: Sequence[_FrozenModel],
    identity: ArtifactIdentity,
    message: str,
) -> ArtifactIdentity:
    validated = _validated(identity, ArtifactIdentity, message)
    if validated != _records_identity(records, _JSONL_ARTIFACT_TYPE):
        _fail(message)
    return validated


def _validate_row_sequence_identity(
    rows: Sequence[FrozenRow], identity: ArtifactIdentity
) -> ArtifactIdentity:
    validated = _validated(identity, ArtifactIdentity, "row sequence identity contract")
    expected = _records_identity(rows, _ROW_SEQUENCE_ARTIFACT_TYPE)
    if validated != expected:
        _fail("row sequence identity contract")
    return validated


def _validate_inventory_identity(identity: ArtifactIdentity, message: str) -> ArtifactIdentity:
    validated = _validated(identity, ArtifactIdentity, message)
    if (
        validated.artifact_type != _RESOURCE_INVENTORY_TYPE
        or validated.version != _RESOURCE_INVENTORY_VERSION
    ):
        _fail(message)
    return validated


class AcceptedBaselineArm:
    """Replay the exact accepted-anchor projections for fixed rows."""

    experiment_id = _ACCEPTED_EXPERIMENT_ID
    config_id = _ACCEPTED_CONFIG_ID

    def __init__(
        self,
        rows: Sequence[FrozenRow],
        accepted_predictions: Sequence[RowPrediction],
        artifact_identity: ArtifactIdentity,
    ) -> None:
        validated_rows = _validated_rows(rows)
        validated_predictions = tuple(
            _validated(value, RowPrediction, "invalid accepted prediction input")
            for value in accepted_predictions
        )
        self._artifact_identity = _validate_stream_identity(
            validated_predictions,
            artifact_identity,
            "accepted prediction artifact identity contract",
        )

        rows_by_id = {_identity(row): row for row in validated_rows}
        predictions_by_id: dict[_Identity, RowPrediction] = {}
        original_by_id: dict[_Identity, RowPrediction] = {}
        for validated, original in zip(validated_predictions, accepted_predictions, strict=True):
            identity = _identity(validated)
            if identity in predictions_by_id:
                _fail("accepted prediction identity contract")
            predictions_by_id[identity] = validated
            original_by_id[identity] = original
        if not set(rows_by_id) <= set(predictions_by_id):
            _fail("accepted prediction identity contract")
        for prediction in predictions_by_id.values():
            if (
                prediction.experiment_id != self.experiment_id
                or prediction.config_id != self.config_id
            ):
                _fail("accepted prediction metadata contract")
        for identity, row in rows_by_id.items():
            if predictions_by_id[identity].predicted_type is not row.baseline_type:
                _fail("accepted prediction metadata contract")

        self._rows = rows_by_id
        self._predictions = {identity: original_by_id[identity] for identity in rows_by_id}

    @property
    def artifact_identity(self) -> ArtifactIdentity:
        return self._artifact_identity

    def predict(self, row: FrozenRow) -> RowPrediction:
        validated = _validated(row, FrozenRow, "invalid frozen row input")
        identity = _identity(validated)
        expected = self._rows.get(identity)
        if expected is None or validated != expected:
            _fail("accepted prediction row identity contract")
        return self._predictions[identity]


def _page_config_id(config_id: str) -> str:
    return f"{_PAGE_EVIDENCE_VERSION}:{config_id}"


def _atom_id(
    record: PageEvidenceRecord,
    row: FrozenRow,
    word: PageWord,
    clipped_bbox: BBox,
) -> str:
    payload = json.dumps(
        {
            "bbox": clipped_bbox,
            "confidence": word.confidence,
            "config_id": record.config_id,
            "evidence_version": record.evidence_version,
            "ordinal": word.ordinal,
            "row_id": row.row_id,
            "source": word.source,
            "text": word.text,
        },
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class _PageBaselineArm:
    experiment_id: _PageMode

    def __init__(
        self,
        rows: Sequence[FrozenRow],
        page_evidence: Sequence[PageEvidenceRecord],
        artifact_identity: ArtifactIdentity,
        *,
        runtime_identity: ArtifactIdentity | None = None,
    ) -> None:
        validated_rows = _validated_rows(rows)
        validated_pages = tuple(
            _validated(value, PageEvidenceRecord, "invalid page evidence input")
            for value in page_evidence
        )
        self._artifact_identity = _validate_stream_identity(
            validated_pages,
            artifact_identity,
            "page evidence artifact identity contract",
        )
        if not validated_pages:
            _fail("page evidence completeness contract")

        configs = {record.config_id for record in validated_pages}
        runtimes = {record.runtime_identity for record in validated_pages}
        if len(configs) != 1:
            _fail("page evidence config identity contract")
        if len(runtimes) != 1:
            _fail("page evidence runtime identity contract")
        stream_runtime = next(iter(runtimes))
        if runtime_identity is not None:
            expected_runtime = _validated(
                runtime_identity,
                ArtifactIdentity,
                "page evidence runtime identity contract",
            )
            if stream_runtime != expected_runtime:
                _fail("page evidence runtime identity contract")
        self._runtime_identity = stream_runtime
        self.config_id = _page_config_id(next(iter(configs)))

        pages_by_id: dict[_PageIdentity, PageEvidenceRecord] = {}
        for record in validated_pages:
            if record.mode != self.experiment_id:
                _fail("page evidence mode contract")
            if not _valid_bbox(record.page_bbox):
                _fail("invalid page evidence geometry")
            if tuple(word.ordinal for word in record.words) != tuple(range(len(record.words))):
                _fail("page evidence ordinal contract")
            for word in record.words:
                if not _valid_bbox(word.bbox) or not _contains(record.page_bbox, word.bbox):
                    _fail("invalid page word geometry")
                if self.experiment_id == _FORCED_EXPERIMENT_ID and word.source != "ocr":
                    _fail("forced page evidence source contract")
            identity = (record.document_id, record.page_number)
            if identity in pages_by_id:
                _fail("duplicate page evidence identity")
            pages_by_id[identity] = record

        expected_pages = {(row.document_id, row.page_number) for row in validated_rows}
        if set(pages_by_id) != expected_pages:
            _fail("page evidence completeness contract")
        for row in validated_rows:
            record = pages_by_id[(row.document_id, row.page_number)]
            if not _contains(record.page_bbox, row.bbox):
                _fail("fixed row page geometry contract")

        self._rows = {_identity(row): row for row in validated_rows}
        self._assigned = self._assign_words(validated_rows, pages_by_id)

    @property
    def artifact_identity(self) -> ArtifactIdentity:
        return self._artifact_identity

    @property
    def runtime_identity(self) -> ArtifactIdentity:
        return self._runtime_identity

    def _assign_words(
        self,
        rows: Sequence[FrozenRow],
        pages: dict[_PageIdentity, PageEvidenceRecord],
    ) -> dict[_Identity, tuple[EvidenceAtom, ...]]:
        by_page: dict[_PageIdentity, list[FrozenRow]] = {}
        for row in rows:
            by_page.setdefault((row.document_id, row.page_number), []).append(row)
        assigned: dict[_Identity, list[EvidenceAtom]] = {_identity(row): [] for row in rows}
        atom_ids: set[str] = set()

        for page_identity in sorted(pages):
            record = pages[page_identity]
            page_rows = by_page[page_identity]
            for word in record.words:
                candidates = tuple(
                    row for row in page_rows if _center_inside(row.bbox, _center(word.bbox))
                )
                if len(candidates) > 1:
                    _fail("page word row collision")
                if not candidates:
                    continue
                row = candidates[0]
                clipped_bbox = _clip(word.bbox, row.bbox)
                clipped_center = _center(clipped_bbox)
                band_candidates = tuple(
                    band
                    for band in row.column_bands
                    if _horizontal_center_inside(band.bbox, clipped_center[0])
                )
                if len(band_candidates) > 1:
                    _fail("page word band collision")
                if not band_candidates:
                    continue
                band = band_candidates[0]
                atom_id = _atom_id(record, row, word, clipped_bbox)
                if atom_id in atom_ids:
                    _fail("page evidence atom ownership contract")
                atom_ids.add(atom_id)
                assigned[_identity(row)].append(
                    EvidenceAtom(
                        atom_id=atom_id,
                        text=word.text,
                        bbox=clipped_bbox,
                        source=word.source,
                        confidence=word.confidence,
                        column_index=band.index,
                    )
                )
        return {identity: tuple(atoms) for identity, atoms in assigned.items()}

    def _base_prediction(
        self,
        row: FrozenRow,
        atoms: tuple[EvidenceAtom, ...],
        proposals: tuple[FieldProposal, ...],
        decision: Decision,
        reason: str,
    ) -> RowPrediction:
        return RowPrediction(
            experiment_id=self.experiment_id,
            config_id=self.config_id,
            document_id=row.document_id,
            row_id=row.row_id,
            predicted_type=row.baseline_type,
            evidence_atoms=atoms,
            proposals=proposals,
            exact_row_confidence=None,
            decision=decision,
            reasons=(reason,),
        )

    def predict(self, row: FrozenRow) -> RowPrediction:
        validated = _validated(row, FrozenRow, "invalid frozen row input")
        identity = _identity(validated)
        expected = self._rows.get(identity)
        if expected is None or validated != expected:
            _fail("page prediction row identity contract")
        atoms = self._assigned[identity]
        if validated.baseline_type is RowType.STRUCTURAL:
            return self._base_prediction(
                validated,
                atoms,
                (),
                Decision.IGNORE,
                "page_baseline_structural_row",
            )
        if validated.baseline_type is RowType.AMBIGUOUS:
            return self._base_prediction(
                validated,
                atoms,
                (),
                Decision.ABSTAIN,
                "page_baseline_ambiguous_row",
            )
        if validated.baseline_type is RowType.CONTINUATION and validated.previous_row_id is None:
            return self._base_prediction(
                validated,
                atoms,
                (),
                Decision.ABSTAIN,
                "page_baseline_continuation_without_previous_row",
            )

        atoms_by_band: dict[int, list[EvidenceAtom]] = {}
        for atom in atoms:
            assert atom.column_index is not None
            atoms_by_band.setdefault(atom.column_index, []).append(atom)
        proposal_specs: list[tuple[FieldRole, tuple[EvidenceAtom, ...]]] = []
        seen_roles: set[FieldRole] = set()
        for band in sorted(validated.column_bands, key=lambda value: value.index):
            band_atoms = tuple(atoms_by_band.get(band.index, ()))
            if not band_atoms or band.role is None:
                continue
            if band.role in seen_roles:
                return self._base_prediction(
                    validated,
                    atoms,
                    (),
                    Decision.ABSTAIN,
                    "page_baseline_duplicate_role",
                )
            seen_roles.add(band.role)
            proposal_specs.append((band.role, band_atoms))

        if not proposal_specs:
            return self._base_prediction(
                validated,
                atoms,
                (),
                Decision.ABSTAIN,
                "page_baseline_no_supported_field",
            )

        owner = (
            validated.previous_row_id if validated.baseline_type is RowType.CONTINUATION else None
        )
        proposals = tuple(
            FieldProposal(
                role=role,
                atom_ids=tuple(atom.atom_id for atom in band_atoms),
                owner_row_id=owner,
                raw_score=min(atom.confidence for atom in band_atoms),
            )
            for role, band_atoms in proposal_specs
        )
        provisional = self._base_prediction(
            validated,
            atoms,
            proposals,
            Decision.ABSTAIN,
            "page_baseline_candidate",
        )
        try:
            for proposal in proposals:
                resolve_proposal(provisional, proposal)
        except EvidenceContractError:
            return self._base_prediction(
                validated,
                atoms,
                (),
                Decision.ABSTAIN,
                "page_baseline_unresolved_proposal",
            )
        return self._base_prediction(
            validated,
            atoms,
            proposals,
            Decision.ACCEPT,
            "page_baseline_supported_fields",
        )


class ConditionalPageOcrArm(_PageBaselineArm):
    experiment_id: Literal["conditional-page-ocr"] = _CONDITIONAL_EXPERIMENT_ID


class ForcedPageOcrArm(_PageBaselineArm):
    experiment_id: Literal["forced-page-ocr"] = _FORCED_EXPERIMENT_ID


class _BaselineArmFactory:
    def __init__(
        self,
        rows: Sequence[FrozenRow],
        arm_manifest_identity: ArtifactIdentity,
        *,
        row_sequence_identity: ArtifactIdentity,
        runtime_identity: ArtifactIdentity,
        model_inventory_identity: ArtifactIdentity,
        dependency_inventory_identity: ArtifactIdentity,
        cache_root: Path,
        experiment_id: str,
        config_id: str,
        resource_basis: _ResourceBasis,
    ) -> None:
        validated_rows = _validated_rows(rows)
        self._rows = validated_rows
        self._row_sequence_identity = _validate_row_sequence_identity(
            validated_rows, row_sequence_identity
        )
        self._runtime_identity = _validated(
            runtime_identity, ArtifactIdentity, "runtime identity contract"
        )
        self._model_inventory_identity = _validate_inventory_identity(
            model_inventory_identity, "model inventory identity contract"
        )
        self._dependency_inventory_identity = _validate_inventory_identity(
            dependency_inventory_identity, "dependency inventory identity contract"
        )
        self._arm_manifest_identity = _validated(
            arm_manifest_identity, ArtifactIdentity, "arm manifest identity contract"
        )
        self._cache_root = cache_root
        self._experiment_id = experiment_id
        self._config_id = config_id
        self._resource_basis = resource_basis
        self._split = validated_rows[0].split

    @property
    def experiment_id(self) -> str:
        return self._experiment_id

    @property
    def config_id(self) -> str:
        return self._config_id

    @property
    def row_sequence_identity(self) -> ArtifactIdentity:
        return self._row_sequence_identity

    @property
    def expected_row_count(self) -> int:
        return len(self._rows)

    @property
    def split(self) -> DatasetSplit:
        return self._split

    @property
    def arm_manifest_identity(self) -> ArtifactIdentity:
        return self._arm_manifest_identity

    @property
    def runtime_identity(self) -> ArtifactIdentity:
        return self._runtime_identity

    @property
    def model_inventory_identity(self) -> ArtifactIdentity:
        return self._model_inventory_identity

    @property
    def dependency_inventory_identity(self) -> ArtifactIdentity:
        return self._dependency_inventory_identity

    @property
    def cache_root(self) -> Path:
        return self._cache_root

    @property
    def resource_basis(self) -> _ResourceBasis:
        return self._resource_basis

    @property
    def worker_count(self) -> Literal[1]:
        return 1

    @property
    def subprocess_count(self) -> int:
        return 0


class AcceptedBaselineArmFactory(_BaselineArmFactory):
    def __init__(
        self,
        rows: Sequence[FrozenRow],
        accepted_predictions: Sequence[RowPrediction],
        artifact_identity: ArtifactIdentity,
        *,
        row_sequence_identity: ArtifactIdentity,
        runtime_identity: ArtifactIdentity,
        model_inventory_identity: ArtifactIdentity,
        dependency_inventory_identity: ArtifactIdentity,
        cache_root: Path,
    ) -> None:
        self._accepted_predictions = tuple(accepted_predictions)
        super().__init__(
            rows,
            artifact_identity,
            row_sequence_identity=row_sequence_identity,
            runtime_identity=runtime_identity,
            model_inventory_identity=model_inventory_identity,
            dependency_inventory_identity=dependency_inventory_identity,
            cache_root=cache_root,
            experiment_id=_ACCEPTED_EXPERIMENT_ID,
            config_id=_ACCEPTED_CONFIG_ID,
            resource_basis="materialized-adapter",
        )

    def build(self) -> ExperimentArm:
        return AcceptedBaselineArm(
            self._rows,
            self._accepted_predictions,
            self.arm_manifest_identity,
        )


class _PageBaselineArmFactory(_BaselineArmFactory):
    arm_type: type[_PageBaselineArm]
    mode: _PageMode

    def __init__(
        self,
        rows: Sequence[FrozenRow],
        page_evidence: Sequence[PageEvidenceRecord],
        artifact_identity: ArtifactIdentity,
        *,
        row_sequence_identity: ArtifactIdentity,
        runtime_identity: ArtifactIdentity,
        model_inventory_identity: ArtifactIdentity,
        dependency_inventory_identity: ArtifactIdentity,
        cache_root: Path,
    ) -> None:
        self._page_evidence = tuple(page_evidence)
        validated_pages = tuple(
            _validated(value, PageEvidenceRecord, "invalid page evidence input")
            for value in page_evidence
        )
        if not validated_pages:
            _fail("page evidence completeness contract")
        if any(record.mode != self.mode for record in validated_pages):
            _fail("page evidence mode contract")
        configs = {record.config_id for record in validated_pages}
        runtimes = {record.runtime_identity for record in validated_pages}
        if len(configs) != 1:
            _fail("page evidence config identity contract")
        if runtimes != {runtime_identity}:
            _fail("page evidence runtime identity contract")
        super().__init__(
            rows,
            artifact_identity,
            row_sequence_identity=row_sequence_identity,
            runtime_identity=runtime_identity,
            model_inventory_identity=model_inventory_identity,
            dependency_inventory_identity=dependency_inventory_identity,
            cache_root=cache_root,
            experiment_id=self.mode,
            config_id=_page_config_id(next(iter(configs))),
            resource_basis="end-to-end-method",
        )

    def build(self) -> ExperimentArm:
        return self.arm_type(
            self._rows,
            self._page_evidence,
            self.arm_manifest_identity,
            runtime_identity=self.runtime_identity,
        )


class ConditionalPageOcrArmFactory(_PageBaselineArmFactory):
    arm_type = ConditionalPageOcrArm
    mode: Literal["conditional-page-ocr"] = _CONDITIONAL_EXPERIMENT_ID


class ForcedPageOcrArmFactory(_PageBaselineArmFactory):
    arm_type = ForcedPageOcrArm
    mode: Literal["forced-page-ocr"] = _FORCED_EXPERIMENT_ID


__all__ = [
    "AcceptedBaselineArm",
    "AcceptedBaselineArmFactory",
    "BaselineContractError",
    "ConditionalPageOcrArm",
    "ConditionalPageOcrArmFactory",
    "ForcedPageOcrArm",
    "ForcedPageOcrArmFactory",
    "PageEvidenceRecord",
    "PageWord",
]
