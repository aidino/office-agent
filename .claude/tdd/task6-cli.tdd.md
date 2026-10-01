# TDD Evidence Report — Task 6: CLI Interface

- **Source plan:** `docs/superpowers/plans/2026-10-01-benchmark-harness.md` (Task 6)
- **Date:** 2026-10-01
- **Branch:** `main`

## User journeys

1. As a benchmark operator, I want `office_bench run` to execute
   registered suites through the Runner with filters (task id, category,
   limit, number of runs), so one command runs a benchmark pass.
2. As a benchmark operator, I want `--run-id` on `run`, so I can resume
   or extend an existing run directory from the CLI (Task 5 review carry:
   resume was unreachable without it).
3. As a benchmark operator, I want `list --suite X` to show a suite's
   tasks (id, category, prompt preview), so I can inspect before running.
4. As a benchmark operator, I want `report --run-id X` to regenerate
   `report.md` from an existing run's persisted results, without
   re-running anything.
5. As a benchmark operator, I want `trend` to read `backdata.csv`
   (filterable by suite) and show recent rows, so I can see performance
   over time.
6. As a benchmark operator, I want `compare --runs A B` to diff two
   runs' primary metrics per suite, so regressions stand out.
7. As a benchmark operator, I want `python -m office_bench --help` to
   work, so the harness is runnable as a module.
8. (Loop 2) As a benchmark operator, I want malformed filter flags,
   empty registries, invalid counts, and stray JSON files to fail loudly
   — never a crash in reporting, never a junk row in the append-only
   backdata CSV.

## Plan-intent verification (before coding)

- Plan safety checklist passed: Task 6 creates three files inside
  `benchmarks/`; `_cmd_setup` shells out only to
  `git submodule update --init --recursive` (non-destructive) and every
  test mocks `subprocess` — no real git/network/agent execution in the
  suite; no credentials; no agent-override phrases; validation commands
  are plain `uv run pytest` (allowlisted).
