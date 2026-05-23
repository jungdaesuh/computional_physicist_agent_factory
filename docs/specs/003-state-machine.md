# Spec 003: Gate State Machine

> Status: ☐ not started · Owner: TBD · Last updated: 2026-05-23

## CONTEXT (60-second summary — read first)
- This is the **orchestrator** — it walks each hypothesis through gates G0 → G6, calling other modules in order, persisting artifacts after each gate, and routing failures to documented recovery paths.
- The 5 facts: (1) gates are pure functions over artifacts (input artifacts → output artifact + outcome); (2) outcome ∈ {pass, fail, qualified, parked, intractable, inconclusive, ood_escalation} — **seven** values; (3) recovery paths are explicit per gate — there is no generic "retry"; (4) the state machine itself owns no LLM calls — it dispatches to spec 001 (Council) and other modules; (5) every gate transition writes an event to `cycle.jsonl`.
- Open first: `factory/state_machine/api.py` and the cycle-trace fixture at `factory/state_machine/fixtures/cycles/sample_cycle.json`.

## ENTRY POINTS
- Main module: `factory/state_machine/api.py`
- Typical-usage test: `factory/state_machine/tests/test_state_machine_typical_usage.py`
- CLI: `python -m factory.state_machine --help` (subcommands: `run-cycle`, `replay`, `inspect`, `step`, `submit-gaps`, `run-gate`, `validate-routes`, `force-terminate`)
- Mock-mode example: `python -m factory.state_machine run-cycle --gap-fixture sample --mock-mode`
- Runbook: `docs/runbooks/state-machine-debugging.md`

## LOCAL DEBUG
- Replay a stored cycle without re-running: `python -m factory.state_machine replay --cycle-id <id>` walks the persisted artifacts and re-emits events without external calls.
- Step a cycle one gate at a time: `python -m factory.state_machine step --cycle-id <id> --pause-after G3`.
- Common error signatures → recovery:
  - `GateTimeoutError(gate=G4)` → check `runs/<cycle-id>/sandbox/` for hung process; kill + restart from prior gate's checkpoint.
  - `GateRouteUndefined(gate=G2, outcome=qualified)` → recovery path missing in `gate_routes.yaml`; configuration bug.
  - `ArtifactNotFound(hash=...)` → an upstream gate didn't persist its output; check that gate's logs.
  - `BudgetExhausted` → routed automatically to `intractable` EvidenceLedger entry; not an error.
- Logs to inspect: `runs/<cycle-id>/cycle.jsonl` filter `module=state_machine`; gate transitions log as `event=gate_enter`/`event=gate_exit` with full I/O hashes.

## DEPENDENCIES
- **Hard:** Spec 002 (artifacts) — reads/writes all artifact types including `ValidationResult`, `SurrogateProbeResult`, `FactoryControlEvent`. Spec 012 (ledger) — persists `EvidenceLedgerEntry` and exposes `evaluate_triggers`. Spec 013 (budget) — checks caps. Spec 001 (council) — invokes for C1–C5 gates. Specs 005, 008, 009, 010 — invokes for non-council gates.
- **Soft:** Spec 014 (telemetry) — emits events if available. Spec 011 (writer) — invoked to produce `RunReport` at G5; mock-mode no-op if unavailable. `specs/016-strategy-archive.md` — C5 program-direction council reads `StrategyArchive` for top-K most-productive strategies and lineage saturation indicators when deciding `DomainScope` mutations (FIX_PLAN §26.4). `specs/017-fidelity-scheduler.md` — invoked at the G3 → G4 transition to walk an `ExperimentSpec.fidelity_ladder` (DRY_RUN → SURROGATE → ORACLE in Phase A) via `FidelityLadderScheduler.run_next_tier(...)` instead of dispatching the validation portfolio (spec 009) directly (FIX_PLAN §26.4).
- **Mocks available:** Every gate has a `mock` implementation. `MockStateMachine` exposes the API but reads outcomes from a YAML script for testing recovery paths.

