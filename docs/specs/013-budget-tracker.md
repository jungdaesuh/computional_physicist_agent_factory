# Spec 013: Budget Tracker

> Status: ☐ not started · Owner: TBD · Last updated: 2026-05-23

## CONTEXT (60-second summary — read first)
- The **Budget Tracker** is the factory's cost governor. **Three** tiers of caps are enforced: per-`HypothesisSpec`, per-day (rolling UTC window), and per-program aggregate (hard kill switch). There is **no `per_cycle` tier** — in Phase A one cycle equals one hypothesis traversal.
- The 5 facts: (1) every cost-incurring operation calls `tracker.record(...)` *after* the operation completes — never estimate-and-commit; (2) per-hypothesis caps are checked *before* expensive operations (G3 surrogate, G4 oracle, council deliberation) via `tracker.check_and_deduct(...)`; (3) aggregate program cap defaults to $1000 and is a hard halt — operator paged, sentinel written to `runs/_control/HALT_AGGREGATE_CAP`, no silent bypass; (4) daily caps reset at UTC midnight; (5) `BudgetExhausted` is routed by spec 003 state machine to the `intractable` terminal.
- Open first: `factory/budget/api.py` and the typical-usage test.

## ENTRY POINTS
- Main module: `factory/budget/api.py`
- Typical-usage test: `factory/budget/tests/test_budget_typical_usage.py`
- Per-module CLI: `python -m factory.budget --help` (subcommands: `show`, `breakdown`, `set-cap`, `reset-day`, `simulate`, `clear-halt`)
- Operator CLI (spec 015 — preferred for normal operations): `factory budget show`, `factory budget set --aggregate-usd USD [--per-hypothesis-usd USD] [--daily-usd USD]`. Both surfaces invoke the same `BudgetTracker.set_cap(...)` underneath.
- Mock-mode example: `python -m factory.budget show --hypothesis-id H-001 --mock-mode`
- Runbook: `docs/runbooks/budget-tuning.md`

## LOCAL DEBUG
- Instantiate without persistence: `BudgetTracker(persistence=None)` runs in-memory only; useful for unit tests.
- Mock-mode fills ledger with fixture entries: `BudgetTracker.from_fixture("typical_run")`.
- Common error signatures → recovery:
  - `BudgetExhausted` → operation would breach a cap; state machine routes hypothesis to `intractable` terminal. Not an emergency.
  - `AggregateCapTriggered` → program-wide kill switch fired; ALL cycles halt; operator must explicitly raise cap and clear the halt sentinel at `runs/_control/HALT_AGGREGATE_CAP`.
  - `BudgetTokenUsageMissing` → OpenRouter response lacked the `usage` block (`prompt_tokens` + `completion_tokens`); the factory cannot compute USD without token counts. Operator is paged; the call is parked until reconciliation.
  - `BudgetLedgerCorrupted` → ledger checksum mismatch on load; restore from last flush or abort startup.
- Logs to inspect: every `record()` emits `factory.budget.record`; every cap breach emits `factory.budget.cap_exhausted`; aggregate trip emits `factory.budget.aggregate_halt`. Filter `runs/<cycle-id>/cycle.jsonl` by `module=budget`.

## DEPENDENCIES
- **Hard:** Spec 002 (artifacts) — reads/writes `Budget` + `BudgetLedgerEntry`. Spec 001 (Council library) — computes USD from token counts via the single OpenRouter pricing table at `config/pricing/openrouter.yaml` (FIX_PLAN §25.6) and calls `tracker.record(cost_usd=...)`; the Budget Tracker never looks up prices itself.
- **Soft:** Spec 004 (catalog) — non-LLM operations use Catalog cost metadata (`cost_estimate_usd` per fidelity tier) combined with telemetry-reported wall clock. Spec 014 (telemetry) — emits structured cost events if available.
- **Persistence:** Phase A runs **JSON-only** — `runs/_budget/state.json` (current caps + running totals) and `runs/_budget/ledger.jsonl` (append-only ledger entries). The Budget Tracker does **not** write to the EvidenceLedger SQLite store in Phase A; spec 012 owns the SQLite store and is intentionally decoupled. Phase B will add an optional SQLite mirror for analytics.
- **Mocks available:** `BudgetTracker.mock_caps()` returns a relaxed cap set safe for tests. `MockCostProvider` provides synthetic OpenRouter-flavored cost reports against the single pricing table (covers all five §25.3 model IDs).

