# Spec 009: Validation Portfolio (G4)

> Status: ☐ not started · Owner: TBD · Last updated: 2026-05-23

## CONTEXT (60-second summary — read first)
- The **Validation Portfolio** is the deterministic G4 gate: it runs nine orthogonal checks (conservation, numerical convergence, refinement / Richardson, CFL / temporal stability, held-out symmetries, limiting cases, statistical validity, cross-simulator, provenance hashing) against a candidate's `RunArtifacts` (spec 006 §4), and emits a `ValidationResult` artifact (canonical definition in spec 002 — see FIX_PLAN §1) carrying a binary PASS/FAIL plus per-check residuals. The G4 gate outcome is then `pass`, `fail`, or `inconclusive` (the last only when cross-simulator is unavailable AND refinement+symmetry cannot disambiguate).
- The 5 facts you need to know: (1) **no LLM is ever called inside G4** — pure physics + statistics + hashing; strict deterministic; (2) the portfolio is a *package of orthogonal defenses* — ANY single check failure fails the portfolio (no first-failure abort: run all checks for diagnostics); (3) the symmetry test fixtures are **held out from code-gen visibility** (they are the defense against invariant hacking, SPEC.md §10.3); (4) the *only* metric that may be reported in statistical validity is `HypothesisSpec.pre_registered_metric` (defined on the parent `HypothesisSpec` per spec 002 §3 — `ExperimentSpec` does NOT carry this field) — no cherry-picking; (5) when cross-simulator validation is not available for the observable, weight on refinement + symmetry is automatically increased (SPEC.md §8 final paragraph).
- Open first: `factory/validation/api.py` (the nine check entry points and `ValidationPortfolio.run(...)`), then `factory/validation/tests/test_validation_typical_usage.py`.

## ENTRY POINTS
- Main module: `factory/validation/api.py`
- Typical-usage test: `factory/validation/tests/test_validation_typical_usage.py`
- CLI: `python -m factory.validation --help` (subcommands: `run`, `check`, `show`, `list-fixtures`, `verify-holdout-isolation`)
- Mock-mode example: `python -m factory.validation run --experiment-fixture sample_passing --candidate-fixture sample_candidate --mock-mode`
- Runbook: `docs/runbooks/validation-debugging.md` (canonical name per FIX_PLAN §21)

## LOCAL DEBUG
- Instantiate without any simulator running: `ValidationPortfolio(catalog=Catalog.mock_lineup(), ledger=Ledger.in_memory()).run(experiment_fixture, candidate_fixture)`. Mock mode returns deterministic PASS for the `sample_passing` fixture and a check-by-check FAIL diagnosis for `sample_failing`.
- Fixture artifacts:
  - `factory/validation/fixtures/results/passing_candidate.json` — synthetic run output that satisfies all nine checks (CFL skipped for the equilibrium-code fixture; explicit `skipped=True`).
  - `factory/validation/fixtures/results/refinement_inconsistent.json` — same observable claim, but two grid resolutions disagree past tolerance.
  - `factory/validation/fixtures/results/conservation_violated.json` — energy drift above tolerance.
  - `factory/validation/fixtures/results/symmetry_failed.json` — passes all *visible* invariants, fails held-out symmetry.
  - `factory/validation/fixtures/results/cherry_picked_metric.json` — reports a metric other than the pre-registered one (must FAIL `StatisticalInvalid`).
  - `factory/validation/fixtures/symmetry/<domain>/*.yaml` — held-out symmetry test cases, kept **outside** any directory that code-gen has read access to.
