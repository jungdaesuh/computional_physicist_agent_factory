# specifications.py — Spec-related Artifact Models
#
# This file defines the core specification artifacts used to formulate hypotheses,
# define experimental designs, scope domain-specific boundaries, and set budgets.
#
# Use cases:
# 1. Storing and validating literature gap discoveries (GapCandidate).
# 2. Defining concretized research hypotheses (HypothesisSpec).
# 3. Specifying simulator selections, controls, and multi-fidelity ladders (ExperimentSpec).
# 4. Tracking and bounding computing resources (Budget).
# 5. Restricting factory operations to approved regimes (DomainScope).

from __future__ import annotations

import logging
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from factory.artifacts.core import (
    ArtifactHash,
    HypothesisId,
    SimulatorId,
    _ArtifactBase,
)

logger = logging.getLogger("factory.artifacts.specifications")

# --------------------------------------------------------------------------
# Enums and supporting sub-models
# --------------------------------------------------------------------------


class GapType(StrEnum):
    """Types of literature gaps discovered by the Gap Miner."""

    STRUCTURAL_HOLE = "structural_hole"
    METHODOLOGY_TRANSFER = "methodology_transfer"
    CONTRADICTION = "contradiction"
    NEGATIVE_RESULT = "negative_result"


class ControlDefinition(BaseModel):
    """Defines the baseline configurations for experimental comparison."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    baseline_simulator_id: SimulatorId
    baseline_config: dict[str, str | int | float | bool]


class FidelityTier(BaseModel):
    """Configuration for a single tier in the Multi-Fidelity Scheduler."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    kind: Literal["dry_run", "surrogate", "mid_fidelity", "oracle", "cross_simulator"]
    cost_estimate_usd: float
    expected_runtime_seconds: float
    kill_threshold: float | None


class BudgetLedgerEntry(BaseModel):
    """A recorded entry of token or monetary spend."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ts: datetime
    module: str
    cost_usd: float
    tokens: int
    description: str


# --------------------------------------------------------------------------
# Top-level Specification Artifacts
# --------------------------------------------------------------------------


class GapCandidate(_ArtifactBase):
    """A literature-derived research direction candidate."""

    gap_type: GapType
    rationale: str
    source_papers: tuple[str, ...]  # OpenAlex Work IDs
    confidence: float = Field(ge=0.0, le=1.0)
    seed_query: str


class HypothesisSpec(_ArtifactBase):
    """A concretized, falsifiable hypothesis specification."""

    hypothesis_id: HypothesisId
    parent_gap_hash: ArtifactHash
    if_then: str
    measurable_metric: str
    expected_effect_size: float
    expected_effect_unit: str
    confidence_interval: tuple[float, float]
    kill_criteria: tuple[str, ...]
    pre_registered_metric: str
    qualified_track: bool = False  # Set true if C1 worthiness was qualified


class ExperimentSpec(_ArtifactBase):
    """Details of the simulator selection and experimental execution setup."""

    hypothesis_id: HypothesisId
    simulator_id: SimulatorId
    control_definition: ControlDefinition
    fidelity_ladder: tuple[FidelityTier, ...]
    seed_set: tuple[int, ...]
    success_metric: str
    kill_criteria: tuple[str, ...]


class Budget(_ArtifactBase):
    """The budget envelope for a single hypothesis run."""

    hypothesis_id: HypothesisId
    dollar_cap: float
    wall_clock_cap_seconds: float
    token_cap: int
    iteration_cap: int
    running_ledger: tuple[BudgetLedgerEntry, ...] = Field(default_factory=tuple)


class DomainScope(_ArtifactBase):
    """Approved simulator families and physical regimes."""

    allowed_domains: tuple[str, ...]
    allowed_simulator_ids: tuple[SimulatorId, ...]
    expansion_criteria: tuple[str, ...]
