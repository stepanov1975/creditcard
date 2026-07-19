# Original Amount Word-Subset Implementation Plan

1. Add test helpers that attach positioned digital or OCR Words to logical cells.
2. Add the positive normalization/reconciliation test and verify the expected RED failure.
3. Add parameterized negative tests for incomplete or ambiguous provenance and verify RED where
   the behavior is not already covered.
4. Implement the smallest typed helper in `normalize.py` and route original-amount parsing
   through it.
5. Run focused tests, Ruff, mypy, and the complete public suite.
6. Run the ignored private corpus sweep and report only aggregate deltas.
