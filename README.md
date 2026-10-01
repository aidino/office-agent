# office-agent

Office Agent — a backend-only office agent (Python, DeepAgents) that reads
and writes documents, spreadsheets, and presentations, exposed through an
AG-UI gateway on `http://127.0.0.1:18088/agent`. Defaults to the DeepSeek
`deepseek-flash` model via DeepSeek's OpenAI-compatible endpoint.

## Repository Structure

```
office-agent/
├── office_agent/          # Agent runtime — DeepAgents + AG-UI gateway
│   ├── src/office_agent/  # binding, tools, settings
│   ├── tests/             # unit tests (binding, tools, workspace)
│   └── .env.example       # runtime config template
├── benchmarks/            # Benchmark harness (office_bench CLI)
│   ├── src/office_bench/  # CLI, runner, suites, judges
│   └── tests/             # unit + E2E tests (198 total, 95% coverage)
├── data/benchmarks/       # git submodules (FORTE, OfficeBench, etc.)
├── results/benchmarks/    # run results + backdata.csv (git-tracked)
└── docs/                  # specs, plans, ENV, CONTRIBUTING, RUNBOOK
```

## Packages

| Package | Path | Description |
|---|---|---|
| `office_agent` | `office_agent/` | DeepAgents agent with office file tools, exposed via AG-UI |
| `office_bench` | `benchmarks/` | CLI harness evaluating the agent across 4 benchmark suites |

## Quick Start

### Agent

```bash
cd office_agent
cp .env.example .env
$EDITOR .env                  # set BUB_API_KEY to a DeepSeek API key

uvx agentseek doctor          # verify environment
uvx agentseek dev             # start gateway at :18088
```

### Benchmark Harness

```bash
cd benchmarks
uv sync

# Clone benchmark repos + check prerequisites
uv run python -m office_bench setup

# Run a suite (agent gateway must be running)
uv run python -m office_bench run --suite forte --limit 5

# View results
uv run python -m office_bench trend
```

See [`office_agent/README.md`](office_agent/README.md) for agent details
and [`benchmarks/README.md`](benchmarks/README.md) for harness documentation.

## Documentation

| Document | Description |
|---|---|
| [`office_agent/README.md`](office_agent/README.md) | Agent quickstart, environment, tools, testing |
| [`benchmarks/README.md`](benchmarks/README.md) | Benchmark harness architecture, CLI reference, suites |
| [`docs/ENV.md`](docs/ENV.md) | All environment variables across both packages |
| [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) | Development workflow, testing, code style |
| [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | Benchmark operations, troubleshooting, maintenance |

## License

See [LICENSE](LICENSE).
