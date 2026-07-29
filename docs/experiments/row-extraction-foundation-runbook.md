# Row-Extraction Foundation Runbook

**Status:** authoritative operational handoff for the four fixed-row extraction experiments.

**Scope check:** every command below directly prepares, validates, measures, or freezes
transaction-row recognition and field-extraction evidence. Stop if a proposed action does not.

The program has exactly four experiments:

1. per-row OCR;
2. deterministic row-type classification with type-specific extraction;
3. a lightweight OCR/text token model; and
4. a lightweight image or image-plus-text model.

The accepted pipeline, conditional page OCR, and forced page OCR are controls. The final
cascade is comparison infrastructure. None is a fifth experiment. Do not use this runbook to
change row detection, production `src/`, corpus-gate policy, controller/security architecture,
or any document-, merchant-, filename-, hash-, date-, amount-, total-, or corpus-specific rule.

## 1. Preconditions and private paths

Run only from a clean committed foundation revision in its isolated worktree. Use Python 3.13
and the repository virtual environment. Set these variables locally; never commit their values:

```bash
set -euo pipefail

export ROW_EXPERIMENT_PRIVATE="/absolute/ignored/row-extraction"
export ROW_EXPERIMENT_DOCUMENTS="/absolute/private/documents"
export ROW_EXPERIMENT_SPLIT_SEED="row-extraction-split-v1"
export ROW_PYTHON="/root/creditcard/.venv/bin/python"
export PYTHONPATH="$PWD/src:$PWD"
```

`ROW_EXPERIMENT_PRIVATE` must be a new ignored directory inside the worktree or a private
directory outside it. Documents may be outside the worktree. Commands fail if derived data is
unignored, path-aliased, symlinked, noncanonical, or already published.

Create the private root once:

```bash
mkdir -p "$ROW_EXPERIMENT_PRIVATE"
```

Normal command output is limited to stable status/count records. Redirect any diagnostic that
could name a source into the private root. Never paste filenames, row IDs, text, labels,
transactions, financial values, or artifact hashes into Git, public logs, or review messages.

## 2. Freeze document groups and splits before labels or results

Generate content-neutral 64-grid structure profiles, exact-match review candidates, and a
geometry-only SVG atlas:

```bash
"$ROW_PYTHON" -m experiments.row_extraction.foundation_admin profile-groups \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --documents "$ROW_EXPERIMENT_DOCUMENTS" \
  --cache-dir "$ROW_EXPERIMENT_PRIVATE/group-profile-cache" \
  --profiles-output "$ROW_EXPERIMENT_PRIVATE/group-profiles.jsonl" \
  --profiles-identity-output "$ROW_EXPERIMENT_PRIVATE/group-profiles.identity.json" \
  --proposals-output "$ROW_EXPERIMENT_PRIVATE/group-proposals.jsonl" \
  --proposals-identity-output "$ROW_EXPERIMENT_PRIVATE/group-proposals.identity.json" \
  --atlas-output "$ROW_EXPERIMENT_PRIVATE/group-atlas.svg" \
  --atlas-identity-output "$ROW_EXPERIMENT_PRIVATE/group-atlas.identity.json"
```

Two reviewers independently inspect only the profiles, proposals, and atlas. They must not see
filenames, PDF pixels, text, accepted predictions, labels, metrics, or proposed split
membership. Exact matches are candidates, not forced merges. Reviewers may reject geometric
false positives; visually equivalent or uncertain near-duplicate/revision/layout relations are
merged conservatively. Save both ignored draft decisions. Agreement produces one final
`ReviewedGrouping`; disagreement requires an ignored adjudication. The final record contains
two distinct opaque attestations over the same final partition digest.

Freeze the reviewed partitions with the predeclared seed:

```bash
"$ROW_PYTHON" -m experiments.row_extraction.foundation_admin freeze-groups \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --profiles "$ROW_EXPERIMENT_PRIVATE/group-profiles.jsonl" \
  --proposals "$ROW_EXPERIMENT_PRIVATE/group-proposals.jsonl" \
  --reviewed-grouping "$ROW_EXPERIMENT_PRIVATE/reviewed-groups.json" \
  --seed "$ROW_EXPERIMENT_SPLIT_SEED" \
  --groups-output "$ROW_EXPERIMENT_PRIVATE/document-groups.jsonl" \
  --groups-identity-output "$ROW_EXPERIMENT_PRIVATE/document-groups.identity.json" \
  --split-output "$ROW_EXPERIMENT_PRIVATE/splits.json" \
  --split-identity-output "$ROW_EXPERIMENT_PRIVATE/splits.identity.json"
```

Stop if any document is missing/duplicated, a duplicate/layout component spans partitions, or
train, validation, or locked test is empty. Group integrity takes precedence over the 60/20/20
target. Do not search seeds, break groups, or inspect labels/results to improve balance.

## 3. Prepare the fixed-row bundle and reviewed labels

Prepare rows, accepted-control predictions, exact unpadded reference crops, and identity
sidecars without changing row detection:

