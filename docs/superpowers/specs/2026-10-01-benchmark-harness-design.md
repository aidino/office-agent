# Office Agent Benchmark Harness — Design Spec

**Date**: 2026-10-01
**Status**: Approved
**Author**: Dino + AI

## 1. Goal

Build a unified benchmark harness (`office_bench`) that evaluates Office Agent
across four external benchmark suites, tracks performance over time via an
append-only backdata CSV, and compares results against published top-tier model
scores. The harness is CLI-first, runs manually, and stores results as JSON
files with Markdown reports.

## 2. Benchmarks

| Suite | Repo | Tasks | Evaluation Method |
|---|---|---|---|
| FORTE | `AGI-Eval-Official/FORTE` | 180 tasks, 15 professions | LLM-as-judge (rubric pass/fail) + automated + hybrid |
| OfficeBench | `zlwang-cs/OfficeBench` | 300 tasks, multi-app chains | Deterministic: exact/fuzzy match, cell value, file existence |
| SpreadsheetBench 2 | `RUCKBReasoning/SpreadsheetBench-2` | 4 categories | Deterministic cell-level comparison; VLM for Visualization |
| PPTC | `gydpku/PPTC` | ~350+ sessions | Deterministic PPTX-Match: position relation + attribute comparison |

All four repos added as git submodules under `data/benchmarks/`. No
modifications to benchmark source code.

## 3. Approach

**Hybrid**: bypass each benchmark's agent runtime entirely; keep their
evaluation logic. Write a custom runner that sets up task workspaces, calls
Office Agent via the existing AG-UI SSE gateway, collects output, then
delegates scoring to each benchmark's native evaluation scripts/functions.

## 4. Architecture

```
office_agent/
├── src/office_agent/              # existing agent code (unchanged)
├── benchmarks/                    # NEW — standalone Python package
│   ├── pyproject.toml
│   └── src/office_bench/
│       ├── __init__.py
│       ├── cli.py                 # CLI: run, report, list, trend, compare, setup
│       ├── runner.py              # Orchestrator: load → run → evaluate → persist
│       ├── agent_bridge.py        # AG-UI SSE client
│       ├── results.py             # JSON persistence + Markdown report + backdata CSV
│       ├── reference.py           # Hardcoded leaderboard scores from papers
│       ├── judges/
│       │   ├── base.py            # JudgeBackend protocol
│       │   ├── llm.py             # LLM judge via OpenAI-compatible API (DeepSeek)
│       │   ├── jev.py             # JEV via OpenRouter (future)
│       │   └── decisions.py       # OpenAI Decisions API (placeholder)
│       └── suites/
│           ├── base.py            # Suite protocol + shared data types
│           ├── forte.py           # FORTE adapter
│           ├── officebench.py     # OfficeBench adapter
│           ├── spreadsheet.py     # SpreadsheetBench 2 adapter
│           └── pptc.py            # PPTC adapter
├── data/
│   └── benchmarks/
│       ├── FORTE/                 # git submodule
│       ├── OfficeBench/           # git submodule
│       ├── SpreadsheetBench-2/    # git submodule
│       ├── PPTC/                  # git submodule
│       └── datasets/             # gitignored — HuggingFace downloads
└── results/
    └── benchmarks/               # git-tracked — run results + backdata.csv
```

## 5. Suite Abstraction

### 5.1 Protocol

```python
class Suite(Protocol):
    name: str

    def load_tasks(self) -> list[Task]: ...
    def setup_workspace(self, task: Task, workspace_dir: Path) -> None: ...
    def format_prompt(self, task: Task) -> str: ...
    def evaluate(self, task: Task, workspace_dir: Path,
                 agent_output: AgentOutput) -> TaskResult: ...
```

### 5.2 Shared Data Types

