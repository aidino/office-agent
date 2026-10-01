"""E2E test: post-run CLI commands (report, trend, compare, list).

These tests first create a run via the pipeline, then exercise the
report regeneration, trend display, and compare commands.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from office_bench.cli import main
from office_bench.suites.spreadsheet import SpreadsheetSuite


def test_report_regeneration(patched_cli: Path, capsys) -> None:
    """CLI report command regenerates a Markdown report from existing results."""
    result = main(["run", "--suite", "officebench", "--runs", "1"])
    assert result == 0

    run_dirs = [d for d in sorted(patched_cli.iterdir()) if d.is_dir()]
    run_dir = run_dirs[0]
    run_id = run_dir.name

    # Delete the report
    report_path = run_dir / "report.md"
    assert report_path.exists()
    report_path.unlink()
    assert not report_path.exists()

    # Regenerate
    result = main(["report", "--run-id", run_id])
    assert result == 0

    # Report is back
    assert report_path.exists()
    report = report_path.read_text()
    assert "officebench" in report

    captured = capsys.readouterr()
    assert "Report regenerated" in captured.out


def test_report_missing_run(patched_cli: Path) -> None:
    """CLI report returns 1 for non-existent run."""
    result = main(["report", "--run-id", "nonexistent-run"])
    assert result == 1


def test_trend_shows_data(patched_cli: Path, capsys) -> None:
    """CLI trend displays backdata rows after a run."""
    main(["run", "--suite", "officebench", "--runs", "1"])

    result = main(["trend"])
    assert result == 0

    captured = capsys.readouterr()
    assert "officebench" in captured.out
    assert "Run ID" in captured.out


def test_trend_filter_by_suite(patched_cli: Path, capsys) -> None:
    """CLI trend --suite filters to one suite."""
    with patch.object(SpreadsheetSuite, "_recalculate", staticmethod(lambda p: p)):
        main(["run", "--suite", "officebench,forte", "--runs", "1"])

    result = main(["trend", "--suite", "forte"])
    assert result == 0

    captured = capsys.readouterr()
    assert "forte" in captured.out
    # officebench should not appear (filtered out)
    lines = captured.out.strip().split("\n")
    data_lines = [line for line in lines if "officebench" in line]
    assert len(data_lines) == 0


def test_trend_no_data(patched_cli: Path) -> None:
    """CLI trend returns 1 when no backdata.csv exists."""
    result = main(["trend"])
    assert result == 1


def test_compare_two_runs(patched_cli: Path, capsys) -> None:
    """CLI compare shows delta between two runs."""
    main(["run", "--suite", "officebench", "--runs", "1", "--run-id", "run-A"])
    main(["run", "--suite", "officebench", "--runs", "1", "--run-id", "run-B"])

    result = main(["compare", "--runs", "run-A", "run-B"])
    assert result == 0

    captured = capsys.readouterr()
    assert "officebench" in captured.out
    assert "Suite" in captured.out


def test_compare_missing_run(patched_cli: Path) -> None:
    """CLI compare returns 1 when a run ID doesn't exist."""
    main(["run", "--suite", "officebench", "--runs", "1", "--run-id", "run-X"])
    result = main(["compare", "--runs", "run-X", "nonexistent"])
    assert result == 1


def test_list_tasks(patched_cli: Path, capsys) -> None:
    """CLI list shows tasks for a suite."""
    result = main(["list", "--suite", "officebench"])
    assert result == 0

    captured = capsys.readouterr()
    assert "1-1" in captured.out
    assert "2-1" in captured.out
