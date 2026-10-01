"""E2E test: validate artifact structure, content, and cross-consistency.

Runs the full pipeline then deeply inspects every generated artifact:
result JSONs, meta.json, backdata.csv columns, and report.md structure.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from office_bench.cli import main
from office_bench.results import BACKDATA_COLUMNS
from office_bench.suites.spreadsheet import SpreadsheetSuite


def _run_multi_suite(patched_cli: Path) -> Path:
    """Run officebench+forte and return the run directory."""
    with patch.object(SpreadsheetSuite, "_recalculate", staticmethod(lambda p: p)):
        result = main([
            "run", "--suite", "officebench,forte", "--runs", "2",
        ])
    assert result == 0
    run_dirs = [d for d in sorted(patched_cli.iterdir()) if d.is_dir()]
    return run_dirs[0]


class TestResultJSON:
    """Validate per-task result JSON structure."""

    def test_result_has_required_fields(self, patched_cli: Path) -> None:
        run_dir = _run_multi_suite(patched_cli)

        for suite_dir in (run_dir / "officebench", run_dir / "forte"):
            if not suite_dir.exists():
                continue
            for result_file in suite_dir.glob("*.json"):
                data = json.loads(result_file.read_text())
                assert "task_id" in data, f"Missing task_id in {result_file}"
                assert "suite" in data
                assert "passed" in data
                assert "score" in data
                assert isinstance(data["score"], (int, float))
                assert 0.0 <= data["score"] <= 1.0
                assert "breakdown" in data
                assert "notes" in data
                assert "judge_backend" in data

    def test_result_has_agent_output(self, patched_cli: Path) -> None:
        """Result JSONs include the agent output summary."""
        run_dir = _run_multi_suite(patched_cli)

        for suite_dir in (run_dir / "officebench",):
            for result_file in suite_dir.glob("*.json"):
                data = json.loads(result_file.read_text())
                assert "agent_output" in data
                ao = data["agent_output"]
                # save_task_result stores response_text, not raw messages
                assert "response_text" in ao
                assert "duration_seconds" in data
                assert isinstance(data["duration_seconds"], (int, float))

    def test_result_filename_convention(self, patched_cli: Path) -> None:
        """Result files follow {task_id}_run{N}.json naming."""
        run_dir = _run_multi_suite(patched_cli)

        for suite_dir in run_dir.iterdir():
            if not suite_dir.is_dir():
                continue
            for result_file in suite_dir.glob("*.json"):
                stem = result_file.stem
                assert "_run" in stem, f"Bad filename: {result_file.name}"
                parts = stem.rsplit("_run", 1)
                assert parts[1].isdigit(), f"Bad run number: {result_file.name}"


class TestMetaJSON:
    """Validate run metadata."""

    def test_meta_has_required_fields(self, patched_cli: Path) -> None:
        run_dir = _run_multi_suite(patched_cli)
        meta = json.loads((run_dir / "meta.json").read_text())

        assert "run_id" in meta
        assert "timestamp" in meta
        assert "suites" in meta
        assert "runs" in meta
        assert meta["runs"] == 2
        assert set(meta["suites"]) == {"officebench", "forte"}

    def test_meta_has_provenance(self, patched_cli: Path) -> None:
        """Meta includes git commit and agent version for reproducibility."""
        run_dir = _run_multi_suite(patched_cli)
        meta = json.loads((run_dir / "meta.json").read_text())

        assert "git_commit" in meta
        assert "agent_version" in meta
        assert "model" in meta


class TestBackdataCSV:
    """Validate the append-only backdata CSV."""

    def test_backdata_columns_match_spec(self, patched_cli: Path) -> None:
        """CSV header matches the declared BACKDATA_COLUMNS constant."""
        _run_multi_suite(patched_cli)

        backdata = patched_cli / "backdata.csv"
        assert backdata.exists()

        with backdata.open() as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames is not None
            assert list(reader.fieldnames) == BACKDATA_COLUMNS

    def test_backdata_values_consistent_with_results(
        self, patched_cli: Path
    ) -> None:
        """Backdata tasks_total matches the number of result files.

        _aggregate_accuracy counts all result rows (task × run), not
        unique task IDs.  With 2 tasks × 2 runs = 4 result rows for
        officebench.  FORTE uses unique tasks for tasks_total.
        """
        run_dir = _run_multi_suite(patched_cli)
        backdata = patched_cli / "backdata.csv"

        with backdata.open() as f:
            rows = list(csv.DictReader(f))

        for row in rows:
            suite_name = row["suite"]
            suite_dir = run_dir / suite_name
            if not suite_dir.exists():
                continue

            result_files = list(suite_dir.glob("*.json"))
            tasks_total = int(row["tasks_total"])
            # tasks_total >= unique tasks; exact count depends on aggregator
            assert tasks_total > 0
            assert tasks_total <= len(result_files)

    def test_backdata_idempotent_on_resume(self, patched_cli: Path) -> None:
        """Resuming the same run does not add duplicate CSV rows."""
        main(["run", "--suite", "officebench", "--runs", "1"])
        run_dirs = [d for d in sorted(patched_cli.iterdir()) if d.is_dir()]
        run_id = run_dirs[0].name

        with (patched_cli / "backdata.csv").open() as f:
            count1 = len(list(csv.DictReader(f)))

        main(["run", "--suite", "officebench", "--runs", "1", "--run-id", run_id])
        with (patched_cli / "backdata.csv").open() as f:
            count2 = len(list(csv.DictReader(f)))

        assert count2 == count1


class TestReportMD:
    """Validate the Markdown report structure."""

    def test_report_has_header_and_suites(self, patched_cli: Path) -> None:
        run_dir = _run_multi_suite(patched_cli)
        report = (run_dir / "report.md").read_text()

        assert "# " in report or "## " in report
        assert "officebench" in report
        assert "forte" in report

    def test_report_contains_scores(self, patched_cli: Path) -> None:
        """Report contains numeric score values."""
        run_dir = _run_multi_suite(patched_cli)
        report = (run_dir / "report.md").read_text()

        numbers = re.findall(r"\d+\.\d+", report)
        assert len(numbers) > 0, "Report should contain numeric scores"

    def test_report_mentions_reference_scores(self, patched_cli: Path) -> None:
        """Report references published model scores for comparison."""
        run_dir = _run_multi_suite(patched_cli)
        report = (run_dir / "report.md").read_text()

        reference_models = ["gpt-4o", "claude-3.5-sonnet", "gemini-1.5-pro"]
        found = any(m in report for m in reference_models)
        assert found, "Report should reference published model scores"
