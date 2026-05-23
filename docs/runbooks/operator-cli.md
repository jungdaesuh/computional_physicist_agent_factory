# Runbook: Operator CLI Reference

> What this covers: every `factory` CLI subcommand documented in spec 015 §3 — signatures, common flags, expected output, exit codes, and one example invocation per command. Grouped by intent: starting/stopping, monitoring, discovery, approval/rejection, catalog management, council operations, budget management. · When to use: any time you need to drive or inspect the factory from the shell; the canonical command surface for a human operator. · Estimated time: 5 minutes per command in mock mode; a full sit-down to read end-to-end takes ~30 minutes.

## 1. Prerequisites

- A clean checkout with the `factory` console script installed (registered in `pyproject.toml` as `factory = factory.operator.cli:main`). Confirm:
  ```bash
  factory --help
  ```
  The output enumerates every subcommand listed below. If missing, run `pip install -e .` from the repo root.
- Optional: mock mode for every command — pass `--mock-mode` or set `FACTORY_MOCK=1`. Backed by `factory/operator/fixtures/`; no live factory required.
- For HTTP-server commands, the FastAPI app binds to `127.0.0.1` only in Phase A; non-loopback binds are refused at startup.
- For mutations (`pause`, `resume`, `approve`, `reject`, `budget set`, `catalog onboard`), the state machine (spec 003) must be reachable. If not, the CLI exits with `FactoryNotRunning` (exit code 3) and the suggestion to pass `--mock-mode`.

### 1.1 Global flags (every subcommand)

| Flag | Effect |
| :--- | :--- |
| `--mock-mode` | Use fixture data instead of live subsystems. Equivalent to `FACTORY_MOCK=1`. |
| `--config-dir <path>` | Override the config directory (default `config/`). Merge precedence: CLI flags > env vars > config file > defaults. |
| `--format text|json` | Output format for read commands. Default `text`. |
| `--quiet` | Suppress info-level output; only errors and the final result. |
| `--verbose` | Emit debug-level diagnostics alongside the normal output stream. |
| `--help` | Show subcommand help and exit. |

### 1.2 Exit codes (uniform across subcommands)

| Code | Meaning |
| :--- | :--- |
| `0` | Success. |
| `1` | Generic `FactoryError` not covered by a more specific code. |
| `2` | `ConfigurationInvalid` — bad flag, missing file, schema violation. Never partial-apply config. |
| `3` | `FactoryNotRunning` — required subsystem not reachable. |
| `4` | `CycleNotFound`, `AmbiguousHypothesisId`, or generic validation error. |
| `5` | `ApprovalDenied` — G6 reject already committed on the same `RunReport`. |

Every CLI invocation appends a structured `FactoryControlEvent` to `runs/_control/events/<ts>.json` and a log line to `runs/_control/operator.jsonl`. Use `jq` to filter by command, actor, or timestamp during postmortem.

---

## 2. Steps

### 2.1 Starting & stopping the factory

#### `factory start [--seed <topic>] [--cycles <N>] [--daily-cap-usd <amount>]`

Starts the factory's autonomous loop. Streams cycle events from spec 014's telemetry bus to stdout for as long as the CLI process is alive. On `SIGINT` (Ctrl-C) emits a `pause` event and exits cleanly.

**Signature:**
```
factory start [--seed TOPIC] [--cycles N] [--daily-cap-usd USD] [--mock-mode] [--format text|json]
```

**Flags:**
- `--seed TOPIC` — Optional seed topic for the literature discovery stage. If omitted, the factory reads from its `open-problems registry`.
- `--cycles N` — Stop after exactly N autonomous cycles. Omit for unbounded (run-until-stopped).
- `--daily-cap-usd USD` — Override `config/operator.yaml` daily cap for this run only. Permanent changes go through `factory budget set --daily-usd`.

**Example:**
```bash
factory start --seed "stellarator coil simplicity" --cycles 1 --daily-cap-usd 50.00 --format json
```

**Expected output snippet (stdout, JSONL by default):**
```json
{"ts": "2026-05-23T12:00:01Z", "event": "cycle_started", "cycle_id": "20260523-abc"}
{"ts": "2026-05-23T12:00:14Z", "event": "gate_passed", "cycle_id": "20260523-abc", "gate": "G0"}
{"ts": "2026-05-23T12:01:08Z", "event": "council_session_complete", "council_id": "C1", ...}
```

