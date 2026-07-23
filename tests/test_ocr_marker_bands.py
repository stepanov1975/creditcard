from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import pytest

import ccparser.layout.regions as layout_regions
from ccparser.evidence.models import (
    EvidenceSource,
    ExtractionQuality,
    PageEvidence,
    Word,
)
from ccparser.layout.columns import cells_in_column
from ccparser.layout.models import ColumnRole, ColumnSpec, TableRegion
from ccparser.layout.regions import detect_table_regions
from ccparser.normalization_dates import (
    DateColumnKind,
    DateExtraction,
    extract_dates,
    proven_assigned_date_evidence,
)
from ccparser.normalization_semantics import (
    SemanticValidation,
    assignment_diagnostics,
    validate_transaction_semantics,
)
from ccparser.semantic_evidence import EvidenceClaim, EvidenceLedger, SemanticOwner

_OCR_MARKER_BAND_DIAGNOSTIC = "stable_headerless_ocr_marker_band"
_MARKER_LABELS = ("|", "\uff5c", "||", "\uff5c\uff5c")


def _word(
    text: str,
    x0: float,
    x1: float,
    y: float,
    *,
    source: EvidenceSource = "digital",
    confidence: float | None = None,
) -> Word:
    return Word(
        text=text,
        bbox=(x0, y, x1, y + 10.0),
        source=source,
        confidence=(0.9 if source == "ocr" else 1.0) if confidence is None else confidence,
    )


def _table_page(
    markers: Sequence[str | None] = _MARKER_LABELS,
    *,
    marker_sources: Sequence[EvidenceSource] | None = None,
    marker_centers: Sequence[float] | None = None,
    marker_y_offsets: Sequence[float] | None = None,
    glued: bool = False,
    explicit_financial_header: bool = False,
    second_date: bool = False,
) -> PageEvidence:
    if len(markers) != 4:
        raise ValueError("synthetic table requires four rows")
    sources = marker_sources or tuple("ocr" for _ in markers)
    centers = marker_centers or (49.0, 49.4, 48.7, 49.2)
    y_offsets = marker_y_offsets or tuple(0.0 for _ in markers)
    words = [
        _word("Description", 5.0, 32.0, 10.0),
        _word("Date", 65.0, 83.0, 10.0),
        _word("Amount", 112.0, 140.0, 10.0),
    ]
    if explicit_financial_header:
        words.append(_word("Exchange rate", 38.0, 55.0, 10.0))

    for index, (marker, marker_source, marker_center, marker_y_offset) in enumerate(
        zip(markers, sources, centers, y_offsets, strict=True)
    ):
        y = 32.0 + index * 18.0
        words.append(_word(f"Merchant {chr(ord('A') + index)}", 5.0, 31.0, y))
        date_text = f"{index + 1:02d}/02/2026"
        if glued and marker is not None:
            words.append(_word(f"{marker}{date_text}", 47.0, 82.0, y, source="ocr"))
        else:
            if marker is not None:
                words.append(
                    _word(
                        marker,
                        marker_center - 2.0,
                        marker_center + 2.0,
                        y + marker_y_offset,
                        source=marker_source,
                    )
                )
            date_x0 = 65.0 if explicit_financial_header else 54.0
            date_x1 = 91.0 if explicit_financial_header else 82.0
            words.append(_word(date_text, date_x0, date_x1, y, source="ocr"))
        if second_date:
            words.append(_word(f"{index + 5:02d}/03/2026", 84.0, 108.0, y, source="ocr"))
        words.append(_word(f"{index + 1}0.00", 116.0, 140.0, y))

    return PageEvidence(
        page_number=1,
        width=150.0,
        height=130.0,
        words=tuple(words),
        quality=ExtractionQuality(
            character_count=0,
            usable_character_count=0,
            word_count=len(words),
            replacement_character_ratio=0.0,
            control_character_ratio=0.0,
            image_area_ratio=0.8,
            requires_ocr=True,
            reasons=("image_dominant",),
        ),
    )