---

## 1. Summary

The State Machine is the only orchestrator in the factory. It does not own intelligence (delegated to spec 001 Council), execution (spec 008 Gen-Verifier), or validation (spec 009). It owns **sequencing**, **persistence after each gate**, and **routing on failure**.

A cycle is a single hypothesis traversing the gate sequence. The state machine handles one cycle at a time; multi-cycle continuous operation is a thin loop above (`factory.operator`, spec 015).

## 2. Scope

**In scope:**
- Gate definitions G0, G1, G1.5, G2, G2.5, G3, G4, G5, G6.
- Gate sequencing: linear with recovery branches per documented outcomes.
- Per-gate timeout enforcement (gate-specific config).
- Artifact persistence after every gate (output written to `runs/<cycle-id>/artifacts/`).
- Event logging to `cycle.jsonl` on every state transition.
- Cycle replay (read artifacts, re-emit events, no external calls).
- Step mode (pause after a specified gate).
- Recovery routing table (`config/state_machine/gate_routes.yaml`).
- Per-gate config (`config/state_machine/gates/<gate>.yaml`).
- EvidenceLedger emission on terminal outcomes — granular terminal state stored in `EvidenceLedgerEntry.terminal_state`; canonical mapping to `EvidenceResult` per §5.4.
- G0 dedup integration via `EvidenceLedger.evaluate_triggers(hypothesis_id)`.
- Carrying `qualified_track` and `skip_surrogate` metadata flags between gates.

**Out of scope:**
- Continuous multi-cycle scheduling (spec 015).
- LLM calls (spec 001).
- Code generation or execution (spec 008).
- Physics validation logic (spec 009).
- C5 program-direction cadence — that's a separate `C5Scheduler` in this module but runs independently of per-cycle loop.

## 3. Public Interface

