# Runbook: Budget Tuning

> What this covers: inspecting current per-hypothesis / per-day / aggregate caps, reading the per-module cost breakdown, adjusting caps before a long autonomous run, investigating cost overruns after a run, distinguishing the **expected** `BudgetExhausted` (routes a single hypothesis to `intractable`) from the **alarm** `AggregateCapTriggered` (halts the whole program), and configuring per-gate timeout caps that bound spend indirectly. · When to use: before a multi-day autonomous run, during an unexplained cost spike, when a hypothesis terminates `intractable` for budget reasons that the operator wants to revisit, or when raising the aggregate kill switch after a deliberate halt. · Estimated time: 10–20 minutes for a routine tuning pass; 30–60 minutes for a cost-overrun postmortem.

---

## 1. Prerequisites

- **Factory state machine quiescent (or in a known state).** Raising caps mid-cycle is supported (`BudgetTracker` re-reads on the next `check_and_deduct`), but the safest pattern is to set caps between cycles or while the factory is paused. Check current state with `factory status`.
- **Read access to `config/budget.yaml`.** The canonical defaults document. Treat it as code; commit changes to git, never hand-edit on a deployed host without a corresponding repo change.
- **30-day window of historical activity for diagnostics.** The Budget Tracker flushes ledger entries to SQLite (spec 013 §5.6 + spec 012); `breakdown_by_module` aggregates over a configurable window. If the factory has been running for less than 30 days, scale the window accordingly.
- **Awareness of the three-tier check order.** Per spec 013 §5.1, every `check_and_deduct` evaluates **aggregate kill switch → aggregate dollar cap → per-day caps → per-hypothesis caps**, in that order. The *first* failing tier wins; raising a downstream cap will not unblock an upstream cap.
- **Awareness of the cost-source matrix** (spec 013 §5.3): LLM cost comes from vendor-reported usage; container build cost comes from the Catalog manifest's `cost_estimate_usd`; simulator runs come from `fidelity_ladder[].cost_estimate_usd` scaled by realized wall-clock; sandbox execution uses a constant per-iteration overhead. If any cost source is misattributed you cannot tune meaningfully — fix attribution first.
- **`runs/_control/events/` writable.** `budget set` / `budget set-cap` operations append a `FactoryControlEvent` for audit (spec 015 §5.1).

---

## 2. Steps

### 2.1 Snapshot the current caps

```
factory budget show
```

Default text format prints (per spec 013 §3 surface):

```
PROGRAM
  aggregate_dollar_cap           : $500.00      halt_active=false
  aggregate_kill_switch_enabled  : true

DAY (window 2026-05-23T00:00:00Z → 2026-05-24T00:00:00Z)
  dollars                        : $0.00 / $100.00
  tokens                         : 0 / 10,000,000
  wall_clock_seconds             : 0 / 86,400

PER-HYPOTHESIS (defaults)
  dollars                        : $20.00
  tokens                         : 2,000,000
  wall_clock_seconds             : 7,200
  iterations                     : 10

FLUSH
  interval_seconds               : 30
  max_unflushed_entries          : 100

RESERVATION
  ttl_seconds                    : 300
```

Useful flags:

- `factory budget show --format json` — machine-readable, suitable for piping into `jq`.
- `factory budget show --hypothesis-id <id>` — replaces the per-hypothesis defaults section with the specific hypothesis's current envelope and remaining headroom on all four surfaces.

If `halt_active=true`, see Step 2.8 (clearing the aggregate halt) before continuing.

### 2.2 Read the last-30-days cost breakdown

```
python -m factory.budget breakdown --window 30d --format text
```

The breakdown is computed by `BudgetTracker.breakdown_by_module` (spec 013 §5.6) — a SQL aggregation over the flushed ledger merged with in-memory unflushed entries. Output groups dollars by module:

