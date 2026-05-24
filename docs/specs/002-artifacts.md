# Spec 002: Typed Artifacts

> Status: ☐ not started · Owner: TBD · Last updated: 2026-05-23

## CONTEXT (60-second summary — read first)
- This module defines the **13 immutable typed artifacts** that are the lingua franca between every other module. Modules talk in artifacts; never in raw dicts.
- The 5 facts: (1) artifacts are Pydantic models with strict types (no `Any`, no untyped `dict`); (2) every artifact has a content-addressed SHA-256 `provenance_hash`; (3) artifacts are JSON-serialized and persisted to `runs/<cycle-id>/artifacts/<hash>.json`; (4) artifacts are *immutable* — produce a new one via `model_copy(update=...)`, never edit; (5) re-running with the same inputs + seed must reproduce the same hash.
- Open first: `factory/artifacts/api.py` to see the canonical Pydantic models. Then `factory/artifacts/tests/test_artifacts_typical_usage.py`.

## ENTRY POINTS
- Main module: `factory/artifacts/api.py`
- Typical-usage test: `factory/artifacts/tests/test_artifacts_typical_usage.py`
- CLI: `python -m factory.artifacts --help` (subcommands: `validate`, `hash`, `show`, `verify-chain`, `emit-schemas`)
- Mock-mode example: `python -m factory.artifacts show --type HypothesisSpec --fixture sample`
- Runbook: `docs/runbooks/artifacts-debugging.md`

## LOCAL DEBUG
- Instantiate any artifact directly in a REPL: `from factory.artifacts import HypothesisSpec; HypothesisSpec.from_fixture("sample")`.
- All 13 artifacts ship with at least 3 fixtures each (typical / edge / malformed) in `factory/artifacts/fixtures/`.
- Common error signatures → recovery:
  - `ArtifactValidationError` → input violates schema; check field types and required fields.
  - `ArtifactProvenanceMismatch` → hash doesn't match content; artifact was tampered or seed drift; do not trust.
  - `ArtifactImmutabilityViolation` → caller tried to mutate; replace with `.model_copy(update=...)` to produce a new artifact.
  - `ArtifactHashFormatError` → constructor received a string that is not a 64-char lowercase hex digest.
  - `ArtifactSerializationError` → canonical-JSON serializer saw a `NaN` or `Infinity` float; fix the upstream physics bug before re-emitting.
- Logs to inspect: every artifact write emits a `factory.artifacts.persist` event with `{hash, type, cycle_id}` to `runs/<cycle-id>/cycle.jsonl`.

## DEPENDENCIES
- **Hard:** none. This is the foundational layer; everything depends on this, this depends on nothing.
- **Soft:** `factory.telemetry` (spec 014) — if available, persistence events are emitted. If not available, in-memory only (degraded mode).
- **Mocks:** N/A (the artifacts themselves are the mock-able data).

---

## 1. Summary

This module is the **typed-artifacts foundation** of the factory. It defines the **thirteen** artifacts listed in `SPEC.md` §2 and FIX_PLAN §1 + §26 as strictly-typed Pydantic models with content-addressed provenance, immutable construction, deterministic serialization, and a fluent fixture-based testing pattern.

Every other module reads and produces these artifacts. No module is allowed to invent its own data shape for cross-module communication, and no module-boundary signature contains `Any` or a raw untyped `dict` (per ARCHITECTURE.md §1.5).

## 2. Scope