---

## 1. Summary

The Budget Tracker is the **only** authority on whether the factory may spend more money, tokens, wall-clock time, or generator-verifier iterations. It exposes a tight contract: record actual cost after every operation, check-and-deduct before any expensive operation, and fail loud when a cap is breached. It owns the in-memory running ledger, the JSON state + ledger files, the daily reset clock, and the aggregate kill switch that halts every cycle when triggered.

## 2. Scope

**In scope:**
- Three-tier cap enforcement: `per_hypothesis`, `per_day`, `aggregate`. No `per_cycle` tier.
- Four tracking surfaces: dollars (USD), tokens (LLM only), wall-clock seconds, generator-verifier iterations.
- Real-time ledger: `record()` after each operation; running totals updated in-memory.
- JSON persistence: `runs/_budget/state.json` snapshot (debounced) + `runs/_budget/ledger.jsonl` append-only (every entry).
- Proactive `check_and_deduct(...)` for G3 surrogate calls, G4 oracle calls, council deliberations, container builds.
- Per-day rolling window with reset at UTC 00:00.
- Aggregate program kill switch (default $1000, configurable in `config/budget.yaml`); halt sentinel at `runs/_control/HALT_AGGREGATE_CAP`.
- Cost attribution by module for telemetry (Settings panel cost-per-component bar).
- Per-module CLI subcommands: `show`, `breakdown`, `set-cap`, `reset-day`, `simulate`, `clear-halt`.
- Mock mode + fixtures for offline tests.

**Out of scope:**
- Per-call LLM cost computation (OpenRouter returns tokens in the `usage` block; the Council library (spec 001) computes USD via the single pricing table at `config/pricing/openrouter.yaml` and passes USD to `record(cost_usd=...)`).
- Forecasting future spend (Phase B; current spec is purely actuarial).
- Multi-tenant cost isolation (Phase C; current factory is single-program).
- UI rendering (spec 015 reads breakdown via HTTP; UI is out of scope here).
- SQLite persistence (Phase B; Phase A is JSON-only).

## 3. Public Interface

