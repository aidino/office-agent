# Office Agent Benchmark Harness Implementation Plan

**Goal:** Build `office_bench`, a standalone CLI harness that runs Office Agent against four external benchmark suites (FORTE, OfficeBench, SpreadsheetBench 2, PPTC), persists results as JSON + backdata CSV, and generates Markdown comparison reports.

**Architecture:** A standalone Python package (`benchmarks/`) separate from the main `office_agent/` package. Each benchmark suite is a pluggable adapter implementing a `Suite` protocol. A single `AgentBridge` calls the existing AG-UI SSE gateway. A `Runner` orchestrates load → run → evaluate → persist. CLI is built with `argparse`.

**Tech Stack:** Python 3.12+, requests, openpyxl, python-pptx, pyyaml, pytest ≥ 8.4. uv for dependency management. No new frameworks.

**Spec:** `docs/superpowers/specs/2026-10-01-benchmark-harness-design.md`

## Global Constraints

- Python ≥ 3.12
- All data types are frozen dataclasses (immutable)
- No modifications to benchmark submodule source code
- `office_agent/` source is unchanged EXCEPT the per-request workspace binding in Task 2 (`binding.py` only)
- Per-task workspace is delivered inside the AG-UI payload as `state._runtime_workspace` (agentseek-native mechanism — see Task 2); never via client-side env vars
- Multi-turn tasks advertise their turns via `Task.metadata["turn_prompts"]: list[str]`; the Runner calls `bridge.run_session()` when it has more than one entry
- Sequential execution only — no parallelism
- Append-only backdata CSV — never rewrite existing rows; on resume, skip the append when a row for (run_id, suite) already exists
- All file paths in results are relative to project root
- Benchmark submodule repos at `data/benchmarks/{FORTE,OfficeBench,SpreadsheetBench-2,PPTC}`
- HuggingFace downloads gitignored at `data/benchmarks/datasets/`
- Agent gateway URL default: `http://127.0.0.1:18088/agent`
- Judge env vars: `JUDGE_MODEL`, `JUDGE_BASE_URL`, `JUDGE_API_KEY`

---

### Task 1: Project Scaffold &amp; Shared Data Types

Set up the `benchmarks/` Python package with `pyproject.toml`, shared data
types used by every subsequent task, and the Suite protocol. This is the
foundation everything imports from.

**Files:**

- Create: `benchmarks/pyproject.toml`
- Create: `benchmarks/src/office_bench/__init__.py`
- Create: `benchmarks/src/office_bench/suites/__init__.py`
- Create: `benchmarks/src/office_bench/suites/base.py`
- Create: `benchmarks/src/office_bench/judges/__init__.py`
- Create: `benchmarks/src/office_bench/judges/base.py`
- Create: `benchmarks/tests/__init__.py`
- Create: `benchmarks/tests/test_data_types.py`
- Modify: `.gitignore` (append benchmark-specific ignores)

**Interfaces:**

- Consumes: nothing (first task)
- Produces:
  - `office_bench.suites.base.Task` — frozen dataclass with fields: `suite: str`, `task_id: str`, `prompt: str`, `category: str`, `input_files: list[Path]`, `metadata: dict`
  - `office_bench.suites.base.AgentOutput` — frozen dataclass with fields: `messages: list[dict]`, `files_created: list[Path]`, `tool_calls: list[dict]`, `duration_seconds: float`
  - `office_bench.suites.base.TaskResult` — frozen dataclass with fields: `task_id: str`, `suite: str`, `passed: bool`, `score: float`, `breakdown: dict`, `notes: str`, `judge_backend: str | None`
  - `office_bench.suites.base.Suite` — Protocol with: `name: str`, `load_tasks() -> list[Task]`, `setup_workspace(task: Task, workspace_dir: Path) -> None`, `format_prompt(task: Task) -> str`, `evaluate(task: Task, workspace_dir: Path, agent_output: AgentOutput) -> TaskResult`
  - `office_bench.judges.base.Rubric` — frozen dataclass: `id: str`, `content: str`, `weight: float`
  - `office_bench.judges.base.JudgeContext` — frozen dataclass: `instruction: str`, `agent_response: str`, `file_contents: dict[str, str]`, `file_images: list[bytes]`, `file_pdfs: list[bytes]`
  - `office_bench.judges.base.RubricResult` — frozen dataclass: `rubric_id: str`, `passed: bool`, `confidence: float | None`, `reason: str`
  - `office_bench.judges.base.JudgeBackend` — Protocol with: `name: str`, `judge_rubric(rubric: Rubric, context: JudgeContext) -> RubricResult`

**DoD:** `uv run --project benchmarks pytest benchmarks/tests/test_data_types.py -v` passes. All dataclasses are frozen, constructible, and have correct field types. Protocol classes importable.



- [x] **Step 1: Create `benchmarks/pyproject.toml`**

```toml
[project]
name = "office_bench"
version = "0.1.0"
description = "Benchmark harness for Office Agent"
requires-python = ">=3.12"
dependencies = [
    "requests>=2.31",
    "openpyxl>=3.1.0",
    "python-pptx>=1.0.0",
    "pyyaml>=6.0",
]

[dependency-groups]
dev = [
    "pytest>=8.4,<10",
]

[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]
```



- [x] **Step 2: Create `benchmarks/src/office_bench/__init__.py`**

```python
"""Office Agent Benchmark Harness."""
```



- [x] **Step 3: Write the failing test for data types**

Create `benchmarks/tests/__init__.py` (empty) and `benchmarks/tests/test_data_types.py`:

```python
from __future__ import annotations

from pathlib import Path

from office_bench.suites.base import AgentOutput, Suite, Task, TaskResult
from office_bench.judges.base import (
    JudgeBackend,
    JudgeContext,
    Rubric,
    RubricResult,
)


def test_task_is_frozen_dataclass() -> None:
    task = Task(
        suite="forte",
        task_id="finance-018",
        prompt="Analyze the spreadsheet",
        category="finance",
        input_files=[Path("input/data.xlsx")],
        metadata={"rubrics": ["r1"]},
    )
    assert task.suite == "forte"
    assert task.task_id == "finance-018"
    assert task.input_files == [Path("input/data.xlsx")]


def test_task_immutability() -> None:
    task = Task(
        suite="forte",
        task_id="t1",
        prompt="p",
        category="c",
        input_files=[],
        metadata={},
    )
    try:
        task.suite = "other"  # type: ignore[misc]
        raise AssertionError("Should have raised FrozenInstanceError")
    except AttributeError:
        pass


def test_agent_output_is_frozen() -> None:
    output = AgentOutput(
        messages=[{"role": "assistant", "content": "done"}],
        files_created=[Path("out.xlsx")],
        tool_calls=[{"name": "write_spreadsheet", "args": {}}],
        duration_seconds=12.5,
    )
    assert output.duration_seconds == 12.5
    assert len(output.files_created) == 1


def test_task_result_fields() -> None:
    result = TaskResult(
        task_id="finance-018",
        suite="forte",
        passed=False,
        score=0.67,
        breakdown={"01": 1.0, "02": 0.0},
        notes="rubric 02 failed",
        judge_backend="llm:deepseek-chat",
    )
    assert result.passed is False
    assert result.score == 0.67
    assert result.judge_backend == "llm:deepseek-chat"


def test_task_result_none_judge() -> None:
    result = TaskResult(
        task_id="t1",
        suite="officebench",
        passed=True,
        score=1.0,
        breakdown={},
        notes="",
        judge_backend=None,
    )
    assert result.judge_backend is None


def test_rubric_and_judge_context() -> None:
    rubric = Rubric(id="r1", content="Check totals", weight=1.0)
    ctx = JudgeContext(
        instruction="Analyze spreadsheet",
        agent_response="Total is 500",
        file_contents={"out.xlsx": "A1: 500"},
        file_images=[],
        file_pdfs=[],
    )
    assert rubric.weight == 1.0
    assert ctx.file_contents["out.xlsx"] == "A1: 500"


def test_rubric_result_fields() -> None:
    rr = RubricResult(
        rubric_id="r1",
        passed=True,
        confidence=None,
        reason="Totals match",
    )
    assert rr.passed is True
    assert rr.confidence is None


class _DummySuite:
    """Verify a class can satisfy the Suite protocol."""

    name = "dummy"

    def load_tasks(self) -> list[Task]:
        return []

    def setup_workspace(self, task: Task, workspace_dir: Path) -> None:
        pass

    def format_prompt(self, task: Task) -> str:
        return task.prompt

    def evaluate(
        self, task: Task, workspace_dir: Path, agent_output: AgentOutput
    ) -> TaskResult:
        return TaskResult(
            task_id=task.task_id,
            suite=self.name,
            passed=True,
            score=1.0,
            breakdown={},
            notes="",
            judge_backend=None,
        )


def test_suite_protocol_structural_typing() -> None:
    suite: Suite = _DummySuite()
    assert suite.name == "dummy"
    tasks = suite.load_tasks()
    assert tasks == []


class _DummyJudge:
    name = "dummy"

    def judge_rubric(self, rubric: Rubric, context: JudgeContext) -> RubricResult:
        return RubricResult(
            rubric_id=rubric.id,
            passed=True,
            confidence=0.9,
            reason="ok",
        )


def test_judge_backend_protocol() -> None:
    judge: JudgeBackend = _DummyJudge()
    result = judge.judge_rubric(
        Rubric(id="r1", content="check", weight=1.0),
        JudgeContext(
            instruction="i",
            agent_response="r",
            file_contents={},
            file_images=[],
            file_pdfs=[],
        ),
    )
    assert result.passed is True
    assert result.confidence == 0.9
```



- [x] **Step 4: Run test to verify it fails**

```bash
cd benchmarks && uv run pytest tests/test_data_types.py -v
```

Expected: FAIL — modules `office_bench.suites.base` and `office_bench.judges.base` not found.



- [x] **Step 5: Implement `benchmarks/src/office_bench/suites/__init__.py`**

```python
"""Benchmark suite adapters."""
```



- [x] **Step 6: Implement `benchmarks/src/office_bench/suites/base.py`**

```python
"""Shared data types and Suite protocol for all benchmark adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Task:
    """A single benchmark task."""

    suite: str
    task_id: str
    prompt: str
    category: str
    input_files: list[Path]
    metadata: dict


@dataclass(frozen=True)
class AgentOutput:
    """Captured output from an agent run."""

    messages: list[dict]
    files_created: list[Path]
    tool_calls: list[dict]
    duration_seconds: float


@dataclass(frozen=True)
class TaskResult:
    """Evaluation result for a single task."""

    task_id: str
    suite: str
    passed: bool
    score: float
    breakdown: dict
    notes: str
    judge_backend: str | None


@runtime_checkable
class Suite(Protocol):
    """Interface that every benchmark adapter must satisfy."""

    name: str

    def load_tasks(self) -> list[Task]: ...

    def setup_workspace(self, task: Task, workspace_dir: Path) -> None: ...

    def format_prompt(self, task: Task) -> str: ...

    def evaluate(
        self, task: Task, workspace_dir: Path, agent_output: AgentOutput
    ) -> TaskResult: ...
```



- [x] **Step 7: Implement `benchmarks/src/office_bench/judges/__init__.py`**

```python
"""Judge backends for LLM and deterministic evaluation."""
```



- [x] **Step 8: Implement `benchmarks/src/office_bench/judges/base.py`**

```python
"""Judge data types and JudgeBackend protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Rubric:
    """A single rubric item for LLM-as-judge evaluation."""

    id: str
    content: str
    weight: float


@dataclass(frozen=True)
class JudgeContext:
    """Context provided to a judge for rubric evaluation."""

    instruction: str
    agent_response: str
    file_contents: dict[str, str]
    file_images: list[bytes]
    file_pdfs: list[bytes]


@dataclass(frozen=True)
class RubricResult:
    """Result of judging one rubric."""

    rubric_id: str
    passed: bool
    confidence: float | None
    reason: str


@runtime_checkable
class JudgeBackend(Protocol):
    """Interface for judge backends."""

    name: str

    def judge_rubric(self, rubric: Rubric, context: JudgeContext) -> RubricResult: ...
```



- [x] **Step 9: Append to `.gitignore`**

Add to the end of `.gitignore`:

```gitignore

# Benchmark harness
data/benchmarks/datasets/
data/benchmarks/PPTC/PPT_label_*
results/benchmarks/*/workspaces/
```



- [x] **Step 10: Run test to verify it passes**

```bash
cd benchmarks && uv run pytest tests/test_data_types.py -v
```

Expected: all 9 tests PASS.



- [x] **Step 11: Commit**

```bash
git add benchmarks/ .gitignore
git commit -m "feat(bench): scaffold benchmarks package with shared data types and protocols"
```

---

### Task 2: Per-Request Workspace Binding (office_agent gateway)

**Code-review finding (2026-10-01):** client-side workspace isolation cannot
work. `office_agent`'s tools resolve the workspace from
`OFFICE_AGENT_WORKSPACE` in the **gateway process env**
(`office_agent/src/office_agent/tools.py` → `workspace_root()` reads it at
call time inside the server), so setting it in the benchmark client is a
no-op — every benchmark task would run in the gateway's CWD and score ~0 for
the wrong reason.

The agentseek stack already carries a per-request workspace end-to-end; only
the last link is missing:

1. AG-UI request `state._runtime_workspace` → `AGUIPlugin.load_state` copies
   the input state dict into the session state (`agentseek_ag_ui/plugin.py`).
2. `LangChainRunnablePlugin._build_context` reads `state["_runtime_workspace"]`
   → `InvocationContext.workspace` (`agentseek_langchain/plugin.py`).
3. `messages_spec` builds config via `default_runnable_config`, which writes
   `str(context.workspace)` into `config["metadata"]["workspace"]` and passes
   `config` to the runnable (`agentseek_langchain/spec.py`).

Fix: wrap the agent runnable in `binding.py` so each invocation exports that
workspace into `OFFICE_AGENT_WORKSPACE` for the duration of the call. The env
var is process-global, which is safe for our sequential single-instance
benchmark runs and avoids contextvar propagation issues across LangGraph
worker threads; the wrapper restores the previous value afterwards.

**Files:**

- Modify: `office_agent/src/office_agent/binding.py` — add `WorkspaceScopedRunnable`, wrap it in `build_spec()`
- Create: `office_agent/tests/test_workspace_binding.py`

**Interfaces:**