- **Documented plan gaps and interpretations:**
  - The plan's DoD promises tests for `run` invokes Runner, `report`
    regenerates, and `python -m office_bench --help` — its own test file
    (4 tests) contains none of them. Added (test-only strengthening).
  - Task 5 review observation carried in: the planned CLI had no
    `--run-id`, making resume unreachable from the CLI. Added
    `--run-id` to `run` (deviation from the plan's code block).
  - `--no-resume` help text documents its actual semantics
    (re-run but existing files kept — the first run's numbers stand).
  - The plan's dead trailing `return 1` in `main()` (unreachable after
    the if/elif chain) became dict dispatch so every statement is
    coverable at the repo's 100% bar; behavior identical.
  - `_cmd_setup` takes the dispatched (unused) namespace parameter.
  - Unused `json` import dropped from the plan's module code; unused
    `StringIO`/`MagicMock` imports dropped from the plan's test code.
  - The plan's Step 5 says "all 4 tests PASS"; the strengthened file had
    18 at GREEN (34 after both loops) — noted like Task 5's count gap.

## Task report

### Loop 1 — planned feature

- **RED** — `cd benchmarks && uv run pytest tests/test_cli.py -v` →
  collection error `ModuleNotFoundError: No module named
  'office_bench.cli'` (valid compile-time RED: the tests import the
  missing module). Commit `104e7e6`.
- **GREEN** — created `benchmarks/src/office_bench/cli.py` (`main()`
  with six argparse subcommands, dict dispatch, lazy suite registry) and
  `__main__.py`. Two mid-step fixes folded in: `_cmd_setup` signature
  accepts the dispatched namespace; run-help assertion made
  case-insensitive. `tests/test_cli.py` **18/18 PASS**; full suite
  **80/80** — no regression in Tasks 1–5. Commit `22a1527`.
- **Refactor** — not needed.
- **Coverage gap closing** (test-only): real `_build_suite_registry`
  both success (fake adapter modules injected via `sys.modules`; pins
  the four fixed repo dirs) and ImportError degradation; in-process
  `__main__` exit-code forwarding (the subprocess entry-point test is
  invisible to coverage). Package **598/598 statements (100%)**, 83
  tests. Commit `3b280f5`.

### Review

`.claude/reviews/task6-cli-review.md` (REQUEST CHANGES — M-1..M-4
medium, L-1..L-3 low; all seven demonstrated with reproducers at
`/tmp/repro_task6.py`; 0 critical/major). Verbatim record commit
`cd92430`. Resolution table appended to the review file.

### Loop 2 — confirmed findings only

- **RED** — twelve failing reproducers + one pin-only test
  (`--suite` whitespace stripping already worked):
  `uv run pytest tests/test_cli.py -q` → **12 failed, 22 passed**.
  Commit `95b0eb3`.
- **GREEN** — `fix(bench)` in `cli.py`: `_result_rows()` guard for
  stray JSON in report/compare (also shields `aggregate_suite`, whose
  per-row `.get` raises `AttributeError` on non-dict JSON — one layer
  below the demonstrated crash, found while fixing and covered by the
  same test); `_split_csv` + loud exit 1 for degenerate filter flags;
  `>=1` argparse type for `--runs`/`--limit`; loud failures for
  `--suite all` with empty registry and empty resolved suite lists;
  `not run` instead of fabricated deltas in compare; setup checks git's
  exit and missing binary; trend truncation marker. Full suite
  **96/96**, coverage **100%** (`cli.py` 197/197, package 641/641).
  Commit `620cce1`.

## Test specification

34 tests in `benchmarks/tests/test_cli.py` (96 in full suite):

| # | What is guaranteed | Test (benchmarks/tests/test_cli.py) | Type | Result | Evidence |
|---|--------------------|--------------------------------------|------|--------|----------|
| 1 | `--help` exits 0 | `test_help_returns_zero` | unit | PASS | `uv run pytest tests/test_cli.py -v` |
| 2 | No command prints help, exits 0 | `test_no_command_prints_help` | unit | PASS | same |
| 3 | `python -m office_bench --help` works (real subprocess) | `test_python_m_entry_point_help` | unit | PASS | same |
| 4 | `list` prints task ids + categories | `test_list_command` | unit | PASS | same |
| 5 | `list` unknown suite → exit 1 + stderr | `test_list_unknown_suite_fails` | unit | PASS | same |
| 6 | `run` builds the right RunConfig and calls `Runner.run(RESULTS_BASE, run_id=None)` | `test_run_invokes_runner` | unit | PASS | same |
| 7 | `--suite all` expands to registry keys; comma flags split; `--run-id` forwarded (resume reachable from CLI) | `test_run_suite_all_comma_split_and_run_id` | unit | PASS | same |
| 8 | Run help documents `--run-id` and `--no-resume` semantics | `test_run_help_documents_resume_flags` | unit | PASS | same |
| 9 | `setup` invokes `git submodule update` | `test_setup_invokes_submodule_update` | unit | PASS | same |
| 10 | `report` regenerates report.md with suite + score from existing results | `test_report_regenerates_from_existing_results` | unit | PASS | same |
| 11 | `report` unknown run → exit 1 + stderr | `test_report_missing_run_fails` | unit | PASS | same |
| 12 | `trend` reads backdata.csv and prints rows | `test_trend_command_reads_csv` | unit | PASS | same |
| 13 | `trend --suite` filters rows | `test_trend_filters_by_suite` | unit | PASS | same |
| 14 | `trend` filter matching nothing → friendly message, exit 0 | `test_trend_no_matching_rows` | unit | PASS | same |
| 15 | `trend` without backdata.csv → exit 1 + stderr | `test_trend_missing_csv_fails` | unit | PASS | same |
| 16 | `compare` prints both run ids, suite, and the delta (+5.00) | `test_compare_command` | unit | PASS | same |
| 17 | `compare` first run missing → exit 1 | `test_compare_missing_run_fails` | unit | PASS | same |
| 18 | `compare` second run missing → exit 1 | `test_compare_missing_second_run_fails` | unit | PASS | same |
| 19 | Registry lazily imports all four adapters, each bound to its fixed `data/benchmarks/` dir | `test_build_suite_registry_discovers_all_adapters` | unit | PASS | same |
| 20 | Per-adapter ImportError degrades to empty registry, no crash | `test_build_suite_registry_empty_when_adapters_unimportable` | unit | PASS | same |
| 21 | `__main__` exits with main()'s return code | `test_dunder_main_forwards_cli_exit_code` | unit | PASS | same |
| 22 | Stray object JSON in run dir does not crash `report` (M-1) | `test_report_tolerates_stray_json` | unit (review) | PASS | same |
| 23 | Stray non-object JSON in run dir does not crash `compare` (M-1) | `test_compare_tolerates_stray_json` | unit (review) | PASS | same |
| 24 | `--task-id`/`--category` strip whitespace and drop empty segments (M-2) | `test_run_filters_strip_whitespace_and_drop_empty_segments` | unit (review) | PASS | same |
| 25 | Pin: `--suite` whitespace stripping | `test_run_suite_flag_strips_whitespace` | unit (pin) | PASS | same |
| 26 | Filter flags with no valid ids → exit 1 before Runner exists (M-2) | `test_run_rejects_degenerate_filter_flags` | unit (review) | PASS | same |
| 27 | `--suite all` with empty registry → loud exit 1, no run dir, no CSV (M-3) | `test_run_suite_all_with_empty_registry_fails` | unit (review) | PASS | same |
| 28 | `--suite` resolving to zero names → exit 1 (M-3) | `test_run_rejects_degenerate_suite_value` | unit (review) | PASS | same |
| 29 | `--runs`/`--limit` reject 0/negatives/garbage (argparse exit 2) (M-3) | `test_run_rejects_nonpositive_runs_and_limit` | unit (review) | PASS | same |
| 30 | Suites missing from one compared run show `not run`, no fabricated delta (M-4) | `test_compare_marks_suites_missing_from_one_run` | unit (review) | PASS | same |
| 31 | git failure in setup → exit 1, no "Setup complete" (L-1) | `test_setup_reports_git_failure` | unit (review) | PASS | same |
| 32 | Missing git binary → clean error, no traceback (L-1) | `test_setup_survives_missing_git` | unit (review) | PASS | same |
| 33 | trend truncation shows "(showing N most recent of M rows)" (L-2) | `test_trend_indicates_truncation` | unit (review) | PASS | same |
| 34 | End-to-end `run` via CLI: real Runner, fake suite, mock bridge — `--task-id "t1, t2"` runs both tasks, honest 2/2 CSV row (M-2/L-3a) | `test_run_end_to_end_writes_honest_backdata_row` | integration (review) | PASS | same |

## Coverage and known gaps

- **Coverage:** 100% statements across `office_bench`
  (`uv run --with pytest-cov pytest tests/ --cov=office_bench`), 96
  tests; `cli.py` 197/197, `__main__.py` 3/3.
- **Known gaps / intentional limits:**
  - `_build_suite_registry` currently resolves to an empty registry —
    the four adapters are Tasks 7–10; `--suite all` therefore exits 1
    until then (by design, review M-3). The registry wiring is pinned
    with injected stand-in modules.
  - `dual_judge` is plumbed through but unused (judges are later tasks,
    same as Task 5).
  - Review Observations (no action): `--run-id` accepts path-y strings
    (local operator tool, no security boundary); `RESULTS_BASE` from
    `__file__ parents[3]` assumes the repo layout (same class as Task
    5's `_agent_version` note); `Available:` with an empty registry is
    cosmetic until Tasks 7–10.
  - No live-agent E2E from the CLI here by design (the bridge contract
    is covered by Task 3; the Task 2 probe covered the live gateway).
- Tests never touch the network, the gateway, or git submodules; every
  writable operation patches `RESULTS_BASE` to `tmp_path`.

## Merge evidence

Checkpoint commits preserved on `main` (not squashed):

1. `104e7e6` — loop-1 RED: 18 tests; validated
   `ModuleNotFoundError: office_bench.cli`.
2. `22a1527` — loop-1 GREEN: `cli.py` + `__main__.py`; 18/18 target,
   suite 80/80.
3. `3b280f5` — loop-1 coverage gap tests; 83 tests, package 100%.
4. `cd92430` — code review record (REQUEST CHANGES).
5. `95b0eb3` — loop-2 RED: 12 review reproducers fail, 1 pin passes.
6. `620cce1` — loop-2 GREEN: six fixes; 96/96, package 100%.
7. close-out — this evidence file + review resolution + plan ticks.

If these are ever squashed, the RED/GREEN summaries above are the record
of what was verified and how.
