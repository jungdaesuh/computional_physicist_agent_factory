from __future__ import annotations

from factory.surrogate.api import TrainingExample, train_knn_surrogate


def _features(offset: float) -> tuple[float, ...]:
    return tuple(offset + float(index) for index in range(25))


def test_knn_training_caps_pca_dimension_and_records_loo_calibration() -> None:
    examples = (
        TrainingExample(features=_features(0.0), target=0.0),
        TrainingExample(features=_features(1.0), target=1.0),
        TrainingExample(features=_features(2.0), target=2.0),
        TrainingExample(features=_features(3.0), target=3.0),
    )

    model = train_knn_surrogate(examples, k=1)
    repeated_model = train_knn_surrogate(examples, k=1)

    assert model == repeated_model
    assert model.feature_dimension == 25
    assert model.pca_dimension <= 20
    assert len(model.loo_residuals) == len(examples)
    assert model.calibration_rmse >= 0.0

    prediction = model.predict(_features(2.0))
    assert prediction.predicted_value == 2.0
    assert prediction.posterior_variance >= model.calibration_rmse * model.calibration_rmse
