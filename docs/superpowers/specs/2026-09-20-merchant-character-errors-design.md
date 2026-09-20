# Remaining Digital Merchant Character-Error Measurement

**Status:** APPROVED — preparing the fixed three-case classification.

The user's “proceed” approves the completed punctuation-spacing report's
recommendation to classify character-order versus missing/extra-character errors.

```text
Scope answer: YES — quantifies character-order and character-inventory signatures in the remaining digital merchant errors
Experiment: row-profiles
Extraction hypothesis: At least one of the three remaining digital mismatches has identical non-whitespace character inventory but a different sequence
Measurement: order-only, missing-only, extra-only and mixed-inventory case counts; missing/extra occurrences and subsequence signatures
Fixed inputs: three remaining digital errors, 24 v3 references, 72 saved scores, punctuation-spacing outputs and recorded source atoms/order
Smallest allowed files: docs/superpowers/specs/2026-09-20-merchant-character-errors-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-character-errors-report.md; artifacts/merchant-character-errors-v1/**
Required output: quantified character-error categories and a supported or falsified order-only hypothesis
Stop condition: stop after the three-case classification or saved-result reproduction failure; no candidate, source extraction, label change or broader selection
```

## Fixed selection and prerequisite

Reproduce all 72 saved scores: original v3 and geometry spacing each have 17/24
exact matches, and punctuation spacing has 19/24. All retain 24 aligned unique
outputs. Select only the three digital cases still non-exact in punctuation
spacing: one partial-text case and two other mismatches. The two OCR errors are
outside this measurement. Reconstruct selected saved strings from original row
evidence, frozen ownership/order and recorded separator decisions.

No source PDFs, images, new extraction, OCR, models or changed predictions are
authorized. Existing artifacts and the frozen checkout remain unchanged. No
human review, reference update, candidate, wider sample or held-out access.

## Predeclared comparison

The disposable diagnostic seam is `classify_characters(prediction, reference)`.
Normalize each complete string to NFC and remove Unicode whitespace. Preserve
case, punctuation, digits, combining marks and format-control characters. These
are code-point observations, not grapheme counts or a new scoring convention.

Compute multiset differences with multiplicity and assign exactly one category:

- `non_whitespace_equal`: normalized non-whitespace sequences are identical.
- `order_only_signature`: sequences differ but code-point multisets are equal.
- `missing_only_inventory`: reference has deficits, with no predicted surplus.
- `extra_only_inventory`: prediction has surplus, with no reference deficit.
- `mixed_inventory`: both deficits and surpluses exist.

Count missing and extra occurrences in total and by Unicode major category
(Letter, Mark, Number, Punctuation, Symbol, Separator, Other). Keep characters,
strings and case identities private. Report case counts by category and original
score class. Independently test whether the prediction is a subsequence of the
reference, and vice versa, using the same normalized non-whitespace sequences.
An inventory deficit alone does not prove the existing characters are ordered
correctly; subsequence membership adds that narrower observation. A mixed
inventory does not prove substitution rather than separate omissions/additions.

Support the hypothesis if at least one selected case has `order_only_signature`;
otherwise falsify it after complete classification. Equal inventory only shows
compatibility with a permutation; it neither identifies a usable ordering rule
nor locates the problem within/across atoms. Missing characters refer to the
selected output, not all available source evidence, and do not establish a
source-extraction failure or certify the reference independently.

## Verification and stop

Commit authority before private measurement. Use invented-input red/green tests
at the diagnostic seam, including repeated characters, order, deficits/surpluses,
NFC, Unicode whitespace, retained format controls and subsequence distinctions.
Independently verify character counts, subsequence signatures, saved scores,
membership and aggregate denominators. Keep private scripts and results only
under ignored `artifacts/merchant-character-errors-v1/`; publish aggregates only.
Run all four repository gates before tracked commits.

Stop after the classification or a saved-result reproduction failure. No second
diagnostic, repair rule, threshold tuning, new source access, label change,
selection expansion, reusable controller/schema/CLI or production integration
is active. The candidate's 19/24 score is unchanged by this measurement.
