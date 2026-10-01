"""FORTE suite adapter — native grade_one + LLM judge evaluation."""

from __future__ import annotations

import importlib.util
import logging
import re
import shutil
from pathlib import Path

import yaml

from office_bench.judges.base import JudgeContext, Rubric
from office_bench.judges.llm import LLMJudge
from office_bench.suites.base import AgentOutput, Task, TaskResult

_log = logging.getLogger(__name__)


class ForteSuite:
    """Adapter for the FORTE benchmark (AGI-Eval-Official/FORTE).

    Parses task markdown with YAML frontmatter, delegates automated grading
    to FORTE's own ``judge/grade.py`` from the submodule, and integrates the
    LLM judge backend for ``llm_judge`` and ``hybrid`` tasks.
    """

    name = "forte"

    def __init__(self, repo_dir: Path, judge: LLMJudge | None = None) -> None:
        self._repo_dir = repo_dir
        self._judge = judge or LLMJudge()

    # ── Suite protocol ──────────────────────────────────────────────

    def load_tasks(self) -> list[Task]:
        """Parse ``data/tasks/*.md`` — YAML frontmatter + ``## Prompt`` section."""
        tasks_dir = self._repo_dir / "data" / "tasks"
        if not tasks_dir.exists():
            return []

        tasks: list[Task] = []
        for md_file in sorted(tasks_dir.glob("*.md")):
            try:
                content = md_file.read_text()
                frontmatter, prompt = self._parse_task_md(content)
            except (OSError, ValueError):
                _log.warning("skipping unparseable task file: %s", md_file)
                continue

            task_id = frontmatter.get("id", md_file.stem)
            category = frontmatter.get("category", "unknown")
            rubrics = frontmatter.get("rubrics", [])
            workspace_files = frontmatter.get("workspace_files", [])

            # Resolve input file paths
            assets_dir = self._repo_dir / "data" / "assets" / task_id / "input"
            input_files: list[Path] = []
            for wf in workspace_files:
                fp = assets_dir / wf
                if fp.exists():
                    input_files.append(fp)

            tasks.append(Task(
                suite=self.name,
                task_id=task_id,
                prompt=prompt,
                category=category,
                input_files=input_files,
                metadata={
                    "rubrics": rubrics,
                    "grading_type": frontmatter.get("grading_type", "automated"),
                    "timeout_seconds": frontmatter.get("timeout_seconds", 600),
                    "solution_files": frontmatter.get("solution_files", []),
                },
            ))
        return tasks

    def setup_workspace(self, task: Task, workspace_dir: Path) -> None:
        """Copy input/asset files into the workspace."""
        for src in task.input_files:
            dst = workspace_dir / src.name
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)

    def format_prompt(self, task: Task) -> str:
        """Return the task prompt."""
        return task.prompt

    def evaluate(
        self,
        task: Task,
        workspace_dir: Path,
        agent_output: AgentOutput,
    ) -> TaskResult:
        """Grade via FORTE's native grade_one and/or the LLM judge."""
        grading_type = task.metadata.get("grading_type", "automated")
        rubrics = task.metadata.get("rubrics", [])

        agent_response = (
            agent_output.messages[-1].get("content", "")
            if agent_output.messages
            else ""
        )

        if not rubrics:
            # Nothing to grade — NEVER award an unearned pass
            return self._error_result(
                task, "no rubrics defined — task not evaluable"
            )

        breakdown: dict[str, float] = {}
        all_passed = True
        backends: list[str] = []

        if grading_type in ("automated", "hybrid"):
            grade_one = self._load_grader()
            if grade_one is None:
                return self._error_result(
                    task,
                    "FORTE judge.grade not importable from submodule",
                )
            try:
                auto_passed, auto_detail = grade_one(
                    instruction=task.prompt,
                    agent_response=agent_response,
                    rubrics=rubrics,
                    workspace_dir=workspace_dir,
                    solution_dir=self._solution_dir(task),
                )
            except TypeError as e:
                return self._error_result(
                    task, f"grade_one signature mismatch: {e}"
                )
            if isinstance(auto_detail, dict):
                breakdown.update(auto_detail)
            else:
                breakdown["automated"] = 1.0 if auto_passed else 0.0
            if not auto_passed:
                all_passed = False
            backends.append("deterministic")

        if grading_type in ("llm_judge", "hybrid"):
            context = JudgeContext(
                instruction=task.prompt,
                agent_response=agent_response,
                file_contents=self._read_workspace_text(workspace_dir),
                file_images=[],
                file_pdfs=[],
            )
            for rubric_data in rubrics:
                rubric = Rubric(
                    id=rubric_data["id"],
                    content=rubric_data["content"],
                    weight=rubric_data.get("weight", 1.0),
                )
                result = self._judge.judge_rubric(rubric, context)
                breakdown[rubric.id] = 1.0 if result.passed else 0.0
                if not result.passed:
                    all_passed = False
            backends.append(self._judge.name)

        # FORTE: all-or-nothing per task
        failed_ids = [k for k, v in breakdown.items() if v == 0.0]
        return TaskResult(
            task_id=task.task_id,
            suite=self.name,
            passed=all_passed,
            score=1.0 if all_passed else 0.0,
            breakdown=breakdown,
            notes=(
                f"Failed rubrics: {failed_ids}" if failed_ids
                else "All rubrics passed"
            ),
            judge_backend="+".join(backends) if backends else None,
        )

    # ── internals ───────────────────────────────────────────────────

    def _load_grader(self):
        """Import judge/grade.py from the FORTE submodule."""
        grade_path = self._repo_dir / "judge" / "grade.py"
        if not grade_path.exists():
            return None
        spec = importlib.util.spec_from_file_location(
            f"forte_grade_{abs(hash(str(self._repo_dir)))}", grade_path
        )
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return getattr(module, "grade_one", None)

    def _solution_dir(self, task: Task) -> Path | None:
        """Read-only solution dir mounted for the judge, never the agent."""
        candidate = self._repo_dir / "data" / "solutions" / task.task_id
        return candidate if candidate.exists() else None

    @staticmethod
    def _read_workspace_text(workspace_dir: Path) -> dict[str, str]:
        file_contents: dict[str, str] = {}
        for f in workspace_dir.iterdir():
            if f.is_file() and f.suffix in (".txt", ".csv", ".md", ".json"):
                try:
                    file_contents[f.name] = f.read_text(errors="replace")[:10_000]
                except OSError:
                    pass
        return file_contents

    def _error_result(self, task: Task, notes: str) -> TaskResult:
        return TaskResult(
            task_id=task.task_id,
            suite=self.name,
            passed=False,
            score=0.0,
            breakdown={},
            notes=notes,
            judge_backend="deterministic",
        )

    @staticmethod
    def _parse_task_md(content: str) -> tuple[dict, str]:
        """Parse YAML frontmatter and ``## Prompt`` section from task markdown."""
        # Extract YAML frontmatter between --- delimiters
        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        if not fm_match:
            raise ValueError("No YAML frontmatter found")

        frontmatter = yaml.safe_load(fm_match.group(1)) or {}
        body = content[fm_match.end():]

        # Extract ## Prompt section
        prompt_match = re.search(r"##\s+Prompt\s*\n(.*?)(?:\n##|\Z)", body, re.DOTALL)
        prompt = prompt_match.group(1).strip() if prompt_match else body.strip()

        return frontmatter, prompt
