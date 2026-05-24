"""Small deterministic PCA+kNN surrogate training."""

from __future__ import annotations

import math
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TrainingExample(BaseModel):
    """One supervised surrogate training row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    features: tuple[float, ...]
    target: float


class SurrogatePrediction(BaseModel):
    """Prediction and local posterior variance from a trained kNN surrogate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    predicted_value: float
    posterior_variance: float
    neighbor_distances: tuple[float, ...]


class KNearestSurrogateModel(BaseModel):
    """A calibrated kNN surrogate with PCA projection owned by the model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    k: int = Field(ge=1)
    feature_dimension: int = Field(ge=1)
    pca_dimension: int = Field(ge=1, le=20)
    feature_means: tuple[float, ...]
    pca_components: tuple[tuple[float, ...], ...]
    projected_features: tuple[tuple[float, ...], ...]
    targets: tuple[float, ...]
    loo_residuals: tuple[float, ...]
    calibration_rmse: float

    @model_validator(mode="after")
    def _validate_model_shape(self) -> Self:
        if len(self.feature_means) != self.feature_dimension:
            raise ValueError("feature_means length must match feature_dimension")
        if len(self.pca_components) != self.pca_dimension:
            raise ValueError("pca_components length must match pca_dimension")
        if len(self.projected_features) != len(self.targets):
            raise ValueError("projected_features and targets must have the same length")
        if len(self.loo_residuals) != len(self.targets):
            raise ValueError("loo_residuals and targets must have the same length")
        for component in self.pca_components:
            if len(component) != self.feature_dimension:
                raise ValueError("each pca component must match feature_dimension")
        for projected_feature in self.projected_features:
            if len(projected_feature) != self.pca_dimension:
                raise ValueError("each projected feature must match pca_dimension")
        return self

    def predict(self, features: tuple[float, ...]) -> SurrogatePrediction:
        """Predict from the calibrated model using inverse-distance kNN weights."""
        projected = _project_features(features, self.feature_means, self.pca_components)
        neighbor_indices = _nearest_indices(projected, self.projected_features, self.k)
        predicted_value = _weighted_prediction(projected, neighbor_indices, self)
        neighbor_targets = tuple(self.targets[index] for index in neighbor_indices)
        local_variance = _population_variance(neighbor_targets)
        return SurrogatePrediction(
            predicted_value=predicted_value,
            posterior_variance=local_variance + self.calibration_rmse * self.calibration_rmse,
            neighbor_distances=tuple(
                _euclidean_distance(projected, self.projected_features[index])
                for index in neighbor_indices
            ),
        )


def train_knn_surrogate(
    examples: tuple[TrainingExample, ...],
    *,
    k: int = 3,
    max_pca_dimension: int = 20,
) -> KNearestSurrogateModel:
    """Train a deterministic PCA-reduced kNN surrogate and LOO calibration."""
    if not examples:
        raise ValueError("at least one TrainingExample is required")
    if k < 1:
        raise ValueError("k must be at least 1")
    if max_pca_dimension < 1 or max_pca_dimension > 20:
        raise ValueError("max_pca_dimension must be between 1 and 20")

    feature_dimension = len(examples[0].features)
    if feature_dimension < 1:
        raise ValueError("TrainingExample.features must not be empty")
    _validate_examples(examples, feature_dimension)

    feature_rows = tuple(example.features for example in examples)
    targets = tuple(example.target for example in examples)
    feature_means = _column_means(feature_rows)
    centered_rows = tuple(_subtract(row, feature_means) for row in feature_rows)
    pca_components = _pca_components(centered_rows, min(max_pca_dimension, feature_dimension))
    projected_features = tuple(_project_centered(row, pca_components) for row in centered_rows)
    effective_k = min(k, len(examples))
    loo_residuals = _leave_one_out_residuals(projected_features, targets, effective_k)

    return KNearestSurrogateModel(
        k=effective_k,
        feature_dimension=feature_dimension,
        pca_dimension=len(pca_components),
        feature_means=feature_means,
        pca_components=pca_components,
        projected_features=projected_features,
        targets=targets,
        loo_residuals=loo_residuals,
        calibration_rmse=_root_mean_square(loo_residuals),
    )


def _validate_examples(examples: tuple[TrainingExample, ...], feature_dimension: int) -> None:
    for index, example in enumerate(examples):
        if len(example.features) != feature_dimension:
            raise ValueError(f"TrainingExample at index {index} has inconsistent feature dimension")
        for value in (*example.features, example.target):
            if not math.isfinite(value):
                raise ValueError(f"TrainingExample at index {index} contains a non-finite value")


def _column_means(rows: tuple[tuple[float, ...], ...]) -> tuple[float, ...]:
    row_count = len(rows)
    return tuple(sum(row[column] for row in rows) / row_count for column in range(len(rows[0])))


def _subtract(row: tuple[float, ...], means: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(value - means[index] for index, value in enumerate(row))


def _pca_components(
    centered_rows: tuple[tuple[float, ...], ...], component_count: int
) -> tuple[tuple[float, ...], ...]:
    feature_dimension = len(centered_rows[0])
    if feature_dimension <= component_count:
        return tuple(
            tuple(
                1.0 if row_index == column_index else 0.0
                for column_index in range(feature_dimension)
            )
            for row_index in range(feature_dimension)
        )

    covariance = _covariance_matrix(centered_rows)
    components: list[tuple[float, ...]] = []
    working = tuple(tuple(value for value in row) for row in covariance)
    for component_index in range(component_count):
        vector = _dominant_eigenvector(working, component_index)
        eigenvalue = _quadratic_form(working, vector)
        if eigenvalue <= 0.0:
            break
        components.append(vector)
        working = _deflate(working, vector, eigenvalue)

    if components:
        return tuple(components)
    return (tuple(1.0 if index == 0 else 0.0 for index in range(feature_dimension)),)


def _covariance_matrix(
    centered_rows: tuple[tuple[float, ...], ...],
) -> tuple[tuple[float, ...], ...]:
    denominator = max(1, len(centered_rows) - 1)
    feature_dimension = len(centered_rows[0])
    return tuple(
        tuple(
            sum(row[left] * row[right] for row in centered_rows) / denominator
            for right in range(feature_dimension)
        )
        for left in range(feature_dimension)
    )


def _dominant_eigenvector(
    matrix: tuple[tuple[float, ...], ...], component_index: int
) -> tuple[float, ...]:
    dimension = len(matrix)
    vector = _normalize(
        tuple(1.0 / float(column + component_index + 1) for column in range(dimension))
    )
    for _ in range(50):
        candidate = _matrix_vector_product(matrix, vector)
        norm = _vector_norm(candidate)
        if norm == 0.0:
            return vector
        vector = tuple(value / norm for value in candidate)
    return vector


def _matrix_vector_product(
    matrix: tuple[tuple[float, ...], ...], vector: tuple[float, ...]
) -> tuple[float, ...]:
    return tuple(
        sum(row[column] * vector[column] for column in range(len(vector))) for row in matrix
    )


def _quadratic_form(matrix: tuple[tuple[float, ...], ...], vector: tuple[float, ...]) -> float:
    product = _matrix_vector_product(matrix, vector)
    return sum(vector[index] * product[index] for index in range(len(vector)))


def _deflate(
    matrix: tuple[tuple[float, ...], ...], vector: tuple[float, ...], eigenvalue: float
) -> tuple[tuple[float, ...], ...]:
    dimension = len(vector)
    return tuple(
        tuple(
            matrix[row][column] - eigenvalue * vector[row] * vector[column]
            for column in range(dimension)
        )
        for row in range(dimension)
    )


def _normalize(vector: tuple[float, ...]) -> tuple[float, ...]:
    norm = _vector_norm(vector)
    if norm == 0.0:
        raise ValueError("cannot normalize a zero vector")
    return tuple(value / norm for value in vector)


def _vector_norm(vector: tuple[float, ...]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def _project_features(
    features: tuple[float, ...],
    feature_means: tuple[float, ...],
    pca_components: tuple[tuple[float, ...], ...],
) -> tuple[float, ...]:
    if len(features) != len(feature_means):
        raise ValueError("feature dimension does not match trained surrogate model")
    return _project_centered(_subtract(features, feature_means), pca_components)


def _project_centered(
    centered_features: tuple[float, ...], pca_components: tuple[tuple[float, ...], ...]
) -> tuple[float, ...]:
    return tuple(
        sum(centered_features[index] * component[index] for index in range(len(centered_features)))
        for component in pca_components
    )


def _leave_one_out_residuals(
    projected_features: tuple[tuple[float, ...], ...],
    targets: tuple[float, ...],
    k: int,
) -> tuple[float, ...]:
    if len(projected_features) == 1:
        return (0.0,)

    residuals: list[float] = []
    for holdout_index, projected_feature in enumerate(projected_features):
        neighbor_indices = _nearest_indices_excluding(
            projected_feature,
            projected_features,
            min(k, len(projected_features) - 1),
            holdout_index,
        )
        prediction = _weighted_target_prediction(
            projected_feature,
            neighbor_indices,
            projected_features,
            targets,
        )
        residuals.append(prediction - targets[holdout_index])
    return tuple(residuals)


def _nearest_indices(
    projected_feature: tuple[float, ...],
    projected_features: tuple[tuple[float, ...], ...],
    k: int,
) -> tuple[int, ...]:
    return tuple(
        index
        for _, index in sorted(
            (_euclidean_distance(projected_feature, row), index)
            for index, row in enumerate(projected_features)
        )[:k]
    )


def _nearest_indices_excluding(
    projected_feature: tuple[float, ...],
    projected_features: tuple[tuple[float, ...], ...],
    k: int,
    excluded_index: int,
) -> tuple[int, ...]:
    return tuple(
        index
        for _, index in sorted(
            (_euclidean_distance(projected_feature, row), index)
            for index, row in enumerate(projected_features)
            if index != excluded_index
        )[:k]
    )


def _weighted_prediction(
    projected_feature: tuple[float, ...],
    neighbor_indices: tuple[int, ...],
    model: KNearestSurrogateModel,
) -> float:
    return _weighted_target_prediction(
        projected_feature,
        neighbor_indices,
        model.projected_features,
        model.targets,
    )


def _weighted_target_prediction(
    projected_feature: tuple[float, ...],
    neighbor_indices: tuple[int, ...],
    projected_features: tuple[tuple[float, ...], ...],
    targets: tuple[float, ...],
) -> float:
    exact_matches = tuple(
        index
        for index in neighbor_indices
        if _euclidean_distance(projected_feature, projected_features[index]) == 0.0
    )
    if exact_matches:
        return sum(targets[index] for index in exact_matches) / len(exact_matches)

    weighted_sum = 0.0
    total_weight = 0.0
    for index in neighbor_indices:
        distance = _euclidean_distance(projected_feature, projected_features[index])
        weight = 1.0 / distance
        weighted_sum += weight * targets[index]
        total_weight += weight
    return weighted_sum / total_weight


def _euclidean_distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return math.sqrt(sum((left[index] - right[index]) ** 2 for index in range(len(left))))


def _population_variance(values: tuple[float, ...]) -> float:
    if len(values) <= 1:
        return 0.0
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


def _root_mean_square(values: tuple[float, ...]) -> float:
    return math.sqrt(sum(value * value for value in values) / len(values))


__all__ = [
    "KNearestSurrogateModel",
    "SurrogatePrediction",
    "TrainingExample",
    "train_knn_surrogate",
]
