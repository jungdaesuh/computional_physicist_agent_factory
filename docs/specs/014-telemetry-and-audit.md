# Spec 014: Telemetry & Audit

> Status: ☐ not started · Owner: TBD · Last updated: 2026-05-23

## CONTEXT (60-second summary — read first)
- This module is the **structured event substrate** of the factory. Every other module emits `{ts, cycle_id, module, level, event, payload}` records via `factory.telemetry.emit(...)`; the records land in the per-cycle `runs/<cycle-id>/cycle.jsonl` log (ARCHITECTURE.md §1.4). Telemetry is *not* a free-text logger — every `event` name comes from an **extensible namespace** policy whose closed dimension is the **set of module namespaces**, not the set of event names.
- The 5 facts: (1) per-cycle JSONL `runs/<cycle-id>/cycle.jsonl` is the SSOT for run-time observability; (2) the **namespace** axis is closed (15 module namespaces; see §4.2); the **event name** axis is open per-namespace and is registered by each module's own `events.py`; (3) all modules talk *to* telemetry, never to each other for status (ARCHITECTURE.md §3.2); (4) telemetry is a **soft dependency** — `emit()` degrades to a no-op if the module is unavailable; (5) the optional Aggregator tails per-cycle logs to compute rates (sycophancy, OOD escalation, dollar burn) that feed C5 program-direction council.
- Open first: `factory/telemetry/api.py` and the typical-usage test.

## ENTRY POINTS
- Main module: `factory/telemetry/api.py`
- Typical-usage test: `factory/telemetry/tests/test_telemetry_typical_usage.py`
- CLI: `python -m factory.telemetry --help` (subcommands: `emit`, `tail`, `export`, `query`, `aggregate`)
- Mock-mode example: `python -m factory.telemetry tail --cycle <id> --mock-mode`
- Runbook: `docs/runbooks/telemetry-export.md`

## LOCAL DEBUG
- Instantiate without a real cycle: `TelemetryEmitter(cycle_dir=Path("/tmp/cycle-x"), mock_mode=True).emit(...)` writes to a tmp `cycle.jsonl`.
- Tail a live cycle: `python -m factory.telemetry tail --cycle <id>` streams events as they are appended.
- Common error signatures → recovery:
  - `EventTaxonomyViolation` → either the namespace is unknown (caller used `factory.notamodule.x` — fix the caller) or the event name is unregistered in a known namespace's `events.py` (add it to that module's `events.py` registry or fix the typo). Never accept dynamic free-text events.
  - `LogFileLocked` → another writer holds an exclusive lock; retry with backoff; if persistent, inspect for crashed writers.
  - `JSONLineCorrupted` → mid-line truncation in `cycle.jsonl` (writer crashed mid-flush); export skips the bad line and emits a `factory.telemetry.line_corrupted` event into a side log.
  - `AggregatorBacklog` → Aggregator is more than N events behind tail; either it is paused or downstream consumers are slow; check `aggregator.state.json` for last-processed offset.
  - `RetentionPolicyConflict` → an operator-set retention rule contradicts the "per-cycle logs are kept indefinitely" invariant; reject and surface in the runbook.
- Logs to inspect: `runs/<cycle-id>/cycle.jsonl` (raw), `runs/<cycle-id>/MANIFEST.json` (index), optional `runs/_aggregator/state.json` (Aggregator offsets), `runs/_aggregator/metrics.jsonl` (rolled-up metrics).

## DEPENDENCIES
- **Hard:** Spec 012 (`EvidenceLedger`) — audit-trail queries that resolve `hypothesis_id` → cycles use the Ledger's index to walk back to cycle directories.
- **Soft:** Spec 002 (artifacts) — events may reference `ArtifactHash` values in payloads, but telemetry never opens artifact files. Spec 013 (budget) — Aggregator may surface dollar-burn-by-module from telemetry events but does not double-write the budget ledger.
- **Mocks available:** `MockTelemetryEmitter` (no-op), `FixtureCycleLog` fixture (10 deterministic events for tail/export tests), `MockAggregator` (returns pre-canned metrics report).
- **Soft-dependency contract:** every module is expected to call `factory.telemetry.emit(...)`. If the telemetry import fails or `FACTORY_TELEMETRY_DISABLED=1` is set, calls degrade to no-ops; module behavior is otherwise unchanged. The factory MUST still function (without observability) when telemetry is unavailable.

