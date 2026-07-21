# Structured FX Transaction Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve printed exchange rates and foreign-currency fees as evidence-backed transaction data in canonical JSON and CSV without changing billed amounts or reconciliation arithmetic.

**Architecture:** Add immutable nested FX models to `Transaction`, reconstruct decimal candidates from bounded positioned evidence, and place issuer-neutral extraction in a focused `ccparser.fx` module. `normalize.py` will call that module after original-currency and conversion-date extraction, merge its evidence claims and diagnostics, and leave reconciliation behavior unchanged.

**Tech Stack:** Python 3.13, Pydantic 2, `Decimal`, pytest, Ruff, mypy, existing geometry and semantic-evidence models.

## Global Constraints

- Use Python 3.13 and `.venv`.
- Follow red-green-refactor for every production behavior and observe each focused test fail for the expected reason before implementation.
- Use `Decimal` for every rate, percentage, fee, discount, and derivation.
- Do not add filename-, path-, hash-, date-, merchant-, amount-, total-, issuer-, card-, account-, or document-specific branches.
- Emit a value only from one unambiguous, locally bounded candidate with exact evidence.
- Explicit but unparseable FX cues add transaction ambiguities and prevent strict success.
- Do not commit private PDFs, copied private statement content beyond minimized test strings, parser output, or cache data.
- Before every commit run `.venv/bin/ruff format --check .`, `.venv/bin/ruff check .`, `.venv/bin/mypy src`, and `.venv/bin/pytest -q`.

---

### Task 1: Add immutable evidence-backed FX models

**Files:**
- Modify: `src/ccparser/models.py:82-140`
- Modify: `tests/test_models.py:133-235`

**Interfaces:**
- Produces: `ExtractedDecimal(value: Decimal, evidence: tuple[EvidenceReference, ...])`
- Produces: `ExtractedMoney(amount: Decimal, currency: str, evidence: tuple[EvidenceReference, ...], derivation: Literal["printed", "gross_fee_minus_discount"] = "printed")`
- Produces: `ForeignExchangeDetails(exchange_rate, fee_percentage, gross_fee, fee_discount, net_fee)`
- Extends: `Transaction.foreign_exchange: ForeignExchangeDetails | None = None`

- [ ] **Step 1: Write failing public-model tests**

Add focused tests that construct printed and derived FX values, verify canonical
Decimal serialization, and reject invalid evidence or derivation:

```python
def _fx_evidence(raw_text: str, y: float) -> EvidenceReference:
    return EvidenceReference(
        page_number=1,
        bbox=(10.0, y, 50.0, y + 10.0),
        raw_text=raw_text,
    )


def test_transaction_preserves_evidence_backed_foreign_exchange_details() -> None:
    from ccparser.models import (
        ExtractedDecimal,
        ExtractedMoney,
        ForeignExchangeDetails,
        Transaction,
        TransactionKind,
    )

    rate_evidence = _fx_evidence("exchange rate 2.9430", 10.0)
    fee_evidence = _fx_evidence("fee ILS 0.88", 20.0)
    discount_evidence = _fx_evidence("discount ILS 0.59", 30.0)
    transaction = Transaction(
        transaction_id="fx-1",
        kind=TransactionKind.CHARGE,
        billed_amount=Decimal("29.72"),
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        original_currency="USD",
        reconciliation_group_ids=("group-1",),
        foreign_exchange=ForeignExchangeDetails(
            exchange_rate=ExtractedDecimal(
                value=Decimal("2.9430"), evidence=(rate_evidence,)
            ),
            fee_percentage=ExtractedDecimal(
                value=Decimal("3.00"), evidence=(fee_evidence,)
            ),
            gross_fee=ExtractedMoney(
                amount=Decimal("0.88"), currency="ILS", evidence=(fee_evidence,)
            ),
            fee_discount=ExtractedMoney(
                amount=Decimal("0.59"), currency="ILS", evidence=(discount_evidence,)
            ),
            net_fee=ExtractedMoney(
                amount=Decimal("0.29"),
                currency="ILS",
                evidence=(fee_evidence, discount_evidence),
                derivation="gross_fee_minus_discount",
            ),
        ),
    )

    payload = transaction.model_dump(mode="json")["foreign_exchange"]
    assert payload["exchange_rate"]["value"] == "2.943"
    assert payload["fee_percentage"]["value"] == "3"
    assert payload["gross_fee"]["amount"] == "0.88"
    assert payload["net_fee"]["amount"] == "0.29"
    assert payload["net_fee"]["derivation"] == "gross_fee_minus_discount"


def test_foreign_exchange_requires_evidence_and_exact_derivation() -> None:
    from ccparser.models import ExtractedDecimal, ExtractedMoney, ForeignExchangeDetails

    fee_evidence = _fx_evidence("fee ILS 0.88", 20.0)
    discount_evidence = _fx_evidence("discount ILS 0.59", 30.0)
    with pytest.raises(ValidationError, match="at least 1 item"):
        ExtractedDecimal(value=Decimal("2.9430"), evidence=())
    with pytest.raises(ValueError, match="at least one FX value"):
        ForeignExchangeDetails()
    with pytest.raises(ValueError, match="exact gross fee minus discount"):
        ForeignExchangeDetails(
            gross_fee=ExtractedMoney(
                amount=Decimal("0.88"), currency="ILS", evidence=(fee_evidence,)
            ),
            fee_discount=ExtractedMoney(
                amount=Decimal("0.59"), currency="ILS", evidence=(discount_evidence,)
            ),
            net_fee=ExtractedMoney(
                amount=Decimal("0.30"),
                currency="ILS",
                evidence=(fee_evidence, discount_evidence),
                derivation="gross_fee_minus_discount",
            ),
        )
```

