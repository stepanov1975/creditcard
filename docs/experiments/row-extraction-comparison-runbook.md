# Locked row-extraction comparison runbook

This runbook executes the reviewed seven-result comparison exactly once. It is a
private diagnostic experiment, not a corpus-acceptance gate and not authority to
change production behavior.

## Preconditions

Use Python 3.13 and the repository virtual environment. Work only from the full
reviewed comparison and profile commit SHAs. Both checkouts must be clean,
including untracked files, and the profile package tree must match its separately
reviewed Git tree SHA.

Use only the final clean v2 producer revisions when authoring the descriptor:
pin the reviewed profile source checkout and package tree exactly, and preserve
each reviewed lane source commit in its manifest input. A superseded v1 handoff,
an abbreviated SHA, or an unreviewed regenerated publication is not an
acceptable substitute.

The private root must already exist outside the repository or be ignored by Git.
Keep the descriptor, locked identity sidecars, canonical manifest, workspace,
stdout, stderr, reports, and every derived artifact under that private root. Never
copy source names, document or row identifiers, field values, financial values,
dates, hashes, or private paths into public logs.

Set the following operator-provided variables to absolute normalized paths and
full lowercase SHAs. Do not reuse an earlier workspace.

```bash
set -euo pipefail

command -v git >/dev/null
command -v realpath >/dev/null
command -v test >/dev/null

COMPARISON_CHECKOUT="${COMPARISON_CHECKOUT:?absolute comparison checkout}"
COMPARISON_SHA="${COMPARISON_SHA:?full reviewed comparison SHA}"
PROFILES_CHECKOUT="${PROFILES_CHECKOUT:?absolute profiles checkout}"
PROFILES_SHA="${PROFILES_SHA:?full reviewed profiles SHA}"
PROFILES_TREE_SHA="${PROFILES_TREE_SHA:?reviewed profile package tree SHA}"
PRIVATE_ROOT="${PRIVATE_ROOT:?existing ignored or external private root}"
MANIFEST_DESCRIPTOR="${MANIFEST_DESCRIPTOR:?reviewed noncanonical descriptor}"
LOCKED_IDENTITY_SIDECARS="${LOCKED_IDENTITY_SIDECARS:?canonical locked sidecar descriptor}"
COMPARISON_MANIFEST="${COMPARISON_MANIFEST:?new canonical manifest output}"
COMPARISON_WORKSPACE="${COMPARISON_WORKSPACE:?new workspace declared by the manifest}"
PRIVATE_LOG_ROOT="${PRIVATE_LOG_ROOT:?new private log directory}"
PYTHON_BIN="${PYTHON_BIN:?Python 3.13 repository virtualenv interpreter}"

test "$(git -C "$COMPARISON_CHECKOUT" rev-parse HEAD)" = "$COMPARISON_SHA"
test "$(git -C "$PROFILES_CHECKOUT" rev-parse HEAD)" = "$PROFILES_SHA"
test -z "$(git -C "$COMPARISON_CHECKOUT" status --porcelain=v1 --untracked-files=all)"
test -z "$(git -C "$PROFILES_CHECKOUT" status --porcelain=v1 --untracked-files=all)"
test "$(git -C "$PROFILES_CHECKOUT" rev-parse \
  "$PROFILES_SHA:experiments/row_extraction/arms/profiles")" = "$PROFILES_TREE_SHA"

test -d "$PRIVATE_ROOT"
test ! -L "$PRIVATE_ROOT"
PRIVATE_ROOT_REAL="$(realpath -e -- "$PRIVATE_ROOT")"
test "$PRIVATE_ROOT" = "$PRIVATE_ROOT_REAL"

require_private_path() {
  local candidate
  candidate="$(realpath -m -- "$1")"
  case "$candidate" in
    "$PRIVATE_ROOT_REAL"/*) ;;
    *) return 1 ;;
  esac
}

require_private_path "$MANIFEST_DESCRIPTOR"
require_private_path "$LOCKED_IDENTITY_SIDECARS"
require_private_path "$COMPARISON_MANIFEST"
require_private_path "$COMPARISON_WORKSPACE"
require_private_path "$PRIVATE_LOG_ROOT"
test ! -e "$COMPARISON_MANIFEST"
test ! -e "$COMPARISON_WORKSPACE"
test ! -e "$PRIVATE_LOG_ROOT"
test -x "$PYTHON_BIN"
mkdir -m 700 "$PRIVATE_LOG_ROOT"
```

