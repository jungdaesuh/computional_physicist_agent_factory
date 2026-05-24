"""Active-learning escalation policy for surrogate probe results."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from factory.artifacts.api import SurrogateProbeResult


class ActiveLearningReason(StrEnum):
    """Reason a candidate should or should not enter the active-learning queue."""

    UNCERTAINTY = "uncertainty"
    OOD = "ood"
    POSTERIOR_VARIANCE = "posterior_variance"
    BASELINE_ESCALATION = "baseline_escalation"
    NONE = "none"


@dataclass(frozen=True)
class ActiveLearningPolicy:
    """Thresholds for deciding when a surrogate probe needs oracle labeling."""

    uncertainty_width_threshold: float
    ood_percentile_threshold: float
    posterior_variance_threshold: float


@dataclass(frozen=True)
class ActiveLearningDecision:
    """Typed decision emitted by the active-learning trigger."""

    should_label: bool
    reason: ActiveLearningReason
    uncertainty_width: float
    surprise_signal: float


def active_learning_trigger(
    probe_result: SurrogateProbeResult,
    policy: ActiveLearningPolicy,
    *,
    posterior_variance: float | None = None,
) -> ActiveLearningDecision:
    """Decide whether a surrogate probe should be escalated for fresh labels."""
    uncertainty_width = probe_result.uncertainty.ci_upper - probe_result.uncertainty.ci_lower
    surprise_signal = _surprise_signal(probe_result, posterior_variance)

    if uncertainty_width >= policy.uncertainty_width_threshold:
        return ActiveLearningDecision(
            should_label=True,
            reason=ActiveLearningReason.UNCERTAINTY,
            uncertainty_width=uncertainty_width,
            surprise_signal=surprise_signal,
        )
    if (
        probe_result.ood_flag
        or probe_result.ood_distance_percentile >= policy.ood_percentile_threshold
    ):
        return ActiveLearningDecision(
            should_label=True,
            reason=ActiveLearningReason.OOD,
            uncertainty_width=uncertainty_width,
            surprise_signal=surprise_signal,
        )
    if posterior_variance is not None and posterior_variance >= policy.posterior_variance_threshold:
        return ActiveLearningDecision(
            should_label=True,
            reason=ActiveLearningReason.POSTERIOR_VARIANCE,
            uncertainty_width=uncertainty_width,
            surprise_signal=surprise_signal,
        )
    if probe_result.pass_vs_baseline == "escalate":
        return ActiveLearningDecision(
            should_label=True,
            reason=ActiveLearningReason.BASELINE_ESCALATION,
            uncertainty_width=uncertainty_width,
            surprise_signal=surprise_signal,
        )
    return ActiveLearningDecision(
        should_label=False,
        reason=ActiveLearningReason.NONE,
        uncertainty_width=uncertainty_width,
        surprise_signal=surprise_signal,
    )


def _surprise_signal(probe_result: SurrogateProbeResult, posterior_variance: float | None) -> float:
    ood_signal = probe_result.ood_distance_percentile / 100.0
    if posterior_variance is None:
        return ood_signal
    return max(ood_signal, posterior_variance)


__all__ = [
    "ActiveLearningDecision",
    "ActiveLearningPolicy",
    "ActiveLearningReason",
    "active_learning_trigger",
]
