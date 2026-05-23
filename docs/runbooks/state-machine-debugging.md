# Runbook: State Machine Debugging

> What this covers: diagnosing a stuck or misrouted cycle in `factory.state_machine` — hung gates, `GateTimeoutError`, `GateRouteUndefined`, `ArtifactNotFound`, unexpected terminal states (`intractable` / `inconclusive` / `parked`), and `RouteCycleDetected` startup refusals. · When to use: a cycle has not advanced for longer than the gate's documented wall-clock budget, the orchestrator raised one of the typed `GateError` subclasses, the operator UI shows a cycle in an unexpected terminal, or replay/inspect output diverges from the persisted artifact graph. · Estimated time: 15–60 minutes for a single stuck cycle; longer if the failure traces back to a configuration bug in `gate_routes.yaml` that blocks every cycle.

---

## 1. Prerequisites

You need the following before you start. If any are missing, fix the prerequisite first — debugging without them is guessing.

- **Cycle ID.** The 7-char-or-longer identifier the state machine generated. Look for it on the UI Mission Control screen, in the `factory status` output, or in `runs/` directory listings (`ls -1 runs/ | sort`).
- **Repository checkout in dev mode.** `pip install -e .` so that `python -m factory.state_machine` resolves to the live code; otherwise replay will reuse stale wheels and you will chase a phantom bug.
- **Read access to `runs/<cycle-id>/`.** The whole runbook depends on the colocated per-cycle directory. If `runs/<cycle-id>/` is missing the cycle ID is stale, was pruned by an operator, or was never persisted (an infrastructure failure unrelated to this runbook — open a separate bug).
- **Mock-mode environment.** `FACTORY_MOCK=1` should work end-to-end. Verify with `python -m factory.state_machine run-cycle --gap-fixture sample --mock-mode` *before* using mock to test a hypothesis about live failure.
- **Per-gate timeout table.** Memorise (or print) the budget defaults from spec 003 §8:
  - G0, G1, G1.5: 5 s each.
  - G2 (council): 120 s.
  - G2.5 (dry-run): 300 s.
  - G3 (surrogate): 600 s.
  - G4 (validation portfolio): 3600 s.
  - G5 (interpretation + review): 240 s.
  - G6 (human gate): unbounded but flagged.
  Per-gate overrides live in `config/state_machine/gates/<gate-id>.yaml`. Use the value there, not the default, when judging whether a gate is hung.
- **`gate_routes.yaml`.** Open `config/state_machine/gate_routes.yaml` in a second pane; you will refer to it constantly. The route table is the single authority on "what should happen next".

If the failure is a `RouteCycleDetected` or `ImplementingModuleMissing` thrown at *startup* (no cycle directory yet), skip Step 2.1 and start at Step 2.5 (configuration triage).

---

## 2. Steps

### 2.1 Locate the cycle directory

```
ls -1 runs/ | grep <cycle-id-prefix>
```

If there is a unique match, set the variable for the rest of the steps:

```
export CYCLE=runs/<full-cycle-id>
```

Confirm the manifest exists:

```
test -f "$CYCLE/MANIFEST.json" && echo "OK" || echo "MANIFEST MISSING"
```

If the manifest is missing the cycle never completed `prepare run_dir`; the state machine crashed before any gate ran. Treat this as an infrastructure failure (not a gate bug) — inspect the parent process (e.g., `factory start` stdout) and `runs/_control/operator.jsonl` for the actual crash.

### 2.2 Snapshot the event log

The event log `cycle.jsonl` is the canonical trace of every gate transition. Pull the gate-related events into a small file so you can scan without scrolling:

```
jq -c 'select(.event | startswith("gate_"))' "$CYCLE/cycle.jsonl" > /tmp/gate_events.jsonl
wc -l /tmp/gate_events.jsonl
```

You should see paired `gate_enter` / `gate_exit` records for every completed gate, plus a single trailing `gate_enter` (no `gate_exit`) for the currently running or hung gate.

If `gate_enter` and `gate_exit` *both* exist for the last gate but no `cycle_terminal` event follows, the bug is in the post-gate transition path (artifact persistence or route lookup), not in the gate itself — jump to Step 2.6.

### 2.3 Identify the hung gate

The hung gate's signature: a `gate_enter` event whose `ts` is older than the gate's configured `timeout_seconds`, with no matching `gate_exit`.

```
jq -r 'select(.event == "gate_enter") | "\(.payload.gate)  ts=\(.ts)"' /tmp/gate_events.jsonl | tail -5
```