**Exit codes:** `0` on clean shutdown (SIGINT), `1` on unhandled `FactoryError`, `2` if `--daily-cap-usd` is invalid.

---

#### `factory stop [--force]`

Requests a graceful shutdown of the running factory loop. Without `--force`, completes the current cycle and exits. With `--force`, sends a `pause` event then kills active subprocesses (sandboxes, simulator containers) immediately.

**Signature:**
```
factory stop [--force] [--mock-mode]
```

**Flags:**
- `--force` — Skip the "wait for current cycle to complete" grace period. Kills in-flight sandbox subprocesses and emits a `forced_stop` `FactoryControlEvent`. Use sparingly.

**Example:**
```bash
factory stop
```

**Expected output:**
```
graceful stop requested
  current cycle: 20260523-abc (in G4 validation)
  waiting for cycle completion (max 5 min)...
  cycle 20260523-abc stopped at gate G4
factory idle
```

**Exit codes:** `0` on clean stop, `3` if factory was already idle (`FactoryNotRunning`), `1` on unexpected error.

---

#### `factory pause --reason <text>`

Pauses the state machine between cycles. The factory completes the in-flight gate and then halts; no new cycles start. Inverse of `factory resume`.

**Signature:**
```
factory pause --reason TEXT [--mock-mode]
```

**Flags:**
- `--reason TEXT` — Required; non-empty. Recorded in the `FactoryControlEvent`.

**Example:**
```bash
factory pause --reason "investigating G4 disagreement on HYP-2c4e9b1"
```

**Expected output:**
```
factory paused
  reason: investigating G4 disagreement on HYP-2c4e9b1
  control_event_hash: a82c1b8...
  paused_at: 2026-05-23T14:08:11Z
```

**Exit codes:** `0` on pause acknowledged, `2` if `--reason` is missing or empty, `3` if factory was not running.

---

#### `factory resume`

Resumes a paused factory. No-op if the factory is already running.

**Signature:**
```
factory resume [--mock-mode]
```

**Example:**
```bash
factory resume
```

**Expected output:**
```
factory resumed
  resumed_at: 2026-05-23T15:02:44Z
  next cycle will start within 60s
```

**Exit codes:** `0` on resume acknowledged, `3` if factory was not paused.

---

### 2.2 Monitoring & inspection

#### `factory status [--format text|json]`

Prints a current snapshot of the factory: which cycle is active, which gate it is in, the current `Budget` running ledger, the most recent council verdict, and any pending operator decisions in the G6 approval queue.

**Signature:**
```
factory status [--format text|json] [--mock-mode]
```

**Example:**
```bash
factory status
```

**Expected output (text):**
```
factory status: running
  active cycle: 20260523-abc
    hypothesis: HYP-2c4e9b1...  ("compact stellarator with high L_grad_B")
    current gate: G4 (validation portfolio)
    progress: 6 of 8 checks complete
  budget:
    dollar_spent: $12.47 / $50.00 daily cap
    cycles_today: 3
  approval queue: 1 RunReport awaiting G6
  last council verdict: C2 (design) at 2026-05-23T12:01:08Z
```

**Expected output (json):**
```json
{
  "status": "running",
  "active_cycle": {"id": "20260523-abc", "hypothesis": "HYP-2c4e9b1...", "gate": "G4", ...},
  "budget": {"dollar_spent": 12.47, "daily_cap": 50.00, "cycles_today": 3},
  "approval_queue_size": 1,
  "stale": false,
  "served_at": "2026-05-23T15:08:11Z"
}
```

**Exit codes:** `0` always (status returns even when factory is idle).

---

#### `factory inspect <hypothesis-id>`

Walks the full artifact chain for a hypothesis: `GapCandidate` → `HypothesisSpec` → `ExperimentSpec` → council verdicts → `GenVerResult` → `ValidationResult` → `EvidenceLedgerEntry` → optional `RunReport`. Accepts the 7-char hash prefix or full hash.

**Signature:**
```
factory inspect HYPOTHESIS_ID [--format text|json] [--mock-mode]
```