Extend `test_existing_transaction_constructor_remains_valid_after_extension`
with `assert transaction.foreign_exchange is None`. Extend the non-finite
parameterized test to cover `ExtractedDecimal.value` and
`ExtractedMoney.amount`.

- [ ] **Step 2: Run the model tests and confirm RED**

Run:

```bash
.venv/bin/pytest -q tests/test_models.py -k 'foreign_exchange or existing_transaction or nonfinite'
```

Expected: FAIL because `ExtractedDecimal`, `ExtractedMoney`,
`ForeignExchangeDetails`, and `Transaction.foreign_exchange` do not exist.

- [ ] **Step 3: Implement the nested models and validators**

Insert these models after `EvidenceReference`, and add the optional field to
`Transaction`:

```python
class ExtractedDecimal(BaseModel):
    """One finite decimal value with the exact evidence that proves it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: FiniteDecimal
    evidence: tuple[EvidenceReference, ...] = Field(min_length=1)

    @field_serializer("value")
    def serialize_value(self, value: Decimal) -> str:
        return _decimal_string(value)


class ExtractedMoney(BaseModel):
    """One printed or exactly derived monetary value with provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    amount: FiniteDecimal
    currency: str
    evidence: tuple[EvidenceReference, ...] = Field(min_length=1)
    derivation: Literal["printed", "gross_fee_minus_discount"] = "printed"

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal) -> str:
        return _decimal_string(value)


class ForeignExchangeDetails(BaseModel):
    """Structured rate and fee details for a foreign-currency transaction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exchange_rate: ExtractedDecimal | None = None
    fee_percentage: ExtractedDecimal | None = None
    gross_fee: ExtractedMoney | None = None
    fee_discount: ExtractedMoney | None = None
    net_fee: ExtractedMoney | None = None

    @model_validator(mode="after")
    def validate_details(self) -> Self:
        if all(
            value is None
            for value in (
                self.exchange_rate,
                self.fee_percentage,
                self.gross_fee,
                self.fee_discount,
                self.net_fee,
            )
        ):
            raise ValueError("at least one FX value is required")
        if self.exchange_rate is not None and self.exchange_rate.value <= 0:
            raise ValueError("exchange rate must be positive")
        if self.fee_percentage is not None and self.fee_percentage.value < 0:
            raise ValueError("fee percentage cannot be negative")
        if self.net_fee is not None and self.net_fee.derivation == "gross_fee_minus_discount":
            if self.gross_fee is None or self.fee_discount is None:
                raise ValueError("derived net fee requires gross fee and discount")
            if len(
                {
                    self.gross_fee.currency,
                    self.fee_discount.currency,
                    self.net_fee.currency,
                }
            ) != 1:
                raise ValueError("derived fee currencies must match")
            expected = self.gross_fee.amount - self.fee_discount.amount
            expected_evidence = tuple(
                dict.fromkeys((*self.gross_fee.evidence, *self.fee_discount.evidence))
            )
            if self.net_fee.amount != expected or self.net_fee.evidence != expected_evidence:
                raise ValueError("net fee must equal exact gross fee minus discount")
        return self
```

Add to `Transaction` immediately before `evidence`:

```python
foreign_exchange: ForeignExchangeDetails | None = None
```

