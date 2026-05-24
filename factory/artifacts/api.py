# api.py — Consolidated Public Exports for Typed Artifacts
#
# This file imports and re-exports all 13 core artifacts, helper types, enums,
# and exceptions defined across the artifacts module, acting as the single public
# boundary for other modules.

from __future__ import annotations

import logging

from factory.artifacts.compression import (
    SUPPORTED_COMPRESSION_ALGORITHMS,
    CompressionAlgorithm,
    compress_bytes,
    compress_path,
    decompress_bytes,
    decompress_path,
    read_compressed_artifact,
    read_compressed_bytes,
    write_compressed_artifact,
    write_compressed_bytes,
)
from factory.artifacts.core import (
    ArtifactHash,
    ArtifactHashStr,
    ArtifactImmutabilityViolation,
    ArtifactProvenanceMismatch,
    ArtifactSerializationError,
    ArtifactValidationError,
    CycleId,
    FactoryError,
    FixtureNotFoundError,
    HypothesisId,
    SimulatorId,
    _ArtifactBase,
)
from factory.artifacts.dedup import (
    ContentAddressedStore,
    DedupStoreEntry,
    sha256_bytes,
)
from factory.artifacts.results import (
    CheckOutcome,
    CouncilId,
    CouncilVerdict,
    CrossSimulatorComparison,
    DissentEntry,
    EvidenceLedgerEntry,
    EvidenceResult,
    FactoryControlEvent,
    PersonaName,
    ProvenanceBlock,
    RelitigationTrigger,
    RunReport,
    SurrogateProbeResult,
    UncertaintyBlock,
    ValidationResult,
)
from factory.artifacts.specifications import (
    Budget,
    BudgetLedgerEntry,
    ControlDefinition,
    DomainScope,
    ExperimentSpec,
    FidelityTier,
    GapCandidate,
    GapType,
    HypothesisSpec,
)
from factory.artifacts.strategies import (
    BehaviorDescriptor,
    ConstraintOvershootStats,
    Strategy,
    StrategyCycleEvidence,
    StrategyKind,
)

logger = logging.getLogger("factory.artifacts.api")

__all__ = [
    # Core types & exceptions
    "ArtifactHash",
    "ArtifactHashStr",
    "HypothesisId",
    "CycleId",
    "SimulatorId",
    "FactoryError",
    "ArtifactValidationError",
    "ArtifactProvenanceMismatch",
    "ArtifactImmutabilityViolation",
    "ArtifactSerializationError",
    "FixtureNotFoundError",
    "_ArtifactBase",
    "ContentAddressedStore",
    "DedupStoreEntry",
    "sha256_bytes",
    # Enums
    "GapType",
    "PersonaName",
    "CouncilId",
    "EvidenceResult",
    "StrategyKind",
    # Supporting sub-models
    "ControlDefinition",
    "FidelityTier",
    "BudgetLedgerEntry",
    "DissentEntry",
    "UncertaintyBlock",
    "RelitigationTrigger",
    "ProvenanceBlock",
    "CheckOutcome",
    "CrossSimulatorComparison",
    "BehaviorDescriptor",
    "ConstraintOvershootStats",
    "CompressionAlgorithm",
    "SUPPORTED_COMPRESSION_ALGORITHMS",
    "compress_bytes",
    "decompress_bytes",
    "write_compressed_bytes",
    "read_compressed_bytes",
    "compress_path",
    "decompress_path",
    "write_compressed_artifact",
    "read_compressed_artifact",
    # Core 13 Artifacts
    "GapCandidate",
    "HypothesisSpec",
    "CouncilVerdict",
    "ExperimentSpec",
    "Budget",
    "DomainScope",
    "EvidenceLedgerEntry",
    "RunReport",
    "ValidationResult",
    "SurrogateProbeResult",
    "FactoryControlEvent",
    "Strategy",
    "StrategyCycleEvidence",
]
