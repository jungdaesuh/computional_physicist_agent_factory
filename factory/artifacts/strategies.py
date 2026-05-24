# strategies.py — Strategy-related Artifact Models
#
# This file defines the artifacts used to manage the Strategy Archive, supporting
# Bayesian surprise tracking, composite UCT scores, and diversity coordinates.
#
# Use cases:
# 1. Storing active search heuristics and their performance histories (Strategy).
# 2. Aggregating rewards and constraint overshoots at cycle terminals (StrategyCycleEvidence).
# 3. Categorizing strategies into novel, mutated, crossover, or library sets.

from __future__ import annotations

import logging
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from factory.artifacts.core import CycleId, _ArtifactBase

logger = logging.getLogger("factory.artifacts.strategies")

# --------------------------------------------------------------------------
# Enums and supporting sub-models
# --------------------------------------------------------------------------


class StrategyKind(StrEnum):
    """Categorization of how the strategy was created in the archive."""

    NOVEL = "novel"
    MUTATE = "mutate"
    CROSSOVER = "crossover"
    LIBRARY = "library"


class BehaviorDescriptor(BaseModel):
    """Behavior-space coordinates for diversity mapping (e.g. MAP-Elites)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    vector: tuple[float, ...]
    cell_id: str | None

    def to_cell_key(self) -> tuple[str, ...]:
        """Return the MAP-Elites cell key for elite bookkeeping."""
        return (self.cell_id,) if self.cell_id is not None else ()

    def to_vector(self) -> tuple[float, ...]:
        """Return the fixed-length numeric vector for cosine-distance novelty."""
        return self.vector


class ConstraintOvershootStats(BaseModel):
    """Summarizes physical or technical boundary violations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    n_violating: int
    mean_overshoot: float
    min_overshoot: float


# --------------------------------------------------------------------------
# Top-level Strategy Artifacts
# --------------------------------------------------------------------------


class Strategy(_ArtifactBase):
    """Represents a search heuristic strategy in the archive."""

    sha: str  # content hash of summary_md
    summary_md: str
    kind: StrategyKind
    parent_shas: tuple[str, ...]
    reward_ema: float | None
    surprise_ema: float | None
    feasibility_distance_ema: float | None
    feasible_count: int
    visits: int
    behavior_descriptor: BehaviorDescriptor
    provenance: str  # e.g., "agent_authored" | "hand_authored"


class StrategyCycleEvidence(_ArtifactBase):
    """Aggregated experimental evidence returned from a cycle run."""

    strategy_sha: str
    cycle_id: CycleId
    best_objective: float | None
    best_feasibility_distance: float | None
    feasible_count: int
    constraint_overshoots: dict[str, ConstraintOvershootStats]
