from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256

from pydantic import BaseModel

from ccparser.date_tokens import DateTokenStyle
from ccparser.discovery import (
    DiscoveredDateYearContext,
    DiscoveredField,
    DiscoveredPrintedTotal,
    DocumentClassification,
    RejectedTotalCandidate,
    StatementDiscovery,
    StatementGroupDiscovery,
)
from ccparser.evidence import ExtractionQuality, Glyph, PageEvidence, Word
from ccparser.layout import Cell, ColumnRole, ColumnSpec, Row, TableRegion, TableSchema
from ccparser.models import (
    DiscoveryCellSummary,
    DiscoveryColumnSummary,
    DiscoveryGlyphSummary,
    DiscoveryRowSummary,
    DiscoveryTableSchemaSummary,
    DiscoveryWordSummary,
    EvidenceReference,
    PrintedTotal,
    PrintedTotalSummary,
    ReconciliationGroup,
    RowNormalizationSummary,
    StatementDiscoverySummary,
    StatementGroupDiscoverySummary,
    Status,
    TableRegionSummary,
    Transaction,
    TransactionKind,
)
from ccparser.normalize import RowNormalizationResult, StatementNormalization
from ccparser.output import canonical_json_bytes
from ccparser.reconcile import ReconciliationOutcome
from ccparser.summary import (
    cell_summary,
    column_summary,
    discovery_summary,
    glyph_summary,
    group_summary,
    printed_total_summary,
    row_summaries,
    row_summary,
    table_region_summary,
    table_schema_summary,
    word_summary,
)


@dataclass(frozen=True, slots=True)
class _SummaryGraph:
    page: PageEvidence
    cell: Cell
    row: Row
    column: ColumnSpec
    schema: TableSchema
    claimed_region: TableRegion
    unclaimed_region: TableRegion
    group: StatementGroupDiscovery
    discovery: StatementDiscovery
    normalization: StatementNormalization


