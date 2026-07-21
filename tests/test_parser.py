from __future__ import annotations

import hashlib
import json
import time
import traceback
from base64 import b64decode
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import fitz  # type: ignore[import-untyped]  # PyMuPDF does not publish typing metadata.
import pytest

import ccparser.parser as parser_module
from ccparser.discovery import (
    DateTokenStyle,
    DiscoveredDateYearContext,
    DiscoveredField,
    DiscoveredPrintedTotal,
    DocumentClassification,
    RejectedTotalCandidate,
    StatementDiscovery,
    StatementGroupDiscovery,
)
from ccparser.evidence import DocumentEvidence, ExtractionQuality, OcrError, PageEvidence
from ccparser.evidence.models import BBox, Glyph, Word
from ccparser.layout import Cell, ColumnRole, ColumnSpec, Row, TableRegion, TableSchema
from ccparser.models import (
    BatchResult,
    EvidenceReference,
    ReconciliationGroup,
    StatementResult,
    Status,
    Transaction,
    TransactionKind,
)
from ccparser.normalize import RowNormalizationResult, StatementNormalization
from ccparser.output import canonical_json_bytes
from ccparser.parser import (
    ParserInputError,
    ParserRuntimeError,
    parse_directory,
    parse_statement,
)
from ccparser.summary import discovery_summary, row_summaries


def _evidence(content: bytes) -> DocumentEvidence:
    return DocumentEvidence(source_sha256=hashlib.sha256(content).hexdigest(), pages=())


def _discovery(
    classification: DocumentClassification,
    *,
    reason_codes: tuple[str, ...] = (),
    diagnostics: tuple[str, ...] = (),
) -> StatementDiscovery:
    return StatementDiscovery(
        classification=classification,
        confidence=1.0,
        reason_codes=reason_codes,
        diagnostics=diagnostics,
    )


def _normalizer(
    status: Status,
    *,
    diagnostics: tuple[str, ...] = (),
) -> Callable[[StatementDiscovery], StatementNormalization]:
    def normalize(discovery: StatementDiscovery) -> StatementNormalization:
        groups = (
            (
                ReconciliationGroup(
                    group_id="group-0001",
                    currency="ILS",
                    printed_total=Decimal("0.00"),
                    calculated_total=Decimal("0.00"),
                    difference=Decimal("0.00"),
                    transaction_ids=(),
                    status=Status.RECONCILED,
                ),
            )
            if status is Status.RECONCILED
            else ()
        )
        reconciliation = StatementResult(
            status=status,
            transactions=(),
            groups=groups,
            diagnostics=diagnostics,
        )
        return StatementNormalization(
            discovery=discovery,
            transactions=(),
            printed_totals=(),
            row_results=(),
            reconciliation=reconciliation,
            confidence=1.0,
            diagnostics=diagnostics,
        )

    return normalize


@pytest.mark.parametrize(
    ("classification", "expected"),
    (
        (DocumentClassification.NOT_STATEMENT, Status.NOT_STATEMENT),
        (DocumentClassification.AMBIGUOUS, Status.UNSUPPORTED),
    ),
)
def test_parse_statement_maps_non_statement_and_unknown_layout_without_normalizing(
    tmp_path: Path,
    classification: DocumentClassification,
    expected: Status,
) -> None:
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"synthetic")
    normalized = False

    def extractor(path: Path, ocr_provider: object) -> DocumentEvidence:
        assert path == source
        assert ocr_provider is not None
        return _evidence(path.read_bytes())

    def normalizer(discovery: StatementDiscovery) -> StatementNormalization:
        nonlocal normalized
        normalized = True
        return _normalizer(Status.RECONCILED)(discovery)

    result = parse_statement(
        source,
        extractor=extractor,
        discoverer=lambda evidence: _discovery(
            classification,
            reason_codes=("classification_reason",),
            diagnostics=("layout_diagnostic",),
        ),
        normalizer=normalizer,
        ocr_provider=object(),
    )

    assert result.status is expected
    assert result.source_name == "synthetic.pdf"
    assert result.source_sha256 == hashlib.sha256(b"synthetic").hexdigest()
    assert result.statement_id == result.source_sha256
    assert result.diagnostics == ("classification_reason", "layout_diagnostic")
    assert normalized is False


@pytest.mark.parametrize("normalized_status", (Status.RECONCILED, Status.UNRECONCILED))
def test_parse_statement_maps_normalized_statement_and_strict_does_not_change_data(
    tmp_path: Path,
    normalized_status: Status,
) -> None:
    source = tmp_path / "statement.pdf"
    source.write_bytes(b"statement")
    evidence = _evidence(source.read_bytes())
    discovery = _discovery(DocumentClassification.STATEMENT)
    dependencies = {
        "extractor": lambda path, ocr_provider: evidence,
        "discoverer": lambda value: discovery,
        "normalizer": _normalizer(normalized_status),
        "ocr_provider": object(),
    }

    ordinary = parse_statement(source, strict=False, **dependencies)
    strict = parse_statement(source, strict=True, **dependencies)

    assert ordinary == strict
    assert ordinary.status is normalized_status
    assert ordinary.discovery is not None
    assert ordinary.discovery.classification == DocumentClassification.STATEMENT.value
    assert ordinary.normalization_confidence == 1.0


