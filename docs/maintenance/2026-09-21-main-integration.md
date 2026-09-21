# Main integration and full-corpus evaluation

Status: IN_PROGRESS. The user requested integration of the accumulated work and
a full-corpus evaluation before further extractor improvements on 2026-09-21.

## Candidate and plan

The reviewed implementation is `ed31951e9e8e34846376bb7a9268e32fcb8738be`.
This task record and the live-status update freeze the evaluation candidate in
the next commit. Production code remains unchanged during evaluation.

1. Confirm branch ancestry, clean status, required checks and protected inputs.
   Local and remote main both point to `661c200`; the implementation branch is
   99 commits ahead with no divergence. Its production changes are limited to
   four parser modules and their synthetic tests; other changes preserve
   experiment evidence and consolidate project knowledge.
2. Run the candidate's private gate in `verify` mode, with independently pinned
   membership and accepted baseline, four workers, fresh output/cache directories,
   and the exact reviewed candidate SHA checked before and after execution.
   Require 104 retained/reconciled documents, five quarantined documents,
   deterministic output, baseline/toolchain parity and checked performance.
3. Quantify any failures using local output and aggregate reports. If the formal
   gate cannot finish, complete a full diagnostic parse where possible and label
   it separately. Keep document identities, contents and financial values private.
4. Merge to main only after corpus acceptance. If verification fails, preserve
   the candidate and complete a concrete evaluation report before requesting any
   necessary decision. Do not alter the accepted baseline or protected membership
   to make verification pass, and do not resume extractor tuning in this task.

The controller's saved corpus and inventory paths are stale. The retained local
inventory matches its independently protected SHA-256, and the accepted baseline
also matches its protected pin. The current local corpus has 104 retained PDFs
and five quarantine PDFs; the gate must independently check their identities.
The protected controller, accepted files and their pins remain unchanged.

## Interpretation

This is the repository acceptance check requested for integration, not a new
merchant-reference experiment. A balanced statement alone does not establish
complete merchant correctness. Earlier source-reviewed samples and predictions
remain frozen, human ownership reviews remain pending, and protected evaluation
labels are not opened. Any intentional output differences still need reviewed
baseline promotion under the existing acceptance policy before a merge can be
claimed corpus-verified.