```python
# factory/state_machine/api.py

from datetime import timedelta
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal
from factory.artifacts import (
    ArtifactHash,
    Budget,
    CouncilVerdict,
    CycleId,
    DomainScope,
    EvidenceLedgerEntry,
    ExperimentSpec,
    FactoryControlEvent,
    FactoryError,
    GapCandidate,
    HypothesisSpec,
    RunReport,
    SurrogateProbeResult,
    ValidationResult,
)
from factory.ledger import Ledger

class GateError(FactoryError): ...
class GateTimeoutError(GateError): ...
class GateRouteUndefined(GateError): ...
class ArtifactNotFound(GateError): ...
class RouteCycleDetected(GateError): ...
class ImplementingModuleMissing(GateError): ...

class Gate(str, Enum):
    G0_DOMAIN = "G0"
    G1_FALSIFIABILITY = "G1"
    G1_5_SIMULABILITY = "G1.5"
    G2_WORTHINESS = "G2"
    G2_5_TRACTABILITY = "G2.5"
    G3_SURROGATE = "G3"
    G4_VALIDATION = "G4"
    G5_INTERPRETATION_AND_REVIEW = "G5"
    G6_HUMAN_APPROVAL = "G6"
    TERMINATE = "__terminate__"   # sentinel for the run-loop exit edge

class GateOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    QUALIFIED = "qualified"            # passed with dissent / caveats
    PARKED = "parked"                   # not failed, deferred to another path
    INTRACTABLE = "intractable"         # budget exhausted or G2.5 dry-run failed
    INCONCLUSIVE = "inconclusive"       # G4 portfolio non-decisive OR C4 weak
    OOD_ESCALATION = "ood_escalation"   # G3 surrogate flagged OOD candidate

class TerminalState(str, Enum):
    PUBLISHED_EXTERNAL = "terminate_published_external"
    PUBLISHED_INTERNAL_ONLY = "terminate_published_internal_only"
    FALSIFIED = "terminate_falsified"
    INTRACTABLE = "terminate_intractable"
    INCONCLUSIVE = "terminate_inconclusive"
    DISCARDED = "terminate_discarded"
    PARKED_FOR_SCOPE_EXPANSION = "terminate_parked_for_scope_expansion"
    PARKED_FOR_LACK_OF_TOOLING = "terminate_parked_for_lack_of_tooling"
    DEDUP_SKIP = "terminate_dedup_skip"

@dataclass(frozen=True)
class GateResult:
    gate: Gate
    outcome: GateOutcome
    output_artifact_hash: ArtifactHash | None
    duration_s: float
    cost_usd: float
    notes: str
    metadata: dict[str, str | bool | int | float]   # carries qualified_track, skip_surrogate, skip_dedup, etc.
    next_step: "Gate | TerminalState"              # the resolved successor — never the string "terminate"

class StateMachine:
    def __init__(
        self,
        cycle_id: CycleId,
        domain_scope: DomainScope,
        budget: Budget,
        run_dir: Path,
        ledger: Ledger,
        mock_mode: bool = False,
    ) -> None: ...

    def run_cycle(self, gap: GapCandidate) -> EvidenceLedgerEntry:
        """Execute one cycle end-to-end. Returns the terminal EvidenceLedger entry.
        Raises GateError only for unrecoverable infrastructure failures.
        Domain rejections, validation failures, etc. produce EvidenceLedger entries with appropriate result."""

    def run_gate(
        self,
        gate: Gate,
        inputs: dict[str, ArtifactHash],
        metadata: dict[str, str | bool | int | float] | None = None,
    ) -> GateResult:
        """Execute one gate. Used by replay and step modes. The metadata dict carries cross-gate
        flags (e.g., qualified_track, skip_surrogate) that the implementing module reads."""

    def replay(self) -> list[GateResult]:
        """Walk persisted artifacts in run_dir without invoking external services."""

    def handle_control_event(self, event: FactoryControlEvent) -> None:
        """Process pause / resume / approve mutations emitted by spec 015 CLI."""

class C5Scheduler:
    """Slow-cadence program-direction council. Runs independently of per-cycle loop."""

    def __init__(
        self,
        cadence: timedelta,
        ledger: Ledger,
        domain_scope: DomainScope,
    ) -> None: ...

    def tick(self) -> CouncilVerdict | None:
        """Called by operator/cron. Runs C5 if cadence has elapsed since last tick; else no-op."""
```

## 4. Data Structures / Schemas

### 4.1 Gate routes table (`config/state_machine/gate_routes.yaml`)

Authoritative source for "what happens after gate X with outcome Y". Static YAML so a fresh agent can read the entire control flow in one file. Outcomes use the seven canonical `GateOutcome` values; route targets are either a `Gate` value or a `TerminalState` value. Metadata carried by the `GateResult` (e.g., `qualified_track`, `skip_surrogate`) is set by the implementing module, not the route table — the route table is purely a (gate, outcome) → successor map.

```yaml
G0:
  pass: G1
  fail: terminate_parked_for_scope_expansion
G1:
  pass: G1.5
  fail: terminate_discarded
G1.5:
  pass: G2
  fail: terminate_parked_for_lack_of_tooling
G2:
  pass: G2.5
  qualified: G2.5                  # C1 issued `qualified`; HypothesisSpec.qualified_track=True carries downstream
  fail: terminate_discarded
G2.5:
  pass: G3
  fail: terminate_intractable
G3:
  pass: G4
  ood_escalation: G4               # G4 runs with skip_surrogate=True via GateResult.metadata
  fail: terminate_falsified
G4:
  pass: G5
  fail: terminate_falsified
  inconclusive: terminate_inconclusive
G5:
  pass: G6
  fail: terminate_inconclusive     # C4 peer review rejected
G6:
  pass: terminate_published_external
  fail: terminate_published_internal_only
```

### 4.2 Per-gate config (`config/state_machine/gates/<gate-id>.yaml`)

