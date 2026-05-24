"""Physics conservation check helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConservationQuantity:
    """Initial and final value for one conserved quantity."""

    name: str
    initial_value: float
    final_value: float
    tolerance: float


@dataclass(frozen=True)
class ConservationCheck:
    """Result of one conservation-law residual check."""

    name: str
    residual: float
    tolerance: float
    passed: bool


def check_conservation(quantity: ConservationQuantity) -> ConservationCheck:
    """Return an absolute residual check for one conserved quantity."""
    residual = abs(quantity.final_value - quantity.initial_value)
    return ConservationCheck(
        name=quantity.name,
        residual=residual,
        tolerance=quantity.tolerance,
        passed=residual <= quantity.tolerance,
    )


__all__ = ["ConservationCheck", "ConservationQuantity", "check_conservation"]