def _summary_graph() -> _SummaryGraph:
    header_glyph = Glyph(
        char="A",
        bbox=(0.0, 10.0, 4.0, 20.0),
        origin=(0.0, 18.0),
        font="Summary Header",
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
        bbox=header_word.bbox,
        text=header_word.text,
        glyphs=(header_glyph,),
        words=(header_word,),
        confidence=0.9,
        diagnostics=("header_cell",),
    )
    value_glyph = Glyph(
        char="1",
        bbox=(0.0, 30.0, 4.0, 40.0),
        origin=(0.0, 38.0),
        font="Summary Value",
        size=9.0,
        source="digital",
        confidence=0.81,
    )
    value_word = Word(
        text="10.00",
        bbox=(0.0, 30.0, 40.0, 40.0),
        source="ocr",
        confidence=0.82,
    )
    cell = Cell(
        page_number=1,
        bbox=value_word.bbox,
        text=value_word.text,
        glyphs=(value_glyph,),
        words=(value_word,),
        confidence=0.8,
        diagnostics=("value_cell",),
    )
    header = Row(
        page_number=1,
        bbox=header_cell.bbox,
        cells=(header_cell,),
        glyphs=(header_glyph,),
        words=(header_word,),
        confidence=0.9,
        diagnostics=("header_row",),
    )
    row = Row(
        page_number=1,
        bbox=cell.bbox,
        cells=(cell,),
        glyphs=(value_glyph,),
        words=(value_word,),
        confidence=0.8,
        diagnostics=("value_row",),
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
        diagnostics=("amount_column",),
    )
    schema = TableSchema(
        page_number=1,
        bbox=(0.0, 10.0, 40.0, 40.0),
        columns=(column,),
        header_cells=(header_cell,),
        sample_cells=(cell,),
        confidence=0.84,
        diagnostics=("claimed_schema",),
    )
    claimed_region = TableRegion(
        page_number=1,
        bbox=schema.bbox,
        header=header,
        rows=(row,),
        table_schema=schema,
        confidence=0.83,
        diagnostics=("claimed_region",),
    )
    unclaimed_region = claimed_region.model_copy(
        update={
            "bbox": (50.0, 10.0, 90.0, 40.0),
            "confidence": 0.61,
            "diagnostics": ("unclaimed_region",),
        }
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
        confidence=0.88,
        diagnostics=("printed_total",),
    )
    group = StatementGroupDiscovery(
        group_id="group-0001",
        table_regions=(claimed_region,),
        printed_total=printed_total,
        confidence=0.86,
        diagnostics=("claimed_group",),
    )
    discovery = StatementDiscovery(
        classification=DocumentClassification.STATEMENT,
        groups=(group,),
        table_regions=(claimed_region, unclaimed_region),
        issuer=DiscoveredField(
            field_name="issuer",
            value="Summary Bank",
            evidence=EvidenceReference(
                page_number=1,
                bbox=(0.0, 0.0, 90.0, 8.0),
                raw_text="Summary Bank",
            ),
            confidence=0.95,
            diagnostics=("issuer_metadata",),
        ),
        date_year_context=DiscoveredDateYearContext(
            year=None,
            year_by_suffix=((25, 2025), (26, 2026)),
            style=DateTokenStyle.DAY_FIRST_SLASH,
            evidence=(
                EvidenceReference(
                    page_number=1,
                    bbox=(0.0, 65.0, 90.0, 75.0),
                    raw_text="Cycle 31/12/2025 to 01/01/2026",
                ),
            ),
            metadata_evidence=(("statement_date", "01/01/2026"),),
            confidence=0.89,
            diagnostics=("rollover_context",),
        ),
        rejected_total_candidates=(
            RejectedTotalCandidate(
                evidence=(
                    EvidenceReference(
                        page_number=1,
                        bbox=(0.0, 80.0, 90.0, 90.0),
                        raw_text="Subtotal 8.00",
                    ),
                ),
                confidence=0.54,
                diagnostics=("ambiguous_total_value",),
            ),
        ),
        confidence=0.79,
        reason_codes=("statement_structure",),
        diagnostics=("discovery_advisory",),
    )
    evidence_reference = EvidenceReference(
        page_number=1,
        bbox=row.bbox,
        raw_text="10.00",
    )
    transaction = Transaction(
        transaction_id="group-0001-p001-r0001",
        kind=TransactionKind.CHARGE,
        billed_amount=Decimal("10.00"),
        billing_currency="ILS",
        reconciliation_group_ids=(group.group_id,),
        evidence=(evidence_reference,),
    )
    reconciliation_group = ReconciliationGroup(
        group_id=group.group_id,
        currency="ILS",
        printed_total=Decimal("10.00"),
        calculated_total=Decimal("10.00"),
        difference=Decimal("0.00"),
        transaction_ids=(transaction.transaction_id,),
        status=Status.RECONCILED,
    )
    normalization = StatementNormalization(
        discovery=discovery,
        transactions=(transaction,),
        printed_totals=(
            PrintedTotal(
                group_id=group.group_id,
                amount=Decimal("10.00"),
                currency="ILS",
            ),
        ),
        row_results=(
            RowNormalizationResult(
                page_number=1,
                bbox=row.bbox,
                raw_text="10.00",
                evidence=(evidence_reference,),
                transaction=transaction,
                confidence=0.8,
                diagnostics=("normalized_row",),
            ),
        ),
        reconciliation=ReconciliationOutcome(
            status=Status.RECONCILED,
            accepted_transaction_ids=(transaction.transaction_id,),
            accepted_transaction_indices=(0,),
            rejected_transactions=(),
            groups=(reconciliation_group,),
            diagnostics=(),
        ),
        confidence=0.87,
        diagnostics=("normalization_advisory",),
    )
    page = PageEvidence(
        page_number=1,
        width=100.0,
        height=100.0,
        glyphs=(header_glyph, value_glyph),
        words=(header_word, value_word),
        quality=ExtractionQuality(
            character_count=2,
            usable_character_count=2,
            word_count=2,
            replacement_character_ratio=0.0,
            control_character_ratio=0.0,
            image_area_ratio=0.0,
            requires_ocr=False,
        ),
    )
    return _SummaryGraph(
        page=page,
        cell=cell,
        row=row,
        column=column,
        schema=schema,
        claimed_region=claimed_region,
        unclaimed_region=unclaimed_region,
        group=group,
        discovery=discovery,
        normalization=normalization,
    )


def _assert_legacy_adapter_snapshot(
    actual: BaseModel,
    expected_type: type[BaseModel],
    expected_model_json_sha256: str,
    expected_canonical_json_sha256: str,
) -> None:
    assert type(actual) is expected_type
    assert sha256(actual.model_dump_json().encode("utf-8")).hexdigest() == (
        expected_model_json_sha256
    )
    assert sha256(canonical_json_bytes(actual)).hexdigest() == expected_canonical_json_sha256


