# test_api.py — Unit tests for the BudgetTracker API
#
# Verifies three-tier cap enforcement, aggregate halts, daily resets,
# and checksum ledger integrity.

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from factory.artifacts import HypothesisId
from factory.budget import (
    AggregateCapTriggered,
    BudgetExhausted,
    BudgetLedgerCorrupted,
    BudgetTracker,
    HypothesisCaps,
)
from factory.budget.api import Clock


class MockClock(Clock):
    """Adjustable clock for daily reset tests."""

    def __init__(self, current_time: str) -> None:
        self._now = datetime.fromisoformat(current_time)

    def now(self) -> datetime:
        return self._now

    def advance(self, hours: float) -> None:
        from datetime import timedelta

        self._now += timedelta(hours=hours)


def test_phase_b_budget_defaults_load_from_config() -> None:
    """Phase B runs default to the overnight aggregate and per-hypothesis caps."""
    tracker = BudgetTracker(mock_mode=True)
    hypothesis_id = HypothesisId("phase-b-defaults")

    budget = tracker.open_hypothesis(hypothesis_id)
    remaining = tracker.remaining(hypothesis_id)

    assert budget.dollar_cap == 100.0
    assert remaining.aggregate.dollars == 500.0


def test_three_tier_enforcement(tmp_path: Path) -> None:
    """Verifies that per-hypothesis, daily, and aggregate limits are checked."""
    tracker = BudgetTracker(
        config_path=tmp_path / "budget.yaml",
        state_path=tmp_path / "state.json",
        ledger_path=tmp_path / "ledger.jsonl",
    )
    tracker._control_dir = tmp_path / "_control"
    tracker._halt_sentinel = tracker._control_dir / "HALT_AGGREGATE_CAP"

    # Configure low caps
    tracker._aggregate_dollar_cap = 5.0
    tracker._day_cap_dollars = 3.0

    h_id = HypothesisId("H-1")
    tracker.open_hypothesis(
        h_id, HypothesisCaps(dollars=2.0, tokens=10, wall_clock_seconds=10.0, iterations=2)
    )

    # 1. Deduct within caps
    res = tracker.check_and_deduct(h_id, "test", estimated_cost_usd=1.0)
    res.commit(actual_cost_usd=1.0, actual_tokens=1, wall_clock_seconds=1.0)

    # 2. Exceed hypothesis cap
    with pytest.raises(BudgetExhausted) as excinfo:
        tracker.check_and_deduct(h_id, "test", estimated_cost_usd=1.5)
    assert excinfo.value.tier == "hypothesis"

    # 3. Exceed day cap (increase hypothesis cap to allow but day cap should stop it)
    tracker._hypotheses_caps[h_id] = HypothesisCaps(
        dollars=10.0, tokens=100, wall_clock_seconds=100.0, iterations=10
    )
    with pytest.raises(BudgetExhausted) as excinfo:
        tracker.check_and_deduct(h_id, "test", estimated_cost_usd=2.5)
    assert excinfo.value.tier == "day"

    # 4. Exceed aggregate cap
    with pytest.raises(AggregateCapTriggered):
        tracker.check_and_deduct(h_id, "test", estimated_cost_usd=4.5)


def test_aggregate_kill_switch(tmp_path: Path) -> None:
    """Verifies that aggregate cap breach creates the sentinel halt file."""
    tracker = BudgetTracker(
        config_path=tmp_path / "budget.yaml",
        state_path=tmp_path / "state.json",
        ledger_path=tmp_path / "ledger.jsonl",
    )
    tracker._control_dir = tmp_path / "_control"
    tracker._halt_sentinel = tracker._control_dir / "HALT_AGGREGATE_CAP"
    tracker._aggregate_dollar_cap = 1.0

    h_id = HypothesisId("H-1")
    tracker.open_hypothesis(
        h_id, HypothesisCaps(dollars=10.0, tokens=100, wall_clock_seconds=100.0, iterations=10)
    )

    # Breaching cap on record should trigger halt
    tracker.record(
        h_id, "test", cost_usd=1.5, tokens=1, wall_clock_seconds=1.0, description="breach"
    )
    assert tracker._halt_sentinel.exists()

    # Subsequent checks should fail immediately
    with pytest.raises(AggregateCapTriggered):
        tracker.check_and_deduct(h_id, "test", estimated_cost_usd=0.1)

    # Raising cap and clearing halt should restore operation
    tracker.set_cap(aggregate_usd=5.0, clear_halt=True)
    assert not tracker._halt_sentinel.exists()
    tracker.check_and_deduct(h_id, "test", estimated_cost_usd=0.1)


def test_daily_reset(tmp_path: Path) -> None:
    """Verifies daily reset occurs when clock crosses midnight."""
    clock = MockClock("2026-05-23T20:00:00+00:00")
    tracker = BudgetTracker(
        config_path=tmp_path / "budget.yaml",
        state_path=tmp_path / "state.json",
        ledger_path=tmp_path / "ledger.jsonl",
        clock=clock,
    )
    tracker._day_cap_dollars = 10.0

    h_id = HypothesisId("H-1")
    tracker.open_hypothesis(
        h_id, HypothesisCaps(dollars=100.0, tokens=100, wall_clock_seconds=100.0, iterations=10)
    )

    # Spend dollars
    tracker.record(
        h_id, "test", cost_usd=8.0, tokens=1, wall_clock_seconds=1.0, description="spend"
    )
    assert tracker._day_used_dollars == 8.0

    # Advance clock past midnight
    clock.advance(5.0)  # past 2026-05-24T01:00:00

    # Trigger interaction to check lazy reset
    rem = tracker.remaining(h_id)
    assert tracker._day_used_dollars == 0.0
    assert rem.day.dollars == 10.0


def test_ledger_corruption(tmp_path: Path) -> None:
    """Verifies that a tampered ledger file raises BudgetLedgerCorrupted."""
    ledger_file = tmp_path / "corrupt.jsonl"

    # Write a valid record
    entry = {
        "ledger_entry_id": "123",
        "ts": "2026-05-23T12:00:00Z",
        "hypothesis_id": "H-1",
        "module": "test",
        "cost_usd": 1.0,
        "tokens": 10,
        "wall_clock_seconds": 1.0,
        "description": "test",
    }
    # Compute checksum
    payload = {k: v for k, v in entry.items() if k != "checksum"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    entry["checksum"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    with open(ledger_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    # Now load and it should succeed
    BudgetTracker(
        config_path=tmp_path / "budget.yaml",
        state_path=tmp_path / "state.json",
        ledger_path=ledger_file,
        mock_mode=False,
    )

    # Let's corrupt the checksum in the file
    entry["checksum"] = "badchecksum"
    with open(ledger_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    # Re-instantiating should raise corruption error
    with pytest.raises(BudgetLedgerCorrupted):
        BudgetTracker(
            config_path=tmp_path / "budget.yaml",
            state_path=tmp_path / "state.json",
            ledger_path=ledger_file,
            mock_mode=False,
        )
