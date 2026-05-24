# results.py — Execution and Verdict Artifact Models
#
# This file defines the artifacts capturing the outcomes of deliberations, physical
# experiments, surrogate predictions, validations, and operator actions.
#
# Use cases:
# 1. Storing multi-model deliberation outputs and preserved dissents (CouncilVerdict).
# 2. Recording permanent physical discoveries with full provenance links (EvidenceLedgerEntry).
# 3. Generating write-ready publications (RunReport).
# 4. Capturing the results of G4 validation checks (ValidationResult).
# 5. Capturing surrogate-first cheap probes and OOD evaluations (SurrogateProbeResult).
# 6. Auditing administrator commands (FactoryControlEvent).

from __future__ import annotations

import logging
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from factory.artifacts.core import (
    ArtifactHash,
    HypothesisId,
    SimulatorId,
    _ArtifactBase,
)

logger = logging.getLogger("factory.artifacts.results")

# --------------------------------------------------------------------------
# Enums and supporting sub-models
# --------------------------------------------------------------------------


class PersonaName(StrEnum):
    """Adversarial personas that council models run under to provide diversity."""

    VISIONARY = "visionary"
    PESSIMIST = "pessimist"
    PRAGMATIST = "pragmatist"


class CouncilId(StrEnum):
    """The five decision gates driven by councils."""

    C1_WORTHINESS = "C1"
    C2_DESIGN = "C2"
    C3_INTERPRETATION = "C3"
    C4_PEER_REVIEW = "C4"
    C5_PROGRAM_DIRECTION = "C5"


class EvidenceResult(StrEnum):
    """The four terminal results written to the Evidence Ledger."""

    PASSED = "passed"
    FALSIFIED = "falsified"
    INTRACTABLE = "intractable"
    INCONCLUSIVE = "inconclusive"


class DissentEntry(BaseModel):
    """Represents a minority objection preserved from deliberation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: str
    persona: PersonaName
    view: str
    rationale: str


class UncertaintyBlock(BaseModel):
    """Typed block representing statistical error estimates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric_name: str
    point_estimate: float
    ci_lower: float
    ci_upper: float
    ci_method: Literal["t_interval", "bootstrap", "bca"]
    n_seeds: int


class RelitigationTrigger(BaseModel):
    """Trigger conditions for repeating experiments."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    condition: str
    check_fn: str
    last_evaluated_at: datetime | None
    currently_satisfied: bool


class ProvenanceBlock(BaseModel):
    """Records the exact reproducible lineage of code, simulator, and inputs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code_hash: str
    env_hash: str
    input_hash: ArtifactHash
    seed: int | None
    simulator_id: SimulatorId | None
    simulator_version: str | None
    container_sha: str | None


class CheckOutcome(BaseModel):
    """The result of a single physical invariance or numerical check."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    check_name: str
    passed: bool
    residual: float | None
    tolerance: float | None
    skipped: bool
    rationale: str | None


class CrossSimulatorComparison(BaseModel):
    """Outcome of comparing results against a secondary simulator."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    paired_simulator_id: SimulatorId
    observable: str
    delta: float
    tolerance: float
    tolerance_kind: Literal["relative", "absolute", "mixed"]
    passed: bool


# --------------------------------------------------------------------------
# Top-level Results Artifacts
# --------------------------------------------------------------------------


class CouncilVerdict(_ArtifactBase):
    """Deliberation outcome of a decision council."""

    council_id: CouncilId
    question: str
    model_lineup: tuple[str, ...]
    persona_assignment: dict[str, PersonaName]
    chairman_model: str
    majority_view: str
    preserved_dissents: tuple[DissentEntry, ...]
    chairman_decision: Literal["approve", "reject", "qualified", "no_consensus"]
    total_cost_usd: float
    wall_clock_seconds: float
    session_id: str


class EvidenceLedgerEntry(_ArtifactBase):
    """A row inside the SQLite-backed Evidence Ledger, linking all provenance."""

    hypothesis_id: HypothesisId
    result: EvidenceResult
    terminal_state: str
    provenance: ProvenanceBlock
    uncertainty: UncertaintyBlock
    relitigate_if: tuple[RelitigationTrigger, ...]
    council_verdict_hashes: tuple[ArtifactHash, ...]
    run_report_hash: ArtifactHash | None
    surprise_bits: float | None = None


class RunReport(_ArtifactBase):
    """The publishable LaTeX/PDF document with BibTeX bibliography."""

    hypothesis_id: HypothesisId
    title: str
    abstract: str
    latex_source: str
    figure_paths: tuple[str, ...]
    bibtex: str
    embedded_council_verdict_hashes: tuple[ArtifactHash, ...]
    g6_approved: bool
    g6_approver: str | None
    g6_approved_at: datetime | None


class ValidationResult(_ArtifactBase):
    """Full suite verification result (G4)."""

    hypothesis_id: HypothesisId
    experiment_spec_hash: ArtifactHash
    per_check_outcomes: tuple[CheckOutcome, ...]
    residuals: dict[str, float]
    tolerances: dict[str, float]
    cross_simulator_comparison: CrossSimulatorComparison | None
    reweighted_for_missing_cross_sim: bool
    overall_verdict: Literal["pass", "fail", "inconclusive"]
    input_hashes_used: tuple[ArtifactHash, ...]


class SurrogateProbeResult(_ArtifactBase):
    """Result of running a candidate against a cheap surrogate model (G3)."""

    hypothesis_id: HypothesisId
    experiment_spec_hash: ArtifactHash
    predicted_value: float
    uncertainty: UncertaintyBlock
    ood_flag: bool
    ood_distance_percentile: float
    pass_vs_baseline: Literal["pass", "fail", "escalate"]
    surrogate_model_id: str
    feature_vector_hash: str


class FactoryControlEvent(_ArtifactBase):
    """Audit record for system operator command mutations."""

    event_type: Literal["pause", "resume", "approve", "reject", "abort"]
    target_id: str | None
    reason: str | None
    operator: str
    invoked_at: datetime