- [ ] **Step 4: Run focused and complete model tests and confirm GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_models.py
```

Expected: all model tests PASS.

- [ ] **Step 5: Format, run all required gates, and commit**

```bash
.venv/bin/ruff format src/ccparser/models.py tests/test_models.py
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
git add src/ccparser/models.py tests/test_models.py
git commit -m "feat: add evidence-backed FX transaction models"
```

---

### Task 2: Add deterministic JSON and append-only CSV projection

**Files:**
- Modify: `src/ccparser/output.py:19-184`
- Modify: `tests/test_output.py:14-128`

**Interfaces:**
- Consumes: `Transaction.foreign_exchange` and the nested models from Task 1
- Produces: canonical nested JSON through existing Pydantic dumping
- Produces: appended FX value, currency, derivation, page, and bounding-box CSV columns

- [ ] **Step 1: Extend the output fixture and write failing schema assertions**

Import the three FX models in `tests/test_output.py`. In `_batch`, create one
rate evidence reference, one gross-fee reference, and one discount reference;
pass a `ForeignExchangeDetails` object to the transaction. Add JSON assertions:

```python
foreign_exchange = transaction["foreign_exchange"]
assert foreign_exchange["exchange_rate"]["value"] == "2.943"
assert foreign_exchange["gross_fee"]["amount"] == "0.88"
assert foreign_exchange["fee_discount"]["amount"] == "0.59"
assert foreign_exchange["net_fee"]["amount"] == "0.29"
assert foreign_exchange["net_fee"]["derivation"] == "gross_fee_minus_discount"
```

Add CSV assertions for the exact additive schema:

```python
assert row["exchange_rate"] == "2.943"
assert row["foreign_currency_fee_percentage"] == "3"
assert row["gross_foreign_currency_fee"] == "0.88"
assert row["gross_foreign_currency_fee_currency"] == "ILS"
assert row["foreign_currency_fee_discount"] == "0.59"
assert row["net_foreign_currency_fee"] == "0.29"
assert row["net_foreign_currency_fee_derivation"] == "gross_fee_minus_discount"
assert row["exchange_rate_source_page"] == "1"
assert row["exchange_rate_source_bbox"].startswith("1:")
```

Add an assertion to the empty-result test that every new FX column is present
and empty.

- [ ] **Step 2: Run focused output tests and confirm RED**

Run:

```bash
.venv/bin/pytest -q tests/test_output.py -k 'canonical_json or transactions_csv'
```

Expected: JSON assertions pass through the model automatically, while CSV
assertions FAIL because the new columns are absent.

- [ ] **Step 3: Append the FX columns and flatten evidence deterministically**

Append the exact columns from the approved specification to `CSV_COLUMNS`.
Generalize `_provenance` to accept evidence references and add one focused FX
projection helper:

```python
def _provenance(references: Iterable[EvidenceReference]) -> tuple[str, str]:
    evidence = tuple(references)
    pages = tuple(dict.fromkeys(reference.page_number for reference in evidence))
    boxes = tuple(
        f"{reference.page_number}:"
        + ",".join(_coordinate(value) for value in reference.bbox)
        for reference in evidence
    )
    return ";".join(str(page) for page in pages), ";".join(boxes)


def _fx_fields(transaction: Transaction) -> dict[str, str]:
    fields = {
        column: ""
        for column in CSV_COLUMNS
        if column.startswith("exchange_rate")
        or column.startswith("foreign_currency_fee")
        or column.startswith("gross_foreign_currency_fee")
        or column.startswith("net_foreign_currency_fee")
    }
    details = transaction.foreign_exchange
    if details is None:
        return fields

    def add_decimal(prefix: str, extracted: ExtractedDecimal | None) -> None:
        if extracted is None:
            return
        pages, boxes = _provenance(extracted.evidence)
        fields[prefix] = _decimal_string(extracted.value)
        fields[f"{prefix}_source_page"] = pages
        fields[f"{prefix}_source_bbox"] = boxes

    def add_money(prefix: str, extracted: ExtractedMoney | None) -> None:
        if extracted is None:
            return
        pages, boxes = _provenance(extracted.evidence)
        fields[prefix] = _decimal_string(extracted.amount)
        fields[f"{prefix}_currency"] = extracted.currency
        fields[f"{prefix}_source_page"] = pages
        fields[f"{prefix}_source_bbox"] = boxes

    add_decimal("exchange_rate", details.exchange_rate)
    add_decimal("foreign_currency_fee_percentage", details.fee_percentage)
    add_money("gross_foreign_currency_fee", details.gross_fee)
    add_money("foreign_currency_fee_discount", details.fee_discount)
    add_money("net_foreign_currency_fee", details.net_fee)
    if details.net_fee is not None:
        fields["net_foreign_currency_fee_derivation"] = details.net_fee.derivation
    return fields
