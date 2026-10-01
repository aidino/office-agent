"""Tests for the FORTE suite adapter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from office_bench.judges.base import RubricResult
from office_bench.suites.forte import ForteSuite
from office_bench.suites.base import AgentOutput, Task

FIXTURES = Path(__file__).parent / "fixtures" / "forte"


@pytest.fixture(autouse=True)
def _create_fixture_files() -> None:
    """Ensure fixture files exist."""
    assets_dir = FIXTURES / "data" / "assets" / "finance-001" / "input"
    assets_dir.mkdir(parents=True, exist_ok=True)
    data_file = assets_dir / "data.xlsx"
    if not data_file.exists():
        data_file.write_bytes(b"fake xlsx")


@pytest.fixture()
def suite() -> ForteSuite:
    return ForteSuite(FIXTURES)


def _make_output() -> AgentOutput:
    return AgentOutput(
        messages=[{"role": "assistant", "content": "Total revenue is $500K. Q1: $100K, Q2: $120K, Q3: $130K, Q4: $150K."}],
        files_created=[],
        tool_calls=[],
        duration_seconds=10.0,
    )


def test_load_tasks(suite: ForteSuite) -> None:
    tasks = suite.load_tasks()
    assert len(tasks) == 3
    ids = {t.task_id for t in tasks}
    assert "finance-001" in ids
    assert "hr-001" in ids
    assert "hr-002" in ids


def test_task_fields(suite: ForteSuite) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "finance-001")
    assert t.suite == "forte"
    assert t.category == "finance"
    assert "Analyze" in t.prompt
    assert len(t.metadata.get("rubrics", [])) == 2


def test_setup_workspace(suite: ForteSuite, tmp_path: Path) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "finance-001")
    suite.setup_workspace(t, tmp_path)
    assert (tmp_path / "data.xlsx").exists()


def test_format_prompt(suite: ForteSuite) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "finance-001")
    prompt = suite.format_prompt(t)
    assert "Analyze" in prompt
    assert "data.xlsx" in prompt


def _make_output_with(text: str) -> AgentOutput:
    return AgentOutput(
        messages=[{"role": "assistant", "content": text}],
        files_created=[],
        tool_calls=[],
        duration_seconds=10.0,
    )


def test_evaluate_automated_delegates_to_grade_one(
    suite: ForteSuite, tmp_path: Path
) -> None:
    """automated WITH rubrics must go through judge.grade.grade_one."""
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "hr-002")

    result = suite.evaluate(
        t, tmp_path, _make_output_with("Employees in department A: Alice, Bob")
    )
    assert result.passed is True
    assert result.score == 1.0
    assert result.judge_backend == "deterministic"
    assert result.breakdown.get("01") == 1.0

    result_fail = suite.evaluate(
        t, tmp_path, _make_output_with("No idea, sorry")
    )
    assert result_fail.passed is False
    assert result_fail.score == 0.0


def test_evaluate_automated_without_rubrics_not_evaluable(
    suite: ForteSuite, tmp_path: Path
) -> None:
    """No rubrics + automated = not evaluable — must NOT auto-pass."""
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "hr-001")
    result = suite.evaluate(t, tmp_path, _make_output())
    assert result.passed is False
    assert result.score == 0.0
    assert "not evaluable" in result.notes.lower()


def test_evaluate_grader_missing_fails_cleanly(tmp_path: Path) -> None:
    """A repo dir without judge/grade.py must fail with an explicit error."""
    bare = tmp_path / "bare_forte"  # no judge/ package inside
    bare.mkdir()
    suite = ForteSuite(bare)
    tasks = suite.load_tasks()
    assert tasks == []  # nothing to load — construct a task manually

    task = Task(
        suite="forte",
        task_id="x-1",
        prompt="p",
        category="c",
        input_files=[],
        metadata={"rubrics": [{"id": "01", "content": "r", "weight": 1.0}],
                  "grading_type": "automated"},
    )
    result = suite.evaluate(task, tmp_path, _make_output())
    assert result.passed is False
    assert "grade" in result.notes.lower()


def test_evaluate_llm_judge_delegates_to_judge_backend(
    suite: ForteSuite, tmp_path: Path
) -> None:
    """llm_judge grading type must delegate rubrics to the LLM judge."""
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "finance-001")
    assert t.metadata["grading_type"] == "llm_judge"

    # Inject a mock judge that always passes
    mock_judge = MagicMock()
    mock_judge.name = "llm:test-model"
    mock_judge.judge_rubric.return_value = RubricResult(
        rubric_id="01", passed=True, confidence=0.95, reason="ok"
    )
    suite._judge = mock_judge  # type: ignore[attr-defined]

    result = suite.evaluate(t, tmp_path, _make_output())
    assert mock_judge.judge_rubric.call_count == 2  # two rubrics
    assert result.judge_backend == "llm:test-model"
    assert result.passed is True
    assert result.score == 1.0


def test_evaluate_llm_judge_fails_when_rubric_fails(
    suite: ForteSuite, tmp_path: Path
) -> None:
    """If LLM judge fails a rubric, the task must fail."""
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "finance-001")

    mock_judge = MagicMock()
    mock_judge.name = "llm:test-model"
    mock_judge.judge_rubric.return_value = RubricResult(
        rubric_id="01", passed=False, confidence=0.3, reason="wrong"
    )
    suite._judge = mock_judge  # type: ignore[attr-defined]

    result = suite.evaluate(t, tmp_path, _make_output())
    assert result.passed is False
    assert result.score == 0.0