def test_parse_statement_downgrades_inconsistent_reconciled_result(tmp_path: Path) -> None:
    source = tmp_path / "statement.pdf"
    source.write_bytes(b"statement")
    discovery = _discovery(DocumentClassification.STATEMENT)

    result = parse_statement(
        source,
        extractor=lambda path, ocr_provider: _evidence(path.read_bytes()),
        discoverer=lambda value: discovery,
        normalizer=_normalizer(Status.RECONCILED, diagnostics=("unresolved_row",)),
        ocr_provider=object(),
    )

    assert result.status is Status.UNRECONCILED
    assert "unresolved_row" in result.diagnostics


def _structured_discovery(classification: DocumentClassification) -> StatementDiscovery:
    header_glyph = Glyph(
        char="A",
        bbox=(0.0, 10.0, 5.0, 20.0),
        origin=(0.0, 18.0),
        font="Synthetic Header",
        size=10.0,
        source="digital",
        confidence=0.91,
    )
    header_word = Word(
        text="Amount",
        bbox=(0.0, 10.0, 40.0, 20.0),
        source="digital",
        confidence=0.92,
    )
    header_cell = Cell(
        page_number=1,
        bbox=(0.0, 10.0, 40.0, 20.0),
        text="Amount",
        glyphs=(header_glyph,),
        words=(header_word,),
        confidence=0.9,
        diagnostics=("header_diagnostic",),
    )
    candidate_glyph = Glyph(
        char="1",
        bbox=(0.0, 30.0, 5.0, 40.0),
        origin=(0.0, 38.0),
        font="Synthetic Row",
        size=9.0,
        source="digital",
        confidence=0.79,
    )
    candidate_word = Word(
        text="10.00",
        bbox=(0.0, 30.0, 40.0, 40.0),
        source="ocr",
        confidence=0.78,
    )
    row_cell = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 40.0, 40.0),
        text="10.00",
        glyphs=(candidate_glyph,),
        words=(candidate_word,),
        confidence=0.8,
        diagnostics=("candidate_cell_diagnostic",),
    )
    header = Row(
        page_number=1,
        bbox=header_cell.bbox,
        cells=(header_cell,),
        words=(header_word,),
        confidence=0.9,
        diagnostics=("header_row_diagnostic",),
    )
    row = Row(
        page_number=1,
        bbox=row_cell.bbox,
        cells=(row_cell,),
        words=(candidate_word,),
        confidence=0.8,
        diagnostics=("candidate_row_diagnostic",),
    )
    column = ColumnSpec(
        index=0,
        page_number=1,
        bbox=(0.0, 10.0, 40.0, 40.0),
        relative_x0=0.0,
        relative_x1=1.0,
        role=ColumnRole.AMOUNT,
        source_cells=(header_cell,),
        confidence=0.85,
        diagnostics=("column_diagnostic",),
    )
    schema = TableSchema(
        page_number=1,
        bbox=(0.0, 10.0, 40.0, 40.0),
        columns=(column,),
        header_cells=(header_cell,),
        sample_cells=(row_cell,),
        confidence=0.85,
        diagnostics=("schema_diagnostic",),
    )
    region = TableRegion(
        page_number=1,
        bbox=(0.0, 10.0, 40.0, 40.0),
        header=header,
        rows=(row,),
        table_schema=schema,
        confidence=0.8,
        diagnostics=("region_diagnostic",),
    )
    issuer_evidence = EvidenceReference(
        page_number=1,
        bbox=(50.0, 5.0, 90.0, 15.0),
        raw_text="Synthetic Issuer",
    )
    total_label = EvidenceReference(
        page_number=1,
        bbox=(0.0, 50.0, 40.0, 60.0),
        raw_text="Total",
    )
    total_value = EvidenceReference(
        page_number=1,
        bbox=(50.0, 50.0, 90.0, 60.0),
        raw_text="10.00",
    )
    printed_total = DiscoveredPrintedTotal(
        amount_text="10.00",
        currency="ILS",
        label_evidence=total_label,
        value_evidence=total_value,
        confidence=0.9,
        diagnostics=("total_diagnostic",),
    )
    groups = (
        (
            StatementGroupDiscovery(
                group_id="group-0001",
                table_regions=(region,),
                printed_total=printed_total,
                confidence=0.85,
                diagnostics=("group_diagnostic",),
            ),
        )
        if classification is DocumentClassification.STATEMENT
        else ()
    )
    return StatementDiscovery(
        classification=classification,
        groups=groups,
        table_regions=(region,),
        issuer=DiscoveredField(
            field_name="issuer",
            value="Synthetic Issuer",
            evidence=issuer_evidence,
            confidence=0.95,
            diagnostics=("metadata_diagnostic",),
        ),
        date_year_context=DiscoveredDateYearContext(
            year=2026,
            style=DateTokenStyle.DAY_FIRST_SLASH,
            evidence=(
                EvidenceReference(
                    page_number=1,
                    bbox=(0.0, 70.0, 90.0, 80.0),
                    raw_text="Statement date 15/01/2026",
                ),
            ),
            confidence=0.9,
        ),
        rejected_total_candidates=(
            RejectedTotalCandidate(
                evidence=(
                    EvidenceReference(
                        page_number=1,
                        bbox=(0.0, 90.0, 90.0, 100.0),
                        raw_text="Subtotal candidate",
                    ),
                ),
                confidence=0.7,
                diagnostics=("ambiguous_total_value",),
            ),
        ),
        confidence=0.8,
        reason_codes=("structured_reason",),
        diagnostics=("discovery_diagnostic",),
    )


