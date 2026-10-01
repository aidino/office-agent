from __future__ import annotations

import builtins
import csv
import importlib
import json
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from office_bench.cli import main
from office_bench.runner import RunConfig
from office_bench.suites.base import AgentOutput, Task, TaskResult


class FakeSuite:
    """Minimal suite for `list` and the end-to-end `run` test."""

    name = "fakesuite"

    def load_tasks(self) -> list[Task]:
        return [
            Task("fakesuite", "t1", "p1", "cat-a", [], {}),
            Task("fakesuite", "t2", "p2", "cat-b", [], {}),
        ]

    def setup_workspace(self, task: Task, workspace_dir: Path) -> None:
        pass

    def format_prompt(self, t: Task) -> str:
        return t.prompt

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


def _write_backdata(csv_path: Path, rows: list[list]) -> None:
    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["run_id", "timestamp", "git_commit", "agent_version",
                         "model", "suite", "tasks_total", "tasks_run",
                         "primary_metric", "primary_value", "secondary_metrics"])
        for row in rows:
            writer.writerow(row)


def _write_result(run_id: str, suite: str, score: float, base: Path) -> None:
    run_dir = base / run_id / suite
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "t1_run1.json").write_text(json.dumps({
        "task_id": "t1", "suite": suite, "run": 1,
        "passed": True, "score": score,
        "breakdown": {}, "notes": "", "judge_backend": None,
    }))


# --- top-level / entry point ---


def test_help_returns_zero() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0


def test_no_command_prints_help(capsys) -> None:
    ret = main([])
    assert ret == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_python_m_entry_point_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "office_bench", "--help"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0
    assert "office_bench" in result.stdout


# --- list ---


def test_list_command(capsys, tmp_path: Path) -> None:
    with patch(
        "office_bench.cli._build_suite_registry",
        return_value={"fakesuite": FakeSuite()},
    ):
        ret = main(["list", "--suite", "fakesuite"])

    assert ret == 0
    captured = capsys.readouterr().out
    assert "t1" in captured
    assert "t2" in captured
    assert "cat-a" in captured


def test_list_unknown_suite_fails(capsys) -> None:
    with patch("office_bench.cli._build_suite_registry", return_value={}):
        ret = main(["list", "--suite", "nope"])
    assert ret == 1
    assert "unknown suite" in capsys.readouterr().err.lower()


# --- run ---


def test_run_invokes_runner(tmp_path: Path) -> None:
    with (
        patch("office_bench.cli._build_suite_registry") as mock_reg,
        patch("office_bench.cli.Runner") as mock_runner_cls,
        patch("office_bench.cli.RESULTS_BASE", tmp_path),
    ):
        fake = FakeSuite()
        mock_reg.return_value = {"fakesuite": fake}
        ret = main(["run", "--suite", "fakesuite", "--limit", "2"])

    assert ret == 0
    config = mock_runner_cls.call_args[0][0]
    assert isinstance(config, RunConfig)
    assert config.suites == ["fakesuite"]
    assert config.limit == 2
    assert config.runs == 1
    assert config.no_resume is False
    assert mock_runner_cls.call_args[0][1] == {"fakesuite": fake}
    mock_runner_cls.return_value.run.assert_called_once_with(tmp_path, run_id=None)


def test_run_suite_all_comma_split_and_run_id(tmp_path: Path) -> None:
    """--suite all expands to registry keys; comma flags split; --run-id
    reaches Runner.run (Task 5 review: resume must be reachable from CLI)."""
    with (
        patch("office_bench.cli._build_suite_registry") as mock_reg,
        patch("office_bench.cli.Runner") as mock_runner_cls,
        patch("office_bench.cli.RESULTS_BASE", tmp_path),
    ):
        suite_a, suite_b = FakeSuite(), FakeSuite()
        suite_a.name = "suite-a"  # type: ignore[misc]
        suite_b.name = "suite-b"  # type: ignore[misc]
        mock_reg.return_value = {"suite-a": suite_a, "suite-b": suite_b}
        ret = main([
            "run", "--suite", "all",
            "--task-id", "t1,t2",
            "--category", "cat-a,cat-b",
            "--runs", "3",
            "--no-resume",
            "--run-id", "my-run",
        ])

    assert ret == 0
    config = mock_runner_cls.call_args[0][0]
    assert config.suites == ["suite-a", "suite-b"]
    assert config.task_ids == ["t1", "t2"]
    assert config.categories == ["cat-a", "cat-b"]
    assert config.runs == 3
    assert config.no_resume is True
    mock_runner_cls.return_value.run.assert_called_once_with(
        tmp_path, run_id="my-run"
    )


