from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from office_bench.results import (
    BackdataRow,
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


def test_backdata_row_columns() -> None:
    """BackdataRow TypedDict must carry the exact backdata CSV columns."""
    expected = {
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
    }
    assert set(BackdataRow.__annotations__) == expected
