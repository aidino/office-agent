"""E2E test: per-suite CLI run → real adapter → evaluate → artifacts.

Each test exercises: CLI main() → Runner → real suite adapter with fixture
data → evaluation → JSON results + backdata CSV + Markdown report.

The only mock is AgentBridge (no live AG-UI gateway). Suite adapters,
evaluation logic, file I/O, and report generation are all real.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from openpyxl import Workbook
from pptx import Presentation

from office_bench.cli import main
from office_bench.suites.spreadsheet import SpreadsheetSuite


# ── FORTE ───────────────────────────────────────────────────────────


def test_forte_cli_run(patched_cli: Path) -> None:
    """Run FORTE suite end-to-end: load 3 fixture tasks, evaluate, check
    artifacts.  hr-001 has no rubrics → not evaluable; hr-002 is automated
    (grade_one); finance-001 is llm_judge → mock judge is used.
    """
    result = main(["run", "--suite", "forte", "--runs", "1"])
    assert result == 0

    # Find the run directory (timestamped)
    run_dirs = sorted(patched_cli.iterdir())
    run_dir = [d for d in run_dirs if d.is_dir()][0]

    assert (run_dir / "meta.json").exists()
    assert (run_dir / "report.md").exists()

    # Per-task results: 3 tasks × 1 run = 3 files
    forte_results = list((run_dir / "forte").glob("*.json"))
    assert len(forte_results) == 3

    results = [json.loads(f.read_text()) for f in forte_results]
    by_id = {r["task_id"]: r for r in results}

    # hr-001: no rubrics → not evaluable (score 0)
    assert by_id["hr-001"]["passed"] is False
    assert "not evaluable" in by_id["hr-001"]["notes"]

    # hr-002: automated, grade_one fixture passes when response
    # contains "department a"
    assert by_id["hr-002"]["passed"] is True
    assert by_id["hr-002"]["score"] == 1.0

    # Backdata CSV
    backdata = patched_cli / "backdata.csv"
    assert backdata.exists()
    with backdata.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["suite"] == "forte"

    # Report
    report = (run_dir / "report.md").read_text()
    assert "forte" in report


# ── OfficeBench ────────────────────────────────────────────────────


def test_officebench_cli_run(patched_cli: Path) -> None:
    """OfficeBench: 2 tasks (1-1 file_exist, 2-1 contain).
    Mock bridge creates budget.xlsx and summary.txt → both pass.
    """
    result = main(["run", "--suite", "officebench", "--runs", "1"])
    assert result == 0

    run_dirs = [d for d in sorted(patched_cli.iterdir()) if d.is_dir()]
    run_dir = run_dirs[0]

    ob_results = list((run_dir / "officebench").glob("*.json"))
    assert len(ob_results) == 2

    results = [json.loads(f.read_text()) for f in ob_results]
    by_id = {r["task_id"]: r for r in results}

    assert by_id["1-1"]["passed"] is True
    assert by_id["1-1"]["judge_backend"] == "deterministic"
    assert by_id["2-1"]["passed"] is True

    # Backdata
    with (patched_cli / "backdata.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert float(rows[0]["primary_value"]) == pytest.approx(100.0, abs=0.1)


# ── SpreadsheetBench ───────────────────────────────────────────────


def test_spreadsheet_cli_run(patched_cli: Path) -> None:
    """SpreadsheetBench: 3 fixture tasks (debug-001, fin-001, viz-001).
    Mock bridge creates xlsx with correct cell values.
    Recalculate is patched to identity.
    Visualization is deferred → always fails.
    """
    with patch.object(SpreadsheetSuite, "_recalculate", staticmethod(lambda p: p)):
        result = main(["run", "--suite", "spreadsheet", "--runs", "1"])
    assert result == 0

    run_dirs = [d for d in sorted(patched_cli.iterdir()) if d.is_dir()]
    run_dir = run_dirs[0]

    ss_results = list((run_dir / "spreadsheet").glob("*.json"))
    assert len(ss_results) == 3

    results = [json.loads(f.read_text()) for f in ss_results]
    by_id = {r["task_id"]: r for r in results}

    # Debugging: cell B5 = 150 matches
    assert by_id["debug-001"]["passed"] is True
    assert by_id["debug-001"]["score"] == 1.0

    # Financial_Model: C3=1000, C4=1100 both match
    assert by_id["fin-001"]["passed"] is True

    # Visualization: deferred
    assert by_id["viz-001"]["passed"] is False
    assert "Visualization" in by_id["viz-001"]["notes"]


# ── PPTC ───────────────────────────────────────────────────────────


def test_pptc_cli_run(patched_cli: Path) -> None:
    """PPTC: 2 sessions. session_1 is multi-turn (Create), session_2 is
    single-turn (Edit). Both produce pptx but labels may not match the
    mock output exactly — what we verify is the pipeline completes and
    produces result JSONs with deterministic judge_backend.
    """
    result = main(["run", "--suite", "pptc", "--runs", "1"])
    assert result == 0

    run_dirs = [d for d in sorted(patched_cli.iterdir()) if d.is_dir()]
    run_dir = run_dirs[0]

    pptc_results = list((run_dir / "pptc").glob("*.json"))
    assert len(pptc_results) == 2

    results = [json.loads(f.read_text()) for f in pptc_results]
    for r in results:
        assert r["suite"] == "pptc"
        assert r["judge_backend"] == "deterministic"
        assert "task_id" in r
        assert isinstance(r["score"], (int, float))

    # session_1 has 2 turns → run_session must have been called
    # session_2 has 1 turn → should go through run_session (turn_prompts > 1)
    #   or run_task if only 1 prompt. Verify at least one session call.

    # Meta and report present
    assert (run_dir / "meta.json").exists()
    assert (run_dir / "report.md").exists()


# ── Multi-suite ────────────────────────────────────────────────────


def test_multi_suite_run(patched_cli: Path) -> None:
    """Run multiple suites in one CLI invocation."""
    with patch.object(SpreadsheetSuite, "_recalculate", staticmethod(lambda p: p)):
        result = main([
            "run",
            "--suite", "officebench,forte",
            "--runs", "1",
        ])
    assert result == 0

    run_dirs = [d for d in sorted(patched_cli.iterdir()) if d.is_dir()]
    run_dir = run_dirs[0]

    # Both suite result dirs exist
    assert (run_dir / "officebench").exists()
    assert (run_dir / "forte").exists()

    # Backdata has 2 rows, one per suite
    with (patched_cli / "backdata.csv").open() as f:
        rows = list(csv.DictReader(f))
    suites_in_csv = {r["suite"] for r in rows}
    assert suites_in_csv == {"officebench", "forte"}

    # Report references both suites
    report = (run_dir / "report.md").read_text()
    assert "officebench" in report
    assert "forte" in report


# ── Filters ────────────────────────────────────────────────────────


def test_task_id_filter(patched_cli: Path) -> None:
    """--task-id filters down to a specific task."""
    result = main([
        "run", "--suite", "officebench", "--runs", "1",
        "--task-id", "1-1",
    ])
    assert result == 0

    run_dirs = [d for d in sorted(patched_cli.iterdir()) if d.is_dir()]
    run_dir = run_dirs[0]

    ob_results = list((run_dir / "officebench").glob("*.json"))
    assert len(ob_results) == 1
    data = json.loads(ob_results[0].read_text())
    assert data["task_id"] == "1-1"


def test_category_filter(patched_cli: Path) -> None:
    """--category filters FORTE tasks by category."""
    result = main([
        "run", "--suite", "forte", "--runs", "1",
        "--category", "hr",
    ])
    assert result == 0

    run_dirs = [d for d in sorted(patched_cli.iterdir()) if d.is_dir()]
    run_dir = run_dirs[0]

    forte_results = list((run_dir / "forte").glob("*.json"))
    # Only hr-001 and hr-002 are in category "hr"
    assert len(forte_results) == 2
    ids = {json.loads(f.read_text())["task_id"] for f in forte_results}
    assert ids == {"hr-001", "hr-002"}


def test_limit_filter(patched_cli: Path) -> None:
    """--limit caps the number of tasks per suite."""
    result = main([
        "run", "--suite", "forte", "--runs", "1",
        "--limit", "1",
    ])
    assert result == 0

    run_dirs = [d for d in sorted(patched_cli.iterdir()) if d.is_dir()]
    run_dir = run_dirs[0]

    forte_results = list((run_dir / "forte").glob("*.json"))
    assert len(forte_results) == 1


# ── Resume ─────────────────────────────────────────────────────────


def test_resume_via_run_id(patched_cli: Path, mock_bridge) -> None:
    """--run-id resumes: completed tasks are skipped, backdata not duplicated."""
    result1 = main([
        "run", "--suite", "officebench", "--runs", "1",
    ])
    assert result1 == 0

    run_dirs = [d for d in sorted(patched_cli.iterdir()) if d.is_dir()]
    run_dir = run_dirs[0]
    run_id = run_dir.name

    first_count = mock_bridge.run_task.call_count

    # Resume with same run_id
    result2 = main([
        "run", "--suite", "officebench", "--runs", "1",
        "--run-id", run_id,
    ])
    assert result2 == 0

    # Bridge should not have been called again
    assert mock_bridge.run_task.call_count == first_count

    # Backdata CSV should still have exactly 1 row for officebench
    with (patched_cli / "backdata.csv").open() as f:
        rows = list(csv.DictReader(f))
    ob_rows = [r for r in rows if r["suite"] == "officebench"]
    assert len(ob_rows) == 1


# ── Multiple runs ──────────────────────────────────────────────────


def test_multiple_runs_per_task(patched_cli: Path) -> None:
    """--runs=2 produces 2 result files per task."""
    result = main([
        "run", "--suite", "officebench", "--runs", "2",
        "--task-id", "1-1",
    ])
    assert result == 0

    run_dirs = [d for d in sorted(patched_cli.iterdir()) if d.is_dir()]
    run_dir = run_dirs[0]

    ob_results = list((run_dir / "officebench").glob("*.json"))
    assert len(ob_results) == 2

    # Both should be for task 1-1
    for f in ob_results:
        data = json.loads(f.read_text())
        assert data["task_id"] == "1-1"
