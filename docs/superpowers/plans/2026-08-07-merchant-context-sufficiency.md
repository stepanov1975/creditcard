# Merchant Context Sufficiency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure which of six nested spatial-context tiers yields the best safe
transaction-level merchant attribution on the fixed 100-row training sample.

**Architecture:** Add one experiment-local module containing private contracts, context
materialization, reference/assertion validation, transaction-level scoring, and aggregate report
rendering. Materialize opaque visual batches whose pixels and positioned text differ only in
spatial extent, freeze an independent source reference before six isolated arm runs, score exactly
once, publish aggregate results, and return the live program to `STOP`.

**Tech Stack:** Python 3.13, Pydantic 2 frozen models, PyMuPDF, canonical JSONL codecs, `Decimal`,
pytest, Ruff, and mypy; no new dependencies or CLI.

## Global Constraints

- Binding design: `docs/superpowers/specs/2026-08-07-merchant-context-sufficiency-design.md`.
- Binding authority: `AGENTS.md`, the amended experiment charter, and the live program status.
- Use `/root/creditcard/.venv`; follow red-green-refactor for every deterministic behavior.
- Reuse exactly the frozen 100 training pilot row identities. Never regenerate the sample.
- Do not read current gold, accepted parser output, Reviewer A/B values, experiment predictions,
  validation, or held-out data.
- All arms use identical fixed 300-DPI source pixels, corresponding frozen atom text/boxes,
  role-free column boundaries, model, prompt, decoding, and output contract. Only spatial extent
  changes.
- Use `Decimal` for every rate; never use binary floating point for measurements.
- Source images, atoms, references, assertions, error labels, merchant text, and financial data
  remain under `artifacts/merchant-context-sufficiency-v1/` and out of Git.
- Tracked reports contain aggregate counts/rates only. Exceptions and public logs must not include
  document IDs, row IDs, source paths, merchant strings, atom IDs, or financial values.
- Do not add a reusable controller, CLI, schema family, receipt chain, attestation, cache system,
  workflow subsystem, production integration, or second support task.
- Do not run the private corpus gate: this shared evaluation does not change production parsing.

Every implementation task and execution worker begins with this exact contract:

```text
Scope answer: YES — this changes or measures how spatial source context affects transaction-level merchant attribution.
Experiment: shared evaluation
Extraction hypothesis: A bounded transaction neighborhood plus visible table headers matches full-page merchant accuracy, while an isolated row crop does not.
Measurement: transaction-level merchant-attribution accuracy, exact merchant-bearing-text rate, omission rate, wrong-merchant count, hallucination count, ownership-error count, and paired accuracy delta by context tier
Fixed inputs: the frozen 100 training pilot row identities and source evidence only; all arms use the same reference cases, model, prompt, and decoding; validation, held-out data, current gold, accepted parser output, Reviewer A/B values, and experiment predictions remain closed
Smallest allowed files: CONTEXT.md; docs/superpowers/specs/2026-08-07-merchant-context-sufficiency-design.md; docs/superpowers/plans/2026-08-07-merchant-context-sufficiency.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; experiments/row_extraction/merchant_context.py; tests/experiments/row_extraction/test_merchant_context.py; docs/experiments/row-extraction-merchant-context-report.md; and artifacts/merchant-context-sufficiency-v1/** (ignored private artifacts only)
Required output: a supported or falsified context-sufficiency hypothesis and the smallest context tier attaining the best observed safe merchant accuracy
Stop condition: stop before arm execution if merchant-bearing evidence is not operationally referenceable, an independent reference cannot be frozen first, an arm would expose prohibited data, or any declared context is truncated; stop after the single scoring run
```

## File Map

- Modify `CONTEXT.md`: clarify that ancillary text cannot substitute for merchant identity.
- Create `experiments/row_extraction/merchant_context.py`: the only implementation module;
  private records, validation, context rendering, scoring, and aggregate Markdown rendering.
- Create `tests/experiments/row_extraction/test_merchant_context.py`: synthetic TDD coverage for
  every deterministic contract and privacy boundary.
- Modify `docs/superpowers/specs/2026-08-07-merchant-context-sufficiency-design.md`: retain the
  already-reviewed monotonic-superset clarification and plan-path authorization.
- Create `docs/experiments/row-extraction-merchant-context-report.md`: final aggregate result only,
  after the one frozen score.
- Modify `docs/experiments/row-extraction-program-status.md`: record the Metric-or-Stop result and
  return the program to `STOP` after scoring.
- Write only ignored private data below `artifacts/merchant-context-sufficiency-v1/`.

---

### Task 1: Freeze Merchant Reference and Assertion Contracts

**Files:**
- Create: `experiments/row_extraction/merchant_context.py`
- Create: `tests/experiments/row_extraction/test_merchant_context.py`

**Interfaces:**
- Consumes: `FrozenRow`, `EvidenceAtom`, `BBox`, `_FrozenModel`, and
  `select_visual_gold_pilot(rows)`.
