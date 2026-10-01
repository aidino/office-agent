# Code Review: Task 4 — Results Persistence & Backdata CSV

**Reviewed**: 2026-10-01
**Range**: `a2e22a8..HEAD` (commits `c86cf99`, `b6508f3`, `2bbaab7`, `a52b307`)
**Decision**: **APPROVE with comments** (0 critical, 0 high, 2 medium, 3 low; validation passes)

## Summary

Clean, well-tested persistence layer that matches the plan interface and the
harness's append-only/resume constraints; 100% statement coverage with
deterministic tests. Two confirmed defensive gaps in error handling on the
crash-resume path — worth fixing before Task 5 builds `Runner` on top, but
neither can corrupt data and neither occurs on the module's happy path.

## Findings

### CRITICAL

None.

### HIGH

None.

### MEDIUM

**M1. `generate_report` crashes on corrupt `meta.json`** —
`benchmarks/src/office_bench/results.py:200` (`generate_report`).

`json.loads(meta_path.read_text())` is unguarded. The module's own
`load_task_results` skips corrupt JSON precisely for the crash-mid-save
scenario (guaranteed by `test_load_task_results_ignores_corrupt_json`),
but `generate_report` re-reads `meta.json` without that protection.

Reproducer (confirmed 2026-10-01):

```
meta.json = '{"model": "trunca'   → JSONDecodeError: Unterminated string
```

Impact: with a truncated `meta.json`, the operator cannot regenerate a
report from surviving per-task results — including via Task 6's planned
`report` command, which calls this exact path. Suggested fix: mirror
`load_task_results` — try/except `(json.JSONDecodeError, OSError)` and
omit the "Run Metadata" section (or warn) instead of raising.

**M2. `_aggregate_forte` raises `KeyError` on rows lacking `task_id`** —
`benchmarks/src/office_bench/results.py:141` (`_aggregate_forte`).

Direct indexing `r["task_id"]` / `r["score"]`, while `_aggregate_accuracy`
correctly uses `r.get("passed")`. `load_task_results` ingests **any**
valid JSON under `run_dir` (it only skips `meta.json`/`summary.json` by
name and invalid JSON), so one stray valid JSON with
`"suite": "forte"` and no `task_id` crashes aggregation.

Reproducer (confirmed 2026-10-01):

```
alien.json = '{"suite": "forte", "score": 1.0}' anywhere under run_dir
→ load_task_results: 1 row ingested
→ aggregate_suite(rows, "forte") → KeyError: 'task_id'
```

Impact: `Runner.run()` (Task 5) would raise **after** all tasks executed —
losing the report and backdata row for the entire run. Suggested fix:
`r.get("task_id")` / `r.get("score", 0.0)` with rows missing either key
skipped, consistent with the accuracy path. Note for Task 5: the plan's
Runner feeds `load_task_results` output straight into this function.

### LOW

**L1. Empty "Reference Scores" section** — `results.py` emits the
`## Reference Scores` heading even when no suite in `aggregated` has
reference scores. Cosmetic; guard the heading behind the loop result.

**L2. Unsanitized `task_id` in path construction** — `save_task_result`
builds `<suite>/<task_id>_run<N>.json` from `result.task_id` verbatim; a
task_id containing `/` or `..` would write outside the suite dir. Inputs
come from pinned benchmark submodules (trusted today) — sanitize or
validate when suite adapters (Tasks 7–10) start supplying ids from
third-party dataset files.

**L3. CSV cells not neutralized for spreadsheet-formula injection** —
`append_backdata` writes `model`/`git_commit` etc. without guarding a
leading `=`, `+`, `-`, `@`. All values are harness-generated or
config/env-sourced today; theoretical only, but the CSV's whole purpose
is to be opened in a spreadsheet.

## Validation Results

| Check   | Result | Note |
|---------|--------|------|
| Tests   | Pass   | `uv run pytest tests/ -q` → 37 passed |
| Imports | Pass   | `office_bench.results`, `office_bench.reference` import clean |
| Typecheck | Skipped | no mypy/pyright configured for `benchmarks/` |
| Lint    | Skipped | no linter configured for `benchmarks/` |
| Coverage | Pass  | 100% statements (verified during Task 4, commit `2bbaab7`) |

## Verified strengths

- Append-only CSV semantics + `has_backdata_row` idempotence match spec §9
  and the plan's global constraints (resume never rewrites history).
- FORTE Avg@N aggregation counts **unique tasks** (`tasks_run`) vs
  task×run rows (`result_rows`) — matches the metric definition and is
  explicitly pinned by `test_aggregate_suite_forte_avg_at_n`.
- `save_task_result` no-overwrite behavior pinned by test; resume-safe.
- Timestamps are timezone-aware UTC ISO-8601.
- `reference.py` is pure data with per-suite provenance (`source`).
- Tests are deterministic and isolated (`tmp_path`), no shared state,
  no order dependence.

## Files Reviewed

- `benchmarks/src/office_bench/results.py` — Added (237 lines)
- `benchmarks/src/office_bench/reference.py` — Added (40 lines)
- `benchmarks/tests/test_results.py` — Added (291 lines)
- `.claude/tdd/task4-results-persistence.tdd.md` — Added (docs)
- `docs/superpowers/plans/2026-10-01-benchmark-harness.md` — Modified (checkboxes)

Reviewed at commit `a52b307`; worktree confirmed identical to HEAD for
all reviewed paths.

## Recommended next steps

1. Fix M1 + M2 in `results.py` with reproducer-first tests (small TDD
   loop; both reproducers above are ready to become tests).
2. Revisit L2 when Task 7 (first real suite adapter) lands, since that is
   when third-party task ids start flowing into path construction.
