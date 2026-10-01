"""CLI: run, report, list, trend, compare, setup."""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

from office_bench.reference import REFERENCE_SCORES
from office_bench.results import (
    aggregate_suite,
    generate_report,
    load_task_results,
)
from office_bench.runner import RunConfig, Runner

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # benchmarks/src/office_bench → repo root
RESULTS_BASE = PROJECT_ROOT / "results" / "benchmarks"
DATA_BASE = PROJECT_ROOT / "data" / "benchmarks"


def _build_suite_registry() -> dict:
    """Build registry of available suite adapters. Lazily import to avoid
    import errors when suites aren't installed yet."""
    registry: dict = {}
    try:
        from office_bench.suites.officebench import OfficeBenchSuite
        registry["officebench"] = OfficeBenchSuite(DATA_BASE / "OfficeBench")
    except ImportError:
        pass
    try:
        from office_bench.suites.pptc import PPTCSuite
        registry["pptc"] = PPTCSuite(DATA_BASE / "PPTC")
    except ImportError:
        pass
    try:
        from office_bench.suites.spreadsheet import SpreadsheetSuite
        registry["spreadsheet"] = SpreadsheetSuite(DATA_BASE / "SpreadsheetBench-2")
    except ImportError:
        pass
    try:
        from office_bench.suites.forte import ForteSuite
        registry["forte"] = ForteSuite(DATA_BASE / "FORTE")
    except ImportError:
        pass
    return registry


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="office_bench",
        description="Office Agent Benchmark Harness",
    )
    sub = parser.add_subparsers(dest="command")

    # --- setup ---
    sub.add_parser("setup", help="Clone submodules and download datasets")

    # --- list ---
    p_list = sub.add_parser("list", help="List available benchmark tasks")
    p_list.add_argument("--suite", required=True, help="Suite name")

    # --- run ---
    p_run = sub.add_parser("run", help="Run benchmarks")
    p_run.add_argument("--suite", default="all", help="Comma-separated suite names or 'all'")
    p_run.add_argument("--runs", type=int, default=1, help="Number of runs per task")
    p_run.add_argument("--task-id", default=None, help="Comma-separated task IDs")
    p_run.add_argument("--category", default=None, help="Comma-separated categories")
    p_run.add_argument("--limit", type=int, default=None, help="Max tasks per suite")
    p_run.add_argument("--keep-workspaces", action="store_true")
    p_run.add_argument(
        "--no-resume",
        action="store_true",
        help="Re-run tasks even if result files already exist; existing files "
        "are kept, so the first run's numbers stand",
    )
    p_run.add_argument(
        "--run-id",
        default=None,
        help="Run inside the existing run directory with this id (resume) "
        "instead of creating a fresh timestamped one",
    )
    p_run.add_argument("--dual-judge", action="store_true")
    p_run.add_argument("--gateway-url", default="http://127.0.0.1:18088/agent")
    p_run.add_argument("--timeout", type=int, default=600)

    # --- report ---
    p_report = sub.add_parser("report", help="Regenerate report for a run")
    p_report.add_argument("--run-id", required=True)

    # --- trend ---
    p_trend = sub.add_parser("trend", help="Show backdata trend")
    p_trend.add_argument("--suite", default=None, help="Filter by suite")

    # --- compare ---
    p_compare = sub.add_parser("compare", help="Compare two runs")
    p_compare.add_argument("--runs", nargs=2, required=True, metavar="RUN_ID")

    args = parser.parse_args(argv)

    # Dict dispatch keeps every branch reachable: argparse already restricts
    # ``command`` to the registered subcommands.
    handlers = {
        "setup": _cmd_setup,
        "list": _cmd_list,
        "run": _cmd_run,
        "report": _cmd_report,
        "trend": _cmd_trend,
        "compare": _cmd_compare,
    }
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 0
    return handler(args)