- Produces: `ContextTier`, `ReferenceDisposition`, `AssertionDisposition`,
  `MerchantErrorCategory`, `MerchantReference`, `MerchantAssertion`,
  `MerchantReferenceSummary`, `canonical_merchant_text(text)`, and
  `validate_merchant_reference(population, selected_rows, references)`.

- [ ] **Step 1: Write failing model and normalization tests**

Add imports and synthetic helpers, then write tests with literal synthetic values:

```python
def test_canonical_merchant_text_changes_only_nfc_and_layout_whitespace() -> None:
    assert canonical_merchant_text("  Cafe\u0301\n  Store  ") == "Café Store"
    assert canonical_merchant_text("A-B, Ltd.") == "A-B, Ltd."


def test_transaction_reference_requires_one_owner_and_source_support() -> None:
    reference = MerchantReference(
        document_id="a" * 64,
        anchor_row_id="continuation",
        disposition=ReferenceDisposition.TRANSACTION,
        owner_row_id="primary",
        owned_row_ids=("primary", "continuation"),
        merchant_text="SYNTHETIC MERCHANT",
        atom_ids=("merchant-1",),
        source_regions=(),
        ambiguity_category=None,
    )
    assert reference.owner_row_id == "primary"

    with pytest.raises(ValidationError):
        MerchantReference.model_validate(
            {
                **reference.model_dump(),
                "owner_row_id": None,
                "atom_ids": (),
                "source_regions": (),
            }
        )


def test_nontransaction_and_ambiguous_references_cannot_carry_merchant_values() -> None:
    with pytest.raises(ValidationError):
        MerchantReference(
            document_id="a" * 64,
            anchor_row_id="row",
            disposition=ReferenceDisposition.NONTRANSACTION,
            owner_row_id=None,
            owned_row_ids=(),
            merchant_text="SECRET MERCHANT",
            atom_ids=(),
            source_regions=(),
            ambiguity_category=None,
        )


def test_assertion_contract_has_only_merchant_nontransaction_or_abstain() -> None:
    assertion = MerchantAssertion(
        context_id="b" * 64,
        document_id="a" * 64,
        anchor_row_id="row",
        disposition=AssertionDisposition.ABSTAIN,
        owner_row_id=None,
        merchant_text=None,
        atom_ids=(),
        source_regions=(),
    )
    assert assertion.model_dump(mode="json")["disposition"] == "abstain"
    with pytest.raises(ValidationError):
        MerchantAssertion.model_validate({**assertion.model_dump(), "prediction": "SECRET"})
```

Define the Task 1 fixture explicitly:

```python
def reference_fixture() -> tuple[
    tuple[FrozenRow, ...],
    tuple[FrozenRow, ...],
    tuple[MerchantReference, ...],
]:
    rows = tuple(
        frozen_row(
            document_id=f"{index:064x}",
            row_id=f"row-{index:03d}",
            atoms=(
                evidence_atom(
                    atom_id=f"merchant-{index:03d}",
                    text="SECRET MERCHANT",
                    bbox=(20.0, 20.0, 80.0, 30.0),
                ),
                evidence_atom(
                    atom_id=f"ancillary-{index:03d}",
                    text="ANCILLARY",
                    bbox=(90.0, 20.0, 130.0, 30.0),
                ),
            ),
        )
        for index in range(100)
    )
    references: list[MerchantReference] = []
    for index, row in enumerate(rows):
        if index == 98:
            references.append(
                MerchantReference(
                    document_id=row.document_id,
                    anchor_row_id=row.row_id,
                    disposition=ReferenceDisposition.AMBIGUOUS,
                    owner_row_id=None,
                    owned_row_ids=(),
                    merchant_text=None,
                    atom_ids=(),
                    source_regions=(),
                    ambiguity_category=MerchantErrorCategory.REFERENCE_AMBIGUITY_OR_DEFECT,
                )
            )
        elif index == 99:
            references.append(
                MerchantReference(
                    document_id=row.document_id,
                    anchor_row_id=row.row_id,
                    disposition=ReferenceDisposition.NONTRANSACTION,
                    owner_row_id=None,
                    owned_row_ids=(),
                    merchant_text=None,
                    atom_ids=(),
                    source_regions=(),
                    ambiguity_category=None,
                )
            )
        else:
            references.append(
                MerchantReference(
                    document_id=row.document_id,
                    anchor_row_id=row.row_id,
                    disposition=ReferenceDisposition.TRANSACTION,
                    owner_row_id=row.row_id,
                    owned_row_ids=(row.row_id,),
                    merchant_text="SECRET MERCHANT",
                    atom_ids=(f"merchant-{index:03d}",),
                    source_regions=(),
                    ambiguity_category=None,
                )
            )
    return rows, rows, tuple(references)
```

Use that `100`-row synthetic training population to prove aggregate-only output. Patch the pilot
selector to return `selected` so this unit test exercises reference validation independently of
the already-covered selector quotas:

```python
def test_reference_validation_is_aggregate_only(monkeypatch: pytest.MonkeyPatch) -> None:
    population, selected, references = reference_fixture()
    monkeypatch.setattr(merchant_context, "select_visual_gold_pilot", lambda rows: selected)

    summary = validate_merchant_reference(population, selected, references)

    assert summary == MerchantReferenceSummary(
        anchor_count=100,
        eligible_transaction_count=98,
        ambiguous_anchor_count=1,
        nontransaction_anchor_count=1,
    )
    serialized = summary.model_dump_json()
    assert "SECRET MERCHANT" not in serialized
    assert selected[0].document_id not in serialized
    assert selected[0].row_id not in serialized
```

Add a separate test that rewrites references `0` and `1` to the same owner and owned-row payload
and asserts `eligible_transaction_count == 97`, proving transaction deduplication. Also cover
duplicate/missing/unknown anchors, nontraining rows, inconsistent repeated transaction payloads,
owners outside `owned_row_ids`, unknown owned rows or atom IDs, regions outside owned-row geometry,
noncanonical text, and an identity set differing from
`select_visual_gold_pilot(population)`. Assert only fixed sanitized error messages.

- [ ] **Step 2: Run the focused tests to verify RED**

Run:

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/test_merchant_context.py
```

Expected: collection fails because `experiments.row_extraction.merchant_context` does not exist.

- [ ] **Step 3: Implement the frozen private contracts and validators**

Start the module with these exact enums and normalization rule:

```python
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
```

Use one `_PrivateModel` with `frozen=True`, `extra="forbid"`, and
`hide_input_in_errors=True`. Implement the exact fields used in the tests:

```python
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


class MerchantAssertion(_PrivateModel):
    context_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    anchor_row_id: str = Field(min_length=1)
    disposition: AssertionDisposition
    owner_row_id: str | None
    merchant_text: str | None
    atom_ids: tuple[str, ...]
    source_regions: tuple[BBox, ...]


class MerchantReferenceSummary(_FrozenModel):
    anchor_count: int = Field(ge=0)
    eligible_transaction_count: int = Field(ge=0)
    ambiguous_anchor_count: int = Field(ge=0)
    nontransaction_anchor_count: int = Field(ge=0)
```

Add `model_validator(mode="after")` methods enforcing the three disposition shapes, canonical
unique IDs, canonical merchant text, and evidence support. Implement
`validate_merchant_reference` by:

1. requiring exactly 100 unique training anchors;
2. comparing their identity set with `select_visual_gold_pilot(population)`;
3. requiring exactly one reference per anchor;
4. indexing only same-document `FrozenRow` values;
5. checking every owner/owned row and declared atom/region against that index;
6. requiring repeated records for one `(document_id, owner_row_id)` to carry identical owner,
   owned-row, merchant-text, atom, and region payloads; and
7. counting unique transaction owners, not anchors.

Every failure raises `MerchantContextError` with one fixed content-free message such as
`"merchant reference coverage mismatch"`.

- [ ] **Step 4: Run focused and repository tests to verify GREEN**

Run:

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/test_merchant_context.py
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
```

Expected: all Task 1 tests and repository gates pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add experiments/row_extraction/merchant_context.py tests/experiments/row_extraction/test_merchant_context.py
git commit -m "feat: define merchant context reference contracts"
```

---

### Task 2: Materialize Six Opaque, Nested Context Arms

**Files:**
- Modify: `experiments/row_extraction/merchant_context.py`
- Modify: `tests/experiments/row_extraction/test_merchant_context.py`

**Interfaces:**
- Consumes: Task 1's `ContextTier` and `CONTEXT_TIERS`, `FrozenRow`, `write_jsonl`, source PDFs,
  reciprocal row adjacency, and role-free `ColumnBand.bbox` values.
- Produces: `ContextImage`, `MerchantContextPacket`, `MerchantContextIndex`,
  `MERCHANT_CONTEXT_PROMPT`,
  `materialize_anchor_contexts(population, anchor, image_root)`, and
  `materialize_merchant_contexts(population, selected_rows, private_root)`.

- [ ] **Step 1: Write failing geometry, leakage, rendering, and privacy tests**

Create a tiny synthetic PDF and five same-page rows whose shared role-free column boxes describe a
table. Define this exact fixture and coverage helper:

```python
def context_fixture(tmp_path: Path) -> tuple[tuple[FrozenRow, ...], FrozenRow]:
    source = tmp_path / "synthetic.pdf"
    with fitz.open() as document:
        document.new_page(width=200, height=300)
        document.save(source)
    rows: list[FrozenRow] = []
    for index in range(5):
        top = 80.0 + 25.0 * index
        row = frozen_row(
            document_id="a" * 64,
            row_id=f"row-{index}",
            source_pdf=source,
            bbox=(10.0, top, 190.0, top + 20.0),
            atoms=(
                evidence_atom(
                    atom_id=f"atom-{index}",
                    bbox=(20.0, top + 2.0, 80.0, top + 12.0),
                ),
            ),
        ).model_copy(
            update={
                "previous_row_id": f"row-{index - 1}" if index else None,
                "next_row_id": f"row-{index + 1}" if index < 4 else None,
                "column_bands": (
                    ColumnBand(index=0, role=FieldRole.DESCRIPTION, bbox=(10.0, 40.0, 190.0, 240.0)),
                ),
            }
        )
        rows.append(row)
    return tuple(rows), rows[2]