```bash
"$ROW_PYTHON" -m experiments.row_extraction.cli prepare \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --documents "$ROW_EXPERIMENT_DOCUMENTS" \
  --split-manifest "$ROW_EXPERIMENT_PRIVATE/splits.json" \
  --output-dir "$ROW_EXPERIMENT_PRIVATE/bundle"
```

Author `gold.jsonl` under annotation-handbook version
`row-extraction-annotations-v2`. Accepted output is only a proposal. Every label used for
training, validation, or locked scoring is reviewed against its source crop. A present field
has exact same-row atom support, a bounded source region, or both. Region-only support is used
for legible printing missing from frozen atoms. Ambiguity remains explicit and fieldless.

Predeclare a document-disjoint annotation-audit sample before model/configuration selection.
Two independent reviewers label that sample and adjudicate disagreements. Retain agreement by
row type and field privately. Optional `ocr-references.jsonl` contains only independently
legible verbatim regions; never derive it from accepted OCR.

Validate the complete labels:

```bash
"$ROW_PYTHON" -m experiments.row_extraction.cli validate \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --rows "$ROW_EXPERIMENT_PRIVATE/bundle/rows.jsonl" \
  --labels "$ROW_EXPERIMENT_PRIVATE/gold.jsonl" \
  --ocr-references "$ROW_EXPERIMENT_PRIVATE/ocr-references.jsonl"
```

If no reviewed OCR references exist, omit `--ocr-references`; CER/WER must remain unavailable.
Any label, handbook, row, group, or split change invalidates all downstream artifacts.

## 4. Freeze resource and runtime identities

Create ignored canonical `InventoryRoots` records for:

- an explicit empty accepted-control model root set;
- the exact Tesseract traineddata/model roots used by page controls; and
- the complete baseline dependency roots.

Then run:

```bash
"$ROW_PYTHON" -m experiments.row_extraction.cli prepare-inventory \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --roots "$ROW_EXPERIMENT_PRIVATE/empty-model-roots.json" \
  --output "$ROW_EXPERIMENT_PRIVATE/empty-model-inventory.json" \
  --identity-output "$ROW_EXPERIMENT_PRIVATE/empty-model-inventory.identity.json"

"$ROW_PYTHON" -m experiments.row_extraction.cli prepare-inventory \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --roots "$ROW_EXPERIMENT_PRIVATE/tesseract-model-roots.json" \
  --output "$ROW_EXPERIMENT_PRIVATE/tesseract-model-inventory.json" \
  --identity-output "$ROW_EXPERIMENT_PRIVATE/tesseract-model-inventory.identity.json"

"$ROW_PYTHON" -m experiments.row_extraction.cli prepare-inventory \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --roots "$ROW_EXPERIMENT_PRIVATE/baseline-dependency-roots.json" \
  --output "$ROW_EXPERIMENT_PRIVATE/baseline-dependency-inventory.json" \
  --identity-output "$ROW_EXPERIMENT_PRIVATE/baseline-dependency-inventory.identity.json"

"$ROW_PYTHON" -m experiments.row_extraction.foundation_admin prepare-runtime \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --dependency-inventory-identity \
  "$ROW_EXPERIMENT_PRIVATE/baseline-dependency-inventory.identity.json" \
  --output "$ROW_EXPERIMENT_PRIVATE/runtime-manifest.json" \
  --identity-output "$ROW_EXPERIMENT_PRIVATE/runtime-identity.json"
```

Run `verify-runtime` immediately before every fresh measured process, outside its timing
boundary:

```bash
"$ROW_PYTHON" -m experiments.row_extraction.foundation_admin verify-runtime \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --manifest "$ROW_EXPERIMENT_PRIVATE/runtime-manifest.json" \
  --identity "$ROW_EXPERIMENT_PRIVATE/runtime-identity.json" \
  --dependency-inventory-identity \
  "$ROW_EXPERIMENT_PRIVATE/baseline-dependency-inventory.identity.json"
```

Stop on any toolchain or inventory drift. Do not recapture merely to accept drift.

## 5. Prepare both page-control repeats

Run each command twice with distinct new cache, inventory, and preparation paths. Example
conditional run 1:

```bash
"$ROW_PYTHON" -m experiments.row_extraction.cli prepare-page-evidence \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --rows "$ROW_EXPERIMENT_PRIVATE/bundle/rows.jsonl" \
  --split validation \
  --mode conditional-page-ocr \
  --runtime-identity "$ROW_EXPERIMENT_PRIVATE/runtime-identity.json" \
  --cache-dir "$ROW_EXPERIMENT_PRIVATE/conditional-page-cache.run-1" \
  --output "$ROW_EXPERIMENT_PRIVATE/conditional-page-cache.run-1/page-evidence.jsonl" \
  --identity-output \
  "$ROW_EXPERIMENT_PRIVATE/conditional-page-cache.run-1/page-evidence.identity.json" \
  --model-inventory "$ROW_EXPERIMENT_PRIVATE/tesseract-model-inventory.json" \
  --dependency-inventory "$ROW_EXPERIMENT_PRIVATE/baseline-dependency-inventory.json" \
  --inventory-output "$ROW_EXPERIMENT_PRIVATE/conditional-page-prep.run-1.inventory.json" \
  --preparation-output "$ROW_EXPERIMENT_PRIVATE/conditional-page-prep.run-1.json"
```