Each gate has a small config file:

```yaml
gate: G3
timeout_seconds: 600
implementing_module: factory.surrogate
required_artifacts: [ExperimentSpec]
output_artifact: SurrogateProbeResult
ood_threshold_percentile: 0.85
```

For G4 specifically, the cross-simulator subcheck inherits its own sub-timeout from spec 009 (the validation portfolio spec), not from this file. The G4 outer timeout (3600 s, see §8) bounds the overall gate; the cross-simulator subcheck is bounded by spec 009 subspec.

### 4.3 Cycle directory layout

```
runs/<cycle-id>/
├── MANIFEST.json                Index: artifact hashes, gate sequence, terminal state, terminal EvidenceResult.
├── cycle.jsonl                  Event log.
├── artifacts/
│   ├── <hash>.json              One file per emitted artifact.
│   └── INDEX.json               Hash → type lookup.
├── councils/
│   ├── <session_id>.jsonl       From spec 001 (canonical per-cycle path).
│   └── INDEX.json               Session → council_id lookup.
└── sandbox/                     Spec 008 outputs per iteration; see FIX_PLAN §7.
    ├── 000/
    └── 001/
```

## 5. Algorithms / Logic

### 5.1 `run_cycle` main loop

The loop uses a `Gate | TerminalState` union throughout — there is **no** sentinel string. `Gate.TERMINATE` is reserved only for the implicit edge after a terminal-state branch and is never persisted in `gate_routes.yaml`.

```python
def run_cycle(self, gap: GapCandidate) -> EvidenceLedgerEntry:
    self._prepare_run_dir()
    self._persist_artifact(gap)

    inputs: dict[str, ArtifactHash] = {"GapCandidate": gap.provenance_hash}
    metadata: dict[str, str | bool | int | float] = {}
    current: Gate | TerminalState = Gate.G0_DOMAIN
    terminal: TerminalState | None = None

    while isinstance(current, Gate):
        # --- G0 dedup integration: consult Ledger triggers BEFORE running the gate body ---
        if current is Gate.G0_DOMAIN:
            trigger_eval = self.ledger.evaluate_triggers(gap.hypothesis_id)
            if trigger_eval.any_currently_satisfied():
                # Trigger says re-litigation is allowed; gate body still runs but downstream
                # must skip the dedup-skip path.
                metadata["skip_dedup"] = True
            elif trigger_eval.prior_entry_exists():
                # Identical prior; no re-run.
                terminal = TerminalState.DEDUP_SKIP
                break

        result = self.run_gate(current, inputs, metadata)
        self._persist_gate_result(result)
        self._emit_event("gate_exit", gate=current, outcome=result.outcome)

        if result.output_artifact_hash is not None:
            inputs[self._artifact_type_for(result.output_artifact_hash)] = result.output_artifact_hash

        # Implementing module sets cross-gate metadata flags on the GateResult.
        metadata.update(result.metadata)

        nxt = result.next_step
        if isinstance(nxt, TerminalState):
            terminal = nxt
            break
        current = nxt

    assert terminal is not None
    return self._build_and_persist_ledger_entry(gap, inputs, terminal, metadata)
```

`run_gate` resolves the successor by reading `gate_routes.yaml` for the `(gate, outcome)` pair. If the YAML target is a `Gate` name (`"G3"`), it returns the matching enum; if it is a `terminate_*` string, it returns the matching `TerminalState`. Any unknown target raises `GateRouteUndefined` — never silently default.

### 5.2 Gate dispatch

Each gate maps to an `implementing_module` (from per-gate config). The state machine imports that module's `run_gate(...)` entry, passes the required input artifact hashes plus the cross-gate `metadata` dict, awaits the result. If the gate doesn't return within `timeout_seconds`, raise `GateTimeoutError`.