---

## 1. Summary

This module provides a **structured, per-cycle, append-only event stream** with an **extensible-by-namespace** taxonomy. The closed axis is the set of 15 **module namespaces** (`factory.council`, `factory.catalog`, ...); each module owns its own event names in its `events.py` registry per the canonical module template. Every meaningful state transition in the factory — a council deliberation finishing, a smoke test passing, a budget cap warning, an OOD candidate escalating, a Ledger entry persisting — is an event with a registered name and a typed payload. The per-cycle JSONL log is the run-time SSOT for observability; an optional Aggregator tails per-cycle logs and computes program-level metrics that feed C5 (program-direction council) and Spec 015 (operator interface) UI surfaces.

## 2. Scope

**In scope:**
- `TelemetryEmitter` writing structured events to `runs/<cycle-id>/cycle.jsonl`.
- **Extensible-by-namespace** taxonomy: closed set of module namespaces; event names registered per-module in `factory/<module>/events.py`.
- Startup-time aggregation: telemetry imports each registered module and collects its event-name set into a single in-memory registry; `emit()` validates against this registry.
- Soft-dependency degradation (no-op when module unavailable).
- Export CLI: `telemetry export --format jsonl --cycle <id>`, `--since <date>`.
- Audit-trail query CLI: filter by `hypothesis_id`, `cycle_id`, `event` name, time range.
- Aggregator (optional, skeleton-level) that tails per-cycle logs and computes:
  - Sycophancy rate (from `factory.council.sycophancy_detected` events).
  - OOD escalation rate (from `factory.surrogate.ood_escalation` events).
  - Dollar burn by module (from any event carrying `payload.cost_usd`).
- Per-cycle log rotation policy: kept indefinitely on disk; never rotated within a cycle.

**Out of scope:**
- Generic log shipping to external observability backends (Datadog, Honeycomb). Deferred to Phase B.
- Real-time alerting / paging. Deferred.
- Distributed tracing across processes. Phase A is single-process per cycle.
- UI rendering of metrics — that is Spec 015's responsibility; this module exposes the data.
- The `EvidenceLedger` DB itself (owned by Spec 012); audit queries go through the Ledger for hypothesis-anchored lookups.
- Adding **new module namespaces** at run-time — the namespace axis is closed at code-review time (any new namespace requires an INDEX.md / ARCHITECTURE.md amendment, not just an `events.py` addition).

## 3. Public Interface

