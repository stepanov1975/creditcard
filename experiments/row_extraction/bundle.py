"""Prepare identical accepted-anchor row observations for every experiment lane."""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Literal

import fitz  # type: ignore[import-untyped]  # PyMuPDF does not publish typing metadata.

from ccparser.decimal_math import plain_decimal_string
from ccparser.models import (
    DiscoveryColumnSummary,
    DiscoveryGlyphSummary,
    DiscoveryRowSummary,
    DiscoveryWordSummary,
    EvidenceReference,
    RowNormalizationSummary,
    StatementResult,
    Transaction,
)
from ccparser.money import canonical_currency
from ccparser.parser import parse_statement
from ccparser.text_tokens import normalize_text
from experiments.row_extraction.codecs import read_jsonl, write_jsonl
from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    BBox,
    ColumnBand,
    DatasetSplit,
    Decision,
    EvidenceAtom,
    FieldProposal,
    FieldRole,
    FrozenRow,
    RowPrediction,
    RowType,
    _FrozenModel,
)
from experiments.row_extraction.crops import CropRecord, render_reference_crop
from experiments.row_extraction.evidence import EvidenceContractError, resolve_proposal

_RENDER_VERSION = "fixed-row-rgb-ppm-300dpi-v1"
_BASELINE_EXPERIMENT_ID = "accepted-baseline"
_BASELINE_CONFIG_ID = "accepted-anchor"

type _AtomObservation = tuple[str, BBox, Literal["digital", "ocr"], float]

_COLUMN_ROLES: dict[str, FieldRole | None] = {
    "unknown": None,
    "date": FieldRole.TRANSACTION_DATE,
    "conversion_date": FieldRole.CONVERSION_DATE,
    "description": FieldRole.DESCRIPTION,
    "location": FieldRole.ANCILLARY,
    "amount": FieldRole.BILLED_AMOUNT,
    "auxiliary_amount": FieldRole.ANCILLARY,
    "exchange_rate": FieldRole.FX_RATE,
    "original_amount": FieldRole.ORIGINAL_AMOUNT,
    "currency": FieldRole.BILLING_CURRENCY,
    "billing_currency": FieldRole.BILLING_CURRENCY,
    "original_currency": FieldRole.ORIGINAL_CURRENCY,
    "installment": FieldRole.INSTALLMENT,
}


class BundlePreparationError(ValueError):
    """Accepted summaries cannot be projected without violating the fixed-row contract."""


class PreparedBundle(_FrozenModel):
    """Identities of the three private, independently consumable bundle streams."""

    rows: ArtifactIdentity
    accepted_predictions: ArtifactIdentity
    crop_index: ArtifactIdentity


