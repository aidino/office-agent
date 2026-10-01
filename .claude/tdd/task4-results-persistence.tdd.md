# TDD Evidence Report — Task 4: Results Persistence & Backdata CSV

- **Source plan:** `docs/superpowers/plans/2026-10-01-benchmark-harness.md` (Task 4)
- **Date:** 2026-10-01
- **Branch:** `main`

## User journeys

1. As a benchmark operator, I want per-task results persisted as
   `<suite>/<task_id>_run<N>.json`, so outcomes are auditable and an
   interrupted run resumes without overwriting existing files.
2. As a benchmark operator, I want run metadata persisted to `meta.json`,
   so a report can carry model/commit/version context.
3. As a benchmark operator, I want an append-only backdata CSV with a
   `has_backdata_row` existence check, so score history accumulates and a
   resumed run never rewrites history or duplicates a `(run_id, suite)` row.
4. As a benchmark operator, I want per-suite aggregation — accuracy for
   officebench/spreadsheet/pptc, Avg@N over **unique tasks** for forte —
   so scores are comparable to the published reference numbers and reports
   never show "6/2 tasks".
5. As a benchmark operator, I want a Markdown `report.md` with run
   metadata, a per-suite results table, and reference-score comparison
   tables, so results are presentable without re-running anything.

## Plan-intent verification (before coding)

- Plan safety checklist passed: Task 4 only creates three files inside
  `benchmarks/`; validation commands are plain `uv run pytest`
  (allowlisted); no destructive filesystem operations, no credential
  handling, no agent-override phrases in the plan.
- **Documented plan gap and interpretation:** the Task 4 interface spec
  requires `office_bench.results.BackdataRow` (TypedDict with the 11
  backdata columns) but neither the plan's test file nor its
  implementation code block defines it. Interpreted as binding interface
  intent: implemented `BackdataRow` in `results.py` and added
  `test_backdata_row_columns` as its guarantee. No other scope widening.
- The plan's expected test count ("all 11 tests PASS") was 11; the
  implemented file has 17 tests (11 plan tests + 1 BackdataRow contract
  test + 5 coverage-gap tests added in Step 7). The delta is test-only.

## Task report

### RED — failing reproducer

- **Command:** `cd benchmarks && uv run pytest tests/test_results.py -v`
- **Result:** collection error —
  `ModuleNotFoundError: No module named 'office_bench.results'`
  (valid compile-time RED: the new test imports the missing module; not a
  setup failure).
- **Commit:** `c86cf99` `test(bench): add reproducers for results persistence and backdata CSV`

### GREEN — minimal implementation

- **Change:** created `benchmarks/src/office_bench/reference.py`
  (`REFERENCE_SCORES` for forte/officebench/spreadsheet/pptc) and
  `benchmarks/src/office_bench/results.py` (`save_task_result`,
  `load_task_results`, `save_run_meta`, `aggregate_suite`,
  `append_backdata`, `has_backdata_row`, `generate_report`,
  `BackdataRow`).
- **Command:** `cd benchmarks && uv run pytest tests/test_results.py -v`
- **Result:** **12 passed** (the RED target, now green). Full suite:
  **32 passed** — no regression in Tasks 1–3 tests.
- **Commit:** `b6508f3` `feat(bench): add results persistence, backdata CSV, and report generation`

### Refactor

- Not needed: the implementation is minimal, matches the plan's code
  verbatim (plus the required TypedDict), and follows the existing module
  style. No refactor commit.

### Coverage — gap closing

- **Command:** `cd benchmarks && uv run --with pytest-cov pytest tests/ --cov=office_bench --cov-report=term-missing -q`
- **Initial result:** `results.py` 88% — uncovered: `meta.json`
  exclusion in `load_task_results`, corrupt-JSON skip, empty-suite
  aggregation, spreadsheet/pptc/unknown metric names, report metadata and
  reference-less-suite sections.
- **Gap tests added** (test-only, no production change): meta.json
  exclusion, corrupt-JSON crash-resume skip, empty-suite aggregation,
  metric-name mapping, report metadata + reference comparison +
  reference-less suite skip.
- **Final result:** **37 passed**, package coverage **100%**
  (`results.py` 124/124 stmts, `reference.py` 2/2).
- **Commit:** `2bbaab7` `test(bench): cover meta.json exclusion, corrupt-JSON resume, and metric naming`

## Test specification