- Common error signatures → recovery:
  - `ConservationViolated` → check candidate output `conservation_diagnostics`; if real physics violation, code-gen iterates; if instrumentation bug, fix the diagnostic.
  - `ConvergenceFailed` → solver claims success but residual > tolerance; check `iterations_used`, `residual_norm`; bump iter cap or rebuild candidate.
  - `RefinementInconsistent` → grid-coarsening mismatch; raise base grid resolution in `ExperimentSpec` and rerun the candidate.
  - `SymmetryHeldOutFailed` → strong invariant-hacking signal; quarantine the candidate; do NOT loosen the symmetry test (that's the trap).
  - `LimitingCaseFailed` → axisymmetric / Newtonian / etc. limit produced wrong answer; physics bug in the candidate.
  - `StatisticalInvalid` → per-seed variance too high or reported metric ≠ pre-registered metric; rerun with more seeds or fix metric selection.
  - `CrossSimulatorDisagreement` → two simulators in the Catalog disagree past the equivalence-map tolerance; cycle is `inconclusive`, not failed — escalate to operator for arbitration.
  - `ProvenanceIncomplete` → a required hash (code / env / input / seed / sim version / container SHA) is missing; refuse to write to ledger.
  - `HeldoutLeakDetected` → static scan found a symmetry fixture path inside code-gen-visible context; **hard halt** the whole cycle and audit.
- Logs to inspect: every portfolio run writes a structured trace to `runs/<cycle-id>/validation/<candidate_id>/portfolio.jsonl` (one JSON line per check). Filter `runs/<cycle-id>/cycle.jsonl` by `module=validation`.

## DEPENDENCIES
- **Hard:**
  - Spec 002 (Typed Artifacts) — **canonical owner** of `ValidationResult`, `CheckOutcome`, `CrossSimComparison`, `LimitingCaseSpec`, and `ConservationTolerance` (per FIX_PLAN §1 + §15.2). This spec references those types; it does **not** add them itself.
  - Spec 002 also owns `HypothesisSpec.pre_registered_metric` (defined on the parent `HypothesisSpec`, see spec 002 §3) — the statistical check (§5.6) reads from there.
  - Spec 004 (Simulator Catalog) — cross-simulator check (§5.8) reads the `cross_simulator_equivalence_map` from Catalog entries via `Catalog.get(simulator_id)`; the simulator's `domain` (used for config dispatch) is read from the catalog entry, **never** from `ExperimentSpec`.
  - Spec 006 (Domain Adapter) — owns `RunArtifacts` (spec 006 §4) and the `Adapter.output_schema()` ABC method that names the keys the adapter promises to populate. The portfolio consumes those — it never reads a `domain` or `adapter_schema` field off `ExperimentSpec`.
  - Spec 008 (Generator-Verifier) — produces the `CandidateRunOutput` payload (§3) by wrapping a promoted `RunArtifacts` with the cross-cutting metadata (provenance hashes, per-seed values, refinement-grid map) the portfolio needs.
  - Spec 012 (Evidence Ledger) — every `ValidationResult` is persisted to the ledger with its full `ProvenanceBlock`; the ledger is the durability boundary for G4 outcomes.
- **Soft:**
  - Spec 005 (Simulator Selector) — needed only when re-running a cross-simulator check on the second simulator (the runner here delegates to the Selector's `select_for_observable(...)` to find the secondary candidate; fallback: skip cross-sim and re-weight per §5.8.3).
  - Spec 014 (Telemetry) — every check emits a structured event; graceful no-op if telemetry is unavailable.
- **Mocks available:**
  - `ValidationPortfolio.mock_factory()` returns a portfolio whose check implementations are fixture-driven (deterministic PASS / FAIL based on which fixture file is loaded).
  - `MockSecondarySimulator` for the cross-simulator runner.
  - `MockCatalogClient` exposing a single Catalog entry with a small `cross_simulator_equivalence_map`.
  - Held-out symmetry fixtures use a separate `MockSymmetryStore` that mimics the production access-control behaviour (read-only, not on code-gen path).

---

## 1. Summary

G4 is the deterministic firewall between code-gen optimism and the Evidence Ledger. It is a **portfolio**, not a single check, because every individual defense has a known failure mode against an adversarial generator:

- Conservation alone is hackable (a code-gen learns to satisfy named invariants while solving the wrong problem — SPEC.md §10.3).
- Convergence alone is hackable (a solver may converge to a wrong answer on a too-coarse grid — SPEC.md §8 row 3).
- Statistics alone is hackable (a generator reports whichever of N metrics happens to be significant — SPEC.md §8 row 6).
- Symmetry alone is fragile if the code-gen ever sees the symmetry tests (it overfits).
- Cross-simulator alone is unavailable in many domains.

The portfolio runs **all nine** checks for every candidate that reaches G4, accumulates per-check outcomes into a single immutable `ValidationResult`, and emits one binary verdict: PASS (every check passed within its tolerance) or FAIL (one or more checks failed). The state machine (spec 003) converts that into a G4 outcome (`pass` / `fail` / `inconclusive` per §5.11).

This module is **pure** — no LLM calls, no councils, no judgement. Strict deterministic. Every threshold, tolerance, and reweighting policy is configured ahead of time and recorded in the `ValidationResult` so the outcome is reproducible bit-for-bit. The implementation also fails loud: a missing diagnostic, a missing config entry, or a mis-shaped `RunArtifacts` raises rather than silently passing — there is no defensive try/except around check bodies.

## 2. Scope

**In scope:**
- The nine check implementations listed below (§5.1 – §5.9).
- The `ValidationPortfolio` orchestrator that runs them all, never short-circuits on first failure, and aggregates results into `ValidationResult`.
- The check-side use of `ValidationResult`, `CheckOutcome`, `CrossSimComparison`, `LimitingCaseSpec`, `ConservationTolerance` — all **defined in spec 002** (canonical owner per FIX_PLAN §1). This spec specifies how they are populated, not where they live in the artifact registry.
- Per-domain configuration of conservation invariants, limiting cases, CFL caps, and symmetry fixtures (`factory/validation/config/<domain>.yaml`).
- Held-out symmetry fixture **access isolation** — fixtures live under `factory/validation/fixtures/symmetry/<domain>/` and an automated check (`verify-holdout-isolation`) asserts the path is not in code-gen's read-allowlist.
- Cross-simulator runner that re-executes a candidate on a second Catalog simulator and compares observables within the `cross_simulator_equivalence_map` tolerance.
- Reweighting policy when cross-simulator is unavailable (§5.8.3).
- Provenance hashing on the `ValidationResult` (every field that contributed to the verdict is included in the hash).
- CLI: `run`, `check`, `show`, `list-fixtures`, `verify-holdout-isolation`.
- Mock mode.

**Out of scope:**
- The decision to *route* to G4 (spec 003 owns gate orchestration).
- The G5 claim interpretation council (spec 001, council C3).
- The G2.5 tractability dry-run (spec 003 + spec 008).
- The G3 surrogate / OOD detector (spec 010).
- Storing the `ValidationResult` long-term — spec 012 owns durability.
- Visualizing portfolio diagnostics in the operator UI (spec 015).

## 3. Public Interface

```python
# factory/validation/api.py

from datetime import datetime
from pathlib import Path
from typing import Literal, Sequence
from factory.artifacts import (
    ArtifactHash, CycleId, ExperimentSpec, HypothesisSpec, HypothesisId,
    ProvenanceBlock, ValidationResult, CheckOutcome, CrossSimComparison,
    ConservationTolerance, LimitingCaseSpec, _ArtifactBase, FactoryError,
)
from factory.adapter import RunArtifacts                # spec 006 §4
from factory.catalog import Catalog, ObservableName      # spec 004

# --- Errors -------------------------------------------------------------

class ValidationError(FactoryError):
    """Base class for all G4 validation failures."""

class ConservationViolated(ValidationError): ...
class ConvergenceFailed(ValidationError): ...
class RefinementInconsistent(ValidationError): ...
class CFLViolated(ValidationError): ...
class SymmetryHeldOutFailed(ValidationError): ...
class LimitingCaseFailed(ValidationError): ...
class StatisticalInvalid(ValidationError): ...
class CrossSimulatorDisagreement(ValidationError): ...
class ProvenanceIncomplete(ValidationError): ...
class HeldoutLeakDetected(ValidationError):
    """Code-gen context referenced a held-out symmetry fixture path.

    Hard-halt; do not retry."""

# CheckOutcome and CrossSimComparison are defined canonically in spec 002.
# This spec's check implementations populate them; we re-export here for the
# convenience of consumers that import from factory.validation directly.
#
# Reference signatures (authoritative copy lives in factory.artifacts):
#
#     class CheckOutcome(BaseModel):
#         check_id: Literal[
#             "conservation", "convergence", "refinement", "cfl",
#             "symmetry_holdout", "limiting_case", "statistical",
#             "cross_simulator", "provenance",
#         ]
#         passed: bool
#         skipped: bool = False              # CFL / equilibrium codes set this
#         skipped_reason: str | None = None
#         tolerance: float | None
#         tolerance_kind: Literal["absolute", "relative", "mixed"] | None
#         tolerance_relative: float | None    # populated when kind == "mixed"
#         tolerance_absolute: float | None    # populated when kind == "mixed"
#         residual: float | None
#         details: dict                      # per-check structured diagnostics
#         duration_seconds: float
#         error_class: str | None
#
#     class CrossSimComparison(BaseModel):
#         primary_simulator_id: str
#         secondary_simulator_id: str | None
#         primary_value: float | None
#         secondary_value: float | None
#         tolerance: float | None
#         tolerance_kind: Literal["absolute", "relative", "mixed"] | None
#         agreement: bool | None
#         equivalence_map_version: str | None
#
#     class ConservationTolerance(BaseModel):
#         invariant: str
#         threshold: float
#         kind: Literal["absolute", "relative"]
#
# ValidationResult is also canonically defined in spec 002 — see §4 below for
# the field set and the cross-check validator.

# --- The orchestrator ---------------------------------------------------

class ValidationPortfolio:
    """Deterministic G4 portfolio. No LLMs. No councils. No surprises."""

    def __init__(
        self,
        catalog: Catalog,
        ledger: "LedgerClient",
        selector: "SelectorClient | None" = None,
        domain_config_dir: Path = Path("factory/validation/config"),
        fixture_dir: Path = Path("factory/validation/fixtures"),
        mock_mode: bool = False,
    ) -> None: ...

    def run(
        self,
        hypothesis: HypothesisSpec,                # parent — carries pre_registered_metric
        experiment: ExperimentSpec,                # child of hypothesis
        candidate_run_output: "CandidateRunOutput",
        cycle_id: CycleId,
    ) -> ValidationResult:
        """Execute all nine checks; never short-circuit.

        Returns a ValidationResult whose hash is recorded to the ledger.
        Raises HeldoutLeakDetected pre-emptively if the candidate's
        captured context references a held-out fixture path; this is the
        only path that aborts before running checks."""

    def check(
        self,
        check_id: str,
        hypothesis: HypothesisSpec,
        experiment: ExperimentSpec,
        candidate_run_output: "CandidateRunOutput",
    ) -> CheckOutcome:
        """Run a single named check in isolation; useful for triage."""

    @classmethod
    def mock_factory(cls) -> "ValidationPortfolio":
        """Deterministic mock portfolio. Returns the fixture-driven outcome."""

@dataclass(frozen=True)
class CandidateRunOutput:
    """Everything G4 needs from the Generator-Verifier loop to validate
    a candidate. Constructed by spec 008 at promote-time; consumed here.

    Note: there is no `domain` field. Domain is read from the catalog entry
    that owns `primary_simulator_id` (FIX_PLAN §15). Similarly there is no
    `adapter_schema` field — the schema is pulled from the Adapter ABC via
    `factory.adapter.load(primary_simulator_id).output_schema()` (spec 006).
    """
    hypothesis_id: HypothesisId
    candidate_artifact_path: Path           # boundary, mesh, config bundle
    run_artifacts: RunArtifacts             # spec 006 §4 — primary payload
    pre_registered_metric_value: float
    pre_registered_metric_name: str
    seed_values: dict[int, float]           # seed → pre-reg-metric value
    primary_simulator_id: str
    primary_simulator_version: str
    refinement_grid_values: dict[float, float]   # grid resolution (h) → metric
    conservation_diagnostics: dict[str, float]   # per-invariant residual
    solver_residual_norm: float
    solver_iterations_used: int
    solver_iteration_cap: int
    container_sha: str
    code_hash: str
    env_hash: str
    candidate_context_paths: list[Path]     # files the code-gen READ
```

The orchestrator does not import `factory.council` and never will — listed in the import-linter contract.

## 4. Data Structures / Schemas

The portfolio's load-bearing typed artifact, `ValidationResult`, is defined **canonically in spec 002** (FIX_PLAN §1 promotes it to the eleven-artifact registry). The same is true for the helper records `CheckOutcome`, `CrossSimComparison`, `ConservationTolerance`, and `LimitingCaseSpec`. This spec specifies how the portfolio **populates** them; it does not redefine them.

The reference field set (authoritative copy in `factory/artifacts/api.py`):

```python
class ValidationVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"

class ValidationResult(_ArtifactBase):
    """Output of one full G4 portfolio run. Immutable.

    The verdict is binary (PASS / FAIL). The state machine (spec 003)
    converts this into the gate's outcome by adding the `inconclusive`
    case when cross-simulator was unavailable AND refinement + symmetry
    were not sufficient to disambiguate (see §5.11)."""

    hypothesis_id: HypothesisId
    hypothesis_hash: ArtifactHash           # parent hash (carries pre_registered_metric)
    experiment_hash: ArtifactHash
    candidate_hash: ArtifactHash
    cycle_id: CycleId
    verdict: ValidationVerdict
    pre_registered_metric_name: str         # mirrored from HypothesisSpec
    pre_registered_metric_value: float
    pre_registered_metric_uncertainty: tuple[float, float]
    ci_method: Literal["bootstrap", "t_interval"]   # default bootstrap (§5.6)

    check_outcomes: list[CheckOutcome]      # one entry per of the 9 checks
    cross_simulator_comparison: CrossSimComparison
    reweighted_for_missing_cross_sim: bool  # see §5.8.3
    provenance: ProvenanceBlock             # mirrors what gets written to ledger
    portfolio_config_hash: ArtifactHash     # hash of tolerances/config used
    inputs_hash: ArtifactHash               # hash that produced this verdict
    duration_seconds: float

    @model_validator(mode="after")
    def _verdict_consistent_with_checks(self) -> "ValidationResult":
        """PASS only if every non-skipped CheckOutcome.passed is True.
        Skipped checks (e.g., CFL on equilibrium codes) do not affect
        verdict. Enforced at artifact construction; tampering surfaces
        immediately."""
        ...
```

`PortfolioConfig` is a config-loading model owned by this module (not an artifact — it is not content-addressed, not persisted to the artifact registry, and not consumed cross-module). It lives at `factory/validation/config.py`:

```python
class PortfolioConfig(BaseModel):
    """Per-domain tolerances and toggles. Loaded from
    factory/validation/config/<domain>.yaml at startup. NOT an artifact;
    its content hash is folded into ValidationResult.portfolio_config_hash."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    domain: str

    # ---- Conservation (§5.1, FIX_PLAN §15.2) ------------------------------
    conservation_tolerances: list[ConservationTolerance]   # typed; see spec 002

    # ---- Convergence (§5.2) -----------------------------------------------
    solver_residual_tolerance: float
    solver_max_iter_fraction: float         # iterations_used <= iter_cap * this

    # ---- Refinement / Richardson (§5.3, FIX_PLAN §15.1) -------------------
    refinement_grid_factors: list[float]    # actual h values, NOT a fixed ratio
    richardson_required_order: float        # expected convergence order p
    richardson_tolerance_factor: float      # |claim - extrap| < this * |claim|
    richardson_monotonicity_R_lo: float = 0.0   # require 0 < R < 1
    richardson_monotonicity_R_hi: float = 1.0

    # ---- CFL / temporal stability (§5.4 new sub-check, FIX_PLAN §15.3) ----
    time_dependent: bool = False            # set per-domain from simulator manifest
    cfl_max: float = 0.5                    # default advection cap
    cfl_diagnostic_keys: tuple[str, str, str] = ("dt", "dx_min", "v_max")

    # ---- Symmetry (held-out, §5.5) ----------------------------------------
    symmetry_fixture_dir: Path              # NOT in code-gen allowlist
    symmetry_tolerance: float

    # ---- Limiting cases (§5.6) --------------------------------------------
    limiting_cases: list[LimitingCaseSpec]  # canonical type in spec 002

    # ---- Statistical (§5.7, FIX_PLAN §15.5) -------------------------------
    min_seeds: int = 3                      # Phase A minimum (poor power; see §5.7)
    recommended_seeds: int = 10             # Phase B target; surfaced in details
    max_relative_std: float                 # std / |mean| <= this (relative branch)
    max_absolute_std: float                 # |std| <= this (near-zero branch)
    near_zero_threshold: float              # |mean| < this triggers absolute branch
    ci_method: Literal["bootstrap", "t_interval"] = "bootstrap"
    bootstrap_resamples: int = 10_000
    only_pre_registered_metric: bool = True # never set False in production

    # ---- Cross-simulator (§5.8, FIX_PLAN §15.6) ---------------------------
    require_cross_simulator: bool           # if True, missing cross-sim = FAIL
    reweight_when_cross_sim_missing: bool   # if True, apply §5.8.3 policy

    # ---- Finite-precision floor (FIX_PLAN §15.7) --------------------------
    precision_floor: float = 1e-15          # float64 default; 1e-7 for float32
```

JSON Schema for `ValidationResult`, `CheckOutcome`, `CrossSimComparison`, `ConservationTolerance`, and `LimitingCaseSpec` is auto-emitted to `docs/schemas/*.schema.json` by the spec-002 CI step. JSON Schema for `PortfolioConfig` is emitted by this module's CLI (`python -m factory.validation emit-schemas`).

## 5. Algorithms / Logic

The portfolio runs the nine checks in deterministic order (cheap → expensive); none of them short-circuit the others. Pseudocode skeleton:

```python
def run(hypothesis, experiment, candidate, cycle_id) -> ValidationResult:
    # 0. Pre-flight: held-out leak detection (the only allowed abort)
    _verify_no_holdout_leak(candidate.candidate_context_paths)

    # 1. Resolve domain from the catalog entry (NOT from ExperimentSpec).
    catalog_entry = catalog.get(experiment.simulator_id)
    domain = catalog_entry.domain
    cfg = _load_domain_config(domain)

    # 2. Pull the adapter's declared output schema from the ABC (spec 006).
    adapter = factory.adapter.load(candidate.primary_simulator_id)
    adapter_schema = adapter.output_schema()
    _verify_run_artifacts_match_schema(candidate.run_artifacts, adapter_schema)

    outcomes: list[CheckOutcome] = []

    # Nine checks, in order. Each appends to `outcomes`. Each check applies
    # the finite-precision floor: effective_tol = max(prescribed, cfg.precision_floor).
    outcomes.append(_check_conservation(candidate, cfg))
    outcomes.append(_check_convergence(candidate, cfg))
    outcomes.append(_check_refinement(candidate, cfg))
    outcomes.append(_check_cfl(candidate, cfg, catalog_entry))     # NEW (§5.4)
    outcomes.append(_check_symmetry_holdout(candidate, cfg))
    outcomes.append(_check_limiting_cases(candidate, cfg))
    outcomes.append(_check_statistical(hypothesis, candidate, cfg))  # reads HypothesisSpec
    cross_sim, cross_outcome = _check_cross_simulator(experiment, candidate, cfg, catalog_entry)
    outcomes.append(cross_outcome)
    outcomes.append(_check_provenance(candidate, experiment))

    # If cross-simulator missing AND policy allows, reweight refinement/symmetry
    reweighted = _maybe_reweight_for_missing_cross_sim(outcomes, cross_sim, cfg)

    # Verdict: PASS iff every non-skipped outcome.passed; else FAIL.
    decisive = [o for o in outcomes if not o.skipped]
    verdict = ValidationVerdict.PASS if all(o.passed for o in decisive) else ValidationVerdict.FAIL

    result = ValidationResult(
        ... ,
        verdict=verdict,
        check_outcomes=outcomes,
        cross_simulator_comparison=cross_sim,
        reweighted_for_missing_cross_sim=reweighted,
        ci_method=cfg.ci_method,
    )
    _persist_to_ledger(result)
    return result
```

Throughout the check implementations, every prescribed tolerance is floored at `cfg.precision_floor` before comparison — `effective_tol = max(prescribed_tol, cfg.precision_floor)`. The `CheckOutcome.tolerance` field records the effective tolerance, and `CheckOutcome.details["precision_floor_applied"]` records whether the floor changed the prescribed value (FIX_PLAN §15.7).

### 5.1 Conservation / invariants

Reads `candidate.conservation_diagnostics` (a `{invariant_name: residual_value}` map populated by the simulator adapter — spec 006 normalises the per-simulator units into the conventions named in the domain config). For each `ConservationTolerance` entry in `cfg.conservation_tolerances` (typed list, FIX_PLAN §15.2 — replacing the old untyped `dict[str, float]`):

- raw_residual = `diagnostics[entry.invariant]`
- effective_tol = `max(entry.threshold, cfg.precision_floor)`
- residual under test:
  - if `entry.kind == "absolute"`: `|raw_residual|`
  - if `entry.kind == "relative"`: `|raw_residual| / max(|reference|, cfg.precision_floor)` where `reference` is the matching value supplied by the adapter in `candidate.run_artifacts.observables[<invariant>_reference]` (the adapter is responsible for shipping the reference scale alongside the residual)
- failure iff `residual_under_test > effective_tol`

Per-domain configuration examples (loaded from `factory/validation/config/<domain>.yaml`; each entry is a `ConservationTolerance`):

- `stellarator-mhd` (FIX_PLAN §15.4):
  - **`force_balance` (PRIMARY stability invariant)** — the J×B − ∇p residual norm, read from `run_artifacts.diagnostics.force_balance_residual`. Default `kind="relative"`, `threshold=1e-9`. This is the load-bearing physics check; demoted invariants below it are structurally trivial.
  - `energy` (`kind="relative"`, `threshold=1e-9`): relative drift over the equilibrium iteration.
  - `momentum`, `mass`: per-equilibrium budget.
  - `W_MHD >= 0` (encoded as a sign-check pseudo-invariant `vacuum_well_sign`): non-negativity of the vacuum well — domain-specific stability invariant.
  - `div_B` (SECONDARY / trivial smoke test): max ‖∇·B‖ / ‖B‖ ≤ 1e-12. **Structurally trivial for vector-potential codes** because the discretisation makes ∇·B = 0 by construction; retained as a smoke test only. Demoted from the primary slot per FIX_PLAN §15.4 — operators must not rely on it as a stability signal.
- `cfd`: mass continuity residual, momentum residual, energy residual (each typed `ConservationTolerance`).
- Domains are *responsible for declaring their invariants in `config/<domain>.yaml`* — the validator never invents physics.

A missing diagnostic for a required invariant is a hard fail (`ConservationViolated` with `reason="diagnostic_missing"`; the simulator adapter didn't emit it — fix the adapter, do not silently pass).

`CheckOutcome.details` includes a per-invariant residual table (raw value, kind, threshold, effective_tol after precision floor, pass/fail) for diagnostic completeness — even when the check passes.

### 5.2 Numerical convergence

A solver may claim success while its residual norm exceeds tolerance. The check:

- `candidate.solver_residual_norm <= cfg.solver_residual_tolerance` (failure if exceeded — `ConvergenceFailed`).
- `candidate.solver_iterations_used <= cfg.solver_max_iter_fraction * candidate.solver_iteration_cap` (warns if at the cap — a solver pegged at its iter cap is a convergence-quality signal, not just a budget signal; recorded in details).

Both must pass. Either alone is insufficient.

### 5.3 Refinement convergence (Richardson where applicable, FIX_PLAN §15.1)

A solver may converge to a wrong answer because the grid was too coarse. The candidate is required to ship `refinement_grid_values: dict[float, float]` — at least two entries (`{h: metric_value}` for actual grid spacings `h`) populated by the Generator-Verifier loop (spec 008) when the experiment's fidelity ladder includes a refinement tier.

Procedure:

1. Sort entries by grid resolution, finest first: `(h_fine, f_fine), (h_mid, f_mid), (h_coarse, f_coarse), ...`. **The refinement ratio is not assumed to be 2** — actual `h` values may differ arbitrarily (Phase A intends factor-of-two ladders, but multi-grid / AMR runs may not be uniform).
2. **Two grids.** Compute relative difference `delta = |f_fine - f_coarse| / max(|f_fine|, cfg.precision_floor)`. Fail if `delta > max(cfg.richardson_tolerance_factor, cfg.precision_floor)`.
3. **Three or more grids — Richardson with variable refinement ratio.**
   a. **Monotonic-convergence pre-check.** Compute
      ```
      R = (f_mid - f_fine) / (f_coarse - f_mid)
      ```
      Richardson extrapolation is only meaningful if the sequence is monotonically converging — require `cfg.richardson_monotonicity_R_lo < R < cfg.richardson_monotonicity_R_hi` (defaults `0 < R < 1`). If the check fails, record `details["reason"] = "richardson_not_applicable_non_monotonic"` and `details["R"] = R`, fall back to the two-grid relative-difference test between the two finest grids, and continue. **Richardson does not run** in this case; the spec must surface that explicitly rather than producing a nonsense extrapolation.
   b. **Observed convergence order with actual refinement ratios.** Let `r_cm = h_coarse / h_mid` and `r_mf = h_mid / h_fine`. The observed order:
      ```
      p_obs = log((f_coarse - f_mid) / (f_mid - f_fine)) / log(r_cm)
      ```
      (Equal-ratio ladders give `r_cm == r_mf`; the formula remains correct for variable ratios because we only use the coarse→mid pair to estimate `p_obs`.)
   c. **Extrapolation with the actual fine-grid refinement ratio.**
      ```
      r = h_mid / h_fine                          # actual refinement ratio
      f_extrap = f_fine + (f_fine - f_mid) / (r**p_obs - 1)
      ```
      This replaces the prior hardcoded `2**p_obs - 1`, which silently assumed `r == 2` (FIX_PLAN §15.1).
   d. **Comparison against the claimed value.** Failure iff
      ```
      |candidate.pre_registered_metric_value - f_extrap|
          / max(|candidate.pre_registered_metric_value|, cfg.precision_floor)
          > cfg.richardson_tolerance_factor
      ```
   e. **Order warning.** Record (but do not necessarily fail on) `|p_obs - cfg.richardson_required_order|` — a large discrepancy suggests the solver order is wrong even when the answer agrees.
4. `CheckOutcome.details` records the sorted grid table, `R` (when ≥3 grids), `p_obs`, `r`, `f_extrap`, the comparison, and whether Richardson actually ran (vs. fallback).

If the experiment did not ship a refinement tier (and the domain config marks refinement as required), `RefinementInconsistent` fires with `details["reason"]="no_refinement_run_supplied"`.

### 5.4 CFL / temporal-stability check (FIX_PLAN §15.3)

For time-dependent simulators (advection, time-stepping PDEs, transport solvers), the Courant–Friedrichs–Lewy condition is a hard prerequisite for stability — a solver run with `dt > dx_min / v_max` produces numbers that look converged but are physically meaningless. This is a new sub-check introduced per FIX_PLAN §15.3 and adds the ninth check to the portfolio.

**Dispatch.** The check reads `time_dependent` from the catalog entry's manifest (`catalog.get(experiment.simulator_id).manifest.time_dependent`); the domain config's `cfg.time_dependent` mirrors that value for convenience but the catalog manifest is canonical. The check has two branches:

**5.4.1 Time-dependent branch.**
- Read `dt`, `dx_min`, `v_max` from `candidate.run_artifacts.diagnostics` (the adapter is required to populate these — a missing key fails with `CFLViolated` `reason="cfl_diagnostic_missing"`).
- Compute `cfl_number = dt * v_max / max(dx_min, cfg.precision_floor)`.
- Effective cap: `effective_cap = cfg.cfl_max` (precision floor does not apply — the cap is dimensionless and bounded away from zero by construction).
- Default `cfg.cfl_max = 0.5` for advection-dominated solvers; documented as `0.25` for diffusion-limited solvers. The per-domain config overrides this.
- Pass iff `cfl_number <= effective_cap`. Failure → `CFLViolated`.
- `CheckOutcome.details` records `dt`, `dx_min`, `v_max`, `cfl_number`, and the effective cap.

**5.4.2 Time-independent branch.**
- Equilibrium codes (e.g., VMEC for stellarator-MHD) have no temporal axis; the CFL check is meaningless.
- `CheckOutcome.skipped = True`, `CheckOutcome.skipped_reason = "time_independent_equilibrium_code"`.
- The skipped outcome does NOT count toward the FAIL aggregate (see §5.x verdict rule).

The check fails loud if the catalog manifest is missing a `time_dependent` field — the validator never invents that flag.

### 5.5 Symmetry tests **held out from code-gen visibility**

This is the defense against invariant hacking (SPEC.md §10.3). Two things matter equally — the tests themselves, and the *access control* that keeps them out of code-gen prompts:

**5.5.1 Access isolation.**
- Symmetry fixtures live under `factory/validation/fixtures/symmetry/<domain>/<case>.yaml`.
- The Generator-Verifier loop (spec 008) defines an explicit `code_gen_visible_paths` list. The symmetry directory must not be in (or reachable from) that list.
- `verify-holdout-isolation` (CLI subcommand + CI step) asserts:
  - the symmetry fixture directory is not in code-gen's read allowlist;
  - no prompt template references the symmetry directory path;
  - no candidate's recorded `candidate_context_paths` includes the symmetry directory (run-time check; on violation, raise `HeldoutLeakDetected` pre-emptively in §5 step 0 above).
- A leak triggers a hard halt of the cycle — the only abort allowed before running the nine checks. A leak means the defense is gone, not that this single candidate is bad.

**5.5.2 Test execution.**
- At G4 time, the portfolio loads N held-out symmetry test cases per domain (configured; default N=5 in Phase A).
- For each case: a `transform_fn` (dotted path) reads the candidate output, applies a symmetry transformation (e.g., reflection across a stellarator-symmetry plane, rotation by `2π/Nfp`, swap of toroidal index), and the test asserts that the observable is invariant within `cfg.symmetry_tolerance` (floored at `cfg.precision_floor`).
- The test cases themselves are deterministic; their RNG seeds are part of the fixture file (no run-time randomness).
- Failure: any case violating its tolerance.

The randomness defense: even though the cases are fixed, the code-gen never saw them, so it cannot have over-fit. Auditing this property is the job of §5.5.1.

### 5.6 Limiting cases

Generic "the answer in this limit is X" tests, configured per domain:

- Stellarator: axisymmetric limit (`Nfp → 1` with zero stellarator deformation) must reproduce the corresponding tokamak equilibrium within tolerance.
- Relativistic: low-velocity limit must reproduce Newtonian within tolerance.
- DFT: a one-electron system limit must reproduce the analytic hydrogenic energies.

Each `LimitingCaseSpec` provides a `transform_fn` (transforms the candidate into the limit configuration) and an `expected_observable_fn` (returns the analytic / authoritative answer). The check fails if `|observable_in_limit - expected| > tolerance`.

`details` records per-case observable, expected, tolerance, and the file path of the case spec — so diagnostic triage is one grep away.

### 5.7 Statistical validity (FIX_PLAN §15.5)

The defense against cherry-picking + low-power claims. The seed-count and CI choices in this section resolve the prior contradiction between this section and the old §5.9: both `min_seeds = 3` (Phase A) AND the bootstrap CI default are canonical here. Procedure:

1. **Metric identity check.** `candidate.pre_registered_metric_name == hypothesis.pre_registered_metric` — read from the parent `HypothesisSpec` (spec 002 §3), **NOT** from `ExperimentSpec` (which does not carry that field). If not equal, immediate fail (`StatisticalInvalid, reason="metric_swap"`). This is the per-experiment, per-result enforcement of the spec's "only the pre-registered metric is reported" rule.
2. **Seed count.**
   - `len(candidate.seed_values) >= cfg.min_seeds` — fail if fewer (`reason="insufficient_seeds"`).
   - Phase A default `cfg.min_seeds = 3`. The spec **explicitly acknowledges this gives poor statistical power**; downstream consumers (council C3, RunReport) must surface the seed count alongside the CI.
   - `cfg.recommended_seeds = 10` is the Phase B target — when actual seed count is below the recommended value but at or above the minimum, the outcome passes but `CheckOutcome.details["below_recommended_seeds"] = True` is set so C3 and the operator console can surface a "low power" warning.
3. **Per-seed dispersion** (FIX_PLAN §15.5, branch on near-zero):
   - `mean = mean(seed_values.values())`, `std = stdev(seed_values.values())`.
   - **Near-zero branch.** If `|mean| < cfg.near_zero_threshold`: compute `dispersion = |std|` and fail if `dispersion > cfg.max_absolute_std` (`reason="excessive_variance_absolute"`). Relative dispersion is undefined near zero, so the absolute test is the only meaningful one.
   - **Normal branch.** Otherwise: `dispersion = std / |mean|` and fail if `dispersion > cfg.max_relative_std` (`reason="excessive_variance"`).
   - `details["dispersion_branch"]` records which branch fired; `details["dispersion"]` records the value.
4. **Confidence interval emission** (FIX_PLAN §15.5, bootstrap default):
   - `cfg.ci_method` defaults to `"bootstrap"` (percentile bootstrap with `cfg.bootstrap_resamples = 10_000`, seeded by `candidate.hypothesis_id + "_statistical_ci"`).
   - `t_interval` is **opt-in only** via `cfg.ci_method = "t_interval"` — for cases where the operator has a defensible parametric story. The spec documents that with N=3 seeds, both methods have wide CIs; bootstrap is preferred because it makes no Gaussianity assumption.
   - The 95% CI is stored in `ValidationResult.pre_registered_metric_uncertainty` and `ValidationResult.ci_method` is set so downstream consumers see exactly which method produced the interval.
   - This CI is the *only* uncertainty number that downstream council C3 (claim interpretation) is allowed to cite.
5. **No multiple-testing.** The portfolio does not compute any p-value, score, or comparison against any metric other than the pre-registered one. There is no other-metric branch.

This check intentionally does **not** decide whether the metric value beats baseline — that is C3's interpretive call. G4 only validates that the metric is statistically well-formed.

### 5.8 Cross-simulator check (FIX_PLAN §15.6)

The strongest single defense against simulator-specific bugs (SPEC.md §8 row 7). Requires:

- Two or more Catalog entries (spec 004) that can compute the same observable for this experiment's domain, with a `cross_simulator_equivalence_map` entry binding them.

Procedure (§5.8.1) when a secondary is available, the recording rule (§5.8.2), and the reweighting policy (§5.8.3) when it is not.

**5.8.1 Run cross-simulator.**
1. Query `catalog.list_for_observable(observable)` (spec 004 canonical API per FIX_PLAN §4) and filter out the primary.
2. If exactly one secondary is returned, use it; if multiple, take the lowest-cost (cost from Catalog entry).
3. Use spec 005 `Selector.adapter_for(secondary)` (when available) to translate `candidate.candidate_artifact_path` into the secondary simulator's input format.
4. Spec 006's adapter (loaded via `factory.adapter.load(secondary_id)`) runs the candidate on the secondary. The same `pre_registered_metric_name` is computed.
5. Look up the equivalence entry for this observable in the primary's `cross_simulator_equivalence_map[observable]` (an `EquivalencePair` from spec 004). Read `pair.tolerance_kind` and the appropriate `tolerance_*` scalars.
6. Compare per `tolerance_kind` (canonicalised per FIX_PLAN §15.6 — `mixed` requires both scalars):
   - `"absolute"`: failure iff `|primary_value - secondary_value| > max(pair.tolerance_absolute, cfg.precision_floor)`.
   - `"relative"`: failure iff `|primary_value - secondary_value| / max(|primary_value|, cfg.precision_floor) > pair.tolerance_relative`.
   - `"mixed"` (ASME V&V 20): both `pair.tolerance_relative` and `pair.tolerance_absolute` are required; failure iff
     ```
     |primary_value - secondary_value|
         > max(pair.tolerance_relative * |primary_value|, pair.tolerance_absolute)
     ```
     The `max(...)` (NOT a sum) ensures the looser of the two limits dominates in the regime that matches the data scale.
   - In all branches, emit `CrossSimulatorDisagreement` on failure. `CheckOutcome.tolerance_kind`, `tolerance_relative`, and `tolerance_absolute` are populated to record exactly which test fired.

**5.8.2 Recording.** `CrossSimComparison` is populated regardless of outcome (including unavailable). The `equivalence_map_version` field is the catalog `version_hash()` (spec 004 §3) at run-time, so a subsequent map update changes the validation hash and forces re-litigation per spec 012's `relitigate_if` policy.

**5.8.3 Reweighting policy when cross-simulator is unavailable.**

If no secondary simulator exists (or selector returns none), AND `cfg.require_cross_simulator` is `False`, the portfolio reweights — meaning the *thresholds* for two earlier checks are tightened, not the verdict logic. Specifically:

| Check | Default tolerance | Tightened tolerance | Justification |
| :--- | :--- | :--- | :--- |
| Refinement (§5.3) | `richardson_tolerance_factor` | `richardson_tolerance_factor / 2` | More confidence in solver mesh quality is required. |
| Symmetry held-out (§5.5) | `symmetry_tolerance` | `symmetry_tolerance / 2` | More invariants must hold within tighter bounds. |

The tightening must happen **before** the corresponding check runs (the CheckOutcome records the actually-used tolerance, floored at `cfg.precision_floor`). The portfolio sets `reweighted_for_missing_cross_sim=True` so spec 012 and C3 know the verdict was produced under the missing-cross-sim regime.

If `cfg.require_cross_simulator` is `True` and no secondary is available, the cross-simulator check fails immediately (`CrossSimulatorDisagreement` with `reason="secondary_unavailable_and_required"`). This is the policy lever for domains where a missing cross-sim is unacceptable.

### 5.9 Provenance hashing

The cheapest, last-line check. Reads `candidate` and asserts that every field required for a complete `ProvenanceBlock` is populated:

- `code_hash` — hash of the candidate's code bundle.
- `env_hash` — hash of the resolved environment (lockfile + system libs).
- `input_hash` — hash of the experiment + candidate inputs.
- `seed` — integer (or null only if the experiment is explicitly seedless, which Phase A disallows).
- `simulator_id` — must equal `experiment.simulator_id`.
- `simulator_version` — must equal `candidate.primary_simulator_version`.
- `container_sha` — must equal `candidate.container_sha`.

A null field where one is required raises `ProvenanceIncomplete`. The check also assembles the `ProvenanceBlock` instance — that exact instance is what gets written to the ledger (spec 012), so this check is the single source of truth for provenance content of this validation.

### 5.10 Determinism guarantees

- The portfolio sets no environment state and reads no clock other than to record wall-clock duration in `CheckOutcome.duration_seconds` (excluded from `inputs_hash`).
- Any randomness used by a check (e.g., bootstrap resampling for the CI in `_check_statistical`) MUST be seeded by `candidate.hypothesis_id` plus the check name, and the seed must be recorded in `CheckOutcome.details["rng_seed"]`. The default `cfg.bootstrap_resamples = 10_000` is part of the config hash and therefore folded into `inputs_hash` — changing it would invalidate prior validations, which is intentional.
- Re-running `ValidationPortfolio.run(...)` on the same `(hypothesis, experiment, candidate)` inputs must produce a `ValidationResult` with the same `inputs_hash` and the same per-check pass/fail outcomes. Reproducibility is asserted by `test_validation_determinism.py`.

### 5.11 Mapping the verdict to a G4 gate outcome

`ValidationResult.verdict` is binary. The state machine (spec 003) maps it to a gate outcome:

```
if verdict == PASS:
    gate_outcome = "pass"
elif verdict == FAIL:
    if (cross_simulator_comparison.secondary_simulator_id is None
        and refinement_outcome.passed
        and symmetry_outcome.passed):
        # We had to reweight; checks passed under tightened tolerances;
        # remaining failure was elsewhere (e.g., conservation). FAIL stands.
        gate_outcome = "fail"
    elif (cross_simulator_comparison.secondary_simulator_id is None
          and not (refinement_outcome.passed and symmetry_outcome.passed)):
        # No secondary AND refinement/symmetry didn't disambiguate.
        gate_outcome = "inconclusive"
    else:
        gate_outcome = "fail"
```

This is the only place in spec 003 that introduces `inconclusive`; everywhere else, a gate outcome is `pass` or `fail`. The presence of the `inconclusive` branch is exactly the reason the `ValidationResult` carries `reweighted_for_missing_cross_sim` and full per-check outcomes — without those, spec 003 cannot compute this mapping.

## 6. Failure Modes

| Error class | When it fires | Recovery action |
| :--- | :--- | :--- |
| `ConservationViolated` | A typed `ConservationTolerance` entry's residual exceeds its threshold (after the precision floor) — or a required diagnostic is missing | `ValidationResult.verdict=FAIL`; state machine routes hypothesis to `falsified` with the full per-invariant residual table in the ledger. |
| `ConvergenceFailed` | Solver residual exceeds tolerance | FAIL. If `iterations_used == iteration_cap`, the failure mode is most likely a too-tight iter budget; otherwise a solver bug — the ledger entry carries both. |
| `RefinementInconsistent` | Richardson / coarse-vs-fine comparison fails, or `R` indicates non-monotonic convergence with no fallback agreement | FAIL. State machine signals the Generator-Verifier loop to escalate the candidate's fidelity tier on retry. |
| `CFLViolated` | A time-dependent simulator's `cfl_number = dt * v_max / dx_min` exceeds `cfg.cfl_max`, or a required CFL diagnostic is missing | FAIL. Time-independent equilibrium codes never raise — the check skips with `CheckOutcome.skipped == True`. |
| `SymmetryHeldOutFailed` | Any held-out symmetry case violates its tolerance | FAIL. Strong invariant-hacking signal — the offending candidate is quarantined; the *symmetry test is not loosened* under any circumstance (that is the design trap to avoid). |
| `LimitingCaseFailed` | A configured limiting case produces the wrong observable | FAIL. Domain physics bug; surfaces in the ledger. |
| `StatisticalInvalid` | Metric swap (where `candidate.pre_registered_metric_name ≠ hypothesis.pre_registered_metric`), insufficient seeds, or excessive per-seed dispersion (absolute or relative branch per §5.7) | FAIL. The candidate either reran with more seeds (spec 008) or its hypothesis is `inconclusive` if dispersion cannot be reduced. |
| `CrossSimulatorDisagreement` | Two simulators disagree past the equivalence-map tolerance under the entry's `tolerance_kind` (`absolute` / `relative` / `mixed`) | FAIL. State machine surfaces to operator; this is the single highest-signal disagreement and warrants human attention. |
| `ProvenanceIncomplete` | A required hash / id / version is missing | FAIL. Never write the ledger entry. State machine retries the candidate's provenance assembly; a second failure escalates to a build-system bug. |
| `HeldoutLeakDetected` | Code-gen context referenced a held-out fixture path | **Hard halt of the cycle.** No retries — the defense itself is compromised; operator must audit and reset the visibility configuration before any further G4 runs in this domain. |

All errors inherit `ValidationError(FactoryError)`. Spec 003's gate state machine catches `ValidationError` once at the gate boundary and produces the failure event; it never catches them mid-check.

## 7. Testing

**Mock-mode unit tests** (`factory/validation/tests/`):
- `test_validation_typical_usage.py` — REQUIRED. Constructs a passing candidate fixture, runs the full portfolio, asserts `ValidationResult.verdict == PASS`, every non-skipped `CheckOutcome.passed`, ledger writeback occurred.
- `test_conservation.py` — feeds residuals across tolerance boundary for both `absolute` and `relative` `ConservationTolerance` kinds; verifies pass/fail symmetry and tolerance edge cases; verifies that the stellarator-mhd config uses `force_balance` as the primary check and `div_B` only as a secondary smoke test.
- `test_convergence.py` — claim-succeeded-with-high-residual case; iter-cap-pegged warning case.
- `test_refinement.py` — 2-grid mismatch fail; 3-grid Richardson agreement pass (variable refinement ratio `r ≠ 2`); wrong-order warning case; non-monotonic `R` triggers fallback with `details["reason"]="richardson_not_applicable_non_monotonic"` and explicit no-extrapolation path.
- `test_cfl.py` — time-dependent simulator (e.g., advection mock) with `cfl_number < cfl_max` passes; with `cfl_number > cfl_max` fails; equilibrium (time-independent) simulator: `CheckOutcome.skipped == True` with `skipped_reason == "time_independent_equilibrium_code"`; missing diagnostic raises `CFLViolated` with `reason="cfl_diagnostic_missing"`.
- `test_symmetry_holdout.py` — passes when symmetry holds; fails when violated; verifies the symmetry fixture is loaded from the held-out directory, not anywhere code-gen could see.
- `test_holdout_leak.py` — feed a candidate whose `candidate_context_paths` references the symmetry directory; assert `HeldoutLeakDetected` and that **no checks run**.
- `test_limiting_cases.py` — axisymmetric-limit case for stellarator domain; Newtonian-limit case for relativistic domain (uses fixture).
- `test_statistical.py` — metric-swap fail (where `candidate.pre_registered_metric_name ≠ hypothesis.pre_registered_metric`); insufficient-seeds fail; below-recommended-seeds detail flag set; near-zero `|mean|` branch uses absolute std; normal branch uses relative std; bootstrap-default CI and t-interval opt-in CI both exercised on an analytic case.
- `test_cross_simulator.py` — both simulators agree (pass); disagree past tolerance (fail) for each of `absolute`, `relative`, and `mixed` tolerance kinds — including a `mixed` case where `max(relative * |ref|, absolute)` is the decisive bound; secondary unavailable (records `reweighted_for_missing_cross_sim=True` and tightened tolerances); required-but-missing (fail).
- `test_provenance.py` — every field required, every field missing once; assert `ProvenanceIncomplete` lists the missing field name.
- `test_precision_floor.py` — feeds an artificially tight tolerance below `cfg.precision_floor`; verifies `CheckOutcome.tolerance` is floored and `details["precision_floor_applied"] == True`.
- `test_validation_determinism.py` — run the portfolio twice with `cfg.ci_method == "bootstrap"`; assert `inputs_hash` and every `CheckOutcome.passed` match exactly (the bootstrap RNG seed is part of the hash).
- `test_run_no_short_circuit.py` — feed a fixture that fails check #1; assert checks #2–#9 still ran (per the "diagnostic completeness" rule).
- `test_gate_outcome_mapping.py` — exhaustive matrix of pass/fail combinations × cross-sim-present/absent; assert the §5.11 mapping is exact.
- `test_no_llm_dependency.py` — static import check: `factory/validation/` does NOT import `factory.council`, `anthropic`, `openai`, `google.generativeai`, or any other LLM SDK. Enforced by `import-linter` config.

**Mock-mode integration test** (`tests/integration/test_validation_with_ledger.py`):
- Construct a passing candidate, run the portfolio, verify the `ValidationResult` artifact persists to the in-memory ledger fixture and that its `inputs_hash` is reproducible.

**Live-mode tests** (`@pytest.mark.live`, gated):
- `test_live_cross_simulator_stellarator.py` — runs a known-good candidate against two real catalog simulators; asserts agreement within the published equivalence-map tolerance. Manual gate before merge to main; rerun on Catalog updates.

**CI step:** `python -m factory.validation verify-holdout-isolation` runs on every commit, asserting:
- The symmetry fixture directory is not in any code-gen allowlist (parsed from spec 008 configs).
- No prompt template references the symmetry directory path.
- No committed fixture under `runs/` references the symmetry directory.

A failure of this step blocks merge — the entire defense rests on the directory being invisible to code-gen.

**Typical-usage test contract:** The required `test_validation_typical_usage.py` is the *canonical* example. New agents copy it.

## 8. Performance & Budget

- Per portfolio run: ≤ 60 s wall clock, ≤ $0 LLM cost (no LLM calls). The dominant cost is the cross-simulator re-run, which inherits spec 006's domain-adapter cost characteristic for the secondary simulator.
- Cheap checks (conservation, convergence, statistical, provenance) run in < 200 ms each.
- Refinement is bounded by the cost of having computed the refined-grid run upstream — spec 008 owns that runtime; the validator only consumes its outputs.
- Symmetry and limiting cases require small additional simulator invocations (the transform + a single forward solve); budgeted into the experiment's iteration cap by spec 008.
- The portfolio respects no separate budget envelope — its cost is part of the experiment's `Budget.dollar_cap` (spec 013) and is logged through `factory.telemetry` (spec 014).

## 9. Open Questions

- **How many held-out symmetry cases per domain are "enough"?** Phase A picks N=5 by hand. The right N depends on the domain's typical invariant-hacking failure modes; needs calibration during Phase A runs.
- **Richardson extrapolation when the solver is not formally convergent at any analytic order.** Some practical solvers (adaptive-mesh, multi-grid with non-uniform refinement) don't have a clean `p_obs`. The current spec uses the monotonicity gate (FIX_PLAN §15.1) to refuse extrapolation in those cases and falls back to a two-grid relative-difference check; whether a more sophisticated criterion (e.g., generalized Richardson with variable order, GCI per ASME V&V 20) is needed is open.
- **`min_seeds = 3` statistical power.** FIX_PLAN §15.5 forces an honest acknowledgement: three seeds gives poor power even with bootstrap CIs. Phase A keeps `min_seeds=3` for compute reasons but surfaces `below_recommended_seeds` to C3; Phase B target is `recommended_seeds=10`. Whether the gate should *fail* below the recommended count (rather than warn) is open.
- **Cross-simulator equivalence map quality.** The map is human-curated per Catalog entry; its tolerances may be too loose or too tight. Spec 004 owns map evolution; this spec just consumes it. A poorly-tuned map could cause false `CrossSimulatorDisagreement`s.
- **Mixed-tolerance calibration.** ASME V&V 20's `max(relative * |ref|, absolute)` is the canonical choice (FIX_PLAN §15.6) but the *values* of the two scalars are heuristic in Phase A. Phase B may need a principled procedure for setting them per observable.
- **Reweighting policy magnitude.** §5.8.3 halves two tolerances. That choice is heuristic. Phase A measures the false-failure rate under reweighting; Phase B will replace with a principled value if needed.
- **Held-out fixture rotation.** If a symmetry fixture is in production for a long time, its existence — though not its content — could become deducible from logs. Whether to periodically rotate the fixture set is open and deferred to Phase B.
- **Multi-objective metrics.** Some experiments may want to validate a vector observable (e.g., the Pareto pair from `SPEC.md` §4 Problem 3). The current spec treats `pre_registered_metric` as scalar. Extending to vectors requires a per-component tolerance and is deferred.

## 10. TODO Checklist

- [ ] Scaffold `factory/validation/` from the canonical module template.
- [ ] **Depend on spec 002** for `ValidationResult`, `CheckOutcome`, `CrossSimComparison`, `LimitingCaseSpec`, and `ConservationTolerance` (canonical owner per FIX_PLAN §1 + §15.2) — do not re-declare here.
- [ ] Implement `ValidationPortfolio.__init__` with mock-mode parameter and config-file loading.
- [ ] Implement `_load_domain_config` reading `factory/validation/config/<domain>.yaml` and resolving `domain` from `catalog.get(experiment.simulator_id).domain` (never from `ExperimentSpec`).
- [ ] Implement `_verify_no_holdout_leak` and the `HeldoutLeakDetected` pre-flight guard.
- [ ] Implement `_verify_run_artifacts_match_schema` against `adapter.output_schema()` (spec 006).
- [ ] Implement `_check_conservation` consuming `list[ConservationTolerance]` with both `absolute` and `relative` `kind` branches; per-invariant residual table in details (FIX_PLAN §15.2 + §15.4 demoting `div_B` to a secondary smoke test under stellarator-mhd).
- [ ] Implement `_check_convergence` with residual + iter-cap-pegged warning.
- [ ] Implement `_check_refinement` with monotonic-convergence `R` gate, variable-ratio Richardson `r = h_mid / h_fine`, and the explicit non-monotonic fallback (FIX_PLAN §15.1).
- [ ] **NEW** Implement `_check_cfl` reading `dt`, `dx_min`, `v_max` from `run_artifacts.diagnostics`; dispatch on `catalog_entry.manifest.time_dependent`; skip for equilibrium codes with `CheckOutcome.skipped=True` (FIX_PLAN §15.3).
- [ ] Implement `_check_symmetry_holdout` reading from `fixtures/symmetry/<domain>/`; load test cases deterministically; verify the directory is not in any code-gen allowlist.
- [ ] Implement `_check_limiting_cases` dispatching configured `transform_fn` and `expected_observable_fn` per case.
- [ ] Implement `_check_statistical` reading the pre-registered metric name from `hypothesis.pre_registered_metric` (NOT `experiment.*`); seed-count with `below_recommended_seeds` detail flag; near-zero vs. relative dispersion branch; bootstrap-default CI with t-interval opt-in (FIX_PLAN §15.5).
- [ ] Implement `_check_cross_simulator` (uses spec 005 selector + spec 006 adapter; canonical Catalog API per FIX_PLAN §4); support `absolute`, `relative`, and `mixed` tolerance kinds per FIX_PLAN §15.6.
- [ ] Implement `_maybe_reweight_for_missing_cross_sim` enforcing the §5.8.3 policy and recording the reweight flag.
- [ ] Implement `_check_provenance` and `_assemble_provenance_block` that yields the canonical `ProvenanceBlock` for the ledger.
- [ ] Implement the finite-precision floor (FIX_PLAN §15.7): every tolerance comparison applies `effective_tol = max(prescribed, cfg.precision_floor)`; default 1e-15 (float64) / 1e-7 (float32).
- [ ] Wire the orchestrator `run(...)` to call all nine checks, never short-circuit, and assemble `ValidationResult`. PASS iff every non-skipped outcome passes.
- [ ] Implement `_persist_to_ledger(result)` via the spec 012 client.
- [ ] Build the deterministic `mock_factory()` fixture-driven implementation.
- [ ] Author per-domain config fixtures: `factory/validation/config/stellarator-mhd.yaml` (Phase A primary, with `force_balance` as primary conservation invariant and `div_B` as secondary), and one orthogonal domain config to enable cross-simulator validation per `SPEC.md` §11 Phase A.
- [ ] Author the initial 5 held-out symmetry test cases per domain in `factory/validation/fixtures/symmetry/<domain>/`.
- [ ] Author candidate-output fixtures: passing, conservation-violated, refinement-inconsistent (incl. non-monotonic `R`), cfl-violated, symmetry-failed, cherry-picked-metric, holdout-leak, equilibrium-code-cfl-skipped.
- [ ] Write `factory/validation/cli.py` with `run`, `check`, `show`, `list-fixtures`, `verify-holdout-isolation`, `emit-schemas` subcommands.
- [ ] Add `import-linter` rule: `factory.validation` forbids importing `factory.council`, `anthropic`, `openai`, `google.generativeai`, `factory.literature`.
- [ ] Write the typical-usage test plus all 15 unit tests listed in §7 (added `test_cfl.py` and `test_precision_floor.py`).
- [ ] Write the live-mode cross-simulator integration test (`@pytest.mark.live`, gated).
- [ ] Add CI step running `verify-holdout-isolation` on every commit; fail merge on violation.
- [ ] Write `docs/runbooks/validation-debugging.md` (canonical name per FIX_PLAN §21) covering per-check failure triage and the holdout-leak hard-halt recovery path.
- [ ] Write `factory/validation/README.md` (≤ 1 page, mock-mode example).
- [ ] Verify `mypy --strict factory/validation/` passes.
- [ ] Verify `python -m factory.validation run --mock-mode` works on a fresh checkout.
- [ ] Verify the §5.11 gate-outcome mapping with the state machine team (spec 003) before merging.