```python
# factory/budget/api.py

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from factory.artifacts import (
    Budget, BudgetLedgerEntry, HypothesisId, ArtifactHash,
)

class BudgetError(FactoryError): ...
class BudgetExhausted(BudgetError):
    """Per-hypothesis or per-day cap breached. State machine routes to `intractable`."""
    tier: Literal["hypothesis", "day"]
    surface: Literal["dollars", "tokens", "wall_clock", "iterations"]
    requested: float
    remaining: float

class AggregateCapTriggered(BudgetError):
    """Program-wide hard halt. Operator must explicitly raise cap and clear the
    halt sentinel at runs/_control/HALT_AGGREGATE_CAP to resume."""

class BudgetTokenUsageMissing(BudgetError):
    """OpenRouter response lacked the `usage` block (`prompt_tokens` +
    `completion_tokens`). The factory cannot compute USD without token counts."""
    module: str
    model_id: str        # OpenRouter vendor-prefixed ID, e.g. "google/gemini-3.5-flash"
                         # or any of the 4 council models in FIX_PLAN §25.3.
    description: str

class BudgetLedgerCorrupted(BudgetError):
    """Ledger checksum mismatch on load."""

@dataclass(frozen=True)
class HypothesisCaps:
    """Per-hypothesis envelope. `iterations` is only valid at this tier."""
    dollars: float
    tokens: int
    wall_clock_seconds: float
    iterations: int

@dataclass(frozen=True)
class TimeWindowCaps:
    """Per-day and aggregate caps. No `iterations` field — iteration counting is
    only meaningful per-hypothesis."""
    dollars: float
    tokens: int
    wall_clock_seconds: float

@dataclass(frozen=True)
class RemainingBudget:
    hypothesis: HypothesisCaps
    day: TimeWindowCaps
    aggregate: TimeWindowCaps

@dataclass(frozen=True)
class CostBreakdown:
    window: tuple[datetime, datetime]
    by_module: dict[str, float]     # module name → dollars
    total_usd: float

class BudgetTracker:
    """Single authority for cost enforcement across the factory."""

    def __init__(
        self,
        config_path: Path = Path("config/budget.yaml"),
        state_path: Path = Path("runs/_budget/state.json"),
        ledger_path: Path = Path("runs/_budget/ledger.jsonl"),
        clock: "Clock | None" = None,        # injectable for testing
        mock_mode: bool = False,
    ) -> None: ...

    def open_hypothesis(
        self,
        hypothesis_id: HypothesisId,
        caps: HypothesisCaps,
    ) -> Budget:
        """Allocate a per-hypothesis envelope. Returns the initial Budget artifact."""

    def check_and_deduct(
        self,
        hypothesis_id: HypothesisId,
        module: str,
        estimated_cost_usd: float,
        estimated_tokens: int = 0,
        estimated_wall_clock_seconds: float = 0.0,
        estimated_iterations: int = 0,
        description: str = "",
    ) -> "Reservation":
        """Proactive check: would this operation breach any cap? If yes, raise BudgetExhausted.
        If no, reserve the estimated cost against all three tiers and return a Reservation.
        Caller MUST call reservation.commit(actual=...) or reservation.cancel() before exit.
        """

    def record(
        self,
        hypothesis_id: HypothesisId,
        module: str,
        cost_usd: float,
        tokens: int,
        wall_clock_seconds: float,
        description: str,
        reservation: "Reservation | None" = None,
    ) -> BudgetLedgerEntry:
        """Canonical record-after-commit entry point. **No `record_entry` alias exists.**
        Records actual cost after operation completes. If a reservation was held, this
        commits the actual numbers and releases the reserved estimate. Updates per-hypothesis,
        per-day, and aggregate running totals. Appends to `runs/_budget/ledger.jsonl` and
        debounces a snapshot to `runs/_budget/state.json`.
        Raises AggregateCapTriggered if the actual cost pushes the program over the kill switch.
        """

    def record_iteration(
        self,
        hypothesis_id: HypothesisId,
        module: str = "genver",
    ) -> None:
        """Increment iteration counter for the generator-verifier loop (spec 008).
        Raises BudgetExhausted(tier='hypothesis', surface='iterations') on overflow.
        Iteration counting only exists at the per-hypothesis tier."""

    def remaining(self, hypothesis_id: HypothesisId) -> RemainingBudget:
        """Snapshot of remaining headroom on all three tiers."""

    def set_cap(
        self,
        *,
        aggregate_usd: float | None = None,
        daily_usd: float | None = None,
        per_hypothesis_usd: float | None = None,
        hypothesis_id: HypothesisId | None = None,
        clear_halt: bool = False,
    ) -> None:
        """Single setter underneath both CLI surfaces. The operator CLI
        (`factory budget set`, spec 015) and the per-module CLI
        (`python -m factory.budget set-cap`, this spec) both invoke this method."""

    def breakdown_by_module(
        self,
        window: tuple[datetime, datetime] | None = None,
    ) -> CostBreakdown:
        """Cost attribution by module over a time window. Default window = since program start."""

    def close_hypothesis(
        self,
        hypothesis_id: HypothesisId,
        terminal_status: Literal["passed", "falsified", "intractable", "inconclusive"],
    ) -> Budget:
        """Finalize the Budget artifact for this hypothesis. The returned artifact is immutable
        and is persisted via spec 012 alongside the EvidenceLedgerEntry."""

    def halt_program(self, reason: str) -> None:
        """Trip the aggregate kill switch. Writes the sentinel file
        `runs/_control/HALT_AGGREGATE_CAP` and flips the in-process flag.
        All check_and_deduct calls subsequently raise AggregateCapTriggered
        until an operator clears the halt via `set_cap(clear_halt=True)`
        (or the equivalent CLI invocation)."""

@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    hypothesis_id: HypothesisId
    module: str
    estimated_cost_usd: float
    estimated_tokens: int
    expires_at: datetime
    def commit(self, *, actual_cost_usd: float, actual_tokens: int, wall_clock_seconds: float) -> None: ...
    def cancel(self) -> None: ...
```