@pytest.mark.parametrize(
    ("classification", "expected_status"),
    (
        (DocumentClassification.AMBIGUOUS, Status.UNSUPPORTED),
        (DocumentClassification.NOT_STATEMENT, Status.NOT_STATEMENT),
    ),
)
def test_parse_statement_preserves_structured_discovery_for_nonparsed_results(
    tmp_path: Path,
    classification: DocumentClassification,
    expected_status: Status,
) -> None:
    source = tmp_path / "document.pdf"
    source.write_bytes(b"synthetic")

    result = parse_statement(
        source,
        extractor=lambda path, provider: _evidence(path.read_bytes()),
        discoverer=lambda evidence: _structured_discovery(classification),
        ocr_provider=object(),
    )

    assert result.status is expected_status
    assert result.discovery is not None
    assert result.discovery.classification == classification.value
    assert result.discovery.metadata[0].value == "Synthetic Issuer"
    assert result.discovery.metadata[0].evidence.raw_text == "Synthetic Issuer"
    assert result.discovery.date_year_context is not None
    assert result.discovery.date_year_context.year == 2026
    assert result.discovery.date_year_context.year_by_suffix == ((26, 2026),)
    assert result.discovery.date_year_context.style == "day_first_slash"
    assert result.discovery.date_year_context.evidence[0].raw_text == ("Statement date 15/01/2026")
    assert len(result.discovery.rejected_total_candidates) == 1
    assert result.discovery.rejected_total_candidates[0].evidence[0].raw_text == (
        "Subtotal candidate"
    )
    table = result.discovery.table_regions[0]
    assert table.header_evidence[0].raw_text == "Amount"
    assert table.column_roles == ("amount",)
    assert table.header.diagnostics == ("header_row_diagnostic",)
    assert table.rows[0].bbox == (0.0, 30.0, 40.0, 40.0)
    assert table.rows[0].cells[0].text == "10.00"
    assert table.rows[0].cells[0].diagnostics == ("candidate_cell_diagnostic",)
    assert table.rows[0].words[0].source == "ocr"
    assert table.rows[0].cells[0].glyphs[0].font == "Synthetic Row"
    assert table.table_schema.diagnostics == ("schema_diagnostic",)
    assert table.table_schema.columns[0].diagnostics == ("column_diagnostic",)
    assert table.table_schema.columns[0].source_cells[0].words[0].text == "Amount"
    assert table.table_schema.header_cells[0].glyphs[0].char == "A"
    assert table.table_schema.sample_cells[0].words[0].source == "ocr"
    assert table.diagnostics == ("region_diagnostic",)
    assert result.discovery.reason_codes == ("structured_reason",)

    payload = json.loads(canonical_json_bytes(result))
    serialized_table = payload["discovery"]["table_regions"][0]
    assert serialized_table["rows"][0]["cells"][0]["text"] == "10.00"
    assert serialized_table["rows"][0]["cells"][0]["bbox"] == [0.0, 30.0, 40.0, 40.0]
    assert serialized_table["rows"][0]["cells"][0]["diagnostics"] == ["candidate_cell_diagnostic"]
    serialized_schema = serialized_table["table_schema"]
    assert serialized_schema["diagnostics"] == ["schema_diagnostic"]
    assert serialized_schema["columns"][0]["diagnostics"] == ["column_diagnostic"]
    assert serialized_schema["columns"][0]["source_cells"][0]["glyphs"][0]["font"] == (
        "Synthetic Header"
    )
    assert serialized_schema["header_cells"][0]["words"][0]["source"] == "digital"
    assert serialized_schema["sample_cells"][0]["words"][0]["source"] == "ocr"


def test_parse_statement_serializes_rollover_year_context_mapping(tmp_path: Path) -> None:
    source = tmp_path / "document.pdf"
    source.write_bytes(b"synthetic")
    discovery = _structured_discovery(DocumentClassification.AMBIGUOUS).model_copy(
        update={
            "date_year_context": DiscoveredDateYearContext(
                year=None,
                year_by_suffix=((25, 2025), (26, 2026)),
                style=DateTokenStyle.DAY_FIRST_SLASH,
                evidence=(
                    EvidenceReference(
                        page_number=1,
                        bbox=(0.0, 70.0, 90.0, 80.0),
                        raw_text="Cycle start 31/12/2025",
                    ),
                    EvidenceReference(
                        page_number=1,
                        bbox=(0.0, 80.0, 90.0, 90.0),
                        raw_text="Cycle end 01/01/2026",
                    ),
                ),
                confidence=0.9,
            )
        }
    )

    result = parse_statement(
        source,
        extractor=lambda path, provider: _evidence(path.read_bytes()),
        discoverer=lambda evidence: discovery,
        ocr_provider=object(),
    )

    assert result.discovery is not None
    assert result.discovery.date_year_context is not None
    assert result.discovery.date_year_context.year is None
    assert result.discovery.date_year_context.year_by_suffix == ((25, 2025), (26, 2026))
    assert tuple(evidence.raw_text for evidence in result.discovery.date_year_context.evidence) == (
        "Cycle start 31/12/2025",
        "Cycle end 01/01/2026",
    )


