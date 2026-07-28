from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import fitz
import pytest

from ccparser.models import (
    DiscoveryCellSummary,
    DiscoveryColumnSummary,
    DiscoveryGlyphSummary,
    DiscoveryRowSummary,
    DiscoveryTableSchemaSummary,
    DiscoveryWordSummary,
    EvidenceReference,
    RowNormalizationSummary,
    StatementDiscoverySummary,
    StatementResult,
    Status,
    TableRegionSummary,
    Transaction,
    TransactionKind,
)
from experiments.row_extraction.bundle import (
    BundlePreparationError,
    baseline_predictions_from_statement,
    fixed_row_id,
    prepare_bundle,
    rows_from_statement,
)
from experiments.row_extraction.codecs import read_jsonl
from experiments.row_extraction.contracts import (
    DatasetSplit,
    FieldRole,
    FrozenRow,
    RowPrediction,
    RowType,
)
from experiments.row_extraction.crops import CropRecord

_DOCUMENT_ID = "a" * 64


def _synthetic_pdf(path: Path) -> Path:
    with fitz.open() as document:
        page = document.new_page(width=200, height=100)
        page.insert_text((10, 27), "01/02/2026 SYNTHETIC MERCHANT ILS 12.34")
        page.insert_text((50, 38), "EXTRA")
        document.save(path)
    return path


def _word(
    text: str,
    bbox: tuple[float, float, float, float],
    *,
    source: str = "digital",
    confidence: float = 0.9,
) -> DiscoveryWordSummary:
    return DiscoveryWordSummary(
        text=text,
        bbox=bbox,
        source=source,
        confidence=confidence,
    )


def _cell(word: DiscoveryWordSummary) -> DiscoveryCellSummary:
    return DiscoveryCellSummary(
        page_number=1,
        bbox=word.bbox,
        text=word.text,
        words=(word,),
        confidence=word.confidence,
    )


def _row(*words: DiscoveryWordSummary) -> DiscoveryRowSummary:
    return DiscoveryRowSummary(
        page_number=1,
        bbox=(
            10.0,
            min(word.bbox[1] for word in words),
            190.0,
            max(word.bbox[3] for word in words),
        ),
        cells=tuple(_cell(word) for word in words),
        words=words,
        confidence=min(word.confidence for word in words),
    )


def _synthetic_statement(*, duplicate_row: bool = False) -> StatementResult:
    header_word = _word("HEADER", (10.0, 10.0, 50.0, 18.0))
    header = _row(header_word)
    first = _row(
        _word("2026-02-01", (10.0, 20.0, 42.0, 30.0)),
        _word("SYNTHETIC MERCHANT", (50.0, 20.0, 130.0, 30.0), confidence=0.8),
        _word("ILS", (150.0, 20.0, 165.0, 30.0), source="ocr", confidence=0.7),
        _word("12.34", (167.0, 20.0, 190.0, 30.0), source="ocr", confidence=0.7),
    )
    continuation = _row(_word("EXTRA", (50.0, 31.0, 80.0, 41.0), confidence=0.75))
    rows = (first, first) if duplicate_row else (first, continuation)
    columns = (
        DiscoveryColumnSummary(
            index=0,
            page_number=1,
            bbox=(10.0, 10.0, 45.0, 90.0),
            relative_x0=0.0,
            relative_x1=0.19444444444444445,
            role="date",
            confidence=0.9,
        ),
        DiscoveryColumnSummary(
            index=1,
            page_number=1,
            bbox=(45.0, 10.0, 145.0, 90.0),
            relative_x0=0.19444444444444445,
            relative_x1=0.75,
            role="description",
            confidence=0.9,
        ),
        DiscoveryColumnSummary(
            index=2,
            page_number=1,
            bbox=(145.0, 10.0, 190.0, 90.0),
            relative_x0=0.75,
            relative_x1=1.0,
            role="amount",
            confidence=0.9,
        ),
    )
    schema = DiscoveryTableSchemaSummary(
        page_number=1,
        bbox=(10.0, 10.0, 190.0, 90.0),
        columns=columns,
        header_cells=header.cells,
        sample_cells=first.cells,
        confidence=0.9,
    )
    region = TableRegionSummary(
        page_number=1,
        bbox=(10.0, 10.0, 190.0, 90.0),
        header_evidence=(),
        column_roles=tuple(column.role for column in columns),
        row_count=len(rows),
        header=header,
        rows=rows,
        table_schema=schema,
        confidence=0.9,
    )
    evidence = tuple(
        EvidenceReference(page_number=1, bbox=cell.bbox, raw_text=cell.text)
        for row in (first, continuation)
        for cell in row.cells
    )
    transaction = Transaction(
        transaction_id="synthetic-transaction",
        kind=TransactionKind.CHARGE,
        billed_amount=Decimal("12.34"),
        billing_currency="ILS",
        reconciliation_group_ids=("synthetic-group",),
        transaction_date=date(2026, 2, 1),
        description="SYNTHETIC MERCHANT EXTRA",
        evidence=evidence,
    )
    first_result = RowNormalizationSummary(
        page_number=1,
        bbox=first.bbox,
        raw_text="2026-02-01 SYNTHETIC MERCHANT ILS 12.34",
        evidence=evidence,
        transaction=transaction,
        confidence=0.8,
    )
    second_result = RowNormalizationSummary(
        page_number=1,
        bbox=continuation.bbox,
        raw_text="EXTRA",
        evidence=(evidence[-1],),
        confidence=0.75,
        diagnostics=("merged_description_continuation",),
    )
    return StatementResult(
        status=Status.UNRECONCILED,
        transactions=(transaction,),
        groups=(),
        source_sha256=_DOCUMENT_ID,
        statement_id=_DOCUMENT_ID,
        discovery=StatementDiscoverySummary(
            classification="statement",
            table_regions=(region,),
            confidence=0.9,
        ),
        row_results=(first_result, first_result)
        if duplicate_row
        else (first_result, second_result),
        normalization_confidence=0.8,
    )


