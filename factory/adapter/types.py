"""Typed adapter payloads and output-schema validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from factory.adapter.errors import AdapterContractViolation
from factory.artifacts import ArtifactHash

SANDBOX_ADAPTER_OUTPUTS_RELPATH = "adapter_outputs"
AdapterOutputDType = Literal["float", "int", "ndarray", "path", "dict[str,float]", "object"]


class AdapterOutputField(BaseModel):
    """One named field the adapter promises to populate in RunArtifacts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    dtype: AdapterOutputDType
    units: str | None
    description: str
    required: bool = True


class AdapterOutputSchema(BaseModel):
    """Static declaration of the RunArtifacts fields emitted by an adapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    simulator_id: str
    schema_version: str
    canonical_tensor_filename: str
    fields: tuple[AdapterOutputField, ...]


class RunArtifacts(BaseModel):
    """Canonical adapter output consumed by validation and fidelity scheduling."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    observables: dict[str, float]
    residuals: dict[str, float]
    diagnostics: dict[str, object]
    sandbox_paths: dict[str, Path]
    seed: int
    fidelity_tier: str
    simulator_version: str
    container_sha: str
    wall_clock_seconds: float
    cost_usd: float
    parent_experiment_hash: ArtifactHash

    def write_json(self, destination_path: Path) -> Path:
        """Persist this payload as deterministic JSON."""
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_text(
            json.dumps(
                self.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        return destination_path


def adapter_output_dir(sandbox_dir: Path, seed: int) -> Path:
    """Return the canonical adapter output directory for one seed."""
    return sandbox_dir / SANDBOX_ADAPTER_OUTPUTS_RELPATH / str(seed)


def assert_output_schema_satisfied(
    schema: AdapterOutputSchema,
    artifacts: RunArtifacts,
) -> None:
    """Raise when a required schema field is absent from RunArtifacts."""
    for field in schema.fields:
        if field.required and _lookup_schema_path(artifacts, field.name) is None:
            raise AdapterContractViolation(
                f"RunArtifacts for {schema.simulator_id} missing required field {field.name}"
            )


def _lookup_schema_path(artifacts: RunArtifacts, dotted_path: str) -> object:
    prefix, separator, key = dotted_path.partition(".")
    if separator == "":
        return getattr(artifacts, dotted_path, None)
    if prefix == "observables":
        return artifacts.observables.get(key)
    if prefix == "residuals":
        return artifacts.residuals.get(key)
    if prefix == "diagnostics":
        return artifacts.diagnostics.get(key)
    if prefix == "sandbox_paths":
        return artifacts.sandbox_paths.get(key)
    return None


__all__ = [
    "AdapterOutputDType",
    "AdapterOutputField",
    "AdapterOutputSchema",
    "RunArtifacts",
    "SANDBOX_ADAPTER_OUTPUTS_RELPATH",
    "adapter_output_dir",
    "assert_output_schema_satisfied",
]