@pytest.mark.parametrize(
    ("classification", "expected_status"),
    (
        (DocumentClassification.STATEMENT, Status.RECONCILED),
        (DocumentClassification.AMBIGUOUS, Status.UNSUPPORTED),
        (DocumentClassification.NOT_STATEMENT, Status.NOT_STATEMENT),
    ),
)
def test_parse_statement_preserves_complete_result_and_canonical_json(
    tmp_path: Path,
    classification: DocumentClassification,
    expected_status: Status,
) -> None:
    source = tmp_path / "complete-summary.pdf"
    source.write_bytes(b"complete synthetic summary")
    evidence = _evidence(source.read_bytes())
    discovery = _structured_discovery(classification)
    normalization = _normalizer(Status.RECONCILED)(discovery)
    discovery_diagnostics = tuple(dict.fromkeys((*discovery.reason_codes, *discovery.diagnostics)))
    expected = StatementResult(
        status=expected_status,
        transactions=(
            normalization.transactions if classification is DocumentClassification.STATEMENT else ()
        ),
        groups=(
            normalization.reconciliation.groups
            if classification is DocumentClassification.STATEMENT
            else ()
        ),
        diagnostics=discovery_diagnostics,
        source_name=source.name,
        source_sha256=evidence.source_sha256,
        statement_id=evidence.source_sha256,
        discovery=discovery_summary(discovery),
        row_results=(
            row_summaries(normalization)
            if classification is DocumentClassification.STATEMENT
            else ()
        ),
        normalization_confidence=(
            normalization.confidence if classification is DocumentClassification.STATEMENT else None
        ),
        normalization_diagnostics=(
            normalization.diagnostics if classification is DocumentClassification.STATEMENT else ()
        ),
    )

    result = parse_statement(
        source,
        extractor=lambda path, provider: evidence,
        discoverer=lambda value: discovery,
        normalizer=lambda value: normalization,
        ocr_provider=object(),
    )

    assert result == expected
    assert result.model_dump_json().encode("utf-8") == expected.model_dump_json().encode("utf-8")
    assert canonical_json_bytes(result) == canonical_json_bytes(expected)


def test_parse_statement_retries_bounded_numeric_ocr_and_uses_exact_rediscovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "statement.pdf"
    content = b"synthetic OCR statement"
    source.write_bytes(content)
    quality = ExtractionQuality(
        character_count=0,
        usable_character_count=0,
        word_count=0,
        replacement_character_ratio=0.0,
        control_character_ratio=0.0,
        image_area_ratio=1.0,
        requires_ocr=True,
        reasons=("image_dominant_without_words",),
    )
    evidence = DocumentEvidence(
        source_sha256=hashlib.sha256(content).hexdigest(),
        pages=(PageEvidence(page_number=1, width=100.0, height=100.0, quality=quality),),
    )
    repaired_evidence = evidence.model_copy(update={"metadata": (("repair", "complete"),)})
    initial_discovery = _structured_discovery(DocumentClassification.STATEMENT).model_copy(
        update={"reason_codes": ("initial_discovery",)}
    )
    repaired_discovery = initial_discovery.model_copy(
        update={"reason_codes": ("repaired_discovery",)}
    )
    discovery_inputs: list[DocumentEvidence] = []
    repair_calls: list[tuple[tuple[str, ...], tuple[Decimal, ...]]] = []

    def discover(value: DocumentEvidence) -> StatementDiscovery:
        discovery_inputs.append(value)
        return repaired_discovery if value is repaired_evidence else initial_discovery

    def normalize(value: StatementDiscovery) -> StatementNormalization:
        return _normalizer(
            Status.RECONCILED if value is repaired_discovery else Status.UNRECONCILED
        )(value)

    def repair(
        value: DocumentEvidence,
        pdf_bytes: bytes,
        provider: object,
        *,
        currency_hints: tuple[str, ...],
        expected_totals: tuple[Decimal, ...],
    ) -> DocumentEvidence:
        assert value is evidence
        assert pdf_bytes == content
        assert provider is not None
        repair_calls.append((currency_hints, expected_totals))
        return repaired_evidence

    monkeypatch.setattr(parser_module, "repair_table_numeric_ocr", repair)

    result = parse_statement(
        source,
        extractor=lambda path, provider: evidence,
        discoverer=discover,
        normalizer=normalize,
        ocr_provider=object(),
    )

    assert discovery_inputs == [evidence, repaired_evidence]
    assert repair_calls == [(("ILS",), (Decimal("10.00"),))]
    assert result.status is Status.RECONCILED
    assert result.discovery is not None
    assert result.discovery.reason_codes == ("repaired_discovery",)


@pytest.mark.parametrize(
    ("requires_ocr", "initial_status"),
    ((False, Status.UNRECONCILED), (True, Status.RECONCILED)),
)
def test_parse_statement_skips_numeric_ocr_retry_without_both_need_and_ocr_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    requires_ocr: bool,
    initial_status: Status,
) -> None:
    source = tmp_path / "statement.pdf"
    content = b"synthetic statement"
    source.write_bytes(content)
    quality = ExtractionQuality(
        character_count=0 if requires_ocr else 100,
        usable_character_count=0 if requires_ocr else 100,
        word_count=0 if requires_ocr else 10,
        replacement_character_ratio=0.0,
        control_character_ratio=0.0,
        image_area_ratio=1.0 if requires_ocr else 0.0,
        requires_ocr=requires_ocr,
        reasons=("image_dominant_without_words",) if requires_ocr else (),
    )
    evidence = DocumentEvidence(
        source_sha256=hashlib.sha256(content).hexdigest(),
        pages=(PageEvidence(page_number=1, width=100.0, height=100.0, quality=quality),),
    )

    def unexpected_repair(*args: object, **kwargs: object) -> DocumentEvidence:
        raise AssertionError("numeric OCR repair must not run")

    monkeypatch.setattr(parser_module, "repair_table_numeric_ocr", unexpected_repair)

    result = parse_statement(
        source,
        extractor=lambda path, provider: evidence,
        discoverer=lambda value: _structured_discovery(DocumentClassification.STATEMENT),
        normalizer=_normalizer(initial_status),
        ocr_provider=object(),
    )

    assert result.status is initial_status