```

Import `EvidenceReference`, `ExtractedDecimal`, and `ExtractedMoney`. Change the
transaction provenance call to `_provenance(transaction.evidence)` and merge
`**_fx_fields(transaction)` into `_transaction_row`.

- [ ] **Step 4: Run output tests and confirm GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_output.py
```

Expected: all output tests PASS, including deterministic repeat writes.

- [ ] **Step 5: Format, run all required gates, and commit**

```bash
.venv/bin/ruff format src/ccparser/output.py tests/test_output.py
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
git add src/ccparser/output.py tests/test_output.py
git commit -m "feat: serialize structured FX transaction data"
```

---

### Task 3: Reconstruct bounded decimal candidates from positioned evidence

**Files:**
- Modify: `src/ccparser/semantic_evidence.py:17-96,300-430,575-588`
- Modify: `tests/test_semantic_evidence.py`

**Interfaces:**
- Produces: `PositionedDecimalCandidate(text: str, atom_ids: frozenset[int])`
- Produces: `EvidenceLedger.positioned_decimal_candidates(atom_ids, *, max_fraction_digits=6)`
- Extends: `SemanticOwner` with `EXCHANGE_RATE`, `FX_FEE_PERCENTAGE`, `GROSS_FX_FEE`, `FX_FEE_DISCOUNT`, and `NET_FX_FEE`

- [ ] **Step 1: Write failing positioned-decimal tests**

Create synthetic cells whose logical text contains spaces but whose glyphs prove
one contiguous decimal. Test three boundaries:

```python
def test_positioned_decimal_candidates_join_only_small_numeric_gaps() -> None:
    cell = _glyph_cell("rate 2.94 30", physical_numeric="2.9430", numeric_gap=0.2)
    ledger = EvidenceLedger.from_rows((_row(cell),))

    candidates = ledger.positioned_decimal_candidates(ledger.atoms_for_cell(cell))

    assert tuple(candidate.text for candidate in candidates) == ("2.9430",)


def test_positioned_decimal_candidates_exclude_claimed_date_atoms() -> None:
    cell = _glyph_cell("22/06/26 2.9660", physical_numeric="22/06/26 2.9660")
    ledger = EvidenceLedger.from_rows((_row(cell),))
    date_ids = frozenset(
        atom_id
        for candidate in ledger.fragmented_date_candidates(cell)
        for atom_id in candidate.atom_ids
    )

    candidates = ledger.positioned_decimal_candidates(
        ledger.atoms_for_cell(cell) - date_ids
    )

    assert tuple(candidate.text for candidate in candidates) == ("2.9660",)


def test_positioned_decimal_candidates_reject_material_interglyph_gap() -> None:
    cell = _glyph_cell("2.94 30", physical_numeric="2.9430", numeric_gap=8.0)
    ledger = EvidenceLedger.from_rows((_row(cell),))

    assert ledger.positioned_decimal_candidates(ledger.atoms_for_cell(cell)) == ()
```

The local `_glyph_cell` helper must build actual `Glyph` positions; it must not
encode the expected result in production-facing metadata.

- [ ] **Step 2: Run the focused evidence tests and confirm RED**

Run:

```bash
.venv/bin/pytest -q tests/test_semantic_evidence.py -k positioned_decimal
```

Expected: FAIL because `positioned_decimal_candidates` does not exist.

- [ ] **Step 3: Add the candidate model, owners, and bounded reconstruction**

Add the immutable candidate:

```python
@dataclass(frozen=True, slots=True)
class PositionedDecimalCandidate:
    """A decimal reconstructed from one contiguous positioned numeric run."""

    text: str
    atom_ids: frozenset[int]
```

Implement `positioned_decimal_candidates` beside
`fragmented_date_candidates`. It must:

1. Restrict processing to the supplied atom IDs.
2. Use glyph-backed atoms only; return no candidates for unpositioned fallback
   text rather than guessing.
3. Group glyphs by page and physical line using the same half-height tolerance
   as date reconstruction.
4. Sort each line by increasing x coordinate.
5. Continue a numeric run only across digits, one `.` or `,`, and gaps no larger
   than `0.6 * min(previous_height, current_height)`.
6. Ignore whitespace glyphs only when that same gap rule holds.
7. Match `\d+[.,]\d{1,max_fraction_digits}` and retain the exact matched atom
   IDs.
8. Reject runs with multiple separators, integer-only footnotes, a missing
   fractional side, or material gaps.