**In scope:**
- Pydantic models for **thirteen** typed artifacts: `GapCandidate`, `HypothesisSpec`, `CouncilVerdict`, `ExperimentSpec`, `Budget`, `DomainScope`, `EvidenceLedgerEntry`, `RunReport`, `ValidationResult`, `SurrogateProbeResult`, `FactoryControlEvent`, `Strategy`, `StrategyCycleEvidence`.
- Supporting typed sub-models that close `dict` boundaries: `ControlDefinition` (replaces `ExperimentSpec.control_definition: dict`), `UncertaintyBlock` (replaces `EvidenceLedgerEntry.uncertainty: dict`), `CheckOutcome`, `CrossSimulatorComparison`, `DissentEntry`, `BudgetLedgerEntry`, `FidelityTier`, `RelitigationTrigger`, `ProvenanceBlock`, `BehaviorDescriptor`, `ConstraintOvershootStats`.
- Content-addressed SHA-256 hashing (canonical JSON serialization + hash). NaN/Infinity raise at serialize time (`allow_nan=False`).
- `ArtifactHash` typed string with runtime regex validation (`^[0-9a-f]{64}$`).
- Immutability via Pydantic `model_config = ConfigDict(frozen=True)` plus tuple-typed sequences for deep immutability.
- Fixture loading API: `Artifact.from_fixture(name)`.
- Validation CLI: `python -m factory.artifacts validate <file.json>`.
- Re-hashing CLI: `python -m factory.artifacts hash <file.json>` (must match stored hash; warns if not).
- Provenance chain verification: `python -m factory.artifacts verify-chain <hypothesis-id>` — walks the artifact graph from `GapCandidate` to `RunReport`.
- Schema emission CLI: `python -m factory.artifacts emit-schemas docs/schemas/`.

**Out of scope:**
- Persistence backend for the Evidence Ledger (handled by `factory.ledger`, spec 012). Other artifacts persist as JSON files under `runs/<cycle-id>/artifacts/<hash>.json`.
- Cross-cycle queries (spec 012).
- Schema migration (Phase B concern; see §9).
- Compression at rest (Phase B; see §9).
- Cross-cycle artifact deduplication (Phase B; see §9).

## 3. Public Interface