def test_run_help_documents_resume_flags(capsys) -> None:
    """--run-id exists and --no-resume semantics are documented (Task 5 review)."""
    with pytest.raises(SystemExit) as exc_info:
        main(["run", "--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out.lower()
    assert "--run-id" in out
    assert "--no-resume" in out
    assert "re-run" in out


# --- setup ---


def test_setup_invokes_submodule_update() -> None:
    with patch("office_bench.cli.subprocess") as mock_sub:
        mock_sub.run.return_value = MagicMock(returncode=0)
        ret = main(["setup"])
    assert ret == 0
    calls = mock_sub.run.call_args_list
    assert any("submodule" in str(c) for c in calls), f"got: {calls}"


# --- report ---


def test_report_regenerates_from_existing_results(capsys, tmp_path: Path) -> None:
    _write_result("run1", "forte", 1.0, tmp_path)
    with patch("office_bench.cli.RESULTS_BASE", tmp_path):
        ret = main(["report", "--run-id", "run1"])

    assert ret == 0
    report = tmp_path / "run1" / "report.md"
    assert report.exists()
    content = report.read_text()
    assert "forte" in content.lower()
    assert "100.0" in content


def test_report_missing_run_fails(capsys, tmp_path: Path) -> None:
    with patch("office_bench.cli.RESULTS_BASE", tmp_path):
        ret = main(["report", "--run-id", "nope"])
    assert ret == 1
    assert "not found" in capsys.readouterr().err.lower()


# --- trend ---


def test_trend_command_reads_csv(capsys, tmp_path: Path) -> None:
    _write_backdata(tmp_path / "backdata.csv", [
        ["run1", "2026-10-01T00:00:00Z", "abc", "0.1.0",
         "deepseek", "forte", 10, 10, "avg_at_3", 45.0, "{}"],
        ["run2", "2026-10-02T00:00:00Z", "def", "0.1.0",
         "deepseek", "forte", 10, 10, "avg_at_3", 48.0, "{}"],
    ])

    with patch("office_bench.cli.RESULTS_BASE", tmp_path):
        ret = main(["trend"])

    assert ret == 0
    captured = capsys.readouterr().out
    assert "run1" in captured
    assert "45.0" in captured


def test_trend_filters_by_suite(capsys, tmp_path: Path) -> None:
    _write_backdata(tmp_path / "backdata.csv", [
        ["run1", "t", "c", "v", "m", "forte", 10, 10, "avg_at_3", 45.0, "{}"],
        ["run2", "t", "c", "v", "m", "pptc", 10, 10, "session_acc", 50.0, "{}"],
    ])

    with patch("office_bench.cli.RESULTS_BASE", tmp_path):
        ret = main(["trend", "--suite", "forte"])

    assert ret == 0
    captured = capsys.readouterr().out
    assert "run1" in captured
    assert "forte" in captured
    assert "pptc" not in captured


def test_trend_no_matching_rows(capsys, tmp_path: Path) -> None:
    _write_backdata(tmp_path / "backdata.csv", [
        ["run1", "t", "c", "v", "m", "forte", 10, 10, "avg_at_3", 45.0, "{}"],
    ])

    with patch("office_bench.cli.RESULTS_BASE", tmp_path):
        ret = main(["trend", "--suite", "nothing-matches"])

    assert ret == 0
    assert "No matching data" in capsys.readouterr().out


def test_trend_missing_csv_fails(capsys, tmp_path: Path) -> None:
    with patch("office_bench.cli.RESULTS_BASE", tmp_path):
        ret = main(["trend"])
    assert ret == 1
    assert "backdata" in capsys.readouterr().err.lower()


# --- compare ---


def test_compare_command(capsys, tmp_path: Path) -> None:
    _write_result("run1", "forte", 0.40, tmp_path)
    _write_result("run2", "forte", 0.45, tmp_path)

    with patch("office_bench.cli.RESULTS_BASE", tmp_path):
        ret = main(["compare", "--runs", "run1", "run2"])

    assert ret == 0
    captured = capsys.readouterr().out
    assert "run1" in captured
    assert "run2" in captured
    assert "forte" in captured
    assert "+5.00" in captured  # 45.0 − 40.0


def test_compare_missing_run_fails(capsys, tmp_path: Path) -> None:
    with patch("office_bench.cli.RESULTS_BASE", tmp_path):
        ret = main(["compare", "--runs", "run1", "run2"])
    assert ret == 1
    assert "not found" in capsys.readouterr().err.lower()


def test_compare_missing_second_run_fails(capsys, tmp_path: Path) -> None:
    _write_result("run1", "forte", 0.40, tmp_path)
    with patch("office_bench.cli.RESULTS_BASE", tmp_path):
        ret = main(["compare", "--runs", "run1", "run2"])
    assert ret == 1
    assert "run2" in capsys.readouterr().err


# --- registry wiring & module entry point (coverage gaps) ---


def _install_fake_adapter(
    monkeypatch: pytest.MonkeyPatch, module_name: str, cls_name: str
) -> None:
    """Stand in for a suite adapter module before Tasks 7-10 land it."""
    module = types.ModuleType(module_name)

    def _init(self: object, repo_dir: Path) -> None:
        self.repo_dir = repo_dir  # type: ignore[attr-defined]

    setattr(module, cls_name, type(cls_name, (), {"__init__": _init}))
    monkeypatch.setitem(sys.modules, module_name, module)


def test_build_suite_registry_discovers_all_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each adapter is lazily imported and bound to its repo dir under
    data/benchmarks/ (global constraint: fixed submodule paths)."""
    from office_bench.cli import DATA_BASE, _build_suite_registry

    _install_fake_adapter(monkeypatch, "office_bench.suites.officebench", "OfficeBenchSuite")
    _install_fake_adapter(monkeypatch, "office_bench.suites.pptc", "PPTCSuite")
    _install_fake_adapter(monkeypatch, "office_bench.suites.spreadsheet", "SpreadsheetSuite")
    _install_fake_adapter(monkeypatch, "office_bench.suites.forte", "ForteSuite")

    registry = _build_suite_registry()

    assert set(registry) == {"officebench", "pptc", "spreadsheet", "forte"}
    assert registry["officebench"].repo_dir == DATA_BASE / "OfficeBench"  # type: ignore[attr-defined]
    assert registry["pptc"].repo_dir == DATA_BASE / "PPTC"  # type: ignore[attr-defined]
    assert registry["spreadsheet"].repo_dir == DATA_BASE / "SpreadsheetBench-2"  # type: ignore[attr-defined]
    assert registry["forte"].repo_dir == DATA_BASE / "FORTE"  # type: ignore[attr-defined]


def test_build_suite_registry_empty_when_adapters_unimportable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ImportError per adapter degrades to an empty registry, not a crash."""
    from office_bench.cli import _build_suite_registry

    real_import = builtins.__import__

    def _failing_import(name, *args, **kwargs):
        if name.startswith("office_bench.suites."):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _failing_import)
    assert _build_suite_registry() == {}


def test_dunder_main_forwards_cli_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`python -m office_bench` exits with main()'s return code."""
    monkeypatch.delitem(sys.modules, "office_bench.__main__", raising=False)
    with patch("office_bench.cli.main", return_value=3):
        with pytest.raises(SystemExit) as exc_info:
            importlib.import_module("office_bench.__main__")
    assert exc_info.value.code == 3


# --- review findings (loop 2) ---


def test_report_tolerates_stray_json(capsys, tmp_path: Path) -> None:
    """M-1: a stray valid JSON in the run dir must not crash `report` —
    every other consumer of load_task_results tolerates it."""
    _write_result("run1", "forte", 1.0, tmp_path)
    (tmp_path / "run1" / "notes.json").write_text(
        json.dumps({"note": "operator annotation"})
    )
    with patch("office_bench.cli.RESULTS_BASE", tmp_path):
        ret = main(["report", "--run-id", "run1"])
    assert ret == 0
    assert "forte" in (tmp_path / "run1" / "report.md").read_text().lower()


def test_compare_tolerates_stray_json(capsys, tmp_path: Path) -> None:
    """M-1: same crash class in `compare` (stray non-object JSON)."""
    _write_result("run1", "forte", 0.40, tmp_path)
    _write_result("run2", "forte", 0.45, tmp_path)
    (tmp_path / "run2" / "snippet.json").write_text("[1, 2, 3]")
    with patch("office_bench.cli.RESULTS_BASE", tmp_path):
        ret = main(["compare", "--runs", "run1", "run2"])
    assert ret == 0
    assert "+5.00" in capsys.readouterr().out


def test_run_filters_strip_whitespace_and_drop_empty_segments(
    tmp_path: Path,
) -> None:
    """M-2: --task-id/--category must behave like --suite — strip segments,
    drop empties — so "t1, t2," never silently scopes a run."""
    with (
        patch("office_bench.cli._build_suite_registry") as mock_reg,
        patch("office_bench.cli.Runner") as mock_runner_cls,
        patch("office_bench.cli.RESULTS_BASE", tmp_path),
    ):
        mock_reg.return_value = {"fakesuite": FakeSuite()}
        ret = main([
            "run", "--suite", "fakesuite",
            "--task-id", "t1, t2,",
            "--category", " cat-a ,, cat-b ",
        ])
    assert ret == 0
    config = mock_runner_cls.call_args[0][0]
    assert config.task_ids == ["t1", "t2"]
    assert config.categories == ["cat-a", "cat-b"]


def test_run_suite_flag_strips_whitespace(tmp_path: Path) -> None:
    """Pin-only (M-2 asymmetry): --suite stripping already works."""
    with (
        patch("office_bench.cli._build_suite_registry") as mock_reg,
        patch("office_bench.cli.Runner") as mock_runner_cls,
        patch("office_bench.cli.RESULTS_BASE", tmp_path),
    ):
        mock_reg.return_value = {"suite-a": FakeSuite(), "suite-b": FakeSuite()}
        ret = main(["run", "--suite", " suite-a , suite-b "])
    assert ret == 0
    assert mock_runner_cls.call_args[0][0].suites == ["suite-a", "suite-b"]


def test_run_rejects_degenerate_filter_flags(capsys, tmp_path: Path) -> None:
    """M-2 (R2c): a filter flag with no valid ids must fail loudly, not
    run zero tasks and append a permanent 0/0 backdata row."""
    with (
        patch("office_bench.cli._build_suite_registry", return_value={"fakesuite": FakeSuite()}),
        patch("office_bench.cli.Runner") as mock_runner_cls,
        patch("office_bench.cli.RESULTS_BASE", tmp_path),
    ):
        ret = main(["run", "--suite", "fakesuite", "--task-id", ","])
    assert ret == 1
    assert "task-id" in capsys.readouterr().err.lower()
    mock_runner_cls.assert_not_called()


def test_run_suite_all_with_empty_registry_fails(capsys, tmp_path: Path) -> None:
    """M-3(a): --suite all with no adapters must be a loud no-op failure,
    not a successful-looking empty run."""
    with (
        patch("office_bench.cli._build_suite_registry", return_value={}),
        patch("office_bench.cli.Runner") as mock_runner_cls,
        patch("office_bench.cli.RESULTS_BASE", tmp_path),
    ):
        ret = main(["run", "--suite", "all"])
    assert ret == 1
    assert "no suite" in capsys.readouterr().err.lower()
    mock_runner_cls.assert_not_called()
    assert not (tmp_path / "backdata.csv").exists()


def test_run_rejects_degenerate_suite_value(capsys, tmp_path: Path) -> None:
    """M-3: --suite "," resolves to zero suite names — loud failure."""
    with (
        patch("office_bench.cli._build_suite_registry", return_value={"fakesuite": FakeSuite()}),
        patch("office_bench.cli.Runner") as mock_runner_cls,
        patch("office_bench.cli.RESULTS_BASE", tmp_path),
    ):
        ret = main(["run", "--suite", ","])
    assert ret == 1
    assert "suite" in capsys.readouterr().err.lower()
    mock_runner_cls.assert_not_called()


def test_run_rejects_nonpositive_runs_and_limit(tmp_path: Path) -> None:
    """M-3(b): --runs 0 / --limit 0 / negatives are parser errors, never
    configs that append permanent 0/0 CSV rows."""
    for flag in ("--runs", "--limit"):
        for bad in ("0", "-1", "abc"):
            with (
                patch("office_bench.cli._build_suite_registry", return_value={"fakesuite": FakeSuite()}),
                patch("office_bench.cli.Runner") as mock_runner_cls,
                patch("office_bench.cli.RESULTS_BASE", tmp_path),
                pytest.raises(SystemExit) as exc_info,
            ):
                main(["run", "--suite", "fakesuite", flag, bad])
            assert exc_info.value.code == 2
            mock_runner_cls.assert_not_called()


def test_compare_marks_suites_missing_from_one_run(capsys, tmp_path: Path) -> None:
    """M-4: a suite absent from one run is 'not run' — no fabricated
    delta that reads as a regression or improvement."""
    _write_result("run1", "forte", 0.45, tmp_path)
    _write_result("run2", "pptc", 1.0, tmp_path)
    with patch("office_bench.cli.RESULTS_BASE", tmp_path):
        ret = main(["compare", "--runs", "run1", "run2"])
    assert ret == 0
    out = capsys.readouterr().out
    assert out.count("not run") == 2
    assert "-45.00" not in out
    assert "+100.00" not in out


def test_setup_reports_git_failure(capsys) -> None:
    """L-1: a failing git must not print 'Setup complete' and exit 0."""
    with patch("office_bench.cli.subprocess") as mock_sub:
        mock_sub.run.return_value = MagicMock(returncode=128)
        ret = main(["setup"])
    assert ret == 1
    assert "failed" in capsys.readouterr().err.lower()


def test_setup_survives_missing_git(capsys) -> None:
    """L-1: a missing git binary is a clean error, not a traceback."""
    with patch("office_bench.cli.subprocess") as mock_sub:
        mock_sub.run.side_effect = OSError("No such file or directory: 'git'")
        ret = main(["setup"])
    assert ret == 1
    assert "git" in capsys.readouterr().err.lower()


def test_trend_indicates_truncation(capsys, tmp_path: Path) -> None:
    """L-2: truncating to the last 10 rows must be visible to the operator."""
    _write_backdata(tmp_path / "backdata.csv", [
        [f"run{i:02d}", "t", "c", "v", "m", "forte", 10, 10, "avg_at_3", 40.0 + i, "{}"]
        for i in range(1, 13)
    ])
    with patch("office_bench.cli.RESULTS_BASE", tmp_path):
        ret = main(["trend"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "of 12" in out  # truncation marker: showing N most recent of 12
    assert "run01" not in out
    assert "run12" in out


def test_run_end_to_end_writes_honest_backdata_row(capsys, tmp_path: Path) -> None:
    """L-3(a)/M-2 end-to-end: real Runner (fake suite, mock bridge) via the
    CLI — whitespace in --task-id runs BOTH tasks and the CSV row says 2/2."""
    with (
        patch("office_bench.cli._build_suite_registry", return_value={"fakesuite": FakeSuite()}),
        patch("office_bench.runner.AgentBridge") as mock_bridge_cls,
        patch("office_bench.cli.RESULTS_BASE", tmp_path),
    ):
        mock_bridge_cls.return_value = MagicMock()
        mock_bridge_cls.return_value.run_task.return_value = AgentOutput(
            messages=[{"role": "assistant", "content": "done"}],
            files_created=[],
            tool_calls=[],
            duration_seconds=1.0,
        )
        ret = main([
            "run", "--suite", "fakesuite",
            "--task-id", "t1, t2",
            "--run-id", "e2e",
        ])
    assert ret == 0
    with (tmp_path / "backdata.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["suite"] == "fakesuite"
    assert rows[0]["tasks_run"] == "2"
    assert rows[0]["tasks_total"] == "2"
    assert rows[0]["primary_value"] == "100.0"
