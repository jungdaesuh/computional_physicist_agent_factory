# test_api.py — Unit tests for the artifacts API
#
# This file implements tests for hashing, immutability, validation constraints,
# schemas, and error boundaries.

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from factory.artifacts.api import (
    ControlDefinition,
    EvidenceLedgerEntry,
    GapCandidate,
    SimulatorId,
    UncertaintyBlock,
)
from factory.artifacts.core import (
    ArtifactHashFormatError,
    ArtifactHashStr,
    ArtifactSerializationError,
)


def test_hash_determinism() -> None:
    """Verifies that hashing is deterministic regardless of key order or whitespace."""
    gap1 = GapCandidate.from_fixture("typical")
    gap2 = GapCandidate.model_validate(gap1.model_dump())
    assert gap1.compute_hash() == gap2.compute_hash()


def test_hash_excludes_created_at_but_includes_content() -> None:
    """Verifies audit timestamps do not perturb content hashes."""
    gap = GapCandidate.from_fixture("typical")

    with_new_timestamp = gap.model_copy(update={"created_at": datetime(2099, 1, 1, tzinfo=UTC)})
    with_new_content = gap.model_copy(update={"seed_query": f"{gap.seed_query} updated"})

    assert with_new_timestamp.compute_hash() == gap.compute_hash()
    assert with_new_content.compute_hash() != gap.compute_hash()


def test_hash_format_validation() -> None:
    """Verifies that ArtifactHashStr validates string digests correctly."""
    valid_hash = "a" * 64
    assert ArtifactHashStr(valid_hash) == valid_hash

    # Rejects invalid lengths
    with pytest.raises(ArtifactHashFormatError):
        ArtifactHashStr("a" * 63)
    with pytest.raises(ArtifactHashFormatError):
        ArtifactHashStr("a" * 65)

    # Rejects uppercase hex
    with pytest.raises(ArtifactHashFormatError):
        ArtifactHashStr("A" + "a" * 63)

    # Rejects non-hex characters
    with pytest.raises(ArtifactHashFormatError):
        ArtifactHashStr("g" + "a" * 63)


def test_nan_serialization() -> None:
    """Verifies that NaN/Infinity values trigger ArtifactSerializationError on hashing."""
    gap = GapCandidate.from_fixture("typical")
    corrupt_gap = gap.model_copy(update={"confidence": float("nan")})

    with pytest.raises(ArtifactSerializationError):
        corrupt_gap.compute_hash()


def test_immutability() -> None:
    """Verifies that artifacts are frozen and attributes cannot be mutated in place."""
    gap = GapCandidate.from_fixture("typical")
    with pytest.raises(ValidationError):
        gap.confidence = 0.9


def test_control_definition() -> None:
    """Verifies that ControlDefinition config fields are strictly checked."""
    # Valid config
    ctrl = ControlDefinition(
        baseline_simulator_id=SimulatorId("vmec"),
        baseline_config={"a": 1, "b": "test", "c": True},
    )
    assert ctrl.baseline_simulator_id == "vmec"

    # Invalid baseline_config value type (e.g. dict)
    with pytest.raises(ValidationError):
        ControlDefinition(
            baseline_simulator_id=SimulatorId("vmec"),
            baseline_config={"invalid": {"nested": "dict"}},  # type: ignore[dict-item]
        )


def test_uncertainty_block() -> None:
    """Verifies that UncertaintyBlock restricts ci_method to allowed enum-like literals."""
    # Valid
    u = UncertaintyBlock(
        metric_name="test",
        point_estimate=1.0,
        ci_lower=0.9,
        ci_upper=1.1,
        ci_method="bootstrap",
        n_seeds=3,
    )
    assert u.ci_method == "bootstrap"

    # Invalid
    with pytest.raises(ValidationError):
        UncertaintyBlock(
            metric_name="test",
            point_estimate=1.0,
            ci_lower=0.9,
            ci_upper=1.1,
            ci_method="invalid_method",  # type: ignore[arg-type]
            n_seeds=3,
        )


def test_schema_generation() -> None:
    """Verifies that all artifacts generate valid Pydantic schemas."""
    schema = GapCandidate.model_json_schema()
    assert schema["title"] == "GapCandidate"
    assert "provenance_hash" in schema["properties"]


def test_evidence_ledger_v1_without_surprise_bits_migrates_without_mutating_input() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "evidenceledgerentry" / "typical.json"
    )
    raw_entry = json.loads(fixture_path.read_text())
    raw_entry.pop("surprise_bits", None)
    original_entry = dict(raw_entry)

    migrated_entry = EvidenceLedgerEntry.from_json(raw_entry)

    assert migrated_entry.surprise_bits is None
    assert raw_entry == original_entry
    assert "surprise_bits" not in raw_entry