**Example:**
```bash
factory inspect HYP-2c4e9b1
```

**Expected output (text):**
```
HypothesisSpec  hash=2c4e9b1...  cycle=20260523-abc
  if_then: "If L_grad_B > 8.61, then coil complexity reduces by 30%"
  measurable_metric: L_grad_B
  pre_registered_metric: L_grad_B
  parent_gap: 7d3a8f2...  (structural_hole from arXiv:2024.xxxxx)
chain:
  GapCandidate            7d3a8f2...  status=approved (C1)
  HypothesisSpec          2c4e9b1...  current
  ExperimentSpec          6f1a8d4...  simulator=vmecpp
  CouncilVerdict (C2)     d1e2f3a...  decision=approve
  GenVerResult                        terminal=promoted iterations=4
  ValidationResult        b4e9c2d...  verdict=PASS  reweighted=false
  EvidenceLedgerEntry     3a2c1b8...  result=passed
  RunReport               8f1d3e9...  g6_approved=false (in queue)
```

**Exit codes:** `0` on success, `4` if `AmbiguousHypothesisId` (prefix matches ≥2 entries — print candidates) or `CycleNotFound`.

---

#### `factory replay <cycle-id> [--dry-run]`

Re-renders the artifacts and events of a completed cycle without re-executing simulators or LLM calls. Useful for postmortems. Streams the cycle's event log in order. Phase A is render-only; deterministic re-execution is deferred to Phase B per spec 015 §9.

**Signature:**
```
factory replay CYCLE_ID [--dry-run] [--format text|json] [--mock-mode]
```

**Flags:**
- `--dry-run` — Stream events without writing any side-effect artifacts; equivalent to read-only replay.

**Example:**
```bash
factory replay 20260523-abc --format json | jq 'select(.event | startswith("gate_"))'
```

**Expected output (filtered to gates):**
```json
{"event": "gate_passed", "gate": "G0", "ts": "..."}
{"event": "gate_passed", "gate": "G1", "ts": "..."}
{"event": "gate_passed", "gate": "G1.5", ...}
{"event": "gate_passed", "gate": "G2", "council_id": "C1", ...}
{"event": "gate_passed", "gate": "G2.5", ...}
{"event": "gate_passed", "gate": "G3", ...}
{"event": "gate_failed", "gate": "G4", "reason": "RefinementInconsistent", ...}
```

**Exit codes:** `0` on success, `4` if `CycleNotFound`.

---

### 2.3 Discovery seeding

#### `factory discover --seed <topic>`

Enqueues a literature-discovery run with the given seed topic. Runs the OpenAlex client, traverses the citation graph per the policy in `config/literature.yaml`, and stages `GapCandidate` artifacts for C1 worthiness review on the next cycle boundary.

**Signature:**
```
factory discover --seed TOPIC [--mock-mode]
```

**Flags:**
- `--seed TOPIC` — Required, non-empty. The topic is the input to OpenAlex `search_works`.

**Example:**
```bash
factory discover --seed "quasi-isodynamic stellarator coil simplicity"
```

**Expected output:**
```
discovery run queued
  run_id: lit-20260523-1508
  seed: "quasi-isodynamic stellarator coil simplicity"
  policy: literature_discovery (max_depth=2, max_nodes=500)
  estimated wall-clock: 8-15 min
  candidate gaps will appear in queue after run completes
```

**Exit codes:** `0` on enqueue, `2` if `--seed` missing or empty, `3` if literature subsystem not present (`TelemetryUnavailable` is also possible).

**Note:** [TBD-impl] If spec 007 (Literature Discovery) is not yet implemented, this command falls back to a mock that writes a `FactoryControlEvent` with the seed and returns immediately. Live mode is gated on spec 007.

---

### 2.4 Approval & rejection (G6)

#### `factory approve <run-report-id> [--yes]`

Approves a `RunReport` for external publication. Records the approver username and timestamp on the `RunReport.g6_approved`, `g6_approver`, `g6_approved_at` fields. Requires interactive confirmation unless `--yes` is passed.

**Signature:**
```
factory approve RUN_REPORT_ID [--yes] [--mock-mode]
```

**Flags:**
- `--yes` — Skip interactive confirmation. Use only in scripted contexts.

