from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

import ccparser.normalization_description as normalization_description
from ccparser.date_tokens import DateTokenStyle
from ccparser.discovery import DiscoveredDateYearContext
from ccparser.evidence import Word
from ccparser.layout import Cell, ColumnRole, ColumnSpec, Row, TableRegion, TableSchema
from ccparser.models import EvidenceReference
from ccparser.normalization_description import (
    _primary_description_cluster,
    extract_description,
    is_description_continuation,
)
from ccparser.semantic_evidence import (
    DescriptionExtraction,
    EvidenceClaim,
    EvidenceCluster,
    EvidenceLedger,
    SemanticOwner,
)


def test_normalization_description_exports_exact_public_contract() -> None:
    assert normalization_description.__all__ == [
        "extract_description",
        "has_processor_reference_alignment",
        "is_description_continuation",
        "is_numeric_processor_reference",
        "is_standalone_primary_description",
        "matching_positioned_cell_text",
    ]


def test_description_extractor_is_real_public_definition() -> None:
    assert extract_description.__name__ == "extract_description"


def _word(text: str, x0: float, x1: float, y: float = 30.0) -> Word:
    return Word(
        text=text,
        bbox=(x0, y, x1, y + 10.0),
        source="digital",
        confidence=1.0,
    )


def _cell(
    text: str,
    column: int,
    y: float = 30.0,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    words: tuple[Word, ...] = (),
) -> Cell:
    x0 = column * 50.0
    return Cell(
        page_number=1,
        bbox=bbox or (x0, y, x0 + 40.0, y + 10.0),
        text=text,
        words=words,
        confidence=1.0,
    )


def _row(*cells: Cell, diagnostics: tuple[str, ...] = ()) -> Row:
    return Row(
        page_number=1,
        bbox=(
            min(cell.bbox[0] for cell in cells),
            min(cell.bbox[1] for cell in cells),
            max(cell.bbox[2] for cell in cells),
            max(cell.bbox[3] for cell in cells),
        ),
        cells=cells,
        confidence=1.0,
        diagnostics=diagnostics,
    )


def _region(
    roles: tuple[ColumnRole, ...],
    rows: tuple[Row, ...],
    *,
    headers: tuple[str, ...] | None = None,
) -> TableRegion:
    header_texts = headers or tuple(role.value for role in roles)
    header_cells = tuple(_cell(text, index, 10.0) for index, text in enumerate(header_texts))
    columns = tuple(
        ColumnSpec(
            index=index,
            page_number=1,
            bbox=(index * 50.0, 10.0, index * 50.0 + 40.0, 200.0),
            relative_x0=index / len(roles),
            relative_x1=(index + 1) / len(roles),
            role=role,
            source_cells=(header_cells[index],),
            confidence=1.0,
        )
        for index, role in enumerate(roles)
    )
    header = _row(*header_cells)
    return TableRegion(
        page_number=1,
        bbox=(0.0, 10.0, len(roles) * 50.0 - 10.0, max(row.bbox[3] for row in rows)),
        header=header,
        rows=rows,
        table_schema=TableSchema(
            page_number=1,
            bbox=(0.0, 10.0, len(roles) * 50.0 - 10.0, 200.0),
            columns=columns,
            header_cells=header_cells,
            sample_cells=tuple(cell for row in rows for cell in row.cells),
            confidence=1.0,
        ),
        confidence=1.0,
    )


def _year_context() -> DiscoveredDateYearContext:
    return DiscoveredDateYearContext(
        year=2026,
        style=DateTokenStyle.DAY_FIRST_SLASH,
        evidence=(
            EvidenceReference(
                page_number=1,
                bbox=(0.0, 0.0, 40.0, 10.0),
                raw_text="statement date 2026",
            ),
        ),
        confidence=1.0,
    )


def _claim(
    owner: SemanticOwner,
    ledger: EvidenceLedger,
    *cells: Cell,
) -> EvidenceClaim:
    return EvidenceClaim(
        owner,
        frozenset(atom_id for cell in cells for atom_id in ledger.atoms_for_cell(cell)),
    )


def _description_band_with_extra_cell(
    extra: Cell,
    *,
    primary_text: str = "Merchant",
) -> tuple[Row, TableRegion, Cell]:
    return _description_band_with_extra_cells((extra,), primary_text=primary_text)


def _description_band_with_extra_cells(
    extras: tuple[Cell, ...],
    *,
    primary_text: str = "Merchant",
) -> tuple[Row, TableRegion, Cell]:
    merchant = _cell(
        primary_text,
        1,
        bbox=(50.0, 30.0, 90.0, 40.0),
        words=(_word(primary_text, 50.0, 90.0),),
    )
    row = _row(
        _cell("01/02/2026", 0, bbox=(0.0, 30.0, 40.0, 40.0)),
        merchant,
        *extras,
        _cell("10.00", 3, bbox=(160.0, 30.0, 200.0, 40.0)),
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (row,),
    )
    columns = (
        region.table_schema.columns[0].model_copy(update={"bbox": (0.0, 10.0, 44.0, 200.0)}),
        region.table_schema.columns[1].model_copy(update={"bbox": (45.0, 10.0, 145.0, 200.0)}),
        region.table_schema.columns[2].model_copy(update={"bbox": (146.0, 10.0, 200.0, 200.0)}),
    )
    return (
        row,
        region.model_copy(
            update={"table_schema": region.table_schema.model_copy(update={"columns": columns})}
        ),
        merchant,
    )


