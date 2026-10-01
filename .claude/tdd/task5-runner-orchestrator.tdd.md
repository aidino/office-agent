# TDD Evidence Report — Task 5: Runner Orchestrator

- **Source plan:** `docs/superpowers/plans/2026-10-01-benchmark-harness.md` (Task 5)
- **Date:** 2026-10-01
- **Branch:** `main`

## User journeys

1. As a benchmark operator, I want the Runner to load tasks from any
   registered suite and run them through the agent bridge, so one command
   executes a full benchmark pass.
2. As a benchmark operator, I want to filter by task id, category, or a
   limit, so I can smoke-test a slice of a suite without editing code.
3. As a benchmark operator, I want multi-turn tasks (metadata
   `turn_prompts` with >1 entry) dispatched as one session via
   `run_session`, so PPTC-style conversations keep a single thread.
4. As a benchmark operator, I want per-task workspaces created fresh and
   removed after evaluation (kept with `keep_workspaces`), so runs are
   isolated and disk does not fill.
5. As a benchmark operator, I want resume: completed result JSONs are
   skipped and the append-only backdata CSV never gains a second row for
   the same `(run_id, suite)` — an interrupted run finishes without
   rewriting history.
6. As a benchmark operator, I want each finished run to produce
   `meta.json` (with model + agent_version filled, per spec §9.3), a
   backdata row, and `report.md` — without re-running anything.

## Plan-intent verification (before coding)

- Plan safety checklist passed: Task 5 creates two files inside
  `benchmarks/`; the only `rmtree` targets directories the runner itself
  creates via `mkdtemp`; `subprocess` only runs read-only
  `git rev-parse --short HEAD`; no credentials, no agent-override
  phrases; validation commands are plain `uv run pytest` (allowlisted).
- **Documented plan gaps and interpretations:**
  - The plan's `test_runner_workspace_cleanup` ended with `assert True`
    ("not observable here"). Strengthened into a real guarantee by
    redirecting `tempfile.mkdtemp` into `tmp_path`: cleanup with
    `keep_workspaces=False`, preservation with `True` (test-only change).
  - The interface spec lists `Runner.__init__(config, suite_registry)`
    but the plan's own tests pass `bridge=` — kept the optional `bridge`
    parameter from the plan's implementation block.
  - The plan's Step 4 says "all 11 tests PASS" but its test block
    defines 10; implemented 10 + test-only additions (see counts below).

## Task report

### Loop 1 — planned feature

- **RED** — `cd benchmarks && uv run pytest tests/test_runner.py -v` →
  collection error `ModuleNotFoundError: No module named
  'office_bench.runner'` (valid compile-time RED: the new test imports
  the missing module). Commit `d444d4a`.
- **GREEN** — created `benchmarks/src/office_bench/runner.py`
  (`RunConfig` frozen dataclass; `Runner` orchestrating load → filter →
  workspace → bridge (single/multi-turn) → evaluate → persist →
  aggregate → backdata → report). `tests/test_runner.py` **10/10 PASS**;
  full suite **49/49** — no regression in Tasks 1–4. Commit `51bf79f`.
- **Refactor** — not needed: minimal implementation, matches module
  style.
- **Coverage gap closing** (test-only): unknown-suite skip, `no_resume`
  re-run semantics, git/version fallbacks in meta. Command:
  `cd benchmarks && uv run --with pytest-cov pytest tests/ --cov=office_bench --cov-report=term-missing -q`
  → `runner.py` 98/98, package 408/408 (100%), **53 tests**. Commit
  `336ee40`.

### Loop 2 — code-review fixes

Review: `.claude/reviews/task5-runner-orchestrator-review.md`
(REQUEST CHANGES — M-A major; M-1/M-2/M-3 medium; all demonstrated with
reproducers). Resolution table in the same file.

- **RED** — six reproducers added (M-A ×2 triggers, M-1 truncated
  result, M-2 ×2 incl. exception-path cleanup, M-3 meta provenance):
  `uv run pytest tests/test_runner.py -q` → **6 failed, 17 passed**
  (the passing 17 = 14 loop-1 tests + 3 pin-only tests: partial resume,
  result-JSON content, corrupt-meta). Commit `f381c24`.
- **GREEN** — `fix(bench)` applied all four fixes (details in the review
  resolution): aggregate registered suites keyed by `suite.name` with
  stderr warning; validate result JSON on resume + unlink garbage;
  per-task exception isolation persisting a failed `TaskResult`;
  `_resume_meta` preserving first-run provenance with `resumed_at`.
  Full suite **62/62**, coverage **100%** (`runner.py` 131/131, package
  441/441). Commit `1a2b1a3`.

## Test specification

23 tests in `benchmarks/tests/test_runner.py` (62 in full suite):

