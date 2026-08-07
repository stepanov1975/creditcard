"""Private merchant-context contracts and aggregate reference validation."""

from __future__ import annotations

import math
import unicodedata
from collections import Counter
from collections.abc import Sequence
from enum import StrEnum
from typing import Self

from pydantic import ConfigDict, Field, ValidationError, model_validator

from experiments.row_extraction.contracts import (
    BBox,
    DatasetSplit,
    FrozenRow,
    _FrozenModel,
)
from experiments.row_extraction.visual_gold_pilot import select_visual_gold_pilot

type _RowIdentity = tuple[str, str]
type _TransactionIdentity = tuple[str, str]
type _TransactionPayload = tuple[
    str,
    tuple[str, ...],
    str,
    tuple[str, ...],
    tuple[BBox, ...],
]

_PILOT_ANCHOR_COUNT = 100


class MerchantContextError(ValueError):
    """A private merchant-context artifact failed content-free validation."""


class ContextTier(StrEnum):
    C0_ROW = "c0_row"
    C1_ADJACENT_ROWS = "c1_adjacent_rows"
    C2_LOCAL_NEIGHBORHOOD = "c2_local_neighborhood"
    C3_HEADER_NEIGHBORHOOD = "c3_header_neighborhood"
    C4_TABLE_REGION = "c4_table_region"
    C5_FULL_PAGE = "c5_full_page"


CONTEXT_TIERS = tuple(ContextTier)


class ReferenceDisposition(StrEnum):
    TRANSACTION = "transaction"
    NONTRANSACTION = "nontransaction"
    AMBIGUOUS = "ambiguous"


class AssertionDisposition(StrEnum):
    MERCHANT = "merchant"
    NONTRANSACTION = "nontransaction"
    ABSTAIN = "abstain"


class MerchantErrorCategory(StrEnum):
    INSUFFICIENT_CONTEXT_OR_MISSING_HEADER = "insufficient_context_or_missing_header"
    CONTINUATION_OWNERSHIP = "continuation_ownership"
    MERCHANT_SPAN_BOUNDARY = "merchant_span_boundary"
    MERCHANT_VERSUS_ANCILLARY = "merchant_versus_ancillary"
    MIXED_DIRECTION_OR_READING_ORDER = "mixed_direction_or_reading_order"
    OCR_OR_ATOM_SEGMENTATION = "ocr_or_atom_segmentation"
    NEIGHBORING_TRANSACTION_CONTAMINATION = "neighboring_transaction_contamination"
    UNSUPPORTED_MERCHANT_TEXT = "unsupported_merchant_text"
    CORRECT_ABSTENTION_ON_AMBIGUOUS_EVIDENCE = "correct_abstention_on_ambiguous_evidence"
    REFERENCE_AMBIGUITY_OR_DEFECT = "reference_ambiguity_or_defect"


def canonical_merchant_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


