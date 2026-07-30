# Row-Extraction Focus Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make metric-or-stop extraction focus binding for future agents and freeze the completed
controller/provenance work without adding enforcement code.

**Architecture:** Put the normative rule in `AGENTS.md` and the approved charter, keep one tracked
live status record, and mark historical executable instructions as frozen. Enforcement is textual
and reviewable; no hook, controller, schema, CLI, or production behavior is added.

**Tech Stack:** Markdown, Git, repository link/path checks; no Python behavior change.

## Global Constraints

- Scope answer: YES — this prevents side work from displacing measured row-field extraction.
- No production `src/`, experiment implementation, private artifact, or controller-code changes.
- Do not delete historical work; preserve it read-only at its exact clean commits.
- Exactly one current phase and one next extraction task are recorded.
- Locked-test access remains forbidden and the test remains unopened.
- Do not add an automated enforcement script or test framework.

---

### Task 1: Install the binding focus authority and live status

**Files:**
- Create: `docs/superpowers/specs/2026-07-30-row-extraction-focus-lock-design.md`
- Create: `docs/superpowers/plans/2026-07-30-row-extraction-focus-lock.md`
- Modify: `AGENTS.md`
- Modify: `docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md`
- Create: `docs/experiments/row-extraction-program-status.md`

**Interfaces:**
- Consumes: the approved focus-lock design and clean branch heads.
- Produces: the mandatory task contract, metric-or-stop rule, one active phase, and exact frozen
  status for all four lanes.

- [ ] **Step 1: Add the program-specific rule to `AGENTS.md`**

  Require the exact task fields from the design, whitelist extraction/measurement/error-analysis
  work, freeze controller/provenance/projection work, require explicit user approval for an
  infrastructure exception, and state that repository private-corpus acceptance policy is not an
  experiment task.

- [ ] **Step 2: Amend the charter without redefining the four experiments**

  Add a focus-lock authority banner and binding section. Replace the loose `metric or experimental
  invariant` scope with a named extraction metric or error category, add the metric-or-stop rule,
  suspend Stages 4-6, and make the live status file authoritative for the active phase.

- [ ] **Step 3: Create the live status record**

  Record Round 1 as frozen, the held-out test as unopened, the five exact branch heads from the
  design audit, privacy-safe validation outcomes, the active supervision/merchant error-analysis
  phase, its allowed outputs, and all frozen side work.

  Use these audited heads and outcomes verbatim:

  - evaluation/controller `409dbcd7994ba1532fcbe8b165f12ebcc1c37cd4`;
  - OCR `9bc582c6876d4e2adba7e19cf2ba1968c5ab2625`: `VALIDATION_STOPPED`,
    `ocr_stage_validation_failed`, zero exact matches, with hallucinated or unsupported fields;
  - deterministic profiles `a2ed73aa58a4e4d8c76f918657d083fa922537d4`: `FROZEN_ELIGIBLE`,
    all validation rows abstained, zero exact matches;
  - text `d573b7f8d5239ca3ff92cbc7bf5475f5ced2ab0a`: `VALIDATION_STOPPED`,
    `no_text_candidate_met_validation_gate`, single-label supervision cannot represent
    overlapping evidence ownership, all abstained, zero exact matches;
  - vision `40f748395c07bb4d2da6658b92087be471681264`: `VALIDATION_STOPPED`,
    `no_pixel_gain`, zero eligible validation rows under the frozen contract, diagnostic output
    all abstained, zero exact matches; and
  - accepted baseline: zero exact matches with partial acceptance; page-OCR controls abstained.

- [ ] **Step 4: Verify authority and status content**

  Run:

  ```bash
  rg -n "Metric-or-Stop|marker-first|held-out test remains unopened|Active phase" \
    AGENTS.md \
    docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md \
    docs/experiments/row-extraction-program-status.md
  ```

  Expected: every required focus/freeze concept is present, with exactly one active phase in the
  status file.

- [ ] **Step 5: Run repository verification and commit the focus authority**

  Run the four required commands from `AGENTS.md`, then stage only the five files named in this
  task and commit with:

  ```text
  docs: lock row extraction work to measured progress
  ```

### Task 2: Freeze misleading executable instructions and verify the complete change

**Files:**
- Modify: `docs/superpowers/plans/2026-07-28-row-extraction-comparison-cascade.md`
- Modify: `docs/experiments/row-extraction-comparison-runbook.md`

**Interfaces:**
- Consumes: the focus authority and live status from Task 1.
- Produces: historical plan/runbook documents that cannot authorize controller continuation.

- [ ] **Step 1: Add a suspension banner to the comparison plan**

  State that unchecked tasks are historical, Task 6 and marker-first projection are not
  authorized, the controller commit is preserved read-only, and only a user-approved charter
  amendment can reactivate locked comparison work.

- [ ] **Step 2: Add a frozen banner to the runbook**

  State `DO NOT EXECUTE`, held-out unopened, missing test-only streams, and that commands are
  retained solely as historical reproduction documentation.

- [ ] **Step 3: Check links, placeholders, and scope**

  Run:

  ```bash
  test -f docs/superpowers/specs/2026-07-30-row-extraction-focus-lock-design.md
  test -f docs/experiments/row-extraction-program-status.md
  rg -n "FROZEN|SUSPENDED|DO NOT EXECUTE" \
    docs/superpowers/plans/2026-07-28-row-extraction-comparison-cascade.md \
    docs/experiments/row-extraction-comparison-runbook.md
  ! rg -n "T[B]D|T[O]DO|implement lat[e]r|fill i[n]" \
    docs/superpowers/specs/2026-07-30-row-extraction-focus-lock-design.md \
    docs/superpowers/plans/2026-07-30-row-extraction-focus-lock.md \
    docs/experiments/row-extraction-program-status.md
  git diff --check
  ```

  Expected: all commands exit zero and no production or experiment implementation file changed.

- [ ] **Step 4: Run repository-required verification**

  Run the four commands from `AGENTS.md`. The full suite must pass outside the sandbox if the five
  known native controller capability tests fail only because of sandbox restrictions.

- [ ] **Step 5: Commit the focus lock**

  Stage only the two historical documents named in this task and commit with:

  ```text
  docs: freeze obsolete row comparison instructions
  ```
