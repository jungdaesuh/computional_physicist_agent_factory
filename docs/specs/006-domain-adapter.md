# Spec 006: Domain Adapter

> Status: ☐ not started · Owner: TBD · Last updated: 2026-05-23

## CONTEXT (60-second summary — read first)
- The **Domain Adapter** layer separates the *abstract solver interface* (defined once for the whole factory) from the *per-simulator translation code* (one adapter module per `SimulatorCatalog` entry). The Generator-Verifier loop (spec 008) targets the abstract interface; the adapter for the chosen `simulator_id` actually runs the experiment against that simulator's API/config format and returns structured `RunArtifacts` for the Validation Portfolio (spec 009) to consume.
- The 5 facts: (1) abstract interface = small set of pluggable Python ABCs covering the six-component solver blueprint (discretization/fidelity, boundary handling, update operator, acceptance/globalization, restart logic, local polishing) — defined once in `factory/adapter/abstract.py`; (2) one adapter module per catalog entry: `factory/adapter/<simulator_id>.py`; (3) adapter registration + lookup goes through `factory.adapter.load(simulator_id)`; (4) the load-bearing call is `adapter.run(experiment_spec, sandbox_dir) -> RunArtifacts`; (5) every adapter ships with a mock that returns fixture `RunArtifacts` so the Generator-Verifier loop is testable without any simulator container booting.
- Open first: `factory/adapter/abstract.py` (the ABCs) and `factory/adapter/tests/test_adapter_typical_usage.py`. Do *not* start by reading individual adapter modules — read the abstract interface first.

## ENTRY POINTS
- Main module: `factory/adapter/api.py` (public-facing registry + load function; the ABCs live in `factory/adapter/abstract.py`).
- Typical-usage test: `factory/adapter/tests/test_adapter_typical_usage.py`
- CLI: `python -m factory.adapter --help` (subcommands: `list`, `inspect <simulator_id>`, `run --experiment <hash> --mock-mode`).
- Mock-mode example: `python -m factory.adapter run --simulator-id sim_a --experiment-fixture sample --mock-mode`
- Runbook: `docs/runbooks/adapter-writing.md`

## LOCAL DEBUG
- Instantiate without containers: `adapter = factory.adapter.load("sim_a", mock_mode=True); adapter.run(spec, tmpdir)` returns fixture `RunArtifacts`.
- Live mode requires the catalog entry's container to be built (spec 004) and any simulator-side credentials / data files prepared per the catalog manifest.
- Common error signatures → recovery:
  - `AdapterNotRegistered` → the `simulator_id` has no adapter module; either onboard the simulator (spec 004) and write an adapter, or pick a different simulator at G1.5.
  - `AdapterContractViolation` → the adapter returned a `RunArtifacts` payload that does not satisfy the abstract interface; bug in the adapter — fix the adapter, do not loosen the contract.
  - `AdapterRuntimeFailure` → the simulator crashed, timed out, or produced unreadable output; state machine routes to the Generator-Verifier debugger (spec 008) for one re-try, then marks the experiment `intractable`.
  - `SimulatorConfigInvalid` → `ExperimentSpec.control_definition` or fidelity-ladder entries do not satisfy the simulator's input DSL; the adapter rejects *before* invoking the simulator, surfaced upstream.
