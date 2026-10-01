"""Orchestrator: load → filter → run → evaluate → persist → report."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from office_bench.agent_bridge import AgentBridge
from office_bench.reference import REFERENCE_SCORES
from office_bench.results import (
    aggregate_suite,
    append_backdata,
    generate_report,
    has_backdata_row,
    load_task_results,
    save_run_meta,
    save_task_result,
)
from office_bench.suites.base import AgentOutput, Suite, Task, TaskResult


@dataclass(frozen=True)
class RunConfig:
    """Configuration for a benchmark run."""

    suites: list[str]
    runs: int
    task_ids: list[str] | None
    categories: list[str] | None
    limit: int | None
    keep_workspaces: bool
    no_resume: bool
    dual_judge: bool
    gateway_url: str
    timeout_seconds: int


class Runner:
    """Benchmark run orchestrator."""

    def __init__(
        self,
        config: RunConfig,
        suite_registry: dict[str, Suite],
        bridge: AgentBridge | None = None,
    ) -> None:
        self._config = config
        self._suites = suite_registry
        self._bridge = bridge or AgentBridge(
            gateway_url=config.gateway_url,
            timeout_seconds=config.timeout_seconds,
        )

    def run(self, results_base: Path, run_id: str | None = None) -> Path:
        """Execute the full benchmark pipeline. Returns the run directory."""
        if run_id is None:
            run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")

        run_dir = results_base / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Save meta
        meta = self._resume_meta(
            run_dir,
            {
                "run_id": run_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "git_commit": self._git_commit(),
                "agent_version": self._agent_version(),
                "model": os.environ.get("BUB_MODEL", "deepseek-flash"),
                "suites": self._config.suites,
                "runs": self._config.runs,
            },
        )
        save_run_meta(run_dir, meta)

        # Run each suite. Unregistered names are warned about and skipped —
        # they must never reach aggregation, or a typo would append a
        # permanent 0/0 "n/a" row to the append-only backdata CSV.
        executed: list[Suite] = []
        for suite_name in self._config.suites:
            suite = self._suites.get(suite_name)
            if suite is None:
                print(
                    f"warning: suite '{suite_name}' not registered — skipped",
                    file=sys.stderr,
                )
                continue
            executed.append(suite)
            self._run_suite(suite, run_dir)

        # Aggregate and report — keyed by suite.name, the name results are
        # persisted under (which may differ from the registry key).
        all_results = load_task_results(run_dir)
        aggregated: dict[str, dict] = {}
        for suite in executed:
            agg = aggregate_suite(all_results, suite.name)
            aggregated[suite.name] = agg

            # Append backdata row — idempotent on resume: never write a
            # second row for the same (run_id, suite) in the append-only CSV
            backdata_path = results_base / "backdata.csv"
            if not has_backdata_row(backdata_path, run_id, suite.name):
                append_backdata(
                    backdata_path,
                    {
                        "run_id": run_id,
                        "timestamp": meta["timestamp"],
                        "git_commit": meta["git_commit"],
                        "agent_version": meta["agent_version"],
                        "model": meta["model"],
                        "suite": suite.name,
                        "tasks_total": agg.get("tasks_total", 0),
                        "tasks_run": agg.get("tasks_run", 0),
                        "primary_metric": agg.get("primary_metric", ""),
                        "primary_value": agg.get("primary_value", 0),
                        "secondary_metrics": "{}",
                    },
                )

        generate_report(run_dir, aggregated, REFERENCE_SCORES)
        return run_dir

    @staticmethod
    def _resume_meta(run_dir: Path, fresh: dict) -> dict:
        """Merge run metadata on resume, preserving first-run provenance.

        The backdata row for an existing (run_id, suite) is frozen at the
        first run's timestamp/commit; overwriting meta.json with the
        resuming invocation's values would make the two records disagree.
        A previous meta that is missing or unreadable is replaced by the
        fresh one.
        """
        meta_path = run_dir / "meta.json"
        if not meta_path.exists():
            return fresh
        try:
            previous = json.loads(meta_path.read_text())
            if not isinstance(previous, dict):
                raise ValueError("meta.json is not an object")
        except (json.JSONDecodeError, OSError, ValueError):
            return fresh
        previous["resumed_at"] = fresh["timestamp"]
        previous["resumed_commit"] = fresh["git_commit"]
        return previous

    def _run_suite(self, suite: Suite, run_dir: Path) -> None:
        """Load, filter, and run all tasks for one suite.

        One crashing task (setup, bridge call, or evaluate) is isolated:
        it is recorded as a failed result and the run continues — the same
        philosophy the bridge applies to gateway errors one layer down.
        """
        tasks = suite.load_tasks()
        tasks = self._filter_tasks(tasks)

        for task in tasks:
            for run_num in range(1, self._config.runs + 1):
                result_path = (
                    run_dir / suite.name / f"{task.task_id}_run{run_num}.json"
                )
                if (
                    result_path.exists()
                    and not self._config.no_resume
                    and self._is_complete_result(result_path)
                ):
                    continue  # resume: skip completed
                if result_path.exists():
                    # Crash-truncated garbage — replace, never skip.
                    result_path.unlink()

                workspace = Path(tempfile.mkdtemp(prefix=f"bench_{task.task_id}_"))
                agent_output = AgentOutput(
                    messages=[], files_created=[], tool_calls=[],
                    duration_seconds=0.0,
                )
                try:
                    try:
                        suite.setup_workspace(task, workspace)
                        turn_prompts = task.metadata.get("turn_prompts")
                        if isinstance(turn_prompts, list) and len(turn_prompts) > 1:
                            # Multi-turn session (e.g. PPTC): same thread, all turns
                            agent_output = self._bridge.run_session(
                                list(turn_prompts), workspace
                            )
                        else:
                            prompt = suite.format_prompt(task)
                            agent_output = self._bridge.run_task(prompt, workspace)
                        result = suite.evaluate(task, workspace, agent_output)
                    finally:
                        if not self._config.keep_workspaces:
                            shutil.rmtree(workspace, ignore_errors=True)
                except Exception as exc:  # noqa: BLE001 — isolate one task
                    print(
                        f"warning: task {suite.name}/{task.task_id} "
                        f"run {run_num} crashed: {exc!r} — recorded as failed",
                        file=sys.stderr,
                    )
                    result = TaskResult(
                        task_id=task.task_id,
                        suite=suite.name,
                        passed=False,
                        score=0.0,
                        breakdown={},
                        notes=f"runner: task crashed: {exc!r}",
                        judge_backend=None,
                    )
                save_task_result(run_dir, result, run_num, agent_output)

    @staticmethod
    def _is_complete_result(path: Path) -> bool:
        """True only if a result file parses and carries a task_id.

        Bare existence is not completion: a crash mid-write leaves a
        truncated file that aggregation (Task 4) already drops — skipping
        it on resume would silently lose the task from the run. Mirrors
        the task_id guard Task 4 added to ``_aggregate_forte``.
        """
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return False
        return isinstance(data, dict) and bool(data.get("task_id"))

    def _filter_tasks(self, tasks: list[Task]) -> list[Task]:
        """Apply task_ids, categories, and limit filters."""
        filtered = tasks

        if self._config.task_ids is not None:
            allowed = set(self._config.task_ids)
            filtered = [t for t in filtered if t.task_id in allowed]

        if self._config.categories is not None:
            allowed_cats = set(self._config.categories)
            filtered = [t for t in filtered if t.category in allowed_cats]

        if self._config.limit is not None:
            filtered = filtered[: self._config.limit]

        return filtered

    @staticmethod
    def _git_commit() -> str:
        """Return short SHA of HEAD, or empty string."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            return ""

    @staticmethod
    def _agent_version() -> str:
        """Version of the office_agent package, from its pyproject.toml."""
        # benchmarks/src/office_bench/runner.py → parents[3] is the repo root
        pyproject = (
            Path(__file__).resolve().parents[3] / "office_agent" / "pyproject.toml"
        )
        try:
            with pyproject.open("rb") as f:
                return str(tomllib.load(f)["project"]["version"])
        except (OSError, KeyError, tomllib.TOMLDecodeError):
            return ""