```python
@dataclass(frozen=True)
class Task:
    suite: str              # "forte", "officebench", "spreadsheet", "pptc"
    task_id: str            # "finance-018"
    prompt: str             # instruction text
    category: str           # profession / app-count / task-type
    input_files: list[Path] # files to copy into workspace
    metadata: dict          # suite-specific (rubrics, eval config, etc.)

@dataclass(frozen=True)
class AgentOutput:
    messages: list[dict]       # conversation transcript
    files_created: list[Path]  # files the agent wrote in workspace
    tool_calls: list[dict]     # tool invocations log
    duration_seconds: float

@dataclass(frozen=True)
class TaskResult:
    task_id: str
    suite: str
    passed: bool
    score: float               # 0.0–1.0
    breakdown: dict            # per-rubric or per-subtask detail
    notes: str
    judge_backend: str | None  # "llm:deepseek-chat", "deterministic", etc.
```

### 5.3 Per-Suite Specifics

**FORTE:**
- `load_tasks()`: parse `data/tasks/*.md` — YAML frontmatter (id, category,
  grading_type, rubrics, workspace_files, solution_files) + `## Prompt`
  section.
- `setup_workspace()`: copy `data/assets/<task_id>/input/` into workspace.
  Copy skills into a skills directory if present.
- `evaluate()`: import `judge.grade.grade_one()` from submodule. Pass
  instruction, agent response text, rubrics list, file paths, path map.
  Judge calls DeepSeek API (configurable via `JUDGE_MODEL`,
  `JUDGE_BASE_URL`, `JUDGE_API_KEY` — FORTE judge supports these env vars
  natively). Solution files mounted read-only for judge, never shown to agent.
  Grading types: `automated` (code-based), `llm_judge` (DeepSeek), `hybrid`
  (weighted combination of both).
- Metrics: Avg@N, Pass@N, Pass^N. All-or-nothing per task (score=1 iff every
  rubric passes).

**OfficeBench:**
- `load_tasks()`: scan `tasks/*/subtasks/*.json` — each JSON contains task
  description + evaluation config (function name + args).
- `setup_workspace()`: copy `tasks/<task_id>/testbed/` into workspace.
- `evaluate()`: call `evaluate_output()` from `evaluation.py` — deterministic
  checks: `evaluate_contain`, `evaluate_exact_match`,
  `evaluate_excel_cell_value`, `evaluate_file_exist`, etc.
- `judge_backend = "deterministic"`.
- Metrics: accuracy by app count (1-app, 2-app, 3-app) and overall.

**SpreadsheetBench 2:**
- `load_tasks()`: parse `data/<category>/dataset.json` — 4 categories:
  Debugging, Financial_Model, Template, Visualization.
- `setup_workspace()`: copy spreadsheet files from HuggingFace dataset.
- `evaluate()`:
  - Debugging / Financial_Model / Template: import cell-level comparison from
    `evaluation/evaluation.py` — deterministic value, formula, font color
    comparison with tolerance.
  - Visualization: VLM checklist evaluator. Requires vision model. Deferred
    to Phase 6 (needs chart image export, Windows COM or LibreOffice
    fallback).
- Prerequisite: run `evaluation/open_spreadsheet.py` (LibreOffice recalc)
  before evaluation.
- Metrics: Pass@1 per category, regression vs modification accuracy.

**PPTC:**
- `load_tasks()`: scan `PPT_test_input/*/session_*.json` — 2 task types:
  Create_new_slides, Edit_ppt_template. Each session is multi-turn.
- `setup_workspace()`: copy template PPT for edit tasks.
- `evaluate()`: PPTX-Match — compare prediction .pptx vs label .pptx on
  position relation + attribute string match.
- Prerequisite: generate label files via `main.py --prepare` (one-time setup).
- `judge_backend = "deterministic"`.
- Metrics: turn-based accuracy, session-based accuracy, per-task-type.

## 6. Agent Bridge

Single integration point between harness and Office Agent. Calls the existing
AG-UI SSE gateway.

```python
class AgentBridge:
    def __init__(self, gateway_url: str = "http://127.0.0.1:18088/agent",
                 timeout_seconds: int = 600): ...

    def run_task(self, prompt: str, workspace_dir: Path) -> AgentOutput: ...
    def run_session(self, prompts: list[str], workspace_dir: Path) -> AgentOutput: ...
```

