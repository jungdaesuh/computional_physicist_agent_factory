"""Shared implementation for built-in reference adapters."""

from __future__ import annotations

from pathlib import Path

from factory.adapter.abstract import (
    AcceptanceController,
    Adapter,
    BlueprintComponents,
    ConstraintAggregator,
    ConstraintHandle,
    DiscretizationHandle,
    Discretizer,
    LocalPolisher,
    RestartController,
    SolverState,
    UpdateStepOperator,
)
from factory.adapter.errors import AdapterContractViolation, SimulatorConfigInvalid
from factory.adapter.types import (
    AdapterOutputField,
    AdapterOutputSchema,
    RunArtifacts,
    adapter_output_dir,
    assert_output_schema_satisfied,
)
from factory.artifacts import ExperimentSpec


class ReferenceDiscretizer(Discretizer):
    """Map an ExperimentSpec and tier name into deterministic degrees of freedom."""

    def configure(self, spec: ExperimentSpec, tier_name: str) -> DiscretizationHandle:
        controls = spec.control_definition.baseline_config
        scale = _numeric_control(controls, "scale", default=1.0)
        return DiscretizationHandle(
            tier_name=tier_name,
            degrees_of_freedom=(scale, float(len(spec.seed_set)), float(len(spec.fidelity_ladder))),
            metadata={"success_metric": spec.success_metric},
        )


class ReferenceConstraintAggregator(ConstraintAggregator):
    """Assemble constraint residuals from the experiment kill criteria."""

    def assemble(self, spec: ExperimentSpec, disc: DiscretizationHandle) -> ConstraintHandle:
        residuals = dict.fromkeys(spec.kill_criteria, 0.0)
        return ConstraintHandle(
            residuals=residuals,
            metadata={"tier_name": disc.tier_name},
        )


class ReferenceUpdateStepOperator(UpdateStepOperator):
    """Take one monotone objective-improving step for the reference adapters."""

    def step(self, state: SolverState) -> SolverState:
        return state.with_update(objective=state.objective * 0.5)


class ReferenceAcceptanceController(AcceptanceController):
    """Accept only non-worsening proposed states."""

    def accept(self, prev: SolverState, proposed: SolverState) -> SolverState:
        if proposed.objective <= prev.objective:
            return proposed
        return prev


class ReferenceRestartController(RestartController):
    """Restart after three non-improving states."""

    def should_restart(self, history: tuple[SolverState, ...]) -> bool:
        if len(history) < 3:
            return False
        last_three = history[-3:]
        return all(state.objective >= last_three[0].objective for state in last_three)

    def reseed(self, history: tuple[SolverState, ...]) -> SolverState:
        if not history:
            raise SimulatorConfigInvalid("cannot reseed without solver history")
        first = history[0]
        return first.with_update(metadata={**first.metadata, "restarted": True})


class ReferenceLocalPolisher(LocalPolisher):
    """Apply the final reference local-polish objective reduction."""

    def polish(self, state: SolverState) -> SolverState:
        return state.with_update(objective=state.objective * 0.9)


class ReferenceAdapter(Adapter):
    """Reference adapter that persists deterministic RunArtifacts under the sandbox."""

    simulator_id = ""
    simulator_version = "reference-1.0"
    container_sha = "sha256:reference"
    metric_offset = 0.0

    def components(self) -> BlueprintComponents:
        return BlueprintComponents(
            discretizer=ReferenceDiscretizer(),
            constraint_aggregator=ReferenceConstraintAggregator(),
            update_step_operator=ReferenceUpdateStepOperator(),
            acceptance_controller=ReferenceAcceptanceController(),
            restart_controller=ReferenceRestartController(),
            local_polisher=ReferenceLocalPolisher(),
        )

    def output_schema(self) -> AdapterOutputSchema:
        return AdapterOutputSchema(
            simulator_id=self.simulator_id,
            schema_version="1.0",
            canonical_tensor_filename="canonical.json",
            fields=(
                AdapterOutputField(
                    name="observables.success_metric",
                    dtype="float",
                    units=None,
                    description="Metric value for the ExperimentSpec success metric.",
                ),
                AdapterOutputField(
                    name="residuals.solver_residual_norm",
                    dtype="float",
                    units=None,
                    description="Reference convergence residual norm.",
                ),
                AdapterOutputField(
                    name="diagnostics.force_balance_residual",
                    dtype="float",
                    units=None,
                    description="Primary validation residual.",
                ),
                AdapterOutputField(
                    name="sandbox_paths.run_artifacts",
                    dtype="path",
                    units=None,
                    description="Canonical RunArtifacts JSON path.",
                ),
            ),
        )

    def run(self, experiment_spec: ExperimentSpec, sandbox_dir: Path) -> RunArtifacts:
        if experiment_spec.simulator_id != self.simulator_id:
            raise AdapterContractViolation(
                f"ExperimentSpec.simulator_id={experiment_spec.simulator_id!r} does not match "
                f"adapter {self.simulator_id!r}"
            )
        if not experiment_spec.seed_set:
            raise SimulatorConfigInvalid("ExperimentSpec.seed_set must contain at least one seed")

        seed = experiment_spec.seed_set[0]
        tier_name = experiment_spec.fidelity_ladder[0].name
        output_dir = adapter_output_dir(sandbox_dir, seed)
        run_artifacts_path = output_dir / "run_artifacts.json"
        metric_value = self._metric_value(experiment_spec)
        residual = self._residual_value(experiment_spec)
        artifacts = RunArtifacts(
            observables={
                experiment_spec.success_metric: metric_value,
                "success_metric": metric_value,
            },
            residuals={"solver_residual_norm": residual},
            diagnostics={
                "force_balance_residual": residual,
                "conservation_diagnostics": {"reference_invariant": residual},
                "refinement_grid_values": {"1.0": metric_value, "0.5": metric_value * 0.5},
                "div_B": residual * 0.1,
            },
            sandbox_paths={"run_artifacts": run_artifacts_path},
            seed=seed,
            fidelity_tier=tier_name,
            simulator_version=self.simulator_version,
            container_sha=self.container_sha,
            wall_clock_seconds=0.0,
            cost_usd=0.0,
            parent_experiment_hash=experiment_spec.provenance_hash,
        )
        assert_output_schema_satisfied(self.output_schema(), artifacts)
        artifacts.write_json(run_artifacts_path)
        return artifacts

    def _metric_value(self, experiment_spec: ExperimentSpec) -> float:
        controls = experiment_spec.control_definition.baseline_config
        return _numeric_control(controls, "metric_value", default=1.0) + self.metric_offset

    def _residual_value(self, experiment_spec: ExperimentSpec) -> float:
        controls = experiment_spec.control_definition.baseline_config
        return _numeric_control(controls, "solver_residual_norm", default=0.01)


class ReferenceMockAdapter(ReferenceAdapter):
    """Mock variant of the reference adapter that never invokes external simulator code."""


def _numeric_control(
    controls: dict[str, str | int | float | bool],
    key: str,
    *,
    default: float,
) -> float:
    value = controls.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SimulatorConfigInvalid(f"baseline_config.{key} must be numeric when provided")
    return float(value)


__all__ = [
    "ReferenceAcceptanceController",
    "ReferenceAdapter",
    "ReferenceConstraintAggregator",
    "ReferenceDiscretizer",
    "ReferenceLocalPolisher",
    "ReferenceMockAdapter",
    "ReferenceRestartController",
    "ReferenceUpdateStepOperator",
]