## 4. Data Structures / Schemas

`Budget` and `BudgetLedgerEntry` are defined in spec 002 — this module produces them, never invents new shapes. Module-local types (`HypothesisCaps`, `TimeWindowCaps`, `RemainingBudget`, `CostBreakdown`, `Reservation`) live in `factory/budget/types.py`.

### 4.1 Configuration (`config/budget.yaml`)

```yaml
program:
  aggregate_dollar_cap: 1000.00
  aggregate_kill_switch_enabled: true
day:
  dollars: 100.00
  tokens: 10_000_000
  wall_clock_seconds: 86_400
default_hypothesis:
  dollars: 50.00          # matches PRD-001 §4 per-hypothesis acceptance ceiling
  tokens: 2_000_000
  wall_clock_seconds: 7_200
  iterations: 10
flush:
  state_debounce_seconds: 5    # state.json snapshot debounce
ledger:
  fsync_every_n_entries: 1     # ledger.jsonl is append-only and fsynced on every record
reservation:
  ttl_seconds: 300
```

The `default_hypothesis.dollars` of **$50** is the Phase A acceptance ceiling defined in PRD-001 §4. Operators may lower the per-hypothesis cap locally via `factory budget set --per-hypothesis-usd <usd>`; they may not silently raise it above the aggregate cap.

### 4.2 Pricing table (`config/pricing/openrouter.yaml`)

Phase A (per FIX_PLAN §25) is hybrid OpenRouter: the council uses four frontier
models from four distinct vendors, and every non-council (agentic) LLM call uses
`google/gemini-3.5-flash`. All access flows through OpenRouter, so there is exactly
**one** pricing table — `config/pricing/openrouter.yaml`. The §24-era single-file
`config/pricing/gemini.yaml` is dropped. The legacy `config/pricing/<vendor>.yaml`
scheme (one table per vendor) is not used.

The Budget Tracker does **not** look up prices. The Council library (spec 001)
loads this table at startup, computes USD from the OpenRouter response's `usage`
block, and passes the resulting USD to `tracker.record(cost_usd=...)`. The schema
covers all five OpenRouter model IDs the factory may invoke (FIX_PLAN §25.3) —
four council models plus the cheap agentic default:

```yaml
# config/pricing/openrouter.yaml
# OpenRouter passthrough prices. Verify at https://openrouter.ai/models
# Updated YYYY-MM-DD by operator-during-setup.
models:
  "openai/gpt-5.5":
    input_per_1m_tokens_usd: <fill>
    output_per_1m_tokens_usd: <fill>
  "anthropic/claude-opus-4.7":
    input_per_1m_tokens_usd: <fill>
    output_per_1m_tokens_usd: <fill>
  "google/gemini-3.1":
    input_per_1m_tokens_usd: <fill>
    output_per_1m_tokens_usd: <fill>
  "x-ai/grok-4.3":
    input_per_1m_tokens_usd: <fill>
    output_per_1m_tokens_usd: <fill>
  "google/gemini-3.5-flash":
    input_per_1m_tokens_usd: <fill>
    output_per_1m_tokens_usd: <fill>
last_updated_iso: 2026-05-23
```

Required top-level fields: `models` (dict keyed by OpenRouter model ID; each value
carries `input_per_1m_tokens_usd` and `output_per_1m_tokens_usd`) and
`last_updated_iso`. Every model ID the council or agentic dispatcher may invoke
MUST appear as a key. The timestamp is required for staleness audits.

