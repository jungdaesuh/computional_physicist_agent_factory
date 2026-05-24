"""Command line interface for fidelity ladder inspection and mock traversal."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from factory.artifacts import ExperimentSpec
from factory.fidelity.api import (
    FidelityDecisionAction,
    FidelityDispatchResult,
    FidelityLadderScheduler,
    FidelityTierDecision,
    FidelityTierResult,
    promote_tier_results,
    run_next_tier,
)


def main(argv: list[str] | None = None) -> None:
    """Run fidelity CLI commands."""
    parser = argparse.ArgumentParser(description="Fidelity CLI")
    parser.add_argument("--mock-mode", action="store_true", help="Run in mock mode")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run-ladder", help="Traverse a fixture ladder")
    run_parser.add_argument("--experiment-fixture", default="typical")
    run_parser.add_argument("--mock-mode", action="store_true")

    inspect_parser = subparsers.add_parser("inspect", help="Inspect a fixture ladder")
    inspect_parser.add_argument("--experiment-fixture", default="typical")

    criteria_parser = subparsers.add_parser("kill-criteria", help="Print tier kill thresholds")
    criteria_parser.add_argument("--experiment-fixture", default="typical")

    args = parser.parse_args(argv)
    if args.command is None:
        if args.mock_mode:
            print("fidelity mock mode ready")
            return
        parser.print_help()
        return

    if args.command == "run-ladder":
        experiment = ExperimentSpec.from_fixture(args.experiment_fixture)
        print(json.dumps(_run_ladder(experiment), indent=2, sort_keys=True))
        return

    if args.command == "inspect":
        experiment = ExperimentSpec.from_fixture(args.experiment_fixture)
        print(json.dumps(_inspect_ladder(experiment), indent=2, sort_keys=True))
        return

    if args.command == "kill-criteria":
        experiment = ExperimentSpec.from_fixture(args.experiment_fixture)
        print(json.dumps(_kill_criteria(experiment), indent=2, sort_keys=True))


def _run_ladder(experiment: ExperimentSpec) -> dict[str, object]:
    scheduler = FidelityLadderScheduler(experiment)
    results: tuple[FidelityTierResult, ...] = ()
    transitions: list[dict[str, object]] = []

    while True:
        decision = scheduler.next_decision(results)
        if decision.action is FidelityDecisionAction.COMPLETE:
            return {
                "hypothesis_id": str(experiment.hypothesis_id),
                "status": "complete",
                "transitions": transitions,
            }
        if decision.action is FidelityDecisionAction.STOP:
            return {
                "hypothesis_id": str(experiment.hypothesis_id),
                "status": "stopped",
                "stop": asdict(decision),
                "transitions": transitions,
            }

        outcome = run_next_tier(
            scheduler,
            results,
            lambda next_decision: _dispatch_mock_tier(experiment, next_decision),
        )
        results = promote_tier_results(results, outcome.result)
        transitions.append(
            {
                "decision": asdict(outcome.decision),
                "result": None if outcome.result is None else asdict(outcome.result),
                "output_ref": outcome.output_ref,
            }
        )


def _dispatch_mock_tier(
    experiment: ExperimentSpec,
    decision: FidelityTierDecision,
) -> FidelityDispatchResult:
    tier = experiment.fidelity_ladder[decision.tier_index]
    metric_value = 0.0 if tier.kill_threshold is None else tier.kill_threshold * 0.5
    return FidelityDispatchResult(
        metric_value=metric_value,
        output_ref=f"mock://fidelity/{experiment.hypothesis_id}/{tier.name}",
    )


def _inspect_ladder(experiment: ExperimentSpec) -> dict[str, object]:
    scheduler = FidelityLadderScheduler(experiment)
    schedule = scheduler.schedule()
    return {
        "hypothesis_id": str(experiment.hypothesis_id),
        "tiers": [tier.model_dump(mode="json") for tier in experiment.fidelity_ladder],
        "next_decision": asdict(schedule.next_decision),
    }


def _kill_criteria(experiment: ExperimentSpec) -> dict[str, object]:
    return {
        "hypothesis_id": str(experiment.hypothesis_id),
        "tiers": [
            {
                "name": tier.name,
                "kind": tier.kind,
                "kill_threshold": tier.kill_threshold,
            }
            for tier in experiment.fidelity_ladder
        ],
    }


if __name__ == "__main__":
    main()
