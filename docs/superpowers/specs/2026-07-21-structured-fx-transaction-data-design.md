# Structured FX Transaction Data Design

## Goal

Preserve unambiguously printed foreign-exchange rates, fee percentages, fee
amounts, fee discounts, and exactly derivable net fees as typed transaction data
with field-level source evidence. Keep billed amounts, transaction membership,
and reconciliation arithmetic unchanged.

This change completes Issue 4 from the 2026-07-20 real-statement validation
report. The merchant reconstruction, conversion-date recovery, and strict
semantic-completeness behavior delivered for Issues 1–3 are required
non-regressions.

## Scope and Constraints

- All financial and rate arithmetic uses `Decimal`.
- Extraction is driven by semantic headers, local cue text, geometry, and row
  structure. It must not branch on filenames, paths, hashes, dates, merchants,
  amounts, totals, issuers, cards, or accounts.
- A value is emitted only when one candidate is proven by its local evidence.
- Missing evidence leaves a field null without a diagnostic. Evidence that says
  a value exists but cannot be parsed uniquely leaves the field null and adds an
  actionable transaction ambiguity.
- Private PDFs, copied statement text beyond minimal synthetic fixtures, and
  generated financial output remain outside Git.
- Existing callers can keep constructing `Transaction` without FX data.

## Considered Approaches

### Typed nested FX details

Add one optional `foreign_exchange` object to `Transaction`. Store every value
with its own evidence and flatten the values and provenance into additive CSV
columns.

This is the selected approach. It keeps related fields together, makes printed
versus derived money explicit, and gives every value auditable provenance.

### Flat transaction fields

Add rate, fee, discount, net-fee, and evidence fields directly to `Transaction`.
This is mechanically simple but expands the transaction namespace and makes it
easy for evidence to become detached from the value it proves.

### Generic semantic annotations

Expose an open-ended collection of extracted key/value annotations. This would
be extensible, but downstream users would lose stable types and the CSV
projection would need ad hoc key conventions.

## Public Data Model

Add frozen, extra-forbidden models following the existing Pydantic conventions:

- `ExtractedDecimal`
  - `value: FiniteDecimal`
  - `evidence: tuple[EvidenceReference, ...]`, with at least one reference
- `ExtractedMoney`
  - `amount: FiniteDecimal`
  - `currency: str`
  - `evidence: tuple[EvidenceReference, ...]`, with at least one reference
  - `derivation: Literal["printed", "gross_fee_minus_discount"]`, defaulting
    to `"printed"`
- `ForeignExchangeDetails`
  - `exchange_rate: ExtractedDecimal | None`
  - `fee_percentage: ExtractedDecimal | None`
  - `gross_fee: ExtractedMoney | None`
  - `fee_discount: ExtractedMoney | None`
  - `net_fee: ExtractedMoney | None`

`Transaction` gains
`foreign_exchange: ForeignExchangeDetails | None = None`. A non-null details
object must contain at least one non-null value. Exchange rates must be positive;
fee percentages must be non-negative. Monetary values remain finite and retain
their printed currency.

`ForeignExchangeDetails` validates any
`gross_fee_minus_discount` net fee: both operands must be present, all three
currencies must match, and the net amount must equal exact Decimal subtraction.
A printed net fee retains the default `printed` derivation and does not require
gross or discount operands.

The exchange rate means billing-currency units per original-currency unit. The
transaction's existing `original_currency` and `billing_currency` fields define
the currency pair, so the nested object does not duplicate them.

When a source prints a fee followed by a separate discount, the printed fee is
`gross_fee`, the discount is `fee_discount`, and `net_fee` is the exact
`gross_fee - fee_discount` result. The derived net fee uses the union of both
operands' evidence and the derivation marker. When a table labels a single fee
that is applied to the billed transaction without separately identifying a
gross fee or discount, the printed value is `net_fee`; the other fee fields stay
null.

## Extraction Architecture

Normalization adds one focused FX extractor after billed/original value and
conversion-date extraction have established that a row is foreign currency.
The extractor returns optional `ForeignExchangeDetails`, evidence ownership
claims, and ordered diagnostic codes. It supports two issuer-neutral evidence
forms.

### Semantic table columns

An `exchange_rate` column supplies a rate candidate. A combined
conversion-date/rate cell is also eligible when the conversion date has already
claimed its date atoms; the remaining geometrically contiguous positive decimal
must be unique.

An `auxiliary_amount` column is eligible only when header evidence identifies it
as a fee or commission. Currency-adjacent glyphs identify the monetary run, so
detached footnote markers do not become part of the fee. A generic applied-fee
column populates `net_fee`.

### Bounded FX continuation blocks

