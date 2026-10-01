from __future__ import annotations

from pathlib import Path

from office_bench.suites.base import AgentOutput, Suite, Task, TaskResult
from office_bench.judges.base import (
    JudgeBackend,
    JudgeContext,
    Rubric,
    RubricResult,
)


def test_task_is_frozen_dataclass() -> None:
    task = Task(
        suite="forte",
        task_id="finance-018",
        prompt="Analyze the spreadsheet",
        category="finance",
        input_files=[Path("input/data.xlsx")],
        metadata={"rubrics": ["r1"]},
    )
    assert task.suite == "forte"
    assert task.task_id == "finance-018"
    assert task.input_files == [Path("input/data.xlsx")]


def test_task_immutability() -> None:
    task = Task(
        suite="forte",
        task_id="t1",
        prompt="p",
        category="c",
        input_files=[],
        metadata={},
    )
    try:
        task.suite = "other"  # type: ignore[misc]
        raise AssertionError("Should have raised FrozenInstanceError")
    except AttributeError:
        pass


def test_agent_output_is_frozen() -> None:
    output = AgentOutput(
        messages=[{"role": "assistant", "content": "done"}],
        files_created=[Path("out.xlsx")],
        tool_calls=[{"name": "write_spreadsheet", "args": {}}],
        duration_seconds=12.5,
    )
    assert output.duration_seconds == 12.5
    assert len(output.files_created) == 1


def test_task_result_fields() -> None:
    result = TaskResult(
        task_id="finance-018",
        suite="forte",
        passed=False,
        score=0.67,
        breakdown={"01": 1.0, "02": 0.0},
        notes="rubric 02 failed",
        judge_backend="llm:deepseek-chat",
    )
    assert result.passed is False
    assert result.score == 0.67
    assert result.judge_backend == "llm:deepseek-chat"


def test_task_result_none_judge() -> None:
    result = TaskResult(
        task_id="t1",
        suite="officebench",
        passed=True,
        score=1.0,
        breakdown={},
        notes="",
        judge_backend=None,
    )
    assert result.judge_backend is None


def test_rubric_and_judge_context() -> None:
    rubric = Rubric(id="r1", content="Check totals", weight=1.0)
    ctx = JudgeContext(
        instruction="Analyze spreadsheet",
        agent_response="Total is 500",
        file_contents={"out.xlsx": "A1: 500"},
        file_images=[],
        file_pdfs=[],
    )
    assert rubric.weight == 1.0
    assert ctx.file_contents["out.xlsx"] == "A1: 500"


def test_rubric_result_fields() -> None:
    rr = RubricResult(
        rubric_id="r1",
        passed=True,
        confidence=None,
        reason="Totals match",
    )
    assert rr.passed is True
    assert rr.confidence is None


class _DummySuite:
    """Verify a class can satisfy the Suite protocol."""

    name = "dummy"

    def load_tasks(self) -> list[Task]:
        return []

    def setup_workspace(self, task: Task, workspace_dir: Path) -> None:
        pass

    def format_prompt(self, task: Task) -> str:
        return task.prompt

    def evaluate(
        self, task: Task, workspace_dir: Path, agent_output: AgentOutput
    ) -> TaskResult:
        return TaskResult(
            task_id=task.task_id,
            suite=self.name,
            passed=True,
            score=1.0,
            breakdown={},
            notes="",
            judge_backend=None,
        )


def test_suite_protocol_structural_typing() -> None:
    suite: Suite = _DummySuite()
    assert suite.name == "dummy"
    tasks = suite.load_tasks()
    assert tasks == []


class _DummyJudge:
    name = "dummy"

    def judge_rubric(self, rubric: Rubric, context: JudgeContext) -> RubricResult:
        return RubricResult(
            rubric_id=rubric.id,
            passed=True,
            confidence=0.9,
            reason="ok",
        )


def test_judge_backend_protocol() -> None:
    judge: JudgeBackend = _DummyJudge()
    result = judge.judge_rubric(
        Rubric(id="r1", content="check", weight=1.0),
        JudgeContext(
            instruction="i",
            agent_response="r",
            file_contents={},
            file_images=[],
            file_pdfs=[],
        ),
    )
    assert result.passed is True
    assert result.confidence == 0.9