```python
# factory/artifacts/api.py

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, NewType

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)


# --------------------------------------------------------------------------
# Type aliases and primitive identifiers
# --------------------------------------------------------------------------

# A 64-character lowercase hex SHA-256 digest. Constructor validates at runtime.
# Implementation note: this is a Pydantic-compatible constrained string alias.
# Equivalent NewType-with-validator form is given below under "ArtifactHash class".
ArtifactHash = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$", strip_whitespace=False, to_lower=False),
]

HypothesisId = NewType("HypothesisId", str)
CycleId = NewType("CycleId", str)
SimulatorId = NewType("SimulatorId", str)


# Optional explicit class form, used where a NewType-with-validator is preferred
# (e.g., places that construct hashes directly without going through a Pydantic model).
class ArtifactHashStr(str):
    """SHA-256 digest as a validated string."""

    _PATTERN = re.compile(r"^[0-9a-f]{64}$")

    def __new__(cls, value: str) -> "ArtifactHashStr":
        if not isinstance(value, str) or not cls._PATTERN.match(value):
            raise ArtifactHashFormatError(f"invalid hash format: {value!r}")
        return super().__new__(cls, value)


# --------------------------------------------------------------------------
# Exception hierarchy
# --------------------------------------------------------------------------

class FactoryError(Exception): ...
class ArtifactValidationError(FactoryError): ...
class ArtifactProvenanceMismatch(FactoryError): ...
class ArtifactImmutabilityViolation(FactoryError): ...
class ArtifactHashFormatError(FactoryError): ...
class ArtifactSerializationError(FactoryError): ...


# --------------------------------------------------------------------------
# Base artifact
# --------------------------------------------------------------------------

class _ArtifactBase(BaseModel):
    """Common base. Every artifact inherits from this."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_type: str
    created_at: datetime
    provenance_hash: ArtifactHash
    parent_hashes: tuple[ArtifactHash, ...] = Field(default_factory=tuple)

    @classmethod
    def from_fixture(cls, name: str) -> "_ArtifactBase":
        """Load a fixture under factory/artifacts/fixtures/<artifact_type>/<name>.json."""

    @classmethod
    def from_json(cls, raw: str | bytes | dict[str, object]) -> "_ArtifactBase":
        """Parse + validate; raises ArtifactValidationError on failure."""

    def to_canonical_json(self) -> bytes:
        """Deterministic JSON serialization for hashing.

        Excludes provenance_hash and created_at, sorts keys, strips whitespace,
        and rejects NaN/Infinity.
        """

    def compute_hash(self) -> ArtifactHash:
        """SHA-256 of canonical JSON excluding provenance_hash and created_at."""

    def verify_self(self) -> None:
        """Raise ArtifactProvenanceMismatch if compute_hash() != self.provenance_hash."""


# --------------------------------------------------------------------------
# Enums and small helper models
# --------------------------------------------------------------------------

class GapType(str, Enum):
    STRUCTURAL_HOLE = "structural_hole"
    METHODOLOGY_TRANSFER = "methodology_transfer"
    CONTRADICTION = "contradiction"
    NEGATIVE_RESULT = "negative_result"


class PersonaName(str, Enum):
    VISIONARY = "visionary"
    PESSIMIST = "pessimist"
    PRAGMATIST = "pragmatist"


class CouncilId(str, Enum):
    C1_WORTHINESS = "C1"
    C2_DESIGN = "C2"
    C3_INTERPRETATION = "C3"
    C4_PEER_REVIEW = "C4"
    C5_PROGRAM_DIRECTION = "C5"


class EvidenceResult(str, Enum):
    PASSED = "passed"
    FALSIFIED = "falsified"
    INTRACTABLE = "intractable"
    INCONCLUSIVE = "inconclusive"


class StrategyKind(str, Enum):
    NOVEL = "novel"
    MUTATE = "mutate"
    CROSSOVER = "crossover"
    LIBRARY = "library"


class DissentEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    model_id: str
    persona: PersonaName
    view: str
    rationale: str


class FidelityTier(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    kind: Literal["dry_run", "surrogate", "mid_fidelity", "oracle", "cross_simulator"]
    cost_estimate_usd: float
    expected_runtime_seconds: float
    kill_threshold: float | None


class BudgetLedgerEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    ts: datetime
    module: str
    cost_usd: float
    tokens: int
    description: str


class RelitigationTrigger(BaseModel):
    model_config = ConfigDict(frozen=True)
    condition: str
    check_fn: str
    last_evaluated_at: datetime | None
    currently_satisfied: bool


class ProvenanceBlock(BaseModel):
    model_config = ConfigDict(frozen=True)
    code_hash: str
    env_hash: str
    input_hash: ArtifactHash
    seed: int | None
    simulator_id: SimulatorId | None
    simulator_version: str | None
    container_sha: str | None


# --------------------------------------------------------------------------
# Typed replacements for previously-untyped dict boundaries
# --------------------------------------------------------------------------

# Replaces ExperimentSpec.control_definition: dict (FIX_PLAN §14).
# baseline_config keeps a constrained dict to allow per-simulator-family
# extension without re-opening the boundary to `Any`.
class ControlDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    baseline_simulator_id: SimulatorId
    baseline_config: dict[str, str | int | float | bool]


# Replaces EvidenceLedgerEntry.uncertainty: dict (FIX_PLAN §14).
class UncertaintyBlock(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    metric_name: str
    point_estimate: float
    ci_lower: float
    ci_upper: float
    ci_method: Literal["t_interval", "bootstrap", "bca"]
    n_seeds: int


# A single validator check outcome — used inside ValidationResult.
class CheckOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    check_name: str
    passed: bool
    residual: float | None
    tolerance: float | None
    skipped: bool
    rationale: str | None


# Cross-simulator comparison outcome — used inside ValidationResult.
class CrossSimulatorComparison(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    paired_simulator_id: SimulatorId
    observable: str
    delta: float
    tolerance: float
    tolerance_kind: Literal["relative", "absolute", "mixed"]
    passed: bool


# Behavior-space coordinates for MAP-Elites diversity — used inside Strategy.
# Supporting Pydantic model (NOT a top-level artifact). See FIX_PLAN §26.2.
class BehaviorDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    vector: tuple[float, ...]                   # behavior-space coordinates
    cell_id: str | None                         # MAP-Elites cell membership; None if not assigned


# Per-constraint overshoot statistics — used inside StrategyCycleEvidence.
# Supporting Pydantic model (NOT a top-level artifact). Closes the `dict` value
# boundary so the StrategyCycleEvidence.constraint_overshoots map carries typed
# values rather than untyped scalars.
class ConstraintOvershootStats(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    n_violating: int
    mean_overshoot: float
    min_overshoot: float


# --------------------------------------------------------------------------
# Artifact 1: GapCandidate (producer: spec 007 Gap Miner)
# --------------------------------------------------------------------------

class GapCandidate(_ArtifactBase):
    gap_type: GapType
    rationale: str
    source_papers: tuple[str, ...]            # OpenAlex Work IDs
    confidence: float = Field(ge=0.0, le=1.0)
    seed_query: str


# --------------------------------------------------------------------------
# Artifact 2: HypothesisSpec (producer: spec 003 after C1)
# --------------------------------------------------------------------------

class HypothesisSpec(_ArtifactBase):
    hypothesis_id: HypothesisId
    parent_gap_hash: ArtifactHash
    if_then: str
    measurable_metric: str
    expected_effect_size: float
    expected_effect_unit: str
    confidence_interval: tuple[float, float]
    kill_criteria: tuple[str, ...]
    pre_registered_metric: str
    qualified_track: bool = False             # set when C1 issued "qualified"


# --------------------------------------------------------------------------
# Artifact 3: CouncilVerdict (producer: spec 001)
# --------------------------------------------------------------------------

class CouncilVerdict(_ArtifactBase):
    council_id: CouncilId
    question: str
    model_lineup: tuple[str, ...]
    persona_assignment: dict[str, PersonaName]   # model_id -> persona, typed value
    chairman_model: str
    majority_view: str
    preserved_dissents: tuple[DissentEntry, ...]
    chairman_decision: Literal["approve", "reject", "qualified", "no_consensus"]
    total_cost_usd: float
    wall_clock_seconds: float
    session_id: str                               # link to runs/<cycle-id>/councils/<session_id>.jsonl


# --------------------------------------------------------------------------
# Artifact 4: ExperimentSpec (producer: spec 003 after C2)
# --------------------------------------------------------------------------

class ExperimentSpec(_ArtifactBase):
    hypothesis_id: HypothesisId
    simulator_id: SimulatorId
    control_definition: ControlDefinition         # FIX_PLAN §14 — no raw dict
    fidelity_ladder: tuple[FidelityTier, ...]
    seed_set: tuple[int, ...]
    success_metric: str
    kill_criteria: tuple[str, ...]


# --------------------------------------------------------------------------
# Artifact 5: Budget (producer: spec 003 at cycle start)
# --------------------------------------------------------------------------

class Budget(_ArtifactBase):
    hypothesis_id: HypothesisId
    dollar_cap: float
    wall_clock_cap_seconds: float
    token_cap: int
    iteration_cap: int
    running_ledger: tuple[BudgetLedgerEntry, ...]


# --------------------------------------------------------------------------
# Artifact 6: DomainScope (producer: operator config; mutated by C5)
# --------------------------------------------------------------------------

class DomainScope(_ArtifactBase):
    allowed_domains: tuple[str, ...]
    allowed_simulator_ids: tuple[SimulatorId, ...]
    expansion_criteria: tuple[str, ...]


# --------------------------------------------------------------------------
# Artifact 7: EvidenceLedgerEntry (producer: spec 003 at cycle terminal)
# --------------------------------------------------------------------------
# Naming note (FIX_PLAN §1): the artifact is `EvidenceLedgerEntry`. The
# storage class `Ledger` lives in spec 012 and is NOT an artifact.

class EvidenceLedgerEntry(_ArtifactBase):
    hypothesis_id: HypothesisId
    result: EvidenceResult
    terminal_state: str                            # e.g., "terminate_published_external" (see spec 003 §5.4)
    provenance: ProvenanceBlock
    uncertainty: UncertaintyBlock                  # FIX_PLAN §14 — no raw dict
    relitigate_if: tuple[RelitigationTrigger, ...]
    council_verdict_hashes: tuple[ArtifactHash, ...]
    run_report_hash: ArtifactHash | None
    # FIX_PLAN §26.2/§26.4: Bayesian-surprise score computed by spec 016 Strategy
    # Archive; NULL until the archive scores the entry. C5 (Program Direction)
    # ranks entries by `surprise_bits × downstream_citation_count` for re-audit
    # prioritization.
    surprise_bits: float | None = None


# --------------------------------------------------------------------------
# Artifact 8: RunReport (producer: spec 011 RAG writer)
# --------------------------------------------------------------------------

class RunReport(_ArtifactBase):
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


# --------------------------------------------------------------------------
# Artifact 9 (NEW): ValidationResult (producer: spec 009 G4 portfolio)
# --------------------------------------------------------------------------
# Consumers: spec 003 (G4 routing), spec 011 (embeds in RunReport context).

class ValidationResult(_ArtifactBase):
    hypothesis_id: HypothesisId
    experiment_spec_hash: ArtifactHash
    per_check_outcomes: tuple[CheckOutcome, ...]
    residuals: dict[str, float]                            # check_name -> residual
    tolerances: dict[str, float]                           # check_name -> tolerance applied
    cross_simulator_comparison: CrossSimulatorComparison | None
    reweighted_for_missing_cross_sim: bool
    overall_verdict: Literal["pass", "fail", "inconclusive"]
    input_hashes_used: tuple[ArtifactHash, ...]


# --------------------------------------------------------------------------
# Artifact 10 (NEW): SurrogateProbeResult (producer: spec 010 surrogate)
# --------------------------------------------------------------------------
# Consumers: spec 003 (G3 routing). On `escalate`, G3 sets the
# `skip_surrogate: True` metadata flag carried into G4 (FIX_PLAN §2).

class SurrogateProbeResult(_ArtifactBase):
    hypothesis_id: HypothesisId
    experiment_spec_hash: ArtifactHash
    predicted_value: float
    uncertainty: UncertaintyBlock
    ood_flag: bool
    ood_distance_percentile: float                          # see spec 010 §5.4
    pass_vs_baseline: Literal["pass", "fail", "escalate"]
    surrogate_model_id: str
    feature_vector_hash: str


# --------------------------------------------------------------------------
# Artifact 11 (NEW): FactoryControlEvent (producer: spec 015 mutation CLI)
# --------------------------------------------------------------------------
# Consumers: spec 003 (pause/resume/approve/reject/abort handler).
# Persisted under `runs/_control/events/<ts>.json` (FIX_PLAN §10).

class FactoryControlEvent(_ArtifactBase):
    event_type: Literal["pause", "resume", "approve", "reject", "abort"]
    target_id: str | None                                   # hypothesis_id or run_report_hash, depending on event_type
    reason: str | None
    operator: str
    invoked_at: datetime


# --------------------------------------------------------------------------
# Artifact 12 (NEW): Strategy (producer: spec 016 Strategy Archive)
# --------------------------------------------------------------------------
# Consumers: spec 003 (state machine) reads `select_lineages(k)` output at
# G2.5 / G3 turns when `StrategyArchiveConfig.parallel_lineages_k > 1` to
# choose which lineage seeds the next generator-verifier iteration. See
# FIX_PLAN §26.2 and spec 016 for the BFTS + Bayesian-surprise + UCT +
# MAP-Elites contract.
#
# Reward / surprise EMAs are NULL until the archive observes the first
# StrategyCycleEvidence; thereafter the archive updates them in place by
# emitting a new immutable Strategy (model_copy(update=...)) — never mutates.

class Strategy(_ArtifactBase):
    sha: str                                                # content hash of summary_md
    summary_md: str                                         # full strategy description (markdown)
    kind: StrategyKind
    parent_shas: tuple[str, ...]                            # empty for novel/library; ≥1 for mutate/crossover
    reward_ema: float | None                                # NULL until first observation
    surprise_ema: float | None                              # NULL until first observation
    feasibility_distance_ema: float | None
    feasible_count: int
    visits: int
    behavior_descriptor: BehaviorDescriptor                 # lazy; for MAP-Elites diversity
    provenance: str                                         # "agent_authored" | "hand_authored" | "transferred_from_exp_<N>"


# --------------------------------------------------------------------------
# Artifact 13 (NEW): StrategyCycleEvidence (producer: spec 008 genver per iteration;
# spec 003 state machine on cycle terminal)
# --------------------------------------------------------------------------
# Consumers: spec 016 Strategy Archive for reward + Bayesian-surprise
# attribution. See FIX_PLAN §26.2.

class StrategyCycleEvidence(_ArtifactBase):
    strategy_sha: str
    cycle_id: CycleId
    best_objective: float | None
    best_feasibility_distance: float | None
    feasible_count: int
    constraint_overshoots: dict[str, ConstraintOvershootStats]   # typed value side
```

