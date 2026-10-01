# Contributing

Development guide for the `office-agent` repository.

## Prerequisites

- Python ≥ 3.12
- [uv](https://docs.astral.sh/uv/) — dependency management and virtual environments
- [git](https://git-scm.com/) — with submodule support
- LibreOffice (optional — needed for SpreadsheetBench formula recalculation)

## Repository Layout

The repo contains two independent Python packages managed with `uv`:

```
office_agent/    # Agent runtime (DeepAgents + AG-UI gateway)
benchmarks/      # Benchmark harness (office_bench CLI)
```

Each has its own `pyproject.toml`, virtual environment, and test suite.

## Setup

```bash
# Clone with submodules
git clone --recurse-submodules <repo-url>
cd office-agent

# Agent package
cd office_agent
cp .env.example .env
$EDITOR .env              # set BUB_API_KEY
uv sync

# Benchmark harness
cd ../benchmarks
uv sync
```

## Development Workflow

1. **Plan first** — for multi-file changes, write an implementation plan
2. **Write tests first** (TDD) — RED → GREEN → REFACTOR
3. **Run tests** — verify before committing
4. **Code review** — address CRITICAL/HIGH issues before merge
5. **Commit** — follow conventional commits format

## Commands Reference

<!-- GENERATED:commands — do not edit manually -->

### Agent (`office_agent/`)

| Command | Description |
|---|---|
| `uv sync` | Install dependencies |
| `uv run pytest -q` | Run agent unit tests |
| `uvx agentseek info` | Show env vars and lifecycle wiring |
| `uvx agentseek doctor` | Lifecycle spec, uv, paths, env checks |
| `uvx agentseek dev` | Start gateway in foreground (port 18088) |
| `uvx agentseek task sync` | Install Python dependencies via lifecycle |

### Benchmark Harness (`benchmarks/`)

| Command | Description |
|---|---|
| `uv sync` | Install dependencies |
| `uv run pytest tests/ -v` | Run all tests (unit + E2E) |
| `uv run pytest tests/ --cov=office_bench` | Run with coverage report |
| `uv run pytest tests/ --ignore=tests/e2e/` | Unit tests only (fast, no network) |
| `uv run pytest tests/e2e/ -v` | E2E tests (includes live LLM judge) |
| `uv run python -m office_bench setup` | Clone submodules + verify prerequisites |
| `uv run python -m office_bench run --suite forte` | Run FORTE benchmark |
| `uv run python -m office_bench trend` | View performance trend |

<!-- /GENERATED:commands -->

## Testing

### Test Structure

```
office_agent/tests/
├── test_binding.py          # Binding registration + stub-server integration
├── test_tools.py            # Workspace confinement + tool behavior
└── test_workspace_binding.py # Per-request workspace scoping

benchmarks/tests/
├── test_*.py                # Unit tests (165 tests)
└── e2e/                     # End-to-end tests (33 tests)
    ├── test_suite_runs.py   # CLI → adapter → evaluate → artifacts
    ├── test_post_run_commands.py  # report, trend, compare, list
    ├── test_artifacts.py    # Result schema + CSV + report validation
    └── test_llm_judge_live.py     # Live DeepSeek API calls
```

### Running Tests

```bash
# Agent tests
cd office_agent && uv run pytest -q

# Benchmark unit tests (no network, fast)
cd benchmarks && uv run pytest tests/ --ignore=tests/e2e/ -v

# Benchmark full suite (includes live API calls)
cd benchmarks && uv run pytest tests/ -v

# Coverage
cd benchmarks && uv run pytest tests/ --cov=office_bench --cov-report=term-missing
```

**Coverage target: ≥ 80%.** Current: 95%.

### Writing Tests

- Follow AAA pattern (Arrange-Act-Assert)
- Descriptive test names: `test_evaluate_cell_value_pass`
- Use `tmp_path` for file system tests
- Monkeypatch external calls (LibreOffice, network)
- E2E tests mock `AgentBridge` only; suite adapters run for real

## Code Style

### Conventions

- **Immutable data**: frozen dataclasses, never mutate existing objects
- **Type hints**: all function signatures must have type annotations
- **Docstrings**: module-level and public functions
- **File size**: soft ceiling of 800 lines per source file
- **Function size**: < 50 lines preferred
- **Naming**: `snake_case` for functions/variables, `PascalCase` for classes
- **Constants**: `UPPER_SNAKE_CASE`

### Error Handling

- Handle errors explicitly; never silently swallow exceptions
- Use typed exceptions where possible
- Log warnings for recoverable errors (task crashes, missing files)

## Commit Messages

```
<type>: <description>

<optional body>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`

Examples:
```
feat(bench): add FORTE suite adapter and LLM judge backend
fix(bench): cache grader module, use deterministic module name
test(bench): add E2E tests for per-suite CLI runs
docs: update README with benchmark harness section
```

## Architecture Decisions

Key design decisions are documented in:
- [`docs/superpowers/specs/2026-10-01-benchmark-harness-design.md`](superpowers/specs/2026-10-01-benchmark-harness-design.md) — benchmark harness design spec
- [`docs/superpowers/plans/2026-10-01-benchmark-harness.md`](superpowers/plans/2026-10-01-benchmark-harness.md) — implementation plan with 12 tasks

### Key Invariants

- Benchmark submodule source code is **never modified**
- `office_agent/` source is unchanged except `binding.py` (workspace scoping)
- Backdata CSV is **append-only** — never rewrite existing rows
- All data types are **frozen dataclasses**
- Per-task workspaces are isolated via `tempfile.mkdtemp()`