Repeat with every `run-1` replaced by `run-2`. Repeat the pair with mode
`forced-page-ocr` and `conditional` replaced by `forced`. Each preparation record is consumed
by exactly one matching prediction run. A retry after failure may reuse it; a second successful
consumer must fail. Run-1/run-2 page-evidence bytes must be identical for each mode.

## 6. Run and score shared controls

For each of `accepted-baseline`, `conditional-page-ocr`, and `forced-page-ocr`, create two
`prepare-run-spec` records with identical rows/split/runtime/arm/model/dependency identities and
distinct new run caches, resource inventories, prediction outputs, and run outputs.

- Accepted uses `bundle/accepted_predictions.jsonl`, its identity sidecar, the empty model
  inventory, and no preparation record.
- Conditional/forced use the matching page-evidence stream/identity, Tesseract model inventory,
  and the corresponding run-1/run-2 preparation record.

Immediately before each run, verify runtime as in section 4. Then execute:

```bash
"$ROW_PYTHON" -m experiments.row_extraction.cli run-baseline \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --mode "$ROW_BASELINE_MODE" \
  --rows "$ROW_EXPERIMENT_PRIVATE/bundle/rows.jsonl" \
  --split validation \
  --baseline-input "$ROW_BASELINE_INPUT" \
  --baseline-identity "$ROW_BASELINE_IDENTITY" \
  --resource-spec "$ROW_RESOURCE_SPEC" \
  --predictions-output "$ROW_PREDICTIONS_OUTPUT" \
  --run-output "$ROW_RUN_OUTPUT" \
  ${ROW_PREPARATION_ARGUMENTS:-}
```

Set `ROW_PREPARATION_ARGUMENTS` to empty for accepted mode or to
`--preparation /absolute/private/preparation.json` for page modes. Do not use this shell
expansion with untrusted values. The CLI refuses locked test; the central comparison opens it
only after every configuration, calibrator, threshold, and lane disposition is frozen.

Require the two canonical prediction files for each mode to pass the shared
`assert_repeated_output` helper. Derive each report context from its completed run:

```bash
"$ROW_PYTHON" -m experiments.row_extraction.foundation_admin prepare-report-context \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --run "$ROW_RUN_OUTPUT" \
  --runtime-manifest "$ROW_EXPERIMENT_PRIVATE/runtime-manifest.json" \
  --runtime-identity "$ROW_EXPERIMENT_PRIVATE/runtime-identity.json" \
  --output "$ROW_REPORT_CONTEXT"

"$ROW_PYTHON" -m experiments.row_extraction.cli score \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --rows "$ROW_EXPERIMENT_PRIVATE/bundle/rows.jsonl" \
  --labels "$ROW_EXPERIMENT_PRIVATE/gold.jsonl" \
  --predictions "$ROW_PREDICTIONS_OUTPUT" \
  --ocr-references "$ROW_EXPERIMENT_PRIVATE/ocr-references.jsonl" \
  --context "$ROW_REPORT_CONTEXT" \
  --run "$ROW_RUN_OUTPUT" \
  --output "$ROW_REPORT_OUTPUT"
```

The accepted control's resources describe replay/validation/publication only, not production
extractor cost. Exclude it from resource Pareto claims. Page controls and all four experiments
use the end-to-end method basis with phase-separated preparation and fixed-row time.

## 7. Foundation freeze gate

Before branching any lane:

```bash
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/mypy experiments/row_extraction
/root/creditcard/.venv/bin/pytest -q
/root/creditcard/.venv/bin/pytest -q --ignore=tests/test_corpus_gate.py
git status --short --branch
git diff --name-only dee4b071ad65231da13825f2f7c74a488ca96c7c..HEAD -- src
```

The extraction suite, Ruff, and mypy must pass. The full suite may reproduce only the five
already established out-of-scope sandbox/controller failures; any new or changed failure
stops the freeze. `src` diff must be empty. Git status must contain no private artifact.

Record the full clean foundation SHA only in the ignored experiment manifest. Create all four
lane worktrees from that exact SHA. Each lane receives only train/validation artifacts and its
own new ignored caches/outputs. No lane may access locked-test rows, labels, predictions, or
metrics. A shared-contract need stops the lane and returns to the foundation branch.

## 8. Invalidations and stop conditions

Stop and regenerate downstream artifacts after any change to:

- source membership/content, reviewed groups, split seed/membership, fixed rows/bounds/bands;
- annotation handbook, labels, OCR references, evidence contracts, metrics, or error taxonomy;
- OCR/model configuration, runtime, inventories, worker count, calibration, or thresholds; or
- a lane's frozen artifact or cascade rule.

Never repair a failed gate with a special case, a new experiment, a template/issuer rule, a
seed search, test inspection, baseline rerecording, or an unreviewed label. A terminal stop is
recorded as a lane disposition and remains visible in the final comparison.