The Council library applies the canonical formula (FIX_PLAN §25.6):

```
cost_usd = (input_tokens × input_per_1m_tokens_usd / 1e6)
         + (output_tokens × output_per_1m_tokens_usd / 1e6)
```

`input_tokens` is `response.usage.prompt_tokens`; `output_tokens` is
`response.usage.completion_tokens`. If the `usage` block is absent from the
OpenRouter response, the Council library raises `BudgetTokenUsageMissing`
(re-exported from `factory.budget`) and the call is parked until the operator
reconciles. The Budget Tracker never defaults missing tokens to zero.

### 4.3 JSON persistence (Phase A)

Phase A uses two files; no SQLite write is involved.

**`runs/_budget/state.json`** — current snapshot, debounced to disk every `flush.state_debounce_seconds` (default 5 s) or on `close_hypothesis`. Schema:

```json
{
  "schema_version": 1,
  "ts": "2026-05-23T15:42:11Z",
  "halted": false,
  "halt_reason": null,
  "aggregate": {
    "cap": {"dollars": 1000.00, "tokens": 0, "wall_clock_seconds": 0},
    "used": {"dollars": 312.41, "tokens": 0, "wall_clock_seconds": 0}
  },
  "day": {
    "window_start": "2026-05-23T00:00:00Z",
    "cap": {"dollars": 100.00, "tokens": 10000000, "wall_clock_seconds": 86400},
    "used": {"dollars": 41.20, "tokens": 412000, "wall_clock_seconds": 9800}
  },
  "hypotheses": {
    "H-001": {
      "cap":  {"dollars": 50.00, "tokens": 2000000, "wall_clock_seconds": 7200, "iterations": 10},
      "used": {"dollars": 12.30, "tokens": 410000, "wall_clock_seconds": 1820, "iterations": 3}
    }
  }
}
```

**`runs/_budget/ledger.jsonl`** — append-only, one `BudgetLedgerEntry` per line, fsynced on each `record()`. Schema per line:

| field | type | notes |
| :--- | :--- | :--- |
| ledger_entry_id | string (UUID) | unique per row |
| ts | string (ISO-8601 UTC) | record timestamp |
| hypothesis_id | string or null | null for program-level entries |
| module | string | producer module name (must match a registered namespace in spec 014) |
| cost_usd | number | actual; never estimated |
| tokens | integer | actual |
| wall_clock_seconds | number | actual |
| description | string | free-form audit string |
| checksum | string (hex, 64 chars) | SHA-256 of the canonical JSON of the row excluding `checksum` itself |

On startup the tracker validates every ledger line's checksum and rebuilds the running totals; mismatch raises `BudgetLedgerCorrupted`.

## 5. Algorithms / Logic

### 5.1 Three-tier check (proactive)

`check_and_deduct` evaluates in this order; the first failing tier wins:

1. **Aggregate kill switch.** If `halt_program` was called *or* `runs/_control/HALT_AGGREGATE_CAP` exists on disk, raise `AggregateCapTriggered` immediately.
2. **Aggregate dollar cap.** If `running_aggregate_usd + estimated_cost_usd > aggregate_dollar_cap`, raise `AggregateCapTriggered` and call `halt_program(reason="aggregate_cap_reached")`. Hard halt — not a per-hypothesis failure. The halt is **never silently bypassed**.
3. **Per-day caps.** Roll forward if the current `day_window_start` is older than UTC midnight (see §5.4). For each surface (dollars, tokens, wall_clock), check `day_used + estimate > day_cap`; if any breach, raise `BudgetExhausted(tier="day", surface=...)`.
4. **Per-hypothesis caps.** Same check against the hypothesis envelope. Iteration count is only checked at this tier.

If all pass, reserve the estimate against all three tiers (the reserved amount counts toward subsequent checks within the reservation TTL) and return a `Reservation`.

