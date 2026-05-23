# Spec 017: Multi-Fidelity Ladder Scheduler

> Status: ☐ not started · Owner: TBD · Last updated: 2026-05-23

## CONTEXT (60-second summary — read first)
- The **Multi-Fidelity Ladder Scheduler** is the runtime ladder traversal engine for the factory. Given an `ExperimentSpec.fidelity_ladder` (a tuple of `FidelityTier` artifacts already defined in spec 002 §3), it decides **which run is next**, dispatches it through the right substrate (DRY_RUN → adapter toy grid, SURROGATE → spec 010 `surrogate.predict`, MID_FIDELITY/ORACLE → spec 006 `adapter.run` on the production grid, CROSS_SIMULATOR → adapter for a second simulator from the catalog equivalence map), promotes on threshold pass, kills on `kill_threshold` violation, and emits per-tier telemetry. **Distinct from spec 006's `Discretizer` ABC**, which decides grid/mesh choices *within one run* — the two are orthogonal: `Discretizer` is *within-run*, the scheduler in this spec is *across-runs*.
- The 5 facts: (1) reads `ExperimentSpec.fidelity_ladder` and walks tiers in declared order; (2) sequentially runs each tier, promoting on success or killing on `kill_threshold` violation, never re-ordering; (3) **Phase A ladder is `[DRY_RUN, SURROGATE, ORACLE]` (3 tiers)**; Phase B adds `MID_FIDELITY` and `CROSS_SIMULATOR` tiers per FIX_PLAN §26.3; (4) integrates with the G3 surrogate gate (spec 010): the SURROGATE tier delegates to `surrogate.predict(...)` and honours `SurrogateProbeResult.pass_vs_baseline` (`pass` → promote, `fail` → kill, `escalate` → promote with `escalated=True` rationale, deferring the judgment to ORACLE); (5) telemetry events per transition under the `factory.fidelity.*` namespace — `tier_started`, `tier_promoted`, `tier_killed`, `ladder_complete`.
- Open first: `factory/fidelity/api.py` and `factory/fidelity/tests/test_fidelity_scheduler_typical_usage.py`.

## ENTRY POINTS
- Main module: `factory/fidelity/api.py`
- Typical-usage test: `factory/fidelity/tests/test_fidelity_scheduler_typical_usage.py`
- CLI: `python -m factory.fidelity --help` (subcommands: `run-ladder`, `inspect`, `kill-criteria`)
- Mock-mode example: `python -m factory.fidelity run-ladder --experiment-fixture sample_experiment_spec --mock-mode`
- Runbook: `docs/runbooks/fidelity-ladder.md`  *(\[TBD-impl\] — author alongside the implementation TODO checklist.)*

## LOCAL DEBUG
- Instantiate without simulators or trained surrogates:

  ```python
  from factory.fidelity import FidelityLadderScheduler
  from factory.artifacts import ExperimentSpec, FidelityTier
  from factory.surrogate import SurrogateRegistry
  from factory.fidelity.fixtures import mock_adapter_run

  experiment = ExperimentSpec.from_fixture("sample_experiment_spec")
  scheduler = FidelityLadderScheduler(
      experiment=experiment,
      surrogate=SurrogateRegistry.mock_registry(),
      adapter_run_fn=mock_adapter_run,
  )
  while not scheduler.is_complete():
      result = scheduler.run_next_tier(experiment.hypothesis_id)
      print(result)
  ```

- Fixture artifacts: `factory/fidelity/fixtures/sample_ladder.json` (3-tier Phase A ladder),
  `factory/fidelity/fixtures/mock_adapter_outputs/*.json` (fixture `RunArtifacts` blobs).
- Common error signatures → recovery action:
  - `TierBudgetExhausted` → spec 013 `BudgetTracker` denied the reservation for this tier; operator must raise the cap or kill the hypothesis (state machine pauses).
  - `TierKillThresholdHit` → the tier's `metric_value` violated `FidelityTier.kill_threshold`; the scheduler correctly stopped the ladder. State machine emits `EvidenceLedgerEntry(result="falsified")`.
  - `SurrogatePredictionUnavailable` → the SURROGATE tier was reached but `surrogate.predict(...)` raised `NoTrainedSurrogate` (spec 010); the scheduler does **not** silently skip — it raises and the state machine routes to G3 with an "untrained surrogate" rationale, which today escalates to ORACLE.
  - `LadderEmpty` → constructed with `experiment.fidelity_ladder == ()`; configuration error in spec 003 C2.
  - `TierOutOfOrder` → ladder declared in a nonsensical order (e.g., `ORACLE` before `SURROGATE`, or two terminal tiers); validated at construction. Fix the `ExperimentSpec` upstream.
- Logs to inspect: every transition writes a structured event to `runs/<cycle-id>/cycle.jsonl` under `module=fidelity` with `{tier_kind, tier_name, hypothesis_id, metric_value, kill_threshold, promoted, kill_reason, cost_usd, wall_clock_seconds}`.

## DEPENDENCIES
- **Hard:**
  - Spec 002 (artifacts) — reads `FidelityTier`, `ExperimentSpec`, `HypothesisId`; never redeclares.
  - Spec 010 (surrogate) — `SurrogateRegistry.predict(...)` powers the SURROGATE tier; the scheduler treats `SurrogateProbeResult.pass_vs_baseline` as the promote/kill/escalate signal.
  - Spec 006 (domain adapter) — `Adapter.run(experiment_spec, sandbox_dir) -> RunArtifacts` powers the DRY_RUN, MID_FIDELITY, ORACLE, and CROSS_SIMULATOR tiers (toy grid vs production grid is a per-tier knob, not a per-spec one).
