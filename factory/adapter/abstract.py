"""Abstract solver interfaces and per-simulator adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from pathlib import Path

from factory.adapter.types import AdapterOutputSchema, RunArtifacts
from factory.artifacts import ExperimentSpec

NumericVector = tuple[float, ...]
NumericMap = dict[str, float]
MetadataValue = str | int | float | bool | None


@dataclass(frozen=True)
class DiscretizationHandle:
    """Per-run discretization choices emitted by a simulator adapter."""

    tier_name: str
    degrees_of_freedom: NumericVector
    metadata: dict[str, MetadataValue]


@dataclass(frozen=True)
class ConstraintHandle:
    """Boundary and constraint residuals assembled for a discretized problem."""

    residuals: NumericMap
    metadata: dict[str, MetadataValue]


@dataclass(frozen=True)
class SolverState:
    """Immutable state vector and adapter metadata at one solver iteration."""

    vector: NumericVector
    objective: float
    constraints: NumericMap
    metadata: dict[str, MetadataValue]

    def with_update(
        self,
        *,
        vector: NumericVector | None = None,
        objective: float | None = None,
        constraints: NumericMap | None = None,
        metadata: dict[str, MetadataValue] | None = None,
    ) -> SolverState:
        """Return a copied state with selected fields replaced."""
        return replace(
            self,
            vector=self.vector if vector is None else vector,
            objective=self.objective if objective is None else objective,
            constraints=dict(self.constraints if constraints is None else constraints),
            metadata=dict(self.metadata if metadata is None else metadata),
        )


class Discretizer(ABC):
    """Module 1: choose grid, mesh, basis, or toy-vs-production tier within one run."""

    @abstractmethod
    def configure(self, spec: ExperimentSpec, tier_name: str) -> DiscretizationHandle:
        """Return the discretization handle for this simulator and tier."""


class ConstraintAggregator(ABC):
    """Module 2: assemble boundary and constraint information for one run."""

    @abstractmethod
    def assemble(self, spec: ExperimentSpec, disc: DiscretizationHandle) -> ConstraintHandle:
        """Return the constraint handle consumed by update operators."""


class UpdateStepOperator(ABC):
    """Module 3: advance the current solver state by one candidate step."""

    @abstractmethod
    def step(self, state: SolverState) -> SolverState:
        """Return a proposed next solver state."""


class AcceptanceController(ABC):
    """Module 4: apply globalization, damping, or trust-region acceptance."""

    @abstractmethod
    def accept(self, prev: SolverState, proposed: SolverState) -> SolverState:
        """Return the accepted next solver state."""


class RestartController(ABC):
    """Module 5: decide whether stalled solver history should restart."""

    @abstractmethod
    def should_restart(self, history: tuple[SolverState, ...]) -> bool:
        """Return whether the solver should restart from its history."""

    @abstractmethod
    def reseed(self, history: tuple[SolverState, ...]) -> SolverState:
        """Return the solver state used after a restart decision."""


class LocalPolisher(ABC):
    """Module 6: apply final local refinement to an accepted state."""

    @abstractmethod
    def polish(self, state: SolverState) -> SolverState:
        """Return the polished solver state."""


@dataclass(frozen=True)
class BlueprintComponents:
    """Six concrete solver components bound to one simulator adapter."""

    discretizer: Discretizer
    constraint_aggregator: ConstraintAggregator
    update_step_operator: UpdateStepOperator
    acceptance_controller: AcceptanceController
    restart_controller: RestartController
    local_polisher: LocalPolisher


class Adapter(ABC):
    """Per-simulator adapter implementation registered by simulator_id."""

    simulator_id: str

    @abstractmethod
    def components(self) -> BlueprintComponents:
        """Return the six concrete components bound to this simulator."""

    @abstractmethod
    def output_schema(self) -> AdapterOutputSchema:
        """Declare the RunArtifacts fields produced by this adapter."""

    @abstractmethod
    def run(self, experiment_spec: ExperimentSpec, sandbox_dir: Path) -> RunArtifacts:
        """Execute the experiment inside the sandbox and return RunArtifacts."""


__all__ = [
    "AcceptanceController",
    "Adapter",
    "BlueprintComponents",
    "ConstraintAggregator",
    "ConstraintHandle",
    "DiscretizationHandle",
    "Discretizer",
    "LocalPolisher",
    "MetadataValue",
    "NumericMap",
    "NumericVector",
    "RestartController",
    "SolverState",
    "UpdateStepOperator",
]