If the private root is inside the comparison checkout, additionally require:

```bash
git -C "$COMPARISON_CHECKOUT" check-ignore --quiet "$PRIVATE_ROOT"
```

Stop immediately if any check fails. Do not repair a failed run in place, record a
new baseline, alter pins, or reuse partially produced stage directories.

## 1. Author the canonical manifest

The reviewed descriptor declares deferred locked paths and identities. The
sidecar descriptor points only to canonical `ArtifactIdentity` records. This
preflight command cross-checks those records and writes the canonical controller
manifest without dereferencing locked rows, gold, accepted predictions, or OCR
reference content.

The descriptor must select the exact reviewed v2 adapters for all four lane
handoffs (`ocr_stop_v2`, `profiles_v2`, `text_stop_v2`, and `vision_stop_v2`).
Each raw provenance record must bind `labels/canonical-jsonl-v1`. The vision
handoff and its measurement must bind `runtime-lock/row-vision-runtime-v1`;
every other current comparison arm must bind
`row-runtime-manifest/row-runtime-manifest-v1`.

```bash
test ! -e "$COMPARISON_MANIFEST"

"$PYTHON_BIN" -m \
  experiments.row_extraction.comparison.cli_manifest_author author \
  --descriptor "$MANIFEST_DESCRIPTOR" \
  --locked-identity-sidecars "$LOCKED_IDENTITY_SIDECARS" \
  --output "$COMPARISON_MANIFEST" \
  >"$PRIVATE_LOG_ROOT/00-manifest-author.stdout.json" \
  2>"$PRIVATE_LOG_ROOT/00-manifest-author.stderr.txt"

test "$(git -C "$COMPARISON_CHECKOUT" rev-parse HEAD)" = "$COMPARISON_SHA"
test "$(git -C "$PROFILES_CHECKOUT" rev-parse HEAD)" = "$PROFILES_SHA"
test -z "$(git -C "$COMPARISON_CHECKOUT" status --porcelain=v1 --untracked-files=all)"
test -z "$(git -C "$PROFILES_CHECKOUT" status --porcelain=v1 --untracked-files=all)"
```

The only successful public-shaped payload is `{"complete":true}`. Any failure
prints only `ROW_COMPARISON_MANIFEST_AUTHOR_ERROR`; detailed inputs remain private.

## 2. Validate handoffs

This is the only first stage. It authenticates and normalizes all seven handoffs,
replays eligible validation factories, snapshots the pinned profile source, and
must not open deferred locked inputs.

```bash
test ! -e "$COMPARISON_WORKSPACE"

"$PYTHON_BIN" -m \
  experiments.row_extraction.comparison.cli validate-handoffs \
  --manifest "$COMPARISON_MANIFEST" \
  >"$PRIVATE_LOG_ROOT/01-validate-handoffs.stdout.json" \
  2>"$PRIVATE_LOG_ROOT/01-validate-handoffs.stderr.txt"
```

## 3. Freeze cascade validation

This stage uses validation evidence only and freezes the reviewed empty policy.
It must finish before locked access.

```bash
test -d "$COMPARISON_WORKSPACE/prelock"
test ! -e "$COMPARISON_WORKSPACE/prelock/policy"
test ! -e "$COMPARISON_WORKSPACE/locked"

"$PYTHON_BIN" -m \
  experiments.row_extraction.comparison.cli select-cascade-validation \
  --manifest "$COMPARISON_MANIFEST" \
  >"$PRIVATE_LOG_ROOT/02-select-cascade-validation.stdout.json" \
  2>"$PRIVATE_LOG_ROOT/02-select-cascade-validation.stderr.txt"
```