- **Soft:**
  - Spec 013 (budget tracker) — per-tier cost is recorded via `tracker.record(module="fidelity", ...)` when a budget context is provided; graceful no-op otherwise.
  - Spec 014 (telemetry) — `factory.fidelity.*` events emitted when a `TelemetryEmitter` is provided; graceful no-op otherwise.
- **Mocks available:** `MockSurrogate` (deterministic `predict` returning a configurable `SurrogateProbeResult`), `mock_adapter_run(...)` (returns fixture `RunArtifacts` from `factory/fidelity/fixtures/mock_adapter_outputs/`), `FidelityTier.from_fixture("dry_run" | "surrogate" | "oracle")` (already provided by spec 002 fixture loader).

---

## 1. Summary

This module owns **runtime ladder traversal** for the factory's multi-fidelity evaluation strategy per FIX_PLAN §26.3. Given an `ExperimentSpec.fidelity_ladder` declared at C2 by the state machine (spec 003), the `FidelityLadderScheduler` walks the tiers in order, dispatches each tier to the correct substrate (surrogate registry for SURROGATE, domain adapter for DRY_RUN/MID_FIDELITY/ORACLE/CROSS_SIMULATOR), evaluates the tier's `kill_threshold` to decide promote-or-kill, and emits structured telemetry per transition.

**This is not the `Discretizer` ABC.** The `Discretizer` ABC defined in spec 006 §3 owns *within-one-run* discretization choices — what grid, what mesh, what spectral basis the solver runs on. The `FidelityLadderScheduler` in this spec owns *which run is next on the ladder*. The two abstractions never conflict: a single `ORACLE` tier traversal in the scheduler might invoke an adapter whose `Discretizer.configure(spec, tier_name="oracle")` selects a production grid; a `DRY_RUN` tier traversal calls the same adapter with `tier_name="dry_run"` and gets a toy grid. The scheduler is orthogonal to the adapter's internal discretization machinery and never inspects it.

The module is shipped as a standalone library — pure Python, no per-simulator coupling — so it can be unit-tested with `MockSurrogate` and `mock_adapter_run` and integration-tested against the live surrogate registry and live adapters once both are wired.

## 2. Scope

**In scope:**
- Walking a non-empty `experiment.fidelity_ladder` in declared order, one tier at a time, with per-tier promote/kill/escalate decisions.
- Promotion criteria: read `FidelityTier.kill_threshold` and the tier-specific metric source (`SurrogateProbeResult.pass_vs_baseline` for SURROGATE; `RunArtifacts.observables[success_metric]` for adapter-backed tiers).
- Dispatching each tier kind to its correct substrate:
  - `DRY_RUN` → `adapter_run_fn(experiment_spec, sandbox_dir, tier_name=tier.name)` with the adapter configured for a toy grid.
  - `SURROGATE` → `surrogate.predict(observable=experiment.success_metric, candidate=experiment_spec, baseline_value=...)`.
  - `MID_FIDELITY` → `adapter_run_fn(...)` against the production grid for a cheap-but-true simulator setting.
  - `ORACLE` → `adapter_run_fn(...)` against the production grid for the full simulator.
  - `CROSS_SIMULATOR` → `adapter_run_fn(...)` against the **second** simulator from the catalog equivalence map (see Open Questions for the spec 009 G4 sub-check overlap).
- Per-tier telemetry under the `factory.fidelity.*` namespace: `tier_started`, `tier_promoted`, `tier_killed`, `ladder_complete`.
- Per-tier budget integration: `BudgetTracker.record(module="fidelity", cost_usd=..., wall_clock_seconds=..., description=...)` when a `BudgetTracker` is supplied.
- A typed `TierResult` dataclass capturing what happened on each tier transition (metric value, cost, wall clock, promoted flag, kill reason if any).
- Construction-time validation: `LadderEmpty`, `TierOutOfOrder`.
- A per-module CLI (`python -m factory.fidelity ...`) with `run-ladder`, `inspect`, `kill-criteria` subcommands.
- Mock mode.

**Out of scope:**
- **The `FidelityTier` artifact itself.** It lives on `factory.artifacts` (spec 002 §3). This spec is a consumer, never a definer.
- **The surrogate model itself.** Training, OOD detection, and inference all live in spec 010. The scheduler is a pure consumer of `SurrogateRegistry.predict(...)`.
- **The validation portfolio (G4 checks).** Cross-simulator validation as a *check* lives in spec 009. The `CROSS_SIMULATOR` tier here is a *runtime substrate choice*, not a check; the overlap is documented in §9.
- **Within-run grid/mesh choices.** Spec 006's `Discretizer` ABC owns these.
- **Re-ordering or skipping tiers based on dynamic intelligence.** The scheduler walks the ladder declared by C2; it never reorders. If a smarter ladder is desired, regenerate the `ExperimentSpec` upstream.
- **Per-tier seed selection.** Seeds are declared on `ExperimentSpec.seed_set`; the scheduler forwards them to the substrate but does not pick them.

## 3. Public Interface

