# TDD Evidence Report — Task 3: Agent Bridge (AG-UI SSE Client)

- **Source plan:** `docs/superpowers/plans/2026-10-01-benchmark-harness.md` (Task 3)
- **Date:** 2026-10-01
- **Branch:** `main`

## User journeys

1. As a benchmark harness, I want to send a single-turn task to the AG-UI
   gateway and capture the assistant messages, tool calls, and duration,
   so each task produces a complete `AgentOutput`.
2. As a benchmark harness, I want every request to carry the per-task
   workspace in `state._runtime_workspace` (Task 2 mechanism), so the
   agent's tools are confined to that workspace.
3. As a benchmark harness, I want `files_created` to contain only files
   that appeared DURING the run (before/after snapshot diff), so
   pre-existing inputs are never counted as outputs.
4. As a benchmark harness, I want gateway failures (SSE `RUN_ERROR`,
   HTTP ≥ 400, timeout, connection refused) returned as an `[ERROR]`
   `AgentOutput` instead of an exception, so one hiccup cannot abort a
   whole benchmark run.
5. As a benchmark harness, I want multi-turn sessions to reuse one
   `threadId`, resend accumulated history, and keep message ids unique,
   so PPTC-style sessions stay self-contained.
6. As a benchmark harness, I want the SSE parser to match the gateway's
   real wire format (`data:`-only frames, camelCase keys, RUN_ERROR reason
   in `message`), guarded by a live-capture replay test.

## Plan-intent verification (before coding)

- Wire-format assumptions were already verified in Task 2 (live curl probe
  + `ag_ui/encoder/encoder.py` inspection) and codified in the plan's
  revision note; `LIVE_CAPTURE_SSE` in the test is that capture, anonymized.
- The plan's Task 3 code blocks were reviewed at
  `.claude/reviews/task3-agent-bridge-plan-review.md` (commit `38ed734`)
  and the revised plan was followed as written.
- Plan safety checklist: test/implementation code only — no destructive
  filesystem operations, no credential handling, no agent-override
  phrases; validation commands are plain `uv run pytest` (allowlisted).

## Task report

### RED — failing reproducer

- **Command:** `cd benchmarks && uv run pytest tests/test_agent_bridge.py -v`
- **Result:** collection error —
  `ModuleNotFoundError: No module named 'office_bench.agent_bridge'`
  (valid compile-time RED: the new test references the missing module; not
  a setup failure).
- **Commit:** `5fd24a4` `test(bench): add reproducer for AgentBridge AG-UI SSE client`

### GREEN — minimal implementation

- **Change:** created `benchmarks/src/office_bench/agent_bridge.py` —
  `AgentBridge` with `run_task`, `run_session`, `_call_gateway`,
  `_consume_stream`, `_snapshot_files`.
- **Command:** `cd benchmarks && uv run pytest tests/test_agent_bridge.py -v`
- **Result:** **6 passed** (single-turn, mid-run file detection, RUN_ERROR,
  HTTP 500, live-capture replay, multi-turn). Full suite: **15 passed**
  (9 pre-existing Task 1 tests + 6 new).
- **Commit:** `2569ede` `feat(bench): add AgentBridge AG-UI SSE client with single/multi-turn support`

### Refactor

None needed — the implementation is the plan's minimal version. One
hardening was included at implementation time (deviation from the plan's
verbatim code, see below).

### Coverage hardening (Step 7 review)

Three defensive branches were unpinned by the plan's tests; each got a
test (all pass immediately — behavior was already implemented):

- malformed `data:` frame is skipped, not fatal
- unparseable tool-call args kept as `{"raw": ...}`, not dropped
- snapshot of a never-existing workspace dir yields empty, not an error

**Command:** `cd benchmarks && uv run --with pytest-cov pytest tests/ --cov=office_bench --cov-report=term-missing`
→ **18 passed, office_bench 100%** (`agent_bridge.py` 112/112 stmts).

**Commit:** `0914d3d` `test(bench): harden agent bridge coverage — malformed frames, raw args, missing workspace`

## Deviation from the plan (recorded per plan-handoff rules)

`_call_gateway` initializes `resp = None` and closes it in a `finally`
block, so a streamed connection is released even when `raise_for_status()`
raises (the plan's verbatim snippet leaked the response on the HTTP-error
path). No test outcome changes; purely resource hygiene.

## Test specification

| # | What is guaranteed | Test | Type | Result | Evidence |
|---|---|---|---|---|---|
| 1 | Single-turn run returns assistant message, decoded tool call, duration; request payload has user message + `state._runtime_workspace` | `test_run_task_single_turn` | unit+integration (mock HTTP) | PASS | `uv run pytest tests/test_agent_bridge.py -v` |
| 2 | `files_created` = files appearing during the run only (pre-existing inputs excluded) | `test_run_task_detects_files_written_mid_run` | unit+integration | PASS | same |
| 3 | SSE `RUN_ERROR` → `[ERROR] <message>` in output messages (reason from `message` field) | `test_run_task_error_event` | unit+integration | PASS | same |
| 4 | HTTP 500 → `[ERROR]` AgentOutput with no tool calls, no exception | `test_run_task_http_error_returns_error_output` | unit+integration | PASS | same |
| 5 | Parser handles the real gateway's framing (contract vs live capture incl. `STATE_SNAPSHOT`, `input`, `result` fields) | `test_parses_live_gateway_capture` | contract | PASS | same |
| 6 | Multi-turn: same threadId, history resent, unique message ids, same workspace, merged output | `test_run_session_multi_turn` | unit+integration | PASS | same |
| 7 | Malformed `data:` frame skipped without losing the run | `test_run_task_skips_malformed_sse_frames` | unit+integration | PASS | same |
| 8 | Unparseable tool-call args kept verbatim as `{"raw": ...}` | `test_run_task_tool_call_args_unparseable_kept_raw` | unit+integration | PASS | same |
| 9 | Missing workspace dir snapshots empty, run still succeeds | `test_run_task_workspace_missing_yields_no_files` | unit+integration | PASS | same |

## Coverage and known gaps

- **Coverage:** `office_bench` **100%** (166/166 stmts) via ephemeral
  `uv run --with pytest-cov` (dev-group unchanged; `pytest-cov` not added
  to `pyproject.toml`).
- Untested follow-ups (accepted): live end-to-end run of the bridge
  against a real gateway (the wire format is pinned by the capture replay,
  and the full stack incl. workspace binding was probed live in Task 2);
  the timeout/connection-refused paths share the
  `except requests.RequestException` branch with the tested HTTP-500 path
  but are not exercised separately; `_consume_stream` breaking on
  stream EOF without RUN_FINISHED is not separately tested.
- The mock server always sends the full body then closes; real gateways
  keep the connection open after RUN_FINISHED — the parser `break`s on
  RUN_FINISHED/RUN_ERROR, so this difference is immaterial for the tests.

## Merge evidence (if commits get squashed)

- RED: `5fd24a4` — 6-test reproducer; ModuleNotFoundError on
  `office_bench.agent_bridge`.
- GREEN: `2569ede` — AgentBridge implemented; 6/6 bridge tests, 15/15
  full suite.
- Harden: `0914d3d` — +3 coverage tests; 18/18, office_bench 100%.