Existing continuation detection already attaches explicit foreign-conversion
detail blocks to their base transaction. Within only those bounded rows, the FX
extractor recognizes semantic cues for:

- exchange or representative rate;
- foreign-currency fee percentage;
- charged fee amount;
- separately stated fee discount.

Candidate construction uses physical glyph order, line membership, and bounded
inter-glyph gaps to reconstruct decimals split across logical cells. It does not
globally remove spaces or concatenate arbitrary digits. Cue vocabularies may
cover supported languages but cannot identify an issuer or statement template.

If a block explicitly prints both fee and discount, the values populate
`gross_fee` and `fee_discount`, and exact subtraction produces `net_fee` only
when the currencies match and the result is non-negative.

## Evidence Ownership and Diagnostics

The semantic evidence ledger gains owners for exchange rate, fee percentage,
gross fee, fee discount, and net fee. Printed values claim the exact atoms used
to parse them. A derived net fee claims the union of its operands' atoms. Other
proven explanatory text in the bounded block remains ancillary.

The extractor emits these transaction ambiguities when an explicit cue cannot
produce exactly one valid value:

- `unparsed_exchange_rate_candidate`
- `unparsed_foreign_currency_fee_percentage_candidate`
- `unparsed_foreign_currency_fee_candidate`
- `unparsed_foreign_currency_fee_discount_candidate`
- `inconsistent_foreign_currency_fee_derivation`

As with existing transaction ambiguities, any of these diagnostics makes the
affected reconciliation group and strict parse unsuccessful even when monetary
totals match. A foreign transaction with no printed FX rate or fee cue does not
receive a diagnostic merely because the optional data is absent.

## JSON and CSV Schema

Canonical JSON includes `foreign_exchange`, using the nested models above.
Decimals remain canonical strings, and every printed or derived value includes
its supporting evidence references.

The CSV projection appends columns after the current schema. It retains the
existing transaction-level `source_page` and `source_bbox` columns and adds:

- `exchange_rate`, `exchange_rate_source_page`,
  `exchange_rate_source_bbox`
- `foreign_currency_fee_percentage`,
  `foreign_currency_fee_percentage_source_page`,
  `foreign_currency_fee_percentage_source_bbox`
- `gross_foreign_currency_fee`, `gross_foreign_currency_fee_currency`,
  `gross_foreign_currency_fee_source_page`,
  `gross_foreign_currency_fee_source_bbox`
- `foreign_currency_fee_discount`,
  `foreign_currency_fee_discount_currency`,
  `foreign_currency_fee_discount_source_page`,
  `foreign_currency_fee_discount_source_bbox`
- `net_foreign_currency_fee`, `net_foreign_currency_fee_currency`,
  `net_foreign_currency_fee_derivation`,
  `net_foreign_currency_fee_source_page`,
  `net_foreign_currency_fee_source_bbox`

Multiple evidence references use the existing deterministic semicolon-separated
page and bounding-box representation. Empty optional values serialize as empty
CSV cells.

This is an additive schema change: old `Transaction` constructors remain valid,
existing JSON keys keep their meanings, and existing CSV columns keep their
names and order. The README will document the new nullable JSON object and
appended columns and advise consumers to tolerate unknown object keys and
trailing CSV columns.

## Testing

Implementation follows red-green-refactor cycles with synthetic, minimized
evidence:

1. Model tests prove finite Decimal serialization, required per-value evidence,
   derivation validation, immutability, and legacy constructor compatibility.
2. Output tests prove deterministic nested JSON and appended CSV values and
   provenance.
3. Normalization tests cover a typed rate/fee table, a combined
   conversion-date/rate cell, a detached footnote next to a fee, a bounded
   narrative block with fragmented decimals, a printed fee percentage, and
   exact gross-minus-discount derivation.
4. Negative tests cover multiple candidates, invalid decimals, mismatched fee
   currencies, discount greater than gross, unrelated numbers outside bounded
   FX evidence, and foreign rows with no printed FX values.
5. Existing merchant, conversion-date, semantic-completeness, reconciliation,
   parser, and output tests remain unchanged and green.

## Acceptance Verification

- The available July statement fixtures parse in strict mode with the existing
  12 and 34 transaction counts and all three exact totals.
- Every unambiguously printed exchange rate and fee value in those foreign rows
  appears in JSON and CSV with field-level evidence.
- Separately printed fee discounts are retained, and net fees are derived only
  by exact Decimal subtraction from same-currency printed operands.
- The 14 merchant descriptions and two recovered conversion dates from Issues
  1–2 remain correct, and no unresolved semantic diagnostics remain.
- Parsing remains born-digital without requiring Tesseract, and two cold-cache
  runs remain byte-identical.
- Ruff formatting, Ruff lint, mypy, and the complete pytest suite pass.
