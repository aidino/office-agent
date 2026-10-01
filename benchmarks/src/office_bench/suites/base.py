"""Shared data types and Suite protocol for all benchmark adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Task:
    """A single benchmark task."""

    suite: str
    task_id: str
    prompt: str
    category: str
    input_files: list[Path]
    metadata: dict


@dataclass(frozen=True)
class AgentOutput:
    """Captured output from an agent run."""

    messages: list[dict]
    files_created: list[Path]
    tool_calls: list[dict]
    duration_seconds: float


@dataclass(frozen=True)
class TaskResult:
    """Evaluation result for a single task."""

    task_id: str
    suite: str
    passed: bool
    score: float
    breakdown: dict
    notes: str
    judge_backend: str | None


@runtime_checkable
class Suite(Protocol):
    """Interface that every benchmark adapter must satisfy."""

    name: str

    def load_tasks(self) -> list[Task]: ...

    def setup_workspace(self, task: Task, workspace_dir: Path) -> None: ...

    def format_prompt(self, task: Task) -> str: ...

    def evaluate(
        self, task: Task, workspace_dir: Path, agent_output: AgentOutput
    ) -> TaskResult: ...
