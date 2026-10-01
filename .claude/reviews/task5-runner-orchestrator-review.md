# Code Review: Task 5 — Runner Orchestrator

**Reviewed**: 2026-10-01
**Range**: `0222b5f..336ee40` (commits `d444d4a`, `51bf79f`, `336ee40`)
**Decision**: **REQUEST CHANGES** (0 critical, 1 major, 3 medium, 3 low; all validation passes, all four findings demonstrated with reproducers)

## Summary

The Runner matches the plan's specified interface verbatim, meets every DoD guarantee, and the 14 tests are deterministic and well-isolated (including a genuine improvement over the plan: the workspace-cleanup test was strengthened from the plan's `assert True` no-op into a real assertion via `mkdtemp` redirection). Full suite 53/53, `runner.py` 100% statement coverage (98/98), worktree identical to HEAD for the reviewed paths.

However, holding the same bar as the Task 4 review (only demonstrable findings), four real defects exist on the paths the DoD cares most about — resume and backdata integrity. The most serious: the aggregation loop iterates *configured* suite names while the run loop skips unregistered ones, so a single typo'd suite name silently appends a permanent `0/0 n/a` row to the append-only CSV — the dataset of record for the whole harness. Reproducers for all four findings are at `/tmp/repro_task5.py` and `/tmp/repro_task5b.py` (run with `cd /home/lai/Documents/office-agent/benchmarks && uv run python /tmp/repro_task5.py`).

## Findings

### CRITICAL

None.

### MAJOR

**M-A. A typo'd or unregistered suite name permanently pollutes the append-only backdata CSV** — `benchmarks/src/office_bench/runner.py:90-113` (aggregation loop) vs `runner.py:81-85` (run loop).

The run loop deliberately skips names missing from the registry (`if suite is None: continue`), but the aggregation loop then iterates `self._config.suites` unconditionally: `aggregate_suite` returns `{"primary_metric": "n/a", "primary_value": 0.0, tasks 0/0}`, `has_backdata_row` is False, so a row is appended for a suite that never executed. The planned Task 6 CLI makes this a one-character typo away (`--suite officebench,of_forte` splits on comma, plan line 2560), the run exits 0 with a report generated, and the operator gets zero signal. Because the CSV is append-only by project rule, removing the junk row requires hand-editing history.

Reproducer (confirmed 2026-10-01, `R1` in `/tmp/repro_task5.py`):

```
config.suites = ["fakesuite", "not-registered"]
→ backdata.csv gains: ...,not-registered,0,0,n/a,0.0,{}
→ report.md includes a "not-registered | n/a | 0.0 | 0/0" row; exit 0
```

The same loop has a second trigger: it matches result rows by registry key (`r.get("suite") == suite_name`) while `_run_suite` persists under `suite.name` (`runner.py:126` → `results.py:52-54`). If a registry key ever diverges from `suite.name`, a suite that ran fully aggregates to 0/0 and appends the same junk row. `runs=0` and a filter matching zero tasks land in the same bucket. `test_runner_skips_unknown_suite_name` pins "skip without crash" but never inspects the CSV, so this is uncovered despite 100% statement coverage.

Suggested minimal fix: resolve executed suites once and aggregate over those, keyed by `suite.name`, with a warning for the rest:

```python
executed = [self._suites[s] for s in self._config.suites if s in self._suites]
for s in self._config.suites:
    if s not in self._suites:
        print(f"warning: unknown suite '{s}' skipped", file=sys.stderr)
...
for suite in executed:
    agg = aggregate_suite(all_results, suite.name)
```

### MEDIUM

**M-1. Resume treats a truncated result file as complete; the task silently vanishes and a "complete-looking" aggregate is persisted** — `benchmarks/src/office_bench/runner.py:128`.

The resume guard is `result_path.exists()` — file *existence*, not validity. A crash mid-`write_text` (which is non-atomic, `results.py:80`) leaves a truncated JSON; resume skips it as "completed", and the Task 4 fix that makes `load_task_results` silently skip corrupt JSON (`results.py:90-93`) removes it from aggregation without a whisper. `tasks_total` is derived from surviving rows, so the record never reveals the gap.

Reproducer (confirmed 2026-10-01, `/tmp/repro_task5b.py`): pre-seed only `R/fakesuite/t0_run1.json` with `'{"task_id": "t0", "sui'`, then resume a 5-task config:

```
bridge calls: 4        (t0 never re-run — file "exists")
backdata row: R,...,fakesuite,4,4,accuracy,100.0   ← configured for 5
report: no mention of t0; no warning anywhere
```

A wrong-but-plausible value persisted to the CSV — exactly the failure class Task 4's M2 guarded against on the aggregation side. Suggested minimal fix: validate before skipping (`json.loads` in a small `_is_complete_result(path)` helper used at `runner.py:128`); the root fix is atomic writes in `save_task_result` (temp file + `os.replace`).

**M-2. One raising task aborts the entire run with no report and no backdata row** — `benchmarks/src/office_bench/runner.py:131-147` (`try/finally` with no `except`).

