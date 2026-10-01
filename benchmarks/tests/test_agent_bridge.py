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


def test_run_task_skips_malformed_sse_frames(sse_server, tmp_path: Path) -> None:
    """A corrupt data: frame must be skipped, not crash the run."""
    SSEHandler.sse_body = (
        'data: {"type":"RUN_STARTED","threadId":"t1","runId":"r9"}\n\n'
        "data: {not valid json\n\n"
        'data: {"type":"TEXT_MESSAGE_START","messageId":"a1","role":"assistant"}\n\n'
        'data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"a1","delta":"Still alive"}\n\n'
        'data: {"type":"TEXT_MESSAGE_END","messageId":"a1"}\n\n'
        'data: {"type":"RUN_FINISHED","threadId":"t1","runId":"r9"}\n\n'
    )
    port = sse_server.server_address[1]
    bridge = AgentBridge(
        gateway_url=f"http://127.0.0.1:{port}/agent",
        timeout_seconds=30,
    )
    output = bridge.run_task("Garbage frame", tmp_path)
    assert output.messages == [{"role": "assistant", "content": "Still alive"}]


def test_run_task_tool_call_args_unparseable_kept_raw(
    sse_server, tmp_path: Path
) -> None:
    """Tool-call args that are not valid JSON are kept verbatim, not dropped."""
    run_id = uuid.uuid4().hex[:8]
    SSEHandler.sse_body = "".join([
        _sse_line("RUN_STARTED", {"threadId": "t1", "runId": run_id}),
        _sse_line(
            "TOOL_CALL_START",
            {"toolCallId": "tc9", "toolCallName": "write_spreadsheet"},
        ),
        _sse_line(
            "TOOL_CALL_ARGS", {"toolCallId": "tc9", "delta": "{not json}"},
        ),
        _sse_line("TOOL_CALL_END", {"toolCallId": "tc9"}),
        _sse_line("RUN_FINISHED", {"threadId": "t1", "runId": run_id}),
    ])
    port = sse_server.server_address[1]
    bridge = AgentBridge(
        gateway_url=f"http://127.0.0.1:{port}/agent",
        timeout_seconds=30,
    )
    output = bridge.run_task("Raw args", tmp_path)
    assert output.tool_calls == [
        {"name": "write_spreadsheet", "args": {"raw": "{not json}"}}
    ]


def test_run_task_workspace_missing_yields_no_files(
    sse_server, tmp_path: Path
) -> None:
    """A workspace dir that never existed snapshots as empty, not an error."""
    port = sse_server.server_address[1]
    bridge = AgentBridge(
        gateway_url=f"http://127.0.0.1:{port}/agent",
        timeout_seconds=30,
    )
    output = bridge.run_task("Hi", tmp_path / "does-not-exist")
    assert output.files_created == []
    assert len(output.messages) == 1


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
