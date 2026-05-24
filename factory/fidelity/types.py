"""Module-local fidelity dispatch types."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

FidelityTierKind = Literal["dry_run", "surrogate", "mid_fidelity", "oracle", "cross_simulator"]


class FidelityKind(StrEnum):
    """Enum mirror of the Artifact-owned FidelityTier.kind literal."""

    DRY_RUN = "dry_run"
    SURROGATE = "surrogate"
    MID_FIDELITY = "mid_fidelity"
    ORACLE = "oracle"
    CROSS_SIMULATOR = "cross_simulator"


__all__ = ["FidelityKind", "FidelityTierKind"]
