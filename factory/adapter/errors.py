"""Adapter error taxonomy."""

from __future__ import annotations

from factory.artifacts import FactoryError


class AdapterError(FactoryError):
    """Base exception for the adapter module."""


class AdapterNotRegistered(AdapterError):
    """Raised when no adapter is registered for a simulator id."""


class AdapterContractViolation(AdapterError):
    """Raised when an adapter violates the declared run-artifact contract."""


class AdapterRuntimeFailure(AdapterError):
    """Raised when the simulator runtime fails after adapter validation."""


class SimulatorConfigInvalid(AdapterError):
    """Raised when an ExperimentSpec cannot be translated for a simulator."""


__all__ = [
    "AdapterContractViolation",
    "AdapterError",
    "AdapterNotRegistered",
    "AdapterRuntimeFailure",
    "SimulatorConfigInvalid",
]
