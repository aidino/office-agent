# TDD Evidence Report — Task 10: FORTE Suite Adapter with LLM Judge

## Source Plan

`docs/superpowers/plans/2026-10-01-benchmark-harness.md` — Task 10 (lines 4030–4803).

## User Journeys

1. **FORTE task loading** — Parse task markdown with YAML frontmatter from `data/tasks/*.md`, resolving input files from `data/assets/<id>/input/`.
2. **Workspace setup** — Copy input files into a per-task workspace directory.
3. **Prompt formatting** — Return the `## Prompt` section from the task markdown.
4. **Automated grading** — Delegate grading to FORTE's native `judge/grade.py::grade_one` for `automated` and `hybrid` tasks.
5. **LLM judge grading** — Evaluate rubrics via an OpenAI-compatible chat completions API (DeepSeek default) for `llm_judge` and `hybrid` tasks.
6. **No-rubric safety** — Automated tasks without rubrics are marked `passed=False` with an explanatory note; never auto-pass.
7. **Missing grader safety** — When `judge/grade.py` is not importable, fail with an explicit error, never silently pass.

## Task Report

### FORTE Suite Adapter (`forte.py`)

- **Files created:** `benchmarks/src/office_bench/suites/forte.py`
- **Summary:** `ForteSuite` implements the `Suite` protocol. Parses YAML frontmatter + `## Prompt` from markdown task files. Handles all three grading types: `automated` (delegates to `grade_one`), `llm_judge` (delegates per-rubric to `LLMJudge`), `hybrid` (both). Missing grader or no rubrics → explicit failure.
- **RED evidence:** `ModuleNotFoundError: No module named 'office_bench.suites.forte'` (commit `934b848`)
- **GREEN evidence:** 9 tests pass (commit `91efb60`)

### LLM Judge Backend (`llm.py`)

- **Files created:** `benchmarks/src/office_bench/judges/llm.py`
- **Summary:** `LLMJudge` implements the `JudgeBackend` protocol. Sends rubric evaluation requests to an OpenAI-compatible API. Parses `PASS.`/`FAIL.` prefix from response. Falls back to `JUDGE_MODEL`, `JUDGE_BASE_URL`, `JUDGE_API_KEY` env vars. API errors → `passed=False` with error reason.
- **RED evidence:** `ModuleNotFoundError: No module named 'office_bench.judges.llm'` (commit `934b848`)
- **GREEN evidence:** 3 tests pass using a real `ThreadingHTTPServer` mock (commit `91efb60`)

## Test Specification

| # | What is guaranteed | Test file::test | Type | Result |
|---|---|---|---|---|
| 1 | Loads 3 tasks from fixture markdown files | `test_suite_forte.py::test_load_tasks` | unit | PASS |
| 2 | Parsed task has correct suite, category, prompt, rubrics | `test_suite_forte.py::test_task_fields` | unit | PASS |
| 3 | setup_workspace copies input files into workspace | `test_suite_forte.py::test_setup_workspace` | unit | PASS |
| 4 | format_prompt returns the markdown prompt section | `test_suite_forte.py::test_format_prompt` | unit | PASS |
| 5 | Automated grading with rubrics delegates to grade_one (pass + fail) | `test_suite_forte.py::test_evaluate_automated_delegates_to_grade_one` | unit | PASS |
| 6 | Automated grading without rubrics → not evaluable, never auto-pass | `test_suite_forte.py::test_evaluate_automated_without_rubrics_not_evaluable` | unit | PASS |
| 7 | Missing grader (no judge/grade.py) → explicit failure | `test_suite_forte.py::test_evaluate_grader_missing_fails_cleanly` | unit | PASS |
| 8 | LLM judge grading delegates all rubrics to judge backend | `test_suite_forte.py::test_evaluate_llm_judge_delegates_to_judge_backend` | unit | PASS |
| 9 | LLM judge rubric failure → task fails | `test_suite_forte.py::test_evaluate_llm_judge_fails_when_rubric_fails` | unit | PASS |
| 10 | LLMJudge.name returns `llm:<model>` | `test_judge_llm.py::test_llm_judge_name` | unit | PASS |
| 11 | LLMJudge correctly parses PASS response from API | `test_judge_llm.py::test_llm_judge_rubric_pass` | integration | PASS |
| 12 | LLMJudge correctly parses FAIL response from API | `test_judge_llm.py::test_llm_judge_rubric_fail` | integration | PASS |

## Coverage

```
Command: uv run pytest tests/test_suite_forte.py tests/test_judge_llm.py --cov=office_bench.suites.forte --cov=office_bench.judges.llm --cov-report=term-missing

Name                               Stmts   Miss  Cover   Missing
----------------------------------------------------------------
src/office_bench/judges/llm.py        32      5    84%   50-52, 81-82
src/office_bench/suites/forte.py     117     14    88%   47-49, 84, 133-134, 140, 191, 205-209, 229
----------------------------------------------------------------
TOTAL                                149     19    87%
```

**Intentional gaps:**
- Lines 47–49: Log warning for unparseable task files (I/O edge case)
- Lines 133–134: `TypeError` catch for `grade_one` signature mismatch (defensive)
- Line 140: Non-dict `auto_detail` fallback (exotic grader return)
- Lines 205–209: Solution directory resolution (only relevant when solutions exist)
- Line 229: Text file reading in workspace (covered indirectly via empty workspace)
- Lines 50–52, 81–82 in `llm.py`: File-contents prompt building and non-dot reason extraction

## Merge Evidence

- **RED commit:** `934b848` — `test(bench): add reproducer for FORTE suite adapter and LLM judge (Task 10 RED)`
- **GREEN commit:** `91efb60` — `feat(bench): add FORTE suite adapter and LLM judge backend (Task 10 GREEN)`
- **Full suite:** 155 tests pass, 0 failures, 0 regressions
