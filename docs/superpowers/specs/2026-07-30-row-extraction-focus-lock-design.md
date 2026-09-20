# Row-Extraction Focus Lock Design

**Status:** Implemented on 2026-07-30 and binding.

## Purpose

Keep the transaction-row program focused on comparing and improving the four approved
field-extraction approaches. Prevent completed comparison-controller and provenance work from
being mistaken for the next active task.

This design is subordinate to repository-wide safety and development requirements, but it is
the binding scope authority for row-extraction experiment work.

## North-Star Outcome

Work counts as progress only when it produces at least one of:

- a runnable implementation of one of the four approved extraction approaches;
- a named extraction-metric measurement or delta;
- a supported or falsified extraction hypothesis; or
- a quantified extraction error category that determines the next experiment.

Framework code, orchestration, provenance, cleaner receipts, and stronger workflow machinery do
not count as extraction progress.

## Allowed Work

An approved row-extraction objective may combine the necessary steps below:

1. change per-row OCR, deterministic extraction, the lightweight text model, or the lightweight
   image/image-plus-text model;
2. run or score a named field-extraction metric on the frozen document-disjoint development or
   validation data; or
3. analyze a measured extraction error, including supervision eligibility, overlapping evidence
   ownership, merchant recognition, omissions, hallucinations, calibration, or abstention.

Shared evaluation work is allowed only when an existing local measurement cannot run without the
smallest immediate change. It must not create a reusable controller, schema family, CLI, receipt
chain, or workflow subsystem.

## Frozen Work

Preserve but do not continue:

- locked-comparison controller or CLI architecture;
- provenance envelopes and handoff re-freezing;
- receipts, replay prevention, attestations, and path/inode/cache-independence machinery;
- marker-first or other locked-input projection features;
- cascade execution and locked-test orchestration;
- private-corpus controller redesign; and
- production integration.

Existing branches and artifacts remain read-only historical evidence. They are not unfinished
tasks. An exception requires a direct user approval followed by a committed charter amendment;
approval may not be inferred from a general request to continue the experiment program.

## Approved Production-Acceptance Exception

On 2026-08-22, the user explicitly approved one bounded exception needed to complete the first
stable release: correct the private-corpus gate's concurrent directory-descriptor enumeration
race. The exception is limited to a focused regression test and the smallest implementation
change in `tests/test_corpus_gate.py` and `src/ccparser/corpus_gate.py`.

The fix must preserve the gate's existing CLI, protected inputs, pinning, attestation, isolation,
and acceptance semantics. It may only make directory-entry validation deterministic when several
OCR workers validate the same sealed runtime concurrently. It must pass the tracked verification
suite and a fresh formal private-corpus `verify` run before release publication.

This exception is production release acceptance work. It does not reactivate row-extraction
experiments, authorize controller redesign, or count as extraction progress.

## Task-level authorization amendment — 2026-09-20

The user explicitly requested full-task execution without approval for each
small subtask. [AGENTS.md](../../../AGENTS.md#task-level-authorization-and-persistence)
is the controlling authorization policy. It supersedes the former per-subtask
contract, one-output-per-subtask and automatic Metric-or-Stop rules.

An approved extraction objective may include the smallest required design,
input adapter, source preparation, human review handoff, generation, scoring,
verification and reporting. Record the task contract once; its subtasks inherit
it. Commit the objective's initial experimental authority before new data access;
do not require a new authority commit at every routine milestone. Keep one
active objective and continue necessary work autonomously.

Evaluate metric progress at objective completion. Preparation may be intermediate
work without a score. If human labels are required, complete independent work,
record AWAITING_HUMAN_REVIEW and resume on receipt of the answers without new
approval. Do not replace human decisions with agent guesses. Negative results
are final results, not permission to tune the same evaluation sample.

The frozen-work restrictions above remain in force. Protected held-out access,
accepted-gold/baseline changes, production integration and infrastructure redesign
still require their separate explicit authorization. No framework, receipt chain,
new CLI or corpus-controller redesign is part of this amendment.

## Enforcement in the Repository

- `AGENTS.md` contains the high-authority program rule.
- The transaction-row charter incorporates this focus lock and defers to the live program status.
- `docs/experiments/row-extraction-program-status.md` records the sole active phase, exact frozen
  branch heads, measured outcomes, and next allowed task.
- Historical comparison plans and runbooks carry prominent frozen banners.

No automated scope hook is added. Semantic scope cannot be reliably enforced by changed-file
rules, and building such a hook would repeat the same infrastructure drift.
