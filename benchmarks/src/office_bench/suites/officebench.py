"""OfficeBench suite adapter — deterministic evaluation via the benchmark's
native evaluation module."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
from types import ModuleType
from typing import Any

from office_bench.suites.base import AgentOutput, Task, TaskResult


class OfficeBenchSuite:
    """Adapter for the OfficeBench benchmark (zlwang-cs/OfficeBench).

    Loads task definitions from ``tasks/*/subtasks/*.json``, copies testbed
    files into per-task workspaces, and delegates evaluation to the
    benchmark's native ``evaluation.py`` module loaded via importlib (spec
    §5.3: "keep their evaluation logic").
    """

    name = "officebench"

    def __init__(self, repo_dir: Path) -> None:
        self._repo_dir = repo_dir

    # ── Suite protocol ──────────────────────────────────────────────

    def load_tasks(self) -> list[Task]:
        """Scan ``tasks/*/subtasks/*.json`` for task definitions."""
        tasks_dir = self._repo_dir / "tasks"
        if not tasks_dir.exists():
            return []

        results: list[Task] = []
        for task_dir in sorted(tasks_dir.iterdir()):
            if not task_dir.is_dir():
                continue
            subtasks_dir = task_dir / "subtasks"
            if not subtasks_dir.exists():
                continue
            for json_file in sorted(subtasks_dir.glob("*.json")):
                task = self._parse_subtask(json_file, task_dir)
                if task is not None:
                    results.append(task)
        return results

    def setup_workspace(self, task: Task, workspace_dir: Path) -> None:
        """Copy testbed files into the workspace."""
        for src in task.input_files:
            dst = workspace_dir / src.name
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)

    def format_prompt(self, task: Task) -> str:
        """Return the task instruction as the prompt."""
        return task.prompt

    def evaluate(
        self,
        task: Task,
        workspace_dir: Path,
        agent_output: AgentOutput,
    ) -> TaskResult:
        """Delegate to OfficeBench's native evaluation module (spec §5.3)."""
        eval_config = task.metadata.get("eval_config", {})
        func_name: str = eval_config.get("function", "")
        func_args: dict[str, Any] = eval_config.get("args", {})

        module = self._load_native_evaluation()
        if module is None:
            return self._error_result(
                task,
                f"Native evaluation module not found: "
                f"{self._repo_dir / 'evaluation.py'}",
                func_name,
            )

        func = getattr(module, func_name, None)
        if not callable(func):
            return self._error_result(
                task, f"Unknown eval function: {func_name}", func_name
            )

        try:
            passed = bool(func(func_args, workspace_dir))
        except Exception as exc:
            return self._error_result(
                task, f"{func_name} raised: {exc}", func_name
            )

        return TaskResult(
            task_id=task.task_id,
            suite=self.name,
            passed=passed,
            score=1.0 if passed else 0.0,
            breakdown={func_name: 1.0 if passed else 0.0},
            notes=f"{func_name} → {'PASS' if passed else 'FAIL'}",
            judge_backend="deterministic",
        )

    # ── internals ───────────────────────────────────────────────────

    def _parse_subtask(
        self, json_file: Path, task_dir: Path
    ) -> Task | None:
        try:
            data = json.loads(json_file.read_text())
        except (json.JSONDecodeError, OSError):
            return None

        app_count = data.get("app_count", 1)
        testbed_dir = task_dir / "testbed"
        input_files = (
            sorted(testbed_dir.iterdir()) if testbed_dir.exists() else []
        )

        return Task(
            suite=self.name,
            task_id=data.get("task_id", json_file.stem),
            prompt=data.get("instruction", ""),
            category=f"{app_count}-app",
            input_files=input_files,
            metadata={
                "eval_config": data.get("eval_config", {}),
                "task_dir": str(task_dir),
            },
        )

    def _load_native_evaluation(self) -> ModuleType | None:
        """Import the benchmark's ``evaluation.py`` from the repo dir."""
        eval_path = self._repo_dir / "evaluation.py"
        if not eval_path.exists():
            return None
        spec = importlib.util.spec_from_file_location(
            f"officebench_eval_{abs(hash(str(self._repo_dir)))}",
            eval_path,
        )
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module

    def _error_result(
        self, task: Task, notes: str, func_name: str
    ) -> TaskResult:
        return TaskResult(
            task_id=task.task_id,
            suite=self.name,
            passed=False,
            score=0.0,
            breakdown={func_name: 0.0},
            notes=notes,
            judge_backend="deterministic",
        )