| # | What is guaranteed | Test (benchmarks/tests/test_results.py) | Type | Result | Evidence |
|---|--------------------|------------------------------------------|------|--------|----------|
| 1 | `save_task_result` writes `<suite>/<task_id>_run<N>.json` with task fields, run, timestamp, duration | `test_save_task_result_creates_json` | unit | PASS | `uv run pytest tests/test_results.py -v` |
| 2 | Resume never overwrites an existing result JSON (returns same path, content untouched) | `test_save_task_result_does_not_overwrite` | unit | PASS | same |
| 3 | `load_task_results` reads back every result JSON in a run | `test_load_task_results_reads_all` | unit | PASS | same |
| 4 | `meta.json` in the run dir is never counted as a task result | `test_load_task_results_skips_meta_json` | unit | PASS | same |
| 5 | A truncated/corrupt JSON (crash mid-save) is skipped, not raised | `test_load_task_results_ignores_corrupt_json` | unit | PASS | same |
| 6 | `save_run_meta` round-trips run metadata | `test_save_run_meta` | unit | PASS | same |
| 7 | officebench aggregation = accuracy = passed/total×100 (66.67 for 2/3) | `test_aggregate_suite_officebench` | unit | PASS | same |
| 8 | forte aggregation = avg_at_N over per-task means; `tasks_run` counts unique tasks (2), `result_rows` counts rows (6) | `test_aggregate_suite_forte_avg_at_n` | unit | PASS | same |
| 9 | Empty suite results aggregate to `n/a` / 0.0 | `test_aggregate_suite_empty_results` | unit | PASS | same |
| 10 | Metric names: spreadsheet → `pass_at_1`, pptc → `session_acc`, unknown → `accuracy` | `test_aggregate_suite_metric_names` | unit | PASS | same |
| 11 | First `append_backdata` creates the CSV with the 11-column header + row | `test_append_backdata_creates_with_header` | unit | PASS | same |
| 12 | Subsequent appends add rows without rewriting (header stays, 3 lines) | `test_append_backdata_appends_without_rewriting` | unit | PASS | same |
| 13 | `has_backdata_row` is False for missing file, True only for the exact (run_id, suite) pair | `test_has_backdata_row` | unit | PASS | same |
| 14 | `generate_report` writes `report.md` containing suite name and score | `test_generate_report_produces_markdown` | unit | PASS | same |
| 15 | Report renders run metadata and the reference comparison table; a suite without published references gets no reference section | `test_generate_report_includes_run_metadata` | unit | PASS | same |
| 16 | `REFERENCE_SCORES` covers forte/officebench/spreadsheet/pptc, each with `scores` + `source` | `test_reference_scores_has_all_suites` | unit | PASS | same |
| 17 | `BackdataRow` TypedDict carries exactly the 11 backdata CSV columns | `test_backdata_row_columns` | unit | PASS | same |

## Coverage and known gaps

- **Coverage:** 100% statements across the `office_bench` package
  (`uv run --with pytest-cov pytest tests/ --cov=office_bench`), 37 tests.
- **Known gaps / intentional limits:**
  - `save_run_meta` always overwrites `meta.json` (by design — meta is
    rewritten on resume; only per-task JSONs and the CSV are append-only).
  - `BackdataRow` is a typing contract only; `append_backdata` accepts any
    mapping and fills missing columns with `""` (lenient on purpose so
    Task 5's Runner cannot crash on a partial row).
  - Reference scores are hardcoded from the papers cited in the plan;
    they are not re-validated against the sources at runtime.

## Merge evidence

Checkpoint commits preserved on `main` (not squashed):

1. `c86cf99` — RED: 12 reproducers; validated
   `ModuleNotFoundError: office_bench.results`.
2. `b6508f3` — GREEN: `results.py` + `reference.py`; 12/12 target tests,
   full suite 32/32.
3. `2bbaab7` — coverage gap tests; 37/37, package coverage 100%.

If these are ever squashed, the RED/GREEN/coverage summary above is the
record of what was verified and how.

## Post-review fix loop (2026-10-01)

Code review (`.claude/reviews/task4-results-persistence-review.md`)
confirmed two defensive-gap findings with live reproducers; both were
fixed in a second small TDD loop:

- **RED** — `17d038b` `test(bench): add reproducers for review findings M1/M2 in results layer`
  - M1: `test_generate_report_survives_corrupt_meta_json` — truncated
    meta.json → failed with `JSONDecodeError`.
  - M2: `test_aggregate_forte_skips_rows_missing_task_id` — stray row
    without `task_id` → failed with `KeyError: 'task_id'`.
- **GREEN** — `d7f86ff` `fix(bench): survive corrupt meta.json and task_id-less rows in results layer`
  - `generate_report` guards the meta.json read and emits an explicit
    "meta.json unreadable" note; per-task results stay reportable.
  - `_aggregate_forte` skips rows without `task_id`; `result_rows`
    counts only ingested rows.
  - Re-validated: **39/39 tests**, package coverage still **100%**
    (`results.py` 134/134 stmts).
- LOW findings (L1 empty section heading, L2 task_id sanitization,
  L3 CSV formula injection) were left open intentionally — see the
  review's next steps; L2 is to be revisited with Task 7.