def _sparse_right_marker_page(
    *,
    standalone_words: tuple[tuple[str, EvidenceSource], ...] = (("\uff5c\uff5c", "ocr"),),
) -> PageEvidence:
    words = [
        _word("Description", 5.0, 32.0, 10.0),
        _word("Date", 50.0, 70.0, 10.0),
        _word("Amount", 112.0, 140.0, 10.0),
    ]
    supporting_markers = {0: "|", 3: "\uff5c", 6: "||"}
    for index in range(9):
        y = 32.0 + index * 14.0
        words.append(_word(f"Merchant {chr(ord('A') + index)}", 5.0, 31.0, y))
        if index != 8:
            words.append(_word(f"{index + 1:02d}/02/2026", 50.0, 76.0, y, source="ocr"))
        if marker := supporting_markers.get(index):
            words.append(_word(marker, 79.0, 83.0, y, source="ocr"))
        if index == 8:
            x0 = 79.0
            for text, source in standalone_words:
                width = 5.0 if len(standalone_words) > 1 else 8.0
                words.append(_word(text, x0, x0 + width, y, source=source))
                x0 += width + 1.0
        words.append(_word(f"{index + 1}0.00", 116.0, 140.0, y))

    return PageEvidence(
        page_number=1,
        width=150.0,
        height=180.0,
        words=tuple(words),
        quality=ExtractionQuality(
            character_count=0,
            usable_character_count=0,
            word_count=len(words),
            replacement_character_ratio=0.0,
            control_character_ratio=0.0,
            image_area_ratio=0.8,
            requires_ocr=True,
            reasons=("image_dominant",),
        ),
    )


_CONFUSED_OCR_MARKER_LABELS = (
    "II",
    "$",
    "8",
    "7%",
    "|",
    "||",
) * 2
_CONFUSED_OCR_MARKER_CONFIDENCES = (
    0.28,
    0.72,
    0.57,
    0.71,
    0.60,
    0.87,
    0.84,
    0.95,
    0.63,
    0.76,
    0.75,
    0.93,
)


def _confused_right_marker_page(
    *,
    high_confidence: bool = False,
    overlapping_last_row: bool = True,
) -> PageEvidence:
    words = [
        _word("Description", 5.0, 32.0, 10.0),
        _word("Date", 50.0, 76.0, 10.0),
        _word("Amount", 112.0, 140.0, 10.0),
    ]
    for index, (marker, marker_confidence) in enumerate(
        zip(
            _CONFUSED_OCR_MARKER_LABELS,
            _CONFUSED_OCR_MARKER_CONFIDENCES,
            strict=True,
        )
    ):
        y = 32.0 + index * 14.0
        words.append(_word(f"Item {index + 1}", 5.0, 31.0, y))
        date_x1 = 82.0 if overlapping_last_row and index == 11 else 76.0
        words.append(_word(f"{index + 1:02d}/02/2026", 50.0, date_x1, y, source="ocr"))
        words.append(
            _word(
                marker,
                79.0,
                83.0,
                y,
                source="ocr",
                confidence=0.95 if high_confidence else marker_confidence,
            )
        )
        words.append(_word(f"{index + 1}0.00", 116.0, 140.0, y))
    return PageEvidence(
        page_number=1,
        width=150.0,
        height=220.0,
        words=tuple(words),
        quality=ExtractionQuality(
            character_count=0,
            usable_character_count=0,
            word_count=len(words),
            replacement_character_ratio=0.0,
            control_character_ratio=0.0,
            image_area_ratio=0.8,
            requires_ocr=True,
            reasons=("image_dominant",),
        ),
    )


def _single_region(page: PageEvidence) -> TableRegion:
    regions = detect_table_regions(page)
    assert len(regions) == 1
    return regions[0]


def _marker_columns(region: TableRegion) -> tuple[ColumnSpec, ...]:
    return tuple(
        column
        for column in region.table_schema.columns
        if _OCR_MARKER_BAND_DIAGNOSTIC in column.diagnostics
    )


def _validate_row(region: TableRegion, row_index: int) -> tuple[EvidenceLedger, SemanticValidation]:
    row = region.rows[row_index]
    description_column = next(
        column for column in region.table_schema.columns if column.role is ColumnRole.DESCRIPTION
    )
    amount_column = next(
        column for column in region.table_schema.columns if column.role is ColumnRole.AMOUNT
    )
    date_column = next(
        column for column in region.table_schema.columns if column.role is ColumnRole.DATE
    )
    description_cell = cells_in_column(row.cells, description_column)[0]
    amount_cell = cells_in_column(row.cells, amount_column)[0]
    ledger = EvidenceLedger.from_rows((row,))
    validation = validate_transaction_semantics(
        rows=(row,),
        region=region,
        ledger=ledger,
        initial_claims=(
            EvidenceClaim(SemanticOwner.DESCRIPTION, ledger.atoms_for_cell(description_cell)),
        ),
        amount_cell=amount_cell,
        billing_currency="ILS",
        original_currency=None,
        description=description_cell.text,
        transaction_date=None,
        posting_date=None,
        conversion_date=None,
        year_context=None,
        date_column_kinds={date_column.index: DateColumnKind.TRANSACTION},
    )
    return ledger, validation


