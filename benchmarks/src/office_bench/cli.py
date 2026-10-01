"""CLI: run, report, list, trend, compare, setup."""

from __future__ import annotations

import argparse
import csv
import os
import shutil
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


def _split_csv(value: str | None) -> list[str] | None:
    """Split a comma-separated CLI flag: strip whitespace, drop empties.

    ``--task-id "t1, t2"`` or a stray trailing comma must never silently
    scope a run — a filter matching fewer tasks than intended is recorded
    permanently in the append-only backdata CSV.
    """
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def _positive_int(value: str) -> int:
    """argparse type for --runs/--limit: integers >= 1 only.

    ``--runs 0`` is not operator intent — it appends a permanent 0/0 row
    to the backdata CSV.
    """
    try:
        ivalue = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {value!r}")
    if ivalue < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {ivalue}")
    return ivalue


def _result_rows(results: list) -> list[dict]:
    """Drop stray non-result JSON: anything not a dict carrying a suite.

    ``load_task_results`` ingests any parseable JSON in a run dir, and
    ``aggregate_suite`` ``.get``s every row — so an operator's notes.json
    or a snippet file would otherwise crash the reporting commands. One
    guard here keeps report/compare tolerant of alien files.
    """
    return [r for r in results if isinstance(r, dict) and r.get("suite")]


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
    p_run.add_argument("--runs", type=_positive_int, default=1, help="Number of runs per task")
    p_run.add_argument("--task-id", default=None, help="Comma-separated task IDs")
    p_run.add_argument("--category", default=None, help="Comma-separated categories")
    p_run.add_argument("--limit", type=_positive_int, default=None, help="Max tasks per suite")
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


def _setup_submodules() -> bool:
    """Step 1/6: clone/update git submodules. Return True on success."""
    print("Step 1/6: Updating git submodules...")
    try:
        result = subprocess.run(
            ["git", "submodule", "update", "--init", "--recursive"],
            check=False,
        )
    except OSError as exc:
        print(f"error: could not run git: {exc}", file=sys.stderr)
        return False
    if result.returncode != 0:
        print(
            f"error: git submodule update failed (exit {result.returncode})",
            file=sys.stderr,
        )
        return False
    return True


def _setup_check_dataset() -> None:
    """Step 2/6: check SpreadsheetBench 2 HuggingFace dataset."""
    print("Step 2/6: Checking SpreadsheetBench 2 dataset...")
    dataset_dir = DATA_BASE / "datasets" / "spreadsheet"
    if not dataset_dir.exists():
        print(f"  → Download KAKA22/SpreadsheetBench-v2 to {dataset_dir}")
        print(
            "  → Run: huggingface-cli download KAKA22/SpreadsheetBench-v2"
            f" --local-dir {dataset_dir}"
        )
    else:
        print("  → Dataset already present.")


def _setup_check_pptc() -> None:
    """Step 3/6: check PPTC label files."""
    print("Step 3/6: Checking PPTC label files...")
    pptc_dir = DATA_BASE / "PPTC"
    if pptc_dir.exists():
        label_dirs = list(pptc_dir.glob("PPT_label_*"))
        if not label_dirs:
            print(
                "  → Generate labels:"
                " cd data/benchmarks/PPTC && python main.py --prepare"
            )
        else:
            print("  → Label files already present.")
    else:
        print("  → PPTC submodule not cloned yet.")


def _setup_check_libreoffice() -> None:
    """Step 4/6: check LibreOffice availability."""
    print("Step 4/6: Checking LibreOffice...")
    if shutil.which("libreoffice") is None:
        print("  ⚠️  LibreOffice not found. Required for SpreadsheetBench 2 recalc.")
    else:
        print("  → LibreOffice found.")


def _setup_check_forte() -> None:
    """Step 5/6: check FORTE judge module directory."""
    print("Step 5/6: Checking FORTE judge module...")
    forte_judge = DATA_BASE / "FORTE" / "judge"
    if forte_judge.exists():
        print("  → FORTE judge directory found.")
    else:
        print("  → FORTE submodule not ready. Judge won't work until cloned.")


def _setup_check_api_keys() -> None:
    """Step 6/6: check judge API keys."""
    print("Step 6/6: Checking API keys...")
    api_key = os.environ.get("JUDGE_API_KEY") or os.environ.get("BUB_API_KEY", "")
    if api_key:
        print("  → JUDGE_API_KEY / BUB_API_KEY set.")
    else:
        print(
            "  ⚠️  Neither JUDGE_API_KEY nor BUB_API_KEY is set."
            " LLM judge won't work."
        )


def _cmd_setup(_args: argparse.Namespace) -> int:
    """Clone submodules, download datasets, and verify prerequisites."""
    if not _setup_submodules():
        return 1
    _setup_check_dataset()
    _setup_check_pptc()
    _setup_check_libreoffice()
    _setup_check_forte()
    _setup_check_api_keys()
    print("\nSetup complete.")
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
        if not suite_names:
            print(
                "error: no suite adapters available — nothing to run",
                file=sys.stderr,
            )
            return 1
    else:
        suite_names = _split_csv(args.suite) or []
        if not suite_names:
            print(
                f"error: --suite contains no valid names: {args.suite!r}",
                file=sys.stderr,
            )
            return 1

    task_ids = _split_csv(args.task_id)
    if args.task_id and not task_ids:
        print(
            f"error: --task-id contains no valid ids: {args.task_id!r}",
            file=sys.stderr,
        )
        return 1
    categories = _split_csv(args.category)
    if args.category and not categories:
        print(
            f"error: --category contains no valid names: {args.category!r}",
            file=sys.stderr,
        )
        return 1

    config = RunConfig(
        suites=suite_names,
        runs=args.runs,
        task_ids=task_ids,
        categories=categories,
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

    results = _result_rows(load_task_results(run_dir))
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
    if len(rows) > len(recent):
        print(f"(showing {len(recent)} most recent of {len(rows)} rows)")
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

    results1 = _result_rows(load_task_results(dir1))
    results2 = _result_rows(load_task_results(dir2))
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
        in1, in2 = s in suites1, s in suites2
        col1 = f"{v1:.2f}" if in1 else "not run"
        col2 = f"{v2:.2f}" if in2 else "not run"
        if not (in1 and in2):
            # Absent from one side: no delta — a fabricated one would read
            # as a regression or improvement that never happened.
            print(f"{s:<15} {metric:<12} {col1:<12} {col2:<12} {'—':<8}")
            continue
        delta = v2 - v1
        status = "⚠️" if delta < -2.0 else "✅" if delta >= 0 else "→"
        print(f"{s:<15} {metric:<12} {col1:<12} {col2:<12} {delta:<+8.2f} {status}")
    return 0