9. Deduplicate by `(text, atom_ids)` while preserving physical order.

Add the five semantic owners and export `PositionedDecimalCandidate` through
`__all__`.

- [ ] **Step 4: Run focused and full evidence tests and confirm GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_semantic_evidence.py
```

Expected: all semantic-evidence tests PASS.

- [ ] **Step 5: Format, run all required gates, and commit**

```bash
.venv/bin/ruff format src/ccparser/semantic_evidence.py tests/test_semantic_evidence.py
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
git add src/ccparser/semantic_evidence.py tests/test_semantic_evidence.py
git commit -m "feat: reconstruct positioned decimal evidence"
```

---

### Task 4: Extract rates and applied fees from semantic table columns

**Files:**
- Create: `src/ccparser/fx.py`
- Create: `tests/test_fx.py`

**Interfaces:**
- Consumes: rows, inferred `TableRegion`, `EvidenceLedger`, currencies, and parsed conversion date
- Produces: `ForeignExchangeExtraction(details, claims, diagnostics)`
- Produces: `extract_foreign_exchange(*, rows, region, ledger, original_currency, billing_currency, conversion_date)`

- [ ] **Step 1: Write failing unit tests for typed table evidence**

Build a synthetic table with these semantic roles and minimized values:

```python
roles = (
    ColumnRole.AMOUNT,
    ColumnRole.AUXILIARY_AMOUNT,
    ColumnRole.CONVERSION_DATE,
    ColumnRole.ORIGINAL_AMOUNT,
    ColumnRole.DESCRIPTION,
    ColumnRole.DATE,
)
headers = (
    "Amount charged",
    "Foreign-currency fee",
    "Conversion date Exchange rate",
    "Original amount",
    "Merchant",
    "Transaction date",
)
```

The row must contain a detached integer footnote in the fee cell and a combined
date/rate cell. Assert:

```python
extraction = extract_foreign_exchange(
    rows=(row,),
    region=region,
    ledger=EvidenceLedger.from_rows((row,)),
    original_currency="USD",
    billing_currency="ILS",
    conversion_date=date(2026, 6, 22),
)

assert extraction.details is not None
assert extraction.details.exchange_rate is not None
assert extraction.details.exchange_rate.value == Decimal("2.9660")
assert extraction.details.net_fee is not None
assert extraction.details.net_fee.amount == Decimal("1.69")
assert extraction.details.net_fee.currency == "ILS"
assert extraction.details.gross_fee is None
assert extraction.details.fee_discount is None
assert extraction.diagnostics == ()
assert {claim.owner for claim in extraction.claims} == {
    SemanticOwner.EXCHANGE_RATE,
    SemanticOwner.NET_FX_FEE,
}
```

Add negative tests proving that a non-foreign row returns an empty extraction,
a generic `auxiliary_amount` header that does not say fee/commission is ignored,
and two decimal rate candidates emit
`unparsed_exchange_rate_candidate` with a null rate.

- [ ] **Step 2: Run the new unit tests and confirm RED**

Run:

```bash
.venv/bin/pytest -q tests/test_fx.py
```

Expected: collection FAIL because `ccparser.fx` does not exist.

- [ ] **Step 3: Implement the focused FX extraction module**

Start with this public internal contract:

```python
@dataclass(frozen=True, slots=True)
class ForeignExchangeExtraction:
    details: ForeignExchangeDetails | None = None
    claims: tuple[EvidenceClaim, ...] = ()
    diagnostics: tuple[str, ...] = ()


def extract_foreign_exchange(
    *,
    rows: Sequence[Row],
    region: TableRegion,
    ledger: EvidenceLedger,
    original_currency: str | None,
    billing_currency: str,
    conversion_date: date | None,
) -> ForeignExchangeExtraction:
    if original_currency is None or original_currency == billing_currency:
        return ForeignExchangeExtraction()
    table = _table_fx_values(rows[0], region, ledger, billing_currency)
    return _finish_extraction(table)