Compare the most recent `gate_enter` timestamp against now (`date -u +%FT%TZ`) and against the per-gate timeout. If the wall-clock since `gate_enter` exceeds the configured `timeout_seconds` by more than a small slack (≈10%), the state machine should already have raised `GateTimeoutError`. If it has not, suspect:

- A long-running subprocess that never returned control (G2.5 dry-run, G3 surrogate fit, G4 oracle). Check Step 2.4.
- The state machine's timeout enforcement was bypassed (a sync call without watchdog wrapping). This is a code bug, not an operational one.

#### How long is "actually hung" vs "slow"?

| Gate | Typical p50 (mock) | Typical p95 (live) | Treat as hung after |
| :--- | ---: | ---: | --- |
| G0 (domain) | < 50 ms | < 1 s | 5 s (= timeout) |
| G1 (falsifiability) | < 50 ms | < 1 s | 5 s |
| G1.5 (simulability) | < 50 ms | < 2 s | 5 s |
| G2 (worthiness council, 4 models × 3 stages) | n/a | 30–90 s | 120 s (= timeout); investigate at 100 s |
| G2.5 (tractability dry-run, one solver iteration on toy) | 5–20 s | 60–180 s | 300 s; investigate at 240 s |
| G3 (surrogate inference + OOD check) | < 1 s | 60–300 s | 600 s; investigate at 480 s |
| G4 (validation portfolio: invariants + refinement + symmetry + statistics + optional cross-sim) | 30 s | 1200–3000 s | 3600 s; investigate at 2700 s |
| G5 (C3 interpretation + C4 peer review) | n/a | 60–180 s | 240 s; investigate at 200 s |
| G6 (human gate) | unbounded | unbounded | check `approval_queue` instead of clock |

If the gate is *slow but progressing* (sub-process CPU is busy, log lines arriving in `sandbox/`), give it the full timeout. If wall-clock is high but the implementing module has produced no output for ≥30 s, treat as hung even before the timeout fires.

### 2.4 Inspect the implementing-module logs

Each gate maps to one module (per `config/state_machine/gates/<gate-id>.yaml: implementing_module`):

| Gate | Implementing module | Where it logs |
| :--- | :--- | :--- |
| G0 | `factory.state_machine` (local check) | `cycle.jsonl` `module=state_machine` |
| G1 | `factory.state_machine` (local check) | same |
| G1.5 | `factory.selector` | `cycle.jsonl` `module=selector`; `$CYCLE/artifacts/<hash>.json` for the SelectorReport |
| G2 | `factory.council` (C1) | `cycle.jsonl` `module=council`; `$CYCLE/councils/<session_id>.jsonl` for the full transcript |
| G2.5 | `factory.genver` (dry-run) | `cycle.jsonl` `module=genver`; `$CYCLE/sandbox/00X/` per iteration |
| G3 | `factory.surrogate` | `cycle.jsonl` `module=surrogate`; surrogate score + OOD detection result in artifacts |
| G4 | `factory.validation` | `cycle.jsonl` `module=validation`; per-check results in `$CYCLE/artifacts/` |
| G5 | `factory.council` (C3 then C4) | `cycle.jsonl` `module=council`; two council sessions |
| G6 | `factory.operator` (human) | `runs/_control/events/<ts>.json` for the approve/reject |

Pull just the suspect module's events for the last 5 minutes:

```
jq -c --arg m <module> 'select(.module == $m)' "$CYCLE/cycle.jsonl" | tail -50
```

Look for:
- The last event before silence — usually points at the exact line that hung (e.g., a `subprocess_spawn` with no matching `subprocess_exit`).
- Repeated retries with no progress (a sign the module is stuck in an internal retry loop that should have surfaced as a failure).
- Vendor / external-call events with no return (LLM API stall, OpenAlex timeout, container daemon unresponsive).

If the implementing module is itself a subprocess, check its `pid` from the spawn event and verify it is still alive:

```
ps -p <pid> -o pid,stat,etime,comm
```

`stat=D` (uninterruptible sleep) for more than a few seconds usually means an NFS / disk I/O block — not a code bug, but a host issue.

### 2.5 Reproduce locally with replay

The cheapest way to confirm "the gate path is broken" vs "this one execution was unlucky" is to replay the cycle:

```
python -m factory.state_machine replay --cycle-id <cycle-id>
```

Replay walks the persisted artifacts in `$CYCLE/artifacts/` and re-emits events *without* calling external services. If replay reaches the same hang point with the same artifacts, the bug is deterministic and in the orchestrator (route lookup, artifact loading, manifest indexing). If replay completes cleanly to a terminal that *differs* from the live cycle's terminal, the live failure was driven by an external dependency (LLM provider error, simulator container missing) — the cycle's artifacts up to the hung gate are still valid and can be reused after fixing the dependency.

