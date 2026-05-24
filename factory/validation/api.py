"""Public implementation contract for the validation module."""

from __future__ import annotations

from factory.module_contracts import ModuleContract
from factory.validation.conservation import (
    ConservationCheck,
    ConservationQuantity,
    check_conservation,
)
from factory.validation.cross_sim import (
    CrossSimulatorCheck,
    CrossSimulatorCheckResult,
    check_cross_simulator,
)
from factory.validation.extrapolation import (
    RichardsonEstimate,
    limit_case_passes,
    richardson_extrapolate,
)

MODULE_CONTRACT = ModuleContract(
    module_name="validation",
    spec_id="009",
    responsibility="Aggregate deterministic physics, numerical, and statistical validation checks.",
    required_inputs=(
        "ExperimentSpec",
        "RunOutputs",
    ),
    produced_outputs=("ValidationResult",),
)


def describe_contract() -> ModuleContract:
    """Return the stable public contract for this module."""
    return MODULE_CONTRACT


__all__ = [
    "ConservationCheck",
    "ConservationQuantity",
    "CrossSimulatorCheck",
    "CrossSimulatorCheckResult",
    "MODULE_CONTRACT",
    "RichardsonEstimate",
    "check_conservation",
    "check_cross_simulator",
    "describe_contract",
    "limit_case_passes",
    "richardson_extrapolate",
]