### 6.1 Single-Turn Flow

1. Set `OFFICE_AGENT_WORKSPACE` env to `workspace_dir`.
2. POST to AG-UI gateway with SSE streaming:
   ```json
   {
     "threadId": "bench-{task_id}-{run_id}",
     "runId": "run-{uuid_hex}",
     "messages": [{"id": "m1", "role": "user", "content": prompt}],
     "state": null, "tools": [], "context": [], "forwardedProps": {}
   }
   ```
3. Parse SSE events:
   - `RUN_STARTED` → start timer.
   - `TEXT_MESSAGE_CONTENT` → accumulate response text.
   - `TOOL_CALL_START/ARGS/END` → log tool invocations.
   - `RUN_FINISHED` → stop timer.
   - `RUN_ERROR` → capture error, mark failed.
4. Scan `workspace_dir` for new/modified files.
5. Return `AgentOutput`.

### 6.2 Multi-Turn Flow

For OfficeBench multi-step tasks and PPTC multi-turn sessions:
- Maintain same `threadId` across turns.
- Append message history each turn.
- Each turn returns intermediate `AgentOutput`; final merged output returned.

### 6.3 Workspace Isolation

- Each task runs in its own `tempfile.mkdtemp()`.
- Suite's `setup_workspace()` copies input files before agent runs.
- Workspace kept if `--keep-workspaces` flag set (for debugging).
- Per-task timeout from benchmark metadata (FORTE frontmatter
  `timeout_seconds`), default 600s.

## 7. Judge Backends

Only FORTE and SpreadsheetBench 2 Visualization require a judge. OfficeBench
and PPTC are fully deterministic.

### 7.1 Protocol

```python
class JudgeBackend(Protocol):
    name: str

    def judge_rubric(self, rubric: Rubric,
                     context: JudgeContext) -> RubricResult: ...

@dataclass(frozen=True)
class Rubric:
    id: str
    content: str
    weight: float

@dataclass(frozen=True)
class JudgeContext:
    instruction: str
    agent_response: str
    file_contents: dict[str, str]  # path → rendered text
    file_images: list[bytes]       # for multimodal judges
    file_pdfs: list[bytes]         # for multimodal judges

@dataclass(frozen=True)
class RubricResult:
    rubric_id: str
    passed: bool
    confidence: float | None       # None for LLM, 0–1 for JEV/Decisions
    reason: str
```

### 7.2 LLM Judge (Default — DeepSeek)

```python
class LLMJudge:
    name = "llm:deepseek-chat"
```

- Reuses FORTE's judge prompt-building logic (`judge/build_prompt.py`,
  `judge/system_prompt.py`) — imported directly from submodule.