```

Implement issuer-neutral helpers with these exact responsibilities:

- `_cells_for_column(row, column)` assigns cells by positioned center, matching
  normalization's established rule.
- `_header_phrase(column)` normalizes only `column.source_cells` text.
- `_is_fee_column(column)` requires an `auxiliary_amount` role plus a complete
  supported fee/commission header cue (`fee`, `commission`, `foreign-currency
  fee`, `עמלה`, or `עמלת מט ח`).
- `_field_evidence(cells)` returns deterministic unique `EvidenceReference`
  objects for the exact supporting cells.
- `_date_atom_ids(cell, ledger)` unions every slash-date candidate's atoms.
- `_one_positive_decimal(atom_ids, ledger)` accepts exactly one positioned
  decimal and converts its normalized `.`/`,` text with `Decimal`.
- `_one_money(cell, ledger, expected_currency)` requires exactly one explicit
  currency in the cell and exactly one decimal candidate adjacent to that
  currency run. It ignores integer-only detached footnotes. It returns no value
  on a currency conflict or multiple decimal candidates.
- `_table_fx_values` extracts a rate from one `exchange_rate` column, or from one
  combined `conversion_date` cell after excluding date atoms. It extracts one
  applied `net_fee` from a proven fee column.
- `_finish_extraction` deduplicates diagnostics, creates
  `ForeignExchangeDetails` only when at least one value exists, and returns all
  exact field claims.

When a proven rate or fee field contains candidate evidence but does not yield
exactly one valid value, emit `unparsed_exchange_rate_candidate` or
`unparsed_foreign_currency_fee_candidate` respectively.

- [ ] **Step 4: Run the FX unit tests and confirm GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_fx.py
```

Expected: all table-column FX extraction tests PASS.

- [ ] **Step 5: Format, run all required gates, and commit**

```bash
.venv/bin/ruff format src/ccparser/fx.py tests/test_fx.py
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
git add src/ccparser/fx.py tests/test_fx.py
git commit -m "feat: extract FX values from semantic columns"
```

---

### Task 5: Extract bounded continuation details and integrate normalization

**Files:**
- Modify: `src/ccparser/fx.py`
- Modify: `src/ccparser/normalize.py:20-42,2651-2920,3149-3227`
- Modify: `tests/test_fx.py`
- Modify: `tests/test_normalize.py`

**Interfaces:**
- Extends: `extract_foreign_exchange` with bounded continuation-block extraction
- Integrates: `Transaction.foreign_exchange`, FX claims, and FX diagnostics into `_normalize_row`
- Preserves: exact billed amount, original amount, dates, descriptions, group membership, and reconciliation totals

- [ ] **Step 1: Write failing continuation-block extraction tests**

Construct one base row and four continuation rows marked with both
`subordinate_detail_continuation` and `foreign_conversion_detail_block`. Use
minimized bilingual cues and positioned fragments for:

- one exchange rate split across adjacent cells;
- one printed fee percentage;
- one printed gross fee amount followed by a discount cue;
- one printed discount amount in the next bounded line.

Assert the complete result:

```python
assert details.exchange_rate.value == Decimal("2.9430")
assert details.fee_percentage.value == Decimal("3.00")
assert details.gross_fee.amount == Decimal("0.88")
assert details.fee_discount.amount == Decimal("0.59")
assert details.net_fee.amount == Decimal("0.29")
assert details.net_fee.currency == "ILS"
assert details.net_fee.derivation == "gross_fee_minus_discount"
assert details.net_fee.evidence == tuple(
    dict.fromkeys((*details.gross_fee.evidence, *details.fee_discount.evidence))
)
assert extraction.diagnostics == ()
```

Add parameterized negative cases:

```python
@pytest.mark.parametrize(
    ("broken_field", "diagnostic"),
    (
        ("rate", "unparsed_exchange_rate_candidate"),
        ("percentage", "unparsed_foreign_currency_fee_percentage_candidate"),
        ("gross_fee", "unparsed_foreign_currency_fee_candidate"),
        ("discount", "unparsed_foreign_currency_fee_discount_candidate"),
    ),
)
def test_explicit_unparseable_fx_cue_emits_targeted_diagnostic(
    broken_field: str,
    diagnostic: str,
) -> None:
    rows, region = _continuation_fixture(broken_field=broken_field)
    extraction = extract_foreign_exchange(
        rows=rows,
        region=region,
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        conversion_date=date(2026, 6, 25),
    )

    assert diagnostic in extraction.diagnostics
    assert extraction.details is None or getattr(
        extraction.details,
        {
            "rate": "exchange_rate",
            "percentage": "fee_percentage",
            "gross_fee": "gross_fee",
            "discount": "fee_discount",
        }[broken_field],
    ) is None
```

Define `_continuation_fixture(*, broken_field: str | None = None) ->
tuple[tuple[Row, ...], TableRegion]` immediately above these tests. It builds the
same base and four bounded continuation rows used by the positive test; for the
selected field it replaces the one valid positioned number with two distinct
valid numbers. Add separate tests proving unrelated numeric continuation text without
`foreign_conversion_detail_block` is ignored and a discount larger than its
gross fee emits `inconsistent_foreign_currency_fee_derivation` with null
`net_fee`.