**Example:**
```bash
factory approve 8f1d3e9
```

**Expected output:**
```
RunReport  hash=8f1d3e9...  title="Compact stellarator with L_grad_B=8.72"
  abstract: "We report a quasi-isodynamic stellarator design..."
  council verdicts embedded: C3 (interpretation), C4 (peer review)
  G4 validation: PASSED (all 9 checks)
  awaiting G6 approval

Approve for external publication? [y/N]: y

approved
  approver: jung.suh@anthropic.com
  approved_at: 2026-05-23T15:08:11Z
  ledger entry updated: 3a2c1b8...
```

**Exit codes:** `0` on approval, `5` if `ApprovalDenied` (already rejected; requires `--re-litigate` flag with a C5 verdict reference per spec 015 §5.5), `4` if `RunReport` not found.

---

#### `factory reject <run-report-id> --reason <text>`

Rejects a `RunReport`. Requires `--reason` non-empty; reasons under 20 chars trigger a prompt before exit. Records the rejection in the ledger; subsequent `factory approve` on the same `RunReport` returns `ApprovalDenied` (exit 5) unless explicitly re-litigated.

**Signature:**
```
factory reject RUN_REPORT_ID --reason TEXT [--mock-mode]
```

**Flags:**
- `--reason TEXT` — Required, non-empty. Reasons under 20 chars trigger an "are you sure" prompt before exit.

**Example:**
```bash
factory reject 8f1d3e9 --reason "G4 PASSED but C3 disagreement on interpretation suggests intensified review needed; want C5 to look first"
```

**Expected output:**
```
RunReport  hash=8f1d3e9...  rejected
  rejector: jung.suh@anthropic.com
  reason: "G4 PASSED but C3 disagreement on interpretation suggests..."
  rejected_at: 2026-05-23T15:08:11Z
  ledger entry updated: 3a2c1b8... (g6_status=rejected)
```

**Exit codes:** `0` on rejection, `2` if `--reason` missing or empty, `4` if `RunReport` not found.

---

### 2.5 Catalog management

#### `factory catalog onboard <manifest-path>`

Onboards a new simulator into the catalog. Reads the manifest YAML, runs the license auditor across the dependency graph, builds the container from the recipe, runs the smoke test, and (on success) adds the entry to the catalog. Phase B per spec 015 §3; Phase A is a stub that writes a `FactoryControlEvent` and enqueues for human review.

**Signature:**
```
factory catalog onboard MANIFEST_PATH [--mock-mode]
```

**Example:**
```bash
factory catalog onboard ./manifests/desc-v1.1.0.yaml
```

**Expected output (Phase A):**
```
catalog onboarding request queued
  manifest: ./manifests/desc-v1.1.0.yaml
  simulator_id: desc
  proposed version: 1.1.0
  license: BSD-3-Clause (verified)
  dependency licenses: 14/14 OSI-approved
  container recipe: Dockerfile present
  smoke test: declared (target: knownGood_axisymmetric)
  request_id: catalog-req-20260523-1508
  awaiting human approval per spec 004 Phase B onboarding workflow
```

**Exit codes:** `0` on enqueue, `2` if manifest invalid, `4` if container recipe missing, `1` if license auditor failed.

**Note:** [TBD-impl] Full automated onboarding (build + smoke + activate) is a spec 004 Phase B deliverable; Phase A returns the enqueue acknowledgement and surfaces the request in `factory status`.

---

### 2.6 Council operations

#### `factory council calibrate`

Runs the council calibration probe set (sycophancy probe + heterogeneity check) against the current model lineup. Produces a calibration report showing each model's agreement rate, persona-faithfulness rate, and chairmanship-balance over the probe set. Used to detect drift in council behavior.

**Signature:**
```
factory council calibrate [--format text|json|html] [--mock-mode]
```

**Flags:**
- `--format html` — In addition to text/json, emit a rendered HTML report for the operator console.

**Example:**
```bash
factory council calibrate --format json | jq '.sycophancy_rate'
```