def test_description_extracts_ordinary_text_with_exact_claim() -> None:
    description = _cell("Ordinary Merchant", 1)
    row = _row(_cell("24/06/2026", 0), description, _cell("10.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (row,),
    )
    ledger = EvidenceLedger.from_rows((row,))

    assert extract_description((row,), region, None, ledger) == DescriptionExtraction(
        "Ordinary Merchant",
        (_claim(SemanticOwner.DESCRIPTION, ledger, description),),
        (),
    )


def test_description_claims_separate_hyphenated_cluster_as_processor_reference() -> None:
    reference_text = "123-456"
    reference = _cell(
        reference_text,
        2,
        bbox=(105.0, 30.0, 128.0, 40.0),
        words=(
            Word(
                text=reference_text,
                bbox=(105.0, 30.0, 128.0, 40.0),
                source="ocr",
                confidence=0.97,
            ),
        ),
    )
    row, region, merchant = _description_band_with_extra_cell(reference)
    ledger = EvidenceLedger.from_rows((row,))

    assert extract_description((row,), region, None, ledger) == DescriptionExtraction(
        "Merchant",
        (
            _claim(SemanticOwner.DESCRIPTION, ledger, merchant),
            _claim(SemanticOwner.PROCESSOR_REFERENCE, ledger, reference),
        ),
        (),
    )


def test_description_rejects_tiny_processor_shaped_superscript_cell() -> None:
    reference_text = "123-456"
    reference = _cell(
        reference_text,
        2,
        bbox=(105.0, 34.5, 128.0, 35.5),
        words=(
            Word(
                text=reference_text,
                bbox=(105.0, 34.5, 128.0, 35.5),
                source="ocr",
                confidence=0.97,
            ),
        ),
    )
    row, region, _ = _description_band_with_extra_cell(reference)
    ledger = EvidenceLedger.from_rows((row,))

    extraction = extract_description((row,), region, None, ledger)

    assert all(claim.owner is not SemanticOwner.PROCESSOR_REFERENCE for claim in extraction.claims)
    assert (
        ledger.atoms_for_cell(reference)
        <= ledger.validate_claims(extraction.claims).unclaimed_atom_ids
    )


@pytest.mark.parametrize(
    "words",
    (
        (),
        (
            Word(
                text="765-432",
                bbox=(105.0, 30.0, 128.0, 40.0),
                source="ocr",
                confidence=0.97,
            ),
        ),
    ),
    ids=("cell-text-only", "mismatched-word"),
)
def test_description_standalone_processor_requires_exact_positioned_source(
    words: tuple[Word, ...],
) -> None:
    reference = _cell(
        "123-456",
        2,
        bbox=(105.0, 30.0, 128.0, 40.0),
        words=words,
    )
    row, region, merchant = _description_band_with_extra_cell(reference)
    ledger = EvidenceLedger.from_rows((row,))

    extraction = extract_description((row,), region, None, ledger)

    assert extraction == DescriptionExtraction(
        "Merchant",
        (_claim(SemanticOwner.DESCRIPTION, ledger, merchant, reference),),
        (),
    )
    assert all(claim.owner is not SemanticOwner.PROCESSOR_REFERENCE for claim in extraction.claims)


def test_description_leaves_uncorroborated_whole_unit_numeric_cell_unclaimed() -> None:
    numeric = _cell(
        "123456",
        2,
        bbox=(105.0, 30.0, 128.0, 40.0),
        words=(_word("123456", 105.0, 128.0),),
    )
    row, region, merchant = _description_band_with_extra_cell(numeric)
    ledger = EvidenceLedger.from_rows((row,))

    extraction = extract_description((row,), region, None, ledger)
    validation = ledger.validate_claims(extraction.claims)

    assert extraction == DescriptionExtraction(
        "Merchant",
        (_claim(SemanticOwner.DESCRIPTION, ledger, merchant),),
        (),
    )
    assert ledger.atoms_for_cell(numeric) <= validation.unclaimed_atom_ids


def test_description_claims_processor_reference_beside_numeric_primary_cell() -> None:
    reference = _cell(
        "123-456",
        2,
        bbox=(105.0, 30.0, 128.0, 40.0),
        words=(_word("123-456", 105.0, 128.0),),
    )
    row, region, primary = _description_band_with_extra_cell(
        reference,
        primary_text="12",
    )
    ledger = EvidenceLedger.from_rows((row,))

    assert extract_description((row,), region, None, ledger) == DescriptionExtraction(
        "12",
        (
            _claim(SemanticOwner.DESCRIPTION, ledger, primary),
            _claim(SemanticOwner.PROCESSOR_REFERENCE, ledger, reference),
        ),
        (),
    )


def test_description_preserves_processor_shaped_cluster_with_competing_numeric_text() -> None:
    description = _cell(
        "Merchant 42 123-456",
        1,
        bbox=(50.0, 30.0, 99.0, 40.0),
        words=(
            _word("Merchant", 50.0, 68.0),
            _word("42", 70.0, 76.0),
            _word("123-456", 90.0, 99.0),
        ),
    )
    row = _row(_cell("01/02/2026", 0), description, _cell("10.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (row,),
    )
    ledger = EvidenceLedger.from_rows((row,))

    assert extract_description((row,), region, None, ledger) == DescriptionExtraction(
        "Merchant 42 123-456",
        (_claim(SemanticOwner.DESCRIPTION, ledger, description),),
        (),
    )


def test_description_does_not_claim_dashed_cluster_beside_typed_currency_primary() -> None:
    description = _cell(
        "USD 123-456",
        1,
        bbox=(50.0, 30.0, 99.0, 40.0),
        words=(
            _word("USD", 50.0, 68.0),
            _word("123-456", 78.0, 99.0),
        ),
    )
    row = _row(_cell("01/02/2026", 0), description, _cell("10.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (row,),
    )
    ledger = EvidenceLedger.from_rows((row,))

    extraction = extract_description((row,), region, None, ledger)

    assert extraction.value == "USD 123-456"
    assert all(claim.owner is not SemanticOwner.PROCESSOR_REFERENCE for claim in extraction.claims)
    assert ledger.atoms_for_cell(description) == frozenset(
        atom_id for claim in extraction.claims for atom_id in claim.atom_ids
    )


def test_description_leaves_uncorroborated_whole_unit_numeric_cluster_unclaimed() -> None:
    description = _cell(
        "Merchant 123456",
        1,
        bbox=(50.0, 30.0, 99.0, 40.0),
        words=(
            _word("Merchant", 50.0, 68.0),
            _word("123456", 78.0, 99.0),
        ),
    )
    row = _row(_cell("01/02/2026", 0), description, _cell("10.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (row,),
    )
    ledger = EvidenceLedger.from_rows((row,))
    numeric_ids = frozenset(atom.atom_id for atom in ledger.atoms if atom.text == "123456")

    extraction = extract_description((row,), region, None, ledger)
    validation = ledger.validate_claims(extraction.claims)

    assert extraction.value == "Merchant"
    assert numeric_ids <= validation.unclaimed_atom_ids


def test_processor_occurrence_geometry_is_frozen_and_explicitly_corroborated() -> None:
    def occurrence(
        row_index: int,
        reference: str,
    ) -> normalization_description._ProcessorOccurrence:
        cell = _cell(
            f"Merchant {reference}",
            1,
            bbox=(50.0, 30.0, 105.0, 40.0),
            words=(
                _word("Merchant", 50.0, 68.0),
                _word(reference, 78.0, 99.0),
            ),
        )
        ledger = EvidenceLedger.from_rows((_row(cell),))
        line = normalization_description._cluster_lines(ledger.clusters_for_cell(cell))[0]
        primary = _primary_description_cluster(line)
        reference_cluster = next(cluster for cluster in line if cluster is not primary)
        result = normalization_description._processor_occurrence(
            row_index,
            ledger,
            cell,
            line,
            primary,
            reference_cluster,
        )
        assert result is not None
        return result

    first = occurrence(3, "1234567")
    matching_numeric = occurrence(4, "1234567")
    positioned_anchor = occurrence(4, ".PROCESSOR")

    assert tuple(first.__slots__) == (
        "row_index",
        "key",
        "signature",
        "center",
        "height",
        "side",
    )
    assert first.key == (
        1,
        (50.0, 30.0, 105.0, 40.0),
        (50.0, 30.0, 68.0, 40.0),
        (78.0, 30.0, 99.0, 40.0),
        "1234567",
    )
    with pytest.raises(FrozenInstanceError):
        first.side = -1
    assert normalization_description._processor_occurrences_corroborate(
        first,
        matching_numeric,
        require_signature_match=True,
    )
    assert not normalization_description._processor_occurrences_corroborate(
        first,
        positioned_anchor,
        require_signature_match=True,
    )
    assert normalization_description._processor_occurrences_corroborate(
        first,
        positioned_anchor,
        require_signature_match=False,
    )


def _repeated_numeric_description_rows(
    second_reference: str,
    *,
    second_reference_x: float = 78.0,
) -> tuple[Row, Row, Cell, Cell]:
    first_description = _cell(
        "Merchant 1234567",
        1,
        30.0,
        bbox=(50.0, 30.0, 105.0, 40.0),
        words=(
            _word("Merchant", 50.0, 68.0, 30.0),
            _word("1234567", 78.0, 99.0, 30.0),
        ),
    )
    second_description = _cell(
        f"Market {second_reference}",
        1,
        50.0,
        bbox=(50.0, 50.0, max(105.0, second_reference_x + 21.0), 60.0),
        words=(
            _word("Market", 50.0, 68.0, 50.0),
            _word(
                second_reference,
                second_reference_x,
                second_reference_x + 21.0,
                50.0,
            ),
        ),
    )
    return (
        _row(_cell("01/02/2026", 0, 30.0), first_description, _cell("10.00", 2, 30.0)),
        _row(_cell("02/02/2026", 0, 50.0), second_description, _cell("20.00", 2, 50.0)),
        first_description,
        second_description,
    )


def test_description_claims_repeated_aligned_numeric_cluster_as_processor_reference() -> None:
    first, second, _, _ = _repeated_numeric_description_rows("1234567")
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (first, second),
    )
    ledger = EvidenceLedger.from_rows((first,))
    atom_id_by_text = {atom.text: atom.atom_id for atom in ledger.atoms}

    assert extract_description((first,), region, None, ledger) == DescriptionExtraction(
        "Merchant",
        (
            EvidenceClaim(
                SemanticOwner.DESCRIPTION,
                frozenset((atom_id_by_text["Merchant"],)),
            ),
            EvidenceClaim(
                SemanticOwner.PROCESSOR_REFERENCE,
                frozenset((atom_id_by_text["1234567"],)),
            ),
        ),
        (),
    )


def test_description_rejects_repeated_numeric_band_with_typed_currency_primary() -> None:
    descriptions: list[Cell] = []
    rows: list[Row] = []
    for y, raw_date in ((30.0, "01/02/2026"), (50.0, "02/02/2026")):
        description = _cell(
            "USD 1234567",
            1,
            y,
            bbox=(50.0, y, 105.0, y + 10.0),
            words=(
                _word("USD", 50.0, 68.0, y),
                _word("1234567", 78.0, 99.0, y),
            ),
        )
        descriptions.append(description)
        rows.append(
            _row(
                _cell(raw_date, 0, y),
                description,
                _cell("10.00", 2, y),
            )
        )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        tuple(rows),
    )
    ledger = EvidenceLedger.from_rows((rows[0],))
    numeric_ids = frozenset(atom.atom_id for atom in ledger.atoms if atom.text == "1234567")

    extraction = extract_description((rows[0],), region, None, ledger)

    assert all(claim.owner is not SemanticOwner.PROCESSOR_REFERENCE for claim in extraction.claims)
    assert numeric_ids <= ledger.validate_claims(extraction.claims).unclaimed_atom_ids


def _processor_anchor_and_numeric_rows(
    *,
    anchor_primary: str = "Market",
    anchor_reference: str = ".PROCESSOR",
    anchor_reference_x: float = 78.0,
    anchor_diagnostics: tuple[str, ...] = (),
    external_anchor: bool = True,
    external_source_text: str | None = None,
    numeric_primary: str = "Merchant",
    positioned_external: bool = True,
) -> tuple[Row, Row, Cell]:
    anchor_description = _cell(
        f"{anchor_primary} {anchor_reference}",
        1,
        30.0,
        bbox=(50.0, 30.0, max(105.0, anchor_reference_x + 21.0), 40.0),
        words=(
            _word(anchor_primary, 50.0, 68.0, 30.0),
            _word(
                anchor_reference,
                anchor_reference_x,
                anchor_reference_x + 21.0,
                30.0,
            ),
        ),
    )
    numeric_description = _cell(
        f"{numeric_primary} 7654321",
        1,
        50.0,
        bbox=(50.0, 50.0, 105.0, 60.0),
        words=(
            _word(numeric_primary, 50.0, 68.0, 50.0),
            _word("7654321", 78.0, 99.0, 50.0),
        ),
    )
    external_text = anchor_reference.removeprefix(".").removeprefix("@")
    positioned_external_text = external_source_text or external_text
    external_cell = _cell(
        external_text,
        2,
        30.0,
        words=(
            (_word(positioned_external_text, 100.0, 140.0, 30.0),) if positioned_external else ()
        ),
    )
    return (
        _row(
            _cell("01/02/2026", 0, 30.0),
            anchor_description,
            *((external_cell,) if external_anchor else ()),
            _cell("10.00", 3, 30.0),
            diagnostics=anchor_diagnostics,
        ),
        _row(
            _cell("02/02/2026", 0, 50.0),
            numeric_description,
            _cell("20.00", 3, 50.0),
        ),
        numeric_description,
    )


def test_description_claims_numeric_cluster_in_processor_anchored_secondary_band() -> None:
    anchor, numeric, numeric_description = _processor_anchor_and_numeric_rows()
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.UNKNOWN,
            ColumnRole.AMOUNT,
        ),
        (anchor, numeric),
    )
    ledger = EvidenceLedger.from_rows((numeric,))
    numeric_ids = frozenset(atom.atom_id for atom in ledger.atoms if atom.text == "7654321")

    extraction = extract_description((numeric,), region, None, ledger)

    assert extraction.value == "Merchant"
    assert EvidenceClaim(SemanticOwner.PROCESSOR_REFERENCE, numeric_ids) in extraction.claims
    assert not (numeric_ids & ledger.validate_claims(extraction.claims).unclaimed_atom_ids)
    assert ledger.atoms_for_cell(numeric_description) == frozenset(
        atom_id for claim in extraction.claims for atom_id in claim.atom_ids
    )


