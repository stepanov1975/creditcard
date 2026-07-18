from __future__ import annotations

import pytest
from pydantic import ValidationError

from ccparser.evidence import Word
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableRegion, TableSchema


def test_layout_models_are_immutable_and_retain_source_evidence() -> None:
    word = Word(
        text="Synthetic",
        bbox=(10.0, 20.0, 50.0, 30.0),
        source="digital",
        confidence=1.0,
    )
    cell = Cell(
        page_number=1,
        bbox=word.bbox,
        text=word.text,
        words=(word,),
        confidence=1.0,
    )
    row = Row(
        page_number=1,
        bbox=word.bbox,
        cells=(cell,),
        words=(word,),
        confidence=1.0,
    )
    column = ColumnSpec(
        index=0,
        page_number=1,
        bbox=word.bbox,
        relative_x0=0.0,
        relative_x1=1.0,
        role=ColumnRole.DESCRIPTION,
        source_cells=(cell,),
        confidence=1.0,
    )
    schema = TableSchema(
        page_number=1,
        bbox=word.bbox,
        columns=(column,),
        header_cells=(cell,),
        sample_cells=(cell,),
        confidence=1.0,
    )
    region = TableRegion(
        page_number=1,
        bbox=word.bbox,
        header=row,
        rows=(row,),
        table_schema=schema,
        confidence=1.0,
    )

    assert region.table_schema.columns[0].source_cells[0].words == (word,)
    with pytest.raises(ValidationError):
        region.rows = ()


def test_column_roles_include_explicit_unknown_and_financial_semantics() -> None:
    assert {role.value for role in ColumnRole} >= {
        "unknown",
        "date",
        "description",
        "amount",
        "original_amount",
        "currency",
        "installment",
    }
