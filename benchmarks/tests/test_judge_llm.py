"""Tests for the LLM judge backend."""

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
