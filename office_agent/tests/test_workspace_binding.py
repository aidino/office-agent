from __future__ import annotations

import asyncio
import os

from office_agent.binding import WorkspaceScopedRunnable
from office_agent.tools import WORKSPACE_ENV


class _AsyncRecorder:
    """Stub runnable that records the workspace env at call time."""

    def __init__(self) -> None:
        self.seen: list[str | None] = []

    async def ainvoke(self, runnable_input, /, **kwargs):
        self.seen.append(os.environ.get(WORKSPACE_ENV))
        return "done"


class _SyncRecorder:
    def __init__(self) -> None:
        self.seen: list[str | None] = []

    def invoke(self, runnable_input, /, **kwargs):
        self.seen.append(os.environ.get(WORKSPACE_ENV))
        return "done"


def _config(workspace: str | None) -> dict:
    metadata = {} if workspace is None else {"workspace": workspace}
    return {"metadata": metadata}


def test_ainvoke_sets_workspace_from_config_metadata(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(WORKSPACE_ENV, raising=False)
    inner = _AsyncRecorder()
    wrapped = WorkspaceScopedRunnable(inner)

    result = asyncio.run(
        wrapped.ainvoke({"messages": []}, config=_config(str(tmp_path)))
    )

    assert result == "done"
    assert inner.seen == [str(tmp_path)]
    assert WORKSPACE_ENV not in os.environ  # restored afterwards


def test_ainvoke_without_workspace_leaves_env_untouched(monkeypatch) -> None:
    monkeypatch.setenv(WORKSPACE_ENV, "/srv/default")
    inner = _AsyncRecorder()
    wrapped = WorkspaceScopedRunnable(inner)

    asyncio.run(wrapped.ainvoke({"messages": []}, config=_config(None)))

    assert inner.seen == ["/srv/default"]
    assert os.environ[WORKSPACE_ENV] == "/srv/default"


def test_sync_invoke_sets_workspace(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(WORKSPACE_ENV, raising=False)
    inner = _SyncRecorder()
    wrapped = WorkspaceScopedRunnable(inner)

    out = wrapped.invoke({"messages": []}, config=_config(str(tmp_path)))

    assert out == "done"
    assert inner.seen == [str(tmp_path)]
    assert WORKSPACE_ENV not in os.environ


def test_restores_previous_value(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(WORKSPACE_ENV, "/srv/old")
    inner = _AsyncRecorder()
    wrapped = WorkspaceScopedRunnable(inner)

    asyncio.run(wrapped.ainvoke({"messages": []}, config=_config(str(tmp_path))))

    assert inner.seen == [str(tmp_path)]
    assert os.environ[WORKSPACE_ENV] == "/srv/old"