def test_rows_from_statement_preserves_summary_bbox_and_count(tmp_path: Path) -> None:
    source = _synthetic_pdf(tmp_path / "source.pdf")
    statement = _synthetic_statement()

    rows = rows_from_statement(source, statement, DatasetSplit.TRAIN)
    source_rows = tuple(
        row
        for region in statement.discovery.table_regions
        for row in region.rows  # type: ignore[union-attr]
    )

    assert tuple(row.bbox for row in rows) == tuple(row.bbox for row in source_rows)
    assert len(rows) == len(source_rows) == 2
    assert rows[0].baseline_type is RowType.PRIMARY_TRANSACTION
    assert rows[1].baseline_type is RowType.CONTINUATION
    assert rows[0].next_row_id == rows[1].row_id
    assert rows[1].previous_row_id == rows[0].row_id
    assert rows[0].gap_after == rows[1].gap_before == pytest.approx(0.1)
    assert tuple(band.role for band in rows[0].column_bands) == (
        FieldRole.TRANSACTION_DATE,
        FieldRole.DESCRIPTION,
        FieldRole.BILLED_AMOUNT,
    )
    assert tuple((band.index, band.bbox) for band in rows[0].column_bands) == (
        (0, (10.0, 10.0, 45.0, 90.0)),
        (1, (45.0, 10.0, 145.0, 90.0)),
        (2, (145.0, 10.0, 190.0, 90.0)),
    )
    assert all(row.render_version == "fixed-row-rgb-ppm-300dpi-v1" for row in rows)
    assert tuple(atom.text for atom in rows[0].atoms) == (
        "2026-02-01",
        "SYNTHETIC MERCHANT",
        "ILS",
        "12.34",
    )
    assert tuple(atom.source for atom in rows[0].atoms) == (
        "digital",
        "digital",
        "ocr",
        "ocr",
    )


def test_fixed_row_id_is_stable_and_geometry_sensitive() -> None:
    first = fixed_row_id(_DOCUMENT_ID, 1, (10.0, 20.0, 190.0, 30.0))

    assert first == "e429076179e3b3eec8cdee1f41d5cee3ddffb92b983c108374ae49b34b835a20"
    assert fixed_row_id(_DOCUMENT_ID, 1, (10.0, 20.0, 190.0, 30.0)) == first
    assert fixed_row_id(_DOCUMENT_ID, 1, (10.0, 20.0, 190.0, 31.0)) != first


def test_accepted_baseline_covers_fixed_rows_and_owns_continuation(tmp_path: Path) -> None:
    source = _synthetic_pdf(tmp_path / "source.pdf")
    statement = _synthetic_statement()
    rows = rows_from_statement(source, statement, DatasetSplit.TRAIN)

    predictions = baseline_predictions_from_statement(rows, statement)

    assert tuple((item.document_id, item.row_id) for item in predictions) == tuple(
        (item.document_id, item.row_id) for item in rows
    )
    assert all(item.experiment_id == "accepted-baseline" for item in predictions)
    assert {proposal.role for proposal in predictions[0].proposals} == {
        FieldRole.TRANSACTION_DATE,
        FieldRole.BILLED_AMOUNT,
        FieldRole.BILLING_CURRENCY,
        FieldRole.KIND,
    }
    assert "accepted_baseline_omitted:description" in predictions[0].reasons
    assert predictions[1].proposals[0].role is FieldRole.DESCRIPTION
    assert predictions[1].proposals[0].owner_row_id == rows[0].row_id