### 5.2 Record-after-commit pattern

The contract is strict: cost is **recorded after the operation completes** with vendor-reported numbers. Reservations exist purely to prevent two concurrent operations from each independently passing the check and then jointly breaching the cap.

```python
res = tracker.check_and_deduct(hyp_id, "council", estimated_cost_usd=0.50, ...)
try:
    verdict = council.deliberate(...)
    res.commit(
        actual_cost_usd=verdict.total_cost_usd,
        actual_tokens=verdict.total_tokens,
        wall_clock_seconds=verdict.wall_clock_seconds,
    )
except Exception:
    res.cancel()
    raise
```

`commit` records the actual numbers via `record()` and releases the reservation. The delta between estimated and actual updates the running totals.

### 5.3 Cost source per operation kind

| Operation | Cost source |
| :--- | :--- |
| LLM call (council, gap-mining, writer, code-gen) | Council library reads OpenRouter `response.usage.prompt_tokens` + `response.usage.completion_tokens`, looks up the model ID in the single `config/pricing/openrouter.yaml` table, computes USD via `(input_tokens × input_per_1m / 1e6) + (output_tokens × output_per_1m / 1e6)` (FIX_PLAN §25.6), calls `tracker.record(cost_usd=...)`. If the `usage` block is absent → `BudgetTokenUsageMissing`, raised to operator; never silently zero. |
| Container build | Catalog entry's `cost_estimate_usd` for the smoke-test target × telemetry-reported wall-clock multiplier. |
| Simulator run (G3 surrogate / G4 oracle) | `fidelity_ladder[].cost_estimate_usd` from the `ExperimentSpec`, calibrated by `wall_clock_seconds / expected_runtime_seconds`. |
| Sandbox execution (genver) | Constant per-iteration overhead from `config/budget.yaml`; wall-clock from telemetry. |

### 5.4 Daily reset

Day window is `[utc_midnight_of_first_record, utc_midnight_of_first_record + 24h)`. When `record()` or `check_and_deduct()` runs and `now() >= day_window_end`, the day totals are zeroed and `day_window_start` advances to the latest UTC midnight ≤ `now()`. A `factory.budget.day_reset` event is emitted. This is lazy — no background thread; reset happens at the next interaction.

### 5.5 Aggregate kill switch

The aggregate cap is the only cap that **calls `halt_program()`** when breached. `halt_program` does three things atomically:

