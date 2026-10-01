# Runbook — Benchmark Operations

Operational procedures for running benchmarks, troubleshooting, and
maintaining the harness.

## Running a Benchmark

### 1. Prerequisites Check

```bash
cd benchmarks
uv run python -m office_bench setup
```

Verifies:
1. Git submodules cloned under `data/benchmarks/`
2. SpreadsheetBench 2 HuggingFace dataset present
3. PPTC label files generated (`main.py --prepare`)
4. LibreOffice available for formula recalculation
5. FORTE judge module importable
6. `JUDGE_API_KEY` or `BUB_API_KEY` set

### 2. Start the Agent Gateway

```bash
cd office_agent
uvx agentseek dev
```

Verify health:
```bash
curl -sS http://127.0.0.1:18088/agent/health
```

### 3. Run the Benchmark

```bash
cd benchmarks

# Full run across all suites
uv run python -m office_bench run --suite all

# Single suite with limits (good for testing)
uv run python -m office_bench run --suite forte --limit 10 --runs 1

# Multiple suites
uv run python -m office_bench run --suite forte,officebench
```

### 4. Review Results

```bash
# Read the report
cat results/benchmarks/<run-id>/report.md

# View trend over time
uv run python -m office_bench trend

# Compare two runs
uv run python -m office_bench compare --runs <id1> <id2>
```

## Resuming an Interrupted Run

If a run is interrupted (gateway crash, network timeout, Ctrl-C):

```bash
# Resume using the same run-id — completed tasks are skipped
uv run python -m office_bench run --suite forte --run-id <run-id>
```

The harness checks each `{task_id}_run{N}.json` for completeness before
skipping. Crash-truncated files are detected and re-run.

**Backdata safety**: the CSV append is idempotent — resuming never creates
duplicate rows for the same (run_id, suite) pair.

## Troubleshooting

### Gateway Connection Refused

```
[ERROR] gateway request failed: ConnectionError
```

**Cause**: Agent gateway not running or wrong URL.

**Fix**:
1. Verify gateway: `curl http://127.0.0.1:18088/agent/health`
2. Start gateway: `cd office_agent && uvx agentseek dev`
3. If using a different port: `--gateway-url http://host:port/agent`

### FORTE Judge API Error

```
Judge API error: 401 Unauthorized
```

**Cause**: Missing or invalid `JUDGE_API_KEY`.

**Fix**:
1. Check: `echo $JUDGE_API_KEY` (or `$BUB_API_KEY` as fallback)
2. Set in `office_agent/.env` or export directly
3. Verify key at [platform.deepseek.com](https://platform.deepseek.com/api_keys)

### SpreadsheetBench Recalculation Failure

```
LibreOffice recalc failed for debug-001.xlsx
```

**Cause**: LibreOffice not installed or `soffice` not in PATH.

**Fix**:
```bash
# Ubuntu/Debian
sudo apt install libreoffice-calc

# Verify
which soffice
```

### PPTC Label Files Missing

```
Label pptx not found — run the PPTC prepare step
```

**Cause**: PPTC label files not generated yet.

**Fix**:
```bash
cd data/benchmarks/PPTC
python main.py --prepare
```

### Submodules Not Cloned

```
Suite 'forte' — 0 tasks loaded
```

**Cause**: Git submodules not initialized.

**Fix**:
```bash
git submodule update --init --recursive
# Or use the setup command:
uv run python -m office_bench setup
```

### Task Crash (Isolated)

```
warning: task forte/finance-001 run 1 crashed: <exception> — recorded as failed
```

**Cause**: Individual task error (setup, bridge, or evaluation). The run
continues — one crash never aborts the whole suite.

**Action**: Check the result JSON for the crashed task:
```bash
cat results/benchmarks/<run-id>/forte/finance-001_run1.json
```
The `notes` field contains the exception details.

## Maintenance

### Updating Benchmark Submodules

```bash
git submodule update --remote data/benchmarks/FORTE
git submodule update --remote data/benchmarks/OfficeBench
git submodule update --remote data/benchmarks/SpreadsheetBench-2
git submodule update --remote data/benchmarks/PPTC
```

After updating, re-run `setup` to verify compatibility:
```bash
uv run python -m office_bench setup
```

### Cleaning Up Results

Results under `results/benchmarks/` are git-tracked. To remove old runs:
```bash
# Delete a specific run (preserves backdata CSV rows)
rm -rf results/benchmarks/<run-id>

# The backdata CSV is append-only — do NOT edit or truncate it
```

### Running Tests After Changes

```bash
cd benchmarks

# Fast check (no network)
uv run pytest tests/ --ignore=tests/e2e/ -q

# Full suite including live LLM judge
uv run pytest tests/ -v

# Coverage
uv run pytest tests/ --cov=office_bench --cov-report=term-missing
```

Target: ≥ 80% coverage. Current: 95% (198 tests).

## Monitoring Checklist

After a benchmark run, verify:

- [ ] `report.md` generated with scores for all requested suites
- [ ] `backdata.csv` has exactly one new row per suite
- [ ] No `warning: task ... crashed` messages (or investigate if present)
- [ ] Score is within expected range vs. reference models
- [ ] `meta.json` records correct git commit and agent version
