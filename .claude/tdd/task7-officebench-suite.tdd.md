# Task 7: OfficeBench Suite Adapter — TDD Evidence Report

## Source Plan

`docs/superpowers/plans/2026-10-01-benchmark-harness.md` — Task 7: OfficeBench Suite Adapter

## User Journeys

1. As a benchmark operator, I want to load OfficeBench tasks from the repo directory so that the runner can iterate them.
2. As a benchmark operator, I want testbed files copied into a per-task workspace so the agent sees correct input.
3. As a benchmark operator, I want evaluation delegated to OfficeBench's native `evaluation.py` so scores are comparable to published reference numbers.
4. As a benchmark operator, I want unknown eval functions and native exceptions to produce `passed=False` with explicit error notes — never a silent pass.

## Task Report

### Fixture creation
- Created `benchmarks/tests/fixtures/officebench/` with two task directories (`1/`, `2/`), subtask JSONs, testbed files, and a hermetic `evaluation.py` stand-in.

### RED validation
- Command: `cd benchmarks && uv run pytest tests/test_suite_officebench.py -v`
- Result: `ModuleNotFoundError: No module named 'office_bench.suites.officebench'`
- Commit: `6b5fec1` — `test(bench): add OfficeBench suite adapter reproducer and fixtures`

### GREEN validation
- Created `benchmarks/src/office_bench/suites/officebench.py` implementing `OfficeBenchSuite`
- Command: `cd benchmarks && uv run pytest tests/test_suite_officebench.py -v`
- Result: 13 passed in 0.04s
- Full suite regression: `uv run pytest tests/ -v` — 109 passed in 6.07s
- Commit: `b5bf7a7` — `feat(bench): add OfficeBench deterministic suite adapter`

## Test Specification

| # | What is guaranteed | Test name | Type | Result |
|---|---|---|---|---|
| 1 | `load_tasks()` returns 2 tasks from fixture dir | `test_load_tasks` | unit | PASS |
| 2 | Tasks have correct suite/category/prompt fields | `test_load_tasks_fields` | unit | PASS |
| 3 | Empty repo dir → empty task list, no crash | `test_load_tasks_empty_dir` | unit | PASS |
| 4 | `setup_workspace()` copies testbed files into workspace | `test_setup_workspace_copies_testbed` | unit | PASS |
| 5 | `format_prompt()` returns non-empty string containing task instruction | `test_format_prompt` | unit | PASS |
| 6 | `evaluate_file_exist` PASS when file exists | `test_evaluate_file_exist_pass` | unit | PASS |
| 7 | `evaluate_file_exist` FAIL when file absent | `test_evaluate_file_exist_fail` | unit | PASS |
| 8 | `evaluate_contain` PASS when substring present | `test_evaluate_contain_pass` | unit | PASS |
| 9 | `evaluate_contain` FAIL when substring absent | `test_evaluate_contain_fail` | unit | PASS |
| 10 | Unknown eval function → `passed=False` with error note | `test_evaluate_unknown_function` | unit | PASS |
| 11 | Native eval exception → `passed=False`, error captured | `test_evaluate_native_exception` | unit | PASS |
| 12 | Missing `evaluation.py` → `passed=False`, "not found" note | `test_evaluate_missing_evaluation_module` | unit | PASS |
| 13 | `OfficeBenchSuite` satisfies `Suite` protocol via `isinstance` | `test_suite_satisfies_protocol` | unit | PASS |

## Coverage and Known Gaps

- **Command:** `uv run coverage run -m pytest tests/test_suite_officebench.py -v && uv run coverage report --include="src/office_bench/suites/officebench.py" -m`
- **Result:** 92% (72 statements, 6 missed)
- **Missed lines:** Defensive branches for non-dir task entries, missing subtasks dir, directory copytree path, malformed JSON, and null spec.loader guard. All are edge guards, not business logic.

## Merge Evidence

- RED commit: `6b5fec1` — test reproducer, `ModuleNotFoundError` confirmed
- GREEN commit: `b5bf7a7` — adapter implemented, 13/13 tests PASS, 109/109 full suite PASS
- Coverage: 92% on `officebench.py`
- No refactoring needed — code is concise and follows plan structure
