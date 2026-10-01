# Office Agent Benchmark Harness (`office_bench`)

A standalone CLI harness that evaluates Office Agent across four external
benchmark suites, tracks performance over time via an append-only backdata
CSV, and generates Markdown comparison reports.

## Architecture

```
benchmarks/
├── src/office_bench/
│   ├── cli.py              # CLI: run, report, list, trend, compare, setup
│   ├── runner.py            # Orchestrator: load → run → evaluate → persist
│   ├── agent_bridge.py      # AG-UI SSE client (single integration point)
│   ├── results.py           # JSON persistence + Markdown report + backdata CSV
│   ├── reference.py         # Published leaderboard scores for comparison
│   ├── suites/
│   │   ├── base.py          # Suite protocol + shared data types
│   │   ├── forte.py         # FORTE adapter (LLM judge + automated)
│   │   ├── officebench.py   # OfficeBench adapter (deterministic)
│   │   ├── spreadsheet.py   # SpreadsheetBench 2 adapter (cell comparison)
│   │   └── pptc.py          # PPTC adapter (PPTX-Match)
│   └── judges/
│       ├── base.py          # JudgeBackend protocol
│       └── llm.py           # LLM judge via OpenAI-compatible API (DeepSeek)
└── tests/
    ├── test_*.py            # Unit tests (165 tests)
    └── e2e/                 # End-to-end tests (33 tests)
        ├── test_suite_runs.py         # Per-suite CLI flows + filters
        ├── test_post_run_commands.py  # report, trend, compare, list
        ├── test_artifacts.py          # Result JSON/CSV/report validation
        └── test_llm_judge_live.py     # Live DeepSeek API tests
```

## Benchmark Suites

| Suite | Source Repo | Tasks | Evaluation |
|---|---|---|---|
| FORTE | `AGI-Eval-Official/FORTE` | 180 tasks, 15 professions | LLM-as-judge + automated + hybrid |
| OfficeBench | `zlwang-cs/OfficeBench` | 300 tasks, multi-app chains | Deterministic: exact/fuzzy match, file exist |
| SpreadsheetBench 2 | `RUCKBReasoning/SpreadsheetBench-2` | 4 categories | Deterministic cell-level comparison |
| PPTC | `gydpku/PPTC` | ~350+ sessions | Deterministic PPTX-Match |

All four repos are added as git submodules under `data/benchmarks/`.

## Prerequisites

- Python ≥ 3.12
- [uv](https://docs.astral.sh/uv/) for dependency management
- LibreOffice (for SpreadsheetBench formula recalculation)
- Office Agent gateway running at `http://127.0.0.1:18088/agent`

## Setup

```bash
cd benchmarks
uv sync

# Clone submodules, check datasets, verify prerequisites
uv run python -m office_bench setup
```

## CLI Reference

<!-- GENERATED:cli-reference — do not edit manually -->

| Command | Description |
|---|---|
| `office_bench setup` | Clone submodules, download datasets, verify prerequisites |
| `office_bench list --suite SUITE` | List available tasks for a suite |
| `office_bench run` | Run benchmark evaluation |
| `office_bench report --run-id ID` | Regenerate Markdown report for an existing run |
| `office_bench trend [--suite SUITE]` | Show performance trend from backdata CSV |
| `office_bench compare --runs ID1 ID2` | Compare two runs side by side |

### `run` Options

| Flag | Default | Description |
|---|---|---|
| `--suite` | `all` | Comma-separated suite names or `all` |
| `--runs` | `1` | Number of runs per task (for Avg@N / Pass@N) |
| `--task-id` | — | Comma-separated task IDs to filter |
| `--category` | — | Comma-separated categories to filter |
| `--limit` | — | Max tasks per suite |
| `--run-id` | auto | Resume an existing run directory |
| `--keep-workspaces` | `false` | Preserve per-task workspace directories |
| `--no-resume` | `false` | Re-run tasks even if results exist |
| `--dual-judge` | `false` | Run both LLM and alternative judge |
| `--gateway-url` | `http://127.0.0.1:18088/agent` | AG-UI gateway URL |
| `--timeout` | `600` | Per-task timeout in seconds |

<!-- /GENERATED:cli-reference -->

## Environment Variables

<!-- GENERATED:env-vars — do not edit manually -->

| Variable | Required | Description | Default |
|---|---|---|---|
| `JUDGE_MODEL` | For FORTE | LLM judge model name | `deepseek-chat` |
| `JUDGE_BASE_URL` | For FORTE | Judge API base URL | `https://api.deepseek.com` |
| `JUDGE_API_KEY` | For FORTE | Judge API key | Falls back to `BUB_API_KEY` |
| `BUB_MODEL` | No | Recorded in run metadata | — |

<!-- /GENERATED:env-vars -->

## Usage Examples

```bash
# Run FORTE on 5 tasks with 2 runs each
uv run python -m office_bench run --suite forte --limit 5 --runs 2

# Run OfficeBench filtering to 1-app tasks
uv run python -m office_bench run --suite officebench --category 1

# Resume an interrupted run
uv run python -m office_bench run --suite forte --run-id 2026-10-01_143000

# Compare two runs
uv run python -m office_bench compare --runs 2026-10-01_143000 2026-10-01_160000

# Show performance trend for FORTE
uv run python -m office_bench trend --suite forte
```

## Output Artifacts

Each run produces:

```
results/benchmarks/<run-id>/
├── meta.json                    # Run metadata (timestamp, git commit, model, suites)
├── report.md                    # Markdown report with scores + reference comparison
├── forte/
│   ├── finance-001_run1.json    # Per-task result with agent output
│   └── ...
├── officebench/
│   └── ...
└── ...
results/benchmarks/backdata.csv  # Append-only trend data
```

### Result JSON Schema

```json
{
  "task_id": "finance-001",
  "suite": "forte",
  "run": 1,
  "passed": true,
  "score": 1.0,
  "breakdown": {"01": 1.0, "02": 1.0},
  "judge_backend": "deterministic+llm:deepseek-chat",
  "notes": "All rubrics passed",
  "duration_seconds": 45.2,
  "agent_output": {
    "response_text": "...",
    "tool_calls": [...],
    "files_created": [...]
  },
  "timestamp": "2026-10-01T14:30:00+00:00"
}
```

## Testing

```bash
# Unit tests only (fast, no network)
uv run pytest tests/ -v --ignore=tests/e2e/

# E2E tests (includes live LLM judge tests hitting DeepSeek API)
uv run pytest tests/e2e/ -v

# Full suite with coverage
uv run pytest tests/ --cov=office_bench --cov-report=term-missing
```

**Coverage:** 95% across 198 tests (165 unit + 33 E2E).

## Design

- **Hybrid approach**: bypass each benchmark's agent runtime; keep their evaluation logic
- **Immutable data types**: all `Task`, `AgentOutput`, `TaskResult` are frozen dataclasses
- **Suite protocol**: pluggable adapters implement `Suite` (load, setup, prompt, evaluate)
- **Workspace isolation**: each task runs in its own `tempfile.mkdtemp()`
- **Resume support**: completed task results are skipped on re-run
- **Append-only CSV**: backdata never rewrites existing rows

For the full design spec, see
[`docs/superpowers/specs/2026-10-01-benchmark-harness-design.md`](../docs/superpowers/specs/2026-10-01-benchmark-harness-design.md).
