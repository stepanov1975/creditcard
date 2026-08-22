# Support policy

## Supported in v0.1.x

`ccparser` v0.1.x supports local Linux execution with Python 3.13 and
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

`0.1.x` preserves supported CLI/output contracts. `0.2.0` is reserved for
additive capabilities or intentional contract revisions. Published tags are
immutable; corrections receive a new patch version.

## Reporting defects

Use GitHub issues with synthetic reproductions. Never attach private
statements, outputs, caches, financial data, source identities, or protected
corpus artifacts.
