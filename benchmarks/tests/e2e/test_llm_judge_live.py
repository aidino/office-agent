"""E2E test: LLM Judge hitting real DeepSeek API.

Marked with pytest.mark.llm — skipped unless --run-llm flag is passed
or LLM_E2E env var is set.  Uses the BUB_API_KEY from office_agent/.env.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from office_bench.judges.base import JudgeContext, Rubric
from office_bench.judges.llm import LLMJudge

# Load API key from office_agent/.env if not already in env
_ENV_FILE = Path(__file__).resolve().parents[3] / "office_agent" / ".env"


def _load_env_file() -> None:
    """Parse key=value lines from .env, skipping comments."""
    if not _ENV_FILE.exists():
        return
    for line in _ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and value and key not in os.environ:
            os.environ[key] = value


_load_env_file()

_HAS_API_KEY = bool(
    os.environ.get("JUDGE_API_KEY") or os.environ.get("BUB_API_KEY")
)

pytestmark = pytest.mark.skipif(
    not _HAS_API_KEY,
    reason="No JUDGE_API_KEY or BUB_API_KEY — skip live LLM judge tests",
)


class TestLLMJudgeLive:
    """Live tests against the DeepSeek API."""

    @pytest.fixture(autouse=True)
    def _setup_judge(self) -> None:
        self.judge = LLMJudge()

    def test_judge_pass_rubric(self) -> None:
        """A clearly correct answer should receive PASS."""
        rubric = Rubric(
            id="revenue-01",
            content="Agent correctly identifies total revenue as $500K",
            weight=1.0,
        )
        context = JudgeContext(
            instruction="Analyze the spreadsheet and report total revenue.",
            agent_response=(
                "Based on my analysis of the spreadsheet, the total revenue "
                "is $500K. This is calculated by summing all quarterly "
                "revenue figures: Q1 ($100K) + Q2 ($120K) + Q3 ($130K) + "
                "Q4 ($150K) = $500K."
            ),
            file_contents={},
            file_images=[],
            file_pdfs=[],
        )
        result = self.judge.judge_rubric(rubric, context)
        assert result.rubric_id == "revenue-01"
        assert result.passed is True
        assert result.reason  # Should have a reason

    def test_judge_fail_rubric(self) -> None:
        """A clearly wrong answer should receive FAIL."""
        rubric = Rubric(
            id="revenue-02",
            content="Agent correctly identifies total revenue as $500K",
            weight=1.0,
        )
        context = JudgeContext(
            instruction="Analyze the spreadsheet and report total revenue.",
            agent_response="I don't know the answer.",
            file_contents={},
            file_images=[],
            file_pdfs=[],
        )
        result = self.judge.judge_rubric(rubric, context)
        assert result.rubric_id == "revenue-02"
        assert result.passed is False
        assert result.reason

    def test_judge_with_file_context(self) -> None:
        """Judge should consider file contents when evaluating."""
        rubric = Rubric(
            id="file-01",
            content="Agent created a budget file with correct Q1 total of $25,000",
            weight=1.0,
        )
        context = JudgeContext(
            instruction="Create a Q1 budget spreadsheet.",
            agent_response="I've created the budget spreadsheet as requested.",
            file_contents={
                "budget.xlsx": (
                    "Department | Amount\n"
                    "Marketing  | $10,000\n"
                    "Engineering | $15,000\n"
                    "Total      | $25,000"
                ),
            },
            file_images=[],
            file_pdfs=[],
        )
        result = self.judge.judge_rubric(rubric, context)
        assert result.rubric_id == "file-01"
        assert result.passed is True

    def test_judge_name_format(self) -> None:
        """Judge name follows llm:<model> pattern."""
        assert self.judge.name.startswith("llm:")