def source_regions_cover(outer: tuple[BBox, ...], inner: tuple[BBox, ...]) -> bool:
    return all(
        any(
            candidate[0] <= region[0]
            and candidate[1] <= region[1]
            and region[2] <= candidate[2]
            and region[3] <= candidate[3]
            for candidate in outer
        )
        for region in inner
    )
```

Assert the declared source coverage is monotonic and grows only where source evidence exists:

```python
def test_context_tiers_are_monotonic_and_change_only_spatial_extent(tmp_path: Path) -> None:
    population, anchor = context_fixture(tmp_path)

    pairs = materialize_anchor_contexts(population, anchor, tmp_path / "images")
    records = tuple((index, packet) for index, packet in pairs)

    assert tuple(index.tier for index, _ in records) == CONTEXT_TIERS
    for smaller, larger in itertools.pairwise(records):
        _, smaller_packet = smaller
        _, larger_packet = larger
        assert source_regions_cover(
            tuple(image.source_bbox for image in larger_packet.images),
            tuple(image.source_bbox for image in smaller_packet.images),
        )
        assert {row.row_id for row in smaller_packet.rows} <= {
            row.row_id for row in larger_packet.rows
        }
    assert tuple(row.row_id for row in records[0][1].rows) == (anchor.row_id,)
    assert len(records[1][1].rows) == 3
    assert len(records[2][1].rows) == 5
    assert len(records[3][1].images) == 2
    assert tuple(image.source_bbox for image in records[4][1].images) == (
        (10.0, 40.0, 190.0, 240.0),
    )
    assert tuple(image.source_bbox for image in records[5][1].images) == (
        (0.0, 0.0, 200.0, 300.0),
    )
```

Test page edges, cross-page adjacency, missing headers, and schemas that do not match the anchor.
Equal neighboring tiers are valid only when the additional declared evidence is absent.

Test the review payload separately from the private index:

```python
def test_review_packet_hides_tier_roles_labels_and_source_paths(tmp_path: Path) -> None:
    population, anchor = context_fixture(tmp_path)
    index, packet = materialize_anchor_contexts(population, anchor, tmp_path / "images")[0]
    serialized = packet.model_dump_json()

    assert index.tier is ContextTier.C0_ROW
    assert index.context_id == packet.context_id
    for forbidden in (
        "c0_row",
        "baseline_type",
        "role",
        "source_pdf",
        "current_gold",
        "reviewer_a",
        "reviewer_b",
        "prediction",
        "SECRET_FILENAME",
    ):
        assert forbidden not in serialized
```

Monkeypatch the renderer for the 100-anchor high-level test. Require exactly 600 unique context
IDs, six opaque batch files of 100 packets, one private index, identical prompt bytes, and cleanup
after any failed write. Require a new absolute ignored root named
`merchant-context-sufficiency-v1`; reject symlinks, nonempty roots, and tracked roots with sanitized
errors.

- [ ] **Step 2: Run the focused tests to verify RED**

Run:

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/test_merchant_context.py -k 'context or materialize or packet'
```

Expected: FAIL because the context records and materializer are absent.

- [ ] **Step 3: Implement source-region selection and opaque packets**

Use these exact review-facing shapes; keep `tier` only in the private index:

```python
class ContextImage(_PrivateModel):
    source_bbox: BBox
    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class MerchantContextRow(_PrivateModel):
    row_id: str = Field(min_length=1)
    bbox: BBox
    atoms: tuple[EvidenceAtom, ...]


class MerchantContextPacket(_PrivateModel):
    context_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    anchor_row_id: str = Field(min_length=1)
    page_number: int = Field(gt=0)
    anchor_bbox: BBox
    column_boundaries: tuple[BBox, ...]
    rows: tuple[MerchantContextRow, ...]
    images: tuple[ContextImage, ...] = Field(min_length=1)


class MerchantContextIndex(_PrivateModel):
    context_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    tier: ContextTier
    batch_id: str = Field(pattern=r"^[0-9a-f]{64}$")
```

Set one literal prompt for every batch:

```python
MERCHANT_CONTEXT_PROMPT = (
    "Identify the merchant for the transaction that owns the highlighted anchor row. "
    "Use only the supplied pixels and positioned atoms. Return exactly one "
    "MerchantAssertion JSON object for each packet. Include the complete merchant-bearing "
    "source text and its exact atom IDs and/or source regions. Do not include category, "
    "location, processor/reference, exchange-rate, fee, date, amount, currency, or "
    "installment text unless it is visually inseparable from and necessary to the printed "
    "merchant identity. Return nontransaction only for source evidence that is not a "
    "transaction; otherwise abstain when one supported merchant and owner cannot be "
    "established. Never guess, repair spelling, use a merchant database, or borrow text "
    "from another transaction."
)
```

Implement context selection without baseline types or semantic column roles:

- `C0`: anchor only and exact anchor bbox;
- `C1`: reciprocal same-page predecessor, anchor, and successor;
- `C2`: `C1` plus the second reciprocal same-page neighbor in each direction;
- `C3`: `C2` plus a separate visible header bbox from the shared role-free column-band top to the
  first row top, only when that rectangle has positive area;
- `C4`: every same-page row with the exact same ordered role-free column bboxes and the union of
  those column bboxes as the detected table region;
- `C5`: every frozen row on the anchor page and the complete PDF page bbox.

Render every source region at one constant 300 DPI to RGB PNG with the same four-pixel neutral
canvas margin. Draw the same one-pixel magenta anchor rectangle in that margin or immediately
outside the transformed anchor bounds, never over source pixels inside the anchor. Hash the exact
PNG bytes. If a declared bbox is invalid, unavailable, or cannot be rendered at that scale, raise
`MerchantContextError`; never resize or drop it.

Derive `context_id`, `batch_id`, image names, and packet ordering from SHA-256 of a fixed version,
opaque row identity, and tier. The packet and image paths contain only hashes. Write one
`context-index.jsonl` and six paths computed as `f"packets/{batch_id}.jsonl"` with `write_jsonl`. The extractor
receives one batch file, its referenced images, and `MERCHANT_CONTEXT_PROMPT`; it never receives
the index or semantic tier name.

`materialize_anchor_contexts` performs the geometry selection and rendering above and returns
six `(MerchantContextIndex, MerchantContextPacket)` pairs in `CONTEXT_TIERS` order. The high-level
`materialize_merchant_contexts` first requires exact selected-pilot identity equality, calls
the anchor function 100 times, groups packets by the index's opaque `batch_id`, writes the seven
private JSONL files, and returns all 600 pairs in canonical `(batch_id, context_id)` order.

- [ ] **Step 4: Run focused, neighboring, and repository tests to verify GREEN**

Run:

```bash
/root/creditcard/.venv/bin/pytest -q \
  tests/experiments/row_extraction/test_merchant_context.py \
  tests/experiments/row_extraction/test_visual_gold_pilot.py \
  tests/experiments/row_extraction/test_visual_gold_agreement.py
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
```

Expected: all focused tests and repository gates pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add experiments/row_extraction/merchant_context.py tests/experiments/row_extraction/test_merchant_context.py
git commit -m "feat: materialize merchant context arms"
```

---

### Task 3: Score Transaction-Level Accuracy and Render an Aggregate Result

**Files:**
- Modify: `experiments/row_extraction/merchant_context.py`
- Modify: `tests/experiments/row_extraction/test_merchant_context.py`

**Interfaces:**
- Consumes: validated Task 1 references and assertions plus Task 2 packets/index records.
- Produces: `MerchantErrorLabel`, `MerchantErrorCount`, `MerchantTierSummary`,
  `MerchantPairedDelta`, `MerchantContextSummary`, `score_merchant_context`, and
  `render_merchant_context_report(summary)`.

- [ ] **Step 1: Write failing scoring, decision, and privacy tests**

Build 100 synthetic anchors representing 98 unique eligible transactions, one ambiguous anchor,
and one nontransaction anchor. Generate all 600 assertions so the outcome is:

- `C0`: one wrong merchant, therefore unsafe;
- `C1`: safe but two omissions;
- `C2`: all 98 merchants correctly attributed, with two ancillary-text exactness failures;
- `C3`, `C4`, and `C5`: safe with identical 98/98 attribution and exact-text sets.

Define the scorer fixture without invoking rendering:

```python
def scoring_fixture() -> dict[str, object]:
    population, selected, references = reference_fixture()
    packets: list[MerchantContextPacket] = []
    index_records: list[MerchantContextIndex] = []
    assertions: list[MerchantAssertion] = []
    errors: list[MerchantErrorLabel] = []

    for tier in CONTEXT_TIERS:
        batch_id = hashlib.sha256(f"batch:{tier.value}".encode()).hexdigest()
        for row_index, row in enumerate(selected):
            context_id = hashlib.sha256(
                f"context:{tier.value}:{row_index}".encode()
            ).hexdigest()
            packets.append(
                MerchantContextPacket(
                    context_id=context_id,
                    document_id=row.document_id,
                    anchor_row_id=row.row_id,
                    page_number=1,
                    anchor_bbox=row.bbox,
                    column_boundaries=(),
                    rows=(
                        MerchantContextRow(
                            row_id=row.row_id,
                            bbox=row.bbox,
                            atoms=row.atoms,
                        ),
                    ),
                    images=(
                        ContextImage(
                            source_bbox=row.bbox,
                            relative_path=f"{context_id}/0.png",
                            sha256="f" * 64,
                            width=100,
                            height=20,
                        ),
                    ),
                )
            )
            index_records.append(
                MerchantContextIndex(
                    context_id=context_id,
                    tier=tier,
                    batch_id=batch_id,
                )
            )

            if row_index == 98:
                disposition = AssertionDisposition.ABSTAIN
                owner_row_id = None
                merchant_text = None
                atom_ids: tuple[str, ...] = ()
            elif row_index == 99:
                disposition = AssertionDisposition.NONTRANSACTION
                owner_row_id = None
                merchant_text = None
                atom_ids = ()
            elif tier is ContextTier.C0_ROW and row_index == 0:
                disposition = AssertionDisposition.MERCHANT
                owner_row_id = row.row_id
                merchant_text = "ANCILLARY"
                atom_ids = ("ancillary-000",)
                errors.append(
                    MerchantErrorLabel(
                        tier=tier,
                        document_id=row.document_id,
                        owner_row_id=row.row_id,
                        primary=MerchantErrorCategory.MERCHANT_VERSUS_ANCILLARY,
                    )
                )
            elif tier is ContextTier.C1_ADJACENT_ROWS and row_index < 2:
                disposition = AssertionDisposition.ABSTAIN
                owner_row_id = None
                merchant_text = None
                atom_ids = ()
                errors.append(
                    MerchantErrorLabel(
                        tier=tier,
                        document_id=row.document_id,
                        owner_row_id=row.row_id,
                        primary=MerchantErrorCategory.INSUFFICIENT_CONTEXT_OR_MISSING_HEADER,
                    )
                )
            elif tier is ContextTier.C2_LOCAL_NEIGHBORHOOD and row_index < 2:
                disposition = AssertionDisposition.MERCHANT
                owner_row_id = row.row_id
                merchant_text = "SECRET MERCHANT ANCILLARY"
                atom_ids = (f"merchant-{row_index:03d}", f"ancillary-{row_index:03d}")
                errors.append(
                    MerchantErrorLabel(
                        tier=tier,
                        document_id=row.document_id,
                        owner_row_id=row.row_id,
                        primary=MerchantErrorCategory.MERCHANT_VERSUS_ANCILLARY,
                    )
                )
            else:
                disposition = AssertionDisposition.MERCHANT
                owner_row_id = row.row_id
                merchant_text = "SECRET MERCHANT"
                atom_ids = (f"merchant-{row_index:03d}",)

            assertions.append(
                MerchantAssertion(
                    context_id=context_id,
                    document_id=row.document_id,
                    anchor_row_id=row.row_id,
                    disposition=disposition,
                    owner_row_id=owner_row_id,
                    merchant_text=merchant_text,
                    atom_ids=atom_ids,
                    source_regions=(),
                )
            )

    return {
        "population": population,
        "selected_rows": selected,
        "packets": tuple(packets),
        "index_records": tuple(index_records),
        "references": references,
        "assertions": tuple(assertions),
        "error_labels": tuple(errors),
    }
