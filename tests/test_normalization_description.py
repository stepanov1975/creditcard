from __future__ import annotations

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
        "is_description_continuation",
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


def test_description_extracts_processor_reference_as_a_distinct_claim() -> None:
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
            "*CHATGPT .OPENAI",
            2,
            y,
            words=(
                _word("*CHATGPT", 100.0, 125.0, y),
                _word(".OPENAI", 141.0, 149.0, y),
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
        atom_id for atom_id in description_ids if ledger.atoms[atom_id].text == "*CHATGPT"
    )
    processor_ids = frozenset(
        atom_id for atom_id in description_ids if ledger.atoms[atom_id].text == ".OPENAI"
    )

    assert extract_description((rows[0],), region, None, ledger) == DescriptionExtraction(
        "*CHATGPT",
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