- [ ] **Step 2: Run continuation unit tests and confirm RED**

Run:

```bash
.venv/bin/pytest -q tests/test_fx.py -k 'continuation or unparseable or derivation'
```

Expected: FAIL because the module currently extracts only typed table columns.

- [ ] **Step 3: Implement the bounded continuation state machine**

Extend `fx.py` with normalized cue sets for supported language concepts, never
issuer names. `_continuation_fx_values` must inspect only rows carrying
`foreign_conversion_detail_block`, in physical y order. For each row:

1. Build positioned decimal candidates from all of that row's exact atoms.
2. A rate cue consumes exactly one positive decimal with up to six fractional
   digits and claims it as `EXCHANGE_RATE`.
3. A fee cue plus `%` consumes exactly one non-negative decimal and claims it as
   `FX_FEE_PERCENTAGE`.
4. A fee-amount cue plus one explicit currency consumes one money candidate. If
   the same row says a discount is subtracted from that fee, record the current
   money as `gross_fee` and set a one-row pending discount state.
5. A discount cue, or the immediately following bounded row while discount is
   pending, consumes one same-currency money candidate as `fee_discount`.
6. Clear pending state at any new base row, non-bounded row, or after one
   attempted discount row.
7. When gross and discount are present with one currency and
   `gross - discount >= 0`, build a derived `net_fee` with exact subtraction,
   evidence union, and `gross_fee_minus_discount`.
8. When no separate gross or discount semantics exist, retain a proven table
   fee as the printed `net_fee` from Task 4.

Merge table and continuation candidates only when they agree exactly. Competing
values for the same field produce that field's existing `unparsed_*` diagnostic
and leave the field null.

- [ ] **Step 4: Add failing end-to-end normalization tests**

Use `tests/test_normalize.py`'s `_region` and `_discovery` helpers to normalize:

1. A typed rate/fee table row.
2. A narrative continuation block with gross fee, discount, and derived net.
3. The same narrative block with an ambiguous rate.

Assert the first two reconcile, preserve existing transaction fields, and expose
the nested FX data. Assert the third keeps its billed transaction, carries
`unparsed_exchange_rate_candidate`, has zero reconciliation difference, and is
`Status.UNRECONCILED`.

- [ ] **Step 5: Run normalization tests and confirm RED**

Run:

```bash
.venv/bin/pytest -q tests/test_normalize.py -k 'foreign_exchange or fx_'
```

Expected: FAIL because `_normalize_row` does not call the FX extractor or place
its result on `Transaction`.

- [ ] **Step 6: Integrate the extractor and semantic ownership**

Import `extract_foreign_exchange`. Immediately after conversion-date recovery,
add:

```python
fx_extraction = extract_foreign_exchange(
    rows=rows,
    region=region,
    ledger=ledger,
    original_currency=original_currency,
    billing_currency=billed.currency,
    conversion_date=conversion_date,
)
semantic_claims.extend(fx_extraction.claims)
diagnostics.extend(fx_extraction.diagnostics)
```

Pass `foreign_exchange=fx_extraction.details` to `Transaction`. Keep the FX
claims in `initial_claims` for `_semantic_claims_and_diagnostics`; its existing
`_add_remaining_claim` behavior will classify only unclaimed remainder from
auxiliary/rate cells as ancillary, avoiding conflicting ownership.

- [ ] **Step 7: Run focused regression suites and confirm GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_fx.py tests/test_normalize.py tests/test_reconcile.py tests/test_cli.py
```

Expected: all focused tests PASS, including issue 1–3 semantic regressions and
strict status behavior.

- [ ] **Step 8: Format, run all required gates, and commit**

```bash
.venv/bin/ruff format src/ccparser/fx.py src/ccparser/normalize.py tests/test_fx.py tests/test_normalize.py
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
git add src/ccparser/fx.py src/ccparser/normalize.py tests/test_fx.py tests/test_normalize.py
git commit -m "feat: preserve structured FX evidence during normalization"
```

---

### Task 6: Document schema migration and verify the private acceptance corpus

**Files:**
- Modify: `README.md:50-74,95-104`
- Verify only: local July PDF inputs and generated temporary output

**Interfaces:**
- Documents: nullable nested JSON schema, appended CSV columns, evidence semantics, and consumer migration
- Verifies: Issues 1–4, deterministic output, strict semantics, and OCR independence

- [ ] **Step 1: Add the documented additive migration path**

After the output-file description, document:

```markdown
Foreign-currency transactions may include a nullable `foreign_exchange` JSON
object. Its exchange rate, fee percentage, gross fee, fee discount, and net fee
values each retain field-level source evidence. A net fee derived by exact gross
fee minus discount is marked `gross_fee_minus_discount`.