```
COST BREAKDOWN  (window 2026-04-23T00:00:00Z → 2026-05-23T00:00:00Z)
  council            $324.12   62.4%
  surrogate           $61.40   11.8%
  genver              $52.20   10.0%
  catalog            $44.85    8.6%
  validation         $24.18    4.7%
  literature         $9.80     1.9%
  writer             $3.10     0.6%
  ----------------------------------
  TOTAL             $519.65   100.0%
```

How to read the bar:

- **Council dominance (>60%) is the normal Phase A profile.** Three-stage deliberation runs four models per stage; a single G2 worthiness gate costs $0.05–$0.50 per call. If council is below 30% you are either pre-G2 (no cycles completing) or the council is short-circuiting (mock mode somewhere it should not be).
- **Surrogate share rising > 25%** usually means OOD escalations are kicking many candidates straight to oracle (spec 013 doesn't bill oracle through `surrogate` — it bills through `validation`/`genver`; if surrogate itself is high, the OOD detector is being called too often, possibly due to mis-calibration).
- **`genver` share rising > 20%** indicates many generator-verifier iterations per hypothesis; check the `record_iteration` counts via `factory budget show --hypothesis-id <id>` for any recent intractable terminations.
- **`catalog` share rising > 15%** means container builds dominate; rare in steady state, common while onboarding new simulators.
- **`literature` should be < 5% in steady state.** Phase 0 discovery is bounded; high values mean either OpenAlex traversals are bleeding into mid-cycle or `discover` is being called manually.
- **`writer` should be < 2%.** It only runs at G5; high values mean RunReport drafting is being retried.

If any module's share looks anomalous, drill in by hypothesis:

```
python -m factory.budget breakdown --window 30d --by-hypothesis --top 10
```

This output ([TBD-impl] — `--by-hypothesis` flag not yet enumerated in spec 013 §3 CLI subcommands; the underlying `BudgetTracker.breakdown_by_module` aggregation is documented in §5.6) lists the 10 hypotheses with highest dollar spend. A single hypothesis above 5% of the 30-day total is a runaway candidate worth force-terminating.

### 2.3 Tune the per-hypothesis cap

Open `config/budget.yaml` and adjust `default_hypothesis`:

```yaml
default_hypothesis:
  dollars: 20.00          # raise if many cycles terminate intractable on dollars
  tokens: 2_000_000       # raise if token cap fires before dollar cap
  wall_clock_seconds: 7_200
  iterations: 10          # raise if genver loop runs out before reaching G3
```

Guidance:

- **Default $20/hypothesis** is calibrated for a single Phase A cycle that touches G2 (one council deliberation), G3 (one surrogate inference), and G4 with cross-simulator check on a small problem. If your domain runs longer simulations, scale `dollars` and `wall_clock_seconds` together — they tend to be correlated.
- **`iterations` is the generator-verifier cap**, enforced by spec 008 via `BudgetTracker.record_iteration`. The default 10 is a hard ceiling per spec 003 §7 (factory-layer enforcement). Raising above 15 erodes the rollback discipline that protects against runaway code-gen.
- **Per-hypothesis override**: when a single hypothesis legitimately needs more headroom, do **not** raise the default. Instead allocate it explicitly when opening:
  ```
  python -m factory.budget set-cap --hypothesis-id <hypothesis-id> --dollars 50 --tokens 5_000_000
  ```
  ([TBD-impl] — `--hypothesis-id` parameter on `set-cap` not yet enumerated in spec 013 §3 CLI surface; the underlying API is `BudgetTracker.open_hypothesis(caps=HypothesisCaps(...))` per spec 013 §3 and FIX_PLAN §6.5.) This preserves the default for the rest of the run.

After editing the YAML, reload and confirm:

```
python -m factory.budget set-cap --reload-config
factory budget show
```

The reload is hot (`BudgetTracker.__init__` re-reads on the next process boundary; the running tracker re-reads on `set --reload-config`). New caps apply to newly opened hypotheses; in-flight hypotheses keep their original allocation per spec 013 §5.1's "envelope at open time" semantics.

### 2.4 Tune the per-day cap

The per-day rolling window resets at UTC 00:00 (spec 013 §5.4). Per-day caps protect against a single bad day even when per-hypothesis caps are individually fine.

In `config/budget.yaml`:

```yaml
day:
  dollars: 100.00         # default ≈ 5 hypotheses at default per-hypothesis cap
  tokens: 10_000_000
  wall_clock_seconds: 86_400  # full day — usually the binding ceiling for total throughput
```

Decision rules:

- **Want N hypotheses per day**: set `dollars ≥ N × default_hypothesis.dollars × 1.2` (the 1.2 is slack for council retries, validation refinement, and the program-level overhead of `literature` + `writer`).
- **Limited by GPU wall clock**: when validation oracles dominate (G4 with cross-simulator), `wall_clock_seconds` becomes the binding cap before dollars. The default 86,400 s (24 h) effectively disables it; lower it (e.g., to 8 × 3600 = 28,800 s) to enforce explicit "no more than 8 GPU-hours/day" budgets.
- **Tokens cap** is mostly a sanity check; the dollar cap kicks in first in normal operation. Raise it proportionally with dollars if you see `BudgetExhausted(surface='tokens')` instead of dollars.

Reset the day window only if you have just adjusted caps mid-day and want the new caps to apply *from now* rather than from the last UTC midnight:

```
python -m factory.budget reset-day --confirm
```

`reset-day` requires `--confirm` because it can mask overspending; use sparingly.

### 2.5 Set the aggregate kill switch

The aggregate cap is the **single largest defense** against the cost-escalation failure mode (SPEC.md §10.7). Spec 013 §5.5: when breached it sets `_program_halted = True`, writes `runs/_control/HALT_AGGREGATE_CAP`, the state machine polls between cycles, and all in-flight cycles complete their current operation and abort.

To set:

```
factory budget set --aggregate-usd 2000
```

This writes the new value into `config/budget.yaml: program.aggregate_dollar_cap` and emits a `FactoryControlEvent` (spec 015 §5.1). It does **not** clear an existing halt — see Step 2.8.

Guidance:

- **Default $1000.** Sized for the Phase A 90-day MVP (PRD-001) with substantial slack. A single 90-day cycle of nominal operation costs ≈$500 by the budgeting model; the default doubles that ceiling.
- **Phase B target $5000–$10000.** Once Catalog grows to ~30 entries and cross-sim becomes routine, the per-cycle floor rises. Confirm with a 30-day breakdown before raising.
- **Never disable the kill switch unattended.** Setting `aggregate_kill_switch_enabled: false` is a foot-gun. The only legitimate use is short-window debugging on a fresh checkout with no live cost paths active. Re-enable in the same session.

### 2.6 Configure per-gate timeout caps that affect spend

Per-gate timeouts (spec 003 §8 — see also FIX_PLAN §19.4 cross-reference correction) bound spend indirectly: a runaway gate cannot accumulate cost forever because the orchestrator will raise `GateTimeoutError` and route to `intractable`. Tuning these caps is a complementary lever to dollar caps.

The defaults are:

| Gate | Default `timeout_seconds` | Typical max cost per gate |
| :--- | ---: | ---: |
| G0, G1, G1.5 | 5 | < $0.01 (no LLM, no sim) |
| G2 (worthiness) | 120 | ≈ $0.30 (4 models × 3 stages) |
| G2.5 (tractability dry-run) | 300 | ≈ $0.50 (sandboxed solver, no real sim) |
| G3 (surrogate + OOD) | 600 | ≈ $0.10 (surrogate inference) |
| G4 (validation portfolio) | 3,600 | $2–$20 (oracle simulator + cross-sim) |
| G5 (interpretation + peer review) | 240 | ≈ $0.20 (C3 + C4 councils) |
| G6 (human) | unbounded | $0 (no LLM in human gate) |

To override for a specific gate, edit `config/state_machine/gates/<gate-id>.yaml`:

```yaml
gate: G4
timeout_seconds: 7200       # raise from 3600 for expensive cross-simulator validation
implementing_module: factory.validation
required_artifacts: [ExperimentSpec, GenVerOutput]
output_artifact: ValidationReport
```

Be deliberate: raising G4 from 3,600 s to 7,200 s doubles the maximum per-cycle wall-clock floor of the most expensive gate. Combine with a proportional review of `day.wall_clock_seconds` and `default_hypothesis.wall_clock_seconds` so the new timeout actually fits inside the dollar caps.

### 2.7 Cost-per-component diagnostic walkthrough

When the 30-day breakdown shows an anomaly, walk it from biggest module down:

1. **Identify the leader.** Module with the largest share of the 30-day spend.

2. **Stratify by hypothesis.**
   ```
   python -m factory.budget breakdown --window 30d --by-hypothesis --module <leader>
   ```
   Look for a long-tail vs. a single-hypothesis dominator. Long tail = systemic; single dominator = one-off.

3. **Cross-reference with terminal status.** For each top-spending hypothesis, run:
   ```
   factory inspect <hypothesis-id>
   ```
   Note the terminal (`passed`, `falsified`, `intractable`, `inconclusive`). Spending heavily on `intractable` hypotheses means budget is being burned on dead-end designs; raise the per-hypothesis cap and you make this worse, not better. The right response is **upstream filtering** at G1 or G2 (more aggressive falsifiability check or stricter worthiness threshold), not a budget increase.

4. **Pull council session transcripts** (if the leader is `council`):
   ```
   ls runs/<cycle-id>/councils/
   ```
   Spec 014 telemetry records `cost_usd` per model call. Identify the most expensive model in the lineup; if one model is a 5× outlier, the lineup is heterogeneous *in cost* not just in capability — consider swapping that model in `config/council/lineup.yaml`.

5. **Reconcile any `BudgetTokenUsageMissing` rows.** These (spec 013 §5.3 — formerly named `BudgetUnknownCost` per FIX_PLAN §6.4) record token usage but $0 cost; they should be rare. Pull them with:
   ```
   python -m factory.budget breakdown --window 30d --include-unknown-cost
   ```
   If a vendor consistently fails to report usage, the council client for that vendor has a bug — file against spec 001's heterogeneous-model client.

### 2.8 Clear the aggregate halt after a deliberate raise

Once the kill switch has tripped, `runs/_control/HALT_AGGREGATE_CAP` exists. Subsequent `factory start` invocations refuse to begin new cycles. To resume:

```
python -m factory.budget clear-halt --raise-aggregate-usd 2000
```

This:
1. Updates `program.aggregate_dollar_cap` to the new value in `config/budget.yaml`.
2. Calls `BudgetTracker.halt_program` with `clear=true` (internally) to reset `_program_halted = False`.
3. Removes `runs/_control/HALT_AGGREGATE_CAP`.
4. Emits a `FactoryControlEvent` with the new cap and the actor.

Use `clear-halt` **only after** you have:
- Identified the cause of the halt via Steps 2.2 and 2.7.
- Confirmed the actual aggregate spend (`factory budget show` → `aggregate.running`) plus expected next-cycle spend remains below the new cap.
- Documented the rationale in the operator log (`--reason "<text>"` accepted by `clear-halt`).

If you cannot identify a cause, **do not raise the cap**. The kill switch is doing its job; the proper response is `factory stop`, then a postmortem.

### 2.9 Configure caps for a planned long-autonomous run

Before kicking off a 7-day autonomous run, pre-size every cap deliberately:

```
factory budget set \
  --aggregate-usd $(( N_cycles_expected * cost_per_cycle * 2 )) \
  --daily-usd $(( cost_per_cycle * cycles_per_day * 1.2 )) \
  --per-hypothesis-usd 25
# Iterations + token caps are set via the per-module CLI:
python -m factory.budget set-cap --per-hypothesis-tokens 2_500_000 --per-hypothesis-iterations 10
```

Then sanity-check:

```
factory budget show
python -m factory.budget simulate --hypotheses 50 --avg-cost 8 --variance 4
```

`simulate` ([TBD-impl] — spec 013 §3 lists `simulate` as a CLI subcommand but does not yet enumerate flags) projects total spend, daily distribution, and probability of aggregate cap breach given a synthetic hypothesis arrival distribution. Use it to validate that your cap set fits the planned scope.

After kickoff, monitor with periodic `factory budget show` and `python -m factory.budget breakdown --window 1d`. Re-tune mid-run only if a single module's share deviates from the 30-day baseline by more than 2×.

---

## 3. Verification

After any tuning step, confirm the change took effect and nothing else regressed.

1. **Show reflects the change.**
   ```
   factory budget show
   ```
   Inspect the relevant section (PROGRAM / DAY / PER-HYPOTHESIS). Numbers match what you set.

2. **`FactoryControlEvent` was written.**
   ```
   ls -lt runs/_control/events/ | head -5
   ```
   The most recent entry should be a `budget_set` event with the new arguments and your actor identity.

3. **Halt sentinel state matches intent.** If you cleared the halt:
   ```
   test -f runs/_control/HALT_AGGREGATE_CAP && echo "STILL HALTED" || echo "CLEAR"
   ```
   Should print `CLEAR`. If `STILL HALTED`, the file removal failed (permissions, race) — remove manually after confirming no live cycle is mid-write.

4. **Reload event in telemetry.** Spec 014 emits `factory.budget.config_reloaded` after `set-cap --reload-config`. Tail telemetry:
   ```
   python -m factory.telemetry tail --module budget --since 1m
   ```
   ([TBD-impl] — `telemetry tail` subcommand not yet enumerated in spec 014; per-module CLI form is the documented path.) If telemetry shows no reload event but `show` already reflects the change, you raised caps without telemetry's knowledge; the cost-per-component bar in the UI will lag until the next periodic flush.

5. **Mock-mode smoke test.**
   ```
   factory budget show --mock-mode
   python -m factory.budget breakdown --window 7d --mock-mode
   ```
   Both should return fixture data; if either errors, the CLI surface itself is broken (not your tuning).

6. **Optional: low-cost dry-run cycle.**
   ```
   factory start --seed mock-hypothesis --cycles 1
   ```
   Confirms the new caps do not immediately route every cycle to `intractable` due to an over-tight setting.

---

## 4. Troubleshooting

| Symptom | Likely cause | Action |
| :--- | :--- | :--- |
| `BudgetExhausted(tier='hypothesis')` on a hypothesis that should fit | Per-hypothesis cap was lowered after this hypothesis opened; the envelope at-open-time is what binds. | Per spec 013 §5.1, the cap is captured at `open_hypothesis`. Either (a) let the hypothesis terminate intractable and re-litigate after raising the cap, or (b) explicitly reopen with the new cap via `python -m factory.budget set-cap --hypothesis-id <id> --dollars X` [TBD-impl]. |
| `BudgetExhausted(tier='day')` halts new hypotheses but in-flight ones continue | Working as designed (spec 013 §6). Per-day cap pauses *intake*; in-flight cycles complete their current operation. | Wait for UTC midnight, or use `python -m factory.budget reset-day --confirm` if you have *just* raised the day cap and want it applied immediately. |
| `AggregateCapTriggered` fires very early in a run | Aggregate cap is too tight for the planned scope; or a single hypothesis has already burned most of the budget. | Step 2.7 walk-through. Identify the runaway; force-terminate it (see state-machine-debugging runbook) before raising aggregate. |
| `BudgetTokenUsageMissing` raised for every council call | Vendor adapter is not parsing the usage block (e.g., vendor changed their response schema). Per FIX_PLAN §6.4 this error class was renamed from `BudgetUnknownCost`. | Inspect the council module's vendor client for the affected provider. Until fixed, `BudgetTokenUsageMissing` rows accumulate but do not count against the dollar cap — risk of silent overspending. Treat as a P1 bug. |
| `BudgetLedgerCorrupted` at startup | Checksum mismatch in the `budget_ledger` table (spec 013 §6). Disk corruption or partial write. | Spec 013: refuse to start; restore from last flush via `python -m factory.budget restore --from <backup>` [TBD-impl]. If no backup exists, halt and require operator intervention. The aggregate spend total is now unknown; do not silently zero it. |
| Breakdown total doesn't match `aggregate.running` in `show` | Unflushed in-memory entries plus a recent crash; the in-memory tracker has entries the ledger lost. | Run `python -m factory.budget flush --force` [TBD-impl] to drain the in-memory ledger. If totals still disagree, restore from a known good ledger backup. |
| `reservation expired` events flooding telemetry | Reservation TTL (default 300 s) is shorter than the actual operation duration. | Either raise `reservation.ttl_seconds` in `config/budget.yaml`, or fix the calling module to commit/cancel more aggressively (a reservation should always pair with a try/finally — spec 013 §5.2). |
| `factory budget set --aggregate-usd 0` raises an error | Treating 0 as "disable" is forbidden; aggregate cap must be > 0 or the kill switch is meaningless. | Pass an explicit large value (`999999`) if you genuinely want a no-op cap. Better: set `program.aggregate_kill_switch_enabled: false` for a defined short window. |
| Running totals stop incrementing despite live LLM calls | The flush schedule has stalled; in-memory totals are still rising but ledger is stale. | Inspect `factory.budget` thread/lock health. Lock contention is rare in Phase A (single-cycle), so a stall usually means the persistence layer (spec 012 ledger) is wedged — see ledger-audit runbook. |
| `set-cap --hypothesis-id` after the hypothesis already passed an expensive gate | Caps are *envelopes*; raising mid-cycle does not refund spent dollars. | The new cap takes effect for the **remaining** operations in the cycle. If the cycle has already consumed > new_cap, the next `check_and_deduct` will fire `BudgetExhausted` immediately. |
| Cost-per-component bar shows `unknown` as 30%+ | Many `BudgetTokenUsageMissing` rows from a vendor that does not report usage; the bar attributes them to `unknown` rather than silently zeroing them. | Diagnose the vendor adapter (see row 4 of this table). Until fixed, accept the unknown bucket as a transparency feature — it shows operators that the budget tracker knows it does not know. |

---

## 5. Related

- **Spec 013 — Budget Tracker** (`docs/specs/013-budget-tracker.md`): canonical interface, three-tier check semantics, cost-source matrix, reservation lifecycle, kill-switch behaviour. The single source of truth for everything in this runbook.
- **Spec 003 — Gate State Machine** (`docs/specs/003-state-machine.md`): explains the auto-routing of `BudgetExhausted → terminate_intractable` (§6 Failure Modes) and the per-gate timeout defaults referenced in Step 2.6. See `runbooks/state-machine-debugging.md` for hung-gate investigation that may be a budget question in disguise.
- **Spec 012 — Evidence Ledger** (`docs/specs/012-evidence-ledger.md`): the persistence backend the budget tracker flushes into. Ledger corruption surfaces here as `BudgetLedgerCorrupted` at startup. See `runbooks/ledger-audit.md` for the recovery flow.
- **Spec 001 — Council Library** (`docs/specs/001-council.md`): owner of the vendor cost-passthrough that feeds the budget tracker; the right place to file `BudgetTokenUsageMissing` regressions (formerly `BudgetUnknownCost` per FIX_PLAN §6.4).
- **Spec 014 — Telemetry & Audit** (`docs/specs/014-telemetry-audit.md`): the structured event stream `factory.budget.record`, `factory.budget.exhausted`, `factory.budget.day_reset`, `factory.budget.config_reloaded`. Operators tune off the breakdown that telemetry composes.
- **SPEC.md §10.7** (cost escalation): the failure mode this runbook defends against. Re-read when arguing about raising the aggregate cap.
