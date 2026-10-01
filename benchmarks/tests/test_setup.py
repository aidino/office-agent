from __future__ import annotations

import argparse
import os
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from office_bench.cli import _cmd_setup


def _ns() -> argparse.Namespace:
    """Build a bare Namespace matching the setup subparser."""
    return argparse.Namespace()


# --- Step 1: git submodule update ---


def test_setup_runs_submodule_update() -> None:
    with patch("office_bench.cli.subprocess") as mock_sub:
        mock_sub.run.return_value = MagicMock(returncode=0)
        ret = _cmd_setup(_ns())

    assert ret == 0
    calls = mock_sub.run.call_args_list
    assert any(
        "submodule" in str(c) for c in calls
    ), f"Expected git submodule call, got: {calls}"


# --- Step 4: LibreOffice check ---


def test_setup_checks_libreoffice() -> None:
    with patch("office_bench.cli.subprocess") as mock_sub:
        mock_sub.run.return_value = MagicMock(returncode=0)
        with patch("builtins.print") as mock_print:
            _cmd_setup(_ns())

    printed = " ".join(str(c) for c in mock_print.call_args_list)
    assert "LibreOffice" in printed or "libreoffice" in printed.lower()


# --- Step 6: API key warnings ---


def test_setup_warns_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BUB_API_KEY", raising=False)
    monkeypatch.delenv("JUDGE_API_KEY", raising=False)

    with patch("office_bench.cli.subprocess") as mock_sub:
        mock_sub.run.return_value = MagicMock(returncode=0)
        with patch("builtins.print") as mock_print:
            _cmd_setup(_ns())

    printed = " ".join(str(c) for c in mock_print.call_args_list)
    assert "API" in printed or "key" in printed.lower() or "JUDGE" in printed


def test_setup_acknowledges_present_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JUDGE_API_KEY", "sk-test")

    with patch("office_bench.cli.subprocess") as mock_sub:
        mock_sub.run.return_value = MagicMock(returncode=0)
        with patch("builtins.print") as mock_print:
            _cmd_setup(_ns())

    printed = " ".join(str(c) for c in mock_print.call_args_list)
    # Should not warn — key is present
    assert "JUDGE_API_KEY" in printed or "set" in printed.lower()


# --- Step 2: SpreadsheetBench dataset check ---


def test_setup_mentions_spreadsheetbench_dataset() -> None:
    with patch("office_bench.cli.subprocess") as mock_sub:
        mock_sub.run.return_value = MagicMock(returncode=0)
        with patch("builtins.print") as mock_print:
            _cmd_setup(_ns())

    printed = " ".join(str(c) for c in mock_print.call_args_list)
    assert (
        "SpreadsheetBench" in printed or "spreadsheet" in printed.lower()
    ), f"Should mention SpreadsheetBench dataset, got: {printed}"


# --- Step 3: PPTC label check ---


def test_setup_mentions_pptc_labels() -> None:
    with patch("office_bench.cli.subprocess") as mock_sub:
        mock_sub.run.return_value = MagicMock(returncode=0)
        with patch("builtins.print") as mock_print:
            _cmd_setup(_ns())

    printed = " ".join(str(c) for c in mock_print.call_args_list)
    assert "PPTC" in printed, f"Should mention PPTC labels, got: {printed}"


# --- Step 5: FORTE judge check ---


def test_setup_mentions_forte_judge() -> None:
    with patch("office_bench.cli.subprocess") as mock_sub:
        mock_sub.run.return_value = MagicMock(returncode=0)
        with patch("builtins.print") as mock_print:
            _cmd_setup(_ns())

    printed = " ".join(str(c) for c in mock_print.call_args_list)
    assert "FORTE" in printed, f"Should mention FORTE judge, got: {printed}"


# --- Step ordering: all 6 steps ---


def test_setup_runs_all_six_steps() -> None:
    """Verify setup prints numbered steps 1-6."""
    with patch("office_bench.cli.subprocess") as mock_sub:
        mock_sub.run.return_value = MagicMock(returncode=0)
        with patch("builtins.print") as mock_print:
            ret = _cmd_setup(_ns())

    assert ret == 0
    printed = " ".join(str(c) for c in mock_print.call_args_list)
    for step_num in range(1, 7):
        assert f"{step_num}/6" in printed, (
            f"Missing step {step_num}/6 in output: {printed}"
        )