Implementing-module contract (per FIX_PLAN §2):
- **G2** sets `metadata["qualified_track"] = True` on its `HypothesisSpec`-typed output artifact when the implementing council issues `qualified`. The next gate (G2.5) reads the flag from `HypothesisSpec.qualified_track` to run an intensified validation profile. The route table still goes G2 → G2.5 in both `pass` and `qualified` cases.
- **G3** sets `metadata["skip_surrogate"] = True` on its `GateResult` when it emits `OOD_ESCALATION`. G4 reads `metadata["skip_surrogate"]` and bypasses the surrogate-only fast path, running oracle-only. The route table still goes G3 → G4.

In mock mode, every implementing module's `mock.run_gate` is called instead — same signature, returns fixture results determined by `mock_outcomes.yaml`.

### 5.3 Recovery routing

Routes are **explicit per (gate, outcome) pair** in `gate_routes.yaml`. If a gate returns an outcome with no route defined, raise `GateRouteUndefined` immediately — never silently default.

Recovery successors are one of:
- The next gate (forward progress).
- The same gate with different config (encoded via `metadata` flags on the carried artifact, not via separate route targets).
- A `TerminalState`.

Loops are forbidden — the route table is validated at startup to be a DAG (`RouteCycleDetected` is raised by `validate-routes` if found).

### 5.4 EvidenceLedger entry construction

At cycle terminal:

- `result` (i.e., `EvidenceResult`) is mapped from the terminal state via the canonical table below. `EvidenceResult` stays at four values; granular terminal information is stored separately in `EvidenceLedgerEntry.terminal_state: TerminalState`.
- `provenance` = filled from cycle's environment hash + code hash + simulator metadata (`ProvenanceBlock`, spec 002).
- `council_verdict_hashes` = all `CouncilVerdict` artifacts persisted in this cycle.
- `run_report_hash` = present if G5 produced one.
- `relitigate_if` = derived from terminal state (e.g., `terminate_parked_for_lack_of_tooling` adds a trigger "simulator added that supports this hypothesis"). The Ledger's `evaluate_triggers` reads these on the next G0 re-entry.

**Canonical terminal → `EvidenceResult` mapping** (per FIX_PLAN §3.2):

| Terminal state | `EvidenceResult` value | Notes |
| :--- | :--- | :--- |
| `terminate_published_internal_only` | `passed` | Internal Ledger entry created; no external pub. |
| `terminate_published_external` | `passed` | Internal + external (G6 approved). |
| `terminate_falsified` | `falsified` | Result published as negative. |
| `terminate_intractable` | `intractable` | Budget exhausted or G2.5 dry-run failed. |
| `terminate_inconclusive` | `inconclusive` | G4 portfolio returned inconclusive OR C4 weak. |
| `terminate_discarded` | `inconclusive` | G1/G2 rejected; minimal Ledger entry for audit. |
| `terminate_parked_for_scope_expansion` | `inconclusive` | G0 rejected; parked for C5. |
| `terminate_parked_for_lack_of_tooling` | `inconclusive` | G1.5 rejected; parked for Catalog growth. |
| `terminate_dedup_skip` | `inconclusive` | G0 found identical prior; no re-run. |

The `EvidenceResult` enum (spec 002) is closed at `{passed, falsified, intractable, inconclusive}`. Any new terminal granularity is added to `TerminalState` and a new row in the table above — never by extending `EvidenceResult`.

### 5.5 C5 program-direction scheduler

Independent of per-cycle loop. Runs on a configurable cadence (default weekly). On tick:

