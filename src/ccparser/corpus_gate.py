"""Privacy-safe immutable projections for corpus regression checks."""

from __future__ import annotations

import json
import math
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ccparser.models import (
    BatchResult,
    EvidenceReference,
    Status,
    Transaction,
    TransactionCategory,
)
from ccparser.output import canonical_json_bytes, transactions_csv_bytes

type Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
type CommitSha = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
type PresentFieldPath = Literal[
    "category",
    "conversion_date",
    "description",
    "foreign_exchange.exchange_rate",
    "foreign_exchange.fee_discount",
    "foreign_exchange.fee_percentage",
    "foreign_exchange.gross_fee",
    "foreign_exchange.net_fee",
    "installment_current",
    "installment_total",
    "original_amount",
    "original_currency",
    "posting_date",
    "transaction_date",
]

type _CanonicalJson = (
    str | int | float | bool | None | list[_CanonicalJson] | dict[str, _CanonicalJson]
)
type _GroupProjection = tuple[str, str, str, tuple[str, ...]]
type _GroupStructure = tuple[tuple[_GroupProjection, ...], ...]
type _TransactionIdentity = tuple[str, tuple[str, ...]]
type _TransactionIdentities = tuple[tuple[_TransactionIdentity, ...], ...]
type _FieldPresence = tuple[tuple[tuple[PresentFieldPath, ...], ...], ...]
type _EvidenceReferenceProjection = tuple[int, tuple[float, float, float, float], str]
type _EvidenceSiteProjection = tuple[str, tuple[_EvidenceReferenceProjection, ...]]
type _EvidenceProvenance = tuple[tuple[tuple[_EvidenceSiteProjection, ...], ...], ...]
type _AmbiguityProjection = tuple[tuple[tuple[str, ...], ...], ...]


