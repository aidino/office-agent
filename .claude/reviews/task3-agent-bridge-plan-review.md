# Plan Review: Task 3 — Agent Bridge (AG-UI SSE Client)

**Reviewed**: 2026-10-01
**Scope**: Task 3 code as embedded in `docs/superpowers/plans/2026-10-01-benchmark-harness.md` (lines ~700–1098: `benchmarks/tests/test_agent_bridge.py` + `benchmarks/src/office_bench/agent_bridge.py`)
**Mode**: Plan-section review (same precedent as commit `089db88`) — Task 3 is not yet implemented; no local diff exists
**Decision**: **REQUEST CHANGES** — fix the plan before starting the TDD cycle

## Summary

The bridge's design (payload shape, per-request `state._runtime_workspace`, thread reuse, before/after file snapshots, single/multi-turn split) is sound, but the SSE parser and its mock test encode a **wire format this gateway never emits**. Three separate wire-format mismatches are each verified at source level (`ag_ui` package in `office_agent/.venv`) and against live gateway captures from the Task 2 E2E probe (`/tmp/bench_probe_response*.txt`). The mock server would let the TDD cycle go green while the bridge stays dead against the real gateway — every suite would score 0 for the wrong reason.

## Wire-format evidence

- `ag_ui/encoder/encoder.py:36` — `EventEncoder._encode_sse` emits **`data: {json}\n\n` only**; there are no `event:` lines.
- `ag_ui/_generated/models.py:46` — `alias_generator=to_camel`, encoder dumps `by_alias=True` → wire keys are camelCase.
- Live captures confirm: `{"type":"RUN_STARTED","threadId":...}`, `{"type":"TEXT_MESSAGE_CONTENT","messageId":...,"delta":...}`.

## Findings

### CRITICAL

**C1. Parser waits for `event:` lines the gateway never sends.**
`_call_gateway` sets `event_type` from `line.startswith("event: ")` and dispatches on it. Real stream is `data:`-only with `"type"` inside the JSON, so `event_type` stays `""`, no branch ever matches, nothing is collected, and the loop only ends when the server closes the stream.
*Fix:* parse `data:` lines, dispatch on `data.get("type")`. Update the mock's `_sse_line` helper to emit `data: {"type": "<EVENT>", ...}`.

### HIGH

**H1. `test_run_task_scans_workspace_files` contradicts the before/after snapshot design.**
The test pre-creates `output.xlsx` before calling `run_task`, so it lands in **both** snapshots; the set difference is empty and the assertion fails for the wrong reason — inviting a "fix" that would count input files as created and break the Suite contract.
*Fix:* have the mock handler write the file into the workspace when it receives the POST (simulating the agent writing mid-run), e.g. via a class attribute the test sets.

**H2. RUN_ERROR field mismatch: parser reads `error`, wire carries `message`.**
`RunErrorEvent` (`ag_ui/_generated/models.py:1894`) has required `message: str` + optional `code`. `data.get("error", "Unknown error")` always yields "Unknown error" from the real gateway — every failure loses its reason (and the suite's error note).
*Fix:* `data.get("message") or data.get("error") or "Unknown error"`; mock should emit `message`.

**H3. Tool name field mismatch: parser reads `toolName`, wire carries `toolCallName`.**
`ToolCallStartEvent` fields are `tool_call_id`/`tool_call_name` → camelCase wire keys `toolCallId`/`toolCallName`. The mock emits `toolName`, matching the parser but not the gateway: real runs would record `name: ""` for every tool call — exactly the signal suites need for debugging.
*Fix:* read `data.get("toolCallName", "")`; mock emits `toolCallName`.

### MEDIUM

**M1. All text deltas merge into one assistant message regardless of `messageId`.**
DeepAgents runs can emit several assistant messages (per tool round). Flat concatenation interleaves them. *Fix:* accumulate per `messageId` (announced by TEXT_MESSAGE_START), append each at TEXT_MESSAGE_END.

**M2. Duplicate message ids in `run_session` history.**
Turn *i* gives every assistant reply the same id `m{i*2+2}` — a turn with >1 assistant message sends duplicate ids in the payload (protocol violation). *Fix:* derive ids from a running counter.

**M3. HTTP-level failures unhandled/untested.**
`raise_for_status()` (and connect/timeout errors) raise out of `run_task` with no catch here or in the planned Runner — one gateway hiccup mid-benchmark aborts the whole run. *Fix:* catch `requests.RequestException` and return an `AgentOutput` carrying `[ERROR] …` (consistent with RUN_ERROR handling), and add one test (mock returning 500).

**M4. Error message may not be last.**
`text_parts` are appended after the loop; when a run errors mid-stream *after* emitting text, `messages[-1]` is the text, not the error — the plan's own error test (`output.messages[-1]`) is brittle against real streams. *Fix:* append the error message last, or have consumers search for the `[ERROR]` marker.

### LOW

- **L1.** Streamed `resp` never closed explicitly after `break` on RUN_FINISHED; use `with`/`resp.close()` for long runs.
- **L2.** `run_session` resends full history each turn; the gateway builds its prompt from the last user message only (`channel.py::_select_message_payload`), so the accumulation is redundant but harmless — worth a comment, not a change.

## Validation Results

| Check | Result |
|---|---|
| benchmarks suite (baseline) | Pass — 9 passed |
| office_agent suite (baseline) | Pass — 17 passed |
| Task 3 tests | Not yet implemented (review target is the plan) |

## Files Reviewed

- `docs/superpowers/plans/2026-10-01-benchmark-harness.md` — Task 3 section (planned code)
- Evidence sources (read-only): `ag_ui/encoder/encoder.py`, `ag_ui/_generated/models.py`, `agentseek_ag_ui/channel.py`, live SSE captures from Task 2 probe

## Next steps

1. Apply C1, H1–H3 (and ideally M1–M4) to the Task 3 section of the plan.
2. Re-run this review on the amended plan section, then start the Task 3 TDD cycle.
3. Optional hardening: add a contract test that replays the captured live SSE stream (`/tmp/bench_probe_response2.txt`) through the parser — the strongest guard against mock/wire drift.