- Calls DeepSeek via OpenAI-compatible `/chat/completions`.
- Parses response via FORTE's `judge/parse_grading.py`.
- Config env vars (compatible with FORTE's judge config):
  ```
  JUDGE_MODEL=deepseek-chat
  JUDGE_BASE_URL=https://api.deepseek.com
  JUDGE_API_KEY=${BUB_API_KEY}
  ```

### 7.3 JEV Judge (Future)

```python
class JEVJudge:
    name = "jev:jev-1.13"
```

- Each rubric → 1 `noul` question via OpenRouter (`typesafe/jev-1.13`).
- Text-only — cannot judge multimodal rubrics.
- Returns `noul` probability (0–1) + confidence. `passed = noul >= 0.5`.

### 7.4 OpenAI Decisions Judge (Placeholder)

Not implemented — Decisions API in limited preview as of 2026-09-30. Supports
vision input. Implement when public API docs and pricing are available.

### 7.5 Dual-Judge Calibration

With `--dual-judge` flag, each rubric is evaluated by both LLM judge and a
second judge (JEV or Decisions). Both results stored. Report includes
correlation metrics: % agreement, divergent rubrics. Used to calibrate before
switching judge backends.

## 8. Runner & CLI

### 8.1 Run Flow

```
Runner.run()
  ├── 1. Discover suites (--suite forte,pptc or "all")
  ├── 2. suite.load_tasks() for each suite
  ├── 3. Filter (--task-id, --category, --limit)
  ├── 4. For each task × each run (--runs N):
  │       ├── workspace = mkdtemp()
  │       ├── suite.setup_workspace(task, workspace)
  │       ├── agent_output = bridge.run_task(prompt, workspace)
  │       ├── result = suite.evaluate(task, workspace, agent_output)
  │       ├── save result JSON immediately (crash-safe)
  │       └── cleanup workspace
  ├── 5. Aggregate results per suite
  ├── 6. Append rows to backdata.csv
  ├── 7. Attach reference scores
  └── 8. Generate summary.json + report.md
```

Sequential execution — no parallelism. Agent gateway is single-instance.

### 8.2 Resume

Each task result saved immediately to
`results/benchmarks/<run_id>/<suite>/<task_id>_run<N>.json`. Runner skips
tasks with existing result files. `--no-resume` forces a fresh run.

### 8.3 CLI Commands

```bash
python -m office_bench setup                              # clone submodules + download datasets
python -m office_bench list --suite forte                  # list available tasks
python -m office_bench run --suite all --runs 3            # run all suites
python -m office_bench run --suite forte --runs 1          # single suite
python -m office_bench run --suite officebench --task-id 1-1,1-10
python -m office_bench run --suite spreadsheet --category Debugging
python -m office_bench run --suite pptc --keep-workspaces  # debug
python -m office_bench run --suite forte --dual-judge      # LLM + JEV
python -m office_bench report --run-id 2026-10-01_143022   # regenerate report
python -m office_bench trend                               # show backdata trend
python -m office_bench trend --suite forte                 # filter by suite
python -m office_bench compare --runs <id1> <id2>          # diff two runs
```

## 9. Results & Reporting

### 9.1 Per-Run Layout

```
results/benchmarks/
├── backdata.csv                    # append-only, git-tracked
└── 2026-10-01_143022/
    ├── meta.json                   # run config
    ├── forte/
    │   ├── finance-018_run1.json
    │   └── ...
    ├── officebench/
    │   └── ...
    ├── spreadsheet/
    │   └── ...
    ├── pptc/
    │   └── ...
    ├── summary.json
    └── report.md
```

### 9.2 Per-Task Result JSON

```json
{
  "task_id": "finance-018",
  "suite": "forte",
  "run": 1,
  "passed": false,
  "score": 0.0,
  "breakdown": {"01": 1.0, "02": 0.0, "03": 1.0},
  "judge_backend": "llm:deepseek-chat",
  "notes": "[02] FAIL: cashflow forecast missing Q3 projection",
  "duration_seconds": 45.2,
  "agent_output": {
    "response_text": "...",
    "tool_calls": [
      {"name": "read_spreadsheet", "args": {"path": "input/2025.xlsx"}}
    ],
    "files_created": ["output/forecast.xlsx"]
  },
  "timestamp": "2026-10-01T14:31:05Z"
}
```

### 9.3 Backdata CSV

File: `results/benchmarks/backdata.csv` — append-only, git-tracked. Each
completed run appends one row per suite.

Columns:

| Column | Type | Description |
|---|---|---|
| `run_id` | string | YYYY-MM-DD_HHMMSS |
| `timestamp` | ISO 8601 | Run completion time |
| `git_commit` | string | Short SHA of office_agent repo |
| `agent_version` | string | From pyproject.toml |
| `model` | string | Runtime model (deepseek-flash) |
| `suite` | string | forte / officebench / spreadsheet / pptc |
| `tasks_total` | int | Total tasks in suite |
| `tasks_run` | int | Tasks executed this run |
| `primary_metric` | string | Metric name (suite-specific) |
| `primary_value` | float | Headline number to track |
| `secondary_metrics` | JSON string | Category breakdowns |

### 9.4 Aggregation Metrics

| Suite | Primary Metric | Calculation |
|---|---|---|
| FORTE | avg_at_3 | Mean of N runs' scores per task, then mean across tasks |
| OfficeBench | accuracy | correct / total × 100 |
| SpreadsheetBench 2 | pass_at_1 | correct / total per category |
| PPTC | session_acc | fully completed sessions / total sessions |

### 9.5 Markdown Report

Generated at `results/benchmarks/<run_id>/report.md`. Contains:
- Run metadata (model, version, commit, date).
- Per-suite results table with reference scores from papers.
- Per-category breakdown tables.
- Trend table (last 5 runs from backdata.csv).

### 9.6 Reference Scores

Hardcoded in `reference.py` from published papers and leaderboards. Each entry
includes source attribution. Updated manually when new numbers are published.

### 9.7 Compare Command

`python -m office_bench compare --runs <id1> <id2>` produces a diff table with
delta and regression warnings (⚠️ if any suite drops > 0.02).

## 10. Setup & Dependencies

### 10.1 Package Dependencies

```toml
[project]
name = "office_bench"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "requests>=2.31",
    "openpyxl>=3.1.0",
    "python-pptx>=1.0.0",
    "pyyaml>=6.0",
]
```

### 10.2 Env Config

Reuses existing `office_agent/.env`:

```bash
# Agent (existing)
BUB_API_KEY=<deepseek key>
BUB_API_BASE=https://api.deepseek.com

# Judge (new)
JUDGE_MODEL=deepseek-chat
JUDGE_BASE_URL=https://api.deepseek.com
JUDGE_API_KEY=${BUB_API_KEY}

# JEV (future)
# OPENROUTER_API_KEY=
```

### 10.3 Setup Command

`python -m office_bench setup` performs:

1. `git submodule update --init --recursive`
2. Download SpreadsheetBench 2 dataset from HuggingFace
   (`KAKA22/SpreadsheetBench-v2`) into `data/benchmarks/datasets/spreadsheet/`.
3. Generate PPTC label files (`main.py --prepare`).
4. Check LibreOffice availability (warn if missing).
5. Verify FORTE judge importable.
6. Verify `BUB_API_KEY` set.

### 10.4 .gitignore Additions

```gitignore
data/benchmarks/datasets/
data/benchmarks/PPTC/PPT_label_*
results/benchmarks/*/workspaces/
```

## 11. Implementation Phases

| Phase | Scope | Deliverable |
|---|---|---|
| 1 | Core framework | `base.py`, `agent_bridge.py`, `runner.py`, `cli.py`, `results.py`, backdata CSV |
| 2 | PPTC + OfficeBench | 2 deterministic suites — validate full pipeline without judge |
| 3 | SpreadsheetBench 2 | Deterministic categories (Debugging / Financial_Model / Template) |
| 4 | FORTE | LLM judge integration with DeepSeek |
| 5 | Polish | `report.md` generation, `trend`, `compare`, reference scores |
| 6 | Future | JEV judge, Decisions judge, SpreadsheetBench Visualization (VLM), CI smoke |

Phase 1–2 delivers the fastest feedback loop: real benchmark runs with
deterministic evaluation, no LLM judge dependency.

## 12. Constraints & Risks

- **FORTE demo-only tasks**: the public repo ships ~15 demo tasks (one per
  profession), not the full 180. Full dataset may require separate access.
- **SpreadsheetBench 2 Visualization**: requires Windows COM (Excel/WPS) to
  export chart images. Deferred; Linux fallback via LibreOffice is untested.
- **PPTC label generation**: one-time `--prepare` step must succeed before
  evaluation works.
- **Agent capabilities gap**: Office Agent currently supports read text/pdf/xlsx
  and write xlsx/pptx. Benchmarks requiring email, calendar, shell, or Word
  operations (OfficeBench) will fail those tasks — this is expected and measures
  the actual gap.
- **DeepSeek as judge**: not validated against Claude (FORTE default judge) for
  rubric evaluation quality. Dual-judge calibration mode addresses this.
- **Sequential execution**: no parallelism. Full suite runs may be slow. Acceptable
  for CLI-first manual workflow.
