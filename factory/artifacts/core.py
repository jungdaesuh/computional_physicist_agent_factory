# core.py — Base classes, hashing, and exception hierarchy for Typed Artifacts
#
# This file provides the foundational types and base class (_ArtifactBase) for all
# 13 typed artifacts in the factory. It enforces SHA-256 content-addressed hashing
# and immutability via Pydantic.
#
# Use cases:
# 1. Computing SHA-256 hashes of Pydantic models deterministically.
# 2. Re-verifying artifact integrity via content-addressing check.
# 3. Disallowing NaN/Infinity values during JSON serialization to catch upstream numerical issues.

from __future__ import annotations

import hashlib
import json
import logging
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, NewType, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
)

from factory.artifacts.migration import migrate_artifact_json

logger = logging.getLogger("factory.artifacts.core")

# --------------------------------------------------------------------------
# Type aliases and primitive identifiers
# --------------------------------------------------------------------------

# A 64-character lowercase hex SHA-256 digest. Constructor validates at runtime.
ArtifactHash = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$", strip_whitespace=False, to_lower=False),
]

HypothesisId = NewType("HypothesisId", str)
CycleId = NewType("CycleId", str)
SimulatorId = NewType("SimulatorId", str)


class ArtifactHashStr(str):
    """SHA-256 digest as a validated string, constructed outside Pydantic."""

    _PATTERN = re.compile(r"^[0-9a-f]{64}$")

    def __new__(cls, value: str) -> ArtifactHashStr:
        logger.info("ArtifactHashStr.__new__(value=%r)", value)
        if not isinstance(value, str) or not cls._PATTERN.match(value):
            raise ArtifactHashFormatError(f"invalid hash format: {value!r}")
        return super().__new__(cls, value)


# --------------------------------------------------------------------------
# Exception hierarchy
# --------------------------------------------------------------------------


class FactoryError(Exception):
    """Base error class for the entire factory."""

    pass


class ArtifactValidationError(FactoryError):
    """Raised when an artifact fails schema validation."""

    pass


class ArtifactProvenanceMismatch(FactoryError):
    """Raised when an artifact's computed hash doesn't match its declared provenance_hash."""

    pass


class ArtifactImmutabilityViolation(FactoryError):
    """Raised when trying to mutate a frozen artifact field."""

    pass


class ArtifactHashFormatError(FactoryError):
    """Raised when a hash string is not a valid 64-char hex digest."""

    pass


class ArtifactSerializationError(FactoryError):
    """Raised when JSON serialization fails (e.g., NaN/Infinity encountered)."""

    pass


class FixtureNotFoundError(FactoryError):
    """Raised when a requested fixture is missing on disk."""

    pass


# --------------------------------------------------------------------------
# Base artifact class
# --------------------------------------------------------------------------


class _ArtifactBase(BaseModel):
    """Common base model for all factory artifacts.

    Enforces immutability and content-addressable provenance hashing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_type: str
    created_at: datetime
    provenance_hash: ArtifactHash
    parent_hashes: tuple[ArtifactHash, ...] = Field(default_factory=tuple)

    @classmethod
    def from_fixture(cls, name: str) -> Self:
        """Load a fixture under factory/artifacts/fixtures/<artifact_type>/<name>.json."""
        logger.info("from_fixture(cls=%s, name=%s)", cls.__name__, name)
        # Search relative to target directory
        fixture_path = (
            Path(__file__).resolve().parent / "fixtures" / cls.__name__.lower() / f"{name}.json"
        )
        if not fixture_path.exists():
            raise FixtureNotFoundError(f"Fixture {name} not found at {fixture_path}")
        with open(fixture_path, "rb") as f:
            data = json.load(f)
        return cls.from_json(data)

    @classmethod
    def from_json(cls, raw: str | bytes | dict[str, Any]) -> Self:
        """Parse and validate; raises ArtifactValidationError on failure."""
        logger.info("from_json(cls=%s)", cls.__name__)
        try:
            data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
            if not isinstance(data, dict):
                raise ArtifactValidationError(
                    f"Validation failed for {cls.__name__}: expected JSON object"
                )
            migrated_data = migrate_artifact_json(deepcopy(data))
            return cls.model_validate(migrated_data)
        except Exception as e:
            raise ArtifactValidationError(f"Validation failed for {cls.__name__}: {e}") from e

    def to_canonical_json(self) -> bytes:
        """Deterministic JSON serialization for hashing.

        Audit metadata is excluded; keys are sorted, whitespace is stripped,
        and NaN/Infinity is disallowed.
        """
        logger.info("to_canonical_json(self=%s)", self.__class__.__name__)
        # Mode='json' serializes datetime, Enum, and nested models properly
        payload = self.model_dump(exclude={"provenance_hash", "created_at"}, mode="json")
        try:
            canonical = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            return canonical.encode("utf-8")
        except ValueError as e:
            raise ArtifactSerializationError(
                f"Serialization failed for {self.__class__.__name__} due to invalid value "
                f"(e.g. NaN/Inf): {e}"
            ) from e

    def compute_hash(self) -> ArtifactHash:
        """SHA-256 of canonical JSON excluding provenance_hash and created_at."""
        logger.info("compute_hash(self=%s)", self.__class__.__name__)
        canonical_bytes = self.to_canonical_json()
        return hashlib.sha256(canonical_bytes).hexdigest()

    def verify_self(self) -> None:
        """Raise ArtifactProvenanceMismatch if compute_hash() != self.provenance_hash."""
        logger.info("verify_self(self=%s)", self.__class__.__name__)
        computed = self.compute_hash()
        if computed != self.provenance_hash:
            raise ArtifactProvenanceMismatch(
                "Integrity check failed: computed hash "
                f"{computed} != provenance_hash {self.provenance_hash}"
            )