def _two_group_discovery(classification: DocumentClassification) -> StatementDiscovery:
    base = _structured_discovery(DocumentClassification.STATEMENT)
    first_region = base.table_regions[0]
    second_cell = (
        first_region.rows[0]
        .cells[0]
        .model_copy(
            update={
                "bbox": (50.0, 30.0, 90.0, 40.0),
                "text": "20.00",
                "diagnostics": ("second_candidate_cell",),
            }
        )
    )
    second_row = first_region.rows[0].model_copy(
        update={
            "bbox": second_cell.bbox,
            "cells": (second_cell,),
            "diagnostics": ("second_candidate_row",),
        }
    )
    second_schema = first_region.table_schema.model_copy(
        update={
            "bbox": (50.0, 10.0, 90.0, 40.0),
            "sample_cells": (second_cell,),
            "diagnostics": ("second_schema",),
        }
    )
    second_region = first_region.model_copy(
        update={
            "bbox": (50.0, 10.0, 90.0, 40.0),
            "rows": (second_row,),
            "table_schema": second_schema,
            "diagnostics": ("second_region",),
        }
    )
    first_total = base.groups[0].printed_total.model_copy(update={"diagnostics": ("first_total",)})
    second_total = first_total.model_copy(
        update={
            "amount_text": "20.00",
            "value_evidence": first_total.value_evidence.model_copy(update={"raw_text": "20.00"}),
            "diagnostics": ("second_total",),
        }
    )
    groups = (
        StatementGroupDiscovery(
            group_id="group-first",
            table_regions=(first_region,),
            printed_total=first_total,
            confidence=0.71,
            diagnostics=("first_group",),
        ),
        StatementGroupDiscovery(
            group_id="group-second",
            table_regions=(second_region,),
            printed_total=second_total,
            confidence=0.62,
            diagnostics=("second_group",),
        ),
    )
    return base.model_copy(
        update={
            "classification": classification,
            "groups": groups,
            "table_regions": (first_region, second_region),
        }
    )


@pytest.mark.parametrize(
    ("classification", "expected_status"),
    (
        (DocumentClassification.STATEMENT, Status.UNRECONCILED),
        (DocumentClassification.AMBIGUOUS, Status.UNSUPPORTED),
        (DocumentClassification.NOT_STATEMENT, Status.NOT_STATEMENT),
    ),
)
def test_parse_statement_preserves_group_structure_and_table_association(
    tmp_path: Path,
    classification: DocumentClassification,
    expected_status: Status,
) -> None:
    source = tmp_path / "two-groups.pdf"
    source.write_bytes(b"two synthetic groups")
    discovery = _two_group_discovery(classification)

    result = parse_statement(
        source,
        extractor=lambda path, provider: _evidence(path.read_bytes()),
        discoverer=lambda evidence: discovery,
        normalizer=_normalizer(Status.UNRECONCILED),
        ocr_provider=object(),
    )

    assert result.status is expected_status
    assert result.discovery is not None
    first, second = result.discovery.groups
    assert first.group_id == "group-first"
    assert first.table_regions[0].rows[0].cells[0].text == "10.00"
    assert first.confidence == 0.71
    assert first.diagnostics == ("first_group",)
    assert first.printed_total.diagnostics == ("first_total",)
    assert second.group_id == "group-second"
    assert second.table_regions[0].rows[0].cells[0].text == "20.00"
    assert second.table_regions[0].bbox == (50.0, 10.0, 90.0, 40.0)
    assert second.confidence == 0.62
    assert second.diagnostics == ("second_group",)
    assert second.printed_total.diagnostics == ("second_total",)
    assert result.discovery.printed_totals[0].diagnostics == ("first_total",)
    assert result.discovery.printed_totals[1].diagnostics == ("second_total",)

    payload = json.loads(canonical_json_bytes(result))
    serialized_groups = payload["discovery"]["groups"]
    assert serialized_groups[0]["table_regions"][0]["rows"][0]["cells"][0]["text"] == ("10.00")
    assert serialized_groups[0]["confidence"] == 0.71
    assert serialized_groups[0]["diagnostics"] == ["first_group"]
    assert serialized_groups[0]["printed_total"]["diagnostics"] == ["first_total"]
    assert serialized_groups[1]["table_regions"][0]["rows"][0]["cells"][0]["text"] == ("20.00")
    assert serialized_groups[1]["diagnostics"] == ["second_group"]
    assert serialized_groups[1]["printed_total"]["diagnostics"] == ["second_total"]


