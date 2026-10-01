# Code Review: Task 7 — OfficeBench Suite Adapter

**Reviewed**: 2026-10-01
**Author**: session (TDD workflow)
**Commits**: `6b5fec1..edc4cb0` (3 commits on main)
**Decision**: REQUEST CHANGES

## Summary

Clean adapter with correct delegation pattern and strong error-edge coverage (13 tests, 92% coverage). Two medium issues: repeated module reload on every `evaluate()` call is wasteful, and `_load_native_evaluation` uses `hash()` for the importlib module name which collides across instances with the same repo dir but adds no cache benefit since the module is re-imported every time. One medium issue around path traversal in the fixture `evaluation.py`.

## Findings

### CRITICAL
None

### HIGH
None

### MEDIUM

**M-1: `_load_native_evaluation()` re-imports `evaluation.py` on every `evaluate()` call**
- File: `benchmarks/src/office_bench/suites/officebench.py:75`
- Each task invocation calls `_load_native_evaluation()` which runs `spec.loader.exec_module(module)` — re-executing the entire module for every task. With 100+ OfficeBench tasks this is ~100 redundant file reads and module executions.
- **Fix**: Cache the loaded module on `self` after first successful load. Lazy `@property` or explicit `_eval_module: ModuleType | None` with sentinel.

**M-2: `hash()`-based module name is non-deterministic and unnecessary**
- File: `benchmarks/src/office_bench/suites/officebench.py:141`
- `abs(hash(str(self._repo_dir)))` uses Python's randomized string hashing (PYTHONHASHSEED). The name is only used for importlib's internal module registry, and since the module is never cached on `self`, the same `evaluation.py` gets registered under different names across runs. If caching is added (M-1 fix), collisions become a real risk.
- **Fix**: Use a deterministic name, e.g. `f"officebench_eval_{id(self)}"` or simply `"_officebench_eval"` (since sequential single-instance runs per global constraint).

**M-3: Fixture `evaluate_file_exist` allows path traversal via `args["file_path"]`**
- File: `benchmarks/tests/fixtures/officebench/evaluation.py:14`
- `workspace_dir / args.get("file_path", "")` joins an untrusted path directly. If the real OfficeBench eval does the same, the adapter mirrors it correctly. But the fixture doc says "mirrors the upstream API" — if the upstream actually sanitizes, the fixture silently diverges.
- **Risk**: Low for test fixtures; but once the real submodule is cloned (Step 5 investigation), confirm whether the adapter needs path sanitization or if OfficeBench tasks never contain traversal paths.
- **Fix**: Add a comment acknowledging this is intentionally mirroring upstream behavior, and flag for Step 5 investigation.

### LOW

**L-1: Unused import `ModuleType`**
- File: `benchmarks/src/office_bench/suites/officebench.py:10`
- `ModuleType` is used in the return type annotation of `_load_native_evaluation`. This is correct — not actually unused. Disregard.

**L-2: `_parse_subtask` silently swallows malformed JSON**
- File: `benchmarks/src/office_bench/suites/officebench.py:112-115`
- `except (json.JSONDecodeError, OSError): return None` silently skips corrupt task files. For a benchmark harness, logging a warning would help operators diagnose why a task count is lower than expected.
- **Fix**: Add a `logging.warning(...)` in the except block. Not blocking — the DoD explicitly says "never a silent pass or fail" for `evaluate()`, but `load_tasks()` silently dropping tasks could confuse operators.

## Validation Results

| Check | Result |
|---|---|
| Type check | Skipped (no mypy/pyright configured) |
| Lint | Skipped (no ruff/flake8 configured) |
| Tests | **Pass** — 109/109 passed in 5.99s |
| Build | Skipped (library package) |
| Coverage | **Pass** — 92% on `officebench.py` |

## Files Reviewed

| File | Change |
|---|---|
| `benchmarks/src/office_bench/suites/officebench.py` | Added |
| `benchmarks/tests/test_suite_officebench.py` | Added |
| `benchmarks/tests/fixtures/officebench/evaluation.py` | Added |
| `benchmarks/tests/fixtures/officebench/tasks/1/subtasks/1-1.json` | Added |
| `benchmarks/tests/fixtures/officebench/tasks/1/testbed/input.txt` | Added |
| `benchmarks/tests/fixtures/officebench/tasks/2/subtasks/2-1.json` | Added |
| `benchmarks/tests/fixtures/officebench/tasks/2/testbed/data.csv` | Added |
| `.claude/tdd/task7-officebench-suite.tdd.md` | Added |
| `benchmarks/pyproject.toml` | Modified (coverage dep) |

## Resolution

All findings addressed in commit `ce9ecfb`:

| Finding | Fix | Verified |
|---|---|---|
| **M-1** cache eval module | `_eval_module` sentinel pattern, loaded once per suite instance | `test_evaluate_caches_native_module` — asserts `is` identity |
| **M-2** deterministic name | `id(self)` replaces `hash(str(repo_dir))` | Implicit in all evaluate tests |
| **M-3** path traversal | Acknowledged as mirroring upstream; flagged for Step 5 investigation | Comment in fixture docstring |
| **L-2** log warning | `_log.warning(...)` in `_parse_subtask` except block | Manual inspection |

**Post-fix validation**: 110/110 tests pass (14 officebench, 96 existing). Decision updated to **APPROVE**.