## 4. Data Structures / Schemas

The Pydantic models above ARE the schemas. JSON Schema for each is auto-generated via `Artifact.model_json_schema()` and emitted to `docs/schemas/<artifact>.schema.json` by a CI step (see §7 Testing).

Persistence format: each artifact is written to `runs/<cycle-id>/artifacts/<hash>.json` (the canonical JSON). The filename IS the hash. A small index `runs/<cycle-id>/artifacts/MANIFEST.json` maps hashes to artifact types for grep-ability.

The thirteen artifacts and their producer / consumer map (mirrors FIX_PLAN §1 + §26):

| # | Artifact | Producer | Consumers |
| ---: | :--- | :--- | :--- |
| 1 | `GapCandidate` | spec 007 Gap Miner | spec 003 (G0), spec 001 (C1) |
| 2 | `HypothesisSpec` | spec 003 after C1 | spec 003 (G1.5+), spec 005, spec 009 |
| 3 | `CouncilVerdict` | spec 001 | spec 003, spec 011 (embeds in RunReport) |
| 4 | `ExperimentSpec` | spec 003 after C2 | spec 005, spec 006, spec 008, spec 009 |
| 5 | `Budget` | spec 003 at cycle start | spec 013 tracker reads/updates |
| 6 | `DomainScope` | operator config | spec 003 (G0 check), C5 mutates |
| 7 | `EvidenceLedgerEntry` | spec 003 at cycle terminal | spec 010 (training data), spec 011 (RAG), spec 016 (writes `surprise_bits`) |
| 8 | `RunReport` | spec 011 RAG writer | spec 003 (G6), spec 015 (approval CLI) |
| 9 | `ValidationResult` | spec 009 G4 portfolio | spec 003 (G4 routing), spec 011 (embeds) |
| 10 | `SurrogateProbeResult` | spec 010 surrogate | spec 003 (G3 routing) |
| 11 | `FactoryControlEvent` | spec 015 mutation CLI | spec 003 (pause/resume/approve handler) |
| 12 | `Strategy` | spec 016 Strategy Archive | spec 003 state machine for lineage selection at G2.5 / G3 turns |
| 13 | `StrategyCycleEvidence` | spec 008 genver per iteration; spec 003 state machine on cycle terminal | spec 016 archive for surprise + reward attribution |