**Expected output (text excerpt):**
```
calibration run: cal-20260523-1508
  model lineup:
    claude-opus-4-7    agreement=0.42  persona-faithful=0.91
    gpt-5              agreement=0.39  persona-faithful=0.88
    gemini-2-pro       agreement=0.41  persona-faithful=0.85
    open-weight-70b    agreement=0.45  persona-faithful=0.79
  pairwise heterogeneity:
    [opus  vs gpt-5]   spearman=0.37  (target <0.6)  OK
    [opus  vs gemini]  spearman=0.42  (target <0.6)  OK
    [opus  vs ow-70b]  spearman=0.51  (target <0.6)  OK
    ...
  chairmanship balance over last 100 sessions:
    opus:  27  gpt-5: 23  gemini: 26  ow-70b: 24   (within target ±15%)
  sycophancy rate (probe set N=50): 0.06 (target <0.10)  OK
  result: HEALTHY
```

**Exit codes:** `0` on report generated, `1` on calibration FAIL (any metric out of band — report shows which).

**Note:** [TBD-impl] The calibration probe set itself is defined in spec 001; if absent at run time, the command falls back to a fixture-based mock report.

---

### 2.7 Budget management

#### `factory budget show [--hypothesis <id>] [--format text|json]`

Reads the `Budget` artifact and shows the running ledger. Without `--hypothesis`, shows the aggregate (daily / cycle / total caps and spend). With `--hypothesis`, shows the per-hypothesis ledger.

**Signature:**
```
factory budget show [--hypothesis HYP_ID] [--format text|json] [--mock-mode]
```

**Example (aggregate):**
```bash
factory budget show
```

**Expected output (aggregate):**
```
aggregate budget:
  aggregate_cap_usd: $1000.00 (lifetime)
  aggregate_spent_usd: $147.18
  daily_cap_usd: $50.00
  daily_spent_usd: $12.47
  daily_remaining_usd: $37.53
  per_hypothesis_default_usd: $50.00
```

**Example (per-hypothesis):**
```bash
factory budget show --hypothesis HYP-2c4e9b1
```

**Expected output (per-hypothesis):**
```
budget for HYP-2c4e9b1:
  dollar_cap: $1.00
  dollar_spent: $0.32
  dollar_remaining: $0.68
  iteration_cap: 10
  iterations_used: 4
  token_cap: 200000
  tokens_used: 38791
  running_ledger:
    iter=0 module=genver cost=$0.04 tokens=11823  "code_gen iteration 0"
    iter=1 module=genver cost=$0.03 tokens=10142  "code_gen iteration 1"
    iter=2 module=genver cost=$0.05 tokens=8124   "code_gen iteration 2"
    iter=3 module=council cost=$0.20 tokens=8702  "C2 design verdict"
```

**Exit codes:** `0` always.

---

#### `factory budget set --aggregate-usd <usd> [--per-hypothesis-usd <usd>] [--daily-usd <usd>]`

Sets one or more budget caps. Each flag is independent; only the caps you pass are updated. Records a `FactoryControlEvent` per cap change. Per FIX_PLAN §6.2 there are exactly **three tiers** (aggregate / per-hypothesis / per-day) — there is no `--per-cycle-usd` flag.

**Signature:**
```
factory budget set --aggregate-usd USD [--per-hypothesis-usd USD] [--daily-usd USD] [--mock-mode]
```

**Flags:**
- `--aggregate-usd USD` — Lifetime cap across all cycles. Required.
- `--per-hypothesis-usd USD` — Per-`HypothesisSpec` cap.
- `--daily-usd USD` — Rolling 24-hour cap.

**Example:**
```bash
factory budget set --aggregate-usd 1000.00 --daily-usd 100.00 --per-hypothesis-usd 2.00
```

**Expected output:**
```
budget caps updated
  aggregate_cap_usd:       $500.00 -> $1000.00
  daily_cap_usd:           $50.00  -> $100.00
  per_hypothesis_cap_usd:  $1.00   -> $2.00
  control_event_hash: f9e8d7c...
  effective immediately
```

**Exit codes:** `0` on update, `2` if `--aggregate-usd` not passed or any value invalid (negative, non-numeric).

---

#### `factory serve [--host <host>] [--port <port>]`

Starts the read-only HTTP API server (spec 015 §3, FIX_PLAN §9.1). The FastAPI app exposes the same `factory status` / `factory inspect` projections via HTTP for the operator UI and external dashboards. Binds to `127.0.0.1` only in Phase A; non-loopback binds are refused at startup.

