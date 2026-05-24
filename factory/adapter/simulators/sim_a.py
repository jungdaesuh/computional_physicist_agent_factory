"""Reference adapter for simulator sim_a."""

from __future__ import annotations

from factory.adapter.registry import register, register_mock
from factory.adapter.simulators.base import ReferenceAdapter, ReferenceMockAdapter


@register
class SimAAdapter(ReferenceAdapter):
    """Built-in reference adapter for sim_a."""

    simulator_id = "sim_a"
    simulator_version = "sim-a-reference-1.0"
    container_sha = "sha256:sim-a-reference"
    metric_offset = 0.0


@register_mock("sim_a")
class SimAMockAdapter(ReferenceMockAdapter):
    """Mock-mode reference adapter for sim_a."""

    simulator_id = "sim_a"
    simulator_version = "sim-a-mock-1.0"
    container_sha = "sha256:sim-a-mock"
    metric_offset = 0.0


__all__ = ["SimAAdapter", "SimAMockAdapter"]
