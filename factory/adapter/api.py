"""Public implementation contract for the adapter module."""

from __future__ import annotations

from factory.adapter.abstract import (
    AcceptanceController,
    Adapter,
    ConstraintAggregator,
    ConstraintHandle,
    DiscretizationHandle,
    Discretizer,
    LocalPolisher,
    RestartController,
    SolverState,
    UpdateStepOperator,
)
from factory.adapter.registry import (
    load,
    load_all,
    register,
    register_mock,
    registered_ids,
    validate_catalog_parity,
)
from factory.adapter.simulators import sim_a as _sim_a
from factory.adapter.simulators import sim_b as _sim_b
from factory.adapter.types import AdapterOutputField, AdapterOutputSchema, RunArtifacts
from factory.module_contracts import ModuleContract

MODULE_CONTRACT = ModuleContract(
    module_name="adapter",
    spec_id="006",
    responsibility="Translate validated experiment specs into simulator-specific run requests.",
    required_inputs=(
        "ExperimentSpec",
        "SimulatorCatalogEntry",
    ),
    produced_outputs=("AdapterRunRequest",),
)


def describe_contract() -> ModuleContract:
    """Return the stable public contract for this module."""
    return MODULE_CONTRACT


_REGISTERED_SIMULATOR_MODULES = (_sim_a, _sim_b)

__all__ = [
    "AcceptanceController",
    "Adapter",
    "AdapterOutputField",
    "AdapterOutputSchema",
    "ConstraintAggregator",
    "ConstraintHandle",
    "DiscretizationHandle",
    "Discretizer",
    "LocalPolisher",
    "MODULE_CONTRACT",
    "RestartController",
    "RunArtifacts",
    "SolverState",
    "UpdateStepOperator",
    "describe_contract",
    "load",
    "load_all",
    "register",
    "register_mock",
    "registered_ids",
    "validate_catalog_parity",
]
