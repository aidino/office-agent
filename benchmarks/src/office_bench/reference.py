"""Hardcoded reference scores from published papers and leaderboards."""

from __future__ import annotations

REFERENCE_SCORES: dict[str, dict] = {
    "forte": {
        "scores": {
            "claude-3.5-sonnet": 47.1,
            "gpt-4o": 42.5,
            "gemini-1.5-pro": 38.9,
        },
        "metric": "avg_at_3",
        "source": "FORTE paper (Table 3), Avg@3 on 180 tasks",
    },
    "officebench": {
        "scores": {
            "gpt-4o": 47.00,
            "claude-3.5-sonnet": 37.67,
            "gemini-1.5-pro": 22.00,
        },
        "metric": "accuracy",
        "source": "OfficeBench paper (Table 2), overall accuracy %",
    },
    "spreadsheet": {
        "scores": {
            "gpt-4o": 35.8,
            "claude-3.5-sonnet": 30.2,
        },
        "metric": "pass_at_1",
        "source": "SpreadsheetBench 2 paper (Table 4), Pass@1 %",
    },
    "pptc": {
        "scores": {
            "gpt-4": 76.8,
            "gpt-3.5-turbo": 64.2,
        },
        "metric": "session_acc",
        "source": "PPTC paper (Table 3), session accuracy %",
    },
}