1. Query the `EvidenceLedger` (spec 012) for findings from the past N days. This includes the high-surprise audit query `Ledger.top_high_surprise_with_dependents(k)` (spec 012 §3) which ranks entries by `surprise_bits × downstream_citation_count` — the most-cited surprising findings are the highest-leverage candidates for re-audit (FIX_PLAN §26.4).
2. Query the `StrategyArchive` (`specs/016-strategy-archive.md`) for **top-K most productive strategies** (ranked by EMA reward + surprise composite) and **lineage saturation indicators** (per-lineage visit counts vs. surprise EMA decay, MAP-Elites cell occupancy when `parallel_lineages_k > 1`). The archive context is read-only at C5 — the council does not mutate strategy state.
3. Construct a context document (top-cited findings, top-high-surprise findings with dependents, dissent-heavy verdicts, OOD-escalation rate, sycophancy report, top-K productive strategies, lineage saturation summary).
4. Call `Council.deliberate(council_id=C5, ...)`.
5. Apply `chairman_decision` (which is one of `approve | reject | qualified | no_consensus`, per FIX_PLAN §3.1):
   - `approve` → apply the council's recommendation to `DomainScope` (add/remove `allowed_domains`, update `expansion_criteria`). When the archive surfaces lineage saturation, `DomainScope` changes are now **informed by archive saturation** (e.g., expand scope when current-domain lineages are saturated; tighten scope when a productive lineage has open MAP-Elites cells worth deepening).
   - `reject` → no state change; record verdict.
   - `qualified` → apply the recommendation with a `qualified_track=True` flag on the downstream `DomainScope` mutation so downstream cycles know to apply intensified validation; record verdict.
   - `no_consensus` → **no scope change**. Emit a `factory.state_machine.c5_no_consensus` telemetry event with the session id; the verdict is still recorded for operator review. No retry, no fallback.

C5 outcomes are written as `CouncilVerdict` to the Ledger but do not bind any per-cycle state beyond the explicit `DomainScope` mutation in the `approve` / `qualified` branches.

### 5.6 G0 dedup + trigger evaluation

Before each cycle's G0 body executes, the state machine calls:

```python
trigger_eval = self.ledger.evaluate_triggers(gap.hypothesis_id)
```

The returned object exposes two predicates:

- `prior_entry_exists()` — there is at least one prior `EvidenceLedgerEntry` keyed by the gap's hypothesis fingerprint.
- `any_currently_satisfied()` — at least one `RelitigationTrigger` on a prior entry is `currently_satisfied=True`.

Routing rules consumed by the run-loop in §5.1:

- If `any_currently_satisfied()` is `True` → gate body proceeds; `metadata["skip_dedup"] = True` is carried forward and the gate's `pass`/`fail` outcome routes normally. (Equivalent to FIX_PLAN's "PASS with skip_dedup metadata".)
- Else if `prior_entry_exists()` → the run-loop short-circuits to `TerminalState.DEDUP_SKIP` without running the G0 body. The Ledger emission writes a minimal entry with `result = inconclusive` and `terminal_state = terminate_dedup_skip`.
- Else → gate body runs normally with no special metadata.

`evaluate_triggers` is also exposed via the per-module CLI: `python -m factory.ledger evaluate-triggers --hypothesis-id <id>`.

## 6. Failure Modes

All error classes inherit from `FactoryError` (declared in spec 002). The error hierarchy:

```
FactoryError                    # spec 002
└── GateError
    ├── GateTimeoutError
    ├── GateRouteUndefined
    ├── ArtifactNotFound
    ├── RouteCycleDetected
    └── ImplementingModuleMissing
```

| Error class | When it fires | Recovery action |
| :--- | :--- | :--- |
| `GateTimeoutError` | Gate exceeded configured `timeout_seconds` | Halt gate; terminal = `terminate_intractable` (→ `EvidenceResult.INTRACTABLE`); cycle ends with documented timeout |
| `GateRouteUndefined` | Gate returned outcome not in `gate_routes.yaml` | Configuration error; halt all cycles; fix YAML |
| `ArtifactNotFound` | Required input artifact missing | Bug in upstream gate; halt cycle; terminal = `terminate_inconclusive` |
| `BudgetExhausted` (raised by spec 013) | Budget tracker reports cap breached | Routed to `terminate_intractable` automatically; not propagated as error |
| `RouteCycleDetected` | Startup validation finds a cycle in routes | Refuse to start; fix YAML |
| `ImplementingModuleMissing` | Gate's `implementing_module` cannot be imported | Configuration error; halt; fix |

