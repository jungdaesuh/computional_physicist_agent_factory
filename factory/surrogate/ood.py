"""Out-of-distribution threshold calibration for surrogate probes."""

from __future__ import annotations

import math
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OODCalibration(BaseModel):
    """Percentile threshold derived from calibration distances."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    percentile: float = Field(ge=0.0, le=100.0)
    threshold: float
    calibration_distances: tuple[float, ...]

    @model_validator(mode="after")
    def _validate_calibration_distances(self) -> Self:
        if not self.calibration_distances:
            raise ValueError("calibration_distances must not be empty")
        return self


class OODClassification(BaseModel):
    """OOD verdict for one candidate distance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    distance: float
    percentile: float
    threshold: float
    is_ood: bool


def calibrate_ood_threshold(
    calibration_distances: tuple[float, ...],
    *,
    percentile: float,
) -> OODCalibration:
    """Calibrate an OOD threshold at the requested empirical percentile."""
    if not calibration_distances:
        raise ValueError("calibration_distances must not be empty")
    if percentile < 0.0 or percentile > 100.0:
        raise ValueError("percentile must be between 0 and 100")
    for distance in calibration_distances:
        if distance < 0.0 or not math.isfinite(distance):
            raise ValueError("calibration_distances must be finite non-negative values")

    sorted_distances = tuple(sorted(calibration_distances))
    threshold = _percentile_value(sorted_distances, percentile)
    return OODCalibration(
        percentile=percentile,
        threshold=threshold,
        calibration_distances=sorted_distances,
    )


def classify_ood(distance: float, calibration: OODCalibration) -> OODClassification:
    """Classify a candidate as OOD when it exceeds the calibrated threshold."""
    if distance < 0.0 or not math.isfinite(distance):
        raise ValueError("distance must be a finite non-negative value")
    percentile = (
        100.0
        * sum(
            calibration_distance <= distance
            for calibration_distance in calibration.calibration_distances
        )
        / len(calibration.calibration_distances)
    )
    return OODClassification(
        distance=distance,
        percentile=percentile,
        threshold=calibration.threshold,
        is_ood=distance > calibration.threshold,
    )


def _percentile_value(sorted_values: tuple[float, ...], percentile: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (percentile / 100.0) * (len(sorted_values) - 1)
    lower_index = math.floor(rank)
    upper_index = math.ceil(rank)
    if lower_index == upper_index:
        return sorted_values[lower_index]
    lower_weight = upper_index - rank
    upper_weight = rank - lower_index
    return sorted_values[lower_index] * lower_weight + sorted_values[upper_index] * upper_weight


__all__ = [
    "OODCalibration",
    "OODClassification",
    "calibrate_ood_threshold",
    "classify_ood",
]
