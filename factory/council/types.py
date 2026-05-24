# types.py — Module-local types for council
#
# Defines internal or local types specific to the council module.
# Do not store shared artifacts here; those live in factory/artifacts/

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from factory.artifacts import PersonaName
from factory.council.errors import CouncilError

CouncilContextValue = str | int | float | bool | None
CouncilContext = Mapping[str, CouncilContextValue]


@dataclass(frozen=True)
class ModelSpec:
    """One frontier model from one vendor, routed through OpenRouter."""

    openrouter_id: str  # e.g. "openai/gpt-5.5"
    vendor: Literal["openai", "anthropic", "google", "x-ai"]
    timeout_s: float = 60.0
    max_tokens: int = 4096


@dataclass(frozen=True)
class CouncilLineup:
    """A council lineup is a fixed 4-vendor frontier set + persona assignment.

    Heterogeneity requirements (enforced at construction):
      - len(models) == 4
      - {m.vendor for m in models} == {"openai", "anthropic", "google", "x-ai"}
        (exactly one model per vendor; vendor heterogeneity is the defense)
      - persona_assignment.keys() == {m.openrouter_id for m in models}
        (every model has an assigned persona)
      - len(set(persona_assignment.values())) >= 3
        (>=3 distinct personas across the 4 calls)
      - sum(1 for p in persona_assignment.values() if p == PersonaName.PESSIMIST) >= 2
        (Pessimist persona must be over-weighted - assigned to >=2 models)
    """

    models: Sequence[ModelSpec]  # exactly 4, one per vendor
    persona_assignment: dict[str, PersonaName]  # openrouter_id → persona
    chairman_policy: Literal["random", "round_robin", "weighted_by_cost"]

    def __post_init__(self) -> None:
        """Enforces lineup invariants."""
        if len(self.models) != 4:
            raise CouncilError(f"Lineup must contain exactly 4 models, got {len(self.models)}")

        vendors = {m.vendor for m in self.models}
        expected_vendors = {"openai", "anthropic", "google", "x-ai"}
        if vendors != expected_vendors:
            raise CouncilError(
                "Lineup must have exactly one model per vendor "
                f"in {expected_vendors}, got {vendors}"
            )

        model_ids = {m.openrouter_id for m in self.models}
        assigned_model_ids = set(self.persona_assignment.keys())
        if model_ids != assigned_model_ids:
            raise CouncilError(
                f"Persona assignment keys {assigned_model_ids} must match model IDs {model_ids}"
            )

        personas = set(self.persona_assignment.values())
        if len(personas) < 3:
            raise CouncilError(
                f"Lineup must cover >=3 distinct personas, got {len(personas)} ({personas})"
            )

        pessimist_count = sum(
            1 for p in self.persona_assignment.values() if p == PersonaName.PESSIMIST
        )
        if pessimist_count < 2:
            raise CouncilError(
                "Lineup must over-weight Pessimist persona "
                f"(assigned >= 2 times), got {pessimist_count}"
            )


@dataclass(frozen=True)
class FirstOpinion:
    """Stage 1 structured opinion from a council member."""

    openrouter_id: str
    vendor: str
    persona: PersonaName
    view: str
    self_rank: int


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of running a single calibration probe."""

    probe_id: str
    question: str
    responses_by_model: dict[str, str]  # openrouter_id → response text
    responses_by_persona: dict[PersonaName, list[str]]  # persona → list of responses
    disagreement_rate: float  # 1 - max pairwise cosine similarity


@dataclass(frozen=True)
class CalibrationReport:
    """Aggregated calibration results across a probe set."""

    probe_results: list[ProbeResult]
    overall_disagreement_rate: float
    flagged_sycophancy: bool
    notes: list[str]
