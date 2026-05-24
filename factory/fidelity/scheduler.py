"""Deterministic traversal for ExperimentSpec fidelity ladders."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from factory.artifacts.api import ExperimentSpec, FidelityTier, ValidationResult
from factory.fidelity.errors import LadderEmpty, TierOutOfOrder
from factory.fidelity.types import FidelityTierKind


class FidelityDecisionAction(StrEnum):
    """Scheduler actions for one fidelity tier."""

    DISPATCH = "dispatch"
    WAIT = "wait"
    COMPLETE = "complete"
    STOP = "stop"


@dataclass(frozen=True)
class FidelityTierResult:
    """Observed result for one dispatched fidelity tier.

    metric_value is compared to the tier kill_threshold with lower values treated as better.
    """

    tier_index: int
    tier_name: str
    tier_kind: FidelityTierKind
    metric_value: float
    passed_kill_threshold: bool


@dataclass(frozen=True)
class FidelityTierDecision:
    """Deterministic scheduler decision for one tier in an experiment ladder."""

    tier_index: int
    tier_name: str
    tier_kind: FidelityTierKind
    action: FidelityDecisionAction
    reason: str
    requires_cross_simulator: bool = False


@dataclass(frozen=True)
class FidelitySchedule:
    """Full ladder state plus the next actionable scheduler decision."""

    decisions: tuple[FidelityTierDecision, ...]
    next_decision: FidelityTierDecision


class FidelityLadderScheduler:
    """Traverse an ExperimentSpec fidelity ladder from cheap tiers to expensive tiers."""

    def __init__(self, experiment_spec: ExperimentSpec) -> None:
        if not experiment_spec.fidelity_ladder:
            raise LadderEmpty("ExperimentSpec.fidelity_ladder must contain at least one tier")
        self._experiment_spec = experiment_spec

    def result_for(self, tier_index: int, metric_value: float) -> FidelityTierResult:
        """Create a tier result with kill-threshold evaluation owned by the scheduler."""
        tier = self._tier_at(tier_index)
        return FidelityTierResult(
            tier_index=tier_index,
            tier_name=tier.name,
            tier_kind=tier.kind,
            metric_value=metric_value,
            passed_kill_threshold=self._passes_kill_threshold(tier, metric_value),
        )

    def schedule(
        self,
        results: tuple[FidelityTierResult, ...] = (),
        validation_result: ValidationResult | None = None,
    ) -> FidelitySchedule:
        """Return per-tier decisions and the next dispatch/stop/complete action."""
        result_by_index = self._validated_results(results)
        decisions: list[FidelityTierDecision] = []
        terminal_stop = False
        dispatch_selected = False

        for tier_index, tier in enumerate(self._experiment_spec.fidelity_ladder):
            decision = self._decision_for_tier(
                tier_index=tier_index,
                tier=tier,
                result=result_by_index.get(tier_index),
                validation_result=validation_result,
                terminal_stop=terminal_stop,
                dispatch_selected=dispatch_selected,
            )
            decisions.append(decision)

            if decision.action == FidelityDecisionAction.STOP:
                terminal_stop = True
            if decision.action == FidelityDecisionAction.DISPATCH:
                dispatch_selected = True

        return FidelitySchedule(
            decisions=tuple(decisions),
            next_decision=self._next_decision(tuple(decisions)),
        )

    def next_decision(
        self,
        results: tuple[FidelityTierResult, ...] = (),
        validation_result: ValidationResult | None = None,
    ) -> FidelityTierDecision:
        """Return the next actionable scheduler decision."""
        return self.schedule(results=results, validation_result=validation_result).next_decision

    def _decision_for_tier(
        self,
        tier_index: int,
        tier: FidelityTier,
        result: FidelityTierResult | None,
        validation_result: ValidationResult | None,
        terminal_stop: bool,
        dispatch_selected: bool,
    ) -> FidelityTierDecision:
        if terminal_stop:
            return self._decision(tier_index, tier, FidelityDecisionAction.WAIT, "blocked_by_stop")

        if result is not None:
            if result.passed_kill_threshold:
                return self._decision(
                    tier_index,
                    tier,
                    FidelityDecisionAction.COMPLETE,
                    "tier_result_passed_kill_threshold",
                )
            return self._decision(
                tier_index,
                tier,
                FidelityDecisionAction.STOP,
                "tier_result_failed_kill_threshold",
            )

        if tier.kind == "cross_simulator":
            cross_simulator_comparison = (
                validation_result.cross_simulator_comparison
                if validation_result is not None
                else None
            )
            if cross_simulator_comparison is not None:
                if cross_simulator_comparison.passed:
                    return self._decision(
                        tier_index,
                        tier,
                        FidelityDecisionAction.COMPLETE,
                        "cross_simulator_comparison_already_passed",
                    )
                return self._decision(
                    tier_index,
                    tier,
                    FidelityDecisionAction.STOP,
                    "cross_simulator_comparison_failed",
                )

        if dispatch_selected:
            return self._decision(
                tier_index, tier, FidelityDecisionAction.WAIT, "waiting_for_prior_tier"
            )

        return self._decision(
            tier_index,
            tier,
            FidelityDecisionAction.DISPATCH,
            "next_unresolved_tier",
            requires_cross_simulator=tier.kind == "cross_simulator",
        )

    def _validated_results(
        self, results: tuple[FidelityTierResult, ...]
    ) -> dict[int, FidelityTierResult]:
        result_by_index: dict[int, FidelityTierResult] = {}
        for result in results:
            tier = self._tier_at(result.tier_index)
            if result.tier_name != tier.name or result.tier_kind != tier.kind:
                raise TierOutOfOrder(
                    "FidelityTierResult does not match ExperimentSpec.fidelity_ladder at "
                    f"index {result.tier_index}"
                )
            if result.tier_index in result_by_index:
                raise TierOutOfOrder(
                    f"duplicate FidelityTierResult for tier index {result.tier_index}"
                )
            result_by_index[result.tier_index] = result
        return result_by_index

    def _tier_at(self, tier_index: int) -> FidelityTier:
        if tier_index < 0 or tier_index >= len(self._experiment_spec.fidelity_ladder):
            raise IndexError(f"tier index {tier_index} is outside the fidelity ladder")
        return self._experiment_spec.fidelity_ladder[tier_index]

    @staticmethod
    def _passes_kill_threshold(tier: FidelityTier, metric_value: float) -> bool:
        return tier.kill_threshold is None or metric_value <= tier.kill_threshold

    @staticmethod
    def _decision(
        tier_index: int,
        tier: FidelityTier,
        action: FidelityDecisionAction,
        reason: str,
        *,
        requires_cross_simulator: bool = False,
    ) -> FidelityTierDecision:
        return FidelityTierDecision(
            tier_index=tier_index,
            tier_name=tier.name,
            tier_kind=tier.kind,
            action=action,
            reason=reason,
            requires_cross_simulator=requires_cross_simulator,
        )

    @staticmethod
    def _next_decision(decisions: tuple[FidelityTierDecision, ...]) -> FidelityTierDecision:
        for decision in decisions:
            if decision.action in {
                FidelityDecisionAction.DISPATCH,
                FidelityDecisionAction.STOP,
            }:
                return decision
        return FidelityTierDecision(
            tier_index=len(decisions),
            tier_name="complete",
            tier_kind="oracle",
            action=FidelityDecisionAction.COMPLETE,
            reason="fidelity_ladder_complete",
        )


__all__ = [
    "FidelityDecisionAction",
    "FidelityLadderScheduler",
    "FidelitySchedule",
    "FidelityTierDecision",
    "FidelityTierKind",
    "FidelityTierResult",
]