## 5. Algorithms / Logic

### 5.1 Content-addressed hashing

```python
def compute_hash(artifact: _ArtifactBase) -> ArtifactHash:
    # 1. Serialize to canonical JSON: sorted keys, no whitespace, UTF-8.
    # 2. Exclude provenance_hash and created_at fields from the serialization.
    # 3. allow_nan=False: NaN and Infinity raise ArtifactSerializationError at serialize-time,
    #    surfacing upstream physics bugs instead of producing an unparseable artifact.
    # 4. SHA-256 over the resulting bytes.
    payload = artifact.model_dump(exclude={"provenance_hash", "created_at"}, mode="json")
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return ArtifactHash(hashlib.sha256(canonical).hexdigest())
```

The hash is set at construction-time via a model validator. Tampering is detected by `verify_self()`.

**RFC 8785 approximation caveat.** This serializer approximates [RFC 8785 JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785) but is *not* strictly compliant. Two known deviations:

1. Floating-point representation may vary subtly across Python versions for subnormal numbers; RFC 8785 mandates the ECMAScript `ToString` algorithm. Producer modules SHOULD avoid emitting subnormal float values in artifacts.
2. We rely on Python's `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)` for member ordering and whitespace; this matches RFC 8785 for ASCII keys but diverges if any artifact were to use non-ASCII keys (none currently do).

