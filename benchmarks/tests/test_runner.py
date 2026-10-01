from __future__ import annotations

import csv
import tempfile
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
    assert call_count_1 == 2  # limit=2 → both tasks actually ran the first time

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


def test_runner_workspace_cleanup(tmp_path: Path, monkeypatch) -> None:
    """Workspaces are removed after each task unless keep_workspaces.

    The plan's version ended with ``assert True`` (cleanup happens in the
    system tempdir, "not observable here"). Redirect mkdtemp into tmp_path
    so the guarantee is actually testable.
    """
    created: list[Path] = []

    def _fake_mkdtemp(prefix: str = "") -> str:
        d = tmp_path / f"{prefix}ws{len(created)}"
        d.mkdir()
        created.append(d)
        return str(d)

    monkeypatch.setattr(tempfile, "mkdtemp", _fake_mkdtemp)

    # Default: workspace removed after the task completes
    suite = FakeSuite()
    bridge = _make_mock_bridge()
    config = _default_config(limit=1, keep_workspaces=False)
    Runner(config, {"fakesuite": suite}, bridge=bridge).run(tmp_path / "out1")
    assert len(created) == 1
    assert not created[0].exists()

    # keep_workspaces=True: workspace survives for inspection
    config_keep = _default_config(limit=1, keep_workspaces=True)
    Runner(config_keep, {"fakesuite": FakeSuite()}, bridge=_make_mock_bridge()).run(
        tmp_path / "out2"
    )
    assert created[-1].exists()
    assert (created[-1] / "input.txt").exists()  # setup ran inside it
