from __future__ import annotations

from pathlib import Path

from factory.surrogate.api import (
    SURROGATE_CHECKPOINT_VERSION,
    KNearestSurrogateModel,
    TrainingExample,
    load_surrogate_checkpoint,
    rollback_surrogate_checkpoint,
    save_surrogate_checkpoint,
    train_knn_surrogate,
)


def _model(offset: float) -> KNearestSurrogateModel:
    return train_knn_surrogate(
        (
            TrainingExample(features=(0.0, offset), target=offset),
            TrainingExample(features=(1.0, offset), target=offset + 1.0),
        ),
        k=1,
    )


def test_checkpoint_versioning_and_rollback(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "surrogate.json"
    first_model = _model(0.0)
    second_model = _model(10.0)

    first_checkpoint = save_surrogate_checkpoint(
        first_model,
        checkpoint_path,
        model_id="first",
        created_at_utc="2026-05-23T00:00:00+00:00",
    )
    second_checkpoint = save_surrogate_checkpoint(
        second_model,
        checkpoint_path,
        model_id="second",
        created_at_utc="2026-05-23T00:01:00+00:00",
    )

    loaded = load_surrogate_checkpoint(checkpoint_path)
    assert first_checkpoint.version == SURROGATE_CHECKPOINT_VERSION
    assert second_checkpoint.parent_checkpoint_sha256 is not None
    assert loaded.model_id == "second"
    assert loaded.model == second_model

    rolled_back = rollback_surrogate_checkpoint(checkpoint_path)
    assert rolled_back.model_id == "first"
    assert rolled_back.model == first_model