**NaN / Infinity policy.** `allow_nan=False` means a `NaN` or `±Infinity` float anywhere in the artifact graph raises `ArtifactSerializationError` *before* the hash is computed. Producer modules MUST sanitize NaN/Infinity *before* constructing the artifact. In practice the G4 validation portfolio (spec 009) catches non-finite residuals as a validation failure, so no NaN should reach the Ledger; this is a belt-and-braces second wall.

### 5.2 Immutability enforcement

`ConfigDict(frozen=True)` blocks attribute assignment after construction. The Pythonic update pattern:

```python
new_artifact = old.model_copy(update={"field": new_value})
# new_artifact has a different provenance_hash; old is unchanged.
```

Deep immutability is enforced **at the type level**: every sequence field on every artifact uses `tuple[...]` (or `frozenset[...]`) rather than `list[...]` or `set[...]`. Pydantic has no read-back validation mechanism, so the contract relies on type discipline plus a CI audit step. The audit step (`python -m factory.artifacts emit-schemas --audit-immutability`) walks every artifact's field annotations and fails CI if it finds a `list[...]`, `set[...]`, or untyped `dict` field outside the explicitly-allowed constrained dict shapes (`dict[str, T]` with concrete `T`, e.g. `dict[str, PersonaName]` on `CouncilVerdict`).