Replay is read-only; it cannot corrupt the cycle. Run it any time.

### 2.6 Step-debug a specific gate

When you have a hypothesis ("G3's OOD detector is rejecting candidates that should pass"), pause the state machine right before that gate so you can introspect the input artifacts:

```
python -m factory.state_machine step --cycle-id <cycle-id> --pause-after G2.5
```

The state machine runs gates in order, persists each gate's output, and exits **after** the named gate. The pause is implemented as a normal terminal; the cycle directory is left in a coherent state. To resume, run the next gate by itself:

```
python -m factory.state_machine run-gate \
  --cycle-id <cycle-id> --gate G3 \
  --inputs ExperimentSpec=$(jq -r '.gates["G2.5"].output_artifact_hash' "$CYCLE/MANIFEST.json")
```

`run-gate` accepts explicit `--inputs` so you can swap an artifact to test a fix. The result is persisted to `$CYCLE/artifacts/` and `MANIFEST.json` is updated, but no `gate_exit` event fires for the broader cycle until you resume the full `run_cycle` from this point ([TBD-impl] — `run-cycle --resume-from` is not yet documented in spec 003 §3 ENTRY POINTS).

### 2.7 Triage `GateRouteUndefined`

This error means a gate returned an outcome that is not listed for that gate in `config/state_machine/gate_routes.yaml`. The state machine refuses to silently default — that is by design (spec 003 §5.3).

Look up the offending `(gate, outcome)` pair from the error message, then choose one of three responses:

1. **The outcome is a legitimate new state.** Add a route in `config/state_machine/gate_routes.yaml`. Decide first whether it terminates the cycle (`terminate_*`) or branches to another gate. Update spec 003 §4.1 to reflect the addition. Re-run `python -m factory.state_machine validate-routes` (per spec 003 §3 ENTRY POINTS) to confirm the DAG property still holds.

2. **The outcome is a bug in the implementing module.** The module is returning an outcome string the route table never expected (typo, leftover from a refactor, new enum value not propagated to YAML). Fix the module to return a known outcome; do **not** add a route to mask the bug.

3. **The outcome is a recovery branch you forgot to wire.** Spec 003 lists these recovery routes per gate (per FIX_PLAN §2, replace any legacy `G4_oracle_only` / `G2.5_with_intensified_validation` route targets with the canonical `G4` / `G2.5` gates and carry the modal via `HypothesisSpec.qualified_track` or G3-side `skip_surrogate=True` metadata):
   - `G0: fail → terminate_parked_for_scope_expansion` — out-of-scope hypothesis; C5 reviews.
   - `G1: fail → terminate_discarded` — non-falsifiable; rationale logged.
   - `G1.5: fail → terminate_parked_for_lack_of_tooling` — no simulator can compute the metric.
   - `G2: qualified → G2.5` (with `HypothesisSpec.qualified_track=True`) — majority-approved with substantive dissent.
   - `G2.5: fail → terminate_intractable` — toy dry-run failed.
   - `G3: ood_escalation → G4` (with `skip_surrogate=True` metadata flag) — OOD candidate skips surrogate.
   - `G3: fail → terminate_falsified` — surrogate rejection is a real falsification.
   - `G4: inconclusive → terminate_inconclusive` — portfolio neither passes nor falsifies.
   - `G5: fail → terminate_inconclusive` — C4 peer review rejected.
   - `G6: fail → terminate_published_internal_only` — human declined external; internal ledger entry stays.
   If any of those is missing from your YAML, the file is stale relative to spec 003 — restore from the spec exemplar.

### 2.8 Triage `ArtifactNotFound`

A gate's required input artifact hash does not resolve. Two sub-cases:

- **The upstream gate did not persist its output.** Check the upstream gate's `gate_exit` event; if `output_artifact_hash` is null but `outcome=pass`, the bug is in the upstream implementing module. File a bug; the cycle is dead — set terminal `inconclusive` via Step 2.10.
- **The artifact was persisted but the file is missing.** Check `$CYCLE/artifacts/<hash>.json`. If absent, someone or something pruned the directory between gates. This is a filesystem / operator-error class bug. Restore from any backup (or accept the loss); the cycle is unrecoverable.

### 2.9 Inspect the artifact graph

When you suspect the cycle's data flow rather than its control flow, walk the artifact graph end-to-end:

```
python -m factory.state_machine inspect --cycle-id <cycle-id> --verify-chain
```

`verify-chain` walks the `MANIFEST.json` index in gate order; for each gate it loads the listed input and output artifact JSONs, recomputes hashes, and confirms references match. It catches:
- Hash drift (an artifact was edited after persistence — should be impossible by design, present if a developer hand-edited).
- Missing artifacts (Step 2.8).
- Gate skips (a gate has no entry in the manifest, meaning the orchestrator jumped past it). Skips violate the route DAG and are a critical bug.

### 2.10 Force a rollback to a clean terminal

When the cycle is unrecoverable but you need to free its budget and clear the operator console:

```
python -m factory.state_machine force-terminate \
  --cycle-id <cycle-id> \
  --terminal terminate_inconclusive \
  --reason "<short text linked to investigation>"
```

`force-terminate` (per spec 003 §3 ENTRY POINTS; the operator CLI in spec 015 does not expose this directly — drive it module-internally) writes an `EvidenceLedgerEntry` with `result=inconclusive`, attaches the cycle's existing artifacts as references, and emits a `cycle_terminal` event. The Budget Tracker (`spec 013`) closes the hypothesis with the current `running_ledger`. The hypothesis is then eligible for re-litigation per the standard `relitigate_if` triggers — usually only after the root cause is fixed.

Never force-terminate as `passed` or `falsified`; those are scientific verdicts and require the validation portfolio to have actually run. The only legal force-terminate states are `intractable` and `inconclusive`.

---

## 3. Verification

After applying any fix (config change, gate config update, module patch), verify the orchestrator is healthy before resuming production cycles.

1. **Route table validates.**
   ```
   python -m factory.state_machine validate-routes
   ```
   Expected output: `OK · N gates · M routes · 0 cycles · 0 unreachable terminals`. Any other output blocks startup.

2. **Mock-mode cycle still passes.**
   ```
   python -m factory.state_machine run-cycle --gap-fixture sample --mock-mode
   ```
   Should terminate at `terminate_published_internal_only` (the default mock route) within 5 seconds. Walks every gate via its mock implementation; confirms the orchestrator can dispatch.

3. **Replay of the original failed cycle reproduces or no longer reproduces, as expected.**
   ```
   python -m factory.state_machine replay --cycle-id <cycle-id>
   ```
   - If your fix was a route addition, replay should now traverse the new route and terminate cleanly.
   - If your fix was in the implementing module, replay still reproduces the original failure (it does not re-call the module) — that is expected. Run `run-gate --gate <fixed-gate>` against the cycle's persisted inputs to confirm the module fix.

4. **Live mini-cycle.** Pick a single low-cost hypothesis from the recent ledger and run:
   ```
   python -m factory.state_machine run-cycle --hypothesis-id <id>
   ```
   Confirm it walks all gates within their budgets and lands at a legitimate terminal. Per spec 003 §8 the full live cycle target is ≤72 h, but a mock-style smoke cycle should finish far faster — anything beyond a few hours during this verification step suggests the fix introduced a regression in a different gate.

5. **No structured errors in the new run.**
   ```
   jq -c 'select(.level == "error" or .event | contains("error"))' "$NEW_CYCLE/cycle.jsonl"
   ```
   Should return nothing. Any structured error is a regression to investigate before declaring victory.

---

## 4. Troubleshooting

