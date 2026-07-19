# Original Amount Word-Subset Design

## Scope

Recover an original amount only when a malformed `ORIGINAL_AMOUNT` cell has exact digital
Word provenance for one strict amount, one supported currency, and residual text already
represented by the same row's single proven `DESCRIPTION` cell. All other malformed cells
remain fatal ambiguities.

The current corpus has two qualifying rows. A shadow normalization promotes two exact groups
and one document to reconciled. Seven cells whose residual merchant Word is not represented in
the description, plus one unknown-currency cell, are intentionally unchanged.

## Design

Add a normalization helper that first uses the existing whole-cell monetary parser. If that
fails, the helper may consider a Word subset only when:

- the row has exactly one original-amount column and one description column;
- the original cell contains only digital Words;
- exactly one Word is a strict amount and exactly one distinct Word is a supported currency;
- those two Words are adjacent and form exactly one successful monetary parse;
- every excluded Word is nonnumeric, lies on the description-facing side of the money Words,
  and is already contained in the same row's description cell.

The transaction retains the original cell as evidence. Its description is unchanged because
the excluded text is already represented there. Candidate selection is ordered by geometry and
text for deterministic output.

## Rejections

Do not recover missing or unknown currencies, multiple amount/currency candidates, OCR/digital
mixtures, nonduplicated residue, numeric residue, residue on the wrong side, multiple semantic
columns, or invalid sign/grouping/decimal forms. Do not use filenames, issuer identity, totals,
or amount equality.

## Tests

The positive matrix covers symbol and alphabetic-code currencies with signed and unsigned
amounts. Negative cases cover every rejection above. Assertions cover amount/currency,
unchanged description, unchanged complete evidence, deterministic repeated normalization, and
exact reconciliation.

## Alternatives deferred

An explicit cross-column merchant-residue merge could recover seven additional cells, but it
requires separate description-order semantics. Retuning table boundaries is broader and risks
unrelated schemas. Permissive substring parsing is prohibited.