## 4. Run the locked comparison

This is the irreversible boundary. The controller writes the locked start receipt
before its first deferred read, then performs exactly eight serial extraction runs:
two repetitions for each of the accepted baseline, two page controls, and the sole
eligible profile lane. The two page controls perform exactly four independent page
preparations.

```bash
test -d "$COMPARISON_WORKSPACE/prelock/policy"
test ! -e "$COMPARISON_WORKSPACE/locked"

"$PYTHON_BIN" -m \
  experiments.row_extraction.comparison.cli compare-locked \
  --manifest "$COMPARISON_MANIFEST" \
  >"$PRIVATE_LOG_ROOT/03-compare-locked.stdout.json" \
  2>"$PRIVATE_LOG_ROOT/03-compare-locked.stderr.txt"
```

Do not invoke any lane-specific CLI and do not run an arm outside the controller.
Do not retry this command in the same workspace. A failure or interruption has no
verdict; preserve the private directory for review and start a newly reviewed
workspace only after the cause is understood.

## 5. Evaluate the frozen cascade

This stage derives the empty-policy cascade twice from already completed locked
prediction streams. It performs zero extraction runs and creates no recommendation
candidate.

```bash
test -f "$COMPARISON_WORKSPACE/locked/completion-receipt.json"
test ! -e "$COMPARISON_WORKSPACE/locked/cascade"

"$PYTHON_BIN" -m \
  experiments.row_extraction.comparison.cli evaluate-cascade-locked \
  --manifest "$COMPARISON_MANIFEST" \
  >"$PRIVATE_LOG_ROOT/04-evaluate-cascade-locked.stdout.json" \
  2>"$PRIVATE_LOG_ROOT/04-evaluate-cascade-locked.stderr.txt"
```

## 6. Produce the recommendation

Only `row-profiles` is eligible for this evidence gate. The stopped lanes, page
controls, and empty derived cascade cannot become recommendation candidates.

```bash
test -f "$COMPARISON_WORKSPACE/locked/cascade/completion-receipt.json"
test ! -e "$COMPARISON_WORKSPACE/locked/recommendation"

"$PYTHON_BIN" -m \
  experiments.row_extraction.comparison.cli recommend \
  --manifest "$COMPARISON_MANIFEST" \
  >"$PRIVATE_LOG_ROOT/05-recommend.stdout.json" \
  2>"$PRIVATE_LOG_ROOT/05-recommend.stderr.txt"

test -f "$COMPARISON_WORKSPACE/locked/recommendation/completion-receipt.json"
test "$(git -C "$COMPARISON_CHECKOUT" rev-parse HEAD)" = "$COMPARISON_SHA"
test "$(git -C "$PROFILES_CHECKOUT" rev-parse HEAD)" = "$PROFILES_SHA"
test -z "$(git -C "$COMPARISON_CHECKOUT" status --porcelain=v1 --untracked-files=all)"
test -z "$(git -C "$PROFILES_CHECKOUT" status --porcelain=v1 --untracked-files=all)"
```

Every controller command emits only a closed aggregate JSON object on success or a
stable aggregate error code on failure. Inspect detailed JSON, Markdown, and logs
only inside the private root. Never publish per-document output.

## Interpretation boundary

A completed sequence proves only that this pinned comparison executed according to
its controller contracts. It does not prove all-document or private-corpus
acceptance, baseline promotion, production readiness, or permission to merge. Any
parsing, extraction, semantic, reconciliation, OCR, JSON, or CSV change still needs
the repository's tracked gates and the separately pinned clean-commit private
corpus `verify` gate with deterministic repeated runs and
`performance_checked=true` before corpus acceptance can be claimed.