def test_description_claims_exact_processor_anchor_occurrence_in_proven_band() -> None:
    anchor, numeric, _ = _processor_anchor_and_numeric_rows()
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.UNKNOWN,
            ColumnRole.AMOUNT,
        ),
        (anchor, numeric),
    )
    ledger = EvidenceLedger.from_rows((anchor,))
    anchor_ids = frozenset(atom.atom_id for atom in ledger.atoms if atom.text == ".PROCESSOR")

    extraction = extract_description((anchor,), region, None, ledger)

    assert extraction.value == "Market"
    assert EvidenceClaim(SemanticOwner.PROCESSOR_REFERENCE, anchor_ids) in extraction.claims
    assert not (anchor_ids & ledger.validate_claims(extraction.claims).unclaimed_atom_ids)


@pytest.mark.parametrize(
    (
        "anchor_primary",
        "anchor_reference",
        "anchor_reference_x",
        "anchor_diagnostics",
        "external_anchor",
        "external_source_text",
        "numeric_primary",
        "positioned_external",
    ),
    (
        ("Market", "PROCESSOR", 78.0, (), True, None, "Merchant", True),
        ("Market", ".PROCESSOR", 105.0, (), True, None, "Merchant", True),
        (
            "Market",
            ".PROCESSOR",
            78.0,
            ("subordinate_detail_continuation",),
            True,
            None,
            "Merchant",
            True,
        ),
        ("Market", ".PROCESSOR", 78.0, (), False, None, "Merchant", True),
        ("USD", ".PROCESSOR", 78.0, (), True, None, "Merchant", True),
        ("Market", ".PROCESSOR", 78.0, (), True, None, "USD", True),
        ("Market", ".PROCESSOR", 78.0, (), True, None, "Merchant", False),
        ("Market", ".PROCESSOR", 78.0, (), True, "OTHER", "Merchant", True),
        ("Market", ".USD", 78.0, (), True, None, "Merchant", True),
    ),
    ids=(
        "untyped-anchor",
        "misaligned-anchor",
        "structural-anchor",
        "unbacked-anchor",
        "typed-anchor-primary",
        "typed-numeric-primary",
        "cell-text-external",
        "mismatched-external",
        "financial-external",
    ),
)
def test_description_rejects_unproven_numeric_secondary_band(
    anchor_primary: str,
    anchor_reference: str,
    anchor_reference_x: float,
    anchor_diagnostics: tuple[str, ...],
    external_anchor: bool,
    external_source_text: str | None,
    numeric_primary: str,
    positioned_external: bool,
) -> None:
    anchor, numeric, _ = _processor_anchor_and_numeric_rows(
        anchor_primary=anchor_primary,
        anchor_reference=anchor_reference,
        anchor_reference_x=anchor_reference_x,
        anchor_diagnostics=anchor_diagnostics,
        external_anchor=external_anchor,
        external_source_text=external_source_text,
        numeric_primary=numeric_primary,
        positioned_external=positioned_external,
    )
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.UNKNOWN,
            ColumnRole.AMOUNT,
        ),
        (anchor, numeric),
    )
    ledger = EvidenceLedger.from_rows((numeric,))
    numeric_ids = frozenset(atom.atom_id for atom in ledger.atoms if atom.text == "7654321")

    extraction = extract_description((numeric,), region, None, ledger)

    assert all(claim.owner is not SemanticOwner.PROCESSOR_REFERENCE for claim in extraction.claims)
    assert numeric_ids <= ledger.validate_claims(extraction.claims).unclaimed_atom_ids


