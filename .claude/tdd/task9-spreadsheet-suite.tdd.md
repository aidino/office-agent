# TDD Evidence Report — Task 9: SpreadsheetBench 2 Suite Adapter

## Source Plan

`docs/superpowers/plans/2026-10-01-benchmark-harness.md` — Task 9

## User Journeys

1. As a benchmark runner, I want to load SpreadsheetBench 2 tasks from `data/<category>/dataset.json` files so that I can evaluate agent spreadsheet manipulation.
2. As a benchmark runner, I want cell-level comparison with numeric tolerance so that I can deterministically verify formula correctness.
3. As a benchmark runner, I want Visualization tasks to return a deferred score so that Phase 6 VLM integration can be added later.
4. As a benchmark runner, I want LibreOffice recalc before cell comparison so that formula-only workbooks produce real values for comparison.
5. As a benchmark runner, I want clean failure when LibreOffice is unavailable so that missing-recalc errors are explicit, not silent zero-match.

## Task Report

### Implementation

- Created `benchmarks/src/office_bench/suites/spreadsheet.py` — `SpreadsheetSuite` class implementing the `Suite` protocol.
- Created fixture data in `benchmarks/tests/fixtures/spreadsheet/data/{Debugging,Financial_Model,Visualization}/dataset.json`.
- Created `benchmarks/tests/test_suite_spreadsheet.py` — 21 tests covering all acceptance criteria.

### Validation

| Step | Command | Result |
|------|---------|--------|
| RED gate | `uv run pytest tests/test_suite_spreadsheet.py -v` | `ModuleNotFoundError: No module named 'office_bench.suites.spreadsheet'` |
| GREEN gate | `uv run pytest tests/test_suite_spreadsheet.py -v` | 21 passed in 0.17s |
| Full suite | `uv run pytest tests/ -q --tb=short` | 143 passed in 6.30s |
| Coverage | `uv run coverage report --include='src/office_bench/suites/spreadsheet.py'` | 88% (114 stmts, 14 missed) |

## Test Specification

| # | What is guaranteed | Test name | Type | Result |
|---|---|---|---|---|
| 1 | Loads 3 tasks across Debugging, Financial_Model, Visualization categories | `test_load_tasks` | unit | PASS |
| 2 | Task fields (suite, category, prompt) are correctly populated | `test_task_fields` | unit | PASS |
| 3 | `format_prompt` returns non-empty instruction text | `test_format_prompt` | unit | PASS |
| 4 | Correct cell value → passed=True, score=1.0, judge_backend="deterministic" | `test_evaluate_cell_value_pass` | unit | PASS |
| 5 | Wrong cell value → passed=False, score<1.0 | `test_evaluate_cell_value_fail` | unit | PASS |
| 6 | All cells correct in multi-cell task → passed=True, score=1.0 | `test_evaluate_multiple_cells` | unit | PASS |
| 7 | Partial cell match → passed=False, score=0.5 (1/2 cells) | `test_evaluate_partial_cell_match` | unit | PASS |
| 8 | Visualization category → score=0.0, notes mention "deferred"/"visualization" | `test_evaluate_visualization_deferred` | unit | PASS |
| 9 | Missing output file → passed=False | `test_evaluate_missing_file` | unit | PASS |
| 10 | Recalc returns None → passed=False, notes mention "recalc" | `test_evaluate_recalc_failure_fails_cleanly` | unit | PASS |
| 11 | Suite satisfies the Suite protocol (isinstance check) | `test_suite_satisfies_protocol` | unit | PASS |
| 12 | Empty repo (no data/ dir) → load_tasks returns [] | `test_load_tasks_empty_repo` | unit | PASS |
| 13 | Non-dir entries in data/ are skipped | `test_load_tasks_skips_non_dirs` | unit | PASS |
| 14 | Category dir without dataset.json is skipped | `test_load_tasks_skips_missing_dataset_json` | unit | PASS |
| 15 | Malformed dataset.json is skipped | `test_load_tasks_skips_bad_json` | unit | PASS |
| 16 | Entry without task_id is skipped | `test_load_tasks_skips_entry_without_task_id` | unit | PASS |
| 17 | setup_workspace copies input files into workspace | `test_setup_workspace_copies_files` | unit | PASS |
| 18 | None cell value matches empty expected string | `test_compare_cell_none_vs_empty` | unit | PASS |
| 19 | None cell value does not match non-empty expected | `test_compare_cell_none_vs_nonempty` | unit | PASS |
| 20 | Non-numeric strings use exact string comparison | `test_compare_cell_string_fallback` | unit | PASS |
| 21 | Task with no expected_cells passes with score=1.0 | `test_evaluate_no_expected_cells` | unit | PASS |

## Coverage and Known Gaps

- **88% coverage** (114 statements, 14 missed) — above 80% threshold.
- Intentional gaps:
  - `_recalculate` real implementation (lines 242-265): requires LibreOffice binary. Tested via monkeypatch (identity for happy path, None return for failure path).
  - `load_workbook` exception path (lines 144-145): defensive catch for corrupted xlsx files.
  - `shutil.copytree` branch in `setup_workspace` (line 71): dir-copy path, low risk.

## Merge Evidence

### Checkpoint Commits (current branch `main`)

| Commit | Stage | Evidence |
|--------|-------|----------|
| `908b050` | RED | `ModuleNotFoundError: No module named 'office_bench.suites.spreadsheet'` |
| `03a7970` | GREEN | 21/21 tests PASS, full suite 143/143 PASS, 88% coverage |
