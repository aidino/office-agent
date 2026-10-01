"""JSON persistence, backdata CSV, and Markdown report generation."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from office_bench.suites.base import AgentOutput, TaskResult

BACKDATA_COLUMNS = [
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
]


class BackdataRow(TypedDict):
    """One append-only row of the backdata CSV (columns in BACKDATA_COLUMNS)."""

    run_id: str
    timestamp: str
    git_commit: str
    agent_version: str
    model: str
    suite: str
    tasks_total: int
    tasks_run: int
    primary_metric: str
    primary_value: float
    secondary_metrics: str


def save_task_result(
    run_dir: Path,
    result: TaskResult,
    run_number: int,
    agent_output: AgentOutput,
) -> Path:
    """Write a per-task result JSON. Skips if file already exists (resume)."""
    suite_dir = run_dir / result.suite
    suite_dir.mkdir(parents=True, exist_ok=True)
    path = suite_dir / f"{result.task_id}_run{run_number}.json"

    if path.exists():
        return path

    data = {
        "task_id": result.task_id,
        "suite": result.suite,
        "run": run_number,
        "passed": result.passed,
        "score": result.score,
        "breakdown": result.breakdown,
        "judge_backend": result.judge_backend,
        "notes": result.notes,
        "duration_seconds": agent_output.duration_seconds,
        "agent_output": {
            "response_text": (
                agent_output.messages[-1].get("content", "")
                if agent_output.messages
                else ""
            ),
            "tool_calls": agent_output.tool_calls,
            "files_created": [str(p) for p in agent_output.files_created],
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return path


def load_task_results(run_dir: Path) -> list[dict]:
    """Read all per-task result JSONs from a run directory."""
    results: list[dict] = []
    for json_path in sorted(run_dir.rglob("*.json")):
        if json_path.name == "meta.json" or json_path.name == "summary.json":
            continue
        try:
            results.append(json.loads(json_path.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return results


def save_run_meta(run_dir: Path, meta: dict) -> Path:
    """Write run metadata to meta.json."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "meta.json"
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    return path


def aggregate_suite(results: list[dict], suite_name: str) -> dict:
    """Compute primary metric for a suite from its task results."""
    suite_results = [r for r in results if r.get("suite") == suite_name]

    if not suite_results:
        return {
            "primary_metric": "n/a",
            "primary_value": 0.0,
            "tasks_run": 0,
            "tasks_total": 0,
        }

    if suite_name == "forte":
        return _aggregate_forte(suite_results)
    elif suite_name == "officebench":
        return _aggregate_accuracy(suite_results, "accuracy")
    elif suite_name == "spreadsheet":
        return _aggregate_accuracy(suite_results, "pass_at_1")
    elif suite_name == "pptc":
        return _aggregate_accuracy(suite_results, "session_acc")
    else:
        return _aggregate_accuracy(suite_results, "accuracy")


def _aggregate_forte(results: list[dict]) -> dict:
    """Avg@N: mean of per-task mean scores across runs.

    Rows without a ``task_id`` (e.g. a stray valid JSON ingested by
    ``load_task_results``) are skipped, so one alien file cannot crash
    aggregation after a full run.
    """
    by_task: dict[str, list[float]] = defaultdict(list)
    ingested = 0
    for r in results:
        task_id = r.get("task_id")
        if not task_id:
            continue
        by_task[task_id].append(r.get("score", 0.0))
        ingested += 1

    task_avgs = [sum(scores) / len(scores) for scores in by_task.values()]
    n = max(len(scores) for scores in by_task.values()) if by_task else 1
    overall = (sum(task_avgs) / len(task_avgs) * 100) if task_avgs else 0.0

    return {
        "primary_metric": f"avg_at_{n}",
        "primary_value": round(overall, 2),
        # unique tasks, not task×run rows, so reports never show "6/2 tasks"
        "tasks_run": len(by_task),
        "tasks_total": len(by_task),
        "result_rows": ingested,
    }


def _aggregate_accuracy(results: list[dict], metric_name: str) -> dict:
    """Simple accuracy: passed / total × 100."""
    passed = sum(1 for r in results if r.get("passed"))
    total = len(results)
    value = round(passed / total * 100, 2) if total else 0.0
    return {
        "primary_metric": metric_name,
        "primary_value": value,
        "tasks_run": total,
        "tasks_total": total,
    }


def append_backdata(backdata_path: Path, row: dict) -> None:
    """Append one row to the backdata CSV, creating with header if needed."""
    backdata_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not backdata_path.exists()

    with backdata_path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=BACKDATA_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow({col: row.get(col, "") for col in BACKDATA_COLUMNS})


def has_backdata_row(backdata_path: Path, run_id: str, suite: str) -> bool:
    """True if a row for (run_id, suite) already exists in the CSV."""
    if not backdata_path.exists():
        return False
    with backdata_path.open(newline="") as f:
        for row in csv.DictReader(f):
            if row.get("run_id") == run_id and row.get("suite") == suite:
                return True
    return False


def generate_report(
    run_dir: Path,
    aggregated: dict[str, dict],
    reference: dict,
) -> Path:
    """Generate a Markdown report at run_dir/report.md."""
    lines: list[str] = []
    run_id = run_dir.name

    lines.append(f"# Benchmark Report — {run_id}\n")

    # Meta
    meta_path = run_dir / "meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            # e.g. truncated by a crash mid-save — the per-task results
            # are still reportable
            meta = None
        if meta is None:
            lines.append("_Note: meta.json unreadable — run metadata omitted._\n")
        else:
            lines.append("## Run Metadata\n")
            for k, v in meta.items():
                lines.append(f"- **{k}**: {v}")
            lines.append("")

    # Results table
    lines.append("## Results\n")
    lines.append("| Suite | Metric | Score | Tasks |")
    lines.append("|-------|--------|-------|-------|")
    for suite, agg in sorted(aggregated.items()):
        metric = agg.get("primary_metric", "n/a")
        value = agg.get("primary_value", 0)
        tasks = f"{agg.get('tasks_run', 0)}/{agg.get('tasks_total', 0)}"
        lines.append(f"| {suite} | {metric} | {value} | {tasks} |")
    lines.append("")

    # Reference comparison
    lines.append("## Reference Scores\n")
    for suite, agg in sorted(aggregated.items()):
        ref = reference.get(suite, {})
        ref_scores = ref.get("scores", {})
        if not ref_scores:
            continue
        lines.append(f"### {suite}\n")
        lines.append(f"*Source: {ref.get('source', 'N/A')}*\n")
        lines.append("| Model | Score |")
        lines.append("|-------|-------|")
        # Our score first
        lines.append(
            f"| **Office Agent** | **{agg.get('primary_value', 0)}** |"
        )
        for model, score in sorted(ref_scores.items()):
            lines.append(f"| {model} | {score} |")
        lines.append("")

    path = run_dir / "report.md"
    path.write_text("\n".join(lines))
    return path