**Signature:**
```
factory serve [--host HOST] [--port PORT] [--mock-mode]
```

**Flags:**
- `--host HOST` — Bind address. Default `127.0.0.1`. Non-loopback values raise `ConfigurationInvalid` in Phase A.
- `--port PORT` — TCP port. Default `8765`.

**Example:**
```bash
factory serve --port 8765 --mock-mode
```

**Expected output:**
```
factory HTTP API listening on http://127.0.0.1:8765
  mock-mode: true
  endpoints: /mission_control /status /inspect/{hypothesis_id} /budget /catalog
```

**Exit codes:** `0` on graceful shutdown (SIGINT), `2` if host is non-loopback in Phase A, `3` if telemetry unreachable and no stale snapshot available.

---

## 3. Verification

After running any of the above commands, confirm:

1. **The state-changing commands wrote a `FactoryControlEvent`.** Inspect the latest entry under `runs/_control/events/`:
   ```bash
   ls -t runs/_control/events/ | head -1 | xargs -I{} cat runs/_control/events/{}
   ```
   Expected fields: `ts`, `command`, `args`, `actor`, `reason?`, `artifact_refs[]`.

2. **The `operator.jsonl` log captured the invocation.** Every CLI invocation (success or failure) writes one structured line:
   ```bash
   tail -1 runs/_control/operator.jsonl | jq
   ```

3. **The exit code matches the table in §1.2.** Scripted callers should branch on exit code, not on stdout parsing.

4. **Mock-mode commands work without any subsystem present.** Quick smoke from a clean checkout:
   ```bash
   FACTORY_MOCK=1 factory --help
   FACTORY_MOCK=1 factory status
   FACTORY_MOCK=1 factory inspect HYP-2c4e9b1
   FACTORY_MOCK=1 factory budget show
   ```
   Each should exit `0` with deterministic fixture output.

5. **HTTP server boots in mock mode.** If you started the FastAPI app via `factory serve` (or equivalent), confirm:
   ```bash
   curl http://127.0.0.1:8765/mission_control | jq '.stale'
   # false (fixture data) — or true with a stale-flag header if telemetry unavailable
   ```

6. **No mutation command short-circuited config validation.** A failed `factory budget set --daily-usd -50` should exit 2 with the config unchanged:
   ```bash
   factory budget set --daily-usd -50
   echo $?  # 2
   factory budget show  # daily_cap unchanged
   ```

## 4. Troubleshooting