| # | What is guaranteed | Test (benchmarks/tests/test_runner.py) | Type | Result | Evidence |
|---|--------------------|------------------------------------------|------|--------|----------|
| 1 | Runner executes all tasks of a suite (5 tasks → 5 result JSONs) | `test_runner_runs_all_tasks` | unit | PASS | `uv run pytest tests/test_runner.py -v` |
| 2 | `task_ids` filter selects exactly the requested tasks | `test_runner_filters_by_task_id` | unit | PASS | same |
| 3 | `categories` filter selects matching tasks (t1, t3 of cat-b) | `test_runner_filters_by_category` | unit | PASS | same |
| 4 | `limit` caps tasks per suite | `test_runner_applies_limit` | unit | PASS | same |
| 5 | `runs=N` fans out to N result files per task | `test_runner_multiple_runs` | unit | PASS | same |
| 6 | Tasks with `turn_prompts` (>1) go through `run_session` with all turns; `run_task` never called | `test_runner_multiturn_uses_run_session` | unit | PASS | same |
| 7 | Resume with same run_id re-runs nothing and appends no duplicate backdata row | `test_runner_resume_skips_existing` | unit | PASS | same |
| 8 | A run produces `report.md` + `meta.json` | `test_runner_generates_report` | unit | PASS | same |
| 9 | Backdata row written with non-empty `model` and `agent_version` (spec §9.3) | `test_runner_appends_backdata` | unit | PASS | same |
| 10 | Workspaces removed after each task; kept with `keep_workspaces=True` | `test_runner_workspace_cleanup` | unit | PASS | same |
| 11 | Unregistered suite name skipped without crashing the run | `test_runner_skips_unknown_suite_name` | unit | PASS | same |
| 12 | `no_resume=True` re-runs tasks but never duplicates result JSONs or CSV rows | `test_runner_no_resume_reruns_everything` | unit | PASS | same |
| 13 | git unavailable → `git_commit` `''` in meta, run completes | `test_runner_meta_survives_git_failure` | unit | PASS | same |
| 14 | office_agent pyproject unreadable → `agent_version` `''`, run completes | `test_runner_meta_survives_version_read_failure` | unit | PASS | same |
| 15 | Typo'd suite name never appends a junk `n/a` CSV row; stderr warns; no results-table row | `test_runner_unknown_suite_never_pollutes_backdata` | unit (review M-A) | PASS | same |
| 16 | Aggregation and backdata key on `suite.name`, not the registry key | `test_runner_aggregates_by_suite_name_not_registry_key` | unit (review M-A) | PASS | same |
| 17 | Crash-truncated result JSON re-runs and is replaced; aggregate keeps all 5 tasks | `test_runner_resume_reruns_truncated_result` | unit (review M-1) | PASS | same |
| 18 | One crashing task is isolated: run completes, task persisted failed with note, aggregate 4/5=80.0 | `test_runner_task_exception_is_isolated_and_persisted` | unit (review M-2) | PASS | same |
| 19 | Workspaces cleaned up even when the task crashes | `test_runner_workspace_cleanup_on_task_exception` | unit (review M-2/L-3b) | PASS | same |
| 20 | Resume preserves first-run timestamp/commit in meta; CSV row matches; `resumed_at` added | `test_runner_resume_preserves_meta_provenance` | unit (review M-3) | PASS | same |
| 21 | Corrupt (truncated / non-object) meta.json replaced by fresh meta | `test_runner_resume_replaces_corrupt_meta` | unit | PASS | same |
| 22 | Partial resume (crash before CSV append) runs only missing tasks; final row covers the suite | `test_runner_partial_resume_completes_remainder` | unit (review L-3a) | PASS | same |
| 23 | Result JSON content pinned: task_id, suite, run, passed, score, judge_backend, duration, agent_output | `test_runner_result_json_content` | unit (review L-3d) | PASS | same |

## Coverage and known gaps

- **Coverage:** 100% statements across `office_bench`
  (`uv run --with pytest-cov pytest tests/ --cov=office_bench`), 62
  tests; `runner.py` 131/131.
- **Known gaps / intentional limits:**
  - `dual_judge`, `gateway_url`, `timeout_seconds` are carried in
    `RunConfig` but unused by the Runner (plan-conformant: judges are
    later tasks; the bridge consumes gateway/timeout when not injected).
  - A *registered* suite whose filters match zero tasks records an
    honest `0 tasks_run` CSV row — deliberate (operator asked for that
    filter), unlike an unregistered name (now warned + skipped).
  - `save_task_result` remains non-atomic; the runner-side
    validate-on-resume guard closes the demonstrated truncated-file
    path, atomic writes deferred (would touch Task 4's module).
  - L-2 (`task_id` trust in `mkdtemp` prefix) deferred with Task 4's L2
    to Task 7, when real adapters supply third-party ids.
  - Review observation for Task 6: the planned CLI has no `--run-id`, so
    resume is unreachable from the CLI; `--no-resume` semantics deserve
    explicit help text.
- Tests use a fake Suite and a mock bridge throughout — no real agent or
  gateway is exercised here by design (live-path coverage lives in the
  Task 2 E2E probe and future integration tasks).

## Merge evidence

Checkpoint commits preserved on `main` (not squashed):

1. `d444d4a` — loop-1 RED: 10 reproducers; validated
   `ModuleNotFoundError: office_bench.runner`.
2. `51bf79f` — loop-1 GREEN: `runner.py`; 10/10 target, suite 49/49.
3. `336ee40` — loop-1 coverage gap tests; 53 tests, package 100%.
4. `34771e4` — code review record (REQUEST CHANGES).
5. `f381c24` — loop-2 RED: 6 review reproducers fail, 17 pass.
6. `1a2b1a3` — loop-2 GREEN: four fixes; 62/62, package 100%.

If these are ever squashed, the RED/GREEN summaries above are the record
of what was verified and how.
