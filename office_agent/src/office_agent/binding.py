"""Expose the Office Agent DeepAgents runnable to agentseek."""

from __future__ import annotations

from typing import Any

from agentseek_langchain import messages_spec
from deepagents import (
    HarnessProfile,
    ProviderProfile,
    create_deep_agent,
    register_harness_profile,
    register_provider_profile,
)

from .settings import get_settings
from .tools import OFFICE_TOOLS

SYSTEM_PROMPT = """\
You are Office Agent, a backend assistant for everyday office work with
documents, spreadsheets, and presentations.

Capabilities:
- Read text files (.txt, .csv, .md) and PDF documents, then summarize,
  extract, or answer questions about their content.
- Inspect .xlsx workbooks and analyze or clean up their tables.
- Create .xlsx spreadsheets from data you produce or derive.
- Build .pptx presentations from an outline of slides and bullet points.

Ground rules:
- Always call the matching tool to read a file before saying anything about
  its content; never guess file contents from the file name alone.
- File paths are confined to the agent workspace. If a path is rejected or
  unclear, ask the user for a path inside the workspace instead of retrying
  the same path.
- When you create a file, report the absolute path returned by the tool.
- Prefer structured, skimmable output: short headings, tables, bullet lists.
- Answer in the same language as the user's question.
"""


def build_agent() -> Any:
    """Build a local DeepAgents runnable."""

    settings = get_settings()
    settings.apply_openai_env_bridge()
    register_provider_profile(
        "openai",
        ProviderProfile(init_kwargs={"use_responses_api": False}),
    )

    # DeepAgents' built-in ls/read_file/write_file/edit_file/glob/grep/execute
    # operate on a virtual filesystem, not the agent workspace, and the task
    # tool has no subagents to call. Exclude them so the model only sees the
    # workspace-backed office tools.
    register_harness_profile(
        "openai",
        HarnessProfile(
            excluded_tools=frozenset(
                {"ls", "read_file", "write_file", "edit_file", "glob", "grep", "execute", "task"}
            )
        ),
    )
    return create_deep_agent(
        model=settings.require_model(),
        tools=OFFICE_TOOLS,
        system_prompt=SYSTEM_PROMPT,
    )


def build_spec():
    """Return a RunnableSpec for AGENTSEEK_LANGCHAIN_SPEC."""

    return messages_spec(build_agent(), include_agents_md=True)
