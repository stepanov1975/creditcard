from __future__ import annotations

import pytest

from ccparser.evidence.models import BBox as EvidenceBBox
from ccparser.evidence.models import Point as EvidencePoint
from ccparser.geometry import (
    BBox,
    Point,
    bbox_area,
    bbox_center_x,
    bbox_center_y,
    bbox_height,
    bbox_width,
    center_inside,
    intersection_over_smaller,
    intersection_over_union,
    union_bbox,
    vertical_overlap,
)


def test_evidence_models_reexport_canonical_geometry_aliases() -> None:
    assert EvidenceBBox is BBox
    assert EvidencePoint is Point


@pytest.mark.parametrize(
    ("bbox", "width", "height", "center_x", "center_y"),
    (
        ((2.0, 3.0, 8.0, 11.0), 6.0, 8.0, 5.0, 7.0),
        ((2.0, 3.0, 2.0, 11.0), 0.0, 8.0, 2.0, 7.0),
        ((2.0, 3.0, 8.0, 3.0), 6.0, 0.0, 5.0, 3.0),
    ),
)
def test_bbox_measurements_preserve_degenerate_box_behavior(
    bbox: BBox,
    width: float,
    height: float,
    center_x: float,
    center_y: float,
) -> None:
    assert bbox_width(bbox) == width
    assert bbox_height(bbox) == height
    assert bbox_center_x(bbox) == center_x
    assert bbox_center_y(bbox) == center_y


@pytest.mark.parametrize(
    ("bbox", "expected"),
    (
        ((2.0, 3.0, 8.0, 11.0), 48.0),
        ((2.0, 3.0, 2.0, 11.0), 0.0),
        ((2.0, 3.0, 8.0, 3.0), 0.0),
    ),
)
def test_bbox_area_preserves_ordinary_and_degenerate_box_behavior(
    bbox: BBox,
    expected: float,
) -> None:
    assert bbox_area(bbox) == expected


@pytest.mark.parametrize(
    ("first", "second", "expected_iou", "expected_smaller", "expected_vertical"),
    (
        ((0.0, 0.0, 4.0, 4.0), (0.0, 0.0, 4.0, 4.0), 1.0, 1.0, 1.0),
        ((0.0, 0.0, 4.0, 4.0), (5.0, 5.0, 9.0, 9.0), 0.0, 0.0, 0.0),
        ((0.0, 0.0, 0.0, 4.0), (0.0, 0.0, 4.0, 4.0), 0.0, 0.0, 1.0),
        ((0.0, 0.0, 4.0, 0.0), (0.0, 0.0, 4.0, 4.0), 0.0, 0.0, 0.0),
    ),
)
def test_overlap_metrics_preserve_identical_disjoint_and_degenerate_behavior(
    first: BBox,
    second: BBox,
    expected_iou: float,
    expected_smaller: float,
    expected_vertical: float,
) -> None:
    assert intersection_over_union(first, second) == expected_iou
    assert intersection_over_smaller(first, second) == expected_smaller
    assert vertical_overlap(first, second) == expected_vertical


@pytest.mark.parametrize(
    ("inner", "outer", "expected"),
    (
        ((8.0, 10.0, 12.0, 14.0), (10.0, 10.0, 20.0, 20.0), True),
        ((18.0, 16.0, 22.0, 20.0), (10.0, 10.0, 20.0, 20.0), True),
        ((14.0, 8.0, 16.0, 12.0), (10.0, 10.0, 20.0, 20.0), True),
        ((14.0, 18.0, 16.0, 22.0), (10.0, 10.0, 20.0, 20.0), True),
        ((20.1, 12.0, 22.1, 14.0), (10.0, 10.0, 20.0, 20.0), False),
    ),
)
def test_center_inside_uses_inclusive_outer_boundaries(
    inner: BBox, outer: BBox, expected: bool
) -> None:
    assert center_inside(inner, outer) is expected


def test_union_bbox_is_independent_of_input_order() -> None:
    boxes: tuple[BBox, ...] = (
        (10.0, 20.0, 30.0, 40.0),
        (-5.0, 25.0, 15.0, 35.0),
        (8.0, -2.0, 50.0, 45.0),
    )

    expected = (-5.0, -2.0, 50.0, 45.0)
    assert union_bbox(boxes) == expected
    assert union_bbox(reversed(boxes)) == expected


def test_union_bbox_rejects_empty_input() -> None:
    with pytest.raises(ValueError):
        union_bbox(())
