# TDD Evidence Report — Task 2: Per-Request Workspace Binding (office_agent gateway)

- **Source plan:** `docs/superpowers/plans/2026-10-01-benchmark-harness.md` (Task 2)
- **Date:** 2026-10-01
- **Branch:** `main`

## User journeys

1. As a benchmark harness, I want each AG-UI request to confine the agent's
   file tools to a per-task workspace, so tasks never read/write the gateway
   CWD or each other's files.
2. As a gateway operator, I want requests without `state._runtime_workspace`
   to behave exactly as before, so existing clients are unaffected.
3. As a sequential benchmark runner, I want the workspace env restored after
   every call (even a failing one), so one task can never leak its workspace
   into the next.

## Plan-intent verification (before coding)

All three mechanism assumptions from the plan were verified against the
installed agentseek sources in `office_agent/.venv/`:

| Plan assumption | Verified at | Result |
|---|---|---|
| `state["_runtime_workspace"]` → `InvocationContext.workspace` | `agentseek_langchain/plugin.py:38-39` | ✅ |
| `default_runnable_config` writes `str(context.workspace)` into `config["metadata"]["workspace"]` | `agentseek_langchain/spec.py` | ✅ |
| A `**kwargs` proxy receives `config` as a kwarg | `spec.py::_supports_config_argument` (True on `VAR_KEYWORD`) | ✅ |
| `AsyncRunnable` (ainvoke) checked before `SyncRunnable` | `spec.py::invoke_runnable` — proxy needs both methods | ✅ |

## Task report

### RED — failing reproducer

- **Command:** `cd office_agent && uv run pytest tests/test_workspace_binding.py -v`
- **Result:** 1 collection error —
  `ImportError: cannot import name 'WorkspaceScopedRunnable' from 'office_agent.binding'`
  (missing implementation — valid RED, not a setup failure).
- **Commit:** `8a50ab6` `test(agent): add reproducer for per-request workspace binding`

### GREEN — minimal implementation

- **Change:** `office_agent/src/office_agent/binding.py` — added
  `WorkspaceScopedRunnable` (invoke/ainvoke proxy + `_scoped_workspace`
  contextmanager) and wrapped `build_agent()` inside `build_spec()`.
- **Command:** `cd office_agent && uv run pytest tests/ -v`
- **Result:** 15 passed (4 new + all existing `test_binding.py` / `test_tools.py`).
- **Commit:** `b58f683` `feat(agent): bind per-request workspace from AG-UI state into office tools`

### Refactor

None needed — implementation is the minimal wrapper from the plan.

### Coverage hardening (Step 7 review)

Two gaps found and closed (both tests pass immediately; behavior already
implemented, tests pin it down):

- inner runnable raising mid-call still restores the env (finally-path)
- `build_spec()` hands agentseek the wrapped runnable (regression guard)

**Command:** `cd office_agent && uv run pytest tests/ -q` → **17 passed**

**Commit:** `4570644` `test(agent): harden workspace binding coverage — env restore on failure, build_spec wrap guard`

### Manual end-to-end verification (plan Step 5) — PASSED with a deviation

Gateway started with `uv run bub gateway --enable-channel ag-ui`
(credentials from `office_agent/.env`, real DeepSeek model).

- Probe 1 ("List the files in the workspace.") ran the full stack but the
  agent correctly answered it has **no directory-listing tool** (office
  toolset is read/write-by-path only). The plan's "must report marker.txt"
  wording assumed a listing tool; adjusted the probe to a read-by-name.
- Probe 2 ("Read the file marker.txt…", workspace `/tmp/bench_probe` via
  `state._runtime_workspace`): agent returned the exact file content
  `bench-probe-42`. The file does **not** exist in the gateway CWD
  (`office_agent/marker.txt: No such file or directory`), so the read could
  only succeed through the per-request binding.
- Gateway stopped afterwards (port 18088 refuses connections).

## Test specification

| # | What is guaranteed | Test | Type | Result | Evidence |
|---|---|---|---|---|---|
| 1 | `ainvoke` exports `config.metadata.workspace` into `OFFICE_AGENT_WORKSPACE` for the call and removes it afterwards | `test_workspace_binding.py::test_ainvoke_sets_workspace_from_config_metadata` | unit | PASS | `uv run pytest tests/test_workspace_binding.py -v` |
| 2 | No workspace in config metadata → env var untouched | `test_ainvoke_without_workspace_leaves_env_untouched` | unit | PASS | same |
| 3 | Sync `invoke` sets/restores the same way | `test_sync_invoke_sets_workspace` | unit | PASS | same |
| 4 | A pre-existing env value is restored after the call | `test_restores_previous_value` | unit | PASS | same |
| 5 | Inner runnable raising still restores env (no cross-task leak) | `test_restores_env_when_inner_raises` | unit | PASS | same |
| 6 | `build_spec()` wraps the agent (bare agent never reaches agentseek) | `test_build_spec_wraps_agent_in_workspace_scope` | unit | PASS | same |
| 7 | Existing binding behavior unchanged | `test_binding.py` (2 tests) | unit+integration | PASS | `uv run pytest tests/ -q` → 17 passed |
| 8 | Tools still confine paths to the workspace root | `test_tools.py` (9 tests) | unit | PASS | same |
| 9 | Live gateway confines tools to `state._runtime_workspace` end-to-end | manual curl probe (Probe 2 above) | E2E (manual) | PASS | agent returned `bench-probe-42` from `/tmp/bench_probe`; file absent from gateway CWD |

## Coverage and known gaps

- `pytest-cov` is not a dev dependency of `office_agent`; no numeric coverage
  was collected. Branch analysis: every `WorkspaceScopedRunnable` branch
  (workspace present/absent, previous set/unset, sync/async, raise-path) is
  exercised by tests 1–6.
- Untested follow-ups (accepted): concurrent requests to the gateway (env is
  process-global by design — safe only for sequential runs, per plan
  Global Constraints); the `config=None` (no kwarg) path is covered only via
  `(config or {})` short-circuit, not a dedicated test.
- Plan Step 5 wording ("agent must report marker.txt") assumed a
  directory-listing tool the agent does not have; probe adjusted to
  read-by-name, which is a stronger proof (content match, not just a
  filename echo). Deviation recorded here per plan-handoff rules.

## Merge evidence (if commits get squashed)

- RED: `8a50ab6` — failing test, ImportError on `WorkspaceScopedRunnable`.
- GREEN: `b58f683` — wrapper implemented; 15/15 office_agent tests pass.
- Harden: `4570644` — +2 coverage tests; 17/17 pass.
- E2E: live gateway probe read `bench-probe-42` from `/tmp/bench_probe`
  via `state._runtime_workspace`; file absent from gateway CWD.