```python
# factory/fidelity/api.py

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from factory.artifacts import (
    ArtifactHash,
    ExperimentSpec,
    FactoryError,
    FidelityTier,
    HypothesisId,
)
from factory.adapter import RunArtifacts            # spec 006 §3
from factory.surrogate import SurrogateRegistry     # spec 010 §3


# --- Error taxonomy (every class inherits FactoryError per spec 002 §3) ---

class FidelityError(FactoryError): ...
class LadderEmpty(FidelityError): ...
class TierOutOfOrder(FidelityError): ...
class TierBudgetExhausted(FidelityError): ...
class TierKillThresholdHit(FidelityError): ...
class SurrogatePredictionUnavailable(FidelityError): ...
class AdapterRunFailed(FidelityError): ...
class MetricMissing(FidelityError): ...


# --- Tier-kind enum mirroring FidelityTier.kind (FIX_PLAN §26.3) ---

class FidelityKind(str, Enum):
    """Module-local enum mirroring the `Literal` in `FidelityTier.kind`.

    Useful for `match`/`switch` dispatch inside the scheduler. The truth is
    on `FidelityTier.kind` (spec 002 §3 — a Literal); this enum mirrors it
    so dispatch code can use names instead of string literals.
    """
    DRY_RUN = "dry_run"
    SURROGATE = "surrogate"
    MID_FIDELITY = "mid_fidelity"
    ORACLE = "oracle"
    CROSS_SIMULATOR = "cross_simulator"


# --- Result of one tier transition ---

@dataclass(frozen=True)
class TierResult:
    """The outcome of one call to `run_next_tier(...)`.

    Frozen, fully typed. Persisted to `runs/<cycle-id>/fidelity/<hypothesis_id>/<tier_index:02d>.json`
    alongside the corresponding telemetry events.
    """
    tier: FidelityTier
    metric_value: float
    cost_usd: float
    wall_clock_seconds: float
    promoted: bool                    # True → next tier will run; False → ladder is killed.
    kill_reason: str | None           # populated iff promoted=False.
    escalated: bool                   # True iff SURROGATE returned pass_vs_baseline="escalate".
    underlying_artifact_hash: ArtifactHash | None
    # ↑ When the substrate is the surrogate, this is the SurrogateProbeResult hash.
    #   When the substrate is the adapter, this is the RunArtifacts.parent_experiment_hash.


# --- The scheduler ---

MAX_LADDER_TIERS: Final[int] = 8   # Phase A: 3, Phase B: 5; defensive cap on pathological specs.


class FidelityLadderScheduler:
    """Walk the `experiment.fidelity_ladder` in declared order.

    One scheduler instance per hypothesis. Stateful (tracks `_cursor`); not thread-safe.
    The state machine in spec 003 owns the lifecycle: instantiate at C2 completion,
    drive via `run_next_tier(...)` until `is_complete()`, then dispose.
    """

    def __init__(
        self,
        experiment: ExperimentSpec,
        surrogate: SurrogateRegistry | None,
        adapter_run_fn: Callable[..., RunArtifacts],
        budget: "BudgetTracker | None" = None,          # spec 013; optional
        telemetry: "TelemetryEmitter | None" = None,    # spec 014; optional
        sandbox_root: Path | None = None,
    ) -> None:
        """
        experiment: the parent `ExperimentSpec`; its `fidelity_ladder` is walked here.
            Construction raises `LadderEmpty` if the ladder is `()`.
            Construction raises `TierOutOfOrder` if the tier sequence violates §5.1.
        surrogate: required iff any tier in the ladder has `kind == "surrogate"`;
            may be `None` if the ladder is purely adapter-backed (e.g. DRY_RUN + ORACLE).
        adapter_run_fn: callable with the same signature as `Adapter.run(...)` per
            spec 006 §3. Tests inject `mock_adapter_run`; production passes
            `factory.adapter.load(experiment.simulator_id).run`.
        budget: optional `BudgetTracker`; if supplied, per-tier reservations and
            commits go through it. If `None`, costs are still computed and stored
            on `TierResult.cost_usd` but never reported upward.
        telemetry: optional `TelemetryEmitter`; if supplied, `factory.fidelity.*`
            events are emitted per transition. If `None`, telemetry is a no-op.
        sandbox_root: optional per-cycle sandbox root. Defaults to
            `runs/<cycle-id>/sandbox/` resolved via the active cycle context.
        """

    def run_next_tier(self, hypothesis_id: HypothesisId) -> TierResult:
        """Run the next tier in the ladder; return its `TierResult`.

        Pre: `not is_complete()`. Calling after completion raises `LadderEmpty`.
        Post:
          - If `result.promoted` and the cursor is not at the terminal tier,
            the next call to `run_next_tier(...)` will run the next tier.
          - If not `result.promoted`, subsequent calls to `is_complete()`
            return True. The ladder is dead; the state machine reads
            `kill_reason()` to decide the routing verdict.

        Raises:
          - `TierBudgetExhausted` — spec 013 denied the reservation.
          - `TierKillThresholdHit` — equivalent to `not promoted` for the
            specific case where the metric violated `kill_threshold`; kept as
            an exception class for ergonomics in callers that prefer
            try/except over flag-checking, but the canonical signal is the
            `TierResult.promoted=False` flag.
          - `SurrogatePredictionUnavailable` — the SURROGATE tier was reached
            and `surrogate.predict(...)` raised. The ladder is not silently
            skipped past this tier; the state machine handles the recovery
            decision (typically: route to G4 with rationale, equivalent to
            an `escalate`).
          - `AdapterRunFailed` — `adapter_run_fn(...)` raised. The scheduler
            does NOT swallow this; it re-raises so the state machine can
            distinguish "adapter died" from "metric violated kill_threshold".
          - `MetricMissing` — adapter returned `RunArtifacts` whose
            `observables` map has no entry for `experiment.success_metric`.
            Treated as adapter bug, not as a kill.
        """

    def is_complete(self) -> bool:
        """True iff the ladder has finished (last tier promoted) or was killed."""

    def kill_reason(self) -> str | None:
        """If the ladder was killed, returns the human-readable reason from the
        terminal `TierResult`. Returns `None` if the ladder completed normally
        or has not been driven yet."""

    def remaining_tiers(self) -> tuple[FidelityTier, ...]:
        """Tiers not yet attempted. Empty after `is_complete()` becomes True."""

    def history(self) -> tuple[TierResult, ...]:
        """All `TierResult`s produced so far, in order. Frozen tuple."""


# --- Fixtures and mocks for testing ---

class MockSurrogate:
    """Deterministic surrogate-registry stand-in for tests. Mirrors
    `SurrogateRegistry.predict(...)` and returns a configurable
    `SurrogateProbeResult` whose `pass_vs_baseline` is supplied at
    construction time."""


def mock_adapter_run(
    experiment_spec: ExperimentSpec,
    sandbox_dir: Path,
    *,
    tier_name: str = "dry_run",
) -> RunArtifacts:
    """Mock adapter for `adapter_run_fn`. Returns fixture `RunArtifacts` from
    `factory/fidelity/fixtures/mock_adapter_outputs/<tier_name>.json`."""
```

