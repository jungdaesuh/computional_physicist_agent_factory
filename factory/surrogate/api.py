"""Public implementation contract for the surrogate module."""

from __future__ import annotations

from factory.module_contracts import ModuleContract
from factory.surrogate.checkpoint import (
    SURROGATE_CHECKPOINT_VERSION,
    SurrogateCheckpoint,
    load_surrogate_checkpoint,
    rollback_surrogate_checkpoint,
    save_surrogate_checkpoint,
)
from factory.surrogate.ood import (
    OODCalibration,
    OODClassification,
    calibrate_ood_threshold,
    classify_ood,
)
from factory.surrogate.training import (
    KNearestSurrogateModel,
    SurrogatePrediction,
    TrainingExample,
    train_knn_surrogate,
)

MODULE_CONTRACT = ModuleContract(
    module_name="surrogate",
    spec_id="010",
    responsibility=(
        "Evaluate cheap surrogate probes before escalating candidates to oracle simulation."
    ),
    required_inputs=(
        "ExperimentSpec",
        "CandidateFeatures",
    ),
    produced_outputs=("SurrogateProbeResult",),
)


def describe_contract() -> ModuleContract:
    """Return the stable public contract for this module."""
    return MODULE_CONTRACT


__all__ = [
    "KNearestSurrogateModel",
    "MODULE_CONTRACT",
    "OODCalibration",
    "OODClassification",
    "SURROGATE_CHECKPOINT_VERSION",
    "SurrogateCheckpoint",
    "SurrogatePrediction",
    "TrainingExample",
    "calibrate_ood_threshold",
    "classify_ood",
    "describe_contract",
    "load_surrogate_checkpoint",
    "rollback_surrogate_checkpoint",
    "save_surrogate_checkpoint",
    "train_knn_surrogate",
]