class _PrivateModel(_FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


def _ids_are_canonical(values: tuple[str, ...]) -> bool:
    return all(values) and len(values) == len(set(values))


def _merchant_text_is_canonical(text: str | None) -> bool:
    return text is not None and bool(text) and canonical_merchant_text(text) == text


class MerchantReference(_PrivateModel):
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    anchor_row_id: str = Field(min_length=1)
    disposition: ReferenceDisposition
    owner_row_id: str | None
    owned_row_ids: tuple[str, ...]
    merchant_text: str | None
    atom_ids: tuple[str, ...]
    source_regions: tuple[BBox, ...]
    ambiguity_category: MerchantErrorCategory | None

    @model_validator(mode="after")
    def has_valid_disposition_shape(self) -> Self:
        if self.disposition is ReferenceDisposition.TRANSACTION:
            if (
                self.owner_row_id is None
                or not self.owner_row_id
                or not _ids_are_canonical(self.owned_row_ids)
                or self.owner_row_id not in self.owned_row_ids
                or self.anchor_row_id not in self.owned_row_ids
                or not _merchant_text_is_canonical(self.merchant_text)
                or (not self.atom_ids and not self.source_regions)
                or self.ambiguity_category is not None
            ):
                raise ValueError("invalid transaction merchant reference")
        elif self.disposition is ReferenceDisposition.NONTRANSACTION:
            if (
                self.owner_row_id is not None
                or self.owned_row_ids
                or self.merchant_text is not None
                or self.atom_ids
                or self.source_regions
                or self.ambiguity_category is not None
            ):
                raise ValueError("invalid nontransaction merchant reference")
        elif (
            self.owner_row_id is not None
            or self.owned_row_ids
            or self.merchant_text is not None
            or self.atom_ids
            or self.source_regions
            or self.ambiguity_category is None
        ):
            raise ValueError("invalid ambiguous merchant reference")
        if self.atom_ids and not _ids_are_canonical(self.atom_ids):
            raise ValueError("invalid merchant reference atom IDs")
        return self


class MerchantAssertion(_PrivateModel):
    context_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    anchor_row_id: str = Field(min_length=1)
    disposition: AssertionDisposition
    owner_row_id: str | None
    merchant_text: str | None
    atom_ids: tuple[str, ...]
    source_regions: tuple[BBox, ...]

    @model_validator(mode="after")
    def has_valid_disposition_shape(self) -> Self:
        if self.disposition is AssertionDisposition.MERCHANT:
            if (
                self.owner_row_id is None
                or not self.owner_row_id
                or not _merchant_text_is_canonical(self.merchant_text)
                or (not self.atom_ids and not self.source_regions)
            ):
                raise ValueError("invalid merchant assertion")
        elif (
            self.owner_row_id is not None
            or self.merchant_text is not None
            or self.atom_ids
            or self.source_regions
        ):
            raise ValueError("invalid empty merchant assertion")
        if self.atom_ids and not _ids_are_canonical(self.atom_ids):
            raise ValueError("invalid merchant assertion atom IDs")
        return self


class MerchantReferenceSummary(_FrozenModel):
    anchor_count: int = Field(ge=0)
    eligible_transaction_count: int = Field(ge=0)
    ambiguous_anchor_count: int = Field(ge=0)
    nontransaction_anchor_count: int = Field(ge=0)


def _identity(row: FrozenRow | MerchantReference) -> _RowIdentity:
    row_id = row.row_id if isinstance(row, FrozenRow) else row.anchor_row_id
    return row.document_id, row_id


def _validated_references(
    references: Sequence[MerchantReference],
) -> tuple[MerchantReference, ...]:
    try:
        return tuple(
            MerchantReference.model_validate(reference.model_dump()) for reference in references
        )
    except ValidationError:
        raise MerchantContextError("merchant reference contract mismatch") from None


def _row_index(
    population: Sequence[FrozenRow],
) -> dict[str, dict[str, FrozenRow | None]]:
    result: dict[str, dict[str, FrozenRow | None]] = {}
    for row in population:
        document_rows = result.setdefault(row.document_id, {})
        if row.row_id in document_rows:
            document_rows[row.row_id] = None
        else:
            document_rows[row.row_id] = row
    return result


def _is_contained(region: BBox, container: BBox) -> bool:
    region_x0, region_y0, region_x1, region_y1 = region
    container_x0, container_y0, container_x1, container_y1 = container
    return (
        all(math.isfinite(value) for value in (*region, *container))
        and region_x0 < region_x1
        and region_y0 < region_y1
        and container_x0 <= region_x0
        and container_y0 <= region_y0
        and region_x1 <= container_x1
        and region_y1 <= container_y1
    )


def _validate_transaction_evidence(
    reference: MerchantReference,
    rows_by_document: dict[str, dict[str, FrozenRow | None]],
) -> _TransactionPayload:
    if reference.owner_row_id is None or reference.merchant_text is None:
        raise MerchantContextError("merchant reference contract mismatch")
    document_rows = rows_by_document.get(reference.document_id, {})
    owned_rows = tuple(document_rows.get(row_id) for row_id in reference.owned_row_ids)
    if any(row is None for row in owned_rows):
        raise MerchantContextError("merchant reference evidence mismatch")
    concrete_rows = tuple(row for row in owned_rows if row is not None)
    atom_counts = Counter(atom.atom_id for row in concrete_rows for atom in row.atoms)
    if any(atom_counts[atom_id] != 1 for atom_id in reference.atom_ids):
        raise MerchantContextError("merchant reference evidence mismatch")
    if any(
        not any(_is_contained(region, row.bbox) for row in concrete_rows)
        for region in reference.source_regions
    ):
        raise MerchantContextError("merchant reference evidence mismatch")
    return (
        reference.owner_row_id,
        reference.owned_row_ids,
        reference.merchant_text,
        reference.atom_ids,
        reference.source_regions,
    )


def validate_merchant_reference(
    population: Sequence[FrozenRow],
    selected_rows: Sequence[FrozenRow],
    references: Sequence[MerchantReference],
) -> MerchantReferenceSummary:
    """Validate one frozen private reference and return aggregate-only counts."""

    selected_identities = tuple(_identity(row) for row in selected_rows)
    selected_identity_set = set(selected_identities)
    if (
        len(selected_rows) != _PILOT_ANCHOR_COUNT
        or len(selected_identity_set) != _PILOT_ANCHOR_COUNT
    ):
        raise MerchantContextError("merchant reference coverage mismatch")
    if any(row.split is not DatasetSplit.TRAIN for row in selected_rows):
        raise MerchantContextError("merchant reference requires training anchors")
    try:
        expected_identities = {_identity(row) for row in select_visual_gold_pilot(population)}
    except Exception:
        raise MerchantContextError("merchant reference pilot membership mismatch") from None
    if selected_identity_set != expected_identities:
        raise MerchantContextError("merchant reference pilot membership mismatch")

    validated_references = _validated_references(references)
    reference_identities = tuple(_identity(reference) for reference in validated_references)
    if (
        len(validated_references) != _PILOT_ANCHOR_COUNT
        or len(set(reference_identities)) != _PILOT_ANCHOR_COUNT
        or set(reference_identities) != selected_identity_set
    ):
        raise MerchantContextError("merchant reference coverage mismatch")

    rows_by_document = _row_index(population)
    transaction_payloads: dict[_TransactionIdentity, _TransactionPayload] = {}
    reference_payloads: dict[_RowIdentity, _TransactionPayload] = {}
    ownership_claims: dict[_RowIdentity, tuple[_TransactionIdentity, _TransactionPayload]] = {}
    ambiguous_anchor_count = 0
    nontransaction_anchor_count = 0
    for reference in validated_references:
        if reference.disposition is ReferenceDisposition.AMBIGUOUS:
            ambiguous_anchor_count += 1
            continue
        if reference.disposition is ReferenceDisposition.NONTRANSACTION:
            nontransaction_anchor_count += 1
            continue
        payload = _validate_transaction_evidence(reference, rows_by_document)
        transaction_identity = (reference.document_id, payload[0])
        previous_payload = transaction_payloads.setdefault(transaction_identity, payload)
        if previous_payload != payload:
            raise MerchantContextError("merchant reference transaction mismatch")
        reference_payloads[_identity(reference)] = payload
        claim = transaction_identity, payload
        for owned_row_id in reference.owned_row_ids:
            owned_identity = reference.document_id, owned_row_id
            previous_claim = ownership_claims.setdefault(owned_identity, claim)
            if previous_claim != claim:
                raise MerchantContextError("merchant reference ownership mismatch")

    for owned_identity, (transaction_identity, payload) in ownership_claims.items():
        if owned_identity not in selected_identity_set:
            continue
        owned_payload = reference_payloads.get(owned_identity)
        if (
            owned_payload is None
            or (owned_identity[0], owned_payload[0]) != transaction_identity
            or owned_payload != payload
        ):
            raise MerchantContextError("merchant reference ownership mismatch")

    return MerchantReferenceSummary(
        anchor_count=len(selected_rows),
        eligible_transaction_count=len(transaction_payloads),
        ambiguous_anchor_count=ambiguous_anchor_count,
        nontransaction_anchor_count=nontransaction_anchor_count,
    )
