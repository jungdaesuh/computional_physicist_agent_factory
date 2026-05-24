from __future__ import annotations

from factory.surrogate.api import calibrate_ood_threshold, classify_ood


def test_ood_percentile_calibration_and_classification() -> None:
    calibration = calibrate_ood_threshold((1.0, 2.0, 3.0, 4.0), percentile=75.0)

    assert calibration.threshold == 3.25

    in_distribution = classify_ood(3.0, calibration)
    assert not in_distribution.is_ood
    assert in_distribution.percentile == 75.0

    out_of_distribution = classify_ood(4.0, calibration)
    assert out_of_distribution.is_ood
    assert out_of_distribution.percentile == 100.0