The CSV appends equivalent FX value, currency, derivation, source-page, and
source-bounding-box columns after the original columns. Existing keys and
columns retain their meanings and order. Consumers should ignore unknown JSON
keys and trailing CSV columns so additive schema extensions remain compatible.
```

Extend the semantic-completeness paragraph to state that explicit unparseable FX
cues are transaction ambiguities and prevent strict success.

- [ ] **Step 2: Run issue 1–3 focused verification**

```bash
.venv/bin/pytest -q tests/test_normalize.py -k 'description or conversion_date or semantic or unresolved or strict'
```

Expected: all selected tests PASS.

- [ ] **Step 3: Run every required repository gate**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
```

Expected: all four commands exit 0 with no failures or warnings.

- [ ] **Step 4: Parse both available July inputs twice without Tesseract**

Use fresh temporary output/cache directories while reading the local PDFs in
place:

```bash
task_tmp=$(mktemp -d /tmp/ccparser-fx-acceptance-XXXXXX)
env PATH=/nonexistent .venv/bin/ccparse parse \
  '/root/creditcard/documents/2026-07-02 Cal Cal Credit Card Statement - 2026-07.pdf' \
  --output-dir "$task_tmp/cal-run-1" \
  --cache-dir "$task_tmp/cal-cache-1" \
  --strict
env PATH=/nonexistent .venv/bin/ccparse parse \
  '/root/creditcard/documents/2026-07-10 First International Bank of Israel First International Bank Credit Card Statement - 2026-07.pdf' \
  --output-dir "$task_tmp/fibi-run-1" \
  --cache-dir "$task_tmp/fibi-cache-1" \
  --strict
env PATH=/nonexistent .venv/bin/ccparse parse \
  '/root/creditcard/documents/2026-07-02 Cal Cal Credit Card Statement - 2026-07.pdf' \
  --output-dir "$task_tmp/cal-run-2" \
  --cache-dir "$task_tmp/cal-cache-2" \
  --strict
env PATH=/nonexistent .venv/bin/ccparse parse \
  '/root/creditcard/documents/2026-07-10 First International Bank of Israel First International Bank Credit Card Statement - 2026-07.pdf' \
  --output-dir "$task_tmp/fibi-run-2" \
  --cache-dir "$task_tmp/fibi-cache-2" \
  --strict
cmp "$task_tmp/cal-run-1/results.json" "$task_tmp/cal-run-2/results.json"
cmp "$task_tmp/cal-run-1/transactions.csv" "$task_tmp/cal-run-2/transactions.csv"
cmp "$task_tmp/fibi-run-1/results.json" "$task_tmp/fibi-run-2/results.json"
cmp "$task_tmp/fibi-run-1/transactions.csv" "$task_tmp/fibi-run-2/transactions.csv"
```

Expected: every parse reports `reconciled`; every `cmp` exits 0; all four cache
directories contain no OCR entries.

- [ ] **Step 5: Check the exact semantic and FX acceptance values locally**

Read the two first-run JSON files with a short local-only assertion script. It
must verify:

- 12 and 34 transactions;
- printed/calculated totals of ILS 1,742.18, ILS 3,569.03, and ILS 9,901.54;
- the 14 corrected descriptions from the issue report;
- the two recovered conversion dates;
- no transaction ambiguities;
- every unambiguously printed July exchange rate and fee is populated;
- continuation-detail rows include fee percentage, gross fee, discount, and
  exact derived net fee;
- typed fee-column rows include printed applied net fee;
- every populated FX value has non-empty evidence;
- JSON and CSV agree on every structured FX value.

Do not save the assertion script or its financial output in the repository.

- [ ] **Step 6: Remove only the generated temporary acceptance data**

Resolve and print the exact `$task_tmp` path, then unlink only files beneath that
validated `ccparser-fx-acceptance-*` directory and remove its now-empty
directories. Confirm `git status --short --untracked-files=all` shows no private
PDF copy, output, or cache.

- [ ] **Step 7: Run final gates, review the diff, and commit documentation**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
git diff --check
git status --short --untracked-files=all
git add README.md
git commit -m "docs: document structured FX output schema"
```

Expected: required gates pass; only intended source, tests, docs, and plan/spec
history are tracked; private inputs and generated financial outputs remain
untracked and absent from the commit.