```python
# factory/telemetry/api.py — SKELETON (TODO: full signatures)

from pathlib import Path
from typing import Any, Literal
from factory.artifacts import CycleId, HypothesisId, ArtifactHash

# TODO: define FactoryError-derived class hierarchy
class TelemetryError(FactoryError): ...
class EventTaxonomyViolation(TelemetryError): ...
class LogFileLocked(TelemetryError): ...
class JSONLineCorrupted(TelemetryError): ...
class AggregatorBacklog(TelemetryError): ...
class RetentionPolicyConflict(TelemetryError): ...

EventLevel = Literal["debug", "info", "warn", "error"]

# Closed set of MODULE NAMESPACES (the only closed dimension of the taxonomy).
# Event names are extensible per-namespace via each module's events.py.
KNOWN_NAMESPACES: frozenset[str] = frozenset({
    "factory.council",
    "factory.catalog",
    "factory.selector",
    "factory.adapter",
    "factory.literature",
    "factory.genver",
    "factory.validation",
    "factory.surrogate",
    "factory.writer",
    "factory.ledger",
    "factory.budget",
    "factory.telemetry",
    "factory.operator",
    "factory.state_machine",
    "factory.artifacts",
})

class EventRegistry:
    """In-memory registry of {namespace -> frozenset[event_name]}.
    Built once at telemetry startup by importing each module in KNOWN_NAMESPACES
    and reading its events.py REGISTERED_EVENTS constant.
    Immutable after build(); emit() does an O(1) lookup against it.
    """
    # TODO: classmethod build(known=KNOWN_NAMESPACES) -> "EventRegistry"
    # TODO: contains(event_name: str) -> bool   (validates "factory.<ns>.<name>" against registry)
    # TODO: namespaces() -> frozenset[str]
    # TODO: events_for(namespace: str) -> frozenset[str]
    ...

class TelemetryEmitter:
    """Per-cycle event writer. One emitter per cycle, owned by the state machine."""
    # TODO: signature: __init__(cycle_dir, registry: EventRegistry, mock_mode=False, flush_every_n=1)
    # TODO: emit(event: str, payload: dict, level: EventLevel = "info") -> None
    # TODO: close() -> None  (flushes + releases file lock)
    ...

def emit(event: str, payload: dict[str, Any], *, level: EventLevel = "info") -> None:
    """Module-global convenience entry point. Reads the active cycle from context.
    Soft-dependency contract: no-op if no active emitter or if FACTORY_TELEMETRY_DISABLED=1.
    """
    # TODO

class AuditQuery:
    """Query interface over per-cycle logs + EvidenceLedger index."""
    # TODO: by_hypothesis(hypothesis_id) -> Iterator[Event]
    # TODO: by_cycle(cycle_id) -> Iterator[Event]
    # TODO: by_event_name(event, since=None, until=None) -> Iterator[Event]
    ...

class Aggregator:
    """Optional process that tails per-cycle logs and computes program-level metrics.
    Surfaces metrics for C5 program-direction council (sycophancy rate, OOD rate, $-burn).
    """
    # TODO: run(once=False) -> None
    # TODO: snapshot() -> AggregatorReport
    ...
```

### 3.1 Per-module `events.py` contract (canonical module template addition)

Every module listed in `KNOWN_NAMESPACES` MUST expose a `factory/<module>/events.py` file with the following surface:

```python
# factory/<module>/events.py — canonical template

NAMESPACE: str = "factory.<module>"

# Tuple of EVENT-NAME SUFFIXES owned by this module. Fully-qualified event names
# are computed as f"{NAMESPACE}.{suffix}". Each suffix MUST be snake_case and MUST
# be unique within this module.
REGISTERED_EVENTS: tuple[str, ...] = (
    "<verb_or_noun>",
    # ...
)

# Optional: per-event payload schemas (recommended; required when payload non-trivial).
# Pydantic models keyed by suffix; the EventRegistry MAY validate payloads against
# these at emit() time when the schema is present.
PAYLOAD_SCHEMAS: dict[str, type] = {
    # "<suffix>": <PydanticModel>,
}
```

The canonical module template in `ARCHITECTURE.md` §3 must include `events.py` as a required file alongside `api.py`, `cli.py`, `tests/`, and `README.md`.

## 4. Data Structures / Schemas

### 4.1 Per-cycle log line (`runs/<cycle-id>/cycle.jsonl`)

One JSON object per line. UTF-8, LF terminator. Schema:

```json
{
  "ts": "2026-05-23T14:02:11.482Z",
  "cycle_id": "cyc-0001",
  "module": "factory.council",
  "level": "info",
  "event": "factory.council.deliberation_complete",
  "payload": {
    "council_id": "C1",
    "verdict_hash": "7a3b2c1...",
    "chairman_decision": "approve",
    "total_cost_usd": 0.42,
    "wall_clock_seconds": 38.1
  }
}
```