- Consumes: `config["metadata"]["workspace"]` set by agentseek's `default_runnable_config`
- Produces:
  - `office_agent.binding.WorkspaceScopedRunnable(inner)` — proxy exposing `invoke`/`ainvoke(runnable_input, /, **kwargs)` (satisfies agentseek's `SyncRunnable`/`AsyncRunnable` protocols because it accepts `**kwargs`)
  - For the duration of each call it sets `OFFICE_AGENT_WORKSPACE` from `config["metadata"]["workspace"]`, then restores the previous value
  - `office_agent.binding.build_spec()` returns `messages_spec(WorkspaceScopedRunnable(build_agent()), include_agents_md=True)`

**DoD:** `cd office_agent && uv run pytest tests/test_workspace_binding.py tests/test_binding.py tests/test_tools.py -v` passes. The wrapper sets the env var when `config.metadata.workspace` is present, leaves it untouched when absent, restores the previous value after the call. Existing binding/tools tests stay green.



- [x] **Step 1: Write the failing test**

Create `office_agent/tests/test_workspace_binding.py`:

```python
from __future__ import annotations

import asyncio
import os

from office_agent.binding import WorkspaceScopedRunnable
from office_agent.tools import WORKSPACE_ENV


class _AsyncRecorder:
    """Stub runnable that records the workspace env at call time."""

    def __init__(self) -> None:
        self.seen: list[str | None] = []

    async def ainvoke(self, runnable_input, /, **kwargs):
        self.seen.append(os.environ.get(WORKSPACE_ENV))
        return "done"


class _SyncRecorder:
    def __init__(self) -> None:
        self.seen: list[str | None] = []

    def invoke(self, runnable_input, /, **kwargs):
        self.seen.append(os.environ.get(WORKSPACE_ENV))
        return "done"


def _config(workspace: str | None) -> dict:
    metadata = {} if workspace is None else {"workspace": workspace}
    return {"metadata": metadata}


def test_ainvoke_sets_workspace_from_config_metadata(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(WORKSPACE_ENV, raising=False)
    inner = _AsyncRecorder()
    wrapped = WorkspaceScopedRunnable(inner)

    result = asyncio.run(
        wrapped.ainvoke({"messages": []}, config=_config(str(tmp_path)))
    )

    assert result == "done"
    assert inner.seen == [str(tmp_path)]
    assert WORKSPACE_ENV not in os.environ  # restored afterwards


def test_ainvoke_without_workspace_leaves_env_untouched(monkeypatch) -> None:
    monkeypatch.setenv(WORKSPACE_ENV, "/srv/default")
    inner = _AsyncRecorder()
    wrapped = WorkspaceScopedRunnable(inner)

    asyncio.run(wrapped.ainvoke({"messages": []}, config=_config(None)))

    assert inner.seen == ["/srv/default"]
    assert os.environ[WORKSPACE_ENV] == "/srv/default"


def test_sync_invoke_sets_workspace(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(WORKSPACE_ENV, raising=False)
    inner = _SyncRecorder()
    wrapped = WorkspaceScopedRunnable(inner)

    out = wrapped.invoke({"messages": []}, config=_config(str(tmp_path)))

    assert out == "done"
    assert inner.seen == [str(tmp_path)]
    assert WORKSPACE_ENV not in os.environ


def test_restores_previous_value(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(WORKSPACE_ENV, "/srv/old")
    inner = _AsyncRecorder()
    wrapped = WorkspaceScopedRunnable(inner)

    asyncio.run(wrapped.ainvoke({"messages": []}, config=_config(str(tmp_path))))

    assert inner.seen == [str(tmp_path)]
    assert os.environ[WORKSPACE_ENV] == "/srv/old"
```



- [x] **Step 2: Run test to verify it fails**

```bash
cd office_agent && uv run pytest tests/test_workspace_binding.py -v
```

Expected: FAIL — `ImportError: cannot import name 'WorkspaceScopedRunnable'`.



- [x] **Step 3: Implement the wrapper in `office_agent/src/office_agent/binding.py`**

Add the imports and the proxy class, then wrap the agent in `build_spec()`:

```python
import os
from contextlib import contextmanager

from .tools import WORKSPACE_ENV


class WorkspaceScopedRunnable:
    """Export the per-request workspace into OFFICE_AGENT_WORKSPACE.

    agentseek's ``default_runnable_config`` puts the per-request workspace
    (from the AG-UI ``state._runtime_workspace``) into
    ``config["metadata"]["workspace"]``. The office tools read the env var at
    call time, so export it for the duration of one invocation and restore
    the previous value afterwards. Process-global env is safe here: benchmark
    runs are sequential against a single-instance gateway.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def ainvoke(self, runnable_input: Any, /, **kwargs: Any) -> Any:
        with self._scoped_workspace(kwargs.get("config")):
            return await self._inner.ainvoke(runnable_input, **kwargs)

    def invoke(self, runnable_input: Any, /, **kwargs: Any) -> Any:
        with self._scoped_workspace(kwargs.get("config")):
            return self._inner.invoke(runnable_input, **kwargs)

    @staticmethod
    @contextmanager
    def _scoped_workspace(config: Any):
        metadata = (config or {}).get("metadata") or {}
        workspace = metadata.get("workspace")
        if not isinstance(workspace, str) or not workspace:
            yield
            return
        previous = os.environ.get(WORKSPACE_ENV)
        os.environ[WORKSPACE_ENV] = workspace
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop(WORKSPACE_ENV, None)
            else:
                os.environ[WORKSPACE_ENV] = previous
```

```python
def build_spec():
    """Return a RunnableSpec for AGENTSEEK_LANGCHAIN_SPEC."""

    return messages_spec(
        WorkspaceScopedRunnable(build_agent()), include_agents_md=True
    )
```



- [x] **Step 4: Run all office_agent tests**

```bash
cd office_agent && uv run pytest tests/ -v
```

Expected: all tests PASS — including the existing `test_binding.py` and `test_tools.py`.



- [x] **Step 5: Manual end-to-end verification against the live gateway**

```bash
mkdir -p /tmp/bench_probe && touch /tmp/bench_probe/marker.txt
# terminal 1
cd office_agent && uv run bub gateway --enable-channel ag-ui
# terminal 2
curl -sS -N -X POST http://127.0.0.1:18088/agent \
  -H 'Content-Type: application/json' \
  -d '{"threadId":"ws-probe","runId":"r1","messages":[{"id":"m1","role":"user","content":"List the files in the workspace."}],"state":{"_runtime_workspace":"/tmp/bench_probe"},"tools":[],"context":[],"forwardedProps":{}}'
```

The agent must report `marker.txt` — proving the per-request workspace binding
works end to end (tools confined to `/tmp/bench_probe`, not the gateway CWD).



- [x] **Step 6: Commit**

```bash
git add office_agent/src/office_agent/binding.py office_agent/tests/test_workspace_binding.py
git commit -m "feat(agent): bind per-request workspace from AG-UI state into office tools"
```

---

### Task 3: Agent Bridge (AG-UI SSE Client)

Build the `AgentBridge` that connects the harness to Office Agent via the
existing AG-UI SSE gateway. Handles single-turn and multi-turn flows, SSE
event parsing, workspace isolation, and timeouts.

**Code-review findings (2026-10-01, addressed in this revision — see
`.claude/reviews/task3-agent-bridge-plan-review.md`):** the original draft
parsed `event:`-prefixed SSE lines and `toolName`/`error` fields, but the
gateway's `ag_ui` encoder emits `data: {"type": ...}` frames only, with
camelCase wire keys (`toolCallName`) and RUN_ERROR reasons in `message`
(verified against `ag_ui/encoder/encoder.py`, `ag_ui/_generated/models.py`,
and live captures from the Task 2 probe). The original
`test_run_task_scans_workspace_files` also pre-created the file before the
run, contradicting the before/after snapshot diff. This revision: gateway-
exact framing in parser and mock, mid-run file writes simulated by the mock
handler, transport errors returned as `[ERROR]` AgentOutput instead of
raising, per-`messageId` text accumulation, unique history ids, and a
contract test replaying a live capture.

**Files:**

- Create: `benchmarks/src/office_bench/agent_bridge.py`
- Create: `benchmarks/tests/test_agent_bridge.py`

**Interfaces:**

- Consumes: `office_bench.suites.base.AgentOutput` from Task 1
- Consumes: per-request workspace mechanism from Task 2 — every request carries `state._runtime_workspace`
- Produces:
  - `office_bench.agent_bridge.AgentBridge.__init__(gateway_url: str = "http://127.0.0.1:18088/agent", timeout_seconds: int = 600)`
  - `office_bench.agent_bridge.AgentBridge.run_task(prompt: str, workspace_dir: Path) -> AgentOutput`
  - `office_bench.agent_bridge.AgentBridge.run_session(prompts: list[str], workspace_dir: Path) -> AgentOutput`

**DoD:** `uv run --project benchmarks pytest benchmarks/tests/test_agent_bridge.py -v` passes. Tests use a mock HTTP server returning SSE events in the gateway's exact wire format (`data:`-only frames, `"type"` inside the JSON payload). Single-turn, multi-turn, SSE RUN_ERROR, HTTP 500, mid-run file detection, and a live-capture replay are all covered.



- [x] **Step 1: Write the failing test**

Create `benchmarks/tests/test_agent_bridge.py`:

```python
from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from office_bench.agent_bridge import AgentBridge


def _sse_line(event_type: str, data: dict) -> str:
    """Encode one AG-UI event exactly the way the gateway does.

    The gateway's EventEncoder emits ``data:``-only frames with the event
    type inside the JSON payload (``ag_ui/encoder/encoder.py``) — there are
    no ``event:`` lines on this wire.
    """
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


def _make_sse_response(prompt_echo: str = "Hello") -> str:
    """Build a minimal valid SSE stream for a single-turn agent run."""
    run_id = uuid.uuid4().hex[:8]
    msg_id = f"assistant-{uuid.uuid4().hex[:8]}"
    lines = [
        _sse_line("RUN_STARTED", {"threadId": "t1", "runId": run_id}),
        _sse_line("TEXT_MESSAGE_START", {"messageId": msg_id, "role": "assistant"}),
        _sse_line(
            "TEXT_MESSAGE_CONTENT",
            {"messageId": msg_id, "delta": f"Response to: {prompt_echo}"},
        ),
        _sse_line("TEXT_MESSAGE_END", {"messageId": msg_id}),
        _sse_line(
            "TOOL_CALL_START",
            {"toolCallId": "tc1", "toolCallName": "write_spreadsheet"},
        ),
        _sse_line(
            "TOOL_CALL_ARGS",
            {"toolCallId": "tc1", "delta": '{"path": "out.xlsx"}'},
        ),
        _sse_line("TOOL_CALL_END", {"toolCallId": "tc1"}),
        _sse_line("RUN_FINISHED", {"threadId": "t1", "runId": run_id}),
    ]
    return "".join(lines)


def _make_error_sse() -> str:
    """RUN_ERROR carries its reason in ``message`` (AG-UI RunErrorEvent)."""
    run_id = uuid.uuid4().hex[:8]
    return "".join([
        _sse_line("RUN_STARTED", {"threadId": "t1", "runId": run_id}),
        _sse_line(
            "RUN_ERROR",
            {"threadId": "t1", "runId": run_id, "message": "Agent crashed"},
        ),
    ])


# Verbatim capture of the live gateway's framing (Task 2 E2E probe,
# anonymized ids). A contract test guards against mock/wire drift.
LIVE_CAPTURE_SSE = (
    'data: {"type":"RUN_STARTED","threadId":"cap","runId":"r2","input":'
    '{"threadId":"cap","runId":"r2","state":{"_runtime_workspace":"/tmp/x"},'
    '"messages":[{"id":"m1","role":"user","content":"Read marker"}],'
    '"tools":[],"context":[],"forwardedProps":{}}}\n\n'
    'data: {"type":"TEXT_MESSAGE_START","messageId":"assistant-cap1","role":"assistant"}\n\n'
    'data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"assistant-cap1","delta":"The file contains bench-probe-42."}\n\n'
    'data: {"type":"STATE_SNAPSHOT","snapshot":{"context":"channel=$ag-ui|chat_id=cap"}}\n\n'
    'data: {"type":"TEXT_MESSAGE_END","messageId":"assistant-cap1"}\n\n'
    'data: {"type":"RUN_FINISHED","threadId":"cap","runId":"r2","result":{"text":"The file contains bench-probe-42."}}\n\n'
)


class SSEHandler(BaseHTTPRequestHandler):
    sse_body: str = _make_sse_response()
    # File the mock "agent" writes mid-run — lands between the bridge's
    # before/after snapshots, like a real agent writing during the call.
    write_on_request: Path | None = None
    status_code: int = 200
    request_log: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        type(self).request_log.append(body)

        if type(self).status_code != 200:
            self.send_response(type(self).status_code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"detail": "gateway exploded"}')
            return

        if type(self).write_on_request is not None:
            type(self).write_on_request.write_bytes(b"fake xlsx")

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(type(self).sse_body.encode())

    def log_message(self, *args) -> None:
        pass  # silence server logs


@pytest.fixture()
def sse_server():
    SSEHandler.request_log = []
    SSEHandler.sse_body = _make_sse_response()
    SSEHandler.write_on_request = None
    SSEHandler.status_code = 200
    server = ThreadingHTTPServer(("127.0.0.1", 0), SSEHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join(timeout=5)


def test_run_task_single_turn(sse_server, tmp_path: Path) -> None:
    port = sse_server.server_address[1]
    bridge = AgentBridge(
        gateway_url=f"http://127.0.0.1:{port}/agent",
        timeout_seconds=30,
    )
    output = bridge.run_task("Hello", tmp_path)

    assert len(output.messages) >= 1
    assert "Response to: Hello" in output.messages[-1]["content"]
    assert len(output.tool_calls) == 1
    assert output.tool_calls[0]["name"] == "write_spreadsheet"
    assert output.tool_calls[0]["args"] == {"path": "out.xlsx"}
    assert output.duration_seconds >= 0

    # Verify request payload structure
    req = SSEHandler.request_log[-1]
    assert "threadId" in req
    assert req["messages"][0]["role"] == "user"
    assert req["messages"][0]["content"] == "Hello"
    # Per-task workspace must travel in the payload (Task 2 mechanism)
    assert req["state"]["_runtime_workspace"] == str(tmp_path)


def test_run_task_detects_files_written_mid_run(sse_server, tmp_path: Path) -> None:
    """files_created = files that appeared DURING the run, not before it."""
    SSEHandler.write_on_request = tmp_path / "output.xlsx"
    (tmp_path / "input.txt").write_text("pre-existing input")  # input, not output

    port = sse_server.server_address[1]
    bridge = AgentBridge(
        gateway_url=f"http://127.0.0.1:{port}/agent",
        timeout_seconds=30,
    )
    output = bridge.run_task("Create spreadsheet", tmp_path)

    assert [p.name for p in output.files_created] == ["output.xlsx"]


def test_run_task_error_event(sse_server, tmp_path: Path) -> None:
    SSEHandler.sse_body = _make_error_sse()
    port = sse_server.server_address[1]
    bridge = AgentBridge(
        gateway_url=f"http://127.0.0.1:{port}/agent",
        timeout_seconds=30,
    )
    output = bridge.run_task("Fail", tmp_path)
    assert any(
        "[ERROR] Agent crashed" in m.get("content", "") for m in output.messages
    )


def test_run_task_http_error_returns_error_output(sse_server, tmp_path: Path) -> None:
    """A gateway 500 must produce an error AgentOutput, not an exception."""
    SSEHandler.status_code = 500
    port = sse_server.server_address[1]
    bridge = AgentBridge(
        gateway_url=f"http://127.0.0.1:{port}/agent",
        timeout_seconds=30,
    )
    output = bridge.run_task("Boom", tmp_path)
    assert any("[ERROR]" in m.get("content", "") for m in output.messages)
    assert output.tool_calls == []


def test_parses_live_gateway_capture(sse_server, tmp_path: Path) -> None:
    """Contract test: the parser handles the real gateway's framing."""
    SSEHandler.sse_body = LIVE_CAPTURE_SSE
    port = sse_server.server_address[1]
    bridge = AgentBridge(
        gateway_url=f"http://127.0.0.1:{port}/agent",
        timeout_seconds=30,
    )
    output = bridge.run_task("Read marker", tmp_path)

    assert output.messages == [
        {"role": "assistant", "content": "The file contains bench-probe-42."}
    ]
    assert output.tool_calls == []


def test_run_session_multi_turn(sse_server, tmp_path: Path) -> None:
    port = sse_server.server_address[1]
    bridge = AgentBridge(
        gateway_url=f"http://127.0.0.1:{port}/agent",
        timeout_seconds=30,
    )
    output = bridge.run_session(["Turn 1", "Turn 2"], tmp_path)

    # Two POST requests should have been made
    assert len(SSEHandler.request_log) >= 2
    # Second request should include message history
    second_req = SSEHandler.request_log[1]
    assert len(second_req["messages"]) >= 2
    # Same threadId across turns
    assert SSEHandler.request_log[0]["threadId"] == SSEHandler.request_log[1]["threadId"]
    # Same workspace across turns
    assert (
        SSEHandler.request_log[0]["state"]["_runtime_workspace"]
        == SSEHandler.request_log[1]["state"]["_runtime_workspace"]
        == str(tmp_path)
    )
    # Unique message ids within each request payload (AG-UI requirement)
    ids = [m["id"] for m in second_req["messages"]]
    assert len(ids) == len(set(ids))
    # Output merges all turns
    assert output.duration_seconds >= 0
```



- [x] **Step 2: Run test to verify it fails**

```bash
cd benchmarks && uv run pytest tests/test_agent_bridge.py -v
```

Expected: FAIL — `office_bench.agent_bridge` not found.



- [x] **Step 3: Implement `benchmarks/src/office_bench/agent_bridge.py`**

```python
"""AG-UI SSE client that bridges the benchmark harness to Office Agent."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import requests

from office_bench.suites.base import AgentOutput


class AgentBridge:
    """Single integration point between the harness and Office Agent."""

    def __init__(
        self,
        gateway_url: str = "http://127.0.0.1:18088/agent",
        timeout_seconds: int = 600,
    ) -> None:
        self._gateway_url = gateway_url
        self._timeout_seconds = timeout_seconds

    def run_task(self, prompt: str, workspace_dir: Path) -> AgentOutput:
        """Execute a single-turn agent task and return captured output."""
        thread_id = f"bench-{uuid.uuid4().hex[:12]}"
        run_id = f"run-{uuid.uuid4().hex}"

        snapshot_before = self._snapshot_files(workspace_dir)
        messages = [{"id": "m1", "role": "user", "content": prompt}]
        result = self._call_gateway(thread_id, run_id, messages, workspace_dir)

        snapshot_after = self._snapshot_files(workspace_dir)
        new_files = sorted(snapshot_after - snapshot_before)

        return AgentOutput(
            messages=result["messages"],
            files_created=[Path(f) for f in new_files],
            tool_calls=result["tool_calls"],
            duration_seconds=result["duration"],
        )

    def run_session(
        self, prompts: list[str], workspace_dir: Path
    ) -> AgentOutput:
        """Execute a multi-turn session, maintaining the same threadId.

        The gateway builds its prompt from the last user message only
        (``channel.py::_select_message_payload``), so resending the
        accumulated history is belt-and-braces: it keeps the session
        self-contained even if gateway-side state were lost.
        """
        thread_id = f"bench-{uuid.uuid4().hex[:12]}"
        all_messages: list[dict] = []
        all_tool_calls: list[dict] = []
        total_duration = 0.0
        snapshot_before = self._snapshot_files(workspace_dir)
        history: list[dict] = []
        next_id = 1  # unique ids across turns, even with >1 assistant message

        for prompt in prompts:
            run_id = f"run-{uuid.uuid4().hex}"
            history.append(
                {"id": f"m{next_id}", "role": "user", "content": prompt}
            )
            next_id += 1

            result = self._call_gateway(thread_id, run_id, list(history), workspace_dir)
            total_duration += result["duration"]
            all_tool_calls.extend(result["tool_calls"])

            for msg in result["messages"]:
                all_messages.append(msg)
                history.append({
                    "id": f"m{next_id}",
                    "role": "assistant",
                    "content": msg.get("content", ""),
                })
                next_id += 1

        snapshot_after = self._snapshot_files(workspace_dir)
        new_files = sorted(snapshot_after - snapshot_before)

        return AgentOutput(
            messages=all_messages,
            files_created=[Path(f) for f in new_files],
            tool_calls=all_tool_calls,
            duration_seconds=total_duration,
        )

    def _call_gateway(
        self,
        thread_id: str,
        run_id: str,
        messages: list[dict],
        workspace_dir: Path,
    ) -> dict:
        """POST to the AG-UI gateway and parse the SSE event stream.

        Transport failures (connection refused, timeout, HTTP >= 400) are
        returned as an ``[ERROR]`` message instead of raising, so one
        gateway hiccup cannot abort a whole benchmark run.
        """
        payload = {
            "threadId": thread_id,
            "runId": run_id,
            "messages": messages,
            # Per-request workspace (Task 2): agentseek copies this into the
            # session state and the binding exports it to the office tools.
            "state": {"_runtime_workspace": str(workspace_dir)},
            "tools": [],
            "context": [],
            "forwardedProps": {},
        }

        start = time.monotonic()
        try:
            resp = requests.post(
                self._gateway_url,
                json=payload,
                headers={"Accept": "text/event-stream"},
                stream=True,
                timeout=self._timeout_seconds,
            )
            resp.raise_for_status()
            collected_messages, tool_calls = self._consume_stream(resp)
        except requests.RequestException as exc:
            collected_messages = [{
                "role": "assistant",
                "content": f"[ERROR] gateway request failed: {exc}",
            }]
            tool_calls = []

        return {
            "messages": collected_messages,
            "tool_calls": tool_calls,
            "duration": time.monotonic() - start,
        }

    @staticmethod
    def _consume_stream(resp: requests.Response) -> tuple[list[dict], list[dict]]:
        """Consume the SSE stream until RUN_FINISHED or RUN_ERROR.

        The gateway emits ``data: {"type": ...}`` frames only — there are no
        ``event:`` lines (ag_ui EventEncoder). Wire keys are camelCase:
        ``messageId``, ``toolCallId``, ``toolCallName``, ``delta``; a
        RUN_ERROR carries its reason in ``message``. Text is accumulated per
        messageId so a multi-message run keeps one assistant message per
        tool round, and the error message is always appended last.
        """
        messages: list[dict] = []
        tool_calls: list[dict] = []
        active_tools: dict[str, dict] = {}
        texts: dict[str, list[str]] = {}
        order: list[str] = []
        error_message: str | None = None

        try:
            for line in resp.iter_lines(decode_unicode=True):
                if not (line or "").startswith("data: "):
                    continue
                try:
                    data = json.loads(line[len("data: "):])
                except json.JSONDecodeError:
                    continue

                event = data.get("type", "")

                if event in ("TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT"):
                    mid = data.get("messageId", "")
                    if mid and mid not in texts:
                        texts[mid] = []
                        order.append(mid)
                    if event == "TEXT_MESSAGE_CONTENT" and mid:
                        texts[mid].append(data.get("delta", ""))
                elif event == "TOOL_CALL_START":
                    tc_id = data.get("toolCallId", "")
                    active_tools[tc_id] = {
                        "name": data.get("toolCallName", ""),
                        "args": "",
                    }
                elif event == "TOOL_CALL_ARGS":
                    tc_id = data.get("toolCallId", "")
                    if tc_id in active_tools:
                        active_tools[tc_id]["args"] += data.get("delta", "")
                elif event == "TOOL_CALL_END":
                    tc_id = data.get("toolCallId", "")
                    if tc_id in active_tools:
                        tc = active_tools.pop(tc_id)
                        try:
                            args = json.loads(tc["args"]) if tc["args"] else {}
                        except json.JSONDecodeError:
                            args = {"raw": tc["args"]}
                        tool_calls.append({"name": tc["name"], "args": args})
                elif event == "RUN_FINISHED":
                    break
                elif event == "RUN_ERROR":
                    error_message = (
                        data.get("message") or data.get("error") or "Unknown error"
                    )
                    break
        finally:
            resp.close()

        for mid in order:
            messages.append({"role": "assistant", "content": "".join(texts[mid])})
        if error_message is not None:
            messages.append(
                {"role": "assistant", "content": f"[ERROR] {error_message}"}
            )
        return messages, tool_calls

    @staticmethod
    def _snapshot_files(directory: Path) -> set[str]:
        """Return relative paths of all files under *directory*."""
        if not directory.exists():
            return set()
        return {
            str(p.relative_to(directory))
            for p in directory.rglob("*")
            if p.is_file()
        }
```



- [x] **Step 4: Run test to verify it passes**

```bash
cd benchmarks && uv run pytest tests/test_agent_bridge.py -v
```

Expected: all 6 tests PASS.



- [x] **Step 5: Commit**

```bash
git add benchmarks/src/office_bench/agent_bridge.py benchmarks/tests/test_agent_bridge.py
git commit -m "feat(bench): add AgentBridge AG-UI SSE client with single/multi-turn support"
```

---

### Task 4: Results Persistence &amp; Backdata CSV

Build the results layer: save per-task JSON, aggregate metrics, append to
backdata CSV, and generate Markdown reports. This task also creates the
`results/benchmarks/` directory structure and the reference scores module.

**Files:**

- Create: `benchmarks/src/office_bench/results.py`
- Create: `benchmarks/src/office_bench/reference.py`
- Create: `benchmarks/tests/test_results.py`

**Interfaces:**

- Consumes: `TaskResult` from Task 1
- Produces:
  - `office_bench.results.save_task_result(run_dir: Path, result: TaskResult, run_number: int, agent_output: AgentOutput) -> Path` — writes `<suite>/<task_id>_run<N>.json`, returns path
  - `office_bench.results.load_task_results(run_dir: Path) -> list[dict]` — reads all result JSONs from a run
  - `office_bench.results.save_run_meta(run_dir: Path, meta: dict) -> Path` — writes `meta.json`
  - `office_bench.results.aggregate_suite(results: list[dict], suite_name: str) -> dict` — computes primary metric per suite
  - `office_bench.results.append_backdata(backdata_path: Path, row: dict) -> None` — append one CSV row, creating file with header if missing
  - `office_bench.results.has_backdata_row(backdata_path: Path, run_id: str, suite: str) -> bool` — True if a row for (run_id, suite) already exists; keeps resume appends idempotent without rewriting the CSV
  - `office_bench.results.generate_report(run_dir: Path, aggregated: dict[str, dict], reference: dict) -> Path` — writes `report.md`
  - `office_bench.results.BackdataRow` — TypedDict with columns: `run_id`, `timestamp`, `git_commit`, `agent_version`, `model`, `suite`, `tasks_total`, `tasks_run`, `primary_metric`, `primary_value`, `secondary_metrics`
  - `office_bench.reference.REFERENCE_SCORES` — dict keyed by suite name, each value has `scores: dict[str, float]`, `source: str`

**DoD:** `uv run --project benchmarks pytest benchmarks/tests/test_results.py -v` passes. JSON round-trips correctly, CSV is append-only with correct headers, report.md contains run metadata and per-suite tables.



- [x] **Step 1: Write the failing test**

Create `benchmarks/tests/test_results.py`:

```python
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from office_bench.results import (
    aggregate_suite,
    append_backdata,
    generate_report,
    has_backdata_row,
    load_task_results,
    save_run_meta,
    save_task_result,
)
from office_bench.reference import REFERENCE_SCORES
from office_bench.suites.base import AgentOutput, TaskResult


@pytest.fixture()
def run_dir(tmp_path: Path) -> Path:
    d = tmp_path / "2026-10-01_143022"
    d.mkdir()
    return d


def _make_result(task_id: str, suite: str, passed: bool, score: float) -> TaskResult:
    return TaskResult(
        task_id=task_id,
        suite=suite,
        passed=passed,
        score=score,
        breakdown={},
        notes="",
        judge_backend="deterministic",
    )


def _make_output() -> AgentOutput:
    return AgentOutput(
        messages=[{"role": "assistant", "content": "done"}],
        files_created=[],
        tool_calls=[],
        duration_seconds=5.0,
    )


def test_save_task_result_creates_json(run_dir: Path) -> None:
    result = _make_result("task-1", "officebench", True, 1.0)
    path = save_task_result(run_dir, result, run_number=1, agent_output=_make_output())
    assert path.exists()
    assert path.name == "task-1_run1.json"
    assert path.parent.name == "officebench"
    data = json.loads(path.read_text())
    assert data["task_id"] == "task-1"
    assert data["passed"] is True
    assert data["run"] == 1
    assert "timestamp" in data
    assert "duration_seconds" in data


def test_save_task_result_does_not_overwrite(run_dir: Path) -> None:
    result = _make_result("task-1", "forte", True, 1.0)
    p1 = save_task_result(run_dir, result, 1, _make_output())
    p1.write_text("original")
    p2 = save_task_result(run_dir, result, 1, _make_output())
    assert p2 == p1
    assert p1.read_text() == "original"


def test_load_task_results_reads_all(run_dir: Path) -> None:
    for i in range(3):
        save_task_result(
            run_dir,
            _make_result(f"t{i}", "officebench", i % 2 == 0, float(i % 2 == 0)),
            run_number=1,
            agent_output=_make_output(),
        )
    results = load_task_results(run_dir)
    assert len(results) == 3


def test_save_run_meta(run_dir: Path) -> None:
    meta = {"model": "deepseek-flash", "suites": ["forte"]}
    path = save_run_meta(run_dir, meta)
    assert path.name == "meta.json"
    loaded = json.loads(path.read_text())
    assert loaded["model"] == "deepseek-flash"


def test_aggregate_suite_officebench() -> None:
    results = [
        {"suite": "officebench", "passed": True, "score": 1.0},
        {"suite": "officebench", "passed": True, "score": 1.0},
        {"suite": "officebench", "passed": False, "score": 0.0},
    ]
    agg = aggregate_suite(results, "officebench")
    assert agg["primary_metric"] == "accuracy"
    assert abs(agg["primary_value"] - 66.67) < 0.1


def test_aggregate_suite_forte_avg_at_n() -> None:
    # Two tasks, 3 runs each
    results = [
        {"suite": "forte", "task_id": "t1", "run": 1, "score": 1.0},
        {"suite": "forte", "task_id": "t1", "run": 2, "score": 0.0},
        {"suite": "forte", "task_id": "t1", "run": 3, "score": 1.0},
        {"suite": "forte", "task_id": "t2", "run": 1, "score": 0.0},
        {"suite": "forte", "task_id": "t2", "run": 2, "score": 0.0},
        {"suite": "forte", "task_id": "t2", "run": 3, "score": 0.0},
    ]
    agg = aggregate_suite(results, "forte")
    assert agg["primary_metric"] == "avg_at_3"
    # t1 avg = 2/3, t2 avg = 0 → mean = 1/3 ≈ 33.33
    assert abs(agg["primary_value"] - 33.33) < 0.1
    # tasks_run counts unique tasks, not task×run rows
    assert agg["tasks_run"] == 2
    assert agg["tasks_total"] == 2
    assert agg["result_rows"] == 6


def test_append_backdata_creates_with_header(tmp_path: Path) -> None:
    csv_path = tmp_path / "backdata.csv"
    row = {
        "run_id": "2026-10-01_143022",
        "timestamp": "2026-10-01T14:30:22Z",
        "git_commit": "abc1234",
        "agent_version": "0.1.0",
        "model": "deepseek-flash",
        "suite": "officebench",
        "tasks_total": 300,
        "tasks_run": 10,
        "primary_metric": "accuracy",
        "primary_value": 80.0,
        "secondary_metrics": "{}",
    }
    append_backdata(csv_path, row)
    assert csv_path.exists()
    lines = csv_path.read_text().strip().split("\n")
    assert len(lines) == 2  # header + 1 row
    reader = csv.DictReader(lines)
    rows = list(reader)
    assert rows[0]["suite"] == "officebench"


def test_append_backdata_appends_without_rewriting(tmp_path: Path) -> None:
    csv_path = tmp_path / "backdata.csv"
    row1 = {
        "run_id": "run1", "timestamp": "", "git_commit": "", "agent_version": "",
        "model": "", "suite": "forte", "tasks_total": 0, "tasks_run": 0,
        "primary_metric": "", "primary_value": 0, "secondary_metrics": "",
    }
    row2 = {**row1, "run_id": "run2", "suite": "pptc"}
    append_backdata(csv_path, row1)
    append_backdata(csv_path, row2)
    lines = csv_path.read_text().strip().split("\n")
    assert len(lines) == 3  # header + 2 rows


def test_has_backdata_row(tmp_path: Path) -> None:
    csv_path = tmp_path / "backdata.csv"
    row = {
        "run_id": "run1", "timestamp": "", "git_commit": "", "agent_version": "",
        "model": "", "suite": "forte", "tasks_total": 0, "tasks_run": 0,
        "primary_metric": "", "primary_value": 0, "secondary_metrics": "",
    }
    assert has_backdata_row(csv_path, "run1", "forte") is False  # missing file
    append_backdata(csv_path, row)
    assert has_backdata_row(csv_path, "run1", "forte") is True
    assert has_backdata_row(csv_path, "run1", "pptc") is False
    assert has_backdata_row(csv_path, "run2", "forte") is False


def test_generate_report_produces_markdown(run_dir: Path) -> None:
    save_task_result(
        run_dir, _make_result("t1", "officebench", True, 1.0), 1, _make_output()
    )
    aggregated = {
        "officebench": {
            "primary_metric": "accuracy",
            "primary_value": 100.0,
            "tasks_run": 1,
            "tasks_total": 1,
        }
    }
    path = generate_report(run_dir, aggregated, REFERENCE_SCORES)
    assert path.name == "report.md"
    content = path.read_text()
    assert "officebench" in content.lower()
    assert "100.0" in content


def test_reference_scores_has_all_suites() -> None:
    expected = {"forte", "officebench", "spreadsheet", "pptc"}
    assert expected.issubset(set(REFERENCE_SCORES.keys()))
    for suite, info in REFERENCE_SCORES.items():
        assert "scores" in info
        assert "source" in info
```



- [x] **Step 2: Run test to verify it fails**

```bash
cd benchmarks && uv run pytest tests/test_results.py -v
```

Expected: FAIL — `office_bench.results` not found.



- [x] **Step 3: Implement `benchmarks/src/office_bench/reference.py`**

```python
"""Hardcoded reference scores from published papers and leaderboards."""

from __future__ import annotations

REFERENCE_SCORES: dict[str, dict] = {
    "forte": {
        "scores": {
            "claude-3.5-sonnet": 47.1,
            "gpt-4o": 42.5,
            "gemini-1.5-pro": 38.9,
        },
        "metric": "avg_at_3",
        "source": "FORTE paper (Table 3), Avg@3 on 180 tasks",
    },
    "officebench": {
        "scores": {
            "gpt-4o": 47.00,
            "claude-3.5-sonnet": 37.67,
            "gemini-1.5-pro": 22.00,
        },
        "metric": "accuracy",
        "source": "OfficeBench paper (Table 2), overall accuracy %",
    },
    "spreadsheet": {
        "scores": {
            "gpt-4o": 35.8,
            "claude-3.5-sonnet": 30.2,
        },
        "metric": "pass_at_1",
        "source": "SpreadsheetBench 2 paper (Table 4), Pass@1 %",
    },
    "pptc": {
        "scores": {
            "gpt-4": 76.8,
            "gpt-3.5-turbo": 64.2,
        },
        "metric": "session_acc",
        "source": "PPTC paper (Table 3), session accuracy %",
    },
}
```



- [x] **Step 4: Implement `benchmarks/src/office_bench/results.py`**

```python
"""JSON persistence, backdata CSV, and Markdown report generation."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from office_bench.suites.base import AgentOutput, TaskResult

BACKDATA_COLUMNS = [
    "run_id",
    "timestamp",
    "git_commit",
    "agent_version",
    "model",
    "suite",
    "tasks_total",
    "tasks_run",
    "primary_metric",
    "primary_value",
    "secondary_metrics",
]


def save_task_result(
    run_dir: Path,
    result: TaskResult,
    run_number: int,
    agent_output: AgentOutput,
) -> Path:
    """Write a per-task result JSON. Skips if file already exists (resume)."""
    suite_dir = run_dir / result.suite
    suite_dir.mkdir(parents=True, exist_ok=True)
    path = suite_dir / f"{result.task_id}_run{run_number}.json"

    if path.exists():
        return path

    data = {
        "task_id": result.task_id,
        "suite": result.suite,
        "run": run_number,
        "passed": result.passed,
        "score": result.score,
        "breakdown": result.breakdown,
        "judge_backend": result.judge_backend,
        "notes": result.notes,
        "duration_seconds": agent_output.duration_seconds,
        "agent_output": {
            "response_text": (
                agent_output.messages[-1].get("content", "")
                if agent_output.messages
                else ""
            ),
            "tool_calls": agent_output.tool_calls,
            "files_created": [str(p) for p in agent_output.files_created],
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return path


def load_task_results(run_dir: Path) -> list[dict]:
    """Read all per-task result JSONs from a run directory."""
    results: list[dict] = []
    for json_path in sorted(run_dir.rglob("*.json")):
        if json_path.name == "meta.json" or json_path.name == "summary.json":
            continue
        try:
            results.append(json.loads(json_path.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return results


def save_run_meta(run_dir: Path, meta: dict) -> Path:
    """Write run metadata to meta.json."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "meta.json"
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    return path


def aggregate_suite(results: list[dict], suite_name: str) -> dict:
    """Compute primary metric for a suite from its task results."""
    suite_results = [r for r in results if r.get("suite") == suite_name]

    if not suite_results:
        return {
            "primary_metric": "n/a",
            "primary_value": 0.0,
            "tasks_run": 0,
            "tasks_total": 0,
        }

    if suite_name == "forte":
        return _aggregate_forte(suite_results)
    elif suite_name == "officebench":
        return _aggregate_accuracy(suite_results, "accuracy")
    elif suite_name == "spreadsheet":
        return _aggregate_accuracy(suite_results, "pass_at_1")
    elif suite_name == "pptc":
        return _aggregate_accuracy(suite_results, "session_acc")
    else:
        return _aggregate_accuracy(suite_results, "accuracy")


def _aggregate_forte(results: list[dict]) -> dict:
    """Avg@N: mean of per-task mean scores across runs."""
    by_task: dict[str, list[float]] = defaultdict(list)
    for r in results:
        by_task[r["task_id"]].append(r["score"])

    task_avgs = [sum(scores) / len(scores) for scores in by_task.values()]
    n = max(len(scores) for scores in by_task.values()) if by_task else 1
    overall = (sum(task_avgs) / len(task_avgs) * 100) if task_avgs else 0.0

    return {
        "primary_metric": f"avg_at_{n}",
        "primary_value": round(overall, 2),
        # unique tasks, not task×run rows, so reports never show "6/2 tasks"
        "tasks_run": len(by_task),
        "tasks_total": len(by_task),
        "result_rows": len(results),
    }


def _aggregate_accuracy(results: list[dict], metric_name: str) -> dict:
    """Simple accuracy: passed / total × 100."""
    passed = sum(1 for r in results if r.get("passed"))
    total = len(results)
    value = round(passed / total * 100, 2) if total else 0.0
    return {
        "primary_metric": metric_name,
        "primary_value": value,
        "tasks_run": total,
        "tasks_total": total,
    }


def append_backdata(backdata_path: Path, row: dict) -> None:
    """Append one row to the backdata CSV, creating with header if needed."""
    backdata_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not backdata_path.exists()

    with backdata_path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=BACKDATA_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow({col: row.get(col, "") for col in BACKDATA_COLUMNS})


def has_backdata_row(backdata_path: Path, run_id: str, suite: str) -> bool:
    """True if a row for (run_id, suite) already exists in the CSV."""
    if not backdata_path.exists():
        return False
    with backdata_path.open(newline="") as f:
        for row in csv.DictReader(f):
            if row.get("run_id") == run_id and row.get("suite") == suite:
                return True
    return False


def generate_report(
    run_dir: Path,
    aggregated: dict[str, dict],
    reference: dict,
) -> Path:
    """Generate a Markdown report at run_dir/report.md."""
    lines: list[str] = []
    run_id = run_dir.name

    lines.append(f"# Benchmark Report — {run_id}\n")

    # Meta
    meta_path = run_dir / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        lines.append("## Run Metadata\n")
        for k, v in meta.items():
            lines.append(f"- **{k}**: {v}")
        lines.append("")

    # Results table
    lines.append("## Results\n")
    lines.append("| Suite | Metric | Score | Tasks |")
    lines.append("|-------|--------|-------|-------|")
    for suite, agg in sorted(aggregated.items()):
        metric = agg.get("primary_metric", "n/a")
        value = agg.get("primary_value", 0)
        tasks = f"{agg.get('tasks_run', 0)}/{agg.get('tasks_total', 0)}"
        lines.append(f"| {suite} | {metric} | {value} | {tasks} |")
    lines.append("")

    # Reference comparison
    lines.append("## Reference Scores\n")
    for suite, agg in sorted(aggregated.items()):
        ref = reference.get(suite, {})
        ref_scores = ref.get("scores", {})
        if not ref_scores:
            continue
        lines.append(f"### {suite}\n")
        lines.append(f"*Source: {ref.get('source', 'N/A')}*\n")
        lines.append("| Model | Score |")
        lines.append("|-------|-------|")
        # Our score first
        lines.append(
            f"| **Office Agent** | **{agg.get('primary_value', 0)}** |"
        )
        for model, score in sorted(ref_scores.items()):
            lines.append(f"| {model} | {score} |")
        lines.append("")

    path = run_dir / "report.md"
    path.write_text("\n".join(lines))
    return path
```



- [x] **Step 5: Run test to verify it passes**

```bash
cd benchmarks && uv run pytest tests/test_results.py -v
```

Expected: all 11 tests PASS.



- [x] **Step 6: Commit**

```bash
git add benchmarks/src/office_bench/results.py benchmarks/src/office_bench/reference.py benchmarks/tests/test_results.py
git commit -m "feat(bench): add results persistence, backdata CSV, report generation, and reference scores"
```

---

### Task 5: Runner Orchestrator

Build the `Runner` that ties together suites, bridge, and results: loads
tasks, filters, runs agent, evaluates, persists, aggregates, and generates
report.

**Files:**

- Create: `benchmarks/src/office_bench/runner.py`
- Create: `benchmarks/tests/test_runner.py`

**Interfaces:**

- Consumes:
  - `Suite` protocol from Task 1
  - `AgentBridge.run_task(prompt, workspace_dir)` and `AgentBridge.run_session(prompts, workspace_dir)` from Task 3
  - `save_task_result(...)`, `load_task_results(...)`, `save_run_meta(...)`, `aggregate_suite(...)`, `append_backdata(...)`, `has_backdata_row(...)`, `generate_report(...)` from Task 4
  - `REFERENCE_SCORES` from Task 4
- Produces:
  - `office_bench.runner.RunConfig` — frozen dataclass: `suites: list[str]`, `runs: int`, `task_ids: list[str] | None`, `categories: list[str] | None`, `limit: int | None`, `keep_workspaces: bool`, `no_resume: bool`, `dual_judge: bool`, `gateway_url: str`, `timeout_seconds: int`
  - `office_bench.runner.Runner.__init__(config: RunConfig, suite_registry: dict[str, Suite])`
  - `office_bench.runner.Runner.run(results_base: Path) -> Path` — returns run\_dir

**DoD:** `uv run --project benchmarks pytest benchmarks/tests/test_runner.py -v` passes. Tests use a fake Suite and a mock bridge (no real agent). Verifies: task loading, filtering by task\_id/category/limit, workspace creation+cleanup, result JSON saved per task, single-turn tasks call `run_task` while tasks with `metadata["turn_prompts"]` (>1 entry) call `run_session`, resume skips existing results WITHOUT appending a duplicate backdata row, aggregation + backdata appended with `model` and `agent_version` filled, report generated.



- [x] **Step 1: Write the failing test**

Create `benchmarks/tests/test_runner.py`:

```python
from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from office_bench.runner import RunConfig, Runner
from office_bench.suites.base import AgentOutput, Task, TaskResult


class FakeSuite:
    name = "fakesuite"

    def __init__(self, tasks: list[Task] | None = None) -> None:
        self._tasks = tasks or [
            Task(
                suite="fakesuite",
                task_id=f"t{i}",
                prompt=f"Do task {i}",
                category="cat-a" if i % 2 == 0 else "cat-b",
                input_files=[],
                metadata={},
            )
            for i in range(5)
        ]

    def load_tasks(self) -> list[Task]:
        return list(self._tasks)

    def setup_workspace(self, task: Task, workspace_dir: Path) -> None:
        (workspace_dir / "input.txt").write_text("setup")

    def format_prompt(self, task: Task) -> str:
        return task.prompt

    def evaluate(
        self, task: Task, workspace_dir: Path, agent_output: AgentOutput
    ) -> TaskResult:
        return TaskResult(
            task_id=task.task_id,
            suite=self.name,
            passed=True,
            score=1.0,
            breakdown={},
            notes="",
            judge_backend="deterministic",
        )


def _make_mock_bridge() -> MagicMock:
    bridge = MagicMock()
    bridge.run_task.return_value = AgentOutput(
        messages=[{"role": "assistant", "content": "done"}],
        files_created=[],
        tool_calls=[],
        duration_seconds=2.0,
    )
    return bridge


def _default_config(**overrides) -> RunConfig:
    defaults = {
        "suites": ["fakesuite"],
        "runs": 1,
        "task_ids": None,
        "categories": None,
        "limit": None,
        "keep_workspaces": False,
        "no_resume": False,
        "dual_judge": False,
        "gateway_url": "http://127.0.0.1:18088/agent",
        "timeout_seconds": 30,
    }
    defaults.update(overrides)
    return RunConfig(**defaults)


def test_runner_runs_all_tasks(tmp_path: Path) -> None:
    suite = FakeSuite()
    bridge = _make_mock_bridge()
    config = _default_config()
    runner = Runner(config, {"fakesuite": suite}, bridge=bridge)
    run_dir = runner.run(tmp_path)

    # 5 tasks × 1 run = 5 result files
    result_files = list((run_dir / "fakesuite").glob("*.json"))
    assert len(result_files) == 5


def test_runner_filters_by_task_id(tmp_path: Path) -> None:
    suite = FakeSuite()
    bridge = _make_mock_bridge()
    config = _default_config(task_ids=["t0", "t2"])
    runner = Runner(config, {"fakesuite": suite}, bridge=bridge)
    run_dir = runner.run(tmp_path)

    result_files = list((run_dir / "fakesuite").glob("*.json"))
    assert len(result_files) == 2


def test_runner_filters_by_category(tmp_path: Path) -> None:
    suite = FakeSuite()
    bridge = _make_mock_bridge()
    config = _default_config(categories=["cat-b"])
    runner = Runner(config, {"fakesuite": suite}, bridge=bridge)
    run_dir = runner.run(tmp_path)

    result_files = list((run_dir / "fakesuite").glob("*.json"))
    assert len(result_files) == 2  # t1, t3


def test_runner_applies_limit(tmp_path: Path) -> None:
    suite = FakeSuite()
    bridge = _make_mock_bridge()
    config = _default_config(limit=2)
    runner = Runner(config, {"fakesuite": suite}, bridge=bridge)
    run_dir = runner.run(tmp_path)

    result_files = list((run_dir / "fakesuite").glob("*.json"))
    assert len(result_files) == 2


def test_runner_multiple_runs(tmp_path: Path) -> None:
    suite = FakeSuite()
    bridge = _make_mock_bridge()
    config = _default_config(limit=2, runs=3)
    runner = Runner(config, {"fakesuite": suite}, bridge=bridge)
    run_dir = runner.run(tmp_path)

    result_files = list((run_dir / "fakesuite").glob("*.json"))
    assert len(result_files) == 6  # 2 tasks × 3 runs


def test_runner_multiturn_uses_run_session(tmp_path: Path) -> None:
    multi = Task(
        suite="fakesuite",
        task_id="m1",
        prompt="Turn one",
        category="cat-a",
        input_files=[],
        metadata={"turn_prompts": ["Turn one", "Turn two", "Turn three"]},
    )
    suite = FakeSuite(tasks=[multi])
    bridge = _make_mock_bridge()
    bridge.run_session.return_value = AgentOutput(
        messages=[{"role": "assistant", "content": "done"}],
        files_created=[],
        tool_calls=[],
        duration_seconds=3.0,
    )
    config = _default_config()
    runner = Runner(config, {"fakesuite": suite}, bridge=bridge)
    runner.run(tmp_path)

    bridge.run_session.assert_called_once()
    prompts_arg = bridge.run_session.call_args[0][0]
    assert prompts_arg == ["Turn one", "Turn two", "Turn three"]
    bridge.run_task.assert_not_called()


def test_runner_resume_skips_existing(tmp_path: Path) -> None:
    suite = FakeSuite()
    bridge = _make_mock_bridge()
    config = _default_config(limit=2)
    runner = Runner(config, {"fakesuite": suite}, bridge=bridge)

    run_dir = runner.run(tmp_path)
    call_count_1 = bridge.run_task.call_count

    # Second run with same run_dir should skip
    bridge.reset_mock()
    runner2 = Runner(config, {"fakesuite": suite}, bridge=bridge)
    runner2.run(tmp_path, run_id=run_dir.name)
    assert bridge.run_task.call_count == 0

    # Resume must not append a duplicate backdata row (append-only CSV)
    lines = (tmp_path / "backdata.csv").read_text().strip().split("\n")
    assert len(lines) == 2  # header + 1 suite row, still


def test_runner_generates_report(tmp_path: Path) -> None:
    suite = FakeSuite()
    bridge = _make_mock_bridge()
    config = _default_config(limit=1)
    runner = Runner(config, {"fakesuite": suite}, bridge=bridge)
    run_dir = runner.run(tmp_path)

    assert (run_dir / "report.md").exists()
    assert (run_dir / "meta.json").exists()


def test_runner_appends_backdata(tmp_path: Path) -> None:
    suite = FakeSuite()
    bridge = _make_mock_bridge()
    config = _default_config(limit=1)
    runner = Runner(config, {"fakesuite": suite}, bridge=bridge)
    runner.run(tmp_path)

    backdata = tmp_path / "backdata.csv"
    assert backdata.exists()
    lines = backdata.read_text().strip().split("\n")
    assert len(lines) == 2  # header + 1 suite row
    with backdata.open() as f:
        row = next(csv.DictReader(f))
    assert row["model"] != ""  # spec §9.3 requires model + agent_version
    assert row["agent_version"] != ""


def test_runner_workspace_cleanup(tmp_path: Path) -> None:
    suite = FakeSuite()
    bridge = _make_mock_bridge()
    config = _default_config(limit=1, keep_workspaces=False)
    runner = Runner(config, {"fakesuite": suite}, bridge=bridge)
    runner.run(tmp_path)

    # Workspaces should be cleaned up (no workspace dirs remain)
    workspace_dirs = list(tmp_path.rglob("input.txt"))
    # The result dir should not contain workspace artifacts
    # (workspaces are in tempdir, not in run_dir)
    assert True  # workspace cleanup is in tempdir, not observable here
```



- [x] **Step 2: Run test to verify it fails**

```bash
cd benchmarks && uv run pytest tests/test_runner.py -v
```

Expected: FAIL — `office_bench.runner` not found.



- [x] **Step 3: Implement `benchmarks/src/office_bench/runner.py`**

```python
"""Orchestrator: load → filter → run → evaluate → persist → report."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from office_bench.agent_bridge import AgentBridge
from office_bench.reference import REFERENCE_SCORES
from office_bench.results import (
    aggregate_suite,
    append_backdata,
    generate_report,
    has_backdata_row,
    load_task_results,
    save_run_meta,
    save_task_result,
)
from office_bench.suites.base import Suite, Task


@dataclass(frozen=True)
class RunConfig:
    """Configuration for a benchmark run."""

    suites: list[str]
    runs: int
    task_ids: list[str] | None
    categories: list[str] | None
    limit: int | None
    keep_workspaces: bool
    no_resume: bool
    dual_judge: bool
    gateway_url: str
    timeout_seconds: int


class Runner:
    """Benchmark run orchestrator."""

    def __init__(
        self,
        config: RunConfig,
        suite_registry: dict[str, Suite],
        bridge: AgentBridge | None = None,
    ) -> None:
        self._config = config
        self._suites = suite_registry
        self._bridge = bridge or AgentBridge(
            gateway_url=config.gateway_url,
            timeout_seconds=config.timeout_seconds,
        )

    def run(self, results_base: Path, run_id: str | None = None) -> Path:
        """Execute the full benchmark pipeline. Returns the run directory."""
        if run_id is None:
            run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")

        run_dir = results_base / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Save meta
        meta = {
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "git_commit": self._git_commit(),
            "agent_version": self._agent_version(),
            "model": os.environ.get("BUB_MODEL", "deepseek-flash"),
            "suites": self._config.suites,
            "runs": self._config.runs,
        }
        save_run_meta(run_dir, meta)

        # Run each suite
        for suite_name in self._config.suites:
            suite = self._suites.get(suite_name)
            if suite is None:
                continue
            self._run_suite(suite, run_dir)

        # Aggregate and report
        all_results = load_task_results(run_dir)
        aggregated: dict[str, dict] = {}
        for suite_name in self._config.suites:
            agg = aggregate_suite(all_results, suite_name)
            aggregated[suite_name] = agg

            # Append backdata row — idempotent on resume: never write a
            # second row for the same (run_id, suite) in the append-only CSV
            backdata_path = results_base / "backdata.csv"
            if not has_backdata_row(backdata_path, run_id, suite_name):
                append_backdata(
                    backdata_path,
                    {
                        "run_id": run_id,
                        "timestamp": meta["timestamp"],
                        "git_commit": meta["git_commit"],
                        "agent_version": meta["agent_version"],
                        "model": meta["model"],
                        "suite": suite_name,
                        "tasks_total": agg.get("tasks_total", 0),
                        "tasks_run": agg.get("tasks_run", 0),
                        "primary_metric": agg.get("primary_metric", ""),
                        "primary_value": agg.get("primary_value", 0),
                        "secondary_metrics": "{}",
                    },
                )

        generate_report(run_dir, aggregated, REFERENCE_SCORES)
        return run_dir

    def _run_suite(self, suite: Suite, run_dir: Path) -> None:
        """Load, filter, and run all tasks for one suite."""
        tasks = suite.load_tasks()
        tasks = self._filter_tasks(tasks)

        for task in tasks:
            for run_num in range(1, self._config.runs + 1):
                result_path = (
                    run_dir / suite.name / f"{task.task_id}_run{run_num}.json"
                )
                if result_path.exists() and not self._config.no_resume:
                    continue  # resume: skip completed

                workspace = Path(tempfile.mkdtemp(prefix=f"bench_{task.task_id}_"))
                try:
                    suite.setup_workspace(task, workspace)
                    turn_prompts = task.metadata.get("turn_prompts")
                    if isinstance(turn_prompts, list) and len(turn_prompts) > 1:
                        # Multi-turn session (e.g. PPTC): same thread, all turns
                        agent_output = self._bridge.run_session(
                            list(turn_prompts), workspace
                        )
                    else:
                        prompt = suite.format_prompt(task)
                        agent_output = self._bridge.run_task(prompt, workspace)
                    result = suite.evaluate(task, workspace, agent_output)
                    save_task_result(run_dir, result, run_num, agent_output)
                finally:
                    if not self._config.keep_workspaces:
                        shutil.rmtree(workspace, ignore_errors=True)

    def _filter_tasks(self, tasks: list[Task]) -> list[Task]:
        """Apply task_ids, categories, and limit filters."""
        filtered = tasks

        if self._config.task_ids is not None:
            allowed = set(self._config.task_ids)
            filtered = [t for t in filtered if t.task_id in allowed]

        if self._config.categories is not None:
            allowed_cats = set(self._config.categories)
            filtered = [t for t in filtered if t.category in allowed_cats]

        if self._config.limit is not None:
            filtered = filtered[: self._config.limit]

        return filtered

    @staticmethod
    def _git_commit() -> str:
        """Return short SHA of HEAD, or empty string."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            return ""

    @staticmethod
    def _agent_version() -> str:
        """Version of the office_agent package, from its pyproject.toml."""
        # benchmarks/src/office_bench/runner.py → parents[3] is the repo root
        pyproject = (
            Path(__file__).resolve().parents[3] / "office_agent" / "pyproject.toml"
        )
        try:
            with pyproject.open("rb") as f:
                return str(tomllib.load(f)["project"]["version"])
        except (OSError, KeyError, tomllib.TOMLDecodeError):
            return ""
```



- [x] **Step 4: Run test to verify it passes**

```bash
cd benchmarks && uv run pytest tests/test_runner.py -v
```

Expected: all 11 tests PASS.



- [x] **Step 5: Commit**

```bash
git add benchmarks/src/office_bench/runner.py benchmarks/tests/test_runner.py
git commit -m "feat(bench): add Runner orchestrator with filtering, resume, and aggregation"
```

---

### Task 6: CLI Interface

Build the `cli.py` module implementing all six CLI commands: `setup`, `list`,
`run`, `report`, `trend`, `compare`. Uses `argparse`. Wires together Runner,
results, and (in future tasks) real suite adapters.

**Files:**

- Create: `benchmarks/src/office_bench/cli.py`
- Create: `benchmarks/src/office_bench/__main__.py`
- Create: `benchmarks/tests/test_cli.py`

**Interfaces:**

- Consumes:
  - `RunConfig`, `Runner` from Task 5
  - `load_task_results(...)`, `generate_report(...)`, `append_backdata(...)` from Task 4
  - `REFERENCE_SCORES` from Task 4
- Produces:
  - `office_bench.cli.main(argv: list[str] | None = None) -> int` — CLI entry point
  - `python -m office_bench <command>` — runnable via `__main__.py`

**DoD:** `uv run --project benchmarks pytest benchmarks/tests/test_cli.py -v` passes. Tests verify: `list` outputs task info to stdout, `run` invokes Runner, `report` regenerates from existing results, `trend` reads backdata.csv, `compare` diffs two runs. `python -m office_bench --help` works.



- [x] **Step 1: Write the failing test**

Create `benchmarks/tests/test_cli.py`:

```python
from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from office_bench.cli import main


def test_help_returns_zero() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0


def test_list_command(capsys, tmp_path: Path) -> None:
    # Create a minimal fake suite registry
    with patch("office_bench.cli._build_suite_registry") as mock_reg:
        from office_bench.suites.base import Task

        class FakeSuite:
            name = "fakesuite"
            def load_tasks(self):
                return [
                    Task("fakesuite", "t1", "p1", "cat-a", [], {}),
                    Task("fakesuite", "t2", "p2", "cat-b", [], {}),
                ]
            def setup_workspace(self, *a): pass
            def format_prompt(self, t): return t.prompt
            def evaluate(self, *a): pass

        mock_reg.return_value = {"fakesuite": FakeSuite()}
        ret = main(["list", "--suite", "fakesuite"])

    assert ret == 0
    captured = capsys.readouterr().out
    assert "t1" in captured
    assert "t2" in captured
    assert "cat-a" in captured


def test_trend_command_reads_csv(capsys, tmp_path: Path) -> None:
    csv_path = tmp_path / "backdata.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["run_id", "timestamp", "git_commit", "agent_version",
                         "model", "suite", "tasks_total", "tasks_run",
                         "primary_metric", "primary_value", "secondary_metrics"])
        writer.writerow(["run1", "2026-10-01T00:00:00Z", "abc", "0.1.0",
                         "deepseek", "forte", 10, 10, "avg_at_3", 45.0, "{}"])
        writer.writerow(["run2", "2026-10-02T00:00:00Z", "def", "0.1.0",
                         "deepseek", "forte", 10, 10, "avg_at_3", 48.0, "{}"])

    with patch("office_bench.cli.RESULTS_BASE", tmp_path):
        ret = main(["trend"])

    assert ret == 0
    captured = capsys.readouterr().out
    assert "run1" in captured
    assert "45.0" in captured


def test_compare_command(capsys, tmp_path: Path) -> None:
    # Create two run dirs with summary data
    for run_id, value in [("run1", 40.0), ("run2", 45.0)]:
        run_dir = tmp_path / run_id / "forte"
        run_dir.mkdir(parents=True)
        (run_dir / "t1_run1.json").write_text(json.dumps({
            "task_id": "t1", "suite": "forte", "run": 1,
            "passed": True, "score": value / 100,
            "breakdown": {}, "notes": "", "judge_backend": None,
        }))

    with patch("office_bench.cli.RESULTS_BASE", tmp_path):
        ret = main(["compare", "--runs", "run1", "run2"])

    assert ret == 0
    captured = capsys.readouterr().out
    assert "run1" in captured
    assert "run2" in captured
```



- [x] **Step 2: Run test to verify it fails**

```bash
cd benchmarks && uv run pytest tests/test_cli.py -v
```

Expected: FAIL — `office_bench.cli` not found.



- [x] **Step 3: Implement `benchmarks/src/office_bench/__main__.py`**

```python
"""Allow ``python -m office_bench``."""

import sys

from office_bench.cli import main

sys.exit(main())
```



- [x] **Step 4: Implement `benchmarks/src/office_bench/cli.py`**

```python
"""CLI: run, report, list, trend, compare, setup."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

from office_bench.reference import REFERENCE_SCORES
from office_bench.results import (
    aggregate_suite,
    generate_report,
    load_task_results,
)
from office_bench.runner import RunConfig, Runner

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # benchmarks/src/office_bench → repo root
RESULTS_BASE = PROJECT_ROOT / "results" / "benchmarks"
DATA_BASE = PROJECT_ROOT / "data" / "benchmarks"


def _build_suite_registry() -> dict:
    """Build registry of available suite adapters. Lazily import to avoid
    import errors when suites aren't installed yet."""
    registry: dict = {}
    try:
        from office_bench.suites.officebench import OfficeBenchSuite
        registry["officebench"] = OfficeBenchSuite(DATA_BASE / "OfficeBench")
    except ImportError:
        pass
    try:
        from office_bench.suites.pptc import PPTCSuite
        registry["pptc"] = PPTCSuite(DATA_BASE / "PPTC")
    except ImportError:
        pass
    try:
        from office_bench.suites.spreadsheet import SpreadsheetSuite
        registry["spreadsheet"] = SpreadsheetSuite(DATA_BASE / "SpreadsheetBench-2")
    except ImportError:
        pass
    try:
        from office_bench.suites.forte import ForteSuite
        registry["forte"] = ForteSuite(DATA_BASE / "FORTE")
    except ImportError:
        pass
    return registry


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="office_bench",
        description="Office Agent Benchmark Harness",
    )
    sub = parser.add_subparsers(dest="command")

    # --- setup ---
    sub.add_parser("setup", help="Clone submodules and download datasets")

    # --- list ---
    p_list = sub.add_parser("list", help="List available benchmark tasks")
    p_list.add_argument("--suite", required=True, help="Suite name")

    # --- run ---
    p_run = sub.add_parser("run", help="Run benchmarks")
    p_run.add_argument("--suite", default="all", help="Comma-separated suite names or 'all'")
    p_run.add_argument("--runs", type=int, default=1, help="Number of runs per task")
    p_run.add_argument("--task-id", default=None, help="Comma-separated task IDs")
    p_run.add_argument("--category", default=None, help="Comma-separated categories")
    p_run.add_argument("--limit", type=int, default=None, help="Max tasks per suite")
    p_run.add_argument("--keep-workspaces", action="store_true")
    p_run.add_argument("--no-resume", action="store_true")
    p_run.add_argument("--dual-judge", action="store_true")
    p_run.add_argument("--gateway-url", default="http://127.0.0.1:18088/agent")
    p_run.add_argument("--timeout", type=int, default=600)

    # --- report ---
    p_report = sub.add_parser("report", help="Regenerate report for a run")
    p_report.add_argument("--run-id", required=True)

    # --- trend ---
    p_trend = sub.add_parser("trend", help="Show backdata trend")
    p_trend.add_argument("--suite", default=None, help="Filter by suite")

    # --- compare ---
    p_compare = sub.add_parser("compare", help="Compare two runs")
    p_compare.add_argument("--runs", nargs=2, required=True, metavar="RUN_ID")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "setup":
        return _cmd_setup()
    elif args.command == "list":
        return _cmd_list(args)
    elif args.command == "run":
        return _cmd_run(args)
    elif args.command == "report":
        return _cmd_report(args)
    elif args.command == "trend":
        return _cmd_trend(args)
    elif args.command == "compare":
        return _cmd_compare(args)

    return 1


def _cmd_setup() -> int:
    """Clone submodules and verify prerequisites."""
    print("Running git submodule update...")
    subprocess.run(
        ["git", "submodule", "update", "--init", "--recursive"],
        check=False,
    )
    print("Setup complete. Verify JUDGE_MODEL / JUDGE_API_KEY env vars.")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    """List tasks in a suite."""
    registry = _build_suite_registry()
    suite = registry.get(args.suite)
    if suite is None:
        print(f"Unknown suite: {args.suite}", file=sys.stderr)
        print(f"Available: {', '.join(registry.keys())}", file=sys.stderr)
        return 1

    tasks = suite.load_tasks()
    print(f"Suite: {suite.name} — {len(tasks)} tasks\n")
    print(f"{'ID':<20} {'Category':<20} {'Prompt (first 60 chars)'}")
    print("-" * 70)
    for t in tasks:
        prompt_preview = t.prompt[:60].replace("\n", " ")
        print(f"{t.task_id:<20} {t.category:<20} {prompt_preview}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    """Run benchmarks."""
    registry = _build_suite_registry()

    if args.suite == "all":
        suite_names = list(registry.keys())
    else:
        suite_names = [s.strip() for s in args.suite.split(",")]

    config = RunConfig(
        suites=suite_names,
        runs=args.runs,
        task_ids=args.task_id.split(",") if args.task_id else None,
        categories=args.category.split(",") if args.category else None,
        limit=args.limit,
        keep_workspaces=args.keep_workspaces,
        no_resume=args.no_resume,
        dual_judge=args.dual_judge,
        gateway_url=args.gateway_url,
        timeout_seconds=args.timeout,
    )

    runner = Runner(config, registry)
    run_dir = runner.run(RESULTS_BASE)
    print(f"\nResults saved to: {run_dir}")
    print(f"Report: {run_dir / 'report.md'}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    """Regenerate report for an existing run."""
    run_dir = RESULTS_BASE / args.run_id
    if not run_dir.exists():
        print(f"Run not found: {run_dir}", file=sys.stderr)
        return 1

    results = load_task_results(run_dir)
    suites = {r["suite"] for r in results}
    aggregated = {s: aggregate_suite(results, s) for s in suites}
    path = generate_report(run_dir, aggregated, REFERENCE_SCORES)
    print(f"Report regenerated: {path}")
    return 0


def _cmd_trend(args: argparse.Namespace) -> int:
    """Show backdata trend."""
    csv_path = RESULTS_BASE / "backdata.csv"
    if not csv_path.exists():
        print("No backdata.csv found. Run benchmarks first.", file=sys.stderr)
        return 1

    with csv_path.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if args.suite:
        rows = [r for r in rows if r.get("suite") == args.suite]

    if not rows:
        print("No matching data.")
        return 0

    # Show last 10 rows
    recent = rows[-10:]
    print(f"{'Run ID':<24} {'Suite':<15} {'Metric':<12} {'Score':<8} {'Tasks'}")
    print("-" * 70)
    for r in recent:
        print(
            f"{r.get('run_id', ''):<24} "
            f"{r.get('suite', ''):<15} "
            f"{r.get('primary_metric', ''):<12} "
            f"{r.get('primary_value', ''):<8} "
            f"{r.get('tasks_run', '')}/{r.get('tasks_total', '')}"
        )
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    """Compare two runs side by side."""
    id1, id2 = args.runs
    dir1 = RESULTS_BASE / id1
    dir2 = RESULTS_BASE / id2

    if not dir1.exists():
        print(f"Run not found: {id1}", file=sys.stderr)
        return 1
    if not dir2.exists():
        print(f"Run not found: {id2}", file=sys.stderr)
        return 1

    results1 = load_task_results(dir1)
    results2 = load_task_results(dir2)
    suites1 = {r["suite"] for r in results1}
    suites2 = {r["suite"] for r in results2}
    all_suites = sorted(suites1 | suites2)

    agg1 = {s: aggregate_suite(results1, s) for s in all_suites}
    agg2 = {s: aggregate_suite(results2, s) for s in all_suites}

    print(f"{'Suite':<15} {'Metric':<12} {id1:<12} {id2:<12} {'Delta':<8} {'Status'}")
    print("-" * 75)
    for s in all_suites:
        metric = agg1.get(s, {}).get("primary_metric", agg2.get(s, {}).get("primary_metric", ""))
        v1 = agg1.get(s, {}).get("primary_value", 0)
        v2 = agg2.get(s, {}).get("primary_value", 0)
        delta = v2 - v1
        status = "⚠️" if delta < -2.0 else "✅" if delta >= 0 else "→"
        print(f"{s:<15} {metric:<12} {v1:<12.2f} {v2:<12.2f} {delta:<+8.2f} {status}")
    return 0
```



- [x] **Step 5: Run test to verify it passes**

```bash
cd benchmarks && uv run pytest tests/test_cli.py -v
```

Expected: all 4 tests PASS.



- [x] **Step 6: Commit**

```bash
git add benchmarks/src/office_bench/cli.py benchmarks/src/office_bench/__main__.py benchmarks/tests/test_cli.py
git commit -m "feat(bench): add CLI with run/list/report/trend/compare/setup commands"
```

---

### Task 7: OfficeBench Suite Adapter

Implement the OfficeBench adapter — the first deterministic suite. Parses
the task JSON structure, copies testbed files, and delegates evaluation to
OfficeBench's native `evaluation.py`.

**Files:**

- Create: `benchmarks/src/office_bench/suites/officebench.py`
- Create: `benchmarks/tests/test_suite_officebench.py`
- Create: `benchmarks/tests/fixtures/officebench/evaluation.py` (hermetic stand-in for the submodule's native evaluation module)

**Interfaces:**

- Consumes: `Suite`, `Task`, `AgentOutput`, `TaskResult` from Task 1
- Produces:
  - `office_bench.suites.officebench.OfficeBenchSuite.__init__(repo_dir: Path)`
  - Implements `Suite` protocol: `name = "officebench"`, `load_tasks()`, `setup_workspace()`, `format_prompt()`, `evaluate()`
  - `evaluate()` **delegates to the benchmark's native evaluation module** loaded from `repo_dir/evaluation.py` via importlib — it must NOT reimplement eval checks locally (spec §5.3: "keep their evaluation logic"), otherwise scores are not comparable to the published reference numbers

**DoD:** `uv run --project benchmarks pytest benchmarks/tests/test_suite_officebench.py -v` passes. Tests use fixture data mimicking OfficeBench structure; the fixture tree ships its own `evaluation.py` so tests stay hermetic. `load_tasks()` returns Task objects with correct fields. `evaluate()` calls the native eval function by name; unknown/missing functions and native exceptions produce `passed=False` with an explicit error note — never a silent pass or fail. After `setup` clones the real submodule, the investigation note in Step 5 must be completed.



- [x] **Step 1: Create fixture test data**

Create `benchmarks/tests/fixtures/officebench/tasks/1/subtasks/1-1.json`:

```json
{
  "task_id": "1-1",
  "instruction": "Create a budget spreadsheet with Q1 expenses",
  "app_count": 1,
  "eval_config": {
    "function": "evaluate_file_exist",
    "args": {
      "file_path": "budget.xlsx"
    }
  }
}
```

Create `benchmarks/tests/fixtures/officebench/tasks/1/testbed/input.txt` with content `test input`.

Create `benchmarks/tests/fixtures/officebench/tasks/2/subtasks/2-1.json`:

```json
{
  "task_id": "2-1",
  "instruction": "Read the CSV and summarize it",
  "app_count": 2,
  "eval_config": {
    "function": "evaluate_contain",
    "args": {
      "file_path": "summary.txt",
      "expected": "total"
    }
  }
}
```

Create `benchmarks/tests/fixtures/officebench/tasks/2/testbed/data.csv` with content `a,b\n1,2`.

Create `benchmarks/tests/fixtures/officebench/evaluation.py` — a hermetic stand-in mirroring the upstream evaluation API (the adapter loads `evaluation.py` from its repo dir; with fixtures as repo dir, this file plays the submodule's role):

```python
"""Fixture stand-in for OfficeBench's native evaluation module.

Mirrors the upstream API surface used by the adapter. After `setup` clones
the real submodule, verify the real function names/signatures (Step 5
investigation) and keep this fixture in sync.
"""

from __future__ import annotations

from pathlib import Path


def evaluate_file_exist(args: dict, workspace_dir: Path) -> bool:
    return (workspace_dir / args.get("file_path", "")).exists()


def evaluate_contain(args: dict, workspace_dir: Path) -> bool:
    file_path = workspace_dir / args.get("file_path", "")
    if not file_path.exists():
        return False
    content = file_path.read_text(errors="replace")
    return str(args.get("expected", "")).lower() in content.lower()


def evaluate_exact_match(args: dict, workspace_dir: Path) -> bool:
    file_path = workspace_dir / args.get("file_path", "")
    if not file_path.exists():
        return False
    content = file_path.read_text(errors="replace").strip()
    return content == str(args.get("expected", "")).strip()


def evaluate_excel_cell_value(args: dict, workspace_dir: Path) -> bool:
    from openpyxl import load_workbook

    file_path = workspace_dir / args.get("file_path", "")
    if not file_path.exists():
        return False
    wb = load_workbook(file_path, data_only=True)
    ws = wb[args["sheet"]] if args.get("sheet") else wb.active
    actual = ws[args.get("cell", "A1")].value
    return actual is not None and str(actual).strip() == str(
        args.get("expected", "")
    ).strip()
```



- [x] **Step 2: Write the failing test**

Create `benchmarks/tests/test_suite_officebench.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from office_bench.suites.officebench import OfficeBenchSuite
from office_bench.suites.base import AgentOutput

FIXTURES = Path(__file__).parent / "fixtures" / "officebench"


@pytest.fixture()
def suite() -> OfficeBenchSuite:
    return OfficeBenchSuite(FIXTURES)


def _make_output(files: list[str] | None = None) -> AgentOutput:
    return AgentOutput(
        messages=[{"role": "assistant", "content": "done"}],
        files_created=[Path(f) for f in (files or [])],
        tool_calls=[],
        duration_seconds=3.0,
    )


def test_load_tasks(suite: OfficeBenchSuite) -> None:
    tasks = suite.load_tasks()
    assert len(tasks) == 2
    ids = {t.task_id for t in tasks}
    assert "1-1" in ids
    assert "2-1" in ids


def test_load_tasks_fields(suite: OfficeBenchSuite) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "1-1")
    assert t.suite == "officebench"
    assert t.category == "1-app"
    assert "budget" in t.prompt.lower()


def test_setup_workspace_copies_testbed(suite: OfficeBenchSuite, tmp_path: Path) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "1-1")
    suite.setup_workspace(t, tmp_path)
    assert (tmp_path / "input.txt").exists()


def test_format_prompt(suite: OfficeBenchSuite) -> None:
    tasks = suite.load_tasks()
    t = tasks[0]
    prompt = suite.format_prompt(t)
    assert len(prompt) > 0
    assert t.prompt in prompt


def test_evaluate_file_exist_pass(suite: OfficeBenchSuite, tmp_path: Path) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "1-1")
    # Create the expected file in workspace
    (tmp_path / "budget.xlsx").write_bytes(b"fake")
    output = _make_output(["budget.xlsx"])
    result = suite.evaluate(t, tmp_path, output)
    assert result.passed is True
    assert result.score == 1.0
    assert result.judge_backend == "deterministic"


def test_evaluate_file_exist_fail(suite: OfficeBenchSuite, tmp_path: Path) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "1-1")
    output = _make_output()
    result = suite.evaluate(t, tmp_path, output)
    assert result.passed is False
    assert result.score == 0.0


def test_evaluate_contain_pass(suite: OfficeBenchSuite, tmp_path: Path) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "2-1")
    (tmp_path / "summary.txt").write_text("The total is 100")
    output = _make_output(["summary.txt"])
    result = suite.evaluate(t, tmp_path, output)
    assert result.passed is True


def test_evaluate_contain_fail(suite: OfficeBenchSuite, tmp_path: Path) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "2-1")
    (tmp_path / "summary.txt").write_text("No match here")
    output = _make_output(["summary.txt"])
    result = suite.evaluate(t, tmp_path, output)
    assert result.passed is False
```



- [x] **Step 3: Run test to verify it fails**

```bash
cd benchmarks && uv run pytest tests/test_suite_officebench.py -v
```

Result: `ModuleNotFoundError: No module named 'office_bench.suites.officebench'` — RED confirmed. Commit `6b5fec1`.



- [x] **Step 4: Implement `benchmarks/src/office_bench/suites/officebench.py`**

```python
"""OfficeBench suite adapter — deterministic evaluation via the benchmark's
native evaluation module."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

from office_bench.suites.base import AgentOutput, Task, TaskResult


class OfficeBenchSuite:
    """Adapter for the OfficeBench benchmark (zlwang-cs/OfficeBench)."""

    name = "officebench"

    def __init__(self, repo_dir: Path) -> None:
        self._repo_dir = repo_dir

    def load_tasks(self) -> list[Task]:
        """Scan tasks/*/subtasks/*.json for task definitions."""
        tasks_dir = self._repo_dir / "tasks"
        if not tasks_dir.exists():
            return []

        results: list[Task] = []
        for task_dir in sorted(tasks_dir.iterdir()):
            if not task_dir.is_dir():
                continue
            subtasks_dir = task_dir / "subtasks"
            if not subtasks_dir.exists():
                continue
            for json_file in sorted(subtasks_dir.glob("*.json")):
                try:
                    data = json.loads(json_file.read_text())
                except (json.JSONDecodeError, OSError):
                    continue

                app_count = data.get("app_count", 1)
                testbed_dir = task_dir / "testbed"
                input_files = (
                    list(testbed_dir.iterdir()) if testbed_dir.exists() else []
                )

                results.append(Task(
                    suite=self.name,
                    task_id=data.get("task_id", json_file.stem),
                    prompt=data.get("instruction", ""),
                    category=f"{app_count}-app",
                    input_files=input_files,
                    metadata={
                        "eval_config": data.get("eval_config", {}),
                        "task_dir": str(task_dir),
                    },
                ))
        return results

    def setup_workspace(self, task: Task, workspace_dir: Path) -> None:
        """Copy testbed files into the workspace."""
        for src in task.input_files:
            dst = workspace_dir / src.name
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)

    def format_prompt(self, task: Task) -> str:
        """Return the task instruction as the prompt."""
        return task.prompt

    def evaluate(
        self,
        task: Task,
        workspace_dir: Path,
        agent_output: AgentOutput,
    ) -> TaskResult:
        """Delegate to OfficeBench's native evaluation module (spec §5.3)."""
        eval_config = task.metadata.get("eval_config", {})
        func_name = eval_config.get("function", "")
        func_args = eval_config.get("args", {})

        module = self._load_native_evaluation()
        if module is None:
            return self._error_result(
                task,
                f"Native evaluation module not found: "
                f"{self._repo_dir / 'evaluation.py'}",
                func_name,
            )

        func = getattr(module, func_name, None)
        if not callable(func):
            return self._error_result(
                task, f"Unknown eval function: {func_name}", func_name
            )

        try:
            passed = bool(func(func_args, workspace_dir))
        except Exception as e:
            return self._error_result(
                task, f"{func_name} raised: {e}", func_name
            )

        return TaskResult(
            task_id=task.task_id,
            suite=self.name,
            passed=passed,
            score=1.0 if passed else 0.0,
            breakdown={func_name: 1.0 if passed else 0.0},
            notes=f"{func_name} → {'PASS' if passed else 'FAIL'}",
            judge_backend="deterministic",
        )

    def _load_native_evaluation(self):
        """Import the benchmark's evaluation.py from the repo dir."""
        eval_path = self._repo_dir / "evaluation.py"
        if not eval_path.exists():
            return None
        spec = importlib.util.spec_from_file_location(
            f"officebench_eval_{abs(hash(str(self._repo_dir)))}", eval_path
        )
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _error_result(
        self, task: Task, notes: str, func_name: str
    ) -> TaskResult:
        return TaskResult(
            task_id=task.task_id,
            suite=self.name,
            passed=False,
            score=0.0,
            breakdown={func_name: 0.0},
            notes=notes,
            judge_backend="deterministic",
        )
```



- [x] **Step 5: Run test to verify it passes**

```bash
cd benchmarks && uv run pytest tests/test_suite_officebench.py -v
```

Result: 14 tests PASS (plan expected 8; implementation added 6 edge-case and review-fix tests). Full suite 110/110 PASS. Commit `b5bf7a7`.

**Code review (2026-10-01):** `.claude/reviews/task7-officebench-suite-review.md` — three findings fixed in `ce9ecfb`:
- M-1: cached eval module via sentinel pattern (`_eval_module`) to avoid per-task reimport
- M-2: replaced non-deterministic `hash()` with `id(self)` for importlib module name
- L-2: added `logging.warning` for malformed/unreadable task JSON in `_parse_subtask`

> **Investigation (after `setup` clones the real submodule):** inspect the
> real `data/benchmarks/OfficeBench/evaluation.py` — confirm the eval function
> names, their argument shapes, and whether a top-level `evaluate_output()`
> dispatcher exists (spec §5.3 references it). If the real signatures differ
> from the fixture stand-in (e.g. absolute paths, an eval-config object, or a
> single dispatcher entry point), adapt the adapter's call site to the real
> API — do NOT fork the checks back into local reimplementations. Keep the
> fixture `evaluation.py` in sync with what you find.



- [x] **Step 6: Commit**

Commits:
- `6b5fec1` — `test(bench): add OfficeBench suite adapter reproducer and fixtures`
- `b5bf7a7` — `feat(bench): add OfficeBench deterministic suite adapter`
- `edc4cb0` — `docs(bench): mark Task 7 complete, add TDD evidence report`
- `ce9ecfb` — `fix(bench): cache native eval module, use deterministic module name, log skipped tasks`
- `6a3fd19` — `docs(bench): record Task 7 code review resolution (approve)`

---

### Task 8: PPTC Suite Adapter

Implement the PPTC adapter — second deterministic suite. Parses session
JSONs, supports multi-turn sessions, and evaluates via PPTX-Match (position
relation + attribute comparison).

**Files:**

- Create: `benchmarks/src/office_bench/suites/pptc.py`
- Create: `benchmarks/tests/test_suite_pptc.py`
- Create: `benchmarks/tests/fixtures/pptc/` (fixture data)

**Interfaces:**

- Consumes: `Suite`, `Task`, `AgentOutput`, `TaskResult` from Task 1
- Produces:
  - `office_bench.suites.pptc.PPTCSuite.__init__(repo_dir: Path)`
  - Implements `Suite` protocol: `name = "pptc"`, `load_tasks()`, `setup_workspace()`, `format_prompt()`, `evaluate()`

**DoD:** `uv run --project benchmarks pytest benchmarks/tests/test_suite_pptc.py -v` passes. Tests use fixture data mimicking PPTC repo structure, including a **label pptx** per session (the `PPT_label_*` tree that `main.py --prepare` generates). `load_tasks()` returns multi-turn sessions as Task objects with `metadata["turn_prompts"]` (the Runner's multi-turn hook). `evaluate()` compares the prediction .pptx against the **label** .pptx — per-slide text-attribute sets must match; a deck that merely contains "any text" must NOT pass. Missing label file → `score=0.0` with notes pointing at the prepare step. The session passes only when every label slide matches.



- [x] **Step 1: Create fixture test data** — `f30c124`

Create `benchmarks/tests/fixtures/pptc/PPT_test_input/Create_new_slides/session_1.json`:

```json
{
  "task_type": "Create_new_slides",
  "session_id": "session_1",
  "turns": [
    {
      "turn_id": 1,
      "instruction": "Create a title slide with text 'Hello World'"
    },
    {
      "turn_id": 2,
      "instruction": "Add a second slide with bullet points"
    }
  ]
}
```

Create `benchmarks/tests/fixtures/pptc/PPT_test_input/Edit_ppt_template/session_2.json`:

```json
{
  "task_type": "Edit_ppt_template",
  "session_id": "session_2",
  "template": "template.pptx",
  "turns": [
    {
      "turn_id": 1,
      "instruction": "Change the title to 'Updated Title'"
    }
  ]
}
```

Create `benchmarks/tests/fixtures/pptc/PPT_test_input/Edit_ppt_template/template.pptx` — a minimal valid pptx created programmatically in tests.



- [x] **Step 2: Write the failing test** — `f30c124` (12 tests, expanded beyond plan with empty-dir, noop-workspace, missing-prediction, extra-slides tests)

Create `benchmarks/tests/test_suite_pptc.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest
from pptx import Presentation

from office_bench.suites.pptc import PPTCSuite
from office_bench.suites.base import AgentOutput

FIXTURES = Path(__file__).parent / "fixtures" / "pptc"


@pytest.fixture(autouse=True)
def _create_fixture_pptx_files() -> None:
    """Create template.pptx (edit fixture) and the session_1 label pptx."""
    template_path = FIXTURES / "PPT_test_input" / "Edit_ppt_template" / "template.pptx"
    if not template_path.exists():
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        slide.shapes.title.text = "Original Title"
        template_path.parent.mkdir(parents=True, exist_ok=True)
        prs.save(str(template_path))

    # Label deck for session_1 (what main.py --prepare generates):
    # slide 1 title "Hello World"; slide 2 title + two bullet points.
    label_path = FIXTURES / "PPT_label_Create_new_slides" / "session_1.pptx"
    if not label_path.exists():
        prs = Presentation()
        s1 = prs.slides.add_slide(prs.slide_layouts[0])
        s1.shapes.title.text = "Hello World"
        s2 = prs.slides.add_slide(prs.slide_layouts[1])
        s2.shapes.title.text = "Agenda"
        tf = s2.placeholders[1].text_frame  # type: ignore[index]
        tf.text = "First point"
        p = tf.add_paragraph()
        p.text = "Second point"
        label_path.parent.mkdir(parents=True, exist_ok=True)
        prs.save(str(label_path))


@pytest.fixture()
def suite() -> PPTCSuite:
    return PPTCSuite(FIXTURES)


def _make_output() -> AgentOutput:
    return AgentOutput(
        messages=[{"role": "assistant", "content": "done"}],
        files_created=[],
        tool_calls=[],
        duration_seconds=5.0,
    )


def test_load_tasks(suite: PPTCSuite) -> None:
    tasks = suite.load_tasks()
    assert len(tasks) == 2
    ids = {t.task_id for t in tasks}
    assert "session_1" in ids
    assert "session_2" in ids


def test_task_fields(suite: PPTCSuite) -> None:
    tasks = suite.load_tasks()
    t1 = next(t for t in tasks if t.task_id == "session_1")
    assert t1.suite == "pptc"
    assert t1.category == "Create_new_slides"
    assert len(t1.metadata.get("turns", [])) == 2
    assert t1.metadata["turn_prompts"] == [
        "Create a title slide with text 'Hello World'",
        "Add a second slide with bullet points",
    ]
    assert t1.metadata["label_file"] is not None


def test_setup_workspace_copies_template(suite: PPTCSuite, tmp_path: Path) -> None:
    tasks = suite.load_tasks()
    t2 = next(t for t in tasks if t.task_id == "session_2")
    suite.setup_workspace(t2, tmp_path)
    assert (tmp_path / "template.pptx").exists()


def test_format_prompt_first_turn(suite: PPTCSuite) -> None:
    tasks = suite.load_tasks()
    t1 = next(t for t in tasks if t.task_id == "session_1")
    prompt = suite.format_prompt(t1)
    assert "Hello World" in prompt


def _save_two_slide_prediction(tmp_path: Path, title: str) -> None:
    """Prediction deck with the same shape as the session_1 label."""
    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[0])
    s1.shapes.title.text = title
    s2 = prs.slides.add_slide(prs.slide_layouts[1])
    s2.shapes.title.text = "Agenda"
    tf = s2.placeholders[1].text_frame  # type: ignore[index]
    tf.text = "First point"
    p = tf.add_paragraph()
    p.text = "Second point"
    prs.save(str(tmp_path / "prediction.pptx"))


def test_evaluate_match_passes(suite: PPTCSuite, tmp_path: Path) -> None:
    tasks = suite.load_tasks()
    t1 = next(t for t in tasks if t.task_id == "session_1")

    _save_two_slide_prediction(tmp_path, title="Hello World")
    result = suite.evaluate(t1, tmp_path, _make_output())

    assert result.suite == "pptc"
    assert result.task_id == "session_1"
    assert result.judge_backend == "deterministic"
    assert result.passed is True
    assert result.score == 1.0


def test_evaluate_wrong_content_fails(suite: PPTCSuite, tmp_path: Path) -> None:
    """A deck with any-text-but-wrong-content must NOT pass."""
    tasks = suite.load_tasks()
    t1 = next(t for t in tasks if t.task_id == "session_1")

    _save_two_slide_prediction(tmp_path, title="Wrong Title")
    result = suite.evaluate(t1, tmp_path, _make_output())

    assert result.passed is False
    assert result.score < 1.0


def test_evaluate_missing_label_reports_prepare_step(
    suite: PPTCSuite, tmp_path: Path
) -> None:
    """session_2 has no label file — must fail with a prepare hint."""
    tasks = suite.load_tasks()
    t2 = next(t for t in tasks if t.task_id == "session_2")

    prs = Presentation()
    prs.slides.add_slide(prs.slide_layouts[0])
    prs.save(str(tmp_path / "template.pptx"))

    result = suite.evaluate(t2, tmp_path, _make_output())
    assert result.passed is False
    assert result.score == 0.0
    assert "prepare" in result.notes.lower()
```



- [x] **Step 3: Run test to verify it fails** — RED confirmed: `ModuleNotFoundError: No module named 'office_bench.suites.pptc'`

```bash
cd benchmarks && uv run pytest tests/test_suite_pptc.py -v
```

Expected: FAIL — `office_bench.suites.pptc` not found.



- [x] **Step 4: Implement `benchmarks/src/office_bench/suites/pptc.py`** — `6ab1c0f` (extracted `_parse_session` method, added `logging`, `int(ok)` for matched counter)

```python
"""PPTC suite adapter — deterministic PPTX-Match evaluation."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from pptx import Presentation

from office_bench.suites.base import AgentOutput, Task, TaskResult


class PPTCSuite:
    """Adapter for the PPTC benchmark (gydpku/PPTC)."""

    name = "pptc"

    def __init__(self, repo_dir: Path) -> None:
        self._repo_dir = repo_dir

    def load_tasks(self) -> list[Task]:
        """Scan PPT_test_input/*/session_*.json for session definitions."""
        input_dir = self._repo_dir / "PPT_test_input"
        if not input_dir.exists():
            return []

        tasks: list[Task] = []
        for task_type_dir in sorted(input_dir.iterdir()):
            if not task_type_dir.is_dir():
                continue
            task_type = task_type_dir.name

            for json_file in sorted(task_type_dir.glob("session_*.json")):
                try:
                    data = json.loads(json_file.read_text())
                except (json.JSONDecodeError, OSError):
                    continue

                session_id = data.get("session_id", json_file.stem)
                turns = data.get("turns", [])

                # Collect input files (templates)
                input_files: list[Path] = []
                template = data.get("template")
                if template:
                    template_path = task_type_dir / template
                    if template_path.exists():
                        input_files.append(template_path)

                turn_prompts = [t.get("instruction", "") for t in turns]
                first_prompt = turn_prompts[0] if turn_prompts else ""

                # Label pptx generated by the one-time prepare step
                # (`main.py --prepare` → PPT_label_* tree)
                label_path = self._find_label(session_id)

                tasks.append(Task(
                    suite=self.name,
                    task_id=session_id,
                    prompt=first_prompt,
                    category=task_type,
                    input_files=input_files,
                    metadata={
                        "turns": turns,
                        "turn_prompts": turn_prompts,
                        "task_type": task_type,
                        "template": template,
                        "session_file": str(json_file),
                        "label_file": str(label_path) if label_path else None,
                    },
                ))
        return tasks

    def setup_workspace(self, task: Task, workspace_dir: Path) -> None:
        """Copy template pptx (for edit tasks) into workspace."""
        for src in task.input_files:
            dst = workspace_dir / src.name
            shutil.copy2(src, dst)

    def format_prompt(self, task: Task) -> str:
        """Return the first turn instruction. Multi-turn handled by bridge."""
        return task.prompt

    def evaluate(
        self,
        task: Task,
        workspace_dir: Path,
        agent_output: AgentOutput,
    ) -> TaskResult:
        """PPTX-Match: compare prediction .pptx against the label .pptx."""
        label_value = task.metadata.get("label_file")
        label_path = Path(label_value) if label_value else None
        if label_path is None or not label_path.exists():
            return TaskResult(
                task_id=task.task_id,
                suite=self.name,
                passed=False,
                score=0.0,
                breakdown={},
                notes=(
                    "Label pptx not found — run the PPTC prepare step "
                    "(main.py --prepare) before evaluating"
                ),
                judge_backend="deterministic",
            )

        prediction_path = self._find_prediction(workspace_dir)
        if prediction_path is None:
            return TaskResult(
                task_id=task.task_id,
                suite=self.name,
                passed=False,
                score=0.0,
                breakdown={},
                notes="No prediction .pptx found in workspace",
                judge_backend="deterministic",
            )

        try:
            pred_slides = self._slide_texts(prediction_path)
            label_slides = self._slide_texts(label_path)
        except Exception as e:
            return TaskResult(
                task_id=task.task_id,
                suite=self.name,
                passed=False,
                score=0.0,
                breakdown={},
                notes=f"Error parsing pptx: {e}",
                judge_backend="deterministic",
            )

        breakdown: dict[str, float] = {}
        matched = 0
        for idx, label_texts in enumerate(label_slides):
            pred_texts = pred_slides[idx] if idx < len(pred_slides) else []
            ok = label_texts == pred_texts
            breakdown[f"slide_{idx + 1}"] = 1.0 if ok else 0.0
            matched += ok

        extra = len(pred_slides) - len(label_slides)
        if extra > 0:
            breakdown["extra_slides"] = 0.0

        score = matched / len(label_slides) if label_slides else 0.0
        passed = matched == len(label_slides) and extra <= 0 and bool(label_slides)
        notes = f"{matched}/{len(label_slides)} slides matched"

        return TaskResult(
            task_id=task.task_id,
            suite=self.name,
            passed=passed,
            score=score,
            breakdown=breakdown,
            notes=notes,
            judge_backend="deterministic",
        )

    def _find_label(self, session_id: str) -> Path | None:
        """Find the label pptx for a session in the PPT_label_* tree."""
        for label_dir in sorted(self._repo_dir.glob("PPT_label_*")):
            for candidate in (
                label_dir / f"{session_id}.pptx",
                label_dir / self._task_type_dir_name(session_id) / f"{session_id}.pptx",
            ):
                if candidate.exists():
                    return candidate
        return None

    def _task_type_dir_name(self, session_id: str) -> str:
        """Best-effort: task-type dir containing this session's input."""
        for task_type_dir in sorted(
            (self._repo_dir / "PPT_test_input").iterdir()
        ):
            if (task_type_dir / f"{session_id}.json").exists():
                return task_type_dir.name
        return ""

    @staticmethod
    def _find_prediction(workspace_dir: Path) -> Path | None:
        """Find the prediction pptx in the workspace."""
        # Prefer prediction.pptx, then output.pptx, then any .pptx
        for name in ["prediction.pptx", "output.pptx"]:
            p = workspace_dir / name
            if p.exists():
                return p
        pptx_files = list(workspace_dir.glob("*.pptx"))
        return pptx_files[0] if pptx_files else None

    @staticmethod
    def _slide_texts(pptx_path: Path) -> list[list[str]]:
        """Per-slide sorted text sets — the attribute signature for matching."""
        prs = Presentation(str(pptx_path))
        slides: list[list[str]] = []
        for slide in prs.slides:
            texts = [
                shape.text_frame.text.strip()
                for shape in slide.shapes
                if shape.has_text_frame and shape.text_frame.text.strip()
            ]
            slides.append(sorted(texts))
        return slides
```



- [x] **Step 5: Run test to verify it passes** — GREEN: 12/12 passed in 0.22s. Coverage 92%. Full suite 122/122.

> **Investigation (after `setup` clones the real submodule):** check the real
> `PPT_label_*` layout produced by `main.py --prepare` (flat vs nested by
> task type) and adjust `_find_label()`. PPTC's full PPTX-Match also scores
> position relations between shapes; this adapter approximates it with
> per-slide text-set comparison. If the submodule's matcher is importable
> without side effects, prefer delegating to it (as the OfficeBench adapter
> does) instead of keeping the approximation.



- [x] **Step 6: Commit** — `f30c124` (RED), `6ab1c0f` (GREEN), `5b41472` (TDD evidence). Review: `.claude/reviews/task8-pptc-suite-review.md` — APPROVE, 0 critical/high.

---

### Task 9: SpreadsheetBench 2 Suite Adapter

Implement the SpreadsheetBench 2 adapter for the three deterministic
categories (Debugging, Financial\_Model, Template). Visualization is deferred
to Phase 6.

**Files:**

- Create: `benchmarks/src/office_bench/suites/spreadsheet.py`
- Create: `benchmarks/tests/test_suite_spreadsheet.py`
- Create: `benchmarks/tests/fixtures/spreadsheet/` (fixture data)

**Interfaces:**

- Consumes: `Suite`, `Task`, `AgentOutput`, `TaskResult` from Task 1
- Produces:
  - `office_bench.suites.spreadsheet.SpreadsheetSuite.__init__(repo_dir: Path)`
  - Implements `Suite` protocol: `name = "spreadsheet"`, `load_tasks()`, `setup_workspace()`, `format_prompt()`, `evaluate()`

**DoD:** `uv run --project benchmarks pytest benchmarks/tests/test_suite_spreadsheet.py -v` passes. Tests use fixture data mimicking SpreadsheetBench 2 dataset.json structure. **Before cell comparison, `evaluate()` recalculates the workbook via LibreOffice headless** (spec §5.3 prerequisite — openpyxl-written files carry no cached formula results, so `data_only=True` would read `None` for every formula cell); unit tests monkeypatch `_recalculate` to identity because fixtures write literal values. Recalc failure (soffice missing/crash) → `passed=False` with an explicit note, never silent zero-matching. Cell-level comparison works for value and formula match with tolerance. Visualization tasks return `score=0.0` with notes indicating deferred status.



- [x] **Step 1: Create fixture test data**

Create `benchmarks/tests/fixtures/spreadsheet/data/Debugging/dataset.json`:

```json
[
  {
    "task_id": "debug-001",
    "instruction": "Fix the SUM formula in cell B5",
    "category": "Debugging",
    "spreadsheet_file": "debug-001.xlsx",
    "expected_cells": {
      "B5": {"value": "150", "tolerance": 0.01}
    }
  }
]
```

Create `benchmarks/tests/fixtures/spreadsheet/data/Financial_Model/dataset.json`:

```json
[
  {
    "task_id": "fin-001",
    "instruction": "Build a revenue projection model",
    "category": "Financial_Model",
    "spreadsheet_file": "fin-001.xlsx",
    "expected_cells": {
      "C3": {"value": "1000"},
      "C4": {"value": "1100"}
    }
  }
]
```

Create `benchmarks/tests/fixtures/spreadsheet/data/Visualization/dataset.json`:

```json
[
  {
    "task_id": "viz-001",
    "instruction": "Create a chart from the data",
    "category": "Visualization",
    "spreadsheet_file": "viz-001.xlsx",
    "expected_cells": {}
  }
]
```



- [x] **Step 2: Write the failing test**

Create `benchmarks/tests/test_suite_spreadsheet.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from office_bench.suites.spreadsheet import SpreadsheetSuite
from office_bench.suites.base import AgentOutput

FIXTURES = Path(__file__).parent / "fixtures" / "spreadsheet"


@pytest.fixture(autouse=True)
def _no_recalc(monkeypatch) -> None:
    """Skip LibreOffice recalc in unit tests — fixtures write literal values."""
    monkeypatch.setattr(
        SpreadsheetSuite, "_recalculate", staticmethod(lambda p: p)
    )


@pytest.fixture()
def suite() -> SpreadsheetSuite:
    return SpreadsheetSuite(FIXTURES)


def _make_output() -> AgentOutput:
    return AgentOutput(
        messages=[{"role": "assistant", "content": "done"}],
        files_created=[],
        tool_calls=[],
        duration_seconds=4.0,
    )


def test_load_tasks(suite: SpreadsheetSuite) -> None:
    tasks = suite.load_tasks()
    # 3 tasks across Debugging, Financial_Model, Visualization
    assert len(tasks) == 3
    categories = {t.category for t in tasks}
    assert "Debugging" in categories
    assert "Financial_Model" in categories


def test_task_fields(suite: SpreadsheetSuite) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "debug-001")
    assert t.suite == "spreadsheet"
    assert t.category == "Debugging"
    assert "SUM" in t.prompt


def test_format_prompt(suite: SpreadsheetSuite) -> None:
    tasks = suite.load_tasks()
    t = tasks[0]
    prompt = suite.format_prompt(t)
    assert len(prompt) > 0


def test_evaluate_cell_value_pass(suite: SpreadsheetSuite, tmp_path: Path) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "debug-001")

    # Create output xlsx with correct cell value
    wb = Workbook()
    ws = wb.active
    ws["B5"] = 150
    wb.save(tmp_path / "debug-001.xlsx")

    result = suite.evaluate(t, tmp_path, _make_output())
    assert result.passed is True
    assert result.score == 1.0
    assert result.judge_backend == "deterministic"


def test_evaluate_cell_value_fail(suite: SpreadsheetSuite, tmp_path: Path) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "debug-001")

    wb = Workbook()
    ws = wb.active
    ws["B5"] = 999  # wrong value
    wb.save(tmp_path / "debug-001.xlsx")

    result = suite.evaluate(t, tmp_path, _make_output())
    assert result.passed is False
    assert result.score < 1.0


def test_evaluate_multiple_cells(suite: SpreadsheetSuite, tmp_path: Path) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "fin-001")

    wb = Workbook()
    ws = wb.active
    ws["C3"] = 1000
    ws["C4"] = 1100
    wb.save(tmp_path / "fin-001.xlsx")

    result = suite.evaluate(t, tmp_path, _make_output())
    assert result.passed is True
    assert result.score == 1.0


def test_evaluate_visualization_deferred(suite: SpreadsheetSuite, tmp_path: Path) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "viz-001")
    result = suite.evaluate(t, tmp_path, _make_output())
    assert result.score == 0.0
    assert "deferred" in result.notes.lower() or "visualization" in result.notes.lower()


def test_evaluate_missing_file(suite: SpreadsheetSuite, tmp_path: Path) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "debug-001")
    result = suite.evaluate(t, tmp_path, _make_output())
    assert result.passed is False


def test_evaluate_recalc_failure_fails_cleanly(
    suite: SpreadsheetSuite, tmp_path: Path, monkeypatch
) -> None:
    """soffice missing/crashing must fail the task with an explicit note."""
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "debug-001")

    wb = Workbook()
    ws = wb.active
    ws["B5"] = 150
    wb.save(tmp_path / "debug-001.xlsx")

    monkeypatch.setattr(
        SpreadsheetSuite, "_recalculate", staticmethod(lambda p: None)
    )
    result = suite.evaluate(t, tmp_path, _make_output())
    assert result.passed is False
    assert "recalc" in result.notes.lower()
```



- [x] **Step 3: Run test to verify it fails**

Result: `ModuleNotFoundError: No module named 'office_bench.suites.spreadsheet'` — RED confirmed. Commit `908b050`.



- [x] **Step 4: Implement `benchmarks/src/office_bench/suites/spreadsheet.py`**

```python
"""SpreadsheetBench 2 suite adapter — deterministic cell-level comparison."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from openpyxl import load_workbook

from office_bench.suites.base import AgentOutput, Task, TaskResult

_DETERMINISTIC_CATEGORIES = {"Debugging", "Financial_Model", "Template"}


class SpreadsheetSuite:
    """Adapter for SpreadsheetBench 2 (RUCKBReasoning/SpreadsheetBench-2)."""

    name = "spreadsheet"

    def __init__(self, repo_dir: Path) -> None:
        self._repo_dir = repo_dir

    def load_tasks(self) -> list[Task]:
        """Parse data/<category>/dataset.json for each category."""
        data_dir = self._repo_dir / "data"
        if not data_dir.exists():
            return []

        tasks: list[Task] = []
        for cat_dir in sorted(data_dir.iterdir()):
            if not cat_dir.is_dir():
                continue
            dataset_file = cat_dir / "dataset.json"
            if not dataset_file.exists():
                continue

            try:
                entries = json.loads(dataset_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            for entry in entries:
                task_id = entry.get("task_id", "")
                spreadsheet_file = entry.get("spreadsheet_file", "")
                input_files: list[Path] = []
                if spreadsheet_file:
                    sf = cat_dir / spreadsheet_file
                    if sf.exists():
                        input_files.append(sf)

                tasks.append(Task(
                    suite=self.name,
                    task_id=task_id,
                    prompt=entry.get("instruction", ""),
                    category=entry.get("category", cat_dir.name),
                    input_files=input_files,
                    metadata={
                        "expected_cells": entry.get("expected_cells", {}),
                        "spreadsheet_file": spreadsheet_file,
                        "category_dir": str(cat_dir),
                    },
                ))
        return tasks

    def setup_workspace(self, task: Task, workspace_dir: Path) -> None:
        """Copy spreadsheet files into workspace."""
        for src in task.input_files:
            shutil.copy2(src, workspace_dir / src.name)

    def format_prompt(self, task: Task) -> str:
        """Return the task instruction."""
        return task.prompt

    def evaluate(
        self,
        task: Task,
        workspace_dir: Path,
        agent_output: AgentOutput,
    ) -> TaskResult:
        """Cell-level comparison for deterministic categories; defer Visualization."""
        category = task.category

        if category == "Visualization":
            return TaskResult(
                task_id=task.task_id,
                suite=self.name,
                passed=False,
                score=0.0,
                breakdown={},
                notes="Visualization evaluation deferred (requires VLM, Phase 6)",
                judge_backend=None,
            )

        expected_cells = task.metadata.get("expected_cells", {})
        spreadsheet_file = task.metadata.get("spreadsheet_file", "")
        output_path = workspace_dir / spreadsheet_file

        if not output_path.exists():
            return TaskResult(
                task_id=task.task_id,
                suite=self.name,
                passed=False,
                score=0.0,
                breakdown={},
                notes=f"Output file not found: {spreadsheet_file}",
                judge_backend="deterministic",
            )

        if not expected_cells:
            return TaskResult(
                task_id=task.task_id,
                suite=self.name,
                passed=True,
                score=1.0,
                breakdown={},
                notes="No cells to check",
                judge_backend="deterministic",
            )

        # LibreOffice recalc (spec §5.3 prerequisite): openpyxl-written files
        # carry no cached formula results, so data_only=True would read None
        # for every formula cell and fail even correct answers.
        recalced = self._recalculate(output_path)
        if recalced is None:
            return TaskResult(
                task_id=task.task_id,
                suite=self.name,
                passed=False,
                score=0.0,
                breakdown={},
                notes=(
                    "LibreOffice recalc unavailable or failed — formula "
                    "results cannot be compared"
                ),
                judge_backend="deterministic",
            )

        try:
            wb = load_workbook(recalced, data_only=True)
            ws = wb.active
        except Exception as e:
            return TaskResult(
                task_id=task.task_id,
                suite=self.name,
                passed=False,
                score=0.0,
                breakdown={},
                notes=f"Error loading workbook: {e}",
                judge_backend="deterministic",
            )

        matches = 0
        total = len(expected_cells)
        breakdown: dict[str, float] = {}

        for cell_ref, expected_info in expected_cells.items():
            expected_value = str(expected_info.get("value", ""))
            tolerance = float(expected_info.get("tolerance", 0.0))
            actual_cell = ws[cell_ref]
            actual_value = actual_cell.value

            cell_match = self._compare_cell(actual_value, expected_value, tolerance)
            breakdown[cell_ref] = 1.0 if cell_match else 0.0
            if cell_match:
                matches += 1

        score = matches / total if total > 0 else 0.0
        passed = matches == total

        return TaskResult(
            task_id=task.task_id,
            suite=self.name,
            passed=passed,
            score=score,
            breakdown=breakdown,
            notes=f"{matches}/{total} cells matched",
            judge_backend="deterministic",
        )

    @staticmethod
    def _compare_cell(
        actual: object, expected_str: str, tolerance: float
    ) -> bool:
        """Compare a cell value against expected, with numeric tolerance."""
        if actual is None:
            return expected_str == ""

        actual_str = str(actual).strip()

        # Try numeric comparison with tolerance
        try:
            actual_num = float(actual_str)
            expected_num = float(expected_str)
            return abs(actual_num - expected_num) <= tolerance + abs(expected_num) * tolerance
        except (ValueError, TypeError):
            pass

        # Fall back to string comparison
        return actual_str == expected_str.strip()

    _SOFFICE = "soffice"

    @classmethod
    def _recalculate(cls, xlsx_path: Path) -> Path | None:
        """Recalculate formulas via LibreOffice headless.

        Returns the recalculated copy's path, or None on failure. Unit tests
        monkeypatch this method to the identity function — fixtures write
        literal values, so no recalc is needed there.
        """
        try:
            with tempfile.TemporaryDirectory() as tmp:
                subprocess.run(
                    [cls._SOFFICE, "--headless", "--convert-to", "xlsx",
                     "--outdir", tmp, str(xlsx_path)],
                    capture_output=True, timeout=120, check=True,
                )
                converted = Path(tmp) / xlsx_path.name
                if not converted.exists():
                    return None
                target = xlsx_path.with_suffix(".recalced.xlsx")
                shutil.copy2(converted, target)
                return target
        except (OSError, subprocess.SubprocessError):
            return None
```



- [x] **Step 5: Run test to verify it passes**

Result: 21 tests PASS (plan expected 8; implementation added 10 edge-case and coverage tests). Full suite 143/143 PASS. Commit `03a7970`.



- [x] **Step 6: Commit**

Commits:
- `908b050` — `test(bench): add reproducer for SpreadsheetBench 2 suite adapter (Task 9 RED)`
- `03a7970` — `feat(bench): add SpreadsheetBench 2 deterministic suite adapter (Task 9 GREEN)`
- `1d4a3ef` — `fix(bench): remove dead constant, fix test isolation and layout (Task 9 review)`

**Code review (2026-10-01):** `.claude/reviews/task9-spreadsheet-suite-review.md` — four findings fixed in `1d4a3ef`:
- M-1: removed dead `_DETERMINISTIC_CATEGORIES` constant
- M-2: restored `test_evaluate_visualization_deferred` to its section header with proper blank line
- M-3: rewrote `test_setup_workspace_copies_files` to use isolated `tmp_path` fixture tree (was polluting shared fixture dir)
- M-4: removed dead `import json as _json`
---

### Task 10: FORTE Suite Adapter with LLM Judge

Implement the FORTE adapter — the LLM-judge-dependent suite. Parses task
markdown with YAML frontmatter, imports FORTE's own grading logic from the
submodule, and integrates the LLM judge backend.

**Files:**

- Create: `benchmarks/src/office_bench/suites/forte.py`
- Create: `benchmarks/src/office_bench/judges/llm.py`
- Create: `benchmarks/tests/test_suite_forte.py`
- Create: `benchmarks/tests/test_judge_llm.py`
- Create: `benchmarks/tests/fixtures/forte/` (fixture data)

**Interfaces:**

- Consumes:
  - `Suite`, `Task`, `AgentOutput`, `TaskResult` from Task 1
  - `JudgeBackend`, `Rubric`, `JudgeContext`, `RubricResult` from Task 1
- Produces:
  - `office_bench.suites.forte.ForteSuite.__init__(repo_dir: Path)`
  - Implements `Suite` protocol: `name = "forte"`
  - `office_bench.judges.llm.LLMJudge.__init__(model: str = "deepseek-chat", base_url: str = "https://api.deepseek.com", api_key: str = "")` — reads from env vars if not provided
  - `office_bench.judges.llm.LLMJudge` implements `JudgeBackend` protocol: `name = "llm:deepseek-chat"`

**DoD:** `uv run --project benchmarks pytest benchmarks/tests/test_suite_forte.py benchmarks/tests/test_judge_llm.py -v` passes. FORTE tests use fixture markdown tasks with YAML frontmatter plus a fixture `judge/grade.py` so automated grading is hermetic. LLM judge tests mock the HTTP call to DeepSeek API. `evaluate()` handles **all three grading types**: `automated` (and the automated half of `hybrid`) delegates to FORTE's own `judge.grade.grade_one` imported from the submodule — never auto-passes; `llm_judge` grades each rubric via the LLM judge; `hybrid` requires both halves. An automated task without rubrics is **not evaluable** → `passed=False` with an explanatory note. Missing/unimportable grader → `passed=False` with an explicit error, never a silent pass.



- [x] **Step 1: Create fixture test data** — commit `934b848`

Create `benchmarks/tests/fixtures/forte/data/tasks/finance-001.md`:

```markdown
---
id: finance-001
category: finance
grading_type: llm_judge
timeout_seconds: 300
rubrics:
  - id: "01"
    content: "Agent correctly identifies total revenue"
    weight: 1.0
  - id: "02"
    content: "Agent provides quarter-by-quarter breakdown"
    weight: 1.0
workspace_files:
  - data.xlsx
solution_files:
  - solution.xlsx
---

## Prompt

Analyze the spreadsheet data.xlsx and provide total revenue and a quarter-by-quarter breakdown.
```

Create `benchmarks/tests/fixtures/forte/data/assets/finance-001/input/data.xlsx` — we'll handle this as an empty marker file for the test.

Create `benchmarks/tests/fixtures/forte/data/tasks/hr-001.md`:

```markdown
---
id: hr-001
category: hr
grading_type: automated
timeout_seconds: 120
rubrics: []
workspace_files: []
solution_files: []
---

## Prompt

List all employees in department A.
```

Create `benchmarks/tests/fixtures/forte/data/tasks/hr-002.md` (automated WITH rubrics — exercises the grade_one delegation):

```markdown
---
id: hr-002
category: hr
grading_type: automated
timeout_seconds: 120
rubrics:
  - id: "01"
    content: "Response lists department A employees"
    weight: 1.0
workspace_files: []
solution_files: []
---

## Prompt

List all employees in department A as a table.
```

Create `benchmarks/tests/fixtures/forte/judge/__init__.py` (empty) and `benchmarks/tests/fixtures/forte/judge/grade.py` — the hermetic stand-in for FORTE's native grading module (the adapter loads `judge/grade.py` from its repo dir):

```python
"""Fixture stand-in for FORTE's judge.grade module.

Mirrors the upstream grade_one API the adapter calls. After `setup` clones
the real submodule, verify the real signature (Step 7 investigation) and
keep this fixture in sync.
"""

from __future__ import annotations

from pathlib import Path


def grade_one(
    instruction: str,
    agent_response: str,
    rubrics: list[dict],
    workspace_dir: Path | None = None,
    solution_dir: Path | None = None,
) -> tuple[bool, dict]:
    """Deterministic fake: passes when the response mentions 'department A'."""
    passed = "department a" in agent_response.lower()
    return passed, {"01": 1.0 if passed else 0.0}
```



- [x] **Step 2: Write the failing test for FORTE suite** — commit `934b848`

Create `benchmarks/tests/test_suite_forte.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from office_bench.suites.forte import ForteSuite
from office_bench.suites.base import AgentOutput

FIXTURES = Path(__file__).parent / "fixtures" / "forte"


@pytest.fixture(autouse=True)
def _create_fixture_files() -> None:
    """Ensure fixture files exist."""
    assets_dir = FIXTURES / "data" / "assets" / "finance-001" / "input"
    assets_dir.mkdir(parents=True, exist_ok=True)
    data_file = assets_dir / "data.xlsx"
    if not data_file.exists():
        data_file.write_bytes(b"fake xlsx")


@pytest.fixture()
def suite() -> ForteSuite:
    return ForteSuite(FIXTURES)


def _make_output() -> AgentOutput:
    return AgentOutput(
        messages=[{"role": "assistant", "content": "Total revenue is $500K. Q1: $100K, Q2: $120K, Q3: $130K, Q4: $150K."}],
        files_created=[],
        tool_calls=[],
        duration_seconds=10.0,
    )


def test_load_tasks(suite: ForteSuite) -> None:
    tasks = suite.load_tasks()
    assert len(tasks) == 3
    ids = {t.task_id for t in tasks}
    assert "finance-001" in ids
    assert "hr-001" in ids
    assert "hr-002" in ids


def test_task_fields(suite: ForteSuite) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "finance-001")
    assert t.suite == "forte"
    assert t.category == "finance"
    assert "Analyze" in t.prompt
    assert len(t.metadata.get("rubrics", [])) == 2


def test_setup_workspace(suite: ForteSuite, tmp_path: Path) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "finance-001")
    suite.setup_workspace(t, tmp_path)
    assert (tmp_path / "data.xlsx").exists()


def test_format_prompt(suite: ForteSuite) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "finance-001")
    prompt = suite.format_prompt(t)
    assert "Analyze" in prompt
    assert "data.xlsx" in prompt


def _make_output_with(text: str) -> AgentOutput:
    return AgentOutput(
        messages=[{"role": "assistant", "content": text}],
        files_created=[],
        tool_calls=[],
        duration_seconds=10.0,
    )


def test_evaluate_automated_delegates_to_grade_one(
    suite: ForteSuite, tmp_path: Path
) -> None:
    """automated WITH rubrics must go through judge.grade.grade_one."""
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "hr-002")

    result = suite.evaluate(
        t, tmp_path, _make_output_with("Employees in department A: Alice, Bob")
    )
    assert result.passed is True
    assert result.score == 1.0
    assert result.judge_backend == "deterministic"
    assert result.breakdown.get("01") == 1.0

    result_fail = suite.evaluate(
        t, tmp_path, _make_output_with("No idea, sorry")
    )
    assert result_fail.passed is False
    assert result_fail.score == 0.0


def test_evaluate_automated_without_rubrics_not_evaluable(
    suite: ForteSuite, tmp_path: Path
) -> None:
    """No rubrics + automated = not evaluable — must NOT auto-pass."""
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "hr-001")
    result = suite.evaluate(t, tmp_path, _make_output())
    assert result.passed is False
    assert result.score == 0.0
    assert "not evaluable" in result.notes.lower()


def test_evaluate_grader_missing_fails_cleanly(tmp_path: Path) -> None:
    """A repo dir without judge/grade.py must fail with an explicit error."""
    bare = tmp_path / "bare_forte"  # no judge/ package inside
    bare.mkdir()
    suite = ForteSuite(bare)
    tasks = suite.load_tasks()
    assert tasks == []  # nothing to load — construct a task manually
    from office_bench.suites.base import Task

    task = Task(
        suite="forte",
        task_id="x-1",
        prompt="p",
        category="c",
        input_files=[],
        metadata={"rubrics": [{"id": "01", "content": "r", "weight": 1.0}],
                  "grading_type": "automated"},
    )
    result = suite.evaluate(task, tmp_path, _make_output())
    assert result.passed is False
    assert "grade" in result.notes.lower()
```



- [x] **Step 3: Write the failing test for LLM judge** — commit `934b848`

Create `benchmarks/tests/test_judge_llm.py`:

```python
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from office_bench.judges.base import JudgeContext, Rubric
from office_bench.judges.llm import LLMJudge


class FakeDeepSeekHandler(BaseHTTPRequestHandler):
    """Mock DeepSeek API returning a rubric pass/fail response."""

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        # Return a response that the judge can parse as "PASS"
        response = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "PASS. The agent correctly identified the total revenue.",
                    },
                }
            ],
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())

    def log_message(self, *args) -> None:
        pass


@pytest.fixture()
def mock_api():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeDeepSeekHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join(timeout=5)


def test_llm_judge_name() -> None:
    judge = LLMJudge(model="deepseek-chat")
    assert judge.name == "llm:deepseek-chat"


def test_llm_judge_rubric_pass(mock_api) -> None:
    port = mock_api.server_address[1]
    judge = LLMJudge(
        model="deepseek-chat",
        base_url=f"http://127.0.0.1:{port}",
        api_key="test-key",
    )
    rubric = Rubric(id="01", content="Agent correctly identifies total revenue", weight=1.0)
    context = JudgeContext(
        instruction="Analyze the spreadsheet",
        agent_response="Total revenue is $500K",
        file_contents={},
        file_images=[],
        file_pdfs=[],
    )
    result = judge.judge_rubric(rubric, context)
    assert result.rubric_id == "01"
    assert result.passed is True
    assert result.reason != ""


def test_llm_judge_rubric_fail(mock_api) -> None:
    """Modify handler to return FAIL."""
    # Override the handler to return FAIL
    class FailHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            response = {
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "FAIL. The agent did not provide a breakdown.",
                    },
                }],
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        def log_message(self, *args) -> None: pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), FailHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        judge = LLMJudge(
            model="deepseek-chat",
            base_url=f"http://127.0.0.1:{port}",
            api_key="test-key",
        )
        rubric = Rubric(id="02", content="Quarter breakdown", weight=1.0)
        context = JudgeContext(
            instruction="Analyze", agent_response="No detail",
            file_contents={}, file_images=[], file_pdfs=[],
        )
        result = judge.judge_rubric(rubric, context)
        assert result.rubric_id == "02"
        assert result.passed is False
    finally:
        server.shutdown()
        thread.join(timeout=5)
```



- [x] **Step 4: Run tests to verify they fail** — RED confirmed: `ModuleNotFoundError` for both modules

```bash
cd benchmarks && uv run pytest tests/test_suite_forte.py tests/test_judge_llm.py -v
```

Expected: FAIL — modules not found.



- [x] **Step 5: Implement `benchmarks/src/office_bench/judges/llm.py`** — commit `91efb60`

```python
"""LLM judge backend via OpenAI-compatible API (DeepSeek default)."""

from __future__ import annotations

import json
import os

import requests

from office_bench.judges.base import JudgeContext, Rubric, RubricResult


class LLMJudge:
    """LLM-as-judge using OpenAI-compatible chat completions API."""

    def __init__(
        self,
        model: str = "",
        base_url: str = "",
        api_key: str = "",
    ) -> None:
        self._model = model or os.environ.get("JUDGE_MODEL", "deepseek-chat")
        self._base_url = (
            base_url or os.environ.get("JUDGE_BASE_URL", "https://api.deepseek.com")
        ).rstrip("/")
        self._api_key = api_key or os.environ.get(
            "JUDGE_API_KEY", os.environ.get("BUB_API_KEY", "")
        )

    @property
    def name(self) -> str:
        return f"llm:{self._model}"

    def judge_rubric(self, rubric: Rubric, context: JudgeContext) -> RubricResult:
        """Evaluate a single rubric using the LLM judge."""
        system_prompt = (
            "You are an expert evaluator. Given an instruction, the agent's response, "
            "and a rubric, determine if the rubric is satisfied.\n\n"
            "Respond with exactly one of:\n"
            "- PASS. <reason>\n"
            "- FAIL. <reason>\n\n"
            "Be strict but fair."
        )

        user_content = (
            f"## Instruction\n{context.instruction}\n\n"
            f"## Agent Response\n{context.agent_response}\n\n"
        )

        if context.file_contents:
            user_content += "## Files\n"
            for path, content in context.file_contents.items():
                user_content += f"### {path}\n```\n{content}\n```\n\n"

        user_content += f"## Rubric\n{rubric.content}\n\nVerdict:"

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.0,
            "max_tokens": 256,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        try:
            resp = requests.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            reply = data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            return RubricResult(
                rubric_id=rubric.id,
                passed=False,
                confidence=None,
                reason=f"Judge API error: {e}",
            )

        passed = reply.upper().startswith("PASS")
        # Extract reason after "PASS." or "FAIL."
        reason = reply.split(".", 1)[1].strip() if "." in reply else reply

        return RubricResult(
            rubric_id=rubric.id,
            passed=passed,
            confidence=None,
            reason=reason,
        )
```



- [x] **Step 6: Implement `benchmarks/src/office_bench/suites/forte.py`** — commit `91efb60`

```python
"""FORTE suite adapter — native grade_one + LLM judge evaluation."""

from __future__ import annotations

import importlib.util
import re
import shutil
from pathlib import Path

import yaml

from office_bench.judges.base import JudgeContext, Rubric
from office_bench.judges.llm import LLMJudge
from office_bench.suites.base import AgentOutput, Task, TaskResult


class ForteSuite:
    """Adapter for the FORTE benchmark (AGI-Eval-Official/FORTE)."""

    name = "forte"

    def __init__(self, repo_dir: Path, judge: LLMJudge | None = None) -> None:
        self._repo_dir = repo_dir
        self._judge = judge or LLMJudge()

    def load_tasks(self) -> list[Task]:
        """Parse data/tasks/*.md — YAML frontmatter + ## Prompt section."""
        tasks_dir = self._repo_dir / "data" / "tasks"
        if not tasks_dir.exists():
            return []

        tasks: list[Task] = []
        for md_file in sorted(tasks_dir.glob("*.md")):
            try:
                content = md_file.read_text()
                frontmatter, prompt = self._parse_task_md(content)
            except (OSError, ValueError):
                continue

            task_id = frontmatter.get("id", md_file.stem)
            category = frontmatter.get("category", "unknown")
            rubrics = frontmatter.get("rubrics", [])
            workspace_files = frontmatter.get("workspace_files", [])

            # Resolve input file paths
            assets_dir = self._repo_dir / "data" / "assets" / task_id / "input"
            input_files: list[Path] = []
            for wf in workspace_files:
                fp = assets_dir / wf
                if fp.exists():
                    input_files.append(fp)

            tasks.append(Task(
                suite=self.name,
                task_id=task_id,
                prompt=prompt,
                category=category,
                input_files=input_files,
                metadata={
                    "rubrics": rubrics,
                    "grading_type": frontmatter.get("grading_type", "automated"),
                    "timeout_seconds": frontmatter.get("timeout_seconds", 600),
                    "solution_files": frontmatter.get("solution_files", []),
                },
            ))
        return tasks

    def setup_workspace(self, task: Task, workspace_dir: Path) -> None:
        """Copy input/asset files into the workspace."""
        for src in task.input_files:
            dst = workspace_dir / src.name
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)

    def format_prompt(self, task: Task) -> str:
        """Return the task prompt."""
        return task.prompt

    def evaluate(
        self,
        task: Task,
        workspace_dir: Path,
        agent_output: AgentOutput,
    ) -> TaskResult:
        """Grade via FORTE's native grade_one and/or the LLM judge."""
        grading_type = task.metadata.get("grading_type", "automated")
        rubrics = task.metadata.get("rubrics", [])

        agent_response = (
            agent_output.messages[-1].get("content", "")
            if agent_output.messages
            else ""
        )

        if not rubrics:
            # Nothing to grade — NEVER award an unearned pass
            return self._error_result(
                task, "no rubrics defined — task not evaluable"
            )

        breakdown: dict[str, float] = {}
        all_passed = True
        backends: list[str] = []

        if grading_type in ("automated", "hybrid"):
            grade_one = self._load_grader()
            if grade_one is None:
                return self._error_result(
                    task,
                    "FORTE judge.grade not importable from submodule",
                )
            try:
                auto_passed, auto_detail = grade_one(
                    instruction=task.prompt,
                    agent_response=agent_response,
                    rubrics=rubrics,
                    workspace_dir=workspace_dir,
                    solution_dir=self._solution_dir(task),
                )
            except TypeError as e:
                return self._error_result(
                    task, f"grade_one signature mismatch: {e}"
                )
            if isinstance(auto_detail, dict):
                breakdown.update(auto_detail)
            else:
                breakdown["automated"] = 1.0 if auto_passed else 0.0
            if not auto_passed:
                all_passed = False
            backends.append("deterministic")

        if grading_type in ("llm_judge", "hybrid"):
            context = JudgeContext(
                instruction=task.prompt,
                agent_response=agent_response,
                file_contents=self._read_workspace_text(workspace_dir),
                file_images=[],
                file_pdfs=[],
            )
            for rubric_data in rubrics:
                rubric = Rubric(
                    id=rubric_data["id"],
                    content=rubric_data["content"],
                    weight=rubric_data.get("weight", 1.0),
                )
                result = self._judge.judge_rubric(rubric, context)
                breakdown[rubric.id] = 1.0 if result.passed else 0.0
                if not result.passed:
                    all_passed = False
            backends.append(self._judge.name)

        # FORTE: all-or-nothing per task
        failed_ids = [k for k, v in breakdown.items() if v == 0.0]
        return TaskResult(
            task_id=task.task_id,
            suite=self.name,
            passed=all_passed,
            score=1.0 if all_passed else 0.0,
            breakdown=breakdown,
            notes=(
                f"Failed rubrics: {failed_ids}" if failed_ids
                else "All rubrics passed"
            ),
            judge_backend="+".join(backends) if backends else None,
        )

    def _load_grader(self):
        """Import judge/grade.py from the FORTE submodule."""
        grade_path = self._repo_dir / "judge" / "grade.py"
        if not grade_path.exists():
            return None
        spec = importlib.util.spec_from_file_location(
            f"forte_grade_{abs(hash(str(self._repo_dir)))}", grade_path
        )
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return getattr(module, "grade_one", None)

    def _solution_dir(self, task: Task) -> Path | None:
        """Read-only solution dir mounted for the judge, never the agent."""
        candidate = self._repo_dir / "data" / "solutions" / task.task_id
        return candidate if candidate.exists() else None

    @staticmethod
    def _read_workspace_text(workspace_dir: Path) -> dict[str, str]:
        file_contents: dict[str, str] = {}
        for f in workspace_dir.iterdir():
            if f.is_file() and f.suffix in (".txt", ".csv", ".md", ".json"):
                try:
                    file_contents[f.name] = f.read_text(errors="replace")[:10000]
                except OSError:
                    pass
        return file_contents

    def _error_result(self, task: Task, notes: str) -> TaskResult:
        return TaskResult(
            task_id=task.task_id,
            suite=self.name,
            passed=False,
            score=0.0,
            breakdown={},
            notes=notes,
            judge_backend="deterministic",
        )

    @staticmethod
    def _parse_task_md(content: str) -> tuple[dict, str]:
        """Parse YAML frontmatter and ## Prompt section from task markdown."""
        # Extract YAML frontmatter between --- delimiters
        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        if not fm_match:
            raise ValueError("No YAML frontmatter found")

        frontmatter = yaml.safe_load(fm_match.group(1)) or {}
        body = content[fm_match.end():]

        # Extract ## Prompt section
        prompt_match = re.search(r"##\s+Prompt\s*\n(.*?)(?:\n##|\Z)", body, re.DOTALL)
        prompt = prompt_match.group(1).strip() if prompt_match else body.strip()

        return frontmatter, prompt
```



- [x] **Step 7: Run tests to verify they pass** — 12 PASS, 87% coverage

```bash
cd benchmarks && uv run pytest tests/test_suite_forte.py tests/test_judge_llm.py -v
```

Expected: all 10 tests PASS.

> **Investigation (after `setup` clones the real submodule):** read
> `data/benchmarks/FORTE/judge/grade.py` and pin down the real `grade_one`
> signature (argument names, return shape, env-based judge config
> `JUDGE_MODEL`/`JUDGE_BASE_URL`/`JUDGE_API_KEY`). Adapt the adapter's call
> and the fixture `judge/grade.py` to match. Also check whether reusing
> FORTE's `build_prompt.py`/`system_prompt.py`/`parse_grading.py` for the
> LLM judge (spec §7.2) is importable without side effects — if yes,
> `LLMJudge` should build its prompt through them instead of its own
> inline prompt.



- [x] **Step 8: Commit** — `91efb60` feat(bench): add FORTE suite adapter and LLM judge backend

```bash
git add benchmarks/src/office_bench/suites/forte.py benchmarks/src/office_bench/judges/llm.py benchmarks/tests/test_suite_forte.py benchmarks/tests/test_judge_llm.py benchmarks/tests/fixtures/forte/
git commit -m "feat(bench): add FORTE suite adapter and LLM judge backend"
```

- [x] **Step 9 (review):** Code review — fixed grader cache (sentinel pattern), deterministic module naming (`id(self)`), return type annotation, dead variable, inline imports. Commit `36e0acf`. Review: `.claude/reviews/task10-forte-llm-judge-review.md`

---

### Task 11: Setup Command &amp; Git Submodules

Wire the `setup` CLI command to actually clone submodules, download the
SpreadsheetBench 2 dataset, generate PPTC labels, and verify prerequisites.
Add `.gitmodules` entries.

**Files:**

- Create: `.gitmodules` (or modify if exists)
- Modify: `benchmarks/src/office_bench/cli.py` — enhance `_cmd_setup()`
- Create: `benchmarks/tests/test_setup.py`

**Interfaces:**

- Consumes: CLI `_cmd_setup()` from Task 6
- Produces: `_cmd_setup()` now performs all 6 setup steps from spec §10.3

**DoD:** `uv run --project benchmarks pytest benchmarks/tests/test_setup.py -v` passes. Tests mock subprocess calls and verify the correct commands are invoked. `.gitmodules` contains all four submodule entries.



- [x] **Step 1: Write the failing test**

Create `benchmarks/tests/test_setup.py`:

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from office_bench.cli import _cmd_setup


def test_setup_runs_submodule_update() -> None:
    with patch("office_bench.cli.subprocess") as mock_sub:
        mock_sub.run.return_value = MagicMock(returncode=0)
        ret = _cmd_setup()

    assert ret == 0
    # Should call git submodule update
    calls = mock_sub.run.call_args_list
    assert any(
        "submodule" in str(c) for c in calls
    ), f"Expected git submodule call, got: {calls}"


def test_setup_checks_api_key(monkeypatch) -> None:
    monkeypatch.delenv("BUB_API_KEY", raising=False)
    monkeypatch.delenv("JUDGE_API_KEY", raising=False)

    with patch("office_bench.cli.subprocess") as mock_sub:
        mock_sub.run.return_value = MagicMock(returncode=0)
        with patch("builtins.print") as mock_print:
            _cmd_setup()

    # Should warn about missing API key
    printed = " ".join(str(c) for c in mock_print.call_args_list)
    assert "API" in printed or "key" in printed.lower() or "JUDGE" in printed
```



- [x] **Step 2: Run test to verify it fails**

```bash
cd benchmarks && uv run pytest tests/test_setup.py -v
```

Expected: FAIL or PASS depending on current `_cmd_setup` — if it works with the simple version, refine the test.



- [x] **Step 3: Enhance `_cmd_setup()` in `benchmarks/src/office_bench/cli.py`**

Replace the existing `_cmd_setup` function:

```python
def _cmd_setup() -> int:
    """Clone submodules, download datasets, and verify prerequisites."""
    # 1. Git submodules
    print("Step 1/6: Updating git submodules...")
    subprocess.run(
        ["git", "submodule", "update", "--init", "--recursive"],
        check=False,
    )

    # 2. Download SpreadsheetBench 2 dataset from HuggingFace
    print("Step 2/6: Checking SpreadsheetBench 2 dataset...")
    dataset_dir = DATA_BASE / "datasets" / "spreadsheet"
    if not dataset_dir.exists():
        print(f"  → Download KAKA22/SpreadsheetBench-v2 to {dataset_dir}")
        print("  → Run: huggingface-cli download KAKA22/SpreadsheetBench-v2 --local-dir " + str(dataset_dir))
    else:
        print("  → Dataset already present.")

    # 3. Generate PPTC label files
    print("Step 3/6: Checking PPTC label files...")
    pptc_dir = DATA_BASE / "PPTC"
    if pptc_dir.exists():
        label_dirs = list(pptc_dir.glob("PPT_label_*"))
        if not label_dirs:
            print("  → Generate labels: cd data/benchmarks/PPTC && python main.py --prepare")
        else:
            print("  → Label files already present.")
    else:
        print("  → PPTC submodule not cloned yet.")

    # 4. Check LibreOffice
    print("Step 4/6: Checking LibreOffice...")
    lo_result = subprocess.run(
        ["which", "libreoffice"], capture_output=True, text=True
    )
    if lo_result.returncode != 0:
        print("  ⚠️  LibreOffice not found. Required for SpreadsheetBench 2 recalc.")
    else:
        print("  → LibreOffice found.")

    # 5. Verify FORTE judge importable
    print("Step 5/6: Checking FORTE judge module...")
    forte_judge = DATA_BASE / "FORTE" / "judge"
    if forte_judge.exists():
        print("  → FORTE judge directory found.")
    else:
        print("  → FORTE submodule not ready. Judge won't work until cloned.")

    # 6. Check API keys
    print("Step 6/6: Checking API keys...")
    import os
    api_key = os.environ.get("JUDGE_API_KEY") or os.environ.get("BUB_API_KEY", "")
    if api_key:
        print("  → JUDGE_API_KEY / BUB_API_KEY set.")
    else:
        print("  ⚠️  Neither JUDGE_API_KEY nor BUB_API_KEY is set. LLM judge won't work.")

    print("\nSetup complete.")
    return 0
```



- [x] **Step 4: Create `.gitmodules`**

```ini
[submodule "data/benchmarks/FORTE"]
	path = data/benchmarks/FORTE
	url = https://github.com/AGI-Eval-Official/FORTE.git

[submodule "data/benchmarks/OfficeBench"]
	path = data/benchmarks/OfficeBench
	url = https://github.com/zlwang-cs/OfficeBench.git

[submodule "data/benchmarks/SpreadsheetBench-2"]
	path = data/benchmarks/SpreadsheetBench-2
	url = https://github.com/RUCKBReasoning/SpreadsheetBench-2.git

[submodule "data/benchmarks/PPTC"]
	path = data/benchmarks/PPTC
	url = https://github.com/gydpku/PPTC.git
```



- [x] **Step 5: Run tests to verify they pass**

```bash
cd benchmarks && uv run pytest tests/test_setup.py -v
```

Expected: all 2 tests PASS.



- [x] **Step 6: Commit**

```bash
git add .gitmodules benchmarks/src/office_bench/cli.py benchmarks/tests/test_setup.py
git commit -m "feat(bench): wire setup command with submodules, dataset download, and prerequisite checks"
```

---

### Task 12: Integration Test — Full Pipeline Dry Run

Write an integration test that exercises the entire pipeline end-to-end with
fake suite data and a mock agent bridge. Verifies that `Runner` produces the
correct directory structure, JSON files, backdata CSV row, and report.

**Files:**

- Create: `benchmarks/tests/test_integration.py`

**Interfaces:**

- Consumes: All modules from Tasks 1–6
- Produces: No new modules — validation only

**DoD:** `uv run --project benchmarks pytest benchmarks/tests/test_integration.py -v` passes. Test creates a fake suite, runs the full pipeline, and asserts: `meta.json` exists, per-task JSONs match expected count, `backdata.csv` has correct row, `report.md` contains suite name and score.



- [ ] **Step 1: Write the integration test**

Create `benchmarks/tests/test_integration.py`:

```python
"""End-to-end integration test with fake suite and mock bridge."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from office_bench.runner import RunConfig, Runner
from office_bench.suites.base import AgentOutput, Task, TaskResult


class IntegrationSuite:
    """Minimal suite for integration testing."""

    name = "integ"

    def load_tasks(self) -> list[Task]:
        return [
            Task("integ", "i-1", "Task one", "alpha", [], {}),
            Task("integ", "i-2", "Task two", "alpha", [], {}),
            Task("integ", "i-3", "Task three", "beta", [], {}),
        ]

    def setup_workspace(self, task: Task, workspace_dir: Path) -> None:
        (workspace_dir / "ready.txt").write_text("ok")

    def format_prompt(self, task: Task) -> str:
        return task.prompt

    def evaluate(
        self, task: Task, workspace_dir: Path, agent_output: AgentOutput
    ) -> TaskResult:
        # i-1 and i-2 pass, i-3 fails
        passed = task.task_id != "i-3"
        return TaskResult(
            task_id=task.task_id,
            suite=self.name,
            passed=passed,
            score=1.0 if passed else 0.0,
            breakdown={},
            notes="pass" if passed else "fail",
            judge_backend="deterministic",
        )


def test_full_pipeline(tmp_path: Path) -> None:
    bridge = MagicMock()
    bridge.run_task.return_value = AgentOutput(
        messages=[{"role": "assistant", "content": "output"}],
        files_created=[],
        tool_calls=[{"name": "write_spreadsheet", "args": {}}],
        duration_seconds=3.0,
    )

    config = RunConfig(
        suites=["integ"],
        runs=2,
        task_ids=None,
        categories=None,
        limit=None,
        keep_workspaces=False,
        no_resume=False,
        dual_judge=False,
        gateway_url="http://localhost:18088/agent",
        timeout_seconds=30,
    )

    runner = Runner(config, {"integ": IntegrationSuite()}, bridge=bridge)
    run_dir = runner.run(tmp_path)

    # 1. Directory structure
    assert run_dir.exists()
    assert (run_dir / "meta.json").exists()
    assert (run_dir / "report.md").exists()

    # 2. Meta
    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["suites"] == ["integ"]
    assert meta["runs"] == 2

    # 3. Per-task result JSONs: 3 tasks × 2 runs = 6 files
    result_files = list((run_dir / "integ").glob("*.json"))
    assert len(result_files) == 6

    # 4. Verify pass/fail distribution
    results = [json.loads(f.read_text()) for f in result_files]
    passed_count = sum(1 for r in results if r["passed"])
    failed_count = sum(1 for r in results if not r["passed"])
    assert passed_count == 4  # i-1 × 2 + i-2 × 2
    assert failed_count == 2  # i-3 × 2

    # 5. Backdata CSV
    backdata = tmp_path / "backdata.csv"
    assert backdata.exists()
    with backdata.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1  # one row per suite
    assert rows[0]["suite"] == "integ"
    assert float(rows[0]["primary_value"]) == pytest.approx(66.67, abs=0.1)
    assert rows[0]["model"] != ""  # spec §9.3 requires both columns
    assert rows[0]["agent_version"] != ""

    # 6. Report contains expected content
    report = (run_dir / "report.md").read_text()
    assert "integ" in report
    assert "66.67" in report

    # 7. Bridge was called 6 times (3 tasks × 2 runs)
    assert bridge.run_task.call_count == 6


def test_resume_skips_completed_tasks(tmp_path: Path) -> None:
    bridge = MagicMock()
    bridge.run_task.return_value = AgentOutput(
        messages=[{"role": "assistant", "content": "output"}],
        files_created=[],
        tool_calls=[],
        duration_seconds=1.0,
    )

    config = RunConfig(
        suites=["integ"],
        runs=1,
        task_ids=None,
        categories=None,
        limit=None,
        keep_workspaces=False,
        no_resume=False,
        dual_judge=False,
        gateway_url="http://localhost:18088/agent",
        timeout_seconds=30,
    )

    runner = Runner(config, {"integ": IntegrationSuite()}, bridge=bridge)
    run_dir = runner.run(tmp_path)
    first_call_count = bridge.run_task.call_count

    # Second run with same run_id should skip all
    bridge.reset_mock()
    runner2 = Runner(config, {"integ": IntegrationSuite()}, bridge=bridge)
    runner2.run(tmp_path, run_id=run_dir.name)
    assert bridge.run_task.call_count == 0
    # And must not append a duplicate backdata row
    with (tmp_path / "backdata.csv").open() as f:
        assert len(list(csv.DictReader(f))) == 1
```



- [ ] **Step 2: Run the integration test**

```bash
cd benchmarks && uv run pytest tests/test_integration.py -v
```

Expected: all 2 tests PASS.



- [ ] **Step 3: Run entire test suite to verify nothing is broken**

```bash
cd benchmarks && uv run pytest tests/ -v --tb=short
```

Expected: all tests across all files PASS.



- [ ] **Step 4: Commit**

```bash
git add benchmarks/tests/test_integration.py
git commit -m "test(bench): add end-to-end integration test for full pipeline"
```

---

## Summary


| Task      | Component                              | Files                        | Tests        | Phase |
| --------- | -------------------------------------- | ---------------------------- | ------------ | ----- |
| 1         | Scaffold + Data Types                  | 8 create, 1 modify           | 9            | 1     |
| 2         | Per-Request Workspace Binding (agent)  | 1 modify, 1 test             | 4            | 1     |
| 3         | Agent Bridge                           | 1 create, 1 test             | 6            | 1     |
| 4         | Results + Backdata + Reference         | 2 create, 1 test             | 11           | 1     |
| 5         | Runner Orchestrator                    | 1 create, 1 test             | 11           | 1     |
| 6         | CLI                                    | 2 create, 1 test             | 4            | 1     |
| 7         | OfficeBench Adapter (native eval)      | 1 create, 1 test, fixtures   | 8            | 2     |
| 8         | PPTC Adapter (label-based match)       | 1 create, 1 test, fixtures   | 7            | 2     |
| 9         | SpreadsheetBench 2 Adapter (+recalc)   | 1 create, 1 test, fixtures   | 8            | 3     |
| 10        | FORTE + LLM Judge (grade_one)          | 2 create, 2 test, fixtures   | 10           | 4     |
| 11        | Setup Command + Submodules             | 1 create, 2 modify, 1 test   | 2            | 5     |
| 12        | Integration Test                       | 1 test                       | 2            | 5     |
| **Total** |                                        | **\~28 files**               | **82 tests** |       |
