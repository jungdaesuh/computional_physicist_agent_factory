from __future__ import annotations

from datetime import UTC, datetime

from factory.artifacts.api import HypothesisId, SurrogateProbeResult, UncertaintyBlock
from factory.fidelity.api import (
    ActiveLearningPolicy,
    ActiveLearningReason,
    active_learning_trigger,
)

HASH_A = "a" * 64
HASH_B = "b" * 64


def _probe(
    *, ci_lower: float, ci_upper: float, ood_flag: bool, percentile: float
) -> SurrogateProbeResult:
    return SurrogateProbeResult(
        artifact_type="SurrogateProbeResult",
        created_at=datetime(2026, 5, 23, tzinfo=UTC),
        provenance_hash=HASH_A,
        parent_hashes=(HASH_B,),
        hypothesis_id=HypothesisId("HYP-001"),
        experiment_spec_hash=HASH_B,
        predicted_value=0.2,
        uncertainty=UncertaintyBlock(
            metric_name="residual",
            point_estimate=0.2,
            ci_lower=ci_lower,
            ci_upper=ci_upper,
            ci_method="t_interval",
            n_seeds=3,
        ),
        ood_flag=ood_flag,
        ood_distance_percentile=percentile,
        pass_vs_baseline="pass",
        surrogate_model_id="knn",
        feature_vector_hash=HASH_A,
    )


def test_active_learning_prefers_uncertainty_then_fallback_surprise_signals() -> None:
    policy = ActiveLearningPolicy(
        uncertainty_width_threshold=0.5,
        ood_percentile_threshold=95.0,
        posterior_variance_threshold=0.3,
    )

    uncertain = active_learning_trigger(
        _probe(ci_lower=0.0, ci_upper=0.7, ood_flag=False, percentile=10.0),
        policy,
    )
    assert uncertain.should_label
    assert uncertain.reason == ActiveLearningReason.UNCERTAINTY

    ood = active_learning_trigger(
        _probe(ci_lower=0.1, ci_upper=0.2, ood_flag=False, percentile=99.0),
        policy,
    )
    assert ood.should_label
    assert ood.reason == ActiveLearningReason.OOD
    assert ood.surprise_signal == 0.99

    posterior = active_learning_trigger(
        _probe(ci_lower=0.1, ci_upper=0.2, ood_flag=False, percentile=20.0),
        policy,
        posterior_variance=0.4,
    )
    assert posterior.should_label
    assert posterior.reason == ActiveLearningReason.POSTERIOR_VARIANCE
    assert posterior.surprise_signal == 0.4
