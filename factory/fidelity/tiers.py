"""Fidelity tier dispatch and promotion helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from factory.fidelity.scheduler import (
    FidelityDecisionAction,
    FidelityLadderScheduler,
    FidelityTierDecision,
    FidelityTierResult,
)
from factory.fidelity.types import FidelityKind


@dataclass(frozen=True)
class FidelityDispatchResult:
    """Observed result returned by a concrete fidelity-tier dispatcher."""

    metric_value: float
    output_ref: str


@dataclass(frozen=True)
class FidelityRunOutcome:
    """Outcome of attempting to run the scheduler's next actionable tier."""

    decision: FidelityTierDecision
    result: FidelityTierResult | None
    output_ref: str | None


TierDispatcher = Callable[[FidelityTierDecision], FidelityDispatchResult]


def run_next_tier(
    scheduler: FidelityLadderScheduler,
    results: tuple[FidelityTierResult, ...],
    dispatch_tier: TierDispatcher,
) -> FidelityRunOutcome:
    """Dispatch the next unresolved fidelity tier and convert its metric to a scheduler result."""
    decision = scheduler.next_decision(results)
    if decision.action is not FidelityDecisionAction.DISPATCH:
        return FidelityRunOutcome(decision=decision, result=None, output_ref=None)

    dispatch_result = dispatch_tier(decision)
    tier_result = scheduler.result_for(decision.tier_index, dispatch_result.metric_value)
    return FidelityRunOutcome(
        decision=decision,
        result=tier_result,
        output_ref=dispatch_result.output_ref,
    )


def promote_tier_results(
    existing_results: tuple[FidelityTierResult, ...],
    new_result: FidelityTierResult | None,
) -> tuple[FidelityTierResult, ...]:
    """Append a new tier result immutably when dispatch produced one."""
    if new_result is None:
        return existing_results
    return (*existing_results, new_result)


__all__ = [
    "FidelityDispatchResult",
    "FidelityKind",
    "FidelityRunOutcome",
    "TierDispatcher",
    "promote_tier_results",
    "run_next_tier",
]