1. Sets the in-process flag `_program_halted = True`.
2. Writes the sentinel file `runs/_control/HALT_AGGREGATE_CAP` (mirroring spec 008's STOP-file polling pattern). Creating the parent directory is part of this step.
3. Emits `factory.budget.aggregate_halt` for spec 014 telemetry.

The state machine (spec 003) polls for this sentinel between cycles; all in-flight cycles complete their current operation and abort. The operator clears the halt via either CLI surface:

- Operator: `factory budget set --aggregate-usd 2000` (and pass `--clear-halt` if raising the cap should also clear the sentinel).
- Per-module: `python -m factory.budget set-cap --aggregate-usd 2000 --clear-halt`.

Both invoke `BudgetTracker.set_cap(..., clear_halt=True)`. The sentinel file is removed only by this code path; the tracker never auto-clears.

### 5.6 Breakdown for telemetry

`breakdown_by_module(window)` scans `runs/_budget/ledger.jsonl` (streaming line-by-line) plus the in-memory unflushed entries. Returns a `CostBreakdown` with `{module → dollars}` and `total_usd`. The operator UI (spec 015) reads this via the HTTP API to render the cost-per-component bar.

### 5.7 Concurrency

The factory state machine (spec 003) runs cycles serially in Phase A, but council deliberations dispatch model calls in parallel within a stage. `BudgetTracker` uses a single `threading.Lock` around the running totals and reservation table. Granularity is coarse (one lock for the whole tracker); contention is acceptable at Phase A throughput. Phase B may shard by hypothesis_id.

## 6. Failure Modes

| Error class | When it fires | Recovery action |
| :--- | :--- | :--- |
| `BudgetExhausted(tier="hypothesis")` | Per-hypothesis cap would breach | State machine (spec 003) routes the hypothesis to `intractable` terminal; `close_hypothesis` is called with `terminal_status="intractable"`. Other hypotheses continue. |
| `BudgetExhausted(tier="day")` | Per-day cap would breach | State machine pauses *new* hypothesis intake until next UTC midnight; in-flight hypotheses complete current operation and pause. |
| `AggregateCapTriggered` | Aggregate program cap breached, OR `halt_program` invoked, OR `runs/_control/HALT_AGGREGATE_CAP` already present on disk | Hard halt. All cycles stop at next operation boundary. Operator paged via spec 014 telemetry alert. Never silently bypassed. Operator clears via `factory budget set --aggregate-usd <new> --clear-halt`. |
| `BudgetTokenUsageMissing` | OpenRouter response did not include the `usage` block (no `prompt_tokens` + `completion_tokens`) | Operation is parked; entry written to ledger with `tokens=0, cost_usd=0` and `description="parked: token usage missing"`. Operator paged; manual reconciliation via `set-cap` CLI. The factory does NOT default to $0 spend silently. |
| `BudgetLedgerCorrupted` | Checksum mismatch on ledger line at startup | Refuse to start; restore from last good snapshot in `state.json`; if no snapshot exists, halt and require operator intervention. |
| `ReservationExpired` | Reservation TTL elapsed without commit/cancel | Auto-cancelled; entry logged for audit; the operation that held the reservation is presumed crashed. |

## 7. Testing

**Mock-mode unit tests** (`factory/budget/tests/`):
- `test_budget_typical_usage.py` — REQUIRED. Open hypothesis → check_and_deduct → record → close. Verify ledger entries and running totals.
- `test_three_tier_enforcement.py` — feed a sequence of records that breaches each of the three tiers (`per_hypothesis`, `per_day`, `aggregate`) individually; verify the correct exception fires and that no `per_cycle` tier exists.
- `test_aggregate_kill_switch.py` — push aggregate over cap; verify `AggregateCapTriggered`, sentinel at `runs/_control/HALT_AGGREGATE_CAP`, and that subsequent `check_and_deduct` raises immediately; verify `set_cap(clear_halt=True)` removes the sentinel and unblocks.
- `test_daily_reset.py` — inject `Clock` advancing across UTC midnight; verify day totals reset and `day_reset` event emitted.
- `test_reservation_lifecycle.py` — commit + cancel + expire paths.
- `test_token_usage_missing.py` — OpenRouter response omits the `usage` block; verify `BudgetTokenUsageMissing` raised; no silent $0; ledger entry marks the call as parked.
- `test_breakdown_by_module.py` — record entries from multiple modules; verify breakdown sums correctly.
- `test_ledger_corruption.py` — tamper with a ledger row; verify `BudgetLedgerCorrupted` on load.
- `test_json_persistence_roundtrip.py` — write entries, restart tracker, verify totals reconstructed from `state.json` + `ledger.jsonl` (no SQLite path involved).
- `test_per_hypothesis_default_is_50.py` — assert the default `HypothesisCaps.dollars` loaded from `config/budget.yaml` is $50.00 per PRD-001 §4.

**Live-mode tests** (`@pytest.mark.live`, gated):
- `test_live_council_cost_attribution.py` — single live council deliberation; verify cost recorded matches vendor invoice estimate within 10%.

## 8. Performance & Budget

- `check_and_deduct` + `record`: < 1 ms each (in-memory totals; ledger fsync amortized).
- Ledger append + fsync: < 5 ms per entry on local disk.
- State snapshot debounce: every 5 s of activity (configurable).
- `breakdown_by_module`: < 100 ms for a 10k-entry ledger (streaming scan).
- Aggregate kill switch check: O(1) flag read + O(1) sentinel file stat in hot path.
- Memory footprint: ~200 bytes per `BudgetLedgerEntry`; ledger is bounded by Phase A run length.

## 9. Open Questions

- **Reservation granularity.** A council deliberation reserves once for the whole 3-stage protocol; individual model calls inside the council are recorded as they complete. Whether to reserve per-model-call instead is an open trade-off between accuracy and lock contention.
- **Cost-rate-of-spend alarms.** Phase A only enforces hard caps. Soft alarms (e.g., "spent 80% of daily cap in 6 hours") are deferred to Phase B telemetry policy.
- **Multi-currency support.** All costs are USD. If a vendor reports in EUR, conversion is currently the council library's problem. Whether the budget should own a currency layer is unresolved.
- **Iteration cap surface — should it span the whole hypothesis or per-experiment?** Currently per-`HypothesisSpec`; spec 008 enforces it per-iteration of the generator-verifier loop. If a hypothesis spawns multiple experiments, the cap is shared, which may be too tight.
- **Phase B SQLite mirror.** Whether the JSON ledger should be mirrored to the EvidenceLedger SQLite for analytics queries; current Phase A is JSON-only by design.

## 10. TODO Checklist

- [ ] Scaffold `factory/budget/` from the canonical module template.
- [ ] Implement `HypothesisCaps`, `TimeWindowCaps`, `RemainingBudget`, `CostBreakdown`, `Reservation` types in `types.py`.
- [ ] Implement `BudgetTracker.__init__`, config loading, JSON state + ledger wiring under `runs/_budget/`.
- [ ] Implement `open_hypothesis` + `close_hypothesis` + `Budget` artifact production.
- [ ] Implement `check_and_deduct` with three-tier check order (aggregate → day → hypothesis).
- [ ] Implement `record` (canonical name — no `record_entry` alias) with vendor-cost passthrough + JSON append + fsync.
- [ ] Implement `record_iteration` for generator-verifier (per-hypothesis only).
- [ ] Implement daily-window reset (lazy, no background thread).
- [ ] Implement `halt_program` + `runs/_control/HALT_AGGREGATE_CAP` sentinel + telemetry alert hook.
- [ ] Implement `set_cap(..., clear_halt=...)` as the single setter underneath both CLI surfaces.
- [ ] Implement `breakdown_by_module` with in-memory + on-disk merge over JSON ledger.
- [ ] Implement reservation lifecycle (commit / cancel / TTL expire).
- [ ] Implement ledger checksum on write + verify on load.
- [ ] Author `config/budget.yaml` with `default_hypothesis.dollars = 50.00` and documented defaults.
- [ ] Document the single `config/pricing/openrouter.yaml` schema (FIX_PLAN §25.6) — 5-model dict covering the 4 council vendors + `google/gemini-3.5-flash`; the Council library (spec 001) is the consumer.
- [ ] Build mock mode (`BudgetTracker.mock_caps`, `MockCostProvider`).
- [ ] Write `factory/budget/cli.py` with `show`, `breakdown`, `set-cap`, `reset-day`, `simulate`, `clear-halt` subcommands; ensure `factory budget set` (spec 015) and `python -m factory.budget set-cap` both call `BudgetTracker.set_cap`.
- [ ] Rename any prior `BudgetUnknownCost` references to `BudgetTokenUsageMissing` across consumers.
- [ ] Write 10 mock-mode tests; ensure all pass in CI.
- [ ] Write `tests/test_live_council_cost_attribution.py` (live; manual gate).
- [ ] Write `factory/budget/README.md` (≤ 1 page).
- [ ] Write `docs/runbooks/budget-tuning.md` (raising caps, clearing aggregate halt, reconciling token-usage-missing entries).
- [ ] Verify `mypy --strict factory/budget/` passes.
- [ ] Verify `python -m factory.budget show --mock-mode` works on a fresh checkout.
- [ ] Wire `BudgetExhausted` into spec 003 state machine's `intractable` route.
- [ ] Wire `check_and_deduct` calls into spec 008 generator-verifier (per-iteration) and council library (per-deliberation).
