"""Tests for the OfficeBench suite adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from office_bench.suites.officebench import OfficeBenchSuite
from office_bench.suites.base import AgentOutput

FIXTURES = Path(__file__).parent / "fixtures" / "officebench"


@pytest.fixture()
def suite() -> OfficeBenchSuite:
    return OfficeBenchSuite(FIXTURES)


def _make_output(files: list[str] | None = None) -> AgentOutput:
    return AgentOutput(
        messages=[{"role": "assistant", "content": "done"}],
        files_created=[Path(f) for f in (files or [])],
        tool_calls=[],
        duration_seconds=3.0,
    )


# ── load_tasks ──────────────────────────────────────────────────────

def test_load_tasks(suite: OfficeBenchSuite) -> None:
    tasks = suite.load_tasks()
    assert len(tasks) == 2
    ids = {t.task_id for t in tasks}
    assert "1-1" in ids
    assert "2-1" in ids


def test_load_tasks_fields(suite: OfficeBenchSuite) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "1-1")
    assert t.suite == "officebench"
    assert t.category == "1-app"
    assert "budget" in t.prompt.lower()


def test_load_tasks_empty_dir(tmp_path: Path) -> None:
    """Suite pointed at a dir with no tasks/ subdirectory returns []."""
    s = OfficeBenchSuite(tmp_path)
    assert s.load_tasks() == []


# ── setup_workspace ─────────────────────────────────────────────────

def test_setup_workspace_copies_testbed(suite: OfficeBenchSuite, tmp_path: Path) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "1-1")
    suite.setup_workspace(t, tmp_path)
    assert (tmp_path / "input.txt").exists()


# ── format_prompt ───────────────────────────────────────────────────

def test_format_prompt(suite: OfficeBenchSuite) -> None:
    tasks = suite.load_tasks()
    t = tasks[0]
    prompt = suite.format_prompt(t)
    assert len(prompt) > 0
    assert t.prompt in prompt


# ── evaluate (deterministic delegation) ─────────────────────────────

def test_evaluate_file_exist_pass(suite: OfficeBenchSuite, tmp_path: Path) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "1-1")
    (tmp_path / "budget.xlsx").write_bytes(b"fake")
    output = _make_output(["budget.xlsx"])
    result = suite.evaluate(t, tmp_path, output)
    assert result.passed is True
    assert result.score == 1.0
    assert result.judge_backend == "deterministic"


def test_evaluate_file_exist_fail(suite: OfficeBenchSuite, tmp_path: Path) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "1-1")
    output = _make_output()
    result = suite.evaluate(t, tmp_path, output)
    assert result.passed is False
    assert result.score == 0.0


def test_evaluate_contain_pass(suite: OfficeBenchSuite, tmp_path: Path) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "2-1")
    (tmp_path / "summary.txt").write_text("The total is 100")
    output = _make_output(["summary.txt"])
    result = suite.evaluate(t, tmp_path, output)
    assert result.passed is True


def test_evaluate_contain_fail(suite: OfficeBenchSuite, tmp_path: Path) -> None:
    tasks = suite.load_tasks()
    t = next(t for t in tasks if t.task_id == "2-1")
    (tmp_path / "summary.txt").write_text("No match here")
    output = _make_output(["summary.txt"])
    result = suite.evaluate(t, tmp_path, output)
    assert result.passed is False


def test_evaluate_unknown_function(suite: OfficeBenchSuite, tmp_path: Path) -> None:
    """Unknown eval function → passed=False with explicit error note."""
    from office_bench.suites.base import Task

    t = Task(
        suite="officebench",
        task_id="bad-1",
        prompt="x",
        category="1-app",
        input_files=[],
        metadata={
            "eval_config": {
                "function": "nonexistent_function",
                "args": {},
            },
            "task_dir": str(tmp_path),
        },
    )
    result = suite.evaluate(t, tmp_path, _make_output())
    assert result.passed is False
    assert "nonexistent_function" in result.notes.lower() or "unknown" in result.notes.lower()


def test_evaluate_native_exception(tmp_path: Path) -> None:
    """Native eval function that raises → passed=False, error captured in notes."""
    # Create a repo dir with a broken evaluation.py
    eval_dir = tmp_path / "repo"
    eval_dir.mkdir()
    tasks_dir = eval_dir / "tasks" / "1" / "subtasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "1-1.json").write_text(
        '{"task_id":"1-1","instruction":"x","app_count":1,'
        '"eval_config":{"function":"evaluate_boom","args":{}}}'
    )
    (eval_dir / "evaluation.py").write_text(
        "def evaluate_boom(args, workspace_dir):\n"
        "    raise RuntimeError('kaboom')\n"
    )

    s = OfficeBenchSuite(eval_dir)
    tasks = s.load_tasks()
    result = s.evaluate(tasks[0], tmp_path, _make_output())
    assert result.passed is False
    assert "kaboom" in result.notes


def test_evaluate_missing_evaluation_module(tmp_path: Path) -> None:
    """Suite pointed at a repo dir without evaluation.py → passed=False."""
    repo_dir = tmp_path / "repo"
    tasks_dir = repo_dir / "tasks" / "1" / "subtasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "1-1.json").write_text(
        '{"task_id":"1-1","instruction":"x","app_count":1,'
        '"eval_config":{"function":"evaluate_file_exist","args":{"file_path":"f.txt"}}}'
    )

    s = OfficeBenchSuite(repo_dir)
    tasks = s.load_tasks()
    result = s.evaluate(tasks[0], tmp_path, _make_output())
    assert result.passed is False
    assert "not found" in result.notes.lower()


def test_suite_satisfies_protocol(suite: OfficeBenchSuite) -> None:
    """OfficeBenchSuite is a structural subtype of Suite."""
    from office_bench.suites.base import Suite

    assert isinstance(suite, Suite)