```

Assert the primary decision and the distinction between attribution and exact text:

```python
def test_scoring_selects_smallest_safe_tier_matching_full_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = scoring_fixture()
    monkeypatch.setattr(
        merchant_context,
        "select_visual_gold_pilot",
        lambda rows: case["selected_rows"],
    )

    summary = score_merchant_context(**case)

    assert summary.eligible_transaction_count == 98
    assert summary.recommended_tier is ContextTier.C3_HEADER_NEIGHBORHOOD
    assert summary.hypothesis_supported is True
    assert summary.hypothesis_falsified is False
    by_tier = {item.tier: item for item in summary.tiers}
    assert by_tier[ContextTier.C0_ROW].safe is False
    assert by_tier[ContextTier.C1_ADJACENT_ROWS].omissions == 2
    assert by_tier[ContextTier.C2_LOCAL_NEIGHBORHOOD].correct_attributions == 98
    assert by_tier[ContextTier.C2_LOCAL_NEIGHBORHOOD].exact_text_matches == 96
    assert by_tier[ContextTier.C3_HEADER_NEIGHBORHOOD].merchant_accuracy == Decimal(1)
```

Add tests proving:

- two selected anchors owned by one transaction count once;
- same-transaction ancillary suffixes preserve attribution but fail exact text;
- wrong owner or another transaction's merchant evidence increments wrong-merchant and ownership
  errors and makes the arm unsafe;
- `UNSUPPORTED_MERCHANT_TEXT` increments hallucination and makes the arm unsafe;
- missing, duplicate, unknown, wrong-context, or out-of-packet assertions fail closed;
- every non-exact eligible transaction/tier has exactly one primary error label, with unique
  secondary labels from the frozen taxonomy;
- error labels for exact transactions or unknown owners are rejected;
- rates ignore the ambient decimal context;
- if every arm is unsafe, the hypothesis is falsified and `recommended_tier` is `None`;
- a smaller safe tier that strictly beats `C5` is reported as context interference and can win;
- paired gains/losses are computed against the preceding tier and `C5`; and
- the serialized summary and rendered report omit all synthetic secrets, IDs, atom text, paths,
  and per-case outcomes.

- [ ] **Step 2: Run focused tests to verify RED**

Run:

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/test_merchant_context.py -k 'score or report or decision or decimal'
```

Expected: FAIL because scorer and aggregate records are absent.

- [ ] **Step 3: Implement exact transaction aggregation and the lexicographic decision**

Use aggregate-only frozen records:

```python
class MerchantErrorLabel(_PrivateModel):
    tier: ContextTier
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    owner_row_id: str = Field(min_length=1)
    primary: MerchantErrorCategory
    secondary: tuple[MerchantErrorCategory, ...] = ()


class MerchantErrorCount(_FrozenModel):
    category: MerchantErrorCategory
    count: int = Field(ge=0)


class MerchantTierSummary(_FrozenModel):
    tier: ContextTier
    eligible_transactions: int = Field(ge=0)
    correct_attributions: int = Field(ge=0)
    merchant_accuracy: Decimal
    exact_text_matches: int = Field(ge=0)
    exact_text_rate: Decimal
    omissions: int = Field(ge=0)
    wrong_merchants: int = Field(ge=0)
    hallucinations: int = Field(ge=0)
    ownership_errors: int = Field(ge=0)
    nontransaction_anchors: int = Field(ge=0)
    correct_nontransaction_anchors: int = Field(ge=0)
    errors: tuple[MerchantErrorCount, ...]
    safe: bool


class MerchantPairedDelta(_FrozenModel):
    tier: ContextTier
    comparator: ContextTier
    attribution_gains: int = Field(ge=0)
    attribution_losses: int = Field(ge=0)
    exact_text_gains: int = Field(ge=0)
    exact_text_losses: int = Field(ge=0)


class MerchantContextSummary(_FrozenModel):
    anchor_count: int = Field(ge=0)
    eligible_transaction_count: int = Field(ge=0)
    reference_ambiguity_count: int = Field(ge=0)
    nontransaction_anchor_count: int = Field(ge=0)
    tiers: tuple[MerchantTierSummary, ...]
    paired_deltas: tuple[MerchantPairedDelta, ...]
    recommended_tier: ContextTier | None
    hypothesis_supported: bool
    hypothesis_falsified: bool
    context_interference: bool
```

Implement `score_merchant_context` with this exact order:

1. call `validate_merchant_reference`;
2. require 600 unique assertions covering every `(context_id, anchor)` from the private index;
3. require all asserted atom IDs and regions to be available in that packet;
4. group eligible references by `(document_id, owner_row_id)` and score each transaction once;
5. mark attribution correct only when every represented anchor asserts the reference owner,
   contains the complete normalized reference merchant text in order, is source-supported, and
   contains no merchant evidence from another transaction;
6. mark exact text only when normalized text, ordered atom IDs, and source regions equal the
   reference and no ancillary text is present;
7. require one `MerchantErrorLabel` for every non-exact eligible transaction/tier and none for an
   exact transaction;
8. derive unsafe status from any wrong-merchant or `UNSUPPORTED_MERCHANT_TEXT` event;
9. compute all rates in a local `Context(prec=28, rounding=ROUND_HALF_EVEN)`;
10. retain private correct-transaction sets only in local variables for paired set differences;
11. select by safe status, attribution set, exact-text set, then tier order; and
12. set support/falsification by exact paired equality of safe `C3`-or-smaller outcomes with `C5`.

`render_merchant_context_report(summary)` returns Markdown containing the task contract, one
aggregate arm table, paired aggregate deltas, the supported/falsified result, limitations, and the
exact Metric-or-Stop block. It accepts only `MerchantContextSummary`; no private record type may
reach it.

- [ ] **Step 4: Run focused and full tracked verification to verify GREEN**

