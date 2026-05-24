import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from factory.artifacts import HypothesisId
from factory.council.cli import (
    summarize_live_certification_budget,
    summarize_live_certification_session,
)


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_live_certification_session_requires_all_stage1_and_stage2_models(
    tmp_path: Path,
) -> None:
    models = ["openai/m", "anthropic/m", "google/m", "x-ai/m"]
    session_log = tmp_path / "session.jsonl"
    _write_jsonl(
        session_log,
        [{"event": "stage1_response", "model_id": model} for model in models]
        + [{"event": "stage2_response", "model_id": model} for model in models]
        + [
            {"event": "stage3_response", "model_id": "openai/m"},
            {"event": "session_end", "total_cost_usd": 0.10},
        ],
    )

    summary = summarize_live_certification_session(session_log, models)

    assert summary["stage1_response_count"] == 4
    assert summary["stage2_response_count"] == 4
    assert summary["stage3_response_count"] == 1


def test_live_certification_session_rejects_missing_vendor(tmp_path: Path) -> None:
    models = ["openai/m", "anthropic/m", "google/m", "x-ai/m"]
    session_log = tmp_path / "session.jsonl"
    _write_jsonl(
        session_log,
        [
            {"event": "stage1_response", "model_id": "openai/m"},
            {"event": "stage1_response", "model_id": "anthropic/m"},
            {"event": "stage1_response", "model_id": "google/m"},
        ]
        + [{"event": "stage2_response", "model_id": model} for model in models]
        + [{"event": "stage3_response", "model_id": "openai/m"}],
    )

    with pytest.raises(RuntimeError, match="Stage 1 vendor coverage mismatch"):
        summarize_live_certification_session(session_log, models)


def test_live_certification_budget_sums_matching_hypothesis(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    hypothesis_id = HypothesisId("H-LIVE")
    _write_jsonl(
        ledger_path,
        [
            {
                "hypothesis_id": "H-LIVE",
                "cost_usd": 0.03,
                "tokens": 10,
                "wall_clock_seconds": 1.5,
                "description": "stage1: openai/m",
            },
            {
                "hypothesis_id": "OTHER",
                "cost_usd": 0.99,
                "tokens": 999,
                "wall_clock_seconds": 9.9,
                "description": "ignored",
            },
            {
                "hypothesis_id": "H-LIVE",
                "cost_usd": 0.07,
                "tokens": 20,
                "wall_clock_seconds": 2.5,
                "description": "stage2: openai/m",
            },
        ],
    )

    summary = summarize_live_certification_budget(ledger_path, hypothesis_id)

    assert summary["budget_entry_count"] == 2
    assert summary["budget_recorded_cost_usd"] == pytest.approx(0.10)
    assert summary["budget_recorded_tokens"] == 30
    assert summary["budget_recorded_wall_clock_seconds"] == pytest.approx(4.0)
