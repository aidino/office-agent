# Task 8: PPTC Suite Adapter — TDD Evidence Report

**Source plan:** `docs/superpowers/plans/2026-10-01-benchmark-harness.md` — Task 8 (lines 3095–3556)

## User Journeys

1. As a benchmark operator, I want to load PPTC session definitions from the repo so that each session becomes a runnable Task.
2. As a benchmark operator, I want multi-turn sessions exposed via `metadata["turn_prompts"]` so the Runner can drive multi-turn agent conversations.
3. As a benchmark operator, I want template pptx files copied into the workspace for edit-type tasks so the agent starts from the correct baseline.
4. As a benchmark operator, I want PPTX-Match evaluation that compares per-slide text-attribute sets against the label deck so results are deterministic.
5. As a benchmark operator, I want a missing label to fail with a "prepare" hint so I know to run `main.py --prepare` first.

## Task Report

### Implementation: `benchmarks/src/office_bench/suites/pptc.py`

- **Summary:** Implemented `PPTCSuite` adapter implementing the `Suite` protocol. Parses `PPT_test_input/*/session_*.json`, builds `Task` objects with `turn_prompts` for multi-turn support, copies templates for edit tasks, and evaluates via per-slide sorted text-set comparison against `PPT_label_*` decks.
- **Validation command:** `uv run --project benchmarks pytest benchmarks/tests/test_suite_pptc.py -v`
- **RED output:** `ModuleNotFoundError: No module named 'office_bench.suites.pptc'` — 0 tests collected, 1 import error.
- **GREEN output:** 12 tests passed in 0.22s.
- **What is guaranteed:** All behaviors listed in the test specification below.

## Test Specification

| # | What is guaranteed | Test | Type | Result | Evidence |
|---|---|---|---|---|---|
| 1 | `load_tasks()` returns 2 sessions from fixture data | `test_load_tasks` | unit | PASS | session_1, session_2 found |
| 2 | Task fields: suite=pptc, category=task_type, turn_prompts populated, label_file set | `test_task_fields` | unit | PASS | metadata matches session JSON |
| 3 | Empty repo dir returns `[]` without error | `test_load_tasks_empty_dir` | unit | PASS | no crash on missing PPT_test_input |
| 4 | `setup_workspace()` copies template.pptx for edit tasks | `test_setup_workspace_copies_template` | unit | PASS | file exists in tmp_path |
| 5 | `setup_workspace()` is a no-op for create tasks (no template) | `test_setup_workspace_noop_for_create_task` | unit | PASS | workspace stays empty |
| 6 | `format_prompt()` returns first turn instruction | `test_format_prompt_first_turn` | unit | PASS | "Hello World" in prompt |
| 7 | Matching prediction deck → passed=True, score=1.0, judge_backend=deterministic | `test_evaluate_match_passes` | unit | PASS | exact text-set match |
| 8 | Wrong content in prediction → passed=False, score < 1.0 | `test_evaluate_wrong_content_fails` | unit | PASS | "Wrong Title" fails |
| 9 | No prediction pptx in workspace → passed=False, score=0.0 | `test_evaluate_missing_prediction_fails` | unit | PASS | explicit note |
| 10 | Missing label file → score=0.0, notes mention "prepare" | `test_evaluate_missing_label_reports_prepare_step` | unit | PASS | session_2 has no label |
| 11 | Extra slides beyond label → passed=False | `test_evaluate_extra_slides_fails` | unit | PASS | 3-slide pred vs 2-slide label |
| 12 | PPTCSuite satisfies Suite protocol (structural typing) | `test_suite_satisfies_protocol` | unit | PASS | isinstance check |

## Coverage and Known Gaps

- **Command:** `uv run coverage run -m pytest tests/test_suite_pptc.py -v && uv run coverage report --include="src/office_bench/suites/pptc.py" --show-missing`
- **Result:** 92% (108 statements, 9 missed)
- **Missed lines:** Defensive branches — JSON decode error (L42), pptx parse exception (L99-101), `_task_type_dir_name` empty-input-dir guard (L149-151, 202, 206). These are unreachable in fixture-based tests without corrupting fixture files at runtime.

## Merge Evidence

- **RED checkpoint:** `f30c124` — `test: add reproducer for PPTC suite adapter (Task 8 RED)`
- **GREEN checkpoint:** `6ab1c0f` — `feat: implement PPTC suite adapter (Task 8 GREEN)`
- **Full suite:** 122/122 tests pass across all benchmark modules.
