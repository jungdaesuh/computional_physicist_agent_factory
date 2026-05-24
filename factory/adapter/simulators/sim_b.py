"""Reference adapter for simulator sim_b."""

from __future__ import annotations

from factory.adapter.registry import register, register_mock
from factory.adapter.simulators.base import ReferenceAdapter, ReferenceMockAdapter


@register
class SimBAdapter(ReferenceAdapter):
    """Built-in reference adapter for sim_b."""

    simulator_id = "sim_b"
    simulator_version = "sim-b-reference-1.0"
    container_sha = "sha256:sim-b-reference"
    metric_offset = 0.05


@register_mock("sim_b")
class SimBMockAdapter(ReferenceMockAdapter):
    """Mock-mode reference adapter for sim_b."""

    simulator_id = "sim_b"
    simulator_version = "sim-b-mock-1.0"
    container_sha = "sha256:sim-b-mock"
    metric_offset = 0.05


__all__ = ["SimBAdapter", "SimBMockAdapter"]
