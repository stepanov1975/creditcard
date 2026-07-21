from __future__ import annotations

import math
from collections.abc import Callable

import pytest
from pydantic import ValidationError

from ccparser.evidence import Word
from ccparser.geometry import BBox
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableRegion, TableSchema

type LayoutBBoxFactory = Callable[[BBox], object]


def _word() -> Word:
    return Word(
        text="Synthetic",
        bbox=(10.0, 20.0, 50.0, 30.0),
        source="digital",
        confidence=1.0,
    )


def _cell(bbox: BBox = (10.0, 20.0, 50.0, 30.0)) -> Cell:
    word = _word()
    return Cell(
        page_number=1,
        bbox=bbox,
        text=word.text,
        words=(word,),
        confidence=1.0,
    )


def _row(bbox: BBox = (10.0, 20.0, 50.0, 30.0)) -> Row:
    cell = _cell()
    return Row(
        page_number=1,
        bbox=bbox,
        cells=(cell,),
        words=cell.words,
        confidence=1.0,
    )


def _column_spec(
    bbox: BBox = (10.0, 20.0, 50.0, 30.0),
    *,
    relative_x0: float = 0.0,
    relative_x1: float = 1.0,
) -> ColumnSpec:
    return ColumnSpec(
        index=0,
        page_number=1,
        bbox=bbox,
        relative_x0=relative_x0,
        relative_x1=relative_x1,
        source_cells=(_cell(),),
        confidence=1.0,
    )


def _table_schema(bbox: BBox = (10.0, 20.0, 50.0, 30.0)) -> TableSchema:
    cell = _cell()
    return TableSchema(
        page_number=1,
        bbox=bbox,
        columns=(_column_spec(),),
        header_cells=(cell,),
        sample_cells=(cell,),
        confidence=1.0,
    )


def _table_region(bbox: BBox = (10.0, 20.0, 50.0, 30.0)) -> TableRegion:
    row = _row()
    return TableRegion(
        page_number=1,
        bbox=bbox,
        header=row,
        rows=(row,),
        table_schema=_table_schema(),
        confidence=1.0,
    )


_BBOX_FACTORIES: tuple[LayoutBBoxFactory, ...] = (
    _cell,
    _row,
    _column_spec,
    _table_schema,
    _table_region,
)

_INVALID_BBOXES: tuple[tuple[str, BBox], ...] = (
    ("nan", (math.nan, 0.0, 10.0, 10.0)),
    ("positive-infinity", (0.0, 0.0, math.inf, 10.0)),
    ("negative-infinity", (-math.inf, 0.0, 10.0, 10.0)),
    ("inverted-x", (10.0, 0.0, 9.0, 10.0)),
    ("inverted-y", (0.0, 10.0, 10.0, 9.0)),
)

_VALID_BBOXES: tuple[tuple[str, BBox], ...] = (
    ("ordered", (0.0, 0.0, 10.0, 10.0)),
    ("zero-area", (5.0, 5.0, 5.0, 5.0)),
    ("outside-page", (-0.25, -0.5, 100.25, 200.5)),
)


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


@pytest.mark.parametrize("factory", _BBOX_FACTORIES, ids=lambda value: value.__name__)
@pytest.mark.parametrize("_name,bbox", _INVALID_BBOXES, ids=[name for name, _ in _INVALID_BBOXES])
def test_layout_bbox_models_reject_impossible_geometry(
    factory: LayoutBBoxFactory,
    _name: str,
    bbox: BBox,
) -> None:
    with pytest.raises(ValidationError):
        factory(bbox)


@pytest.mark.parametrize("factory", _BBOX_FACTORIES, ids=lambda value: value.__name__)
@pytest.mark.parametrize("_name,bbox", _VALID_BBOXES, ids=[name for name, _ in _VALID_BBOXES])
def test_layout_bbox_models_accept_ordered_finite_geometry(
    factory: LayoutBBoxFactory,
    _name: str,
    bbox: BBox,
) -> None:
    factory(bbox)


@pytest.mark.parametrize(
    "relative_x0,relative_x1",
    ((0.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
)
def test_column_spec_accepts_ordered_relative_band_boundaries(
    relative_x0: float,
    relative_x1: float,
) -> None:
    column = _column_spec(relative_x0=relative_x0, relative_x1=relative_x1)

    assert (column.relative_x0, column.relative_x1) == (relative_x0, relative_x1)


def test_column_spec_rejects_inverted_relative_band() -> None:
    with pytest.raises(ValidationError):
        ColumnSpec(
            index=0,
            page_number=1,
            bbox=(10.0, 20.0, 50.0, 30.0),
            relative_x0=0.75,
            relative_x1=0.25,
            confidence=1.0,
        )