@pytest.mark.parametrize(
    ("second_reference", "second_reference_x"),
    (("7654321", 78.0), ("1234567", 105.0)),
    ids=("not-repeated", "misaligned"),
)
def test_description_does_not_claim_unproven_numeric_cluster_as_processor_reference(
    second_reference: str,
    second_reference_x: float,
) -> None:
    first, second, _, _ = _repeated_numeric_description_rows(
        second_reference,
        second_reference_x=second_reference_x,
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (first, second),
    )
    ledger = EvidenceLedger.from_rows((first,))
    extraction = extract_description((first,), region, None, ledger)
    numeric_ids = frozenset(atom.atom_id for atom in ledger.atoms if atom.text == "1234567")

    assert all(claim.owner is not SemanticOwner.PROCESSOR_REFERENCE for claim in extraction.claims)
    assert numeric_ids <= ledger.validate_claims(extraction.claims).unclaimed_atom_ids
    assert "1234567" not in (extraction.value or "")


def test_description_does_not_apply_repeated_numeric_proof_to_rogue_occurrence() -> None:
    first, second, _, _ = _repeated_numeric_description_rows("1234567")
    rogue_description = _cell(
        "Store 42 1234567",
        1,
        70.0,
        bbox=(50.0, 70.0, 115.0, 80.0),
        words=(
            _word("Store", 50.0, 68.0, 70.0),
            _word("42", 78.0, 84.0, 70.0),
            _word("1234567", 94.0, 115.0, 70.0),
        ),
    )
    rogue = _row(
        _cell("03/02/2026", 0, 70.0),
        rogue_description,
        _cell("30.00", 2, 70.0),
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (first, second, rogue),
    )
    ledger = EvidenceLedger.from_rows((rogue,))
    numeric_ids = frozenset(atom.atom_id for atom in ledger.atoms if atom.text == "1234567")

    extraction = extract_description((rogue,), region, None, ledger)

    assert all(claim.owner is not SemanticOwner.PROCESSOR_REFERENCE for claim in extraction.claims)
    assert extraction.value == "Store 42"
    assert numeric_ids <= ledger.validate_claims(extraction.claims).unclaimed_atom_ids