def test_typed_summary_converters_match_legacy_parser_adapter_snapshots() -> None:
    # Captured only after direct model and byte equality against every parser adapter.
    graph = _summary_graph()
    glyph = graph.page.glyphs[1]
    word = graph.page.words[1]

    _assert_legacy_adapter_snapshot(
        glyph_summary(glyph),
        DiscoveryGlyphSummary,
        "9f9e11fd20db85604e2281a79a71d8a3ed478f569f1ddb161914c382349fad16",
        "9587d54255a6ea9e91de1de7e878a7d4936a6557c83536fadbd02434a1d0e4a8",
    )
    _assert_legacy_adapter_snapshot(
        word_summary(word),
        DiscoveryWordSummary,
        "6c2fafa6d803cb927b9f9a0a491998276be471ebff3276efc574eb75d4987619",
        "799fe3dcb478a8128dd5fce54b9a4eaf492ca4e293c4bfb267cca6ed5783515d",
    )
    _assert_legacy_adapter_snapshot(
        cell_summary(graph.cell),
        DiscoveryCellSummary,
        "60ee69981bc34e60050e85d7e1d82720a8eec29c179d22918539b896fc8fa14a",
        "8152aa3bf84543259c47a081c49d94d765597a2bbe90c64cae8f537e12b43a90",
    )
    _assert_legacy_adapter_snapshot(
        row_summary(graph.row),
        DiscoveryRowSummary,
        "83cbaec7d5c3096ce8ab1c04023ef6828b8c43ba79d6f1e60b4051fc2a580530",
        "440700190cc128e24d5474d2a662234bb0ad3161a77faae189a232425984cea4",
    )
    _assert_legacy_adapter_snapshot(
        column_summary(graph.column),
        DiscoveryColumnSummary,
        "2b28a71e3b96d59bf3ddd352582ac8fc9d5959249222d6e26252355a0deb1024",
        "6eecedffbabc7004f6ec8552ec1f64a1291aaefb57dd9b9e047198d4e1baa316",
    )
    _assert_legacy_adapter_snapshot(
        table_schema_summary(graph.schema),
        DiscoveryTableSchemaSummary,
        "ff83ab56ab83726ce418b66ea3c873d67f745f96bed820fbd2ad598c9575c5c9",
        "642dc98e68232f371b792b27665da04d79d8f69996c09b5c77ac4a32e2abd5a9",
    )
    _assert_legacy_adapter_snapshot(
        table_region_summary(graph.claimed_region),
        TableRegionSummary,
        "a70e00e75afc8ccec45246298dade29b0ee90a74776f2f7eeccf5ab6530eea9e",
        "fa63d00a44e735962bfa1df252d7a6659b01a25b6e84b6052115820b0a597f35",
    )
    _assert_legacy_adapter_snapshot(
        printed_total_summary(graph.group),
        PrintedTotalSummary,
        "087475cbcfedf01d999e5a377fabbaf51b48b09c232445b4db25ab213db65d7c",
        "0dbf258dcedbe4709c5aa402dae444c599f29ad055ba4a3154266c30c8594918",
    )
    _assert_legacy_adapter_snapshot(
        group_summary(graph.group),
        StatementGroupDiscoverySummary,
        "42239f8fca35925d3efe77dbc979e5a7adc9b250d25ef5ae2718e922e95281b0",
        "90804596f783166ebe303474eb6dfd58f07241a3481e01522b12300f10528395",
    )
    _assert_legacy_adapter_snapshot(
        discovery_summary(graph.discovery),
        StatementDiscoverySummary,
        "63af15b0c99ee07012a3ac1e845dc9e8f4beeae002558ec4a581fb11b3458a28",
        "69484c2b8a8723ba9259391612ef15df1e932ef8cbee76066283c468d63cd821",
    )

    actual_rows = row_summaries(graph.normalization)
    assert len(actual_rows) == 1
    _assert_legacy_adapter_snapshot(
        actual_rows[0],
        RowNormalizationSummary,
        "0569c89278f8de927a4b329cfa26941e69c2c4cf080a2ba314ff3e90fc7402e0",
        "06ef0d86c90c14d1ee49ddd09120d23d240f6cf612e8428577d377540486adc2",
    )


def test_discovery_summary_keeps_unclaimed_regions_and_rollover_evidence() -> None:
    graph = _summary_graph()

    summary = discovery_summary(graph.discovery)

    assert summary.table_regions == (
        table_region_summary(graph.claimed_region),
        table_region_summary(graph.unclaimed_region),
    )
    assert summary.groups[0].table_regions == (table_region_summary(graph.claimed_region),)
    assert summary.table_regions[1].diagnostics == ("unclaimed_region",)
    assert summary.date_year_context is not None
    assert summary.date_year_context.year is None
    assert summary.date_year_context.year_by_suffix == ((25, 2025), (26, 2026))
    assert summary.date_year_context.metadata_evidence == (("statement_date", "01/01/2026"),)
    assert summary.rejected_total_candidates[0].diagnostics == ("ambiguous_total_value",)
    assert summary.printed_totals == (summary.groups[0].printed_total,)
