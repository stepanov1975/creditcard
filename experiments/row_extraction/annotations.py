"""Validate human-reviewed row annotations without treating accepted output as truth."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Never

from pydantic import Field

from ccparser.decimal_math import finite_decimal, plain_decimal_string
from ccparser.models import TransactionKind
from ccparser.money import canonical_currency
from ccparser.normalization_dates import _parse_date
from ccparser.normalization_fields import _parse_installment
from ccparser.text_tokens import normalize_text
from experiments.row_extraction.contracts import (
    PRIMARY_REQUIRED_FIELD_ROLES,
    BBox,
    FieldRole,
    FrozenRow,
    GoldField,
    GoldRow,
    OcrReference,
    RowType,
    _FrozenModel,
)

type _RowIdentity = tuple[str, str]
type _ReferenceIdentity = tuple[str, str, FieldRole, BBox]

_AMOUNT_ROLES = frozenset({FieldRole.BILLED_AMOUNT, FieldRole.ORIGINAL_AMOUNT})
_CURRENCY_ROLES = frozenset({FieldRole.BILLING_CURRENCY, FieldRole.ORIGINAL_CURRENCY})
_DATE_ROLES = frozenset(
    {
        FieldRole.TRANSACTION_DATE,
        FieldRole.POSTING_DATE,
        FieldRole.CONVERSION_DATE,
    }
)
_TEXT_ROLES = frozenset({FieldRole.DESCRIPTION, FieldRole.ANCILLARY})


class AnnotationError(ValueError):
    """Reviewed labels violate the frozen annotation contract."""


class AnnotationSummary(_FrozenModel):
    """Privacy-safe annotation coverage containing aggregate counts only."""

    row_count: int = Field(ge=0)
    label_count: int = Field(ge=0)
    field_count: int = Field(ge=0)
    primary_row_count: int = Field(ge=0)
    continuation_row_count: int = Field(ge=0)
    structural_row_count: int = Field(ge=0)
    ambiguous_row_count: int = Field(ge=0)
    ocr_reference_count: int = Field(ge=0)
    ocr_referenced_row_count: int = Field(ge=0)
    ocr_referenced_field_count: int = Field(ge=0)


def _identity(record: FrozenRow | GoldRow | OcrReference) -> _RowIdentity:
    return record.document_id, record.row_id


def _fail(message: str, identity: _RowIdentity) -> Never:
    document_id, row_id = identity
    raise AnnotationError(f"{message} [document_id={document_id} row_id={row_id}]")


def _finite_ordered_bbox(bbox: BBox) -> bool:
    x0, y0, x1, y1 = bbox
    return all(math.isfinite(value) for value in bbox) and x0 < x1 and y0 < y1


def _inside(outer: BBox, inner: BBox) -> bool:
    if not _finite_ordered_bbox(outer) or not _finite_ordered_bbox(inner):
        return False
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


def _regions_overlap(first: BBox, second: BBox) -> bool:
    return min(first[2], second[2]) > max(first[0], second[0]) and min(first[3], second[3]) > max(
        first[1], second[1]
    )


def _canonical_decimal(value: str) -> Decimal | None:
    try:
        parsed = finite_decimal(Decimal(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if plain_decimal_string(parsed) == value else None


def _canonical_date(value: str) -> bool:
    parsed, diagnostic = _parse_date(value, None)
    return parsed is not None and diagnostic is None and parsed.isoformat() == value


def _canonical_field(field: GoldField) -> bool:
    value = field.canonical_value
    if field.role in _TEXT_ROLES:
        return bool(value) and normalize_text(value) == value
    if field.role in _DATE_ROLES:
        return _canonical_date(value)
    if field.role in _AMOUNT_ROLES or field.role is FieldRole.FX_RATE:
        return _canonical_decimal(value) is not None
    if field.role in _CURRENCY_ROLES:
        return canonical_currency(value) == value
    if field.role is FieldRole.KIND:
        try:
            TransactionKind(value)
        except ValueError:
            return False
        return True
    if field.role is FieldRole.INSTALLMENT:
        parsed = _parse_installment(value)
        return parsed is not None and f"{parsed[0]}/{parsed[1]}" == value
    return False


def _index_rows(rows: Iterable[FrozenRow]) -> dict[_RowIdentity, FrozenRow]:
    indexed: dict[_RowIdentity, FrozenRow] = {}
    for row in rows:
        identity = _identity(row)
        if identity in indexed:
            _fail("duplicate frozen row identity", identity)
        if not _finite_ordered_bbox(row.bbox):
            _fail("frozen row bbox is invalid", identity)
        atom_ids = tuple(atom.atom_id for atom in row.atoms)
        if len(atom_ids) != len(set(atom_ids)):
            _fail("frozen row atom IDs must be unique", identity)
        indexed[identity] = row
    return indexed


def _index_labels(
    labels: Iterable[GoldRow],
    rows: Mapping[_RowIdentity, FrozenRow],
) -> dict[_RowIdentity, GoldRow]:
    indexed: dict[_RowIdentity, GoldRow] = {}
    for label in labels:
        identity = _identity(label)
        if identity in indexed:
            _fail("duplicate gold label identity", identity)
        if identity not in rows:
            _fail("gold label has no frozen row", identity)
        indexed[identity] = label
    for identity in rows:
        if identity not in indexed:
            _fail("frozen row is missing a gold label", identity)
    return indexed


def _validate_row_type(
    row: FrozenRow,
    label: GoldRow,
    rows: Mapping[_RowIdentity, FrozenRow],
    labels: Mapping[_RowIdentity, GoldRow],
) -> None:
    identity = _identity(row)
    is_ambiguous = label.row_type is RowType.AMBIGUOUS
    if label.ambiguous != is_ambiguous:
        _fail("ambiguous flag must match ambiguous row type", identity)
    if is_ambiguous and label.fields:
        _fail("ambiguous row cannot assert unique fields", identity)
    if label.row_type is RowType.STRUCTURAL and label.fields:
        _fail("structural row cannot assert transaction fields", identity)
    if label.row_type is RowType.PRIMARY_TRANSACTION:
        roles = {field.role for field in label.fields}
        if not roles >= PRIMARY_REQUIRED_FIELD_ROLES:
            _fail("primary row is missing required transaction fields", identity)
    if label.row_type is not RowType.CONTINUATION:
        return
    if row.previous_row_id is None:
        _fail("continuation row has no fixed predecessor", identity)
    predecessor_identity = (row.document_id, row.previous_row_id)
    predecessor = rows.get(predecessor_identity)
    if predecessor is None:
        _fail("continuation predecessor is not a fixed row", identity)
    if predecessor.next_row_id != row.row_id:
        _fail("continuation predecessor is not reciprocal", identity)
    predecessor_label = labels[predecessor_identity]
    if predecessor_label.row_type not in {
        RowType.PRIMARY_TRANSACTION,
        RowType.CONTINUATION,
    }:
        _fail("continuation predecessor has no transaction ownership", identity)
    if not label.fields:
        _fail("continuation row has no uniquely supported fields", identity)


def _validate_field_support(row: FrozenRow, label: GoldRow) -> None:
    identity = _identity(row)
    roles = tuple(field.role for field in label.fields)
    if len(roles) != len(set(roles)):
        _fail("gold field roles must be unique", identity)

    atoms = {atom.atom_id: atom for atom in row.atoms}
    atom_order = {atom.atom_id: index for index, atom in enumerate(row.atoms)}
    owners: dict[str, FieldRole] = {}
    regions: list[tuple[FieldRole, BBox]] = []
    supports: list[tuple[FieldRole, BBox]] = []
    by_role = {field.role: field for field in label.fields}
    for field in label.fields:
        if not field.atom_ids and field.source_region is None:
            _fail("gold field requires atom IDs or source region", identity)
        if len(field.atom_ids) != len(set(field.atom_ids)):
            _fail("gold field atom IDs must be unique", identity)
        for atom_id in field.atom_ids:
            atom = atoms.get(atom_id)
            if atom is None:
                _fail("gold atom is not present in frozen row", identity)
            if not _inside(row.bbox, atom.bbox):
                _fail("gold atom is outside the exact fixed row", identity)
            previous_role = owners.get(atom_id)
            if previous_role is not None and {
                previous_role,
                field.role,
            } != {FieldRole.BILLED_AMOUNT, FieldRole.KIND}:
                _fail("gold atom is owned by multiple fields", identity)
            owners[atom_id] = field.role
        positions = tuple(atom_order[atom_id] for atom_id in field.atom_ids)
        if positions != tuple(sorted(positions)):
            _fail("gold field atom IDs must preserve frozen source order", identity)
        if field.source_region is not None:
            if not _inside(row.bbox, field.source_region):
                _fail("gold source region is outside the exact fixed row", identity)
            if field.atom_ids and not all(
                _regions_overlap(field.source_region, atoms[atom_id].bbox)
                for atom_id in field.atom_ids
            ):
                _fail("gold source region does not overlap declared atoms", identity)
            for previous_role, previous_region in regions:
                if _regions_overlap(previous_region, field.source_region) and {
                    previous_role,
                    field.role,
                } != {FieldRole.BILLED_AMOUNT, FieldRole.KIND}:
                    _fail("gold source regions overlap across fields", identity)
            regions.append((field.role, field.source_region))
        if not _canonical_field(field):
            _fail("invalid canonical field value", identity)
        field_support = tuple(atoms[atom_id].bbox for atom_id in field.atom_ids) + (
            (field.source_region,) if field.source_region is not None else ()
        )
        if any(
            _regions_overlap(previous_bbox, bbox)
            and {previous_role, field.role} != {FieldRole.BILLED_AMOUNT, FieldRole.KIND}
            for bbox in field_support
            for previous_role, previous_bbox in supports
        ):
            _fail("gold field supports overlap across fields", identity)
        supports.extend((field.role, bbox) for bbox in field_support)

    billed = by_role.get(FieldRole.BILLED_AMOUNT)
    kind = by_role.get(FieldRole.KIND)
    if kind is not None and (
        billed is None
        or billed.atom_ids != kind.atom_ids
        or billed.source_region != kind.source_region
    ):
        _fail("kind must use the exact billed amount support", identity)


def _validate_field_relationships(row: FrozenRow, label: GoldRow) -> None:
    identity = _identity(row)
    by_role = {field.role: field for field in label.fields}
    has_original_amount = FieldRole.ORIGINAL_AMOUNT in by_role
    has_original_currency = FieldRole.ORIGINAL_CURRENCY in by_role
    if has_original_amount != has_original_currency:
        _fail("original amount and currency must be paired", identity)

    billed = by_role.get(FieldRole.BILLED_AMOUNT)
    kind = by_role.get(FieldRole.KIND)
    if billed is None or kind is None:
        return
    amount = _canonical_decimal(billed.canonical_value)
    if amount is None:
        return
    expected = TransactionKind.CREDIT if amount < 0 else TransactionKind.CHARGE
    if amount == 0 or kind.canonical_value != expected.value:
        _fail("kind does not match billed amount sign", identity)


def _validate_continuation_ownership(
    rows: Mapping[_RowIdentity, FrozenRow],
    labels: Mapping[_RowIdentity, GoldRow],
) -> None:
    for origin, origin_label in labels.items():
        if origin_label.row_type is not RowType.CONTINUATION:
            continue
        visited: set[_RowIdentity] = set()
        current = origin
        while True:
            if current in visited:
                _fail("continuation ownership must terminate at a primary row", origin)
            visited.add(current)
            current_label = labels.get(current)
            current_row = rows.get(current)
            if current_label is None or current_row is None:
                _fail("continuation ownership must terminate at a primary row", origin)
            if current_label.row_type is RowType.PRIMARY_TRANSACTION:
                break
            if (
                current_label.row_type is not RowType.CONTINUATION
                or current_row.previous_row_id is None
            ):
                _fail("continuation ownership must terminate at a primary row", origin)
            current = (current_row.document_id, current_row.previous_row_id)


def _validate_references(
    references: Iterable[OcrReference],
    rows: Mapping[_RowIdentity, FrozenRow],
    labels: Mapping[_RowIdentity, GoldRow],
) -> tuple[int, int, int]:
    seen: set[_ReferenceIdentity] = set()
    referenced_rows: set[_RowIdentity] = set()
    referenced_fields: set[tuple[str, str, FieldRole]] = set()
    count = 0
    for reference in references:
        identity = _identity(reference)
        reference_identity = (
            reference.document_id,
            reference.row_id,
            reference.role,
            reference.source_region,
        )
        if reference_identity in seen:
            _fail("duplicate OCR reference identity", identity)
        seen.add(reference_identity)
        row = rows.get(identity)
        if row is None:
            _fail("OCR reference has no frozen row", identity)
        annotated_fields = {field.role: field for field in labels[identity].fields}
        field = annotated_fields.get(reference.role)
        if field is None:
            _fail("OCR reference role is not annotated", identity)
        if not _inside(row.bbox, reference.source_region):
            _fail("OCR reference region is outside the exact fixed row", identity)
        atom_by_id = {atom.atom_id: atom for atom in row.atoms}
        matches_support = (
            reference.source_region == field.source_region
            if field.source_region is not None
            else any(
                _regions_overlap(reference.source_region, atom_by_id[atom_id].bbox)
                for atom_id in field.atom_ids
            )
        )
        if not matches_support:
            _fail(
                "OCR reference region does not match annotated field support",
                identity,
            )
        count += 1
        referenced_rows.add(identity)
        referenced_fields.add((*identity, reference.role))
    return count, len(referenced_rows), len(referenced_fields)


def validate_annotations(
    rows: Iterable[FrozenRow],
    labels: Iterable[GoldRow],
    ocr_references: Iterable[OcrReference] = (),
) -> AnnotationSummary:
    """Validate complete reviewed labels and return aggregate privacy-safe coverage."""

    indexed_rows = _index_rows(rows)
    indexed_labels = _index_labels(labels, indexed_rows)
    for identity, row in indexed_rows.items():
        label = indexed_labels[identity]
        _validate_row_type(row, label, indexed_rows, indexed_labels)
        _validate_field_support(row, label)
        _validate_field_relationships(row, label)
    _validate_continuation_ownership(indexed_rows, indexed_labels)

    reference_count, referenced_rows, referenced_fields = _validate_references(
        ocr_references,
        indexed_rows,
        indexed_labels,
    )
    row_types = tuple(label.row_type for label in indexed_labels.values())
    return AnnotationSummary(
        row_count=len(indexed_rows),
        label_count=len(indexed_labels),
        field_count=sum(len(label.fields) for label in indexed_labels.values()),
        primary_row_count=row_types.count(RowType.PRIMARY_TRANSACTION),
        continuation_row_count=row_types.count(RowType.CONTINUATION),
        structural_row_count=row_types.count(RowType.STRUCTURAL),
        ambiguous_row_count=row_types.count(RowType.AMBIGUOUS),
        ocr_reference_count=reference_count,
        ocr_referenced_row_count=referenced_rows,
        ocr_referenced_field_count=referenced_fields,
    )


__all__ = ["AnnotationError", "AnnotationSummary", "validate_annotations"]