def test_description_ignores_excluded_numeric_semantics_when_classifying_processor() -> None:
    description = _cell(
        "Merchant 01/02/2026 123-456",
        1,
        bbox=(50.0, 30.0, 130.0, 40.0),
        words=(
            _word("Merchant", 50.0, 68.0),
            _word("01/02/2026", 82.0, 102.0),
            _word("123-456", 116.0, 130.0),
        ),
    )
    row = _row(_cell("10.00", 0), description)
    region = _region((ColumnRole.AMOUNT, ColumnRole.DESCRIPTION), (row,))
    ledger = EvidenceLedger.from_rows((row,))
    atom_id_by_text = {atom.text: atom.atom_id for atom in ledger.atoms}

    assert extract_description(
        (row,),
        region,
        None,
        ledger,
        excluded_atom_ids=frozenset((atom_id_by_text["01/02/2026"],)),
    ) == DescriptionExtraction(
        "Merchant",
        (
            EvidenceClaim(
                SemanticOwner.DESCRIPTION,
                frozenset((atom_id_by_text["Merchant"],)),
            ),
            EvidenceClaim(
                SemanticOwner.PROCESSOR_REFERENCE,
                frozenset((atom_id_by_text["123-456"],)),
            ),
        ),
        (),
    )


def test_description_rejects_competing_standalone_processor_references() -> None:
    references = (
        _cell(
            "123-456",
            2,
            bbox=(100.0, 30.0, 119.0, 40.0),
            words=(_word("123-456", 100.0, 119.0),),
        ),
        _cell(
            "789-012",
            2,
            bbox=(121.0, 30.0, 140.0, 40.0),
            words=(_word("789-012", 121.0, 140.0),),
        ),
    )
    row, region, merchant = _description_band_with_extra_cells(references)
    ledger = EvidenceLedger.from_rows((row,))

    extraction = extract_description((row,), region, None, ledger)
    validation = ledger.validate_claims(extraction.claims)

    assert extraction == DescriptionExtraction(
        "Merchant",
        (_claim(SemanticOwner.DESCRIPTION, ledger, merchant),),
        (),
    )
    assert all(
        ledger.atoms_for_cell(reference) <= validation.unclaimed_atom_ids
        for reference in references
    )