Run:

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/test_merchant_context.py
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
```

Expected: all commands pass. If the five sealed-runtime tests fail only inside the sandbox, rerun
the identical full pytest command with approved unsandboxed execution; do not change experiment
code to accommodate that environment.

- [ ] **Step 5: Commit Task 3**

```bash
git add experiments/row_extraction/merchant_context.py tests/experiments/row_extraction/test_merchant_context.py
git commit -m "feat: score merchant context sufficiency"
```

---

### Task 4: Freeze the Reference, Run Six Blind Arms Once, and Publish the Result

**Files:**
- Create: `docs/experiments/row-extraction-merchant-context-report.md`
- Modify: `docs/experiments/row-extraction-program-status.md`
- Private only: `artifacts/merchant-context-sufficiency-v1/**`

**Interfaces:**
- Consumes: the complete Task 1-3 module, the ignored frozen row bundle, the exact 100 selected
  identities, original source PDFs, six fresh extraction contexts, and one independent reference
  plus source-verification context.
- Produces: one frozen private reference, six frozen assertion streams, private error labels, one
  `MerchantContextSummary`, the aggregate report, and final `STOP` status.

- [ ] **Step 1: Verify the execution preconditions without printing private values**

Run `git status --short` and require a clean worktree at the committed Task 3 revision. Set only
task-specific environment variables to absolute ignored paths:

```bash
: "${MERCHANT_ROWS_JSONL:?set MERCHANT_ROWS_JSONL from the existing private local bundle configuration}"
export MERCHANT_CONTEXT_ROOT=/root/creditcard/.worktrees/merchant-context-sufficiency/artifacts/merchant-context-sufficiency-v1
test -f "$MERCHANT_ROWS_JSONL"
test ! -e "$MERCHANT_CONTEXT_ROOT"
git check-ignore --quiet "$MERCHANT_CONTEXT_ROOT"
```

Do not echo either variable or any digest. Load the rows, recompute
`select_visual_gold_pilot(rows)`, and report only `population_count=2503 selected_count=100
split=train`.

- [ ] **Step 2: Materialize the six opaque batches once**

Run this direct private-data invocation; it prints aggregate counts only and creates no helper
file:

```bash
PYTHONPATH=. /root/creditcard/.venv/bin/python -c '
import os
from pathlib import Path
from experiments.row_extraction.codecs import read_jsonl
from experiments.row_extraction.contracts import FrozenRow
from experiments.row_extraction.merchant_context import materialize_merchant_contexts
from experiments.row_extraction.visual_gold_pilot import select_visual_gold_pilot
rows = tuple(read_jsonl(Path(os.environ["MERCHANT_ROWS_JSONL"]), FrozenRow))
selected = select_visual_gold_pilot(rows)
materialized = materialize_merchant_contexts(
    rows,
    selected,
    Path(os.environ["MERCHANT_CONTEXT_ROOT"]),
)
print(
    f"packets={len(materialized)} "
    f"batches={len({index.batch_id for index, _ in materialized})} "
    f"anchors={len(selected)}"
)
'
```

Require exactly `packets=600 batches=6 anchors=100`. Inspect the private index only to assign
opaque batch paths to workers; do not print its IDs or tier mapping.

- [ ] **Step 3: Create and verify the independent reference before any arm runs**

Use a clean reference worker that receives the 100 anchors, full-page source evidence, the written
merchant rule, and no tested-arm prompt or outputs. It writes exactly one `MerchantReference` per
anchor to private canonical JSONL. A separate source-verification worker checks every asserted
character, owner, owned row, atom/region, and ambiguous/nontransaction disposition against the
source and written rule. Resolve challenges against the source; unresolved cases become ambiguous.

Run `validate_merchant_reference` and print only its four aggregate counts. Freeze the file
read-only. Stop here if the reference is incomplete, invalid, cannot be verified independently, or
requires current gold, accepted parser output, Reviewer A/B values, or predictions.

- [ ] **Step 4: Run each opaque context batch in a fresh extraction worker**

For each of the six batch files, create a fresh worker with exactly
`MERCHANT_CONTEXT_PROMPT`, that one packet file, and its referenced images. The worker must not see
the private tier index, reference, previous arm output, report, or expected hypothesis. Use the same
model snapshot and decoding settings for every batch. Each worker writes exactly one
`MerchantAssertion` per packet to a new private JSONL file and exits; do not reprompt a completed
case.

After all six workers finish, validate exact coverage and evidence support without scoring. Stop
if any assertion is missing, duplicated, malformed, cross-context, or based on unavailable
evidence. Do not repair output or rerun an arm.

- [ ] **Step 5: Classify frozen non-exact outcomes against the source**

Using the already-frozen reference and arm outputs, have the independent source-verification
context assign exactly one primary and any unique secondary `MerchantErrorCategory` values to each
non-exact eligible transaction/tier. It writes private `MerchantErrorLabel` JSONL. The extraction
workers never see these labels. Validation rejects missing, extra, duplicate, or post-taxonomy
categories.

- [ ] **Step 6: Execute the scorer exactly once**

Load the frozen packets, private index, reference, six assertion streams, and error labels, then
call `score_merchant_context` once. Persist the private canonical summary and render the
aggregate Markdown in memory. Print only the per-tier aggregate counts/rates, hypothesis result,
recommended tier or `none`, and context-interference boolean.

If scoring raises, stop the program task. Do not add a support task, change a label, rerun an arm,
or execute a second score to rescue the result.

- [ ] **Step 7: Publish the privacy-safe result and return status to STOP**

Use `apply_patch` to create
`docs/experiments/row-extraction-merchant-context-report.md` from the aggregate renderer output.
Use `apply_patch` to update `docs/experiments/row-extraction-program-status.md` with the same
aggregate values and exactly:

```text
Scope: YES — measured the effect of nested source context on transaction-level merchant attribution
Experiment: shared evaluation
Measurement: merchant-attribution accuracy, exact merchant-bearing-text rate, omission rate, wrong-merchant count, hallucination count, ownership-error count, and paired context-tier deltas
Result: copy the aggregate Result line emitted by render_merchant_context_report without editing
Next extraction task: STOP
```

Run a privacy scan before staging. Reject the report if it contains any document ID, row ID, atom
ID, source filename/path, merchant string, financial value, or per-case outcome.

- [ ] **Step 8: Run final verification and commit the measured result**

Run:

```bash
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/test_merchant_context.py
/root/creditcard/.venv/bin/pytest -q
git diff --check
git status --short
```

Expected: all gates pass and only the aggregate report/status files are uncommitted. Stage only
tracked implementation, tests, design clarification, plan, aggregate report, and status; never
stage `artifacts/`.

```bash
git add docs/experiments/row-extraction-merchant-context-report.md docs/experiments/row-extraction-program-status.md
git commit -m "docs: report merchant context sufficiency result"
```

Report the exact Metric-or-Stop block, the final tracked verification result, and that no private
corpus acceptance was claimed.