def test_parse_statement_preserves_every_normalization_row_and_unfiltered_transactions(
    tmp_path: Path,
) -> None:
    source = tmp_path / "statement.pdf"
    source.write_bytes(b"synthetic")
    discovery = _structured_discovery(DocumentClassification.STATEMENT)
    transaction = Transaction(
        transaction_id="group-0001-p001-r0001",
        kind=TransactionKind.CHARGE,
        billed_amount=Decimal("10.00"),
        billing_currency="ILS",
        reconciliation_group_ids=("group-0001",),
    )
    accepted_evidence = EvidenceReference(
        page_number=1,
        bbox=(0.0, 30.0, 40.0, 40.0),
        raw_text="accepted raw row",
    )
    rejected_evidence = EvidenceReference(
        page_number=1,
        bbox=(0.0, 40.0, 40.0, 50.0),
        raw_text="rejected raw row",
    )
    row_results = (
        RowNormalizationResult(
            page_number=1,
            bbox=accepted_evidence.bbox,
            raw_text="accepted raw row",
            evidence=(accepted_evidence,),
            transaction=transaction,
            confidence=0.8,
        ),
        RowNormalizationResult(
            page_number=1,
            bbox=rejected_evidence.bbox,
            raw_text="rejected raw row",
            evidence=(rejected_evidence,),
            confidence=0.4,
            diagnostics=("unresolved_relevant_cell",),
        ),
        RowNormalizationResult(
            page_number=1,
            bbox=(0.0, 50.0, 40.0, 60.0),
            raw_text="merged raw row",
            evidence=(),
            confidence=0.7,
            diagnostics=("merged_description_continuation",),
        ),
    )
    group = ReconciliationGroup(
        group_id="group-0001",
        currency="ILS",
        printed_total=Decimal("10.00"),
        calculated_total=Decimal("0.00"),
        difference=Decimal("-10.00"),
        transaction_ids=(),
        status=Status.UNRECONCILED,
        diagnostics=("transaction_filtered",),
    )
    normalization = StatementNormalization(
        discovery=discovery,
        transactions=(transaction,),
        printed_totals=(),
        row_results=row_results,
        reconciliation=StatementResult(
            status=Status.UNRECONCILED,
            transactions=(),
            groups=(group,),
            diagnostics=("reconciliation_diagnostic",),
        ),
        confidence=0.65,
        diagnostics=("rows_not_emitted:1",),
    )

    result = parse_statement(
        source,
        extractor=lambda path, provider: _evidence(path.read_bytes()),
        discoverer=lambda evidence: discovery,
        normalizer=lambda value: normalization,
        ocr_provider=object(),
    )
    payload = result.model_dump(mode="json")

    assert result.status is Status.UNRECONCILED
    assert result.transactions == (transaction,)
    assert result.groups == (group,)
    assert tuple(row.raw_text for row in result.row_results) == (
        "accepted raw row",
        "rejected raw row",
        "merged raw row",
    )
    assert result.row_results[1].diagnostics == ("unresolved_relevant_cell",)
    assert result.normalization_confidence == 0.65
    assert result.normalization_diagnostics == ("rows_not_emitted:1",)
    assert result.discovery is not None
    assert result.discovery.printed_totals[0].label_evidence.raw_text == "Total"
    assert result.discovery.printed_totals[0].value_evidence.raw_text == "10.00"
    assert result.discovery.table_regions[0].rows[0].cells[0].text == "10.00"
    assert result.discovery.table_regions[0].table_schema.sample_cells[0].words[0].source == "ocr"
    assert payload["row_results"][1]["evidence"][0]["raw_text"] == "rejected raw row"


@pytest.mark.parametrize("missing_kind", ("missing", "directory"))
def test_parse_statement_rejects_missing_or_non_file_input(
    tmp_path: Path,
    missing_kind: str,
) -> None:
    source = tmp_path / "source"
    if missing_kind == "directory":
        source.mkdir()

    with pytest.raises(ParserInputError, match="input PDF"):
        parse_statement(source)


@pytest.mark.parametrize("error", (OcrError("private detail"), RuntimeError("private detail")))
def test_parse_statement_wraps_ocr_and_processing_failures_without_detail(
    tmp_path: Path,
    error: Exception,
) -> None:
    source = tmp_path / "statement.pdf"
    source.write_bytes(b"statement")

    def failing_extractor(path: Path, ocr_provider: object) -> DocumentEvidence:
        del path, ocr_provider
        raise error

    with pytest.raises(ParserRuntimeError) as caught:
        parse_statement(source, extractor=failing_extractor, ocr_provider=object())

    assert "private detail" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert "private detail" not in "".join(traceback.format_exception(caught.value))


class _RecordingOcr:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[int] = []
        self.error = error

    def extract_words(
        self,
        pdf_bytes: bytes,
        source_sha256: str,
        page_index: int,
        clip: BBox | None = None,
    ) -> tuple[Word, ...]:
        del pdf_bytes, source_sha256, clip
        self.calls.append(page_index)
        if self.error is not None:
            raise self.error
        return ()


def _write_digital_pdf(path: Path) -> None:
    with fitz.open() as document:
        page = document.new_page(width=200, height=100)
        page.insert_text((10, 50), "Synthetic digital statement text")
        document.save(path)


def _write_image_pdf(path: Path) -> None:
    one_pixel_png = b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    with fitz.open() as document:
        page = document.new_page(width=100, height=100)
        page.insert_image(page.rect, stream=one_pixel_png)
        document.save(path)


def test_parse_statement_real_digital_pdf_does_not_invoke_ocr(tmp_path: Path) -> None:
    source = tmp_path / "digital.pdf"
    _write_digital_pdf(source)
    provider = _RecordingOcr()

    result = parse_statement(
        source,
        ocr_provider=provider,
        discoverer=lambda evidence: _discovery(DocumentClassification.AMBIGUOUS),
    )

    assert result.status is Status.UNSUPPORTED
    assert provider.calls == []


def test_parse_statement_real_image_only_pdf_invokes_local_ocr(tmp_path: Path) -> None:
    source = tmp_path / "image.pdf"
    _write_image_pdf(source)
    provider = _RecordingOcr()

    result = parse_statement(
        source,
        ocr_provider=provider,
        discoverer=lambda evidence: _discovery(DocumentClassification.AMBIGUOUS),
    )

    assert result.status is Status.UNSUPPORTED
    assert provider.calls == [0]