Callers MUST use `tuple[...]` (or `frozenset[...]`) for sequence fields where deep immutability matters. The audit step in CI confirms no `list`/`dict` field exists outside tuple-wrapped form (excepting the constrained `dict[str, T]` cases noted above).

### 5.3 `ArtifactHash` runtime validation

`ArtifactHash` is a Pydantic-compatible constrained string (`Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]`). Any artifact field typed as `ArtifactHash` is validated on construction; supplying a non-conforming string raises `ArtifactValidationError` at the model boundary.

For code paths that build hash strings *outside* a Pydantic model (e.g., low-level utilities), the explicit class form `ArtifactHashStr(str)` is provided; its constructor raises `ArtifactHashFormatError` for invalid input.

### 5.4 Parent-hash chains

`parent_hashes` on every artifact records its provenance lineage. `verify-chain` CLI walks backward from a `RunReport` through `EvidenceLedgerEntry`, `CouncilVerdict`s, `ExperimentSpec`, `ValidationResult` (when present), `SurrogateProbeResult` (when present), `HypothesisSpec`, `GapCandidate` — verifying each step's hash and parent links.

## 6. Failure Modes

| Error class | When it fires | Recovery action |
| :--- | :--- | :--- |
| `ArtifactValidationError` | Pydantic validation fails on construction or `from_json` (any of the 13 artifacts, including `Strategy` — e.g. `parent_shas` empty for `kind=mutate` — and `StrategyCycleEvidence` — e.g. `constraint_overshoots` value not a `ConstraintOvershootStats`) | State machine routes to upstream module that produced the bad data; surfaces in `cycle.jsonl` |
| `ArtifactProvenanceMismatch` | `verify_self()` finds `compute_hash() != provenance_hash` | Halt cycle; mark artifact as poisoned; full provenance audit before resuming |
| `ArtifactImmutabilityViolation` | Caller attempts `artifact.field = x` | Caller must use `model_copy`; this raises at code-review time via mypy strict mode |
| `ArtifactHashFormatError` | A string passed to `ArtifactHash` or `ArtifactHashStr` does not match `^[0-9a-f]{64}$` | Caller is constructing a hash by hand instead of via `compute_hash()`; fix the call site |
| `ArtifactSerializationError` | Canonical-JSON serializer encounters `NaN`/`Infinity` | Producer module emitted a non-finite float; fix the upstream physics bug (G4 should have flagged this) |
| `FixtureNotFoundError` | `from_fixture(name)` cannot find file | List available fixtures in error message; clearly a developer error |

## 7. Testing

**Mock-mode unit tests** (`factory/artifacts/tests/`):
- `test_artifacts_typical_usage.py` — REQUIRED. Constructs every artifact (all thirteen) from fixture; round-trips JSON; verifies hash stability.
- `test_hash_determinism.py` — same input + seed produces same hash; serialization order doesn't affect hash.
- `test_hash_format_validation.py` — `ArtifactHash` rejects upper-case hex, short strings, non-hex characters; round-trips a known-good digest.
- `test_nan_serialization.py` — constructing an artifact whose graph contains `float("nan")` or `float("inf")` raises `ArtifactSerializationError`.
- `test_immutability.py` — attempts to mutate fail loudly; the CI audit step rejects any `list[...]` / untyped `dict` field on artifacts.
- `test_parent_chains.py` — `verify_chain` follows a multi-level lineage correctly across all thirteen artifacts.
- `test_schema_generation.py` — `model_json_schema()` for every artifact is valid JSON Schema Draft 2020-12.
- `test_control_definition.py` — `ControlDefinition.baseline_config` rejects values outside `str | int | float | bool`.
- `test_uncertainty_block.py` — `UncertaintyBlock.ci_method` accepts only `t_interval`, `bootstrap`, `bca`.

**Live-mode tests:** none required for this module — artifacts are pure data structures.