### 3.1 `FidelityTier`, `ExperimentSpec`, `SurrogateProbeResult`, `RunArtifacts`

All four are defined elsewhere:

| Type | Owner |
| :--- | :--- |
| `FidelityTier` | spec 002 §3 — frozen Pydantic model with `name`, `kind`, `cost_estimate_usd`, `expected_runtime_seconds`, `kill_threshold: float \| None` |
| `ExperimentSpec.fidelity_ladder: tuple[FidelityTier, ...]` | spec 002 §3 (Artifact 4) |
| `SurrogateProbeResult` | spec 002 §4 / spec 010 §3.1 — the surrogate registry is the sole producer |
| `RunArtifacts` | spec 006 §3 — Protocol-typed; observables/residuals/diagnostics maps + provenance |

This module is a **pure consumer** of all four and never re-declares them.

## 4. Data Structures / Schemas

Module-local types live in `factory/fidelity/types.py`:

```text
FidelityKind        — Enum mirroring FidelityTier.kind for ergonomic dispatch
TierResult          — frozen dataclass; one entry per ladder transition
LadderHistory       — tuple[TierResult, ...] returned by FidelityLadderScheduler.history()
```

**Persistence layout** (per FIX_PLAN §26.3, mirroring spec 010 / 006 conventions):

```
runs/<cycle-id>/fidelity/<hypothesis_id>/
├── ladder_manifest.json      # the experiment.fidelity_ladder, serialized once at scheduler init
├── 00_dry_run.json           # TierResult, tier index 00
├── 01_surrogate.json         # TierResult, tier index 01
├── 02_oracle.json            # TierResult, tier index 02
└── ladder_summary.json       # final state: completed | killed, kill_reason, total cost_usd
```

Filenames use `<index:02d>_<tier.name>.json` so directory listings sort chronologically.

The `ladder_summary.json` is written once at `is_complete()` boundary by the state machine driver; it is not written by the scheduler itself (which is library code, not a CLI). The driver reads `history()` and emits.

## 5. Algorithms / Logic

### 5.1 Construction-time ladder validation

At `__init__`, validate the ladder in this exact order:

1. If `experiment.fidelity_ladder == ()` → `LadderEmpty`.
2. If `len(experiment.fidelity_ladder) > MAX_LADDER_TIERS` → `TierOutOfOrder` with reason "ladder length exceeds defensive cap".
3. Enforce the canonical kind ordering. The kinds form a partial order on cost: `dry_run < surrogate < mid_fidelity < oracle`, with `cross_simulator` permitted only **after** `oracle` (it is by construction at least as expensive as `oracle`). The ladder is valid iff it is a non-strictly-increasing sequence under this order:

   ```text
   kind_rank: dry_run=0, surrogate=1, mid_fidelity=2, oracle=3, cross_simulator=4
   for i in range(1, len(ladder)):
       if kind_rank[ladder[i].kind] < kind_rank[ladder[i-1].kind]:
           raise TierOutOfOrder
   ```

   Equal ranks are permitted (e.g., two `oracle` tiers with different seed_set partitions) but **discouraged**; emit a `factory.fidelity.ladder_warning` event when they appear.

4. If any tier has `kind == "surrogate"` and `surrogate is None` → `TierOutOfOrder` with reason "ladder contains surrogate tier but no SurrogateRegistry was supplied".

### 5.2 Promotion / kill criteria

For each tier transition, the scheduler computes a single `metric_value: float` (the observable defined by `experiment.success_metric`) and compares it to `tier.kill_threshold`:

```text
def evaluate_promotion(tier: FidelityTier, metric_value: float, success_metric_kind: Literal["lower_is_better", "higher_is_better"]) -> tuple[bool, str | None]:
    if tier.kill_threshold is None:
        return (True, None)                       # unconditional promote
    if success_metric_kind == "lower_is_better":
        if metric_value > tier.kill_threshold:
            return (False, f"metric {metric_value} exceeded kill_threshold {tier.kill_threshold}")
    else:                                          # higher_is_better
        if metric_value < tier.kill_threshold:
            return (False, f"metric {metric_value} fell below kill_threshold {tier.kill_threshold}")
    return (True, None)
```

`success_metric_kind` is resolved from the `MetricCatalog` (spec 002 / spec 003 §6 metric registry) at scheduler construction; the scheduler does not infer directionality.

The SURROGATE tier is special: it does not produce a raw metric — it produces a `SurrogateProbeResult` with `pass_vs_baseline ∈ {"pass", "fail", "escalate"}`. The mapping is:

| `pass_vs_baseline` | Scheduler decision |
| :--- | :--- |
| `"pass"` | `promoted=True`, `escalated=False`, `kill_reason=None` |
| `"fail"` | `promoted=False`, `escalated=False`, `kill_reason="surrogate predicted miss vs baseline"` |
| `"escalate"` | `promoted=True`, `escalated=True`, `kill_reason=None` — defer the judgment to the next tier (typically ORACLE) per spec 010 §3.1 |

Note: in the `"escalate"` path the `TierResult.metric_value` is set to `predicted_value` from the `SurrogateProbeResult`; the scheduler does NOT re-evaluate the surrogate's prediction against `tier.kill_threshold` because the surrogate has self-flagged the prediction as untrustworthy.

### 5.3 Dispatch by tier kind

```text
def dispatch(tier: FidelityTier) -> tuple[float, ArtifactHash | None, float, float, bool]:
    """Returns (metric_value, underlying_artifact_hash, cost_usd, wall_clock_seconds, escalated)."""
    match FidelityKind(tier.kind):
        case FidelityKind.DRY_RUN:
            return _run_adapter_tier(tier, tier_name=tier.name)         # toy grid
        case FidelityKind.SURROGATE:
            return _run_surrogate_tier(tier)
        case FidelityKind.MID_FIDELITY:
            return _run_adapter_tier(tier, tier_name=tier.name)         # production grid, cheap solver settings
        case FidelityKind.ORACLE:
            return _run_adapter_tier(tier, tier_name=tier.name)         # production grid, full solver
        case FidelityKind.CROSS_SIMULATOR:
            return _run_adapter_tier(
                tier,
                tier_name=tier.name,
                simulator_override=_pick_second_simulator(experiment),
            )
```

`_run_adapter_tier(...)`:

1. Construct `sandbox_dir = sandbox_root / f"{cursor:03d}"` (per spec 006 §3 path convention).
2. Reserve cost via `budget.check_and_deduct(hypothesis_id, module="fidelity", estimated_cost_usd=tier.cost_estimate_usd, estimated_wall_clock_seconds=tier.expected_runtime_seconds, description=tier.name)` if `budget` is supplied. If `budget.check_and_deduct(...)` raises `BudgetExhausted`, re-raise as `TierBudgetExhausted` with the original cause chained.
3. Call `adapter_run_fn(experiment, sandbox_dir, tier_name=tier.name)`; if it raises any subclass of `FactoryError`, wrap as `AdapterRunFailed(cause=...)`.
4. Read `metric_value = run_artifacts.observables[experiment.success_metric]`; if missing → `MetricMissing` (adapter contract bug per spec 006 §6).
5. Commit the actual cost via `reservation.commit(actual_cost_usd=run_artifacts.cost_usd, actual_wall_clock_seconds=run_artifacts.wall_clock_seconds)`.
6. Return `(metric_value, run_artifacts.parent_experiment_hash, run_artifacts.cost_usd, run_artifacts.wall_clock_seconds, False)`.

`_run_surrogate_tier(tier)`:

1. Look up `baseline_value` from `experiment.control_definition.baseline_config` (per spec 002 §3 `ControlDefinition`).
2. Reserve negligible cost via `budget.check_and_deduct(..., estimated_cost_usd=0.0)`; surrogate predict is essentially free.
3. Call `result = surrogate.predict(observable=experiment.success_metric, candidate=experiment, baseline_value=baseline_value)`; if it raises `NoTrainedSurrogate` → `SurrogatePredictionUnavailable`.
4. Set `escalated = (result.pass_vs_baseline == "escalate")`.
5. Commit zero actual cost; `surrogate.predict(...)` does not charge budget.
6. Return `(result.predicted_value, result.provenance_hash, 0.0, ~0.0, escalated)`.

`_pick_second_simulator(experiment)`:

- Reads the `SimulatorCatalog.equivalence_map(experiment.simulator_id)` (spec 004) and returns the first entry that is *not* `experiment.simulator_id`. If no equivalence is registered, raise `TierOutOfOrder` with reason "cross_simulator tier requires at least one equivalent simulator in SimulatorCatalog".

### 5.4 Telemetry

Per FIX_PLAN §26.3 + spec 014 conventions, the scheduler emits four event names under the `factory.fidelity` namespace. They are registered in `factory/fidelity/events.py` so spec 014's `EventRegistry` picks them up at startup.