def fixed_row_id(document_id: str, page_number: int, bbox: BBox) -> str:
    """Derive an opaque stable identity from immutable accepted row geometry."""

    payload = json.dumps(
        [document_id, page_number, *bbox],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _fixed_atom_id(
    row_id: str,
    text: str,
    bbox: BBox,
    source: str,
    confidence: float,
    column_index: int | None,
) -> str:
    payload = json.dumps(
        [row_id, text, *bbox, source, confidence, column_index],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _intersection_width(first: BBox, second: BBox) -> float:
    return max(0.0, min(first[2], second[2]) - max(first[0], second[0]))


def _column_index(bbox: BBox, bands: Sequence[ColumnBand]) -> int | None:
    candidates = tuple(
        (width, band.index) for band in bands if (width := _intersection_width(bbox, band.bbox)) > 0
    )
    if not candidates:
        return None
    return min(candidates, key=lambda item: (-item[0], item[1]))[1]


def _column_bands(columns: Sequence[DiscoveryColumnSummary]) -> tuple[ColumnBand, ...]:
    bands: list[ColumnBand] = []
    for column in columns:
        index = column.index
        role_name = column.role
        bbox = column.bbox
        if role_name not in _COLUMN_ROLES:
            raise BundlePreparationError("unknown accepted column role")
        bands.append(ColumnBand(index=index, role=_COLUMN_ROLES[role_name], bbox=bbox))
    return tuple(bands)


def _word_key(word: DiscoveryWordSummary) -> _AtomObservation:
    return (word.text, word.bbox, word.source, word.confidence)


def _glyph_fallback(
    cell_glyphs: Sequence[DiscoveryGlyphSummary], text: str, bbox: BBox, confidence: float
) -> _AtomObservation | None:
    if not cell_glyphs:
        return None
    source: Literal["digital", "ocr"] = (
        "ocr" if any(glyph.source == "ocr" for glyph in cell_glyphs) else "digital"
    )
    return (text, bbox, source, min(confidence, *(glyph.confidence for glyph in cell_glyphs)))


def _row_atoms(
    row: DiscoveryRowSummary, row_id: str, bands: Sequence[ColumnBand]
) -> tuple[EvidenceAtom, ...]:
    observations: list[_AtomObservation] = []
    seen: set[_AtomObservation] = set()
    for word in (*row.words, *(word for cell in row.cells for word in cell.words)):
        value = _word_key(word)
        if value not in seen:
            seen.add(value)
            observations.append(value)
    for cell in row.cells:
        if cell.words:
            continue
        fallback = _glyph_fallback(cell.glyphs, cell.text, cell.bbox, cell.confidence)
        if fallback is not None and fallback not in seen:
            seen.add(fallback)
            observations.append(fallback)

    atoms: list[EvidenceAtom] = []
    for text, bbox, source, confidence in observations:
        column_index = _column_index(bbox, bands)
        atoms.append(
            EvidenceAtom(
                atom_id=_fixed_atom_id(
                    row_id,
                    text,
                    bbox,
                    source,
                    confidence,
                    column_index,
                ),
                text=text,
                bbox=bbox,
                source=source,
                confidence=confidence,
                column_index=column_index,
            )
        )
    return tuple(atoms)


def _row_key(page_number: int, bbox: BBox) -> tuple[int, BBox]:
    return (page_number, bbox)


def _normalization_rows(result: StatementResult) -> dict[tuple[int, BBox], RowNormalizationSummary]:
    values: dict[tuple[int, BBox], RowNormalizationSummary] = {}
    for row in result.row_results:
        key = _row_key(row.page_number, row.bbox)
        if key in values:
            raise BundlePreparationError("duplicate accepted normalization row")
        values[key] = row
    return values


def _baseline_type(row: RowNormalizationSummary) -> RowType:
    if row.transaction is not None:
        return RowType.PRIMARY_TRANSACTION
    if any(
        diagnostic == "unowned_leading_subordinate_detail_continuation"
        or (diagnostic.startswith("merged_") and diagnostic.endswith("_continuation"))
        for diagnostic in row.diagnostics
    ):
        return RowType.CONTINUATION
    if "printed_total_row" in row.diagnostics:
        return RowType.STRUCTURAL
    return RowType.AMBIGUOUS


def _validate_source_rows(source_pdf: Path, rows: Sequence[DiscoveryRowSummary]) -> None:
    try:
        with fitz.open(source_pdf) as document:
            for row in rows:
                if row.page_number > document.page_count:
                    raise BundlePreparationError("fixed row page is absent from source PDF")
                rect = fitz.Rect(row.bbox)
                if (
                    rect.is_empty
                    or rect.is_infinite
                    or not document[row.page_number - 1].rect.contains(rect)
                ):
                    raise BundlePreparationError("fixed row bbox is outside source page")
    except BundlePreparationError:
        raise
    except Exception:
        raise BundlePreparationError("source PDF cannot be inspected") from None


def _normalized_gap(first: FrozenRow, second_bbox: BBox, second_page: int) -> float | None:
    if first.page_number != second_page:
        return None
    denominator = max(first.bbox[3] - first.bbox[1], second_bbox[3] - second_bbox[1])
    if denominator <= 0:
        raise BundlePreparationError("fixed row bbox has no height")
    return max(0.0, second_bbox[1] - first.bbox[3]) / denominator


def rows_from_statement(
    source_pdf: Path,
    result: StatementResult,
    split: DatasetSplit,
) -> tuple[FrozenRow, ...]:
    """Project fixed discovery rows without detecting, moving, merging, or splitting rows."""

    if result.discovery is None:
        raise BundlePreparationError("accepted discovery summary is absent")
    if result.source_sha256 is None:
        raise BundlePreparationError("accepted source identity is absent")
    source_rows = tuple(
        (row, region.table_schema.columns)
        for region in result.discovery.table_regions
        for row in region.rows
    )
    if any(region.row_count != len(region.rows) for region in result.discovery.table_regions):
        raise BundlePreparationError("accepted region row count mismatch")
    if len(source_rows) != len(result.row_results):
        raise BundlePreparationError("accepted row count mismatch")
    _validate_source_rows(source_pdf, tuple(row for row, _ in source_rows))
    source_ids = tuple(
        fixed_row_id(result.source_sha256, row.page_number, row.bbox) for row, _ in source_rows
    )
    if len(source_ids) != len(set(source_ids)):
        raise BundlePreparationError("duplicate fixed row identity")
    normalization_rows = _normalization_rows(result)
    if len(normalization_rows) != len(source_rows):
        raise BundlePreparationError("accepted row count mismatch")

    partial: list[FrozenRow] = []
    seen_ids: set[str] = set()
    for source_row, columns in source_rows:
        row_id = fixed_row_id(result.source_sha256, source_row.page_number, source_row.bbox)
        if row_id in seen_ids:
            raise BundlePreparationError("duplicate fixed row identity")
        seen_ids.add(row_id)
        accepted = normalization_rows.get(_row_key(source_row.page_number, source_row.bbox))
        if accepted is None:
            raise BundlePreparationError("accepted normalization row is absent")
        bands = _column_bands(columns)
        partial.append(
            FrozenRow(
                document_id=result.source_sha256,
                row_id=row_id,
                split=split,
                source_pdf=source_pdf,
                page_number=source_row.page_number,
                bbox=source_row.bbox,
                baseline_type=_baseline_type(accepted),
                column_bands=bands,
                atoms=_row_atoms(source_row, row_id, bands),
                render_version=_RENDER_VERSION,
            )
        )

    completed: list[FrozenRow] = []
    for index, frozen in enumerate(partial):
        previous = partial[index - 1] if index else None
        following = partial[index + 1] if index + 1 < len(partial) else None
        completed.append(
            frozen.model_copy(
                update={
                    "previous_row_id": previous.row_id if previous is not None else None,
                    "next_row_id": following.row_id if following is not None else None,
                    "gap_before": (
                        _normalized_gap(previous, frozen.bbox, frozen.page_number)
                        if previous is not None
                        else None
                    ),
                    "gap_after": (
                        _normalized_gap(frozen, following.bbox, following.page_number)
                        if following is not None
                        else None
                    ),
                }
            )
        )
    return tuple(completed)


def _overlaps(first: BBox, second: BBox) -> bool:
    return min(first[2], second[2]) > max(first[0], second[0]) and min(first[3], second[3]) > max(
        first[1], second[1]
    )


def _supported_atoms(
    row: FrozenRow, evidence: Sequence[EvidenceReference]
) -> tuple[EvidenceAtom, ...]:
    return tuple(
        atom
        for atom in row.atoms
        if any(
            item.page_number == row.page_number and _overlaps(atom.bbox, item.bbox)
            for item in evidence
        )
    )


def _atom_ids_for_role(
    row: FrozenRow, atoms: Sequence[EvidenceAtom], role: FieldRole
) -> tuple[str, ...]:
    roles = {role}
    if role is FieldRole.BILLING_CURRENCY:
        roles.add(FieldRole.BILLED_AMOUNT)
    elif role is FieldRole.ORIGINAL_CURRENCY:
        roles.add(FieldRole.ORIGINAL_AMOUNT)
    elif role is FieldRole.KIND:
        roles = {FieldRole.BILLED_AMOUNT}
    band_roles = {band.index: band.role for band in row.column_bands}
    candidates = tuple(
        atom.atom_id
        for atom in atoms
        if atom.column_index is not None and band_roles.get(atom.column_index) in roles
    )
    if role in {FieldRole.BILLING_CURRENCY, FieldRole.ORIGINAL_CURRENCY}:
        ledger = {atom.atom_id: atom for atom in atoms}
        return tuple(
            atom_id
            for atom_id in candidates
            if canonical_currency(ledger[atom_id].text) is not None
        )
    return candidates


def _expected_fields(transaction: Transaction) -> dict[FieldRole, str]:
    values: dict[FieldRole, str] = {
        FieldRole.BILLED_AMOUNT: plain_decimal_string(transaction.billed_amount),
        FieldRole.BILLING_CURRENCY: transaction.billing_currency,
        FieldRole.KIND: transaction.kind.value,
    }
    optional_dates: tuple[tuple[FieldRole, date | None], ...] = (
        (FieldRole.TRANSACTION_DATE, transaction.transaction_date),
        (FieldRole.POSTING_DATE, transaction.posting_date),
        (FieldRole.CONVERSION_DATE, transaction.conversion_date),
    )
    for role, value in optional_dates:
        if value is not None:
            values[role] = value.isoformat()
    if transaction.description is not None:
        values[FieldRole.DESCRIPTION] = normalize_text(transaction.description)
    if transaction.original_amount is not None and transaction.original_currency is not None:
        values[FieldRole.ORIGINAL_AMOUNT] = plain_decimal_string(transaction.original_amount)
        values[FieldRole.ORIGINAL_CURRENCY] = transaction.original_currency
    if transaction.installment_current is not None and transaction.installment_total is not None:
        values[FieldRole.INSTALLMENT] = (
            f"{transaction.installment_current}/{transaction.installment_total}"
        )
    if (
        transaction.foreign_exchange is not None
        and transaction.foreign_exchange.exchange_rate is not None
    ):
        values[FieldRole.FX_RATE] = plain_decimal_string(
            transaction.foreign_exchange.exchange_rate.value
        )
    return values


def _proposal(
    row: FrozenRow, atoms: Sequence[EvidenceAtom], role: FieldRole, owner: str | None = None
) -> FieldProposal | None:
    atom_ids = _atom_ids_for_role(row, atoms, role)
    if not atom_ids:
        return None
    selected = tuple(atom for atom in atoms if atom.atom_id in set(atom_ids))
    return FieldProposal(
        role=role,
        atom_ids=atom_ids,
        owner_row_id=owner,
        raw_score=min(atom.confidence for atom in selected),
    )


def _base_prediction(
    row: FrozenRow,
    proposals: Sequence[FieldProposal],
    decision: Decision,
    reasons: Sequence[str],
) -> RowPrediction:
    return RowPrediction(
        experiment_id=_BASELINE_EXPERIMENT_ID,
        config_id=_BASELINE_CONFIG_ID,
        document_id=row.document_id,
        row_id=row.row_id,
        predicted_type=row.baseline_type,
        evidence_atoms=row.atoms,
        proposals=tuple(proposals),
        exact_row_confidence=None,
        decision=decision,
        reasons=tuple(reasons),
    )


def _primary_prediction(row: FrozenRow, accepted: RowNormalizationSummary) -> RowPrediction:
    assert accepted.transaction is not None
    supported = _supported_atoms(row, accepted.transaction.evidence)
    expected = _expected_fields(accepted.transaction)
    candidates = tuple(
        proposal for role in expected if (proposal := _proposal(row, supported, role)) is not None
    )
    candidate_prediction = _base_prediction(
        row,
        candidates,
        Decision.ABSTAIN,
        ("accepted_baseline_candidate",),
    )
    retained: list[FieldProposal] = []
    for proposal in candidates:
        try:
            resolved = resolve_proposal(candidate_prediction, proposal)
        except EvidenceContractError:
            continue
        if resolved.canonical_value == expected[proposal.role]:
            retained.append(proposal)
    retained_prediction = _base_prediction(
        row,
        retained,
        Decision.ABSTAIN,
        ("accepted_baseline_candidate",),
    )
    valid: list[FieldProposal] = []
    for proposal in retained:
        try:
            resolve_proposal(retained_prediction, proposal)
        except EvidenceContractError:
            continue
        valid.append(proposal)

    present_roles = {proposal.role for proposal in valid}
    missing_roles = tuple(role for role in expected if role not in present_roles)
    exact = not missing_roles and not accepted.transaction.ambiguities
    reasons = (
        ("accepted_baseline_exactly_grounded",)
        if exact
        else tuple(f"accepted_baseline_omitted:{role.value}" for role in missing_roles)
        or ("accepted_baseline_transaction_ambiguous",)
    )
    return _base_prediction(
        row,
        valid,
        Decision.ACCEPT if exact else Decision.ABSTAIN,
        reasons,
    )


def _continuation_prediction(row: FrozenRow, accepted: RowNormalizationSummary) -> RowPrediction:
    if "unowned_leading_subordinate_detail_continuation" in accepted.diagnostics:
        return _base_prediction(
            row,
            (),
            Decision.ABSTAIN,
            ("accepted_baseline_unowned_continuation",),
        )
    if row.previous_row_id is None:
        return _base_prediction(
            row,
            (),
            Decision.ABSTAIN,
            ("accepted_baseline_continuation_without_previous_row",),
        )
    supported = _supported_atoms(row, accepted.evidence)
    roles = tuple(
        dict.fromkeys(
            band.role
            for band in row.column_bands
            if band.role is not None and band.role is not FieldRole.ANCILLARY
        )
    )
    if (
        "merged_description_continuation" in accepted.diagnostics
        and FieldRole.DESCRIPTION not in roles
    ):
        roles = (FieldRole.DESCRIPTION, *roles)
    candidates: list[FieldProposal] = []
    for role in roles:
        proposal = _proposal(row, supported, role, row.previous_row_id)
        if proposal is None and role is FieldRole.DESCRIPTION and supported:
            proposal = FieldProposal(
                role=role,
                atom_ids=tuple(atom.atom_id for atom in supported),
                owner_row_id=row.previous_row_id,
                raw_score=min(atom.confidence for atom in supported),
            )
        if proposal is not None:
            candidates.append(proposal)
    provisional = _base_prediction(
        row,
        candidates,
        Decision.ABSTAIN,
        ("accepted_baseline_continuation_candidate",),
    )
    valid: list[FieldProposal] = []
    for proposal in candidates:
        try:
            resolve_proposal(provisional, proposal)
        except EvidenceContractError:
            continue
        valid.append(proposal)
    return _base_prediction(
        row,
        valid,
        Decision.ACCEPT if valid else Decision.ABSTAIN,
        (
            ("accepted_baseline_owned_continuation",)
            if valid
            else ("accepted_baseline_continuation_without_supported_field",)
        ),
    )


def baseline_predictions_from_statement(
    rows: Sequence[FrozenRow],
    result: StatementResult,
) -> tuple[RowPrediction, ...]:
    """Materialize one conservative, evidence-grounded accepted baseline per fixed row."""

    if len(rows) != len(result.row_results):
        raise BundlePreparationError("accepted row count mismatch")
    if result.source_sha256 is None or any(row.document_id != result.source_sha256 for row in rows):
        raise BundlePreparationError("fixed row document identity mismatch")
    accepted_rows = _normalization_rows(result)
    predictions: list[RowPrediction] = []
    for row in rows:
        accepted = accepted_rows.get(_row_key(row.page_number, row.bbox))
        if accepted is None:
            raise BundlePreparationError("accepted normalization row is absent")
        if row.baseline_type is RowType.PRIMARY_TRANSACTION:
            predictions.append(_primary_prediction(row, accepted))
        elif row.baseline_type is RowType.CONTINUATION:
            predictions.append(_continuation_prediction(row, accepted))
        elif row.baseline_type is RowType.STRUCTURAL:
            predictions.append(
                _base_prediction(
                    row,
                    (),
                    Decision.IGNORE,
                    ("accepted_baseline_structural_row",),
                )
            )
        else:
            predictions.append(
                _base_prediction(
                    row,
                    (),
                    Decision.ABSTAIN,
                    ("accepted_baseline_ambiguous_row",),
                )
            )
    return tuple(predictions)


def _records_from_parts[T: _FrozenModel](parts: Sequence[Path], model: type[T]) -> Iterator[T]:
    for part in parts:
        yield from read_jsonl(part, model)


def prepare_bundle(
    sources: Iterable[Path],
    destination: Path,
    split_by_document: Mapping[str, DatasetSplit],
) -> PreparedBundle:
    """Parse sources once and stream separate row, baseline, and crop-index artifacts."""

    destination.mkdir(parents=True, exist_ok=True)
    crop_root = destination / "crops"
    with tempfile.TemporaryDirectory(dir=destination, prefix=".bundle-parts-") as temporary:
        staging = Path(temporary)
        prediction_parts: list[Path] = []
        crop_parts: list[Path] = []
        seen_document_ids: set[str] = set()

        def row_records() -> Iterator[FrozenRow]:
            for ordinal, source in enumerate(sources):
                result = parse_statement(source)
                if result.source_sha256 is None or result.source_sha256 not in split_by_document:
                    raise BundlePreparationError("document split is not frozen")
                if result.source_sha256 in seen_document_ids:
                    raise BundlePreparationError("duplicate document identity")
                seen_document_ids.add(result.source_sha256)
                rows = rows_from_statement(
                    source,
                    result,
                    split_by_document[result.source_sha256],
                )
                predictions = baseline_predictions_from_statement(rows, result)
                prediction_part = staging / f"predictions-{ordinal:08d}.jsonl"
                crop_part = staging / f"crops-{ordinal:08d}.jsonl"
                write_jsonl(prediction_part, predictions)
                write_jsonl(
                    crop_part,
                    (render_reference_crop(row, crop_root) for row in rows),
                )
                prediction_parts.append(prediction_part)
                crop_parts.append(crop_part)
                yield from rows

        rows_identity = write_jsonl(destination / "rows.jsonl", row_records())
        accepted_predictions_identity = write_jsonl(
            destination / "accepted_predictions.jsonl",
            _records_from_parts(prediction_parts, RowPrediction),
        )
        crop_index_identity = write_jsonl(
            destination / "crop_index.jsonl",
            _records_from_parts(crop_parts, CropRecord),
        )
    return PreparedBundle(
        rows=rows_identity,
        accepted_predictions=accepted_predictions_identity,
        crop_index=crop_index_identity,
    )


__all__ = [
    "BundlePreparationError",
    "PreparedBundle",
    "baseline_predictions_from_statement",
    "fixed_row_id",
    "prepare_bundle",
    "rows_from_statement",
]
