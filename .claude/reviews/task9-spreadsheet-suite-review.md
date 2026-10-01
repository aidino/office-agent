# Code Review: Task 9 — SpreadsheetBench 2 Suite Adapter

**Reviewed**: 2026-10-01
**Decision**: APPROVE (after fixes)

## Summary

SpreadsheetSuite adapter is well-structured, follows the patterns established by OfficeBench and PPTC adapters, and has solid test coverage (88%). Four medium-severity code quality issues found and fixed in this review.

## Findings

### CRITICAL
None

### HIGH
None

### MEDIUM

- **M-1 (FIXED):** Dead symbol `_DETERMINISTIC_CATEGORIES` at `spreadsheet.py:28` — declared as `frozenset` but never referenced. The `evaluate()` method checks `category == "Visualization"` directly. **Fix:** Removed the dead constant.

- **M-2 (FIXED):** `test_evaluate_visualization_deferred` was displaced from its section header and missing a blank line separator from `test_evaluate_no_expected_cells` (lines 251-252 jammed together). **Fix:** Moved the test back under its section header with proper blank line separation.

- **M-3 (FIXED):** `test_setup_workspace_copies_files` wrote a file into the shared fixture tree (`FIXTURES / "data" / "Debugging" / "debug-001.xlsx"`) and cleaned up in a `finally` block. Process crash or test interruption would leave a phantom file, causing downstream test instability. **Fix:** Rewrote the test to build an isolated fixture tree in `tmp_path`.

- **M-4 (FIXED):** Dead `import json as _json` in `test_setup_workspace_copies_files` (original version at line 195). **Fix:** Removed from the original location; the rewritten test uses `_json` import where actually needed.

### LOW

- **L-1:** Tolerance formula `abs(a - e) <= tol + abs(e) * tol` combines absolute and relative tolerance in a non-standard way (not `math.isclose` semantics). Plan specifies this formula explicitly — intentional.

- **L-2:** `_recalculate` writes `.recalced.xlsx` as a sibling file in the workspace. Acceptable for benchmark runs; workspace is ephemeral.

## Validation Results

| Check | Result |
|---|---|
| Tests (spreadsheet) | 21/21 PASS |
| Tests (full suite) | 143/143 PASS |
| Coverage (spreadsheet.py) | 88% (above 80% threshold) |

## Files Reviewed

| File | Type |
|---|---|
| `benchmarks/src/office_bench/suites/spreadsheet.py` | Added — source |
| `benchmarks/tests/test_suite_spreadsheet.py` | Added — test |
| `benchmarks/tests/fixtures/spreadsheet/data/Debugging/dataset.json` | Added — fixture |
| `benchmarks/tests/fixtures/spreadsheet/data/Financial_Model/dataset.json` | Added — fixture |
| `benchmarks/tests/fixtures/spreadsheet/data/Visualization/dataset.json` | Added — fixture |
| `.claude/tdd/task9-spreadsheet-suite.tdd.md` | Added — docs |