def test_description_rejects_misaligned_standalone_processor_reference() -> None:
    reference = _cell(
        "123-456",
        2,
        bbox=(105.0, 45.0, 128.0, 55.0),
        words=(_word("123-456", 105.0, 128.0, 45.0),),
    )
    row, region, _ = _description_band_with_extra_cell(reference)
    ledger = EvidenceLedger.from_rows((row,))

    extraction = extract_description((row,), region, None, ledger)

    assert all(claim.owner is not SemanticOwner.PROCESSOR_REFERENCE for claim in extraction.claims)


def test_description_rejects_processor_reference_on_structural_continuation() -> None:
    reference = _cell(
        "123-456",
        2,
        bbox=(105.0, 30.0, 128.0, 40.0),
        words=(_word("123-456", 105.0, 128.0),),
    )
    row, region, _ = _description_band_with_extra_cell(reference)
    row = row.model_copy(update={"diagnostics": ("subordinate_auxiliary_continuation",)})
    region = region.model_copy(
        update={
            "rows": (row,),
            "table_schema": region.table_schema.model_copy(update={"sample_cells": row.cells}),
        }
    )
    ledger = EvidenceLedger.from_rows((row,))

    extraction = extract_description((row,), region, None, ledger)

    assert all(claim.owner is not SemanticOwner.PROCESSOR_REFERENCE for claim in extraction.claims)


@pytest.mark.parametrize(
    "typed_primary",
    ("99.00", "01/02/2026", "1/3", "USD", "12%", "+123456", "(123456)"),
)
def test_description_rejects_processor_reference_beside_only_typed_semantic_cell(
    typed_primary: str,
) -> None:
    reference = _cell(
        "123-456",
        2,
        bbox=(105.0, 30.0, 128.0, 40.0),
        words=(_word("123-456", 105.0, 128.0),),
    )
    row, region, primary = _description_band_with_extra_cell(
        reference,
        primary_text=typed_primary,
    )
    ledger = EvidenceLedger.from_rows((row,))

    extraction = extract_description((row,), region, None, ledger)
    validation = ledger.validate_claims(extraction.claims)

    assert all(claim.owner is not SemanticOwner.PROCESSOR_REFERENCE for claim in extraction.claims)
    assert ledger.atoms_for_cell(primary) <= validation.unclaimed_atom_ids


