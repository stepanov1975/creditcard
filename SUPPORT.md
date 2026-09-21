# Support policy

## Supported in v0.1.x and v0.2.x

`ccparser` v0.1.x and v0.2.x support local Linux execution with Python 3.13 and
Tesseract Hebrew and English data. Its bounded domain is Hebrew and mixed
right-to-left credit-card statements.

The supported compatibility surface is the documented `ccparse` CLI, process
exit codes, JSON keys and meanings, and CSV columns and meanings. JSON
consumers must ignore unknown keys; CSV consumers must ignore trailing
columns. Python modules and call interfaces are implementation details.

## Conservative result contract

The parser does not promise every issuer or layout. Ambiguous, incomplete, or
contradictory evidence produces a conservative non-success status. A
`reconciled` result requires exact `Decimal` reconciliation and no unresolved
extraction ambiguity. Other platforms and general bank statements are
unsupported.

## Versioning

Patch releases preserve the supported CLI/output contracts of their minor version.
`0.2.0` adds a nullable JSON `merchant` field and a trailing CSV `merchant` column.
The merchant is the complete printed field, including owned continuation text,
not a cleaned business name. Existing JSON keys and CSV columns remain available;
merchant/description text can differ from v0.1.0 because field ownership was corrected.
Further additive capabilities or intentional contract revisions receive a new minor
version. Published tags are immutable; corrections receive a new patch version.

## Reporting defects

Use GitHub issues with synthetic reproductions. Never attach private
statements, outputs, caches, financial data, source identities, or protected
corpus artifacts.
