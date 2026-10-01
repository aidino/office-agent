"""Judge data types and JudgeBackend protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Rubric:
    """A single rubric item for LLM-as-judge evaluation."""

    id: str
    content: str
    weight: float


@dataclass(frozen=True)
class JudgeContext:
    """Context provided to a judge for rubric evaluation."""

    instruction: str
    agent_response: str
    file_contents: dict[str, str]
    file_images: list[bytes]
    file_pdfs: list[bytes]


@dataclass(frozen=True)
class RubricResult:
    """Result of judging one rubric."""

    rubric_id: str
    passed: bool
    confidence: float | None
    reason: str


@runtime_checkable
class JudgeBackend(Protocol):
    """Interface for judge backends."""

    name: str

    def judge_rubric(self, rubric: Rubric, context: JudgeContext) -> RubricResult: ...
