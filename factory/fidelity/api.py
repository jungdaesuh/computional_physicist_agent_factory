"""Public implementation contract for the fidelity module."""

from __future__ import annotations

from factory.fidelity.active import (
    ActiveLearningDecision,
    ActiveLearningPolicy,
    ActiveLearningReason,
    active_learning_trigger,
)
from factory.fidelity.errors import (
    AdapterRunFailed,
    FidelityError,
    LadderEmpty,
    MetricMissing,
    SurrogatePredictionUnavailable,
    TierBudgetExhausted,
    TierKillThresholdHit,
    TierOutOfOrder,
)
from factory.fidelity.scheduler import (
    FidelityDecisionAction,
    FidelityLadderScheduler,
    FidelitySchedule,
    FidelityTierDecision,
    FidelityTierResult,
)
from factory.fidelity.tiers import (
    FidelityDispatchResult,
    FidelityKind,
    FidelityRunOutcome,
    TierDispatcher,
    promote_tier_results,
    run_next_tier,
)
from factory.module_contracts import ModuleContract

MODULE_CONTRACT = ModuleContract(
    module_name="fidelity",
    spec_id="017",
    responsibility="Choose the next allowed fidelity tier from an experiment ladder.",
    required_inputs=(
        "ExperimentSpec",
        "SurrogateProbeResult",
    ),
    produced_outputs=("FidelityTierDecision",),
)


def describe_contract() -> ModuleContract:
    """Return the stable public contract for this module."""
    return MODULE_CONTRACT


__all__ = [
    "ActiveLearningDecision",
    "ActiveLearningPolicy",
    "ActiveLearningReason",
    "AdapterRunFailed",
    "FidelityDecisionAction",
    "FidelityDispatchResult",
    "FidelityError",
    "FidelityKind",
    "FidelityLadderScheduler",
    "FidelityRunOutcome",
    "FidelitySchedule",
    "FidelityTierDecision",
    "FidelityTierResult",
    "LadderEmpty",
    "MODULE_CONTRACT",
    "MetricMissing",
    "SurrogatePredictionUnavailable",
    "TierDispatcher",
    "TierBudgetExhausted",
    "TierKillThresholdHit",
    "TierOutOfOrder",
    "active_learning_trigger",
    "describe_contract",
    "promote_tier_results",
    "run_next_tier",
]