| Symptom | Likely cause | Action |
| :--- | :--- | :--- |
| `GateTimeoutError(gate=G4)` after 1 hour | Validation portfolio's cross-simulator step hung on a container that never came up. | Inspect `$CYCLE/sandbox/` for the simulator's stdout. If the container failed to start, check `python -m factory.catalog show <simulator_id>` for `container_recipe` and re-run the smoke test (`python -m factory.catalog smoke <simulator_id>`). Bump the timeout only if the smoke test passes and the validation work is genuinely longer than 3600 s — otherwise the gate is masking a broken simulator. |
| `GateTimeoutError(gate=G3)` after 10 minutes | Surrogate model loading or OOD detector cold-start exceeded budget. | Check `factory.surrogate` logs for the load time. If load is most of the time, the artifact is too large for the per-gate window — split surrogate load into a process-level warm pool (Phase B). For now raise `config/state_machine/gates/G3.yaml: timeout_seconds` only after confirming the surrogate is otherwise healthy. |
| `GateRouteUndefined(from=G2, outcome=qualified)` | Operator pulled spec 003 §4.1 from a stale checkout and `config/state_machine/gate_routes.yaml` is missing the qualified branch. | Restore the `G2.qualified → G2.5` route (with `HypothesisSpec.qualified_track=True`) per Step 2.7 sub-case 3. |
| `GateRouteUndefined(from=G3, outcome=ood_escalation)` | Surrogate module produces an OOD signal but the YAML is missing the escalation route. | Add `G3.ood_escalation: G4` and ensure the surrogate emits `skip_surrogate=True` metadata that G4 reads. |
| `ArtifactNotFound(hash=...)` raised during G4 | A G2.5 dry-run artifact (`SolverDryRunResult`) was not persisted but G4 expects it. | Inspect G2.5's `gate_exit` event; if `output_artifact_hash=null` while `outcome=pass`, the dry-run module returned a stub. Fix the module to persist real output. Force-terminate the current cycle as `inconclusive`. |
| `RouteCycleDetected` at startup | A new route accidentally points backward (e.g., `G4: fail → G3`). | Routes must be a DAG (spec 003 §5.3). Re-read the YAML; remove the offending back-edge. Failures branch to terminal states, never to a prior gate. |
| `ImplementingModuleMissing` at startup | `config/state_machine/gates/G4.yaml` references `factory.validation` but that module is not installed. | Run `pip install -e .[validation]` ([TBD-impl] — extras matrix not documented in spec 015) or confirm the gate's spec module has been scaffolded (`factory.validation` per spec 009). |
| Cycle hung at G6 indefinitely with no error | The human approval gate is unbounded; the operator never approved or rejected. | Check `runs/_control/events/` for any approve/reject for this `run_report_id`. If none, the cycle is waiting on a human — there is no bug. Surface in the approval queue UI (screen 9). |
| `gate_exit` event present but no `cycle_terminal` for the last gate | The orchestrator crashed during artifact persistence or `EvidenceLedger.insert_entry`. | Inspect `runs/<cycle-id>/cycle.jsonl` tail for a structured error event with `level=error`. Also tail `runs/_control/operator.jsonl` for orchestrator-level crashes. If `EvidenceLedger` rejected the entry, see the ledger-audit runbook. |
| Replay diverges from live trace at gate K | A gate's implementing module is non-deterministic without persisting its seed. | Locate the gate's output artifact; check whether `seed` is in its `ProvenanceBlock`. If absent, the module violates ARCHITECTURE.md §4.1 (determinism). Patch the module to persist its seed. |
| `factory status` shows cycle stuck in G2 but cycle.jsonl says G3 entered | The CLI is reading from a stale snapshot served by spec 015 HTTP; the state machine has advanced. | Refresh status (the CLI cache is per-invocation; if you see staleness across invocations, the underlying telemetry feed is stuck — see the telemetry spec). |
| `GateRouteUndefined(from=G1.5, outcome=parked)` | The selector module is producing `parked` outcomes but `gate_routes.yaml` only maps `pass` and `fail`. | Decision: is "parked" a legitimate G1.5 outcome distinct from "fail"? Per spec 003 §4.1, G1.5 currently has only pass/fail; `parked_for_lack_of_tooling` is the terminal name, not the outcome. Patch the selector to return `fail` and let the route lead to `terminate_parked_for_lack_of_tooling`. |

---

## 5. Related

- **Spec 003 — Gate State Machine** (`docs/specs/003-state-machine.md`): canonical gate definitions, route table reference, outcome enum, recovery paths, C5 scheduler. The authority on every behaviour this runbook touches.
- **Spec 002 — Typed Artifacts** (`docs/specs/002-artifacts.md`): artifact schemas the state machine reads/writes; hash computation rules referenced by `verify-chain`.
- **Spec 012 — Evidence Ledger** (`docs/specs/012-evidence-ledger.md`): consult for any failure inside `insert_entry` at cycle terminal (Step 2.10). See `runbooks/ledger-audit.md`.
- **Spec 013 — Budget Tracker** (`docs/specs/013-budget-tracker.md`): explains `BudgetExhausted → terminate_intractable` automatic routing. See `runbooks/budget-tuning.md` when a hung gate is actually waiting on an exhausted budget reservation.
- **Spec 015 — Operator Interface** (`docs/specs/015-operator-interface.md`): defines the CLI surface used in this runbook. Mark `[TBD-impl]` notes flag commands that this runbook needs but spec 015 has not yet enumerated; add them when the spec is extended.
- **`ARCHITECTURE.md` §1.4** (logs are structured, colocated, and per-cycle): the contract this runbook relies on for log shape; if `cycle.jsonl` is missing or unstructured, that invariant is broken — fix the invariant first.
