from __future__ import annotations

from datetime import UTC, datetime

from factory.artifacts.api import (
    CheckOutcome,
    ControlDefinition,
    CrossSimulatorComparison,
    ExperimentSpec,
    FidelityTier,
    HypothesisId,
    SimulatorId,
    ValidationResult,
)
from factory.fidelity.api import FidelityDecisionAction, FidelityLadderScheduler

HASH_A = "a" * 64
HASH_B = "b" * 64


def _five_tier_spec() -> ExperimentSpec:
    return ExperimentSpec(
        artifact_type="ExperimentSpec",
        created_at=datetime(2026, 5, 23, tzinfo=UTC),
        provenance_hash=HASH_A,
        parent_hashes=(HASH_B,),
        hypothesis_id=HypothesisId("HYP-001"),
        simulator_id=SimulatorId("primary"),
        control_definition=ControlDefinition(
            baseline_simulator_id=SimulatorId("baseline"),
            baseline_config={"mode": "test"},
        ),
        fidelity_ladder=(
            FidelityTier(
                name="dry",
                kind="dry_run",
                cost_estimate_usd=0.0,
                expected_runtime_seconds=1.0,
                kill_threshold=1.0,
            ),
            FidelityTier(
                name="surrogate",
                kind="surrogate",
                cost_estimate_usd=0.01,
                expected_runtime_seconds=2.0,
                kill_threshold=0.8,
            ),
            FidelityTier(
                name="medium",
                kind="mid_fidelity",
                cost_estimate_usd=0.2,
                expected_runtime_seconds=20.0,
                kill_threshold=0.4,
            ),
            FidelityTier(
                name="oracle",
                kind="oracle",
                cost_estimate_usd=2.0,
                expected_runtime_seconds=200.0,
                kill_threshold=0.2,
            ),
            FidelityTier(
                name="cross",
                kind="cross_simulator",
                cost_estimate_usd=3.0,
                expected_runtime_seconds=300.0,
                kill_threshold=None,
            ),
        ),
        seed_set=(1,),
        success_metric="residual",
        kill_criteria=("residual above tier threshold",),
    )


def _validation_with_cross_simulator(passed: bool) -> ValidationResult:
    return ValidationResult(
        artifact_type="ValidationResult",
        created_at=datetime(2026, 5, 23, tzinfo=UTC),
        provenance_hash=HASH_B,
        parent_hashes=(HASH_A,),
        hypothesis_id=HypothesisId("HYP-001"),
        experiment_spec_hash=HASH_A,
        per_check_outcomes=(
            CheckOutcome(
                check_name="residual",
                passed=True,
                residual=0.1,
                tolerance=0.2,
                skipped=False,
                rationale=None,
            ),
        ),
        residuals={"residual": 0.1},
        tolerances={"residual": 0.2},
        cross_simulator_comparison=CrossSimulatorComparison(
            paired_simulator_id=SimulatorId("secondary"),
            observable="residual",
            delta=0.01,
            tolerance=0.02,
            tolerance_kind="absolute",
            passed=passed,
        ),
        reweighted_for_missing_cross_sim=False,
        overall_verdict="pass" if passed else "fail",
        input_hashes_used=(HASH_A,),
    )


def test_scheduler_traverses_five_tier_ladder_and_requires_cross_simulator() -> None:
    scheduler = FidelityLadderScheduler(_five_tier_spec())

    first_decision = scheduler.next_decision()
    assert first_decision.action == FidelityDecisionAction.DISPATCH
    assert first_decision.tier_kind == "dry_run"

    completed_results = (
        scheduler.result_for(0, 0.2),
        scheduler.result_for(1, 0.3),
        scheduler.result_for(2, 0.3),
        scheduler.result_for(3, 0.1),
    )
    cross_decision = scheduler.next_decision(completed_results)
    assert cross_decision.action == FidelityDecisionAction.DISPATCH
    assert cross_decision.tier_kind == "cross_simulator"
    assert cross_decision.requires_cross_simulator

    satisfied_schedule = scheduler.schedule(
        completed_results,
        validation_result=_validation_with_cross_simulator(passed=True),
    )
    assert satisfied_schedule.decisions[-1].action == FidelityDecisionAction.COMPLETE
    assert satisfied_schedule.next_decision.reason == "fidelity_ladder_complete"


def test_scheduler_stops_when_tier_fails_kill_threshold() -> None:
    scheduler = FidelityLadderScheduler(_five_tier_spec())
    failed_surrogate = (
        scheduler.result_for(0, 0.2),
        scheduler.result_for(1, 0.9),
    )

    decision = scheduler.next_decision(failed_surrogate)

    assert decision.action == FidelityDecisionAction.STOP
    assert decision.tier_name == "surrogate"
    assert decision.reason == "tier_result_failed_kill_threshold"
