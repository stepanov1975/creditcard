# Merchant Primary/Continuation Assembly Experiment

**Status:** Complete — STOP. Approved by the user's “proceed” on 2026-09-12 following
the concrete recommendation in the completed residual-error analysis. Authority
was committed at `4b9a14a` before candidate generation; see the
[result report](../../experiments/row-extraction-merchant-continuation-assembly-report.md).

```text
Scope answer: YES — changes merchant assembly from explicitly owned primary and continuation evidence
Experiment: row-profiles
Extraction hypothesis: Assembling eligible primary and continuation descriptions in page reading order increases exact merchant matches above 13/24 with no losses
Measurement: exact merchant match, unique-output coverage, and paired gains/losses
Fixed inputs: 135 saved predictions, 127 original plus eight diagnostic training rows, 24 unchanged references, and candidate alignment
Smallest allowed files: docs/superpowers/specs/2026-09-12-merchant-continuation-assembly-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-continuation-assembly-report.md; artifacts/merchant-continuation-assembly-v1/**
Required output: fixed-candidate metric delta and supported or falsified assembly hypothesis
Stop condition: stop after one candidate comparison; no tuning, label changes, new extraction, or support subsystem
```

## One fixed candidate

Start from the 135 saved pre-filter diagnostic predictions and their 135 rows.
Group description proposals by their existing explicit owner, falling back to
the source row only for proposals without an owner. Preserve empty groups and
single-proposal outputs exactly.

Assemble a multiple-proposal group only when it has exactly one description from
its primary-transaction owner and one description from each of one or more
continuation rows. Each continuation must explicitly name that same primary
owner. Do not infer transitive ownership, reclassify a row, or find a new owner.
Require all contributing rows to have the same document, page, and render version
as the owner, so incomparable coordinate conventions are not mixed.

Require nonempty rendered descriptions and finite positive-area selected atom
geometry. If two proposals share a positioned observation (text, box, source,
confidence), leave the group unchanged; do not deduplicate evidence. Do not add
unselected atoms or edit source text. Input evidence must match its saved row.

For eligible groups, flatten all selected atom occurrences and apply the existing
fixed geometry/Unicode directional-run reading order across them. Use temporary
occurrence indices only to disambiguate source-local atom IDs. Render the ordered
source text with the existing single-space joining convention. Retain a private
ordered list of original row/atom references for checking complete preservation.
Invalid geometry or other ineligibility preserves the original output list.

This candidate changes the diagnostic merchant assembly, not the saved prediction
records, classification, ownership, decisions, reasons, or billing inclusion.
Future-billing diagnostics remain ignored for billing. No OCR, source reading,
discovery, model call, alternate reading order, or recognition change is allowed.

## Measurement

Generate the candidate for every saved owner group before opening references,
reference regions, or case-level prior diagnostics. The extractor must accept
only saved rows and predictions. This avoids selecting a rule or eligible groups
using the reviewed merchant text or human geometry.

Then reproduce all 24 saved `before_future_billing_filter` scores and outputs,
including 13 exact matches, 22 unique outputs, one omission, and one ambiguous
output. Score the fixed candidate with the same NFC/whitespace scorer and the
same candidate alignment. Keep all 24 references and the six training-page modes.

Report exact merchant match and unique-output coverage, paired gains/losses,
score-category transitions, digital/OCR slices, and counts of assembled versus
unchanged owner groups. The hypothesis is supported only if exact matches exceed
13/24 and losses are zero. A coverage gain alone does not support it.

The 24 labels remain a small single-reviewer training calibration set. Do not
claim independently verified gold, held-out performance, or production acceptance.

## Implementation and completion checklist

Use the existing `codex/merchant-gold-seed` branch. A disposable private assembly
helper, invented-input tests, and one comparison script may write only under
ignored `artifacts/merchant-continuation-assembly-v1/`. Reuse frozen contracts,
renderer, reading-order helper, and scorer. Do not change frozen arms or create
a shared schema, controller, CLI, workflow, or production integration.

- [x] Commit this scope and sole active phase after required repository gates.
- [x] Observe focused failing tests for assembly, untouched singletons/omissions,
  explicit ownership, incompatible sources, overlaps, and invalid geometry; then
  implement the smallest helper and pass tests, Ruff, and strict mypy.
- [x] Generate one candidate without labels, compare all 24 fixed references,
  and independently check exact-match outcomes and evidence preservation.
- [x] Verify original inputs unchanged, pass repository gates, publish aggregate
  findings, mark the live phase STOP, and commit documentation.

All private text, identities, coordinates, and financial values remain local and
out of Git and tool output. Stop after this comparison regardless of the result.
No candidate tuning, reference repair, new labels, expansion, gold promotion,
validation/test access, or production integration is authorized.