def test_parse_statement_image_ocr_dependency_failure_is_typed(tmp_path: Path) -> None:
    source = tmp_path / "image.pdf"
    _write_image_pdf(source)
    provider = _RecordingOcr(OcrError("private OCR executable detail"))

    with pytest.raises(ParserRuntimeError) as caught:
        parse_statement(source, ocr_provider=provider)

    assert "private OCR executable detail" not in str(caught.value)


def test_parse_statement_corrupt_pdf_failure_is_typed_and_redacted(tmp_path: Path) -> None:
    source = tmp_path / "corrupt.pdf"
    source.write_bytes(b"private corrupt PDF detail")

    with pytest.raises(ParserRuntimeError) as caught:
        parse_statement(source, ocr_provider=_RecordingOcr())

    assert "private corrupt PDF detail" not in str(caught.value)


def _directory_parser(calls: list[str]) -> Callable[..., StatementResult]:
    def parse(
        path: Path, strict: bool = False, *, cache_dir: str | Path | None = None
    ) -> StatementResult:
        del strict, cache_dir
        calls.append(path.name)
        if path.name.startswith("slow"):
            time.sleep(0.02)
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        return StatementResult(
            status=Status.RECONCILED,
            transactions=(),
            groups=(),
            source_name=path.name,
            source_sha256=digest,
            statement_id=digest,
        )

    return parse


def test_parse_directory_recurses_regular_pdfs_skips_trees_and_orders_posix_paths(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = input_dir / "generated"
    cache_dir = input_dir / "cache"
    for relative in ("z.pdf", "a.PDF", "nested/slow-b.pdf", "notes.txt"):
        source = input_dir / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(relative.encode())
    output_dir.mkdir(parents=True)
    (output_dir / "ignored.pdf").write_bytes(b"ignored")
    cache_dir.mkdir()
    (cache_dir / "ignored.pdf").write_bytes(b"ignored")
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"outside")
    (input_dir / "linked.pdf").symlink_to(outside)
    calls: list[str] = []

    result = parse_directory(
        input_dir,
        output_dir,
        jobs=3,
        cache_dir=cache_dir,
        statement_parser=_directory_parser(calls),
    )

    assert isinstance(result, BatchResult)
    assert result.status is Status.RECONCILED
    assert tuple(statement.source_name for statement in result.statements) == (
        "a.PDF",
        "nested/slow-b.pdf",
        "z.pdf",
    )
    assert sorted(calls) == ["a.PDF", "slow-b.pdf", "z.pdf"]
    assert (output_dir / "results.json").is_file()
    assert (output_dir / "transactions.csv").is_file()


