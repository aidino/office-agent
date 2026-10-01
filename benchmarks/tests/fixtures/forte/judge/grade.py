"""Fixture stand-in for FORTE's judge.grade module.

Mirrors the upstream grade_one API the adapter calls. After `setup` clones
the real submodule, verify the real signature (Step 7 investigation) and
keep this fixture in sync.
"""

from __future__ import annotations

from pathlib import Path


def grade_one(
    instruction: str,
    agent_response: str,
    rubrics: list[dict],
    workspace_dir: Path | None = None,
    solution_dir: Path | None = None,
) -> tuple[bool, dict]:
    """Deterministic fake: passes when the response mentions 'department A'."""
    passed = "department a" in agent_response.lower()
    return passed, {"01": 1.0 if passed else 0.0}