def test_table_wide_heterogeneous_ocr_marker_band_is_split_losslessly_from_date() -> None:
    region = _single_region(_table_page())

    marker_columns = _marker_columns(region)
    assert len(marker_columns) == 1
    marker_column = marker_columns[0]
    assert marker_column.role is ColumnRole.UNKNOWN
    assert not cells_in_column(region.header.cells, marker_column)

    date_columns = tuple(
        column for column in region.table_schema.columns if column.role is ColumnRole.DATE
    )
    assert len(date_columns) == 1
    for row, expected_marker in zip(region.rows, _MARKER_LABELS, strict=True):
        marker_cells = cells_in_column(row.cells, marker_column)
        date_cells = cells_in_column(row.cells, date_columns[0])
        assert tuple(cell.text for cell in marker_cells) == (expected_marker,)
        assert tuple(cell.text for cell in date_cells) == (
            f"{region.rows.index(row) + 1:02d}/02/2026",
        )
        assert tuple(word for cell in row.cells for word in cell.words) == row.words


def test_split_ocr_marker_has_ancillary_owner_and_date_owns_only_date_atom() -> None:
    region = _single_region(_table_page())
    marker_column = _marker_columns(region)[0]
    date_column = next(
        column for column in region.table_schema.columns if column.role is ColumnRole.DATE
    )
    description_column = next(
        column for column in region.table_schema.columns if column.role is ColumnRole.DESCRIPTION
    )
    amount_column = next(
        column for column in region.table_schema.columns if column.role is ColumnRole.AMOUNT
    )
    row = region.rows[1]
    marker_cell = cells_in_column(row.cells, marker_column)[0]
    date_cell = cells_in_column(row.cells, date_column)[0]
    description_cell = cells_in_column(row.cells, description_column)[0]
    amount_cell = cells_in_column(row.cells, amount_column)[0]
    ledger = EvidenceLedger.from_rows((row,))
    description_claim = EvidenceClaim(
        SemanticOwner.DESCRIPTION,
        ledger.atoms_for_cell(description_cell),
    )

    assert assignment_diagnostics(row, region, ledger) == ()
    validation = validate_transaction_semantics(
        rows=(row,),
        region=region,
        ledger=ledger,
        initial_claims=(description_claim,),
        amount_cell=amount_cell,
        billing_currency="ILS",
        original_currency=None,
        description=description_cell.text,
        transaction_date=date(2026, 2, 2),
        posting_date=None,
        conversion_date=None,
        year_context=None,
        date_column_kinds={date_column.index: DateColumnKind.TRANSACTION},
    )

    assert (
        EvidenceClaim(
            SemanticOwner.TRANSACTION_DATE,
            ledger.atoms_for_cell(date_cell),
        )
        in validation.claims
    )
    assert (
        EvidenceClaim(
            SemanticOwner.ANCILLARY,
            ledger.atoms_for_cell(marker_cell),
        )
        in validation.claims
    )
    assert not any(
        claim.owner is SemanticOwner.TRANSACTION_DATE
        and claim.atom_ids & ledger.atoms_for_cell(marker_cell)
        for claim in validation.claims
    )
    assert validation.diagnostics == ()


def test_one_off_ocr_annotation_is_not_promoted_to_marker_band() -> None:
    region = _single_region(_table_page(("$", None, None, None)))

    assert _marker_columns(region) == ()


@pytest.mark.parametrize(
    "centers,glued",
    [
        ((49.0, 42.0, 52.0, 39.0), False),
        ((49.0, 49.0, 49.0, 49.0), True),
    ],
    ids=("drifting", "glued"),
)
def test_drifting_or_glued_ocr_annotations_are_not_marker_bands(
    centers: tuple[float, ...],
    glued: bool,
) -> None:
    region = _single_region(_table_page(marker_centers=centers, glued=glued))

    assert _marker_columns(region) == ()


def test_digitally_corroborated_band_is_not_an_ocr_marker_band() -> None:
    region = _single_region(
        _table_page(marker_sources=("digital", "digital", "digital", "digital"))
    )

    assert _marker_columns(region) == ()


@pytest.mark.parametrize(
    "markers",
    [
        ("$", "7%", "8", "XQ"),
        ("USD", "5.00", "7%", "XQ"),
        ("$", "EUR", "GBP", "ILS"),
        ("1%", "2%", "3%", "4%"),
        ("1", "2", "3", "4"),
        ("03/04/2026", "$", "7%", "XQ"),
        ("2/5", "$", "7%", "XQ"),
    ],
    ids=(
        "heterogeneous_semantic",
        "money",
        "currency",
        "percentage",
        "numeric",
        "date",
        "installment",
    ),
)
def test_semantic_evidence_is_not_a_nonmaterial_marker_band(
    markers: tuple[str, ...],
) -> None:
    region = _single_region(_table_page(markers))

    assert _marker_columns(region) == ()


def test_explicit_financial_header_retains_its_typed_column() -> None:
    region = _single_region(_table_page(explicit_financial_header=True))

    assert _marker_columns(region) == ()
    assert any(column.role is ColumnRole.EXCHANGE_RATE for column in region.table_schema.columns)


