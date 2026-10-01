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


def _make_config(
    *, suites: list[str] = ("integ",), runs: int = 2  # noqa: C408
) -> RunConfig:
    return RunConfig(
        suites=list(suites),
        runs=runs,
        task_ids=None,
        categories=None,
        limit=None,
        keep_workspaces=False,
        no_resume=False,
        dual_judge=False,
        gateway_url="http://localhost:18088/agent",
        timeout_seconds=30,
    )


def _make_bridge() -> MagicMock:
    bridge = MagicMock()
    bridge.run_task.return_value = AgentOutput(
        messages=[{"role": "assistant", "content": "output"}],
        files_created=[],
        tool_calls=[{"name": "write_spreadsheet", "args": {}}],
        duration_seconds=3.0,
    )
    return bridge


def test_full_pipeline(tmp_path: Path) -> None:
    bridge = _make_bridge()
    config = _make_config(runs=2)
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
    bridge = _make_bridge()
    config = _make_config(runs=1)

    runner = Runner(config, {"integ": IntegrationSuite()}, bridge=bridge)
    run_dir = runner.run(tmp_path)
    first_call_count = bridge.run_task.call_count

    assert first_call_count == 3  # 3 tasks × 1 run

    # Second run with same run_id should skip all
    bridge.reset_mock()
    runner2 = Runner(config, {"integ": IntegrationSuite()}, bridge=bridge)
    runner2.run(tmp_path, run_id=run_dir.name)
    assert bridge.run_task.call_count == 0

    # And must not append a duplicate backdata row
    with (tmp_path / "backdata.csv").open() as f:
        assert len(list(csv.DictReader(f))) == 1