**Cross-spec interaction notes (FIX_PLAN §26.4):**

- C5 program-direction (§5.5) consumes `StrategyArchive` read-only queries from `specs/016-strategy-archive.md`. Archive unavailability is non-fatal: C5 deliberation proceeds without the strategy/lineage context, the verdict records the missing input, and `DomainScope` mutations fall back to ledger-only signals.
- The G3 → G4 transition delegates tier execution to `FidelityLadderScheduler.run_next_tier(...)` from `specs/017-fidelity-scheduler.md`. The scheduler's `kill_reason()` propagates back as the gate outcome (`PASS` on promote-to-next-tier, `FAIL`/`INCONCLUSIVE` per the kill semantics). The state machine itself does not implement ladder traversal — it dispatches to the scheduler.

## 7. Testing

**Mock-mode** (CI):
- `test_state_machine_typical_usage.py` — REQUIRED. Run a full cycle with all mock gates; verify terminal artifact + manifest + event log shape.
- `test_recovery_routes.py` — for each `(gate, outcome)` pair in `gate_routes.yaml`, drive the state machine and verify correct route across all seven outcomes.
- `test_gate_timeout.py` — mock gate hangs; verify timeout fires and routes to `terminate_intractable`.
- `test_replay.py` — run a cycle live, then replay from persisted artifacts; verify same event sequence.
- `test_route_validation.py` — startup catches an introduced cycle in the YAML.
- `test_c5_scheduler.py` — cadence honored; all four `chairman_decision` branches (`approve`, `reject`, `qualified`, `no_consensus`) drive the documented behavior; `no_consensus` emits the telemetry event and no scope change.
- `test_g0_dedup.py` — three branches of `evaluate_triggers` (prior + satisfied, prior + unsatisfied, no prior) produce the documented routing.
- `test_qualified_track_propagation.py` — G2 `qualified` outcome sets `HypothesisSpec.qualified_track=True`; G2.5 reads and applies intensified profile.
- `test_skip_surrogate_propagation.py` — G3 `ood_escalation` outcome sets `metadata["skip_surrogate"]`; G4 reads and runs oracle-only.

**Live-mode** (`@pytest.mark.live`, gated):
- `test_one_cycle_live.py` — single cycle against real Council, real catalog, real generator-verifier. Slow + expensive; manual gate.

**Acceptance test** (PRD-003): full cycle in mock mode reproduces the canonical reference cycle in `factory/state_machine/fixtures/cycles/reference_cycle.json`.

## 8. Performance & Budget

- Per-gate overhead (orchestrator only): < 50 ms.
- Gate timeouts (config defaults):
  - G0, G1, G1.5: 5 s each (pure checks).
  - G2 (council): 120 s.
  - G2.5 (dry-run): 300 s.
  - G3 (surrogate): 600 s.
  - G4 (validation portfolio): **3600 s** (outer gate budget). The cross-simulator subcheck inside G4 inherits its own subspec budget from spec 009 and is bounded independently — it does not extend the 3600 s outer cap.
  - G5 (interpretation + review councils): 240 s.
  - G6 (human gate): unbounded but flagged.
- Total per-cycle target: ≤ 72 h wall clock (PRD-001 constraint).

## 9. Open Questions

- **Parallel cycle execution.** Phase A is one cycle at a time. Phase B may run N concurrent cycles with independent budgets. State machine is stateless per cycle so this should be a thin wrapper, but resource contention (sandbox, surrogate) needs design.
- **Partial replay from mid-cycle.** Replay currently walks the full cycle. Restarting a failed cycle from gate K with new code is a Phase B feature.
- **C5 expansion criteria semantics.** How does C5 actually decide whether to expand `DomainScope`? Currently relies on chairman judgment + Council prompts. Needs calibration in PRD-001 acceptance.