@pytest.mark.parametrize(
    "semantic_text",
    (
        "99.00",
        "01/02/2026",
        "1/3",
        "USD",
        "12%",
        "+123456",
        "-123456",
        "\N{MINUS SIGN}123456",
        "(123456)",
        "123456-",
    ),
)
def test_description_does_not_claim_separate_typed_semantic_cell(
    semantic_text: str,
) -> None:
    semantic = _cell(
        semantic_text,
        2,
        bbox=(105.0, 30.0, 128.0, 40.0),
        words=(_word(semantic_text, 105.0, 128.0),),
    )
    row, region, merchant = _description_band_with_extra_cell(semantic)
    ledger = EvidenceLedger.from_rows((row,))

    assert extract_description((row,), region, None, ledger) == DescriptionExtraction(
        "Merchant",
        (_claim(SemanticOwner.DESCRIPTION, ledger, merchant),),
        (),
    )


@pytest.mark.parametrize("fragment", ("(Branch)", "-Market", "Market-", "+Cafe"))
def test_description_keeps_alphabetic_fragment_with_edge_punctuation(fragment: str) -> None:
    punctuated = _cell(
        fragment,
        2,
        bbox=(105.0, 30.0, 140.0, 40.0),
        words=(_word(fragment, 105.0, 140.0),),
    )
    row, region, merchant = _description_band_with_extra_cell(punctuated)
    ledger = EvidenceLedger.from_rows((row,))

    extraction = extract_description((row,), region, None, ledger)
    validation = ledger.validate_claims(extraction.claims)

    assert extraction.value == f"Merchant {fragment}"
    assert not ledger.atoms_for_cell(merchant) & validation.unclaimed_atom_ids
    assert not ledger.atoms_for_cell(punctuated) & validation.unclaimed_atom_ids


@pytest.mark.parametrize(
    ("clusters", "expected_index"),
    (
        (
            (
                EvidenceCluster((0.0, 0.0, 10.0, 10.0), frozenset({0}), "ALPHA"),
                EvidenceCluster((20.0, 0.0, 30.0, 10.0), frozenset({1}), "BETA"),
            ),
            0,
        ),
        (
            (
                EvidenceCluster((0.0, 0.0, 10.0, 10.0), frozenset({0}), "אלפא"),
                EvidenceCluster((20.0, 0.0, 30.0, 10.0), frozenset({1}), "בטא"),
            ),
            1,
        ),
    ),
)
def test_primary_description_cluster_preserves_ltr_and_rtl_edges(
    clusters: tuple[EvidenceCluster, EvidenceCluster],
    expected_index: int,
) -> None:
    assert _primary_description_cluster(clusters) is clusters[expected_index]


def test_description_splits_date_boundary_and_claims_only_residual_text() -> None:
    compound = _cell(
        "01/02/26 Merchant",
        1,
        bbox=(20.0, 30.0, 90.0, 40.0),
        words=(
            _word("01/02/26", 20.0, 48.0),
            _word("Merchant", 52.0, 90.0),
        ),
    )
    row = _row(compound, _cell("4.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (row,),
    )
    ledger = EvidenceLedger.from_rows((row,))
    merchant_ids = frozenset(atom.atom_id for atom in ledger.atoms if atom.text == "Merchant")

    assert extract_description((row,), region, _year_context(), ledger) == DescriptionExtraction(
        "Merchant",
        (EvidenceClaim(SemanticOwner.DESCRIPTION, merchant_ids),),
        (),
    )


def test_description_continuation_preserves_text_claim_order_and_ownership() -> None:
    description = _cell("Merchant", 1, 30.0)
    base = _row(_cell("01/02/2026", 0), description, _cell("10.00", 2))
    continuation_cell = _cell("IRELAND", 1, 41.0)
    continuation = _row(continuation_cell)
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (base, continuation),
    )
    ledger = EvidenceLedger.from_rows((base, continuation))

    assert is_description_continuation(continuation, base, region)
    assert extract_description((base, continuation), region, None, ledger) == DescriptionExtraction(
        "Merchant IRELAND",
        (
            _claim(SemanticOwner.DESCRIPTION, ledger, description),
            _claim(SemanticOwner.DESCRIPTION, ledger, continuation_cell),
        ),
        (),
    )


def test_description_column_only_continuation_is_owned_without_boundary_fallback() -> None:
    base = _row(
        _cell("01/02/2026", 0),
        _cell("Merchant", 1),
        _cell("10.00", 3),
    )
    continuation = _row(
        _cell("IRELAND", 1, 41.0),
        _cell("note", 2, 41.0),
    )
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.UNKNOWN,
            ColumnRole.AMOUNT,
        ),
        (base, continuation),
    )

    assert is_description_continuation(continuation, base, region)


