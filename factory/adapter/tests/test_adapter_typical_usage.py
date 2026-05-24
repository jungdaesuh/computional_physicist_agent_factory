"""Typical usage tests for the adapter module public contract."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from factory.adapter.api import describe_contract, load
from factory.adapter.types import SANDBOX_ADAPTER_OUTPUTS_RELPATH, RunArtifacts
from factory.artifacts import (
    ControlDefinition,
    ExperimentSpec,
    FidelityTier,
    HypothesisId,
    SimulatorId,
)

HASH_A = "a" * 64
HASH_B = "b" * 64


def test_adapter_typical_usage() -> None:
    """Documents the module boundary consumed by orchestration code."""
    contract = describe_contract()

    assert contract.module_name == "adapter"
    assert contract.spec_id == "006"
    assert contract.requires("ExperimentSpec")
    assert contract.produces("AdapterRunRequest")


def test_sim_a_mock_adapter_writes_run_artifacts(tmp_path: Path) -> None:
    """Mock-mode adapter run returns and persists canonical RunArtifacts."""
    adapter = load("sim_a", mock_mode=True)
    artifacts = adapter.run(_experiment_spec("sim_a"), tmp_path)

    assert isinstance(artifacts, RunArtifacts)
    assert artifacts.observables["force_balance_residual"] == 0.2
    assert artifacts.residuals["solver_residual_norm"] == 0.03
    assert artifacts.sandbox_paths["run_artifacts"].exists()
    assert artifacts.sandbox_paths["run_artifacts"].relative_to(tmp_path).parts[:2] == (
        SANDBOX_ADAPTER_OUTPUTS_RELPATH,
        "7",
    )


def _experiment_spec(simulator_id: str) -> ExperimentSpec:
    return ExperimentSpec(
        artifact_type="ExperimentSpec",
        created_at=datetime(2026, 5, 23, tzinfo=UTC),
        provenance_hash=HASH_A,
        parent_hashes=(HASH_B,),
        hypothesis_id=HypothesisId("HYP-001"),
        simulator_id=SimulatorId(simulator_id),
        control_definition=ControlDefinition(
            baseline_simulator_id=SimulatorId("baseline"),
            baseline_config={"metric_value": 0.2, "solver_residual_norm": 0.03},
        ),
        fidelity_ladder=(
            FidelityTier(
                name="dry_run",
                kind="dry_run",
                cost_estimate_usd=0.0,
                expected_runtime_seconds=1.0,
                kill_threshold=1.0,
            ),
        ),
        seed_set=(7,),
        success_metric="force_balance_residual",
        kill_criteria=("solver_residual_norm <= 1.0",),
    )