`setup_workspace` / `run_task` / `evaluate` exceptions propagate out of `Runner.run`: no aggregation, no report.md, no backdata row — a traceback after hours of real agent time because one fixture is broken at task 3 of 200. This contradicts the project's own stated philosophy in `agent_bridge.py:103-105` ("one gateway hiccup cannot abort a whole benchmark run" — which is why the bridge returns `[ERROR]` messages instead of raising); suite-side exceptions defeat the same goal one layer up.

Reproducer (confirmed 2026-10-01, `R3`): `evaluate` raises on `t2` of 5 → `RuntimeError` propagates; 2 per-task JSONs survive; `report.md` absent; `backdata.csv` absent. Note the workspace lifecycle on this path is *correct* — all 3 created workspaces were cleaned by the `finally` (verified; this behavior is currently unpinned by any test, see L-3). Recoverable via resume, which is why this is MEDIUM and not MAJOR. Suggested fix: `except Exception:` per task (bare `Exception` lets `KeyboardInterrupt`/`SystemExit` through) → log with `traceback` and continue, optionally persisting a failed `TaskResult` so the aggregate reflects the gap rather than hiding it.

**M-3. Resume overwrites `meta.json`, diverging run provenance from the already-persisted backdata row** — `benchmarks/src/office_bench/runner.py:69-78`.

`save_run_meta` is called unconditionally at the top of `run()`. On resume, `meta["timestamp"]` (and `git_commit`, if the operator fixed something before resuming — the common case) is replaced with the resuming invocation's values, while `has_backdata_row` correctly keeps the CSV row at the originals. Result: `meta.json`, the per-task JSONs (a mix of both invocations), and the backdata row tell three different provenance stories, and `meta.json` attributes all results to the resume commit.

Reproducer (confirmed 2026-10-01, `R4`):

```
first run  meta timestamp: 2026-10-01T08:10:30.213753+00:00
resumed    meta timestamp: 2026-10-01T08:10:30.267269+00:00  (overwritten)
backdata row timestamp   : 2026-10-01T08:10:30.213753+00:00  (original)
```

Suggested fix: write meta only when `meta.json` is absent, or preserve the original `timestamp`/`git_commit` and add `resumed_at`/`resumed_commit` fields — consistent with the project's append-only philosophy for this run's history.

### LOW

**L-1. Result-path scheme duplicated across modules** — `runner.py:125-126` re-derives `run_dir / suite.name / f"{task.task_id}_run{run_num}.json"` that `results.py:54` owns. If either drifts, resume silently re-runs everything (or skips nothing) with no error. Suggest a shared `task_result_path(...)` helper in `results.py` used by both.

**L-2. Raw `task_id` in `mkdtemp` prefix** — `runner.py:131`. A `task_id` containing `/` makes `tempfile.mkdtemp(prefix=f"bench_{task_id}_")` raise `FileNotFoundError` (mkdtemp does not create intermediate dirs). Same trusted-input assumption and same deferred disposition as Task 4's L2: revisit when suite adapters (Tasks 7-10) start supplying ids from third-party dataset files.

**L-3. Test gaps that let M-A and M-2 through** — `benchmarks/tests/test_runner.py`. Statement coverage is 100% but three behaviors are unpinned: (a) *partial* resume mid-suite (some results exist, remainder executes — the realistic crash-resume shape; `test_runner_resume_skips_existing` only tests the all-complete case); (b) workspace cleanup on the exception path (verified working in R3, but no test would catch a regression to a bare `rmtree` outside `finally`); (c) backdata *contents* in the unknown-suite case — asserting the CSV has exactly one row would have caught M-A. Also minor: no test asserts the *content* of a saved result JSON (fields like `run`, `duration_seconds`), only file counts.

### Observations (not defects in this diff — flag for Task 6)