Required fields: `ts` (RFC3339 UTC), `cycle_id`, `module` (dotted; MUST equal the namespace prefix of `event`), `level`, `event` (MUST be `<module>.<suffix>` where `module` is in `KNOWN_NAMESPACES` and `suffix` is registered in that module's `events.py`), `payload` (object — may be empty `{}`). No extra top-level keys.

### 4.2 Closed-set: module namespaces

The **only** closed axis of the taxonomy. Adding a new namespace requires an INDEX.md + ARCHITECTURE.md amendment and is **not** a run-time operation.

| # | Namespace | Module spec | Owns events.py at |
| ---: | :--- | :--- | :--- |
| 1 | `factory.council` | 001 | `factory/council/events.py` |
| 2 | `factory.catalog` | 004 | `factory/catalog/events.py` |
| 3 | `factory.selector` | 005 | `factory/selector/events.py` |
| 4 | `factory.adapter` | 006 | `factory/adapter/events.py` |
| 5 | `factory.literature` | 007 | `factory/literature/events.py` |
| 6 | `factory.genver` | 008 | `factory/genver/events.py` |
| 7 | `factory.validation` | 009 | `factory/validation/events.py` |
| 8 | `factory.surrogate` | 010 | `factory/surrogate/events.py` |
| 9 | `factory.writer` | 011 | `factory/writer/events.py` |
| 10 | `factory.ledger` | 012 | `factory/ledger/events.py` |
| 11 | `factory.budget` | 013 | `factory/budget/events.py` |
| 12 | `factory.telemetry` | 014 | `factory/telemetry/events.py` |
| 13 | `factory.operator` | 015 | `factory/operator/events.py` |
| 14 | `factory.state_machine` | 003 | `factory/state_machine/events.py` |
| 15 | `factory.artifacts` | 002 | `factory/artifacts/events.py` |

### 4.3 Open-set (per-namespace): registered event names

Each namespace's `events.py` is the SSOT for the events that namespace may emit. The list grows by ordinary PR (adding a suffix to `REGISTERED_EVENTS` plus the call site that emits it) — no spec-014 amendment required.

#### 4.3.1 Required events that MUST be registered by Phase A

These events are referenced by spec contracts (state machine routing, aggregator metrics, runbook procedures) and therefore are part of the Phase-A acceptance surface. Each must appear in the listed module's `events.py`:

`factory/genver/events.py` (spec 008):
- `iteration_start`
- `iteration_end`
- `sandbox_open`
- `sandbox_exit`
- `promote_attempt`
- `promote_succeeded`
- `promote_failed`

`factory/ledger/events.py` (spec 012):
- `entry_inserted`
- `trigger_check_failed`
- `evaluate_triggers_complete`

`factory/surrogate/events.py` (spec 010):
- `evaluated`
- `ood_escalation`
- `retrain_started`
- `retrain_complete`

`factory/budget/events.py` (spec 013):
- `cap_warning`
- `cap_exhausted`
- `aggregate_halt`

`factory/state_machine/events.py` (spec 003):
- `gate_enter`
- `gate_exit`
- `cycle_complete`

`factory/council/events.py` (spec 001):
- `deliberation_complete`
- `sycophancy_detected`

`factory/catalog/events.py` (spec 004):
- `smoke_test_passed`
- `smoke_test_failed`

`factory/validation/events.py` (spec 009):
- `portfolio_passed`
- `portfolio_failed`

`factory/telemetry/events.py` (spec 014):
- `line_corrupted`
- `aggregator_backlog`

Modules may register additional events as they land; the list above is the **minimum** Phase-A floor. The aggregator's metric computations and the runbook procedures depend on these specific names being registered.

### 4.4 Aggregator state (`runs/_aggregator/state.json`)

TODO: schema for last-processed offset per cycle log; not yet defined.

### 4.5 Aggregator metrics output (`runs/_aggregator/metrics.jsonl`)

TODO: define rolled-up metric record schema (sycophancy_rate, ood_escalation_rate, dollar_burn_by_module).

## 5. Algorithms / Logic

### 5.1 Startup: build the EventRegistry

Executed once when the first `TelemetryEmitter` is constructed in a process:

1. For each `ns` in `KNOWN_NAMESPACES`:
   1. `import factory.<ns_suffix>.events as ev_mod` (e.g. `factory.council.events`).
   2. Assert `ev_mod.NAMESPACE == ns` (fail-fast if a module's events.py is mislabeled).
   3. Collect fully-qualified names: `{f"{ns}.{suffix}" for suffix in ev_mod.REGISTERED_EVENTS}`.
2. Union all namespaces' event sets into a single `frozenset[str]` indexed by fully-qualified name.
3. If any module's `events.py` cannot be imported, telemetry **does not** silently skip it — it surfaces the import error as a startup failure. (The soft-dependency contract applies to *callers* of telemetry, not to *telemetry's discovery of its own registry*.)

### 5.2 Emit path (per-cycle JSONL)

1. Resolve the active `TelemetryEmitter` for the current cycle from the state machine's context.
2. Parse `event` into `(namespace, suffix)` by splitting on the last `.`.
3. **Namespace check:** if `namespace not in KNOWN_NAMESPACES`, raise `EventTaxonomyViolation("unknown namespace: <ns>")`.
4. **Event-name check:** if `event not in registry`, raise `EventTaxonomyViolation("unregistered event in known namespace: <event>")`. The error message distinguishes the two failure modes (§6).
5. (Optional) If a `PAYLOAD_SCHEMAS[suffix]` Pydantic model is registered, validate `payload` against it; on mismatch, raise `EventTaxonomyViolation("payload schema mismatch: <event>")`.
6. Build the record `{ts, cycle_id, module, level, event, payload}`. Assert `module == namespace`.
7. Acquire an exclusive append lock on `cycle.jsonl`; `fsync` per `flush_every_n` records.
8. Append the JSON-serialized line + `\n`; release lock.
9. On import or write failure at the *caller* side, degrade to no-op (soft dependency).

### 5.3 Export and audit query

- `telemetry export --cycle <id>` streams the cycle's `cycle.jsonl` to stdout (or `--out file.jsonl`).
- `telemetry export --since <date>` walks `runs/*/cycle.jsonl` in cycle-id-sorted order, emits records with `ts >= date`.
- `AuditQuery.by_hypothesis(hypothesis_id)` resolves `hypothesis_id` → list of cycle IDs via the `EvidenceLedger` index (spec 012), then concatenates filtered streams.
- Corrupt lines (mid-flush truncation) are skipped with a side-channel `factory.telemetry.line_corrupted` event.

### 5.4 Aggregator (Aggregator process — TBD in skeleton)

- Watches `runs/` for new cycle directories; tails each `cycle.jsonl` from last offset in `runs/_aggregator/state.json`.
- Maintains rolling counters keyed by module and event:
  - `sycophancy_rate = count(factory.council.sycophancy_detected) / count(factory.council.deliberation_complete)` over a window.
  - `ood_escalation_rate = count(factory.surrogate.ood_escalation) / count(factory.surrogate.evaluated)`.
  - `dollar_burn_by_module = Σ payload.cost_usd` grouped by `module`.
- Emits rolled-up records to `runs/_aggregator/metrics.jsonl`; consumed by C5 council briefings and Spec 015 UI.

### 5.5 Retention

Per-cycle `runs/<cycle-id>/cycle.jsonl` is **kept indefinitely** (cheap on disk; auditability is the priority). The Aggregator's own state may roll over (window-based). Any operator request to delete per-cycle logs surfaces as `RetentionPolicyConflict` and routes to the runbook.

## 6. Failure Modes

| Error class | When it fires | Recovery action |
| :--- | :--- | :--- |
| `EventTaxonomyViolation` | (a) Caller uses an unknown **namespace** (typo or new module not yet listed in `KNOWN_NAMESPACES`) — fix the caller or amend INDEX.md/ARCHITECTURE.md. (b) Caller uses an event name **not registered** in that namespace's `events.py` — add the suffix to `REGISTERED_EVENTS` in the owning module's `events.py`, or fix the typo. (c) Payload fails the namespace's `PAYLOAD_SCHEMAS` validation. The error message distinguishes the three sub-cases. | Reject at `emit()`; CI catches via unit tests that assert every emit() call site uses a registered name; never accept dynamic event names |
| `LogFileLocked` | Another writer holds the lock past timeout | Retry with bounded backoff; if persistent, surface to state machine; investigate for orphaned writers |
| `JSONLineCorrupted` | Export/audit reader hits a truncated mid-line write | Skip line; emit `factory.telemetry.line_corrupted` to a side log; continue |
| `AggregatorBacklog` | Aggregator falls more than N events behind tail of any cycle | Pause Aggregator; alert via UI; investigate downstream consumer slowness |
| `RetentionPolicyConflict` | An operator-set retention rule contradicts "per-cycle logs indefinite" | Reject the rule; document in runbook; do not silently delete |
| `TelemetryDisabled` (non-error condition) | `FACTORY_TELEMETRY_DISABLED=1` or import failed | No-op `emit()`; factory continues without observability |

## 7. Testing

**Mock-mode unit tests** (in CI):
- `test_telemetry_typical_usage.py` — REQUIRED. Constructs `TelemetryEmitter` against a tmp cycle dir; emits 3 events across 2 modules; verifies JSONL schema + taxonomy enforcement.
- `test_event_registry_build.py` — REGISTRY building: every namespace in `KNOWN_NAMESPACES` is importable, every module exposes `NAMESPACE` and `REGISTERED_EVENTS`, `NAMESPACE` matches the expected value, all required Phase-A events (§4.3.1) are present.
- `test_namespace_vs_event_violation.py` — unknown namespace and unregistered-suffix-in-known-namespace both raise `EventTaxonomyViolation` with distinguishable error messages.
- `test_soft_dependency_degradation.py` — `FACTORY_TELEMETRY_DISABLED=1` makes `emit()` a no-op; downstream module logic unaffected.
- `test_export_and_query.py` — `telemetry export --cycle <id>` and `AuditQuery.by_hypothesis` over fixture cycles.
- `test_corrupted_line_handling.py` — manually-corrupted line in cycle.jsonl; export skips + side-log fires.

**Live-mode tests** (`@pytest.mark.live`, gated):
- TODO: `test_aggregator_against_real_cycle.py` — runs Aggregator over a Phase-A end-to-end cycle.

## 8. Performance & Budget

- `emit()` per-call latency: < 1 ms (append + fsync amortized via `flush_every_n`).
- Registry-build cost: one-time on first emitter construction; bounded by `len(KNOWN_NAMESPACES) = 15` import statements (~tens of ms cold; cached thereafter).
- `cycle.jsonl` typical size per cycle: 100 KB – 5 MB depending on event verbosity.
- Aggregator tail latency target: ≤ 5 s behind tail of any active cycle.
- Disk footprint: per-cycle logs are kept indefinitely; budget at the volume level, not per-cycle.

## 9. Open Questions

- **Aggregator process model.** Co-resident with state machine, sidecar process, or pull-based on demand? Skeleton defers to Aggregator implementation phase.
- **Per-event payload schema enforcement.** `PAYLOAD_SCHEMAS` is optional in the events.py template. Should it be mandatory for Phase-A required events (§4.3.1)? Strict typing wins long-term; cost is template-maintenance burden.
- **Cross-cycle event correlation.** A hypothesis spans multiple cycles (re-litigation). Whether to denormalize `hypothesis_id` onto every event or join via the Ledger at query time is an open trade-off (write-time cost vs. read-time cost).
- **Aggregator metric windowing.** Rolling N events vs. rolling time window vs. since-last-C5; needs C5 council requirements to land.
- **Per-event-name access controls.** Some events (e.g. `factory.budget.cap_exhausted`) may be operator-visible while others are debug-only. Deferred until Spec 015 UI defines surfaces.

## 10. TODO Checklist

- [ ] Scaffold `factory/telemetry/` from the canonical module template.
- [ ] Author `factory/telemetry/events.py` declaring `NAMESPACE = "factory.telemetry"` and `REGISTERED_EVENTS = ("line_corrupted", "aggregator_backlog", ...)`.
- [ ] Author `factory/council/events.py` (registers `deliberation_complete`, `sycophancy_detected`, plus any spec-001 additions).
- [ ] Author `factory/catalog/events.py` (registers `smoke_test_passed`, `smoke_test_failed`, plus any spec-004 additions).
- [ ] Author `factory/selector/events.py` (registers spec-005 events).
- [ ] Author `factory/adapter/events.py` (registers spec-006 events).
- [ ] Author `factory/literature/events.py` (registers spec-007 events).
- [ ] Author `factory/genver/events.py` (registers `iteration_start`, `iteration_end`, `sandbox_open`, `sandbox_exit`, `promote_attempt`, `promote_succeeded`, `promote_failed`).
- [ ] Author `factory/validation/events.py` (registers `portfolio_passed`, `portfolio_failed`, plus any spec-009 additions).
- [ ] Author `factory/surrogate/events.py` (registers `evaluated`, `ood_escalation`, `retrain_started`, `retrain_complete`).
- [ ] Author `factory/writer/events.py` (registers spec-011 events).
- [ ] Author `factory/ledger/events.py` (registers `entry_inserted`, `trigger_check_failed`, `evaluate_triggers_complete`).
- [ ] Author `factory/budget/events.py` (registers `cap_warning`, `cap_exhausted`, `aggregate_halt`).
- [ ] Author `factory/operator/events.py` (registers spec-015 events).
- [ ] Author `factory/state_machine/events.py` (registers `gate_enter`, `gate_exit`, `cycle_complete`, plus any spec-003 additions).
- [ ] Author `factory/artifacts/events.py` (registers spec-002 events; may be minimal/empty in Phase A).
- [ ] Implement `EventRegistry.build()` that imports every namespace in `KNOWN_NAMESPACES`, asserts `NAMESPACE` match, and unions `REGISTERED_EVENTS` into the registry.
- [ ] Implement `TelemetryEmitter` with per-cycle JSONL append, file-lock, registry-backed `event` validation (namespace + suffix), and `flush_every_n` policy.
- [ ] Implement the module-global `emit()` convenience entry point with soft-dependency degradation (`FACTORY_TELEMETRY_DISABLED=1` → no-op).
- [ ] Implement `AuditQuery` with `by_hypothesis`, `by_cycle`, `by_event_name`, and time-range filters; resolve hypothesis → cycles via `EvidenceLedger` index (spec 012).
- [ ] Implement `telemetry export --format jsonl --cycle <id>` and `--since <date>` CLIs.
- [ ] Implement corrupted-line skipping in export readers with `factory.telemetry.line_corrupted` side-log.
- [ ] (Skeleton-level) Specify Aggregator state file + metrics output schema; implementation deferred.
- [ ] Update the canonical module template in `ARCHITECTURE.md` §3 to require `events.py` alongside `api.py`, `cli.py`, `tests/`, and `README.md`.
- [ ] Write `tests/test_telemetry_typical_usage.py` and the five other test files in §7.
- [ ] Write `docs/runbooks/telemetry-export.md`.
- [ ] Write `factory/telemetry/README.md` (≤ 1 page; mock-mode example).
- [ ] Verify `mypy --strict factory/telemetry/` passes.
- [ ] Verify `python -m factory.telemetry tail --cycle <id> --mock-mode` works on a fresh checkout.
