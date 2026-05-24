"""Cross-simulator validation checker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class CrossSimulatorCheck:
    """Comparison of one observable across two simulator backends."""

    observable: str
    primary_value: float
    secondary_value: float
    tolerance: float
    tolerance_kind: Literal["absolute", "relative", "mixed"]


@dataclass(frozen=True)
class CrossSimulatorCheckResult:
    """Result for one cross-simulator observable comparison."""

    observable: str
    delta: float
    tolerance: float
    passed: bool


def check_cross_simulator(check: CrossSimulatorCheck) -> CrossSimulatorCheckResult:
    """Evaluate a cross-simulator comparison with the requested tolerance policy."""
    delta = abs(check.primary_value - check.secondary_value)
    if check.tolerance_kind == "absolute":
        threshold = check.tolerance
    elif check.tolerance_kind == "relative":
        threshold = abs(check.primary_value) * check.tolerance
    else:
        threshold = max(check.tolerance, abs(check.primary_value) * check.tolerance)

    return CrossSimulatorCheckResult(
        observable=check.observable,
        delta=delta,
        tolerance=threshold,
        passed=delta <= threshold,
    )


__all__ = ["CrossSimulatorCheck", "CrossSimulatorCheckResult", "check_cross_simulator"]
