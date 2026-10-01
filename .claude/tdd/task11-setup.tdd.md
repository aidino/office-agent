# TDD Evidence Report — Task 11: Setup Command & Git Submodules

**Date:** 2026-10-01
**Source plan:** `docs/superpowers/plans/2026-10-01-benchmark-harness.md` (Task 11, lines 4808–4989)

## User Journeys

1. As a developer, I want `office_bench setup` to clone all four benchmark submodules so I don't have to manually manage git submodules.
2. As a developer, I want the setup command to check for the SpreadsheetBench 2 dataset and tell me how to download it.
3. As a developer, I want setup to check for PPTC label files and tell me how to generate them.
4. As a developer, I want setup to verify LibreOffice is installed (required for SpreadsheetBench 2 recalc).
5. As a developer, I want setup to verify the FORTE judge module directory exists.
6. As a developer, I want setup to warn me if API keys (JUDGE_API_KEY / BUB_API_KEY) are missing.

## Task Report

### Enhanced `_cmd_setup()` (6 setup steps)

**Execution summary:** Replaced the minimal 2-line setup function with a full 6-step setup command matching spec §10.3. Each step prints numbered progress (`Step N/6:`). Git submodule failure still causes early exit with return code 1 (preserving existing error-handling behavior from Task 6 review findings).

**Validation command:** `uv run --project benchmarks pytest benchmarks/tests/test_setup.py benchmarks/tests/test_cli.py -v`

**RED output (5 of 8 tests FAIL):**
```
tests/test_setup.py::test_setup_checks_libreoffice FAILED
tests/test_setup.py::test_setup_mentions_spreadsheetbench_dataset FAILED
tests/test_setup.py::test_setup_mentions_pptc_labels FAILED
tests/test_setup.py::test_setup_mentions_forte_judge FAILED
tests/test_setup.py::test_setup_runs_all_six_steps FAILED
```
Failures caused by missing steps 2–5 and numbered output in old implementation.

**GREEN output (42/42 pass):**
```
tests/test_setup.py: 8 passed
tests/test_cli.py: 34 passed (including existing setup error-handling tests)
```

### `.gitmodules` created

All four benchmark submodule entries: FORTE, OfficeBench, SpreadsheetBench-2, PPTC.

## Test Specification

| # | What is guaranteed | Test file::test | Type | Result |
|---|---|---|---|---|
| 1 | `setup` calls `git submodule update --init --recursive` | `test_setup.py::test_setup_runs_submodule_update` | unit | PASS |
| 2 | `setup` checks for LibreOffice installation | `test_setup.py::test_setup_checks_libreoffice` | unit | PASS |
| 3 | `setup` warns when JUDGE_API_KEY and BUB_API_KEY are missing | `test_setup.py::test_setup_warns_missing_api_key` | unit | PASS |
| 4 | `setup` acknowledges when API key is present | `test_setup.py::test_setup_acknowledges_present_api_key` | unit | PASS |
| 5 | `setup` mentions SpreadsheetBench dataset | `test_setup.py::test_setup_mentions_spreadsheetbench_dataset` | unit | PASS |
| 6 | `setup` mentions PPTC label files | `test_setup.py::test_setup_mentions_pptc_labels` | unit | PASS |
| 7 | `setup` mentions FORTE judge | `test_setup.py::test_setup_mentions_forte_judge` | unit | PASS |
| 8 | `setup` runs all 6 numbered steps | `test_setup.py::test_setup_runs_all_six_steps` | unit | PASS |
| 9 | `setup` via CLI invokes submodule update (existing) | `test_cli.py::test_setup_invokes_submodule_update` | integration | PASS |
| 10 | Git failure returns exit 1 with error (existing) | `test_cli.py::test_setup_reports_git_failure` | unit | PASS |
| 11 | Missing git binary is clean error (existing) | `test_cli.py::test_setup_survives_missing_git` | unit | PASS |

## Coverage

```
cli.py: 227 statements, 7 missed → 97%
TOTAL:  1133 statements, 58 missed → 95%
```

**Uncovered lines (190, 196-203, 213, 221):** `else` branches for dataset/labels/FORTE directory existence. These execute only when actual benchmark data is present on disk — intentional gap for a mock-based test suite.

## Merge Evidence

- RED checkpoint: 5 tests failed because `_cmd_setup()` only performed git submodule + JUDGE key message
- GREEN checkpoint: 42/42 pass after enhancing with all 6 steps
- Refactor: moved `import os` to module top-level
- No existing tests broken
