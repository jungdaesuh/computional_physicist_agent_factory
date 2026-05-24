"""Shared module contract metadata for implementation-facing APIs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModuleContract:
    """Stable description of a factory module's public responsibility."""

    module_name: str
    spec_id: str
    responsibility: str
    required_inputs: tuple[str, ...]
    produced_outputs: tuple[str, ...]

    def requires(self, input_name: str) -> bool:
        """Return whether this module declares the named input contract."""
        return input_name in self.required_inputs

    def produces(self, output_name: str) -> bool:
        """Return whether this module declares the named output contract."""
        return output_name in self.produced_outputs
