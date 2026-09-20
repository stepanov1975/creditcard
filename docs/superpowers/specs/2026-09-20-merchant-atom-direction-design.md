# Merchant Within-Atom Directional Signatures

**Status:** APPROVED — preparing the fixed two-case measurement.

The user's “proceed” approves the whole-atom witness report's recommendation to
examine character ordering inside the selected atoms before proposing a correction.

```text
Scope answer: YES — quantifies within-atom ordering signatures in two fixed merchant errors
Experiment: row-profiles
Extraction hypothesis: At least one case contains an atom absent forward but present reversed in the non-whitespace reference
Measurement: forward-only, reverse-only, both, neither and unresolved atom counts with directional profiles
Fixed inputs: two saved order-only digital training cases, their seven selected atoms, v3 references and prior scores/results
Smallest allowed files: docs/superpowers/specs/2026-09-20-merchant-atom-direction-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-atom-direction-report.md; artifacts/merchant-atom-direction-v1/**
Required output: quantified directional signatures and a supported, falsified or unresolved hypothesis
Stop condition: stop after this two-case measurement or reproduction failure; do not generate corrections, expand selection, edit labels or open source documents
```

## Fixed measurement

Reproduce all 72 saved scores, three previous digital classifications and the
two whole-atom witness results. Reuse the selected source occurrences and their
recorded order. The public diagnostic seam is
`classify_atom_direction(text, reference)`. Project text and reference with NFC
followed by removal of Unicode whitespace, retaining every other code point.

For each nonempty atom projection, count overlapping exact substring occurrences
in the reference, first forward and then with its code points reversed. Classify
eligible atoms as `forward_only`, `reverse_only`, `both` or `neither` according to
nonzero counts. Empty projections have their own category and remain counted.
Record palindromic eligible projections separately: they cannot distinguish order.
Occurrence counts do not assign reference spans or require disjoint occurrences.

Report reversal as unresolved if the atom or reference projection is not NFC,
if the atom contains Unicode marks (`M*`) or format controls (`Cf`), or if its
reversal is not NFC. Preserve forward counts even when reversal is unresolved.
These exclusions keep code-point reversal from masquerading as a safe Unicode
text transformation. This query is not the Unicode Bidirectional Algorithm.

Characterize each atom using Unicode bidi classes: `L` is LTR, `R`/`AL` are RTL;
ignore other classes when counting transitions between strong directions. Record
`ltr_only`, `rtl_only`, `mixed_strong` or `no_strong`, plus strong-direction
transitions and Unicode decimal-digit (`Nd`), punctuation (`P*`), mark (`M*`) and
format-control (`Cf`) occurrence counts. These are descriptive signatures, not
rendering-order decisions. Report category counts, cases with reverse-only atoms,
and category-by-direction counts without private identities or text.

The hypothesis is supported if at least one case has a resolved reverse-only
atom; falsified if no case has one and every nonempty atom resolves; otherwise
unresolved. Substring containment alone does not prove complete merchant coverage,
correct ownership, a general reversal rule or correctness of a human reference.
Do not concatenate transformed atoms, search transformed combinations, save
corrected predictions or score a new candidate.

## Verification and boundary

Commit this authority before reading the fixed private inputs for the new query.
Use invented-input red/green tests at the declared diagnostic seam, including
overlapping occurrences, repeated text, palindrome/empty cases, mixed directions,
normalization and mark/control exclusions. Independently verify substring counts
with escaped lookahead matching and check all aggregate counts. Existing saved
artifacts and the frozen extractor checkout remain unchanged.

Keep scripts and results only in ignored `artifacts/merchant-atom-direction-v1/`.
Run the four repository verification gates before tracked commits. Stop after
this measurement or reproduction failure. No follow-on diagnostic, candidate,
new sources, extraction/OCR/models, label edits, wider selection, held-out access,
reusable infrastructure or production integration is active.