@pytest.mark.parametrize("merchant_suffix", ("", " 42"))
def test_description_extracts_processor_reference_as_a_distinct_claim(
    merchant_suffix: str,
) -> None:
    rows: list[Row] = []
    descriptions: list[Cell] = []
    for raw_date, y in (("20/06/2026", 30.0), ("25/06/2026", 50.0)):
        external = _cell(
            "OPENAI",
            1,
            y,
            words=(_word("OPENAI", 50.0, 70.0, y),),
        )
        description = _cell(
            f"*CHATGPT{merchant_suffix} .OPENAI",
            2,
            y,
            words=tuple(
                word
                for word in (
                    _word("*CHATGPT", 100.0, 125.0, y),
                    _word("42", 126.0, 130.0, y) if merchant_suffix else None,
                    _word(".OPENAI", 141.0, 149.0, y),
                )
                if word is not None
            ),
        )
        descriptions.append(description)
        rows.append(
            _row(
                _cell("10.00", 0, y),
                external,
                description,
                _cell(raw_date, 3, y),
            )
        )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        tuple(rows),
    )
    ledger = EvidenceLedger.from_rows((rows[0],))
    description_ids = ledger.atoms_for_cell(descriptions[0])
    merchant_ids = frozenset(
        atom_id for atom_id in description_ids if ledger.atoms[atom_id].text in {"*CHATGPT", "42"}
    )
    processor_ids = frozenset(
        atom_id for atom_id in description_ids if ledger.atoms[atom_id].text == ".OPENAI"
    )

    assert extract_description((rows[0],), region, None, ledger) == DescriptionExtraction(
        f"*CHATGPT{merchant_suffix}",
        (
            EvidenceClaim(SemanticOwner.DESCRIPTION, merchant_ids),
            EvidenceClaim(SemanticOwner.PROCESSOR_REFERENCE, processor_ids),
        ),
        (),
    )


def test_description_recovers_boundary_cluster_from_adjacent_unknown_column() -> None:
    unknown = _cell(
        "Category SUFFIX",
        0,
        bbox=(0.0, 30.0, 49.0, 40.0),
        words=(
            _word("Category", 2.0, 20.0),
            _word("SUFFIX", 42.0, 49.0),
        ),
    )
    description = _cell(
        "Merchant",
        1,
        words=(_word("Merchant", 50.0, 80.0),),
    )
    row = _row(unknown, description, _cell("10.00", 2))
    region = _region(
        (ColumnRole.UNKNOWN, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (row,),
    )
    ledger = EvidenceLedger.from_rows((row,))
    category_ids = frozenset(atom.atom_id for atom in ledger.atoms if atom.text == "Category")
    description_ids = frozenset(
        atom.atom_id for atom in ledger.atoms if atom.text in {"SUFFIX", "Merchant"}
    )

    assert extract_description((row,), region, None, ledger) == DescriptionExtraction(
        "SUFFIX Merchant",
        (
            EvidenceClaim(SemanticOwner.ANCILLARY, category_ids),
            EvidenceClaim(SemanticOwner.DESCRIPTION, description_ids),
        ),
        (),
    )


def test_description_marks_competing_continuation_clusters_in_order() -> None:
    description = _cell("Merchant", 1, 30.0)
    base = _row(_cell("01/02/2026", 0), description, _cell("10.00", 2))
    continuation_cell = _cell(
        "ALPHA BETA",
        1,
        41.0,
        words=(
            _word("ALPHA", 50.0, 60.0, 41.0),
            _word("BETA", 80.0, 90.0, 41.0),
        ),
    )
    continuation = _row(
        continuation_cell,
        diagnostics=("subordinate_auxiliary_continuation",),
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (base, continuation),
    )
    ledger = EvidenceLedger.from_rows((base, continuation))

    assert is_description_continuation(continuation, base, region)
    assert extract_description((base, continuation), region, None, ledger) == DescriptionExtraction(
        "Merchant ALPHA BETA",
        (
            _claim(SemanticOwner.DESCRIPTION, ledger, description),
            _claim(SemanticOwner.DESCRIPTION, ledger, continuation_cell),
        ),
        ("ambiguous_description_continuation",),
    )


@pytest.mark.parametrize(
    ("raw_text", "expected"),
    (
        (
            'בע " מ',
            "בע״מ",
        ),
        (") ה", "(ה)"),
    ),
)
def test_description_preserves_merchant_punctuation(raw_text: str, expected: str) -> None:
    description = _cell(raw_text, 1)
    row = _row(_cell("24/06/2026", 0), description, _cell("10.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (row,),
    )
    ledger = EvidenceLedger.from_rows((row,))

    assert extract_description((row,), region, None, ledger) == DescriptionExtraction(
        expected,
        (_claim(SemanticOwner.DESCRIPTION, ledger, description),),
        (),
    )


def test_description_preserves_empty_result_and_ordered_diagnostic() -> None:
    row = _row(_cell("24/06/2026", 0), _cell("10.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (row,),
    )

    assert extract_description(
        (row,),
        region,
        None,
        EvidenceLedger.from_rows((row,)),
    ) == DescriptionExtraction(None, (), ("missing_description_cell",))