def test_parse_directory_jobs_are_bounded_and_byte_identical_to_sequential(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input"
    for name in ("slow-c.pdf", "a.pdf", "b.pdf"):
        input_dir.mkdir(exist_ok=True)
        (input_dir / name).write_bytes(name.encode())
    sequential_output = tmp_path / "sequential"
    concurrent_output = tmp_path / "concurrent"

    sequential = parse_directory(
        input_dir,
        sequential_output,
        jobs=1,
        statement_parser=_directory_parser([]),
    )
    concurrent = parse_directory(
        input_dir,
        concurrent_output,
        jobs=10_000,
        statement_parser=_directory_parser([]),
    )

    assert sequential == concurrent
    assert (sequential_output / "results.json").read_bytes() == (
        concurrent_output / "results.json"
    ).read_bytes()
    assert (sequential_output / "transactions.csv").read_bytes() == (
        concurrent_output / "transactions.csv"
    ).read_bytes()


def test_parse_directory_empty_is_explicit_unsupported_and_serialized(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    output_dir = tmp_path / "output"

    result = parse_directory(input_dir, output_dir, statement_parser=_directory_parser([]))

    assert result.status is Status.UNSUPPORTED
    assert result.statements == ()
    assert result.diagnostics == ("no_pdf_files",)
    assert b"no_pdf_files" in (output_dir / "results.json").read_bytes()
    assert b"no_pdf_files" in (output_dir / "transactions.csv").read_bytes()


@pytest.mark.parametrize("jobs", (0, -1, 1.5, True))
def test_parse_directory_validates_positive_integer_jobs(tmp_path: Path, jobs: object) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    with pytest.raises(ParserInputError, match="jobs"):
        parse_directory(input_dir, tmp_path / "output", jobs=jobs)  # type: ignore[arg-type]


def test_parse_directory_does_not_write_outputs_when_one_input_fails(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.pdf").write_bytes(b"valid")
    (input_dir / "b.pdf").write_bytes(b"failure")
    output_dir = tmp_path / "output"

    def parser(
        path: Path,
        strict: bool = False,
        *,
        cache_dir: str | Path | None = None,
    ) -> StatementResult:
        del strict, cache_dir
        if path.name == "b.pdf":
            raise ParserRuntimeError("generic processing failure")
        return StatementResult(status=Status.RECONCILED, transactions=(), groups=())

    with pytest.raises(ParserRuntimeError) as caught:
        parse_directory(input_dir, output_dir, jobs=2, statement_parser=parser)

    assert caught.value.__cause__ is None
    assert "generic processing failure" not in "".join(traceback.format_exception(caught.value))
    assert not (output_dir / "results.json").exists()
    assert not (output_dir / "transactions.csv").exists()


def test_parse_directory_walk_error_is_typed_input_failure_without_empty_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    output_dir = tmp_path / "output"

    def failing_walk(
        top: Path,
        *,
        followlinks: bool,
        onerror: Callable[[OSError], object] | None = None,
    ) -> tuple[object, ...]:
        del top, followlinks
        assert onerror is not None
        onerror(PermissionError("private unreadable directory detail"))
        return ()

    monkeypatch.setattr(parser_module.os, "walk", failing_walk)

    with pytest.raises(ParserInputError, match="cannot be inspected") as caught:
        parse_directory(input_dir, output_dir)

    assert caught.value.__cause__ is None
    assert not output_dir.exists()


@pytest.mark.parametrize("error_type", (OSError, RuntimeError))
def test_parse_directory_path_inspection_error_is_typed_and_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    original_exists = Path.exists

    def failing_exists(path: Path) -> bool:
        if path == input_dir:
            raise error_type("private path inspection detail")
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", failing_exists)

    with pytest.raises(ParserInputError, match="cannot be inspected") as caught:
        parse_directory(input_dir, tmp_path / "output")

    rendered = "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None
    assert "private path inspection" not in rendered


def test_parse_directory_default_cache_runtime_error_is_typed_and_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    def failing_default_cache() -> Path:
        raise RuntimeError("private home lookup detail")

    monkeypatch.setattr(parser_module, "default_cache_directory", failing_default_cache)

    with pytest.raises(ParserRuntimeError, match="cache directory") as caught:
        parse_directory(input_dir, tmp_path / "output")

    rendered = "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None
    assert "private home lookup detail" not in rendered


@pytest.mark.parametrize(
    ("output_location", "cache_location"),
    (
        ("input", "cache-disjoint"),
        ("parent", "cache-disjoint"),
        ("output-disjoint", "input"),
        ("output-disjoint", "parent"),
        ("shared", "shared"),
        ("shared", "shared/nested"),
        ("shared/nested", "shared"),
    ),
)
def test_parse_directory_rejects_unsafe_input_output_cache_topology(
    tmp_path: Path,
    output_location: str,
    cache_location: str,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "statement.pdf").write_bytes(b"synthetic")
    output_dir = (
        input_dir
        if output_location == "input"
        else tmp_path
        if output_location == "parent"
        else tmp_path / output_location
    )
    cache_dir = (
        input_dir
        if cache_location == "input"
        else tmp_path
        if cache_location == "parent"
        else tmp_path / cache_location
    )

    with pytest.raises(ParserInputError, match="topology") as caught:
        parse_directory(
            input_dir,
            output_dir,
            cache_dir=cache_dir,
            statement_parser=_directory_parser([]),
        )

    assert caught.value.__cause__ is None


@pytest.mark.parametrize("placement", ("nested", "disjoint"))
def test_parse_directory_allows_and_prunes_only_safe_output_cache_trees(
    tmp_path: Path,
    placement: str,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "statement.pdf").write_bytes(b"statement")
    if placement == "nested":
        output_dir = input_dir / "output"
        cache_dir = input_dir / "cache"
    else:
        output_dir = tmp_path / "output"
        cache_dir = tmp_path / "cache"
    output_dir.mkdir(parents=True)
    cache_dir.mkdir(parents=True)
    (output_dir / "ignored.pdf").write_bytes(b"ignored output")
    (cache_dir / "ignored.pdf").write_bytes(b"ignored cache")
    calls: list[str] = []

    result = parse_directory(
        input_dir,
        output_dir,
        cache_dir=cache_dir,
        statement_parser=_directory_parser(calls),
    )

    assert result.status is Status.RECONCILED
    assert calls == ["statement.pdf"]


def test_parse_directory_publishes_with_one_pair_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "statement.pdf").write_bytes(b"statement")
    output_dir = tmp_path / "output"
    published: list[tuple[Path, BatchResult]] = []
    monkeypatch.setattr(
        parser_module,
        "write_batch_outputs",
        lambda path, batch: published.append((Path(path), batch)),
    )

    result = parse_directory(
        input_dir,
        output_dir,
        statement_parser=_directory_parser([]),
    )

    assert published == [(output_dir, result)]


@pytest.mark.parametrize("failure_stage", ("creation", "execution"))
def test_parse_directory_wraps_executor_failures_without_private_causes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.pdf").write_bytes(b"a")
    (input_dir / "b.pdf").write_bytes(b"b")

    class FailingExecutor:
        def __init__(self, max_workers: int) -> None:
            del max_workers
            if failure_stage == "creation":
                raise RuntimeError("private executor creation detail")

        def __enter__(self) -> FailingExecutor:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def map(self, function: object, values: object) -> tuple[object, ...]:
            del function, values
            raise RuntimeError("private executor execution detail")

    monkeypatch.setattr(parser_module, "ThreadPoolExecutor", FailingExecutor)

    with pytest.raises(ParserRuntimeError, match="directory statement processing failed") as caught:
        parse_directory(
            input_dir,
            tmp_path / "output",
            jobs=2,
            statement_parser=_directory_parser([]),
        )

    rendered = "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None
    assert "private executor" not in rendered


@pytest.mark.parametrize(
    "failure",
    (
        OSError("private output OSError"),
        ValueError("private output ValueError"),
        TypeError("private output TypeError"),
        UnicodeError("private output UnicodeError"),
        RuntimeError("private output RuntimeError"),
    ),
)
def test_parse_directory_wraps_all_output_failures_without_private_causes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    monkeypatch.setattr(
        parser_module,
        "write_batch_outputs",
        lambda output, batch: (_ for _ in ()).throw(failure),
    )

    with pytest.raises(ParserRuntimeError, match="output writing failed") as caught:
        parse_directory(input_dir, tmp_path / "output")

    rendered = "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None
    assert "private output" not in rendered