**CI step:** `python -m factory.artifacts emit-schemas docs/schemas/` regenerates `docs/schemas/*.schema.json`. Diff against committed version; fail CI on drift. A second CI step `python -m factory.artifacts emit-schemas --audit-immutability` walks every artifact field annotation and fails on any `list[...]`/raw `dict` outside the permitted constrained forms (see §5.2).

## 8. Performance & Budget

- Artifact construction + hashing: < 5 ms per artifact for typical sizes (< 100 KB).
- JSON parse + validate: < 20 ms for typical sizes.
- `verify_chain` for a full cycle (depth ~10): < 100 ms.
- No external calls; pure in-process work.

## 9. Open Questions

- **Schema versioning.** Phase A pins all schemas; if a field is added later, do we version the artifact type (`HypothesisSpec.v2`) or store schema version in a field? Deferred to Phase B (FIX_PLAN §22).
- **Compression at rest.** Artifacts in `runs/<cycle-id>/artifacts/` could gzip; sub-millisecond decode cost. Deferred to Phase B (FIX_PLAN §22).
- **Cross-cycle artifact deduplication.** Identical `GapCandidate`s across cycles could share hash and a single file. Implies cycle-aware path resolution. Deferred to Phase B (FIX_PLAN §22).
- **Strict RFC 8785 compliance.** Move from the current Python `json` approximation to a strict implementation (e.g., a vendored JCS library). Deferred until cross-tool interoperability becomes a concrete requirement.

## 10. TODO Checklist

- [ ] Create `factory/artifacts/` directory with template files.
- [ ] Implement `_ArtifactBase` with hashing (`allow_nan=False`), freezing, fixture loading.
- [ ] Implement `ArtifactHash` annotated alias and `ArtifactHashStr` class with regex validation.
- [ ] Implement all thirteen artifact subclasses (`GapCandidate`, `HypothesisSpec`, `CouncilVerdict`, `ExperimentSpec`, `Budget`, `DomainScope`, `EvidenceLedgerEntry`, `RunReport`, `ValidationResult`, `SurrogateProbeResult`, `FactoryControlEvent`, `Strategy`, `StrategyCycleEvidence`) plus supporting models (`ControlDefinition`, `UncertaintyBlock`, `CheckOutcome`, `CrossSimulatorComparison`, `DissentEntry`, `FidelityTier`, `BudgetLedgerEntry`, `RelitigationTrigger`, `ProvenanceBlock`, `BehaviorDescriptor`, `ConstraintOvershootStats`).
- [ ] Implement `Strategy` + `StrategyCycleEvidence` Pydantic models with provenance hashing (`Strategy.sha` is the content hash of `summary_md`; `parent_shas` carries lineage).
- [ ] Implement `BehaviorDescriptor` + `ConstraintOvershootStats` supporting models (frozen, `extra="forbid"`, no top-level artifact persistence).
- [ ] Add `surprise_bits: float | None` field to `EvidenceLedgerEntry` (default `None`; populated by spec 016 archive post-cycle).
- [ ] Write canonical-JSON serializer with determinism tests and explicit NaN/Infinity rejection.
- [ ] Write `verify_chain` walker covering all thirteen artifacts.
- [ ] Write `factory/artifacts/cli.py` with `validate`, `hash`, `show`, `verify-chain`, `emit-schemas` subcommands.
- [ ] Author 3 fixtures per artifact (typical, edge, malformed) in `factory/artifacts/fixtures/<artifact_type>/`, including new fixtures for `Strategy`, `StrategyCycleEvidence`, and an updated `EvidenceLedgerEntry` fixture that exercises both `surprise_bits=None` and a scored case.
- [ ] Write `tests/test_artifacts_typical_usage.py` plus the 8 other test files listed in §7.
- [ ] Add CI step emitting JSON schemas; fail on drift.
- [ ] Add CI step `--audit-immutability` that rejects `list[...]` and raw `dict` on artifact fields.
- [ ] Write `docs/runbooks/artifacts-debugging.md` covering common failures.
- [ ] Add `factory/artifacts/README.md` 1-page overview.
- [ ] Verify `mypy --strict factory/artifacts/` passes.
- [ ] Verify `python -m factory.artifacts show --type HypothesisSpec --fixture sample` works on a fresh checkout.