def test_multiple_positioned_dates_are_not_retyped_as_marker_evidence() -> None:
    region = _single_region(_table_page(second_date=True))

    assert _marker_columns(region) == ()


def test_sparse_right_marker_band_includes_ocr_only_standalone_occupant() -> None:
    region = _single_region(_sparse_right_marker_page())
    marker_column = _marker_columns(region)[0]
    standalone = cells_in_column(region.rows[-1].cells, marker_column)[0]

    assert "repeated_row_support:3/9" in marker_column.diagnostics
    assert standalone in marker_column.source_cells
    assert (
        assignment_diagnostics(
            region.rows[-1],
            region,
            EvidenceLedger.from_rows((region.rows[-1],)),
        )
        == ()
    )
    ledger, validation = _validate_row(region, -1)
    assert (
        EvidenceClaim(
            SemanticOwner.ANCILLARY,
            ledger.atoms_for_cell(standalone),
        )
        in validation.claims
    )
    assert validation.diagnostics == ()


@pytest.mark.parametrize(
    "standalone_words",
    [
        (("EUR", "digital"),),
        (("EUR", "ocr"),),
        (("EUR", "ocr"), ("5.00", "ocr")),
    ],
    ids=("digitally_backed", "ocr_currency", "composite_financial"),
)
def test_unproven_marker_band_occupant_retains_assignment_diagnostics(
    standalone_words: tuple[tuple[str, EvidenceSource], ...],
) -> None:
    region = _single_region(_sparse_right_marker_page(standalone_words=standalone_words))
    marker_column = _marker_columns(region)[0]
    row = region.rows[-1]
    occupant = cells_in_column(row.cells, marker_column)[0]

    assert occupant not in marker_column.source_cells
    diagnostics = assignment_diagnostics(row, region, EvidenceLedger.from_rows((row,)))
    assert f"column:{marker_column.index}:role_unknown" in diagnostics
    assert "unresolved_relevant_cell" in diagnostics
    ledger, validation = _validate_row(region, -1)
    assert not any(
        claim.owner is SemanticOwner.ANCILLARY and claim.atom_ids & ledger.atoms_for_cell(occupant)
        for claim in validation.claims
    )
    assert "unconsumed_transaction_semantic_text" in validation.diagnostics


def test_vertically_offset_ocr_annotations_are_not_marker_band_evidence() -> None:
    region = _single_region(_table_page(marker_y_offsets=(5.0, 5.0, 5.0, 5.0)))

    assert _marker_columns(region) == ()


def test_low_confidence_cross_profile_ocr_band_is_split_from_every_date_cell() -> None:
    region = _single_region(_confused_right_marker_page())

    marker_columns = _marker_columns(region)
    assert len(marker_columns) == 1
    marker_column = marker_columns[0]
    date_column = next(
        column for column in region.table_schema.columns if column.role is ColumnRole.DATE
    )
    assert all(len(cells_in_column(row.cells, marker_column)) == 1 for row in region.rows)
    assert all(len(cells_in_column(row.cells, date_column)) == 1 for row in region.rows)


def test_high_confidence_cross_profile_values_are_not_promoted_to_marker_band() -> None:
    region = _single_region(
        _confused_right_marker_page(
            high_confidence=True,
            overlapping_last_row=False,
        )
    )

    assert _marker_columns(region) == ()


def test_cached_unsplit_cross_profile_band_proves_date_and_marker_atoms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        layout_regions,
        "separate_repeated_ocr_marker_band",
        lambda region: region,
    )
    region = _single_region(_confused_right_marker_page())
    assert _marker_columns(region) == ()
    date_column = next(
        column for column in region.table_schema.columns if column.role is ColumnRole.DATE
    )
    row = region.rows[-1]
    date_cell = cells_in_column(row.cells, date_column)[0]
    ledger = EvidenceLedger.from_rows((row,))
    date_word = next(word for word in date_cell.words if "/" in word.text)
    marker_word = next(word for word in date_cell.words if word is not date_word)
    date_atom_ids = frozenset(atom.atom_id for atom in ledger.atoms if atom.word == date_word)
    marker_atom_ids = frozenset(atom.atom_id for atom in ledger.atoms if atom.word == marker_word)
    expected_date = date(2026, 2, 12)

    assert extract_dates(
        row,
        region,
        None,
        {date_column.index: DateColumnKind.TRANSACTION},
        ledger=ledger,
    ) == DateExtraction(expected_date, None, None, (), ())
    assert proven_assigned_date_evidence(
        row,
        region,
        date_column,
        date_cell,
        ledger,
        expected_date,
        None,
    ) == (date_atom_ids, marker_atom_ids)