| Event | Fires | Payload |
| :--- | :--- | :--- |
| `factory.fidelity.tier_started` | Immediately before substrate dispatch | `{hypothesis_id, tier_kind, tier_name, kill_threshold, baseline_value, cursor_index}` |
| `factory.fidelity.tier_promoted` | After a successful promote (incl. `escalate`) | `{hypothesis_id, tier_kind, tier_name, metric_value, cost_usd, wall_clock_seconds, escalated}` |
| `factory.fidelity.tier_killed` | After a kill (`promoted=False`) | `{hypothesis_id, tier_kind, tier_name, metric_value, kill_reason, cost_usd, wall_clock_seconds}` |
| `factory.fidelity.ladder_complete` | When `is_complete()` first becomes True | `{hypothesis_id, terminal_state: "completed" \| "killed", total_cost_usd, total_wall_clock_seconds, tier_count}` |

All four are emitted at `EventLevel.info`. The state machine in spec 003 owns the cycle-level aggregation.

### 5.5 Budget integration

Per spec 013 §3, the canonical pattern is `check_and_deduct → run → reservation.commit`. The scheduler is one of the few non-LLM modules that uses this pattern directly (most use `record(...)` post-hoc). The reason: a single ORACLE tier can blow the per-hypothesis cap and we need the pre-flight check.

Per-tier cost-source matrix:

| Tier kind | Cost source | Token cost |
| :--- | :--- | :--- |
| `DRY_RUN` | `RunArtifacts.cost_usd` (adapter-reported) | 0 |
| `SURROGATE` | 0.0 (predict is effectively free; see §8) | 0 |
| `MID_FIDELITY` | `RunArtifacts.cost_usd` | 0 |
| `ORACLE` | `RunArtifacts.cost_usd` | 0 |
| `CROSS_SIMULATOR` | `RunArtifacts.cost_usd` | 0 |

`tier.cost_estimate_usd` is used as the *estimate* for `check_and_deduct(...)`; the actual cost commits via `reservation.commit(actual_cost_usd=run_artifacts.cost_usd, ...)`. The difference is reconciled by the budget tracker (spec 013 §5).

## 6. Failure Modes

