# test_artifacts_typical_usage.py — Integration-style test showing typical usage
#
# This test demonstrates loading every artifact type from its fixture,
# performing validation, verifying the provenance hash, and checking serialization.

import logging

import pytest

from factory.artifacts.api import (
    ArtifactValidationError,
    Budget,
    CouncilVerdict,
    DomainScope,
    EvidenceLedgerEntry,
    ExperimentSpec,
    FactoryControlEvent,
    GapCandidate,
    HypothesisSpec,
    RunReport,
    Strategy,
    StrategyCycleEvidence,
    SurrogateProbeResult,
    ValidationResult,
    _ArtifactBase,
)

logger = logging.getLogger("factory.artifacts.tests.typical_usage")


def test_artifacts_typical_usage() -> None:
    """Verifies that all 13 artifacts can be loaded from their typical fixtures and verified."""
    logger.info("Running test_artifacts_typical_usage")

    artifact_classes: tuple[type[_ArtifactBase], ...] = (
        GapCandidate,
        HypothesisSpec,
        CouncilVerdict,
        ExperimentSpec,
        Budget,
        DomainScope,
        EvidenceLedgerEntry,
        RunReport,
        ValidationResult,
        SurrogateProbeResult,
        FactoryControlEvent,
        Strategy,
        StrategyCycleEvidence,
    )

    for cls in artifact_classes:
        logger.info("Testing typical usage of %s", cls.__name__)
        # 1. Load the typical fixture
        artifact = cls.from_fixture("typical")
        assert artifact is not None
        assert artifact.artifact_type == cls.__name__

        # 2. Verify self (integrity check against provenance hash)
        artifact.verify_self()

        # 3. Test round-trip serialization
        raw_json = artifact.model_dump_json()
        reloaded = cls.from_json(raw_json)
        assert reloaded.provenance_hash == artifact.provenance_hash
        assert reloaded.compute_hash() == artifact.compute_hash()

        # Verify edge fixture loads correctly
        edge_artifact = cls.from_fixture("edge")
        assert edge_artifact is not None
        edge_artifact.verify_self()

        # Verify malformed fixture raises validation error
        with pytest.raises(ArtifactValidationError):
            cls.from_fixture("malformed")