def test_accepted_baseline_rejects_row_from_another_document(tmp_path: Path) -> None:
    source = _synthetic_pdf(tmp_path / "source.pdf")
    statement = _synthetic_statement()
    rows = rows_from_statement(source, statement, DatasetSplit.TRAIN)
    changed = (rows[0].model_copy(update={"document_id": "b" * 64}), rows[1])

    with pytest.raises(BundlePreparationError, match="fixed row document identity mismatch"):
        baseline_predictions_from_statement(changed, statement)


def test_accepted_baseline_rejects_forged_fixed_row_id(tmp_path: Path) -> None:
    source = _synthetic_pdf(tmp_path / "source.pdf")
    statement = _synthetic_statement()
    rows = rows_from_statement(source, statement, DatasetSplit.TRAIN)
    changed = (rows[0].model_copy(update={"row_id": "forged-row"}), rows[1])

    with pytest.raises(BundlePreparationError, match="fixed row universe mismatch"):
        baseline_predictions_from_statement(changed, statement)


def test_accepted_baseline_rejects_duplicate_row_replacing_peer(tmp_path: Path) -> None:
    source = _synthetic_pdf(tmp_path / "source.pdf")
    statement = _synthetic_statement()
    rows = rows_from_statement(source, statement, DatasetSplit.TRAIN)

    with pytest.raises(BundlePreparationError, match="fixed row universe mismatch"):
        baseline_predictions_from_statement((rows[0], rows[0]), statement)


def test_accepted_baseline_rejects_mutated_baseline_type(tmp_path: Path) -> None:
    source = _synthetic_pdf(tmp_path / "source.pdf")
    statement = _synthetic_statement()
    rows = rows_from_statement(source, statement, DatasetSplit.TRAIN)
    changed = (rows[0], rows[1].model_copy(update={"baseline_type": RowType.PRIMARY_TRANSACTION}))

    with pytest.raises(BundlePreparationError, match="fixed row universe mismatch"):
        baseline_predictions_from_statement(changed, statement)


def test_accepted_baseline_rejects_corrupted_continuation_owner(tmp_path: Path) -> None:
    source = _synthetic_pdf(tmp_path / "source.pdf")
    statement = _synthetic_statement()
    rows = rows_from_statement(source, statement, DatasetSplit.TRAIN)
    changed = (rows[0], rows[1].model_copy(update={"previous_row_id": "forged-owner"}))

    with pytest.raises(BundlePreparationError, match="fixed row universe mismatch"):
        baseline_predictions_from_statement(changed, statement)


def test_rows_from_statement_rejects_duplicate_fixed_identity(tmp_path: Path) -> None:
    source = _synthetic_pdf(tmp_path / "source.pdf")

    with pytest.raises(BundlePreparationError, match="duplicate fixed row identity"):
        rows_from_statement(source, _synthetic_statement(duplicate_row=True), DatasetSplit.TRAIN)


def test_rows_from_statement_rejects_region_row_count_mismatch(tmp_path: Path) -> None:
    source = _synthetic_pdf(tmp_path / "source.pdf")
    statement = _synthetic_statement()
    assert statement.discovery is not None
    region = statement.discovery.table_regions[0].model_copy(update={"row_count": 3})
    changed = statement.model_copy(
        update={"discovery": statement.discovery.model_copy(update={"table_regions": (region,)})}
    )

    with pytest.raises(BundlePreparationError, match="accepted region row count mismatch"):
        rows_from_statement(source, changed, DatasetSplit.TRAIN)


def test_rows_from_statement_projects_glyph_backed_cell_when_words_are_absent(
    tmp_path: Path,
) -> None:
    source = _synthetic_pdf(tmp_path / "source.pdf")
    statement = _synthetic_statement()
    assert statement.discovery is not None
    region = statement.discovery.table_regions[0]
    continuation = region.rows[1]
    glyph = DiscoveryGlyphSummary(
        char="E",
        bbox=(50.0, 31.0, 55.0, 41.0),
        origin=(50.0, 39.0),
        font="Synthetic",
        size=10.0,
        source="digital",
        confidence=0.72,
    )
    glyph_cell = continuation.cells[0].model_copy(update={"words": (), "glyphs": (glyph,)})
    glyph_row = continuation.model_copy(update={"words": (), "cells": (glyph_cell,)})
    changed_region = region.model_copy(update={"rows": (region.rows[0], glyph_row)})
    changed = statement.model_copy(
        update={
            "discovery": statement.discovery.model_copy(update={"table_regions": (changed_region,)})
        }
    )

    rows = rows_from_statement(source, changed, DatasetSplit.TRAIN)

    assert tuple(atom.text for atom in rows[1].atoms) == ("EXTRA",)
    assert rows[1].atoms[0].bbox == glyph_cell.bbox
    assert rows[1].atoms[0].confidence == pytest.approx(0.72)