| Error class | When it fires | Recovery action |
| :--- | :--- | :--- |
| `LadderEmpty(FidelityError)` | `experiment.fidelity_ladder == ()` at construction OR `run_next_tier(...)` called after `is_complete()` | Configuration error in spec 003 C2; cannot recover within the scheduler. State machine fails the cycle. |
| `TierOutOfOrder(FidelityError)` | Ladder kinds violate the canonical order in §5.1, OR the ladder declares a `surrogate` tier but no registry was provided, OR a `cross_simulator` tier was declared with no equivalent simulator in `SimulatorCatalog` | Construction-time failure; spec 003 C2 must regenerate a valid ladder. |
| `TierBudgetExhausted(FidelityError)` | `budget.check_and_deduct(...)` raised `BudgetExhausted` for the current tier reservation | Re-raise; spec 003 routes to "ladder killed by budget" and pauses the hypothesis. Operator can raise the cap and resume via `factory budget set` (spec 015). |
| `TierKillThresholdHit(FidelityError)` | Reserved class — by default the kill is signalled via `TierResult.promoted=False`; this exception class is provided for callers that prefer try/except over flag-checking. Production code prefers flags. | Spec 003 reads `TierResult.kill_reason` and emits `EvidenceLedgerEntry(result="falsified")`. |
| `SurrogatePredictionUnavailable(FidelityError)` | The SURROGATE tier was reached and `surrogate.predict(...)` raised `NoTrainedSurrogate` (spec 010) | Re-raise. The scheduler does NOT silently skip a tier. Spec 003 typically promotes-via-escalate to the next tier (ORACLE) with rationale `"surrogate untrained — escalated to oracle"`. |
| `AdapterRunFailed(FidelityError)` | `adapter_run_fn(...)` raised any `FactoryError` subclass (most commonly spec 006's `AdapterRuntimeFailure` or `SimulatorConfigInvalid`) | Re-raise with the original cause chained. Spec 003 distinguishes "adapter died" from "metric violated threshold" — these are different routing verdicts. |
| `MetricMissing(FidelityError)` | The adapter returned `RunArtifacts` whose `observables` map has no entry for `experiment.success_metric` | Re-raise; adapter contract bug per spec 006 §6 `AdapterContractViolation`. The scheduler does not invent a value. |

## 7. Testing

**Mock-mode** (in CI; no live simulator, no live OpenRouter):

- `test_fidelity_scheduler_typical_usage.py` — **REQUIRED**. Constructs a 3-tier Phase A ladder `[DRY_RUN, SURROGATE, ORACLE]` from fixtures; drives `scheduler.run_next_tier(...)` until `is_complete()`; verifies all three tiers passed through to ORACLE; verifies `history()` returns three `TierResult`s with `promoted=True` for each; verifies `kill_reason()` is `None`; verifies total cost matches sum of per-tier `cost_usd`.
- `test_construction_validation.py` — empty ladder → `LadderEmpty`; out-of-order kinds → `TierOutOfOrder`; `surrogate` tier with `surrogate=None` → `TierOutOfOrder`; ladder length > `MAX_LADDER_TIERS` → `TierOutOfOrder`.
- `test_promotion_kill.py` — DRY_RUN that violates `kill_threshold` → `TierResult.promoted=False`, `kill_reason` populated; subsequent `is_complete()=True`; subsequent `run_next_tier(...)` raises `LadderEmpty`.
- `test_surrogate_dispatch.py` — `MockSurrogate` configured to return `pass_vs_baseline="pass"` → promote; `"fail"` → kill; `"escalate"` → promote with `escalated=True`.
- `test_surrogate_unavailable.py` — `MockSurrogate.predict(...)` raises `NoTrainedSurrogate` → `SurrogatePredictionUnavailable`.
- `test_adapter_failure_isolation.py` — `mock_adapter_run` raises `AdapterRuntimeFailure` → `AdapterRunFailed` with `__cause__` chained, NOT a kill.
- `test_metric_missing.py` — `mock_adapter_run` returns `RunArtifacts` missing the success metric → `MetricMissing`.
- `test_budget_integration.py` — `check_and_deduct(...)` raises `BudgetExhausted` for the ORACLE tier → `TierBudgetExhausted`; verify the reservation for ORACLE is never committed.
- `test_telemetry_events.py` — capture events via `MockTelemetryEmitter`; verify exact event names (`factory.fidelity.tier_started`, etc.) and payload shapes for a 3-tier pass-through and a 2-tier kill.
- `test_cross_simulator_dispatch.py` — Phase B ladder ending in `CROSS_SIMULATOR`; verify `_pick_second_simulator` reads `SimulatorCatalog.equivalence_map(...)` correctly; verify the adapter is invoked with the *second* simulator's id, not `experiment.simulator_id`.

**Live-mode** (`@pytest.mark.live`, gated):

- `test_live_phase_a_ladder.py` — drives the full Phase A ladder against a live `SurrogateRegistry` (one trained surrogate) and the smallest live adapter from the catalog (`sim_a` toy). Asserts wall-clock end-to-end ≤ 5 minutes and verifies the telemetry log contains all four event names.

**Acceptance grep** (per FIX_PLAN §26.6):

```bash
grep -rn "FidelityLadderScheduler\|FidelityKind\|run_next_tier" docs/specs/017-fidelity-scheduler.md
# Expect: each appears ≥ once. (This spec satisfies the grep.)
```

## 8. Performance & Budget

- **Scheduler overhead.** Each tier transition incurs < 10 ms of scheduler-internal logic (validation, dispatch, telemetry, persistence of `TierResult`). The per-tier *cost* is dominated by the underlying surrogate or adapter call, not by the scheduler.
- **SURROGATE tier cost.** Per spec 010 §8, `surrogate.predict(...)` is sub-second on Phase A surrogates. The scheduler charges `cost_usd=0.0` to the budget tracker for SURROGATE tiers (any non-zero charge is the surrogate registry's own bookkeeping per spec 010, and it does NOT pass through to the budget — predict-time cost is "negligible but tracked when a budget context is provided" per spec 010 §LOCAL_DEBUG).
- **DRY_RUN / MID_FIDELITY / ORACLE / CROSS_SIMULATOR cost.** Dominated by `adapter_run_fn(...)`. Read `RunArtifacts.cost_usd` and `RunArtifacts.wall_clock_seconds`; commit those to the budget tracker. Phase A toy grids are ≤ 1 minute; production ORACLE grids are 10 minutes to 1 hour per spec 004 simulator catalog.
- **Ladder budget envelope.** The state machine should size `Budget.dollar_cap` to be at least the sum of `tier.cost_estimate_usd` across the entire ladder, with a 30% headroom buffer for actual-vs-estimated drift. Recommended default: `dollar_cap = 1.3 × Σ tier.cost_estimate_usd`.
- **Telemetry overhead.** ≤ 1 ms per event (spec 014's `TelemetryEmitter` is append-only JSONL with per-cycle file handles).

## 9. Open Questions

- **Phase B `MID_FIDELITY` semantics.** Phase A ships with 3 tiers. Phase B introduces `MID_FIDELITY`, but the precise meaning of "mid-fidelity" varies by simulator family (a multi-grid solver setting? a coarser PDE discretization? a reduced-physics model with the same simulator binary?). Per FIX_PLAN §26.3 this is a Phase B problem; for now the spec routes `MID_FIDELITY` to the same `adapter_run_fn` as `ORACLE` but with `tier_name="mid_fidelity"`, leaving the adapter (via its `Discretizer.configure(spec, tier_name="mid_fidelity")`) to decide what that means. Need to coordinate with spec 006 §3 on whether `Discretizer` needs a new `tier_name` enum entry or if it stays as a free-form `str`.
- **`CROSS_SIMULATOR` as a tier vs. as a G4 sub-check.** The cross-simulator-validation check in spec 009 §G4 is logically equivalent to running an ORACLE tier on a second simulator and comparing observables. There are two valid factorings:
  - **Option A (this spec):** `CROSS_SIMULATOR` is a fifth fidelity tier. The scheduler dispatches it like ORACLE but with `simulator_override`; the resulting `RunArtifacts` is compared to the prior ORACLE result by the state machine at G4.
  - **Option B (spec 009):** `CROSS_SIMULATOR` is purely a G4 sub-check; the scheduler never has a tier of that kind. The check fires after the scheduler completes the ORACLE tier and independently dispatches a second adapter run.
  
  Both factorings exist in the current docs. Per FIX_PLAN §26.3 the tier-based factoring is the canonical one (the `Literal` in `FidelityTier.kind` includes `"cross_simulator"`); but spec 009 still references the check-based factoring. **Action item:** reconcile with spec 009 owner before Phase B; document the chosen factoring in the next FIX_PLAN amendment.
- **Re-entry after kill.** If a `TierBudgetExhausted` kill is followed by an operator cap-raise (spec 015 `factory budget set --clear-halt`), can the scheduler resume from the next tier, or must the state machine spawn a fresh `FidelityLadderScheduler`? Current design: spawn fresh (the scheduler is stateful per-hypothesis and re-entry is messy). Open: is "lossless resume" worth the complexity? Probably not for Phase A.
- **Equal-rank tiers.** §5.1 permits two `oracle` tiers back-to-back (e.g. one for in-distribution seeds, one for the seed_set tail). This is currently un-tested and emits only a warning. Phase B may need a stricter contract.
- **Surrogate retraining trigger.** When a SURROGATE tier returns `escalate` repeatedly across many hypotheses, the surrogate is over-conservative or under-trained. Should the scheduler emit a `factory.fidelity.surrogate_retrain_needed` event, or is that purely spec 010's concern? Currently routed to spec 010 (the scheduler stays a pure consumer).

## 10. TODO Checklist

- [ ] Scaffold `factory/fidelity/` from the canonical module template (per `ARCHITECTURE.md` §3).
- [ ] Implement `FidelityKind` enum and `TierResult` dataclass in `factory/fidelity/types.py`. Verify both are fully frozen and fully typed (no `Any`, no `Optional` shorthand — use `X | None`).
- [ ] Implement `FidelityLadderScheduler.__init__` with the §5.1 ladder validation in the documented order. Verify `LadderEmpty` and `TierOutOfOrder` fire under each of the four documented conditions.
- [ ] Implement `_run_adapter_tier(tier, tier_name, simulator_override=None)` per §5.3. Wire through to `adapter_run_fn`; persist `TierResult`; emit telemetry events.
- [ ] Implement `_run_surrogate_tier(tier)` per §5.3. Wire through to `surrogate.predict(...)`; persist `TierResult`; emit telemetry events. Map `SurrogateProbeResult.pass_vs_baseline` per the §5.2 table — including the `escalate` → `escalated=True` semantics.
- [ ] Implement `_pick_second_simulator(experiment)` per §5.3 reading `SimulatorCatalog.equivalence_map(...)`. Raise `TierOutOfOrder` when no equivalent simulator is registered.
- [ ] Implement `evaluate_promotion(...)` per §5.2. Resolve `success_metric_kind` from the metric catalog at scheduler construction; do NOT infer at evaluation time.
- [ ] Implement `run_next_tier(hypothesis_id)` per §3 contract. Verify it raises `LadderEmpty` after `is_complete()`; verify the budget reservation/commit pattern (`check_and_deduct → run → commit`); verify per-tier persistence to `runs/<cycle-id>/fidelity/<hypothesis_id>/<index:02d>_<name>.json`.
- [ ] Implement `is_complete()`, `kill_reason()`, `remaining_tiers()`, `history()` accessors. All four are pure reads of internal state; no side effects.
- [ ] Author event registry at `factory/fidelity/events.py` declaring the four `factory.fidelity.*` event names. Verify spec 014 `EventRegistry.build(...)` picks them up at startup.
- [ ] Author CLI at `factory/fidelity/cli.py` with `run-ladder`, `inspect`, `kill-criteria` subcommands. All reachable as `python -m factory.fidelity <subcommand>`.
- [ ] Author fixtures at `factory/fidelity/fixtures/` — `sample_ladder.json` (3-tier Phase A ladder), `mock_adapter_outputs/{dry_run,mid_fidelity,oracle,cross_simulator}.json`.
- [ ] Implement `MockSurrogate` and `mock_adapter_run` in `factory/fidelity/mocks.py`. Verify `mock_adapter_run` returns `RunArtifacts` that satisfy the protocol (spec 006 §3) — including all required fields (`observables`, `residuals`, `diagnostics`, `sandbox_paths`, `seed`, `fidelity_tier`, etc.).
- [ ] Write the 10 tests listed in §7. All must pass in mock mode without external services.
- [ ] Write `test_live_phase_a_ladder.py` (live; manual gate).
- [ ] Write `factory/fidelity/README.md` (≤ 1 page, mock-mode example).
- [ ] Author `docs/runbooks/fidelity-ladder.md` covering: ladder configuration, kill-threshold tuning, telemetry inspection, recovery from `TierBudgetExhausted`, and the SURROGATE → ORACLE escalation pattern.
- [ ] Verify `mypy --strict factory/fidelity/` passes.
- [ ] Verify `python -m factory.fidelity run-ladder --mock-mode` works on a fresh checkout.
- [ ] **Acceptance grep (per FIX_PLAN §26.6):** `grep -rn "FidelityLadderScheduler\|FidelityKind\|run_next_tier" docs/specs/017-fidelity-scheduler.md` returns ≥ 1 hit for each of the three names.
- [ ] Reconcile the §9 open question on `CROSS_SIMULATOR` factoring with spec 009 owner before Phase B.
