from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from office_bench.cli import main
from office_bench.runner import RunConfig
from office_bench.suites.base import Task


class FakeSuite:
    """Minimal suite for `list` — only load_tasks is exercised."""

    name = "fakesuite"

    def load_tasks(self) -> list[Task]:
        return [
            Task("fakesuite", "t1", "p1", "cat-a", [], {}),
            Task("fakesuite", "t2", "p2", "cat-b", [], {}),
        ]

    def setup_workspace(self, *a) -> None:  # pragma: no cover - unused here
        pass

    def format_prompt(self, t: Task) -> str:
        return t.prompt

    def evaluate(self, *a) -> None:  # pragma: no cover - unused here
        pass


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