@pytest.mark.parametrize(
    ("diagnostics", "expected"),
    (
        (("merged_description_continuation",), RowType.CONTINUATION),
        (("merged_subordinate_detail_continuation",), RowType.CONTINUATION),
        (("merged_auxiliary_continuation",), RowType.CONTINUATION),
        (("unowned_leading_subordinate_detail_continuation",), RowType.CONTINUATION),
        (("printed_total_row",), RowType.STRUCTURAL),
        (("unresolved_relevant_cell",), RowType.AMBIGUOUS),
    ),
)
def test_rows_from_statement_projects_closed_baseline_types(
    tmp_path: Path,
    diagnostics: tuple[str, ...],
    expected: RowType,
) -> None:
    source = _synthetic_pdf(tmp_path / "source.pdf")
    statement = _synthetic_statement()
    second_result = statement.row_results[1].model_copy(update={"diagnostics": diagnostics})
    changed = statement.model_copy(
        update={"row_results": (statement.row_results[0], second_result)}
    )

    rows = rows_from_statement(source, changed, DatasetSplit.TRAIN)

    assert rows[0].baseline_type is RowType.PRIMARY_TRANSACTION
    assert rows[1].baseline_type is expected


def test_rows_from_statement_rejects_out_of_page_bbox(tmp_path: Path) -> None:
    source = _synthetic_pdf(tmp_path / "source.pdf")
    statement = _synthetic_statement()
    assert statement.discovery is not None
    region = statement.discovery.table_regions[0]
    outside = region.rows[0].model_copy(update={"bbox": (10.0, 20.0, 210.0, 30.0)})
    changed_region = region.model_copy(update={"rows": (outside, region.rows[1])})
    changed = statement.model_copy(
        update={
            "discovery": statement.discovery.model_copy(update={"table_regions": (changed_region,)})
        }
    )

    with pytest.raises(BundlePreparationError, match="fixed row bbox is outside source page"):
        rows_from_statement(source, changed, DatasetSplit.TRAIN)


class _SinglePassSources:
    def __init__(self, source: Path) -> None:
        self._source = source
        self._iterated = False

    def __iter__(self) -> Iterator[Path]:
        if self._iterated:
            raise AssertionError("sources were materialized or iterated more than once")
        self._iterated = True
        yield self._source


def test_prepare_bundle_streams_separate_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _synthetic_pdf(tmp_path / "source.pdf")
    statement = _synthetic_statement()
    monkeypatch.setattr(
        "experiments.row_extraction.bundle.parse_statement",
        lambda path: statement,
    )
    destination = tmp_path / "private-bundle"

    prepared = prepare_bundle(
        _SinglePassSources(source),
        destination,
        {_DOCUMENT_ID: DatasetSplit.VALIDATION},
    )

    rows = tuple(read_jsonl(destination / "rows.jsonl", FrozenRow))
    predictions = tuple(read_jsonl(destination / "accepted_predictions.jsonl", RowPrediction))
    crops = tuple(read_jsonl(destination / "crop_index.jsonl", CropRecord))
    assert len(rows) == len(predictions) == len(crops) == 2
    assert all(row.split is DatasetSplit.VALIDATION for row in rows)
    assert prepared.rows.byte_size == (destination / "rows.jsonl").stat().st_size
    assert (
        prepared.accepted_predictions.byte_size
        == (destination / "accepted_predictions.jsonl").stat().st_size
    )
    assert prepared.crop_index.byte_size == (destination / "crop_index.jsonl").stat().st_size


def test_prepare_bundle_rejects_document_without_frozen_split(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _synthetic_pdf(tmp_path / "source.pdf")
    monkeypatch.setattr(
        "experiments.row_extraction.bundle.parse_statement",
        lambda path: _synthetic_statement(),
    )

    with pytest.raises(BundlePreparationError, match="document split is not frozen"):
        prepare_bundle((source,), tmp_path / "private-bundle", {})


def test_prepare_bundle_rejects_duplicate_document_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _synthetic_pdf(tmp_path / "source.pdf")
    monkeypatch.setattr(
        "experiments.row_extraction.bundle.parse_statement",
        lambda path: _synthetic_statement(),
    )

    with pytest.raises(BundlePreparationError, match="duplicate document identity"):
        prepare_bundle(
            (source, source),
            tmp_path / "private-bundle",
            {_DOCUMENT_ID: DatasetSplit.TRAIN},
        )
