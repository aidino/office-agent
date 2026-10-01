"""LLM judge backend via OpenAI-compatible API (DeepSeek default)."""

from __future__ import annotations

import os

import requests

from office_bench.judges.base import JudgeContext, Rubric, RubricResult

_SYSTEM_PROMPT = (
    "You are an expert evaluator. Given an instruction, the agent's response, "
    "and a rubric, determine if the rubric is satisfied.\n\n"
    "Respond with exactly one of:\n"
    "- PASS. <reason>\n"
    "- FAIL. <reason>\n\n"
    "Be strict but fair."
)


class LLMJudge:
    """LLM-as-judge using OpenAI-compatible chat completions API."""

    def __init__(
        self,
        model: str = "",
        base_url: str = "",
        api_key: str = "",
    ) -> None:
        self._model = model or os.environ.get("JUDGE_MODEL", "deepseek-chat")
        self._base_url = (
            base_url or os.environ.get("JUDGE_BASE_URL", "https://api.deepseek.com")
        ).rstrip("/")
        self._api_key = api_key or os.environ.get(
            "JUDGE_API_KEY", os.environ.get("BUB_API_KEY", "")
        )

    @property
    def name(self) -> str:
        return f"llm:{self._model}"

    def judge_rubric(self, rubric: Rubric, context: JudgeContext) -> RubricResult:
        """Evaluate a single rubric using the LLM judge."""
        user_content = (
            f"## Instruction\n{context.instruction}\n\n"
            f"## Agent Response\n{context.agent_response}\n\n"
        )

        if context.file_contents:
            user_content += "## Files\n"
            for path, content in context.file_contents.items():
                user_content += f"### {path}\n```\n{content}\n```\n\n"

        user_content += f"## Rubric\n{rubric.content}\n\nVerdict:"

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.0,
            "max_tokens": 256,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        try:
            resp = requests.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            reply = data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            return RubricResult(
                rubric_id=rubric.id,
                passed=False,
                confidence=None,
                reason=f"Judge API error: {e}",
            )

        passed = reply.upper().startswith("PASS")
        # Extract reason after "PASS." or "FAIL."
        reason = reply.split(".", 1)[1].strip() if "." in reply else reply

        return RubricResult(
            rubric_id=rubric.id,
            passed=passed,
            confidence=None,
            reason=reason,
        )
