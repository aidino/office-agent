from __future__ import annotations

import csv
import json
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


def test_runner_skips_unknown_suite_name(tmp_path: Path) -> None:
    """A config naming an unregistered suite must not crash the run."""
    bridge = _make_mock_bridge()
    config = _default_config(suites=["fakesuite", "not-registered"])
    runner = Runner(config, {"fakesuite": FakeSuite()}, bridge=bridge)
    run_dir = runner.run(tmp_path)

    # Registered suite ran completely; unknown name skipped without error
    assert len(list((run_dir / "fakesuite").glob("*.json"))) == 5
    assert (run_dir / "report.md").exists()


# ---------------------------------------------------------------------------
# Review-fix reproducers (.claude/reviews/task5-runner-orchestrator-review.md)
# ---------------------------------------------------------------------------


def _read_backdata_rows(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


class ExplodingSuite(FakeSuite):
    """evaluate() raises on t2 — models a broken suite fixture/evaluator."""

    def evaluate(
        self, task: Task, workspace_dir: Path, agent_output: AgentOutput
    ) -> TaskResult:
        if task.task_id == "t2":
            raise RuntimeError("boom: evaluator exploded")
        return super().evaluate(task, workspace_dir, agent_output)


def test_runner_unknown_suite_never_pollutes_backdata(
    tmp_path: Path, capsys
) -> None:
    """M-A: a typo'd suite name must not append a permanent n/a CSV row."""
    bridge = _make_mock_bridge()
    config = _default_config(suites=["fakesuite", "not-registered"])
    run_dir = Runner(
        config, {"fakesuite": FakeSuite()}, bridge=bridge
    ).run(tmp_path)

    backdata = tmp_path / "backdata.csv"
    rows = _read_backdata_rows(backdata)
    assert len(rows) == 1  # exactly one row — no junk row for the typo
    assert rows[0]["suite"] == "fakesuite"
    assert rows[0]["primary_value"] == "100.0"

    # The operator gets a signal instead of silence
    assert "not-registered" in capsys.readouterr().err
    assert "not-registered" not in (run_dir / "report.md").read_text()


def test_runner_aggregates_by_suite_name_not_registry_key(
    tmp_path: Path,
) -> None:
    """M-A trigger 2: results are persisted under suite.name, so aggregation
    and the backdata row must key on suite.name, not the registry key."""
    bridge = _make_mock_bridge()
    config = _default_config(suites=["fs"])
    Runner(config, {"fs": FakeSuite()}, bridge=bridge).run(tmp_path)

    rows = _read_backdata_rows(tmp_path / "backdata.csv")
    assert len(rows) == 1
    assert rows[0]["suite"] == "fakesuite"  # suite.name, not the "fs" key
    assert rows[0]["primary_value"] == "100.0"
    assert rows[0]["tasks_run"] == "5"


def test_runner_resume_reruns_truncated_result(tmp_path: Path) -> None:
    """M-1: a crash-truncated result file is not "completed" — the task
    re-runs and the aggregate never silently loses it."""
    run_dir = tmp_path / "R"
    (run_dir / "fakesuite").mkdir(parents=True)
    (run_dir / "fakesuite" / "t0_run1.json").write_text('{"task_id": "t0", "sui')

    bridge = _make_mock_bridge()
    config = _default_config()
    Runner(config, {"fakesuite": FakeSuite()}, bridge=bridge).run(
        tmp_path, run_id="R"
    )

    # t0 re-ran (file existence alone must not count as completed)
    assert bridge.run_task.call_count == 5
    # The truncated file was replaced by a valid result
    data = json.loads((run_dir / "fakesuite" / "t0_run1.json").read_text())
    assert data["task_id"] == "t0"
    assert data["passed"] is True
    # The aggregate reflects all 5 tasks, not the 4 survivors
    rows = _read_backdata_rows(tmp_path / "backdata.csv")
    assert rows[0]["tasks_run"] == "5"


def test_runner_task_exception_is_isolated_and_persisted(
    tmp_path: Path, capsys
) -> None:
    """M-2: one crashing task must not abort the run — it is recorded as a
    failed result so the aggregate reflects the gap instead of hiding it."""
    bridge = _make_mock_bridge()
    config = _default_config()
    run_dir = Runner(
        config, {"fakesuite": ExplodingSuite()}, bridge=bridge
    ).run(tmp_path)

    # The run completed: report + backdata exist
    assert (run_dir / "report.md").exists()
    rows = _read_backdata_rows(tmp_path / "backdata.csv")
    assert len(rows) == 1

    # The crashed task is persisted as failed with an explicit note
    t2 = json.loads((run_dir / "fakesuite" / "t2_run1.json").read_text())
    assert t2["passed"] is False
    assert t2["judge_backend"] is None
    assert "boom" in t2["notes"]

    # The other four passed; the aggregate counts all 5 (4/5 = 80.0)
    assert rows[0]["tasks_run"] == "5"
    assert rows[0]["primary_value"] == "80.0"
    assert "t2" in capsys.readouterr().err


def test_runner_workspace_cleanup_on_task_exception(
    tmp_path: Path, monkeypatch
) -> None:
    """M-2/L-3b: workspaces are removed even when the task crashes."""
    created: list[Path] = []

    def _fake_mkdtemp(prefix: str = "") -> str:
        d = tmp_path / f"{prefix}ws{len(created)}"
        d.mkdir()
        created.append(d)
        return str(d)

    monkeypatch.setattr(tempfile, "mkdtemp", _fake_mkdtemp)

    config = _default_config(keep_workspaces=False)
    run_dir = Runner(
        config, {"fakesuite": ExplodingSuite()}, bridge=_make_mock_bridge()
    ).run(tmp_path / "out")

    assert (run_dir / "report.md").exists()  # run completed despite crash
    assert len(created) == 5
    assert not any(p.exists() for p in created)  # every workspace cleaned


def test_runner_resume_preserves_meta_provenance(tmp_path: Path) -> None:
    """M-3: resume keeps the first run's timestamp/commit in meta.json
    (matching the frozen backdata row) and records the resume separately."""
    bridge = _make_mock_bridge()
    config = _default_config(limit=1)
    run_dir = Runner(
        config, {"fakesuite": FakeSuite()}, bridge=bridge
    ).run(tmp_path)
    first_meta = json.loads((run_dir / "meta.json").read_text())

    Runner(config, {"fakesuite": FakeSuite()}, bridge=bridge).run(
        tmp_path, run_id=run_dir.name
    )
    resumed_meta = json.loads((run_dir / "meta.json").read_text())

    assert resumed_meta["timestamp"] == first_meta["timestamp"]
    assert resumed_meta["git_commit"] == first_meta["git_commit"]
    assert "resumed_at" in resumed_meta

    # The CSV row keeps the original timestamp (append-only history)
    rows = _read_backdata_rows(tmp_path / "backdata.csv")
    assert len(rows) == 1
    assert rows[0]["timestamp"] == first_meta["timestamp"]


def test_runner_resume_replaces_corrupt_meta(tmp_path: Path) -> None:
    """A truncated meta.json is replaced by fresh meta on resume."""
    run_dir = tmp_path / "R"
    run_dir.mkdir()
    (run_dir / "meta.json").write_text('{"run_id": "R", "sui')

    config = _default_config(limit=1)
    Runner(
        config, {"fakesuite": FakeSuite()}, bridge=_make_mock_bridge()
    ).run(tmp_path, run_id="R")

    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["run_id"] == "R"


def test_runner_partial_resume_completes_remainder(tmp_path: Path) -> None:
    """L-3a: crash mid-suite before any backdata row — resume runs only the
    missing tasks and the final row covers the full suite."""
    from office_bench.results import save_task_result

    seed_dir = tmp_path / "R"
    (seed_dir / "fakesuite").mkdir(parents=True)
    for tid in ("t0", "t1"):
        save_task_result(
            seed_dir,
            TaskResult(
                task_id=tid,
                suite="fakesuite",
                passed=True,
                score=1.0,
                breakdown={},
                notes="",
                judge_backend="deterministic",
            ),
            run_number=1,
            agent_output=AgentOutput(
                messages=[], files_created=[], tool_calls=[], duration_seconds=1.0
            ),
        )

    bridge = _make_mock_bridge()
    config = _default_config()  # all 5 tasks
    run_dir = Runner(
        config, {"fakesuite": FakeSuite()}, bridge=bridge
    ).run(tmp_path, run_id="R")

    assert bridge.run_task.call_count == 3  # only the missing three re-ran
    assert len(list((run_dir / "fakesuite").glob("*.json"))) == 5
    rows = _read_backdata_rows(tmp_path / "backdata.csv")
    assert len(rows) == 1
    assert rows[0]["tasks_run"] == "5"


def test_runner_result_json_content(tmp_path: Path) -> None:
    """L-3d: pin the persisted result JSON schema, not just file counts."""
    bridge = _make_mock_bridge()
    config = _default_config(limit=1)
    run_dir = Runner(
        config, {"fakesuite": FakeSuite()}, bridge=bridge
    ).run(tmp_path)

    data = json.loads((run_dir / "fakesuite" / "t0_run1.json").read_text())
    assert data["task_id"] == "t0"
    assert data["suite"] == "fakesuite"
    assert data["run"] == 1
    assert data["passed"] is True
    assert data["score"] == 1.0
    assert data["judge_backend"] == "deterministic"
    assert data["duration_seconds"] == 2.0
    assert "timestamp" in data
    assert data["agent_output"]["response_text"] == "done"


def test_runner_no_resume_reruns_everything(tmp_path: Path) -> None:
    """no_resume=True re-runs tasks but never duplicates persisted rows."""
    suite = FakeSuite()
    bridge = _make_mock_bridge()
    config = _default_config(limit=2, no_resume=True)
    runner = Runner(config, {"fakesuite": suite}, bridge=bridge)
    run_dir = runner.run(tmp_path)

    bridge.reset_mock()
    runner.run(tmp_path, run_id=run_dir.name)

    # Tasks re-ran despite existing result files…
    assert bridge.run_task.call_count == 2
    # …but result JSONs were not overwritten/duplicated (skip-on-exists)
    assert len(list((run_dir / "fakesuite").glob("*.json"))) == 2
    # …and the append-only CSV gained no second (run_id, suite) row
    lines = (tmp_path / "backdata.csv").read_text().strip().split("\n")
    assert len(lines) == 2


def test_runner_meta_survives_git_failure(tmp_path: Path, monkeypatch) -> None:
    """git unavailable → git_commit falls back to '' and the run completes."""

    def _raise(*a, **kw):
        raise OSError("git not installed")

    # runner.py does `import subprocess`, so this is the reference it uses
    monkeypatch.setattr("office_bench.runner.subprocess.run", _raise)

    config = _default_config(limit=1)
    run_dir = Runner(
        config, {"fakesuite": FakeSuite()}, bridge=_make_mock_bridge()
    ).run(tmp_path)

    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["git_commit"] == ""
    assert meta["model"] != ""  # the rest of meta is still populated


def test_runner_meta_survives_version_read_failure(
    tmp_path: Path, monkeypatch
) -> None:
    """Unreadable office_agent pyproject → agent_version '' and run completes."""
    import tomllib as _tomllib

    def _raise(f):
        raise _tomllib.TOMLDecodeError("truncated", "pyproject.toml", 0)

    monkeypatch.setattr("office_bench.runner.tomllib.load", _raise)

    config = _default_config(limit=1)
    run_dir = Runner(
        config, {"fakesuite": FakeSuite()}, bridge=_make_mock_bridge()
    ).run(tmp_path)

    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["agent_version"] == ""
