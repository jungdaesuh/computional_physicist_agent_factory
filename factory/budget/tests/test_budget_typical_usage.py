# test_budget_typical_usage.py — Typical usage and integration tests for BudgetTracker
#
# Demonstrates allocating hypothesis envelopes, reservations, commits, and close-outs.

import logging
from pathlib import Path

from factory.artifacts import HypothesisId
from factory.budget import (
    BudgetTracker,
    HypothesisCaps,
)

logger = logging.getLogger("factory.budget.tests")


def test_budget_typical_usage(tmp_path: Path) -> None:
    """Demonstrates typical usage of the BudgetTracker."""
    logger.info("Running typical usage test for budget")

    # Instantiate tracker with temporary file paths
    tracker = BudgetTracker(
        config_path=tmp_path / "budget.yaml",
        state_path=tmp_path / "state.json",
        ledger_path=tmp_path / "ledger.jsonl",
    )

    hypothesis_id = HypothesisId("HYP-001")
    caps = HypothesisCaps(dollars=10.0, tokens=1000, wall_clock_seconds=3600.0, iterations=5)

    # 1. Open hypothesis
    budget = tracker.open_hypothesis(hypothesis_id, caps)
    assert budget.dollar_cap == 10.0
    assert budget.token_cap == 1000

    # 2. Check and deduct (proactive reservation)
    res = tracker.check_and_deduct(
        hypothesis_id,
        module="council",
        estimated_cost_usd=0.50,
        estimated_tokens=50,
        estimated_wall_clock_seconds=10.0,
        estimated_iterations=0,
    )
    assert res.estimated_cost_usd == 0.50

    # 3. Commit the reservation with actual costs
    res.commit(actual_cost_usd=0.45, actual_tokens=45, wall_clock_seconds=12.0)

    # 4. Check remaining
    rem = tracker.remaining(hypothesis_id)
    assert rem.hypothesis.dollars == 9.55
    assert rem.hypothesis.tokens == 955

    # 5. Record iteration
    tracker.record_iteration(hypothesis_id)
    rem_iter = tracker.remaining(hypothesis_id)
    assert rem_iter.hypothesis.iterations == 4

    # 6. Close hypothesis
    final_budget = tracker.close_hypothesis(hypothesis_id, terminal_status="passed")
    assert final_budget.dollar_cap == 10.0
    assert len(final_budget.running_ledger) == 1
    assert final_budget.running_ledger[0].cost_usd == 0.45
