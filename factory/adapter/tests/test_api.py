"""Unit tests for the adapter registry and contract validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from factory.adapter.abstract import Adapter, BlueprintComponents
from factory.adapter.api import load, registered_ids, validate_catalog_parity
from factory.adapter.errors import AdapterContractViolation, AdapterNotRegistered
from factory.adapter.types import AdapterOutputField, AdapterOutputSchema, RunArtifacts
from factory.artifacts import ExperimentSpec


def test_registered_reference_adapters_are_loadable() -> None:
    assert registered_ids() == ("sim_a", "sim_b")
    assert registered_ids(mock_mode=True) == ("sim_a", "sim_b")
    assert load("sim_b", mock_mode=True).simulator_id == "sim_b"


def test_load_unknown_adapter_raises() -> None:
    with pytest.raises(AdapterNotRegistered):
        load("missing-simulator")


def test_catalog_parity_detects_missing_and_extra_adapters() -> None:
    validate_catalog_parity(("sim_a", "sim_b"))
    with pytest.raises(AdapterContractViolation, match="missing_adapters"):
        validate_catalog_parity(("sim_a", "sim_b", "sim_c"))


def test_schema_simulator_mismatch_is_rejected() -> None:
    class BadAdapter(Adapter):
        simulator_id = "bad"

        def components(self) -> BlueprintComponents:
            return load("sim_a").components()

        def output_schema(self) -> AdapterOutputSchema:
            return AdapterOutputSchema(
                simulator_id="other",
                schema_version="1.0",
                canonical_tensor_filename="canonical.json",
                fields=(
                    AdapterOutputField(
                        name="observables.success_metric",
                        dtype="float",
                        units=None,
                        description="metric",
                    ),
                ),
            )

        def run(self, experiment_spec: ExperimentSpec, sandbox_dir: Path) -> RunArtifacts:
            return load("sim_a").run(experiment_spec, sandbox_dir)

    with pytest.raises(AdapterContractViolation, match="does not match"):
        from factory.adapter.registry import _validate_adapter_schema

        _validate_adapter_schema(BadAdapter())