class _GateModel(BaseModel):
    """Strict immutable base for persisted gate data."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class FieldCount(_GateModel):
    """Aggregate presence count for one closed transaction field path."""

    path: PresentFieldPath
    count: int = Field(ge=0)


class CorpusCounts(_GateModel):
    """Non-sensitive aggregate counts for one parsed corpus."""

    documents: int = Field(ge=0)
    reconciled: int = Field(ge=0)
    unreconciled: int = Field(ge=0)
    unsupported: int = Field(ge=0)
    not_statement: int = Field(ge=0)
    groups: int = Field(ge=0)
    row_results: int = Field(ge=0)
    transactions: int = Field(ge=0)
    ambiguous_transactions: int = Field(ge=0)
    ambiguity_occurrences: int = Field(ge=0)
    evidence_references: int = Field(ge=0)
    present_fields: tuple[FieldCount, ...]

    @model_validator(mode="after")
    def validate_present_fields(self) -> Self:
        paths = tuple(field.path for field in self.present_fields)
        if paths != tuple(sorted(paths)):
            raise ValueError("present fields must be sorted by path")
        if len(paths) != len(set(paths)):
            raise ValueError("present field paths must be unique")
        return self


class CorpusMembership(_GateModel):
    """Count and order-independent multiset digest for corpus inputs."""

    document_count: int = Field(ge=0)
    source_multiset_digest: Digest


class CorpusMembershipInventory(_GateModel):
    """Approved retained and quarantine corpus membership."""

    version: Literal[1]
    retained: CorpusMembership
    quarantine: CorpusMembership


class RunManifest(_GateModel):
    """Aggregate and digest-only snapshot of one parser run."""

    elapsed_seconds: Decimal = Field(ge=0)
    counts: CorpusCounts
    json_digest: Digest
    csv_digest: Digest
    ordered_status_digest: Digest
    group_structure_digest: Digest
    transaction_identity_digest: Digest
    field_presence_digest: Digest
    evidence_provenance_digest: Digest
    ambiguity_digest: Digest


@dataclass(frozen=True, slots=True)
class _StructuralProjections:
    counts: CorpusCounts
    ordered_statuses: tuple[str, tuple[str, ...]]
    group_structure: _GroupStructure
    transaction_identities: _TransactionIdentities
    field_presence: _FieldPresence
    evidence_provenance: _EvidenceProvenance
    ambiguities: _AmbiguityProjection


def _normalized_json(value: object) -> _CanonicalJson:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON numeric values must be finite")
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list | tuple):
        return [_normalized_json(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, _CanonicalJson] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON object keys must be strings")
            normalized[unicodedata.normalize("NFC", key)] = _normalized_json(item)
        return normalized
    raise TypeError("unsupported canonical JSON value")


def _digest_bytes(content: bytes) -> str:
    return sha256(content).hexdigest()


def _digest_json(value: object) -> str:
    normalized = _normalized_json(value)
    content = (
        json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )
    return _digest_bytes(content)


def digest_membership(source_hashes: Iterable[str]) -> CorpusMembership:
    """Digest a source-hash multiset without depending on traversal order."""

    ordered = tuple(sorted(source_hashes))
    return CorpusMembership(
        document_count=len(ordered),
        source_multiset_digest=_digest_json(ordered),
    )


def _transaction_present_fields(transaction: Transaction) -> tuple[PresentFieldPath, ...]:
    present: list[PresentFieldPath] = []
    if transaction.category is not TransactionCategory.UNKNOWN:
        present.append("category")
    if transaction.conversion_date is not None:
        present.append("conversion_date")
    if transaction.description is not None:
        present.append("description")
    if transaction.installment_current is not None:
        present.append("installment_current")
    if transaction.installment_total is not None:
        present.append("installment_total")
    if transaction.original_amount is not None:
        present.append("original_amount")
    if transaction.original_currency is not None:
        present.append("original_currency")
    if transaction.posting_date is not None:
        present.append("posting_date")
    if transaction.transaction_date is not None:
        present.append("transaction_date")

    details = transaction.foreign_exchange
    if details is not None:
        if details.exchange_rate is not None:
            present.append("foreign_exchange.exchange_rate")
        if details.fee_discount is not None:
            present.append("foreign_exchange.fee_discount")
        if details.fee_percentage is not None:
            present.append("foreign_exchange.fee_percentage")
        if details.gross_fee is not None:
            present.append("foreign_exchange.gross_fee")
        if details.net_fee is not None:
            present.append("foreign_exchange.net_fee")
    return tuple(sorted(present))


def _project_evidence_reference(reference: EvidenceReference) -> _EvidenceReferenceProjection:
    raw_text_digest = _digest_bytes(
        unicodedata.normalize("NFC", reference.raw_text).encode("utf-8")
    )
    return reference.page_number, reference.bbox, raw_text_digest


def _project_evidence_site(
    path: str, references: tuple[EvidenceReference, ...]
) -> _EvidenceSiteProjection:
    return path, tuple(_project_evidence_reference(reference) for reference in references)


def _transaction_evidence_provenance(
    transaction: Transaction,
) -> tuple[_EvidenceSiteProjection, ...]:
    sites = [_project_evidence_site("evidence", transaction.evidence)]
    details = transaction.foreign_exchange
    if details is not None:
        if details.exchange_rate is not None:
            sites.append(
                _project_evidence_site(
                    "foreign_exchange.exchange_rate", details.exchange_rate.evidence
                )
            )
        if details.fee_discount is not None:
            sites.append(
                _project_evidence_site(
                    "foreign_exchange.fee_discount", details.fee_discount.evidence
                )
            )
        if details.fee_percentage is not None:
            sites.append(
                _project_evidence_site(
                    "foreign_exchange.fee_percentage", details.fee_percentage.evidence
                )
            )
        if details.gross_fee is not None:
            sites.append(
                _project_evidence_site("foreign_exchange.gross_fee", details.gross_fee.evidence)
            )
        if details.net_fee is not None:
            sites.append(
                _project_evidence_site("foreign_exchange.net_fee", details.net_fee.evidence)
            )
    return tuple(sorted(sites, key=lambda item: item[0]))


def _project_structural_dimensions(batch: BatchResult) -> _StructuralProjections:
    statuses = Counter(statement.status for statement in batch.statements)
    present_field_counts: Counter[PresentFieldPath] = Counter()
    field_presence: list[tuple[tuple[PresentFieldPath, ...], ...]] = []
    evidence_provenance: list[tuple[tuple[_EvidenceSiteProjection, ...], ...]] = []
    evidence_reference_count = 0

    for statement in batch.statements:
        statement_fields: list[tuple[PresentFieldPath, ...]] = []
        statement_evidence: list[tuple[_EvidenceSiteProjection, ...]] = []
        for transaction in statement.transactions:
            transaction_fields = _transaction_present_fields(transaction)
            present_field_counts.update(transaction_fields)
            statement_fields.append(transaction_fields)

            transaction_evidence = _transaction_evidence_provenance(transaction)
            statement_evidence.append(transaction_evidence)
            evidence_reference_count += sum(
                len(references) for _, references in transaction_evidence
            )
        field_presence.append(tuple(statement_fields))
        evidence_provenance.append(tuple(statement_evidence))

    counts = CorpusCounts(
        documents=len(batch.statements),
        reconciled=statuses[Status.RECONCILED],
        unreconciled=statuses[Status.UNRECONCILED],
        unsupported=statuses[Status.UNSUPPORTED],
        not_statement=statuses[Status.NOT_STATEMENT],
        groups=sum(len(statement.groups) for statement in batch.statements),
        row_results=sum(len(statement.row_results) for statement in batch.statements),
        transactions=sum(len(statement.transactions) for statement in batch.statements),
        ambiguous_transactions=sum(
            bool(transaction.ambiguities)
            for statement in batch.statements
            for transaction in statement.transactions
        ),
        ambiguity_occurrences=sum(
            len(transaction.ambiguities)
            for statement in batch.statements
            for transaction in statement.transactions
        ),
        evidence_references=evidence_reference_count,
        present_fields=tuple(
            FieldCount(path=path, count=present_field_counts[path])
            for path in sorted(present_field_counts)
        ),
    )
    return _StructuralProjections(
        counts=counts,
        ordered_statuses=(
            batch.status.value,
            tuple(statement.status.value for statement in batch.statements),
        ),
        group_structure=tuple(
            tuple(
                (group.group_id, group.currency, group.status.value, group.transaction_ids)
                for group in statement.groups
            )
            for statement in batch.statements
        ),
        transaction_identities=tuple(
            tuple(
                (transaction.transaction_id, transaction.reconciliation_group_ids)
                for transaction in statement.transactions
            )
            for statement in batch.statements
        ),
        field_presence=tuple(field_presence),
        evidence_provenance=tuple(evidence_provenance),
        ambiguities=tuple(
            tuple(transaction.ambiguities for transaction in statement.transactions)
            for statement in batch.statements
        ),
    )


def project_run(batch: BatchResult, *, elapsed_seconds: Decimal) -> RunManifest:
    """Project a parser result into aggregate counts and one-way digests."""

    json_content = canonical_json_bytes(batch)
    csv_content = transactions_csv_bytes(batch)
    projections = _project_structural_dimensions(batch)
    return RunManifest(
        elapsed_seconds=elapsed_seconds,
        counts=projections.counts,
        json_digest=_digest_bytes(json_content),
        csv_digest=_digest_bytes(csv_content),
        ordered_status_digest=_digest_json(projections.ordered_statuses),
        group_structure_digest=_digest_json(projections.group_structure),
        transaction_identity_digest=_digest_json(projections.transaction_identities),
        field_presence_digest=_digest_json(projections.field_presence),
        evidence_provenance_digest=_digest_json(projections.evidence_provenance),
        ambiguity_digest=_digest_json(projections.ambiguities),
    )
