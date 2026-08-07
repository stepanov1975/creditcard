# Domain Context

This project extracts statement-faithful credit-card transactions whose financial identity and
merchant attribution can be verified directly against positioned source evidence.

## Language

**Accurate transaction**: A transaction whose core financial fields are exact and whose merchant
is attributed to the correct source transaction. Ancillary metadata is not required for this
status.

**Core financial fields**: The billed amount, billed currency, charge-or-credit kind, transaction
group, and every other printed financial value required to preserve the transaction's monetary
identity and exact reconciliation.

**Merchant attribution**: The association of a transaction with the merchant-bearing evidence
that belongs to that transaction, without borrowing text from another transaction or inventing
unsupported text.

**Merchant-bearing evidence**: The smallest ordered, source-grounded text span needed to identify
the merchant for a transaction, assembled across its primary row and owned continuation rows when
necessary.

**Ancillary transaction metadata**: Source-grounded category, location, processor/reference,
exchange-rate narrative, fee narrative, or other text that is not needed for core financial
identity or merchant attribution.

**Context tier**: One predeclared, nested amount of source evidence shown to the same extraction
process so that the effect of additional context can be measured without changing the task,
prompt, model, or decision rules.

**Reference transaction**: An independently source-adjudicated transaction and its exact
merchant-bearing evidence, created without current gold, accepted parser output, or experiment
predictions.
