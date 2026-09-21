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

**Merchant field**: All printed text in a transaction's merchant/description position,
including reference codes, prefixes, URLs, location text and owned continuation lines.
It represents the statement's field value, not a cleaned or inferred business identity.

**Merchant attribution**: The association of the complete merchant field with its source
transaction, without borrowing text from another transaction or inventing unsupported text.

**Merchant-bearing evidence**: The ordered, source-grounded text occupying the merchant field
on the primary row and its owned continuation rows.

**Continuation ownership**: The source-grounded association of a continuation row with its
transaction, retained through a chain even when adjacency is established by the preceding
continuation row. Owning a row does not make all of its text merchant-bearing evidence.

**Ancillary transaction metadata**: Information printed in separate category, location,
reference or explanatory fields outside the merchant field. Text inside the merchant field
remains merchant text regardless of its apparent meaning.

**Context tier**: One predeclared, nested amount of source evidence shown to the same extraction
process so that the effect of additional context can be measured without changing the task,
prompt, model, or decision rules.

**Reference transaction**: An independently source-adjudicated transaction and its exact
merchant-bearing evidence, created without current gold, accepted parser output, or experiment
predictions.