| Symptom | Likely cause | First action |
| :--- | :--- | :--- |
| `factory --help` does not list a documented subcommand | Console script not installed or out of date | `pip install -e .` from repo root; re-check `pyproject.toml` `[project.scripts]` |
| `factory status` shows `stale: true` | Telemetry bus (spec 014) unreachable | Restart telemetry; CLI degrades to last-known snapshot from artifact store |
| `factory start` exits immediately with `FactoryNotRunning` (exit 3) | State machine subprocess failed to launch | Check `runs/_control/operator.jsonl` for the failed launch event; inspect state-machine logs in `runs/<cycle-id>/cycle.jsonl` |
| `factory inspect <prefix>` returns `AmbiguousHypothesisId` (exit 4) | Prefix matches multiple ledger entries | Re-run with a longer prefix or the full hash; the command's output lists the candidate full hashes |
| `factory replay` shows no events for a known-good cycle | `cycle.jsonl` was rotated or pruned | Confirm `runs/<cycle-id>/cycle.jsonl` exists; if not, check log rotation policy in `config/operator.yaml` |
| `factory approve` prompts repeatedly even with `--yes` | `--yes` not implemented for this RunReport's domain (Phase B) | Provide interactive confirmation; `--yes` is only honored when the implementation supports scripted approval |
| `factory reject --reason "no"` triggers a prompt asking for confirmation | Reason under 20 chars triggers a confirmation per spec 015 §5.5 | Type `y` to confirm or rerun with a more substantive reason |
| `factory catalog onboard` always returns enqueue acknowledgement | Phase A — automated onboarding is Phase B [TBD-impl] | Manual approval workflow per spec 004 Phase B onboarding policy |
| `factory council calibrate` returns `result: FAIL` | One or more calibration metrics out of band | Read the failing metric, adjust model lineup or persona prompts; do not run the factory until calibration is HEALTHY |
| `factory council calibrate` mock-mode output looks the same every time | Fixture is deterministic by design | Live mode reflects actual model behavior; mock is a smoke check only |
| `factory discover --seed ""` exits 2 | Seed must be non-empty | Provide a non-empty topic |
| `factory discover` returns immediately with no `run_id` | Spec 007 not implemented yet [TBD-impl] | Mock mode returns a mock run_id; live mode is gated on spec 007 |
| `factory budget set --aggregate-usd 0` exits 2 | Caps must be positive | Provide a positive value; to "disable" a cap, set it to a very large value, not zero |
| `factory budget set` succeeds but `factory budget show` still shows old caps | Budget tracker cache not invalidated | Restart the budget service; spec 013 owns the invalidation contract |
| HTTP server returns 503 on every endpoint | Telemetry unavailable, no stale-snapshot to serve | Restart telemetry or pass `--mock-mode` when starting the server |
| `factory stop --force` does not actually kill in-flight sandbox | Sandbox processes ignore SIGTERM | The state machine should send SIGKILL after 5s grace; if not, file a bug against spec 003 |
| `factory pause` while in G6 approval queue review | Pause is between cycles; G6 is a per-RunReport gate, not a cycle gate | The pause takes effect after the current operator action completes |
| Two `factory` CLI processes running simultaneously corrupt `operator.jsonl` | Multi-CLI safety not yet specified (spec 015 §9) | Use one CLI at a time in Phase A; file lock on `runs/_control/` is a future feature |
| `factory --config-dir /nonexistent` exits 2 | `ConfigurationInvalid` | Provide a valid config directory or omit `--config-dir` to use defaults |
| `factory budget show --hypothesis <id>` shows zero spend on an active hypothesis | Budget tracker not yet receiving entries (spec 013 wiring) | Confirm spec 013 is integrated and the running ledger writes are firing |
| `factory inspect` slow on large chains | Disk-bound on artifact reads | Acceptable for chains <20 nodes; if much slower, check that `runs/` is on local disk |

## 5. Related

- Spec 015 (Operator Interface) — the canonical specification for every command in this runbook, including the FastAPI read-only HTTP surface and the `FactoryControlEvent` artifact.
- Spec 003 (Gate State Machine) — the consumer of every mutation event written by the CLI. The CLI does not transition gates itself; it appends events that spec 003 reads.
- Spec 002 (Typed Artifacts) — every read endpoint and every `inspect` output returns artifacts; never raw dicts. The runbook `runbooks/artifacts-debugging.md` covers artifact-shape issues that may surface here.
- Spec 012 (Evidence Ledger) — backing store for `factory inspect`, `factory replay`, `factory approve`, `factory reject`. The ledger is the durability boundary for G6 decisions.
- Spec 013 (Budget Tracker) — owns `factory budget show` and `factory budget set`. The CLI never bypasses the tracker.
- Spec 001 (Council) — owns `factory council calibrate` and the verdict artifacts that `factory inspect` surfaces.
- Spec 004 (Simulator Catalog) — owns the onboarding workflow that `factory catalog onboard` enqueues against.
- Spec 007 (Literature Discovery) — owns `factory discover` once implemented; Phase A returns a stub enqueue [TBD-impl].
- `UI_DESIGN.md` — the 11 UI screens this CLI's read endpoints support. The UI never owns a write path in Phase A; every mutation flows through this CLI's structured shell history.
- `runbooks/artifacts-debugging.md` — when an `inspect` output looks malformed or `verify-chain` fails.
- `runbooks/genver-debugging.md` — when `inspect` surfaces a hypothesis that terminated `intractable_*`, that runbook explains the root cause.
- `runbooks/validation-debugging.md` — when `inspect` surfaces a FAIL `ValidationResult`, that runbook walks the eight checks.
- `ARCHITECTURE.md` §1.1 (Every component is runnable in isolation) — the invariant the `--mock-mode` flag enforces; every CLI command must work in mock mode against fixtures.
- `ARCHITECTURE.md` §1.4 (Logs are structured) — the invariant the `operator.jsonl` log enforces; every command appends a structured event.
