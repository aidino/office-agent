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
        timeout_seconds: float = 600,
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
        # Wall-clock deadline for the whole call. requests' timeout only
        # bounds each individual socket read, so a slow-drip stream would
        # otherwise run forever; the per-line check below enforces the cap.
        deadline = start + self._timeout_seconds
        resp: requests.Response | None = None
        try:
            resp = requests.post(
                self._gateway_url,
                json=payload,
                headers={"Accept": "text/event-stream"},
                stream=True,
                timeout=self._timeout_seconds,
            )
            resp.raise_for_status()
            collected_messages, tool_calls = self._consume_stream(
                resp, deadline, self._timeout_seconds
            )
        except requests.RequestException as exc:
            collected_messages = [{
                "role": "assistant",
                "content": f"[ERROR] gateway request failed: {exc}",
            }]
            tool_calls = []
        finally:
            if resp is not None:
                resp.close()

        return {
            "messages": collected_messages,
            "tool_calls": tool_calls,
            "duration": time.monotonic() - start,
        }

    @staticmethod
    def _consume_stream(
        resp: requests.Response,
        deadline: float | None = None,
        timeout_seconds: float = 0,
    ) -> tuple[list[dict], list[dict]]:
        """Consume the SSE stream until RUN_FINISHED, RUN_ERROR, or deadline.

        The gateway emits ``data: {"type": ...}`` frames only — there are no
        ``event:`` lines (ag_ui EventEncoder). Wire keys are camelCase:
        ``messageId``, ``toolCallId``, ``toolCallName``, ``delta``; a
        RUN_ERROR carries its reason in ``message``. Text is accumulated per
        messageId so a multi-message run keeps one assistant message per
        tool round, and the error message is always appended last. Tool
        calls still in flight when the stream ends are flushed with
        best-effort args rather than dropped.
        """
        messages: list[dict] = []
        tool_calls: list[dict] = []
        active_tools: dict[str, dict] = {}
        texts: dict[str, list[str]] = {}
        order: list[str] = []
        error_message: str | None = None

        try:
            for line in resp.iter_lines(decode_unicode=True):
                if deadline is not None and time.monotonic() > deadline:
                    error_message = (
                        f"stream exceeded wall-clock timeout ({timeout_seconds}s)"
                    )
                    break
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
                        tool_calls.append({
                            "name": tc["name"],
                            "args": AgentBridge._parse_tool_args(tc["args"]),
                        })
                elif event == "RUN_FINISHED":
                    break
                elif event == "RUN_ERROR":
                    error_message = (
                        data.get("message") or data.get("error") or "Unknown error"
                    )
                    break
        finally:
            resp.close()

        # Stream ended (RUN_ERROR, deadline, or EOF) with tool calls still
        # in flight — record them rather than losing them silently.
        for tc in active_tools.values():
            tool_calls.append({
                "name": tc["name"],
                "args": AgentBridge._parse_tool_args(tc["args"]),
            })

        for mid in order:
            messages.append({"role": "assistant", "content": "".join(texts[mid])})
        if error_message is not None:
            messages.append(
                {"role": "assistant", "content": f"[ERROR] {error_message}"}
            )
        return messages, tool_calls

    @staticmethod
    def _parse_tool_args(raw: str) -> dict:
        """Parse accumulated tool-call args, keeping unparseable text verbatim."""
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return {"raw": raw}

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
