"""Richardson extrapolation and limiting-case helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RichardsonEstimate:
    """Estimated continuum value from two grid spacings."""

    extrapolated_value: float
    observed_order: float
    residual: float


def richardson_extrapolate(
    coarse_value: float,
    fine_value: float,
    *,
    refinement_ratio: float,
    observed_order: float,
) -> RichardsonEstimate:
    """Estimate the zero-grid-spacing value using Richardson extrapolation."""
    if refinement_ratio <= 1.0:
        raise ValueError("refinement_ratio must be greater than 1")
    if observed_order <= 0.0:
        raise ValueError("observed_order must be positive")

    denominator = refinement_ratio**observed_order - 1.0
    correction = (fine_value - coarse_value) / denominator
    extrapolated = fine_value + correction
    return RichardsonEstimate(
        extrapolated_value=extrapolated,
        observed_order=observed_order,
        residual=abs(correction),
    )


def limit_case_passes(observed: float, expected: float, *, tolerance: float) -> bool:
    """Return whether an observed value recovers a known limiting case."""
    return abs(observed - expected) <= tolerance


__all__ = ["RichardsonEstimate", "limit_case_passes", "richardson_extrapolate"]
