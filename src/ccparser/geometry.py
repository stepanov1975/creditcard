"""Dependency-neutral helpers for document-space geometry."""

from __future__ import annotations

from collections.abc import Iterable

type BBox = tuple[float, float, float, float]
type Point = tuple[float, float]


def bbox_width(bbox: BBox) -> float:
    """Return the non-negative width of a bounding box."""

    return max(0.0, bbox[2] - bbox[0])


def bbox_height(bbox: BBox) -> float:
    """Return the non-negative height of a bounding box."""

    return max(0.0, bbox[3] - bbox[1])


def bbox_center_x(bbox: BBox) -> float:
    """Return the horizontal midpoint of a bounding box."""

    return (bbox[0] + bbox[2]) / 2


def bbox_center_y(bbox: BBox) -> float:
    """Return the vertical midpoint of a bounding box."""

    return (bbox[1] + bbox[3]) / 2


def union_bbox(boxes: Iterable[BBox]) -> BBox:
    """Return the smallest bounding box containing every input box."""

    candidates = tuple(boxes)
    if not candidates:
        raise ValueError("at least one bounding box is required")
    return (
        min(box[0] for box in candidates),
        min(box[1] for box in candidates),
        max(box[2] for box in candidates),
        max(box[3] for box in candidates),
    )


def _intersection_area(first: BBox, second: BBox) -> float:
    width = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    height = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    return width * height


def intersection_over_union(first: BBox, second: BBox) -> float:
    """Return intersection area divided by combined union area."""

    intersection = _intersection_area(first, second)
    union = (
        bbox_width(first) * bbox_height(first)
        + bbox_width(second) * bbox_height(second)
        - intersection
    )
    return intersection / union if union > 0.0 else 0.0


def intersection_over_smaller(first: BBox, second: BBox) -> float:
    """Return intersection area divided by the smaller box area."""

    intersection = _intersection_area(first, second)
    smaller = min(
        bbox_width(first) * bbox_height(first),
        bbox_width(second) * bbox_height(second),
    )
    return intersection / smaller if smaller > 0.0 else 0.0


def vertical_overlap(first: BBox, second: BBox) -> float:
    """Return vertical intersection divided by the smaller box height."""

    overlap = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    smaller_height = min(bbox_height(first), bbox_height(second))
    return overlap / smaller_height if smaller_height > 0.0 else 0.0


def center_inside(inner: BBox, outer: BBox) -> bool:
    """Return whether ``inner`` has its center within inclusive ``outer`` bounds."""

    center_x = bbox_center_x(inner)
    center_y = bbox_center_y(inner)
    return outer[0] <= center_x <= outer[2] and outer[1] <= center_y <= outer[3]