- Logs to inspect: per-cycle sandbox layout is `runs/<cycle-id>/sandbox/<iteration:03d>/adapter_outputs/<seed>/` (canonical scheme; see FIX_PLAN §7). Adapter-level events go to `runs/<cycle-id>/sandbox/<iteration:03d>/adapter_outputs/<seed>/adapter.jsonl`; raw simulator output lives in `runs/<cycle-id>/sandbox/<iteration:03d>/stdout.log` and `stderr.log` (one stream per iteration, shared across seeds for that iteration's blueprint). Filter `runs/<cycle-id>/cycle.jsonl` by `module=adapter`. The legacy `runs/<cycle-id>/sandbox/<simulator_id>/<seed>/` layout is deprecated — `simulator_id` is implicit in the cycle's `ExperimentSpec.simulator_id`.

## DEPENDENCIES
- **Hard:** Spec 002 (artifacts) — adapter reads `ExperimentSpec` and emits `RunArtifacts` payloads consumed by spec 009. Spec 004 (catalog) — each adapter is paired 1:1 with a `SimulatorCatalog` manifest entry (license, container recipe, smoke test). Spec 008 (Generator-Verifier) — only intended caller of `adapter.run(...)` from inside the loop.
- **Soft:** Spec 013 (budget) — adapter reports per-run cost / wall-clock back through structured events when a budget context is provided; falls back to no-op cost reporting. Spec 014 (telemetry) — adapter emits structured events when present.
- **Mocks available:** Every adapter ships a `MockAdapter` subclass (in the same module file) that returns fixture `RunArtifacts` from `factory/adapter/fixtures/<simulator_id>/`. `factory.adapter.load(simulator_id, mock_mode=True)` returns the mock.

---

## 1. Summary

This module isolates the Generator-Verifier code-gen from per-simulator quirks. Code-gen targets a single abstract interface — the same six-component solver blueprint regardless of which simulator is selected — and the adapter for the chosen catalog entry translates that abstract program into the simulator's actual API or config DSL, runs it inside the sandbox, and returns structured `RunArtifacts` for downstream validation. Without this layer the factory would have to re-prompt code-gen for every simulator added to the catalog; with it, **adding a simulator is writing an adapter, not retraining a prompt**.

The distinction this spec must hammer home: the **abstract interface** is defined exactly once for the whole factory (`factory/adapter/abstract.py`); the **adapter** is a per-catalog-entry module (`factory/adapter/<simulator_id>.py`) that implements that interface for one specific simulator. Code-gen never sees the adapter; the Generator-Verifier loop never sees the simulator's native config DSL.

**Distinction vs. spec 017 (`FidelityLadderScheduler`).** This spec's `Discretizer` ABC (§3, Module 1 in FIX_PLAN §26.1) makes grid/mesh/spectral-basis choices **within one run** — given a single tier label, it returns the discretization handle the rest of the blueprint will solve on. The `FidelityLadderScheduler` from spec 017 sits one layer up and decides **which run is next on the fidelity ladder** (DRY_RUN → SURROGATE → ORACLE in Phase A) given the outcomes so far. The two never overlap: `Discretizer.configure(spec, tier_name)` is called *by* the per-tier execution that the scheduler dispatches.

## 2. Scope

**In scope:**
- The abstract solver interface as a small set of Python ABCs covering discretization/fidelity, boundary handling, update operator, acceptance/globalization, restart logic, and local polishing. The six canonical ABC names are locked per FIX_PLAN §26.1: `Discretizer`, `ConstraintAggregator`, `UpdateStepOperator`, `AcceptanceController`, `RestartController`, `LocalPolisher`.
- Adapter registration mechanism keyed by `simulator_id`.
- `factory.adapter.load(simulator_id, *, mock_mode=False) -> Adapter` lookup function.
- The `Adapter.run(experiment_spec, sandbox_dir) -> RunArtifacts` contract and its error taxonomy.
- The `Adapter.output_schema() -> AdapterOutputSchema` declarative contract — names which `RunArtifacts` fields the adapter promises to populate; consumed by spec 008's local-gate parser and spec 009's check-applicability gate.
- A canonical `RunArtifacts` payload schema (observables, residuals, diagnostics, sandbox paths, provenance fields) that spec 009 consumes; persistence path is `runs/<cycle-id>/sandbox/<iteration:03d>/adapter_outputs/<seed>/run_artifacts.json` (FIX_PLAN §7).
- Mock-mode for every adapter: same public API, fixture data, no container required.
- The "adding a new adapter" runbook and module template.

**Out of scope:**
- Defining the simulators themselves (spec 004).
- Choosing which simulator a given hypothesis routes to (spec 005, `SimulatorSelector`).
- The Generator-Verifier loop itself (spec 008) — this spec only defines what that loop is allowed to call.
- Validation logic (spec 009) — adapter only *produces* the artifacts the validator consumes.
- Cross-simulator equivalence checks (spec 009 §G4 with help from the catalog manifest).
- Container build orchestration (spec 004).

## 3. Public Interface

The skeleton fixes the call surface and locks the six ABC names per FIX_PLAN §26.1. Method bodies inside each ABC are intentionally left as `...` — concrete adapters bind them when the simulator is onboarded; the Generator-Verifier loop (spec 008) only ever sees the abstract surface.

```python
# factory/adapter/abstract.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from pydantic import BaseModel, ConfigDict
from factory.artifacts import ExperimentSpec, ArtifactHash

# --- Adapter output schema (declarative; consumed by specs 008 + 009) ---

class AdapterOutputField(BaseModel):
    """One named field the adapter promises to populate in RunArtifacts."""
    model_config = ConfigDict(frozen=True)
    name: str                                 # dotted path, e.g. "diagnostics.force_balance_residual"
    dtype: str                                # canonical dtype tag: "float", "int", "ndarray", "path", "dict[str,float]"
    units: str | None                         # SI units string when applicable, else None
    description: str                          # one-line human description (surfaced by `adapter inspect`)
    required: bool = True                     # if False, validators must tolerate absence

class AdapterOutputSchema(BaseModel):
    """Typed declaration of what RunArtifacts the adapter populates.

    Returned by `Adapter.output_schema()`. Consumed by:
      - spec 008 §5.1 local-gate parser: validates that the sandbox subprocess
        produced every `required=True` field before promote.
      - spec 009 validation portfolio: looks up which `diagnostics.*` fields are
        guaranteed to exist before invoking the corresponding check (e.g. only
        runs the CFL check if `diagnostics.dt`, `diagnostics.dx_min`,
        `diagnostics.v_max` are all declared).

    The schema is static for a given adapter version — produced once at import
    time, not per-run — so the local-gate parser can cache it.
    """
    model_config = ConfigDict(frozen=True)
    simulator_id: str
    schema_version: str                       # bumped when the adapter changes its declared keys
    canonical_tensor_filename: str            # the load-bearing output file (e.g. "canonical.npz")
    fields: list[AdapterOutputField]

# --- The six-component solver blueprint (canonical names locked per FIX_PLAN §26.1) ---
#
# Each ABC below maps 1:1 to a GCPH brain-folder module. Method bodies are
# intentionally `...` — concrete per-simulator adapters bind them. Spec 008's
# code-gen targets ONLY these ABCs; it never imports a concrete subclass.
#
# Note: `Discretizer` makes grid / mesh / spectral-basis choices WITHIN one run
# given a tier label. The decision of WHICH run is next on the fidelity ladder
# (DRY_RUN → SURROGATE → ORACLE in Phase A) lives one layer up in the spec 017
# `FidelityLadderScheduler` — a separate, non-overlapping component.

class Discretizer(ABC):
    """Module 1 — Fidelity & Discretization Manager.

    Owns: grid / mesh / spectral basis + per-run fidelity tier selection.
    Given an `ExperimentSpec` and a tier label, returns the discretization
    handle the rest of the blueprint will solve on. Does NOT decide which
    tier is next (that is spec 017's `FidelityLadderScheduler`).
    """
    @abstractmethod
    def configure(self, spec: ExperimentSpec, tier_name: str) -> "DiscretizationHandle": ...

class ConstraintAggregator(ABC):
    """Module 2 — Boundary & Constraint Aggregator.

    Owns: assembly of boundary conditions (Dirichlet / Neumann / periodic /
    free) plus any inequality / equality constraints the solver must honour.
    Returns a constraint handle the update operator consumes each step.
    """
    @abstractmethod
    def assemble(self, spec: ExperimentSpec, disc: "DiscretizationHandle") -> "ConstraintHandle": ...

class UpdateStepOperator(ABC):
    """Module 3 — Update & Step Operator.

    Owns: the iterative / stepping kernel (Newton, Runge-Kutta, SCF,
    gradient step, etc.). One call advances the solver state by one step.
    """
    @abstractmethod
    def step(self, state: "SolverState") -> "SolverState": ...

class AcceptanceController(ABC):
    """Module 4 — Globalization & Acceptance Controller.

    Owns: acceptance + globalization (line search, trust region, damping,
    backtracking). Given the previous state and a proposed step, returns
    the accepted next state.
    """
    @abstractmethod
    def accept(self, prev: "SolverState", proposed: "SolverState") -> "SolverState": ...

class RestartController(ABC):
    """Module 5 — Restart & Reset Controller.

    Owns: restart / continuation / homotopy logic when the solver stalls.
    Decides whether to restart from history and supplies the reseeded state.
    """
    @abstractmethod
    def should_restart(self, history: list["SolverState"]) -> bool: ...
    @abstractmethod
    def reseed(self, history: list["SolverState"]) -> "SolverState": ...

class LocalPolisher(ABC):
    """Module 6 — Polishing & Local Search.

    Owns: final local refinement once the solver has converged to a basin
    (e.g. one-pass Newton polish, BFGS clean-up, post-projection).
    """
    @abstractmethod
    def polish(self, state: "SolverState") -> "SolverState": ...

@dataclass(frozen=True)
class BlueprintComponents:
    """The six concrete components bound to one simulator.

    Returned by `Adapter.components()`. Order matches FIX_PLAN §26.1 modules
    1..6. Frozen so the binding is stable for the life of the adapter.
    """
    discretizer: Discretizer
    constraint_aggregator: ConstraintAggregator
    update_step_operator: UpdateStepOperator
    acceptance_controller: AcceptanceController
    restart_controller: RestartController
    local_polisher: LocalPolisher

# --- The per-catalog-entry adapter contract ---

class RunArtifacts(Protocol):
    """Structured outputs the Validation Portfolio (spec 009) consumes.

    Shape is stable across adapters; the *contents* of `observables`, `residuals`,
    and `diagnostics` are declared per-adapter via `Adapter.output_schema()`.
    The concrete Pydantic class lives next to spec 009's validator (final home
    decided in §10 TODO); adapter modules return any object that fulfils this
    protocol and persists at `runs/<cycle-id>/sandbox/<iteration:03d>/adapter_outputs/<seed>/run_artifacts.json`.

    Spec 009 reads the following fields (canonical names — adapters MUST populate
    these via `output_schema()` declarations):
      - `observables[<pre_registered_metric_name>]`     — point value per seed
      - `residuals["solver_residual_norm"]`             — convergence residual
      - `diagnostics["force_balance_residual"]`         — primary G4 residual for stellarator-mhd
                                                          (per FIX_PLAN §15.4)
      - `diagnostics["conservation_diagnostics"]`       — dict[invariant_name, residual_value]
                                                          (per FIX_PLAN §15.2)
      - `diagnostics["refinement_grid_values"]`         — dict[grid_resolution_h, metric_value]
                                                          (per FIX_PLAN §15.1 Richardson)
      - `diagnostics["dt"]`, `["dx_min"]`, `["v_max"]`  — CFL inputs when adapter
                                                          declares `time_dependent: True`
                                                          (per FIX_PLAN §15.3)
      - `diagnostics["div_B"]`                          — secondary smoke check (stellarator-mhd)
    """
    observables: dict[str, float]               # pre-registered metrics + invariants (keys from output_schema)
    residuals: dict[str, float]                 # convergence + conservation residuals (keys from output_schema)
    diagnostics: dict[str, object]              # spec 009 reads typed entries here; shape declared by output_schema
    sandbox_paths: dict[str, Path]              # named on-disk outputs (e.g. "wout", "log") under adapter_outputs/<seed>/
    seed: int
    fidelity_tier: str
    simulator_version: str
    container_sha: str
    wall_clock_seconds: float
    cost_usd: float
    parent_experiment_hash: ArtifactHash

class Adapter(ABC):
    """Per-simulator implementation of the abstract solver interface.

    One subclass per SimulatorCatalog entry. Subclasses live in
    factory/adapter/<simulator_id>.py and are auto-registered at import time.
    """

    simulator_id: str                            # MUST match a SimulatorCatalog entry id

    @abstractmethod
    def components(self) -> BlueprintComponents:
        """Return the six concrete components bound to this simulator.

        The returned `BlueprintComponents` carries one concrete subclass per
        ABC in FIX_PLAN §26.1 (Modules 1..6). Spec 008's code-gen consumes
        this tuple to wire the abstract solver loop without ever importing
        the concrete subclasses directly.
        """

    @abstractmethod
    def output_schema(self) -> AdapterOutputSchema:
        """Declare what fields the RunArtifacts payload will contain.

        Static for a given adapter version. Consumed by:
          - spec 008 §5.1 local-gate parser (validates promote-eligibility).
          - spec 009 validation portfolio (gates which checks fire).

        Returning a schema that the adapter's own `run(...)` does not honour
        is an `AdapterContractViolation` caught by the contract-enforcement
        startup check (§5.1).
        """

    @abstractmethod
    def run(
        self,
        experiment_spec: ExperimentSpec,
        sandbox_dir: Path,
    ) -> RunArtifacts:
        """Execute the experiment end-to-end inside the sandbox; return artifacts.

        Writes outputs to `sandbox_dir/adapter_outputs/<seed>/` (see FIX_PLAN §7).
        Note: `sandbox_dir` is the per-iteration root
        `runs/<cycle-id>/sandbox/<iteration:03d>/`; the simulator identity is
        implicit in `experiment_spec.simulator_id` and never appears in the path.

        Raises:
          SimulatorConfigInvalid   - bad inputs detected before launching the sim
          AdapterRuntimeFailure    - simulator crashed / timed out / unreadable output
          AdapterContractViolation - implementation bug; sim ran but output schema wrong
        """

# factory/adapter/api.py  (registry + load)

def register(adapter_cls: type[Adapter]) -> type[Adapter]:
    """Decorator. Adds the class to the registry keyed by simulator_id."""

def load(simulator_id: str, *, mock_mode: bool = False) -> Adapter:
    """Return the registered adapter (or its mock) for simulator_id.
    Raises AdapterNotRegistered if no adapter is registered for that id.
    """

def registered_ids() -> list[str]:
    """List all currently-registered simulator_ids (for CLI / debug)."""
```

The six ABCs and `BlueprintComponents` live in `factory/adapter/abstract.py` (per FIX_PLAN §26.5 repo layout). The concrete `DiscretizationHandle`, `ConstraintHandle`, and `SolverState` shapes — plus any shared helpers — belong in `factory/adapter/types.py`; spec 008 binds them when the Generator-Verifier loop is implemented.

## 4. Data Structures / Schemas

This module owns two load-bearing data structures:

1. **`AdapterOutputSchema`** (Pydantic, frozen) — declarative description of the `RunArtifacts` keys each adapter promises to populate. Returned by `Adapter.output_schema()`. Consumed by spec 008's local-gate parser (§5.1) and spec 009's validation portfolio (gating per-check applicability). Static per-adapter-version.
2. **`RunArtifacts`** (Protocol here; Pydantic-backed concrete class lives next to spec 009's validator — see §10 TODO for final home). Shape is uniform across adapters; field *contents* are declared per-adapter via `output_schema()`.

**Canonical persistence path (FIX_PLAN §7):**

```
runs/<cycle-id>/sandbox/<iteration:03d>/adapter_outputs/<seed>/
├── run_artifacts.json                   # the canonical RunArtifacts payload (this spec)
├── observables.json                     # mirrored observables map (spec 008 promote target)
└── diagnostics.json                     # mirrored diagnostics map (spec 009 read target)
```

The legacy `runs/<cycle-id>/sandbox/<simulator_id>/<seed>/` layout is **deprecated**; `simulator_id` is implicit in `ExperimentSpec.simulator_id` and is never encoded in the directory tree. The promote step (spec 008 §5.5) moves the contents of `adapter_outputs/` (across all seeds) into `runs/<cycle-id>/artifacts/<hash>/` once the local gate passes; the staging subtree is preserved for forensics regardless of outcome.

The adapter registry is an in-process dict keyed by `simulator_id` populated via the `@register` decorator at import time. There is no on-disk registry — discovery happens by importing the `factory.adapter` package, which transitively imports each `factory/adapter/<simulator_id>.py` module. The catalog entry (spec 004) is the source of truth for *which* `simulator_id`s should exist.

## 5. Algorithms / Logic

### 5.1 Adapter discovery and registration

At `factory.adapter` package import time, every `factory/adapter/<simulator_id>.py` module is imported. Each adapter module calls `@register` on its `Adapter` subclass, which inserts `(simulator_id, adapter_cls)` into the registry. `load(simulator_id)` returns either a fresh `adapter_cls()` instance or — when `mock_mode=True` — the paired `MockAdapter` subclass from the same module file.

Three startup-time checks raise `AdapterContractViolation` and refuse the boot:
1. **Adapter ↔ catalog parity.** Every registered adapter's `simulator_id` is present in the current `SimulatorCatalog`, and vice versa.
2. **`output_schema()` validity.** Calling `adapter.output_schema()` returns a valid `AdapterOutputSchema` whose `simulator_id` matches the adapter's own; every fixture under `factory/adapter/fixtures/<simulator_id>/` parses into a `RunArtifacts` that satisfies the declared schema.
3. **Canonical-tensor filename collision-free.** The `canonical_tensor_filename` declared by `output_schema()` matches the placeholder spec 008's local-gate parser expects (e.g. `canonical.npz`) — drift between the two is caught here, not at first-iteration runtime.

### 5.2 `adapter.run(...)` contract

The skeleton-level contract:
1. Validate `experiment_spec.simulator_id == self.simulator_id`; raise `AdapterContractViolation` if not.
2. Translate `experiment_spec.control_definition` and the chosen fidelity tier into the simulator's native input format. Validation here raises `SimulatorConfigInvalid` *before* any container is launched — failing fast is part of the contract.
3. Create the per-seed output directory `sandbox_dir / "adapter_outputs" / str(seed)` for the seed taken from `experiment_spec`. The adapter writes *only* under this root (spec 008's sandbox shim refuses writes elsewhere).
4. Invoke the simulator inside that per-seed directory (subprocess, container, or in-process call — adapter's choice).
5. Parse simulator outputs into a `RunArtifacts` payload whose populated keys are a superset of what `self.output_schema()` declares as `required=True`; persist a JSON copy at `sandbox_dir / "adapter_outputs" / str(seed) / "run_artifacts.json"` alongside the raw outputs.
6. Return the payload. The Generator-Verifier loop (spec 008) promotes it; spec 009 then reads `run_artifacts.json` for G4 validation.

Crashes, OOMs, and timeouts surface as `AdapterRuntimeFailure`; output-parsing problems and schema mismatches (declared field absent, dtype mismatch) surface as `AdapterContractViolation` (adapter bug, not simulator bug).

### 5.3 Mock mode

`MockAdapter.run(...)` reads fixture `RunArtifacts` from `factory/adapter/fixtures/<simulator_id>/<fixture_name>.json`, writes it to `sandbox_dir / "adapter_outputs" / str(seed) / "run_artifacts.json"` (canonical path per FIX_PLAN §7), and returns it. The fixture set must include at least one passing run, one invariant-violating run, and one runtime-failure case so spec 009's validation tests have realistic adversarial inputs without containers. Every fixture is validated against the adapter's `output_schema()` at module import time (startup check §5.1, item 2).

## 6. Failure Modes

| Error class | When it fires | Recovery action |
| :--- | :--- | :--- |
| `AdapterNotRegistered(AdapterError)` | `load(simulator_id)` called with id not in registry | Halt before Generator-Verifier turn; surface to operator; either add an adapter or have `SimulatorSelector` (spec 005) pick a different simulator. |
| `AdapterContractViolation(AdapterError)` | Adapter returned a `RunArtifacts` payload that does not satisfy the protocol, *or* startup adapter↔catalog mismatch detected | Mark the experiment as code-bug not science-bug; do not retry blindly — the adapter module itself must be fixed. State machine pauses, operator notified. |
| `AdapterRuntimeFailure(AdapterError)` | Simulator crashed, OOM'd, timed out, or produced unparseable output | Forward traceback to Generator-Verifier debugger (spec 008) for at most one corrective re-run; on second failure mark the `ExperimentSpec` `intractable` per SPEC.md §G2.5. |
| `SimulatorConfigInvalid(AdapterError)` | `ExperimentSpec.control_definition` or fidelity-ladder entry fails the simulator's input-DSL validation before launch | Bubble back to spec 008 / spec 005; if the selector cannot produce a config-valid spec, the hypothesis routes to `parked_for_lack_of_tooling` per G1.5. |

All four inherit from `AdapterError(FactoryError)` so the gate state machine (spec 003) can catch the family at one boundary.

## 7. Testing

**Mock-mode unit tests (`factory/adapter/tests/`):**
- `test_adapter_typical_usage.py` — REQUIRED. Mock-mode load of a sample adapter; `run(...)` on a fixture `ExperimentSpec`; assert `RunArtifacts` shape, observables present, residuals present.
- `test_registry.py` — `register` populates the table; duplicate `simulator_id` raises; `load(unknown)` raises `AdapterNotRegistered`.
- `test_contract_enforcement.py` — feed an adapter that returns malformed `RunArtifacts`; verify `AdapterContractViolation`.
- `test_catalog_adapter_match.py` — startup-time check fires when an adapter is registered for a `simulator_id` absent from the catalog fixture, and vice versa.
- `test_mock_fixtures.py` — every fixture under `factory/adapter/fixtures/` parses into a `RunArtifacts` payload that satisfies the protocol.

**Live-mode tests** (`@pytest.mark.live`, gated): one smoke test per adapter that boots its catalog-entry container and runs the catalog's smoke-test problem end-to-end; asserts the returned `RunArtifacts` matches the catalog's known-good output. Lives alongside the adapter module.

## 8. Performance & Budget

The adapter is a thin translation + I/O layer; its own overhead is bounded at <100 ms per call (config translation + result parsing). Wall-clock and dollar cost are dominated by the underlying simulator and are reported back inside `RunArtifacts.wall_clock_seconds` and `RunArtifacts.cost_usd` for spec 013 to ledger. Mock-mode is essentially free (<10 ms, fixture read).

## 9. Open Questions

- **In-process vs. container-subprocess execution.** Some simulators have Python bindings (cheap, in-process); others ship only a CLI binary and demand subprocess. Whether `Adapter.run` standardizes on one or branches per adapter is open.
- **`RunArtifacts` ownership.** This spec defines the protocol and names the spec-009-consumed fields inline in §3; spec 009 will promote it to a concrete Pydantic class. Whether that concrete class lives here, in spec 009, or in spec 002 (artifacts) is unresolved — leaning toward spec 009 since it owns the canonical-name list, with this spec exporting only the `Protocol` and `AdapterOutputSchema`.
- **Hot-reloading adapters.** Phase A imports adapters once at startup. Whether a long-running factory needs to hot-add a newly-onboarded adapter without a restart is deferred to Phase B.
- **Cross-simulator equivalence helpers.** SPEC.md §G4 cross-simulator check needs a shared observable schema; whether that helper belongs here or in spec 009 is open.

## 10. TODO Checklist

- [ ] Scaffold `factory/adapter/` from the canonical module template (`__init__.py`, `api.py`, `abstract.py`, `types.py`, `errors.py`, `cli.py`, `mock.py`, `fixtures/`, `tests/`).
- [ ] Implement the six ABC subclasses in `factory/adapter/abstract.py`: `Discretizer`, `ConstraintAggregator`, `UpdateStepOperator`, `AcceptanceController`, `RestartController`, `LocalPolisher`. Each is an `abc.ABC` with abstract methods left as `...` until a concrete adapter binds them. Also implement the `BlueprintComponents` frozen dataclass that bundles the six concrete subclasses returned by `Adapter.components()`. (Names locked per FIX_PLAN §26.1; distinct from spec 017's `FidelityLadderScheduler`, which sits one layer up.)
- [ ] Implement `AdapterOutputSchema` + `AdapterOutputField` Pydantic models in `factory/adapter/types.py` (skeleton: fields list, dtype tags, units, required flag — final dtype taxonomy locked alongside spec 009 §5 check applicability table).
- [ ] Add the abstract `Adapter.output_schema() -> AdapterOutputSchema` method body skeleton in `factory/adapter/abstract.py` and stub the per-adapter concrete implementations for the two PRD-001 reference adapters.
- [ ] Define `SANDBOX_ADAPTER_OUTPUTS_RELPATH = "adapter_outputs"` constant in `factory/adapter/types.py` and import the per-iteration root constant from `factory.genver` (spec 008) — the joined path `runs/<cycle-id>/sandbox/<iteration:03d>/adapter_outputs/<seed>/` is computed by composing the two; this spec owns only the `adapter_outputs/<seed>/` tail to keep spec 008 as SSOT for `<iteration:03d>/`.
- [ ] Author the `RunArtifacts` protocol and decide its concrete home (here vs. spec 009 vs. spec 002). Document the spec-009-consumed field names in §3 inline once decided.
- [ ] Implement the `@register` decorator + in-process registry + `load(simulator_id, mock_mode=...)`.
- [ ] Implement the three startup-time consistency checks listed in §5.1 (adapter↔catalog parity, `output_schema()` validity, canonical-tensor filename alignment with spec 008).
- [ ] Write `factory/adapter/cli.py` with `list`, `inspect` (renders `output_schema()` as a table), and `run --mock-mode` subcommands.
- [ ] Author the first two reference adapters paired to the two cross-validatable catalog entries from PRD-001 (names left to spec 004).
- [ ] Ship a `MockAdapter` for each reference adapter with ≥3 fixtures (passing, invariant-violation, runtime-failure); fixtures must conform to the adapter's `output_schema()`.
- [ ] Write `docs/runbooks/adapter-writing.md` walking a new contributor from catalog entry → adapter skeleton → `output_schema()` declaration → mock fixtures → live smoke test. (FIX_PLAN §21 canonical filename.)
- [ ] Write the five tests listed in §7; all green in CI mock-mode. Add a sixth test `test_output_schema_satisfied.py` that loads each fixture and asserts every `required=True` field from the declared `AdapterOutputSchema` is populated.
- [ ] Verify `mypy --strict factory/adapter/` passes.
- [ ] Verify `python -m factory.adapter run --simulator-id <id> --experiment-fixture sample --mock-mode` works on a fresh checkout (architectural invariant §1.1).