## 10. TODO Checklist

- [ ] Scaffold `factory/state_machine/` from canonical template.
- [ ] Implement `Gate`, `GateOutcome` (seven values: PASS, FAIL, QUALIFIED, PARKED, INTRACTABLE, INCONCLUSIVE, OOD_ESCALATION), `TerminalState`, `GateResult` types.
- [ ] Implement `Gate | TerminalState` union throughout `run_cycle`; remove any string `"terminate"` sentinel.
- [ ] Write `config/state_machine/gate_routes.yaml` with full route table (using `G2.5` for qualified and `G4` for ood_escalation — no synthetic gate names); write loader + DAG-validator (raises `RouteCycleDetected`).
- [ ] Implement per-gate config loader (`config/state_machine/gates/<gate>.yaml`).
- [ ] Implement `StateMachine.run_cycle` main loop using the clean union (no string sentinel).
- [ ] Implement `StateMachine.run_gate` with timeout + dispatch + metadata propagation (`qualified_track`, `skip_surrogate`, `skip_dedup`).
- [ ] Implement G0 `evaluate_triggers` integration per §5.6 (call before gate body; route to PASS+skip_dedup or `terminate_dedup_skip`).
- [ ] Implement G2 contract: set `HypothesisSpec.qualified_track=True` when C1 issues `qualified`.
- [ ] Implement G3 contract: set `metadata["skip_surrogate"]=True` when emitting `OOD_ESCALATION`; G4 reads and applies oracle-only path.
- [ ] Implement artifact persistence + `MANIFEST.json` builder (includes `terminal_state` and `EvidenceResult`).
- [ ] Implement `cycle.jsonl` event logger.
- [ ] Implement `StateMachine.replay`.
- [ ] Implement step mode (`--pause-after`).
- [ ] Implement EvidenceLedger entry construction with the canonical terminal → `EvidenceResult` mapping table (§5.4); persist `terminal_state` on the entry.
- [ ] Implement `C5Scheduler` handling all four `chairman_decision` values (approve / reject / qualified / no_consensus); emit `factory.state_machine.c5_no_consensus` telemetry event on no-consensus.
- [ ] Implement `StateMachine.handle_control_event` consuming `FactoryControlEvent` from spec 015.
- [ ] Ensure every error class inherits `FactoryError` (no bare `Exception` subclasses).
- [ ] Mock-mode: every gate has a `mock.run_gate` returning fixture results from `mock_outcomes.yaml`, including OOD_ESCALATION and INCONCLUSIVE outcomes.
- [ ] Write `factory/state_machine/cli.py` with run-cycle, replay, inspect, step, submit-gaps, run-gate, validate-routes, force-terminate.
- [ ] Author tests listed in §7 (typical-usage + concern tests). All pass in mock mode.
- [ ] Wire `C5Scheduler` to read the `StrategyArchive` (`specs/016-strategy-archive.md`) top-K productive strategies and lineage saturation indicators per §5.5 step 2; treat archive unavailability as non-fatal context degradation (FIX_PLAN §26.4).
- [ ] Wire `C5Scheduler` to read `Ledger.top_high_surprise_with_dependents(k)` (spec 012) into the C5 context document (FIX_PLAN §26.4).
- [ ] Wire the G3 → G4 transition to dispatch through `FidelityLadderScheduler.run_next_tier(...)` (`specs/017-fidelity-scheduler.md`) instead of calling the validation portfolio directly; map `TierResult.promoted` / `kill_reason()` back to `GateOutcome` for `gate_routes.yaml` (FIX_PLAN §26.4).
- [ ] Write `factory/state_machine/README.md`.
- [ ] Write `docs/runbooks/state-machine-debugging.md`.
- [ ] Verify `mypy --strict factory/state_machine/` passes.