def _cmd_setup(_args: argparse.Namespace) -> int:
    """Clone submodules and verify prerequisites."""
    print("Running git submodule update...")
    subprocess.run(
        ["git", "submodule", "update", "--init", "--recursive"],
        check=False,
    )
    print("Setup complete. Verify JUDGE_MODEL / JUDGE_API_KEY env vars.")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    """List tasks in a suite."""
    registry = _build_suite_registry()
    suite = registry.get(args.suite)
    if suite is None:
        print(f"Unknown suite: {args.suite}", file=sys.stderr)
        print(f"Available: {', '.join(registry.keys())}", file=sys.stderr)
        return 1

    tasks = suite.load_tasks()
    print(f"Suite: {suite.name} — {len(tasks)} tasks\n")
    print(f"{'ID':<20} {'Category':<20} {'Prompt (first 60 chars)'}")
    print("-" * 70)
    for t in tasks:
        prompt_preview = t.prompt[:60].replace("\n", " ")
        print(f"{t.task_id:<20} {t.category:<20} {prompt_preview}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    """Run benchmarks."""
    registry = _build_suite_registry()

    if args.suite == "all":
        suite_names = list(registry.keys())
    else:
        suite_names = [s.strip() for s in args.suite.split(",")]

    config = RunConfig(
        suites=suite_names,
        runs=args.runs,
        task_ids=args.task_id.split(",") if args.task_id else None,
        categories=args.category.split(",") if args.category else None,
        limit=args.limit,
        keep_workspaces=args.keep_workspaces,
        no_resume=args.no_resume,
        dual_judge=args.dual_judge,
        gateway_url=args.gateway_url,
        timeout_seconds=args.timeout,
    )

    runner = Runner(config, registry)
    run_dir = runner.run(RESULTS_BASE, run_id=args.run_id)
    print(f"\nResults saved to: {run_dir}")
    print(f"Report: {run_dir / 'report.md'}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    """Regenerate report for an existing run."""
    run_dir = RESULTS_BASE / args.run_id
    if not run_dir.exists():
        print(f"Run not found: {run_dir}", file=sys.stderr)
        return 1

    results = load_task_results(run_dir)
    suites = {r["suite"] for r in results}
    aggregated = {s: aggregate_suite(results, s) for s in suites}
    path = generate_report(run_dir, aggregated, REFERENCE_SCORES)
    print(f"Report regenerated: {path}")
    return 0


def _cmd_trend(args: argparse.Namespace) -> int:
    """Show backdata trend."""
    csv_path = RESULTS_BASE / "backdata.csv"
    if not csv_path.exists():
        print("No backdata.csv found. Run benchmarks first.", file=sys.stderr)
        return 1

    with csv_path.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if args.suite:
        rows = [r for r in rows if r.get("suite") == args.suite]

    if not rows:
        print("No matching data.")
        return 0

    # Show last 10 rows
    recent = rows[-10:]
    print(f"{'Run ID':<24} {'Suite':<15} {'Metric':<12} {'Score':<8} {'Tasks'}")
    print("-" * 70)
    for r in recent:
        print(
            f"{r.get('run_id', ''):<24} "
            f"{r.get('suite', ''):<15} "
            f"{r.get('primary_metric', ''):<12} "
            f"{r.get('primary_value', ''):<8} "
            f"{r.get('tasks_run', '')}/{r.get('tasks_total', '')}"
        )
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    """Compare two runs side by side."""
    id1, id2 = args.runs
    dir1 = RESULTS_BASE / id1
    dir2 = RESULTS_BASE / id2

    if not dir1.exists():
        print(f"Run not found: {id1}", file=sys.stderr)
        return 1
    if not dir2.exists():
        print(f"Run not found: {id2}", file=sys.stderr)
        return 1

    results1 = load_task_results(dir1)
    results2 = load_task_results(dir2)
    suites1 = {r["suite"] for r in results1}
    suites2 = {r["suite"] for r in results2}
    all_suites = sorted(suites1 | suites2)

    agg1 = {s: aggregate_suite(results1, s) for s in all_suites}
    agg2 = {s: aggregate_suite(results2, s) for s in all_suites}

    print(f"{'Suite':<15} {'Metric':<12} {id1:<12} {id2:<12} {'Delta':<8} {'Status'}")
    print("-" * 75)
    for s in all_suites:
        metric = agg1.get(s, {}).get("primary_metric", agg2.get(s, {}).get("primary_metric", ""))
        v1 = agg1.get(s, {}).get("primary_value", 0)
        v2 = agg2.get(s, {}).get("primary_value", 0)
        delta = v2 - v1
        status = "⚠️" if delta < -2.0 else "✅" if delta >= 0 else "→"
        print(f"{s:<15} {metric:<12} {v1:<12.2f} {v2:<12.2f} {delta:<+8.2f} {status}")
    return 0
