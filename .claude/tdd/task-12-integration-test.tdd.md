# TDD Evidence Report — Task 12: Integration Test — Full Pipeline Dry Run

## Source Plan

`docs/superpowers/plans/2026-10-01-benchmark-harness.md` — Task 12.

## User Journeys

1. As a developer, I want to verify the full Runner pipeline (load → run → evaluate → persist → report) works end-to-end with a fake suite and mock bridge, so that I'm confident all modules integrate correctly.
2. As a developer, I want to verify resume semantics — a second run with the same `run_id` skips completed tasks and doesn't duplicate backdata rows.

## Task Report

### test_full_pipeline

- **Summary:** Exercises the complete Runner pipeline with an `IntegrationSuite` (3 tasks, deterministic pass/fail) and a mocked `AgentBridge`. Asserts directory structure, meta.json, 6 per-task result JSONs, correct pass/fail distribution (4/2), backdata CSV with accuracy 66.67%, report.md content, and bridge call count.
- **Validation command:** `uv run --project benchmarks pytest benchmarks/tests/test_integration.py::test_full_pipeline -v`
- **Result:** PASS (0.12s)
- **Guarantees:** Runner correctly orchestrates suite → workspace → bridge → evaluate → save_task_result → aggregate → backdata → report pipeline. All artifacts are created with correct content.

### test_resume_skips_completed_tasks

- **Summary:** Runs the pipeline once, then runs again with the same `run_id`. Asserts the bridge is not called on the second run and backdata CSV still has exactly one row (no duplicates).
- **Validation command:** `uv run --project benchmarks pytest benchmarks/tests/test_integration.py::test_resume_skips_completed_tasks -v`
- **Result:** PASS (0.12s)
- **Guarantees:** Resume correctly detects existing complete result JSONs and skips them. Append-only backdata CSV idempotency is enforced.

## Test Specification

| # | What is guaranteed | Test file / id | Type | Result | Evidence |
|---|---|---|---|---|---|
| 1 | Full pipeline produces meta.json, per-task JSONs, backdata.csv, report.md | `test_integration.py::test_full_pipeline` | integration | PASS | `uv run --project benchmarks pytest benchmarks/tests/test_integration.py -v` |
| 2 | 3 tasks × 2 runs = 6 result files, 4 passed / 2 failed | `test_integration.py::test_full_pipeline` | integration | PASS | assertions on result_files count and pass/fail distribution |
| 3 | Backdata CSV has correct suite, accuracy ≈66.67%, model and agent_version populated | `test_integration.py::test_full_pipeline` | integration | PASS | `pytest.approx(66.67, abs=0.1)` |
| 4 | Report.md contains suite name and score | `test_integration.py::test_full_pipeline` | integration | PASS | `assert "integ" in report; assert "66.67" in report` |
| 5 | Bridge is called exactly 6 times | `test_integration.py::test_full_pipeline` | integration | PASS | `bridge.run_task.call_count == 6` |
| 6 | Resume skips all completed tasks (0 bridge calls) | `test_integration.py::test_resume_skips_completed_tasks` | integration | PASS | `bridge.run_task.call_count == 0` after second run |
| 7 | Resume does not duplicate backdata rows | `test_integration.py::test_resume_skips_completed_tasks` | integration | PASS | CSV DictReader row count == 1 |

## Coverage and Known Gaps

- **Full suite:** 165 tests passed, 0 failures, 0 skipped.
- **Command:** `uv run --project benchmarks pytest benchmarks/tests/ -v --tb=short`
- **Note:** This is a test-only task (no production code written). The integration test validates existing modules from Tasks 1–6 working together. No RED gate applies — production code was already implemented.

## Merge Evidence

- **Checkpoint commit:** `00fabeb` — `test(bench): add end-to-end integration test for full pipeline (Task 12)`
- **Branch:** `main`
- **GREEN:** Both `test_full_pipeline` and `test_resume_skips_completed_tasks` pass. Full suite: 165/165 pass.
