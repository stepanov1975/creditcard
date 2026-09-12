# Residual Merchant Error Analysis

**Status:** Approved by the user's “proceed” on 2026-09-12 following the concrete
recommendation to analyze the remaining 11 failures using existing merchant
regions. Commit this authority before private measurement.

```text
Scope answer: YES — quantifies residual merchant text, selection, and ownership errors on the fixed seed
Experiment: row-profiles
Extraction hypothesis: At least one omission or ambiguous-output case retains strongly located alphabetic merchant evidence or a strongly supported proposal that the single-output contract does not expose
Measurement: retained-evidence support, proposal ownership conflicts, omission gates, text-error signatures, and character error rate
Fixed inputs: 11 non-exact pre-filter cases, 24 unchanged references, 135 saved row/prediction records, candidate alignment, and selected source-page geometry
Smallest allowed files: docs/superpowers/specs/2026-09-12-merchant-residual-errors-design.md; docs/superpowers/plans/2026-09-12-merchant-residual-errors.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-residual-errors-report.md; artifacts/merchant-residual-errors-v1/**
Required output: quantified residual error categories and supported or falsified retained-evidence hypothesis
Stop condition: stop after the fixed 11-case analysis; no new prediction, label change, alternate extraction, or support subsystem
```

## Fixed input and unchanged outputs

Select the 11 non-exact `before_future_billing_filter` cases from the completed
pre-filter comparison: nine text mismatches, one omission, and one ambiguous
output. First reproduce all 24 saved scores from their unchanged proposals and
candidate alignment. The 13 exact cases are controls for score reproduction,
not extra cases in the error analysis. Save the fixed selection privately.

Use the 127 original rows plus eight diagnostic rows, the 135 saved predictions,
and existing human transaction/merchant regions. Read only identity, dimensions,
and rotation from the six selected local source copies as needed. Existing rows
use their native-point geometry; the eight new diagnostic rows use display-point
geometry. Do not render, extract text, OCR, rerun classification/discovery, or
read unrelated source pages or held-out records.

For each case, recover every saved description proposal owned by its aligned row,
including proposals emitted by continuation rows. Reproduce the saved output list
without combining, selecting, repairing, or dropping proposals. Preserve original
and candidate alignment, prediction decisions, merchant scores, and labels.

## Geometry and ownership measurements

Reuse the existing strong-support rule: a finite positive-area atom box has its
center in a human region and at least half its area inside any one region.
Zero positive-area intersection is outside; partial support is boundary-sensitive;
invalid geometry or another source page is unusable. Measure these categories
against both the merchant region and its transaction region.

Count selected atom occurrences and their support per proposal and case. Record
whether each proposal is wholly strongly supported by the merchant region,
whether it exactly equals the saved merchant reference on its own, whether its
source row is the owner or a continuation, and whether multiple proposals share
identical positioned observations. Individual-proposal equality is a diagnostic;
it does not turn an ambiguous output list into a successful prediction.

Scan saved atoms on the same selected page to count strongly located merchant
records in the owner row, contributing rows, and other rows. Separate selected
from unselected records and count alphabetic evidence. Preserve duplicate records
and separately report overlap between proposals; unselected records are possible
missing evidence, not confirmed missing words.

For the omission, report its saved predicted type and known rejection/probe gate,
and whether strongly supported alphabetic evidence exists in the owner row or
elsewhere on the page. For the ambiguous case, report proposal counts, individually
exact proposals, wholly supported proposals, and proposals containing evidence
outside the merchant or transaction region. Do not infer a recognition failure
from a missing output or infer incorrect ownership from boundary overlap alone.

Disjoint case categories use this precedence: unusable selected geometry;
omission with/without strongly located alphabetic evidence; multiple owned
proposals; selected evidence outside the transaction; selected evidence outside
the merchant only; boundary-sensitive selected evidence; and single-output text
mismatch with all selected evidence strongly supported. Also report overlapping
flags so that precedence does not conceal evidence conflicts in ambiguous cases.

The retained-evidence hypothesis is supported if either the omission has at least
one strongly located alphabetic atom, or the ambiguous output has at least one
nonempty proposal wholly strongly supported by the merchant region. Falsify it
only with complete comparable geometry and neither observation. Otherwise report
unresolved geometry. Geometric support does not certify the reference or prove
that the retained text is semantically correct.

## Text measurements

For the nine single-output mismatches, reuse NFC/whitespace normalization,
word-order, spacing-only, and format-control-only signatures plus Levenshtein
code-point edits. Add two explicitly diagnostic signatures: NFKC/whitespace-only
equality, and equality after deleting Unicode punctuation characters and
collapsing whitespace. Require nonempty transformed strings. Apply neither
transformation to predictions or the official scorer.

Report edit totals, reference code points, and micro character error rate using
`Decimal`, overall and by digital/OCR slice. Report signature counts as potentially
overlapping observations. Fully supported mismatching atoms may reflect source
recognition, ordering, serialization, or reference transcription; do not declare
an OCR or label error without evidence distinguishing those explanations.

## Implementation and stop boundary

A disposable local analysis and invented-input tests may write only under ignored
`artifacts/merchant-residual-errors-v1/`. Reuse existing geometry, renderer, scorer,
and text diagnostics. Test new category precedence, empty-output handling,
ambiguous-proposal evidence, and added signature boundaries before implementation.
No shared schema family, controller, CLI, annotation UI, workflow, or infrastructure
is authorized.

Keep all private text, identities, coordinates, and financial values out of tool
output and Git. Report only aggregate counts and existing general rule names.
Check original inputs unchanged and run required repository gates before commits.
Stop after this one analysis. No candidate generation, tuning, rescoring with a
changed rule, label correction, new labels, expansion, gold promotion,
validation/test access, or production integration is authorized. The measured
merchant score remains 13/24 throughout this diagnostic.