- `no_resume=True` with a reused `run_id` re-runs the agent but silently discards the fresh results (`runner.py:128` bypasses the skip; `save_task_result`'s skip-on-exists keeps the old file). This is plan-verbatim and deliberately pinned by `test_runner_no_resume_reruns_everything`, so it is a design decision, not an implementation bug — but the operator pays for a full re-run and keeps the old numbers with no warning. Note the planned CLI (plan lines 2477-2487, 2553-2579) has no `--run-id`, so from the CLI every invocation gets a fresh run directory — meaning resume (the DoD centerpiece) is currently unreachable except via the API, and Task 6 should either add `--run-id` or document that `--no-resume` implies a fresh run.
- `dual_judge`, `gateway_url`, `timeout_seconds` are plumbed into `RunConfig` but unused by the Runner — plan-conformant (judges are Task 11+); noting so it is not re-flagged later.

## Validation Results

| Check | Result | Note |
|-------|--------|------|
| Tests | Pass | `uv run pytest tests/test_runner.py -v` → 14 passed |
| Full suite | Pass | `uv run pytest tests/` → 53 passed |
| Coverage | Pass | `runner.py` 98/98 statements; package 408/408 (100%) — matches commit claim |
| Reproducers | Confirmed | `/tmp/repro_task5.py` (R1-R4), `/tmp/repro_task5b.py` (R2b), all behaviors as described |
| Worktree | Clean | `benchmarks/` identical to HEAD; only untracked `.coverage` artifact |
| Typecheck / Lint | Skipped | none configured for `benchmarks/` (same as Task 4) |

## Verified strengths

- DoD fully pinned by tests: loading, all three filters, multi-run fan-out, single- vs multi-turn dispatch (`run_session` only when `turn_prompts` has >1 entry — exactly the global constraint), resume-skip without duplicate backdata rows, backdata with `model`/`agent_version` filled, report generation.
- Backdata idempotence via `has_backdata_row` is correctly implemented and tested on both the resume and `no_resume` paths — the append-only constraint holds in every scenario I exercised.
- Workspace lifecycle is correct on both success and exception paths (`try/finally` around setup→run→evaluate→persist), and the team strengthened the plan's no-op cleanup test into a real assertion — good catch on the plan's weakness.
- Meta fallbacks (`git_commit`, `agent_version` → `""`) are graceful and tested; `_agent_version`'s `parents[3]` path resolves correctly in this layout (test asserts non-empty).
- Sequential execution only; workspace delivered via bridge payload (`state._runtime_workspace`), never env vars; `RunConfig` is a frozen dataclass — all global constraints respected.

## Files Reviewed

- `benchmarks/src/office_bench/runner.py` — Added (191 lines)
- `benchmarks/tests/test_runner.py` — Added (316 lines)
- Read for context (unchanged): `results.py`, `agent_bridge.py`, `suites/base.py`, `docs/superpowers/plans/2026-10-01-benchmark-harness.md` (Task 5 and Task 6 sections), `.claude/reviews/task4-results-persistence-review.md`

## Recommended next steps

1. Fix M-A before Task 6 lands the CLI that makes the typo path reachable (~5 lines + a test asserting the CSV contents — R1 is ready to become that test).
2. Fix M-1 (validate-on-resume or atomic writes) and M-3 (preserve first-run provenance) in the same small TDD loop; R2b and R4 are ready to become tests.
3. Decide M-2's policy explicitly (per-task isolation vs fail-fast) and pin the exception-path workspace cleanup with a test either way.
4. Carry L-3(a)/(c) test gaps into the fix commits; revisit L-2 alongside Task 4's L2 when the first real suite adapter (Task 7) arrives.
5. Raise the `--run-id` question with the plan before Task 6: without it, resume is unreachable from the CLI.

**Verdict: REQUEST CHANGES** — M-A silently writes permanent junk into the append-only dataset of record on an ordinary operator error, and M-1 persists a wrong-but-plausible aggregate after a mid-write crash; both are small, test-ready fixes in the established TDD style of this repo.

---

## Resolution (2026-10-01)

All four demonstrable findings fixed in a second TDD loop; re-validated
**62/62 tests, coverage 100%** (`runner.py` 131/131, package 441/441).

| Finding | Resolution | Commit |
|---------|------------|--------|
| M-A | Aggregation iterates only registered suites, keyed by `suite.name`; unregistered names print a stderr warning and never reach the CSV. Both triggers covered by tests (typo'd name; registry-key vs `suite.name` divergence). Policy note: a *registered* suite whose filters match zero tasks still records an honest `0 tasks_run` row — that is operator-intended, unlike a typo. | `1a2b1a3` |
| M-1 | Resume validates result JSON (parses + carries `task_id`, mirroring Task 4's aggregation guard) before skipping; invalid files are unlinked and the task re-runs. Atomic writes in `save_task_result` noted as the root fix — deferred (would touch the Task 4 module; the runner-side guard closes the demonstrable path). | `1a2b1a3` |
| M-2 | Policy decided: **per-task isolation**, matching the bridge's stated philosophy. `except Exception` per task → stderr warning + persisted failed `TaskResult` (`passed=False`, `judge_backend=None`, explicit crash note) so the aggregate reflects the gap instead of hiding it. Exception-path workspace cleanup pinned by test. | `1a2b1a3` |
| M-3 | `_resume_meta` preserves the first run's `timestamp`/`git_commit` (consistent with the frozen backdata row) and adds `resumed_at`/`resumed_commit`; unreadable or non-object meta is replaced by fresh meta (tested). | `1a2b1a3` |
| L-1 | Open — the partial-resume test added in this loop pins runner's path derivation against `save_task_result`'s actual writes, so drift now fails a test rather than silently re-running everything. Shared helper optional. | — |
| L-2 | Open, deferred with Task 4's L2 to Task 7 (first real suite adapter supplying third-party task ids). | — |
| L-3 | All carried: (a) partial resume test, (b) exception-path cleanup test, (c) unknown-suite CSV-contents test, (d) result-JSON content pin. | `f381c24`, `1a2b1a3` |

Task 6 flags from Observations carried forward: the planned CLI has no
`--run-id`, making resume unreachable from the CLI; and `--no-resume`
semantics (re-run but keep old numbers) deserve explicit help text.
