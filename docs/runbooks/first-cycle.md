# Runbook: First Autonomous Cycle (PRD-003 Milestone)

> What this covers: Drives the factory from a clean checkout through one complete autonomous cycle (G0 -> G6), producing one `RunReport` written to the `EvidenceLedger` with full provenance.
> When to use: First end-to-end integration run of Phase A; whenever a tester or operator needs to verify the full closed loop on a fresh machine; the canonical acceptance test for PRD-003.
> Estimated time: 4 hours of operator-attended setup + up to 72 hours of supervised cycle wall-clock (typical observed ~6-18 hours). Cost ceiling per PRD-003: $50.

This runbook is load-bearing. If a step does not produce the documented signal, **stop** and resolve the discrepancy. The whole point of a Phase A acceptance run is that nothing is happening that you cannot account for.

---

## 1. Prerequisites

### 1.1 Repository + tooling

- A clean checkout of `2026_google/` at the tagged Phase A integration commit (use `git describe --tags --always` to record the SHA in your run journal).
- Python 3.11+ available as `python3`.
- `uv` installed and on `$PATH` (`uv --version` >= 0.4.0). `uv sync` is the single source of truth for the dependency lock; do not mix `pip install` against the project venv.
- A container runtime: `docker buildx` 0.13+ **or** `podman` 5.0+. Verify with `docker buildx version` (or `podman version`). The Catalog refuses to onboard without one of these.
- `git`, `make`, `jq` (used by inspection scripts), and `sqlite3` CLI for ad-hoc Ledger queries.
- Disk: at least 50 GB free under `runs/` (per-cycle artifacts + container layers).
- Network: outbound HTTPS to OpenRouter (`openrouter.ai`), OpenAlex, and the OCI registries your manifests reference. No inbound ports are required.

### 1.2 API keys and secrets

- A single LLM API key exported in the shell that will launch the factory:
  - `OPENROUTER_API_KEY` — OpenRouter API key used by both the council (4 frontier vendors) and every agentic LLM call (Gemini Flash). See FIX_PLAN §25 (which **SUPERSEDES §24**).
- The legacy keys `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `XAI_API_KEY`, and `GEMINI_FLASH` are **no longer required** and must not be set as a fallback path. All LLM access flows through OpenRouter under one env var.
- `OPENALEX_API_KEY` set for live OpenAlex literature discovery. `OPENALEX_MAILTO` is obsolete for OpenAlex rate-limit behavior and is not required.
- Never commit keys. Store `OPENROUTER_API_KEY` in `.envrc.local` (gitignored) or your system keychain. The factory reads it at startup only; rotation requires a restart.

### 1.3 Configuration that must be in place

- `config/operator.yaml` (operator interface defaults) present and parseable. Verify with `factory --mock-mode status`.
- `config/council/lineup.yaml` lineup file carrying a `CouncilLineup` with `models: list[ModelSpec]` (4 entries, one per vendor in FIX_PLAN §25.3 — `openai/gpt-5.5`, `anthropic/claude-opus-4.7`, `google/gemini-3.1-pro-preview`, `x-ai/grok-4.3`) plus a `persona_assignment` mapping each model id to a persona (`Visionary | Pessimist | Pragmatist`) and a `chairman_policy` (`random | round_robin | weighted_by_cost`). Each `ModelSpec` records `openrouter_id`, `vendor`, `timeout_s`, `max_tokens` per FIX_PLAN §25.4. The default `Council.mock_lineup()` is **not** acceptable for live cycles.
- `config/pricing/openrouter.yaml` populated with current OpenRouter passthrough USD-per-1M input/output prices for all 5 model IDs (FIX_PLAN §25.6). The Council library reads this once at startup; missing or stale pricing causes `BudgetTokenUsageMissing` semantics to misreport cost.
- `config/budget.yaml` with `per_hypothesis_usd`, `daily_usd`, and `aggregate_usd` set. For the first cycle pin `per_hypothesis_usd: 50` to match the PRD-001 cost ceiling per FIX_PLAN §25.8 (typical cycle ≤ $5; the $50 cap is the hard ceiling, not the expected spend).
- `config/domain_scope.yaml` listing `allowed_domains[]` and `allowed_simulator_ids[]`. Out-of-scope hypotheses park at G0 silently if this file is empty; do not skip it.

### 1.4 Other runbooks that must succeed first

- `docs/runbooks/council-calibration.md` -- `factory council calibrate` must show `flagged_sycophancy: false` and `overall_disagreement_rate >= 0.40` against the built-in probe set (FIX_PLAN §25.4 restored the threshold to 0.40 because the 4-vendor heterogeneity defense is back in force; this **reverts §24's** lowered 0.25 floor). PRD-002 cannot be bypassed.
- `docs/runbooks/catalog-onboarding.md` -- at least **two** active entries must share an `EquivalencePair` on one observable (PRD-004 acceptance). Without this, G4's cross-simulator check cannot fire and the cycle is not a valid PRD-003 acceptance run.
- The `EvidenceLedger` schema (spec 012) must be migrated to head. Run `factory --mock-mode status` and confirm the response includes `ledger_schema_version` matching the current spec's documented version.

---

## 2. Steps

Each step has an exact command, the expected success signal, and what to inspect on deviation. Stay in the repo root for every command unless noted otherwise.

### Step 1 -- Initialise the workspace

```bash
cd /path/to/2026_google
uv sync
```

Expected output: `uv sync` resolves the lock and creates `.venv/`. Final line resembles `Audited <N> packages in <ms>`. Activate the venv with `source .venv/bin/activate` (or rely on `uv run`).

If it fails: re-run with `uv sync --refresh`. If the failure persists, the lock has drifted -- file a doc bug; do not paper over with `pip install`. Phase A invariant 1.7 (module boundaries) requires the canonical install path to work.

### Step 2 -- Smoke-test the mock factory end to end

```bash
factory --mock-mode status
factory --mock-mode inspect <fixture-hypothesis-id>   # ID printed in mock-mode status output
factory --mock-mode budget show
```

Expected signals:
- `factory --mock-mode status` prints a JSON snapshot (or pretty text under `--format text`) containing at minimum: `running: false`, `current_cycle: null`, `ledger_schema_version`, `mock_mode: true`.
- `factory --mock-mode inspect` returns a deterministic `HypothesisSpec` projection with `provenance_hash` populated.
- `factory --mock-mode budget show` returns the default budget envelope from `factory/operator/fixtures/`.

If any command exits non-zero, the operator interface (spec 015) is broken on this machine -- fix before going live. Treat the mock-mode smoke as the architectural-invariant-1.1 test.

### Step 3 -- Build the container images referenced by your Catalog

```bash
python -m factory.catalog list --status active
for sid in $(python -m factory.catalog list --status active --format json | jq -r '.[].simulator_id'); do
    python -m factory.catalog build --simulator-id "$sid"
    python -m factory.catalog smoke --simulator-id "$sid"
done
```

Expected output: each `build` emits a `sha256:` image digest matching the manifest's recorded `image_sha`; each `smoke` emits `passed: true` with `max_field_residual` within the manifest tolerance. Build logs land under `runs/catalog/<sid>/<attempt>/build.log`.

If a build is non-deterministic (different SHA on rebuild), do not proceed -- it is a Catalog determinism bug (spec 004 §5.3). Open a Catalog hotfix issue and resolve before the live cycle. Reproducibility is a PRD-004 acceptance criterion.

If `smoke` fails: do **not** widen tolerances to make it pass. Read `runs/catalog/<sid>/<attempt>/smoke.diff.json`, identify the root cause, and either patch the recipe or quarantine the entry via `python -m factory.catalog quarantine --simulator-id <sid> --reason "<text>"`. Quarantined entries are invisible to the Selector at G1.5.

### Step 4 -- Confirm Council calibration is fresh

```bash
factory council calibrate --format json > runs/_calibration/calibration-$(date +%Y%m%dT%H%M%S).json
jq '{flagged_sycophancy, overall_disagreement_rate, n_probes: (.probe_results | length)}' \
    runs/_calibration/calibration-*.json | tail -n 1
```

Expected: `flagged_sycophancy: false`, `overall_disagreement_rate >= 0.40`, `n_probes >= 10`. Anything else means the council lineup is currently sycophantic and you must run `docs/runbooks/council-calibration.md` to repair it before continuing. The threshold is restored to 0.40 under the 4-vendor OpenRouter lineup (FIX_PLAN §25.4 **SUPERSEDES §24**'s lowered 0.25 floor); empirical floor 0.30 triggers re-calibration; below 0.30 fails.

Pin the calibration JSON in your run journal; the PRD-003 postmortem must reference the exact lineup hash used for the first cycle.

### Step 4.5 -- Certify the live council production path

```bash
uv run python -m factory.council certify-live --cost-cap-usd 0.50
```

Expected output: one JSON object with `status: "passed"`, `lineup_vendor_count: 4`, `session.stage1_response_count: 4`, `session.stage2_response_count: 4`, `cost_within_cap: true`, `budget.budget_entry_count >= 9`, and `error_path.exception: "OpenRouterModelUnavailable"`. The command also writes `runs/live_council_certifications/<timestamp>/certification.json`.

If this fails, do not start the first autonomous cycle. Follow `docs/runbooks/openrouter-client.md` to distinguish key failure, model catalog drift, rate limiting, pricing drift, and a true council integration bug.

### Step 5 -- Configure `DomainScope` and `Budget`

Open `config/domain_scope.yaml` and confirm:

- `allowed_domains` contains the domain you onboarded simulators for in step 3.
- `allowed_simulator_ids` is either empty (allow all in-domain) or explicitly lists the IDs you intend the cycle to use.
- `expansion_criteria` exists; missing this field causes C5 to refuse to run later (not blocking for the first cycle, but record it).

Then set the budget envelope:

```bash
factory budget set --per-hypothesis-usd 50 --daily-usd 50 --aggregate-usd 50
factory budget show
```

Expected: `factory budget show` echoes the new caps and lists `running_ledger: 0.0`. The values are written to a `FactoryControlEvent` under `runs/_control/events/`.

If `ConfigurationInvalid` fires, you passed mismatched units or an unknown flag -- spec 015 §6 lists the exact failure mode and exit code 2.

### Step 6 -- Seed literature discovery

```bash
factory discover --seed "<your topic here>"
```

The seed is a short natural-language phrase (e.g. "quasi-isodynamic stellarator MHD stability margins"). The command enqueues an OpenAlex traversal with the default policy from `config/literature.yaml` and exits as soon as the traversal is scheduled.

Expected output: a JSON envelope with `run_id`, the chosen `policy_hash`, and `status: "scheduled"`. The traversal itself completes in the background. Tail it with:

```bash
factory --format json status | jq '.literature.last_run'
```

Wait until `status: "complete"` and `gap_candidates_emitted >= 1`. Per spec 007, the traversal honours `max_depth`, `max_nodes`, and wall-clock caps from the policy. The PRD-003 user-journey explicitly allows an operator-supplied seed but **forbids** an operator-supplied hypothesis -- do not write the hypothesis yourself.

If `gap_candidates_emitted == 0`, broaden the seed and rerun. If two seeds produce zero candidates, the literature module is misconfigured -- check `runs/_control/operator.jsonl` for `event=discover_failed` entries and consult spec 007.

### Step 7 -- Launch the cycle

```bash
factory start --cycles 1 --format json 2>&1 | tee runs/_control/start-$(date +%Y%m%dT%H%M%S).log
```

`--cycles 1` is the PRD-003 envelope: exactly one autonomous cycle, then a clean stop (spec 015 §3). `--format json` streams structured events to stdout (spec 015 §5.3) so the log file becomes your primary post-mortem source.

Expected first events:
- `event=cycle_start` with a fresh `cycle_id`.
- `event=gate_entered` with `gate=G0`.
- `event=hypothesis_locked` with the hash of the autonomously generated `HypothesisSpec`.

If you do not see `hypothesis_locked` within 15 minutes of `cycle_start`, something upstream (Gap Miner or C1) is stuck -- jump to step 8 to monitor before assuming progress.

Do not close this terminal. The CLI is also the streaming consumer of the telemetry bus (spec 014).

### Step 8 -- Monitor the cycle

In a second terminal:

```bash
watch -n 15 'factory status --format text'
```

The status output (spec 015) includes: `current_cycle`, `gate`, `gate_dwell_seconds`, `budget_spent_usd`, and `last_council_session_id`. Expected wall-clock by gate, with hard ceilings (cycle is killed at the per-gate cap):

| Gate | Typical | Hard ceiling | Drives time |
| :--- | :--- | :--- | :--- |
| G0 (domain check) | < 1 s | 30 s | DB lookup only |
| G1 (falsifiability) | < 30 s | 5 min | One council-light LLM call |
| G1.5 (simulability) | 10 s - 2 min | 5 min | Selector + Catalog lookup |
| G2 (C1 worthiness) | 1 - 5 min | 15 min | 4 vendor-distinct OpenRouter calls × three stages |
| G2.5 (tractability dry-run) | 5 - 30 min | 1 h | One short solver run |
| G3 (surrogate + OOD) | 30 s - 5 min | 15 min | Inference + OOD score |
| G4 (validation portfolio) | 30 min - 8 h | 24 h | Full simulator run + cross-simulator check |
| G5 (C3 + C4) | 5 - 15 min | 30 min | Two council deliberations back-to-back |
| G6 (human gate) | n/a in Phase A | n/a | External publication is out of scope |

When the cycle reaches G5, the system writes the `RunReport` to the ledger and emits `cycle_complete`. The streaming CLI in terminal 1 exits with code 0 on clean completion. Capture the printed `cycle_id` -- everything else hangs off it.

### Step 9 -- Inspect the outcome

```bash
factory inspect <hypothesis-id>           # 7-char prefix accepted
factory --format json status | jq '.last_completed_cycle'
sqlite3 runs/ledger.db "SELECT hypothesis_id, result, provenance_hash, cost_usd FROM ledger WHERE cycle_id = '<cycle_id>';"
```

`factory inspect` returns the merged projection of the `HypothesisSpec`, `ExperimentSpec`, all `CouncilVerdict`s, the `RunReport` ID, and the final ledger row. Spec 015 §5.4 specifies the prefix resolver; `AmbiguousHypothesisId` means you need the full hash.

Expected ledger row: `result` is one of `passed | falsified | intractable | inconclusive`. **A null result is acceptable** -- PRD-003 §5 states the cycle is valid as long as the termination is correct. The goal of the first cycle is not a discovery; the goal is a verified loop.

Read the `RunReport` LaTeX source under `runs/<cycle_id>/artifacts/run_report_*.tex`. Confirm citations resolve against the local Paper Store (no fabricated BibTeX entries -- spec 011 forbids them).

---

## 3. Verification

Walk the full PRD-003 §4 success-criteria checklist. Every box must be checked, with the cited evidence path.

- [ ] **Cycle traversed G0 -> G6 without manual intervention.** Evidence: grep `event=gate_entered` in `runs/_control/start-*.log`; you should see one entry per gate (G6 is a no-op in Phase A but the state machine still records `gate=G6, decision=deferred`). Any `event=manual_intervention` entry disqualifies the run.
- [ ] **All four per-cycle councils (C1-C4) fired and emitted `CouncilVerdict`s.** Evidence: `ls runs/<cycle_id>/councils/` lists four `*.jsonl` transcripts plus four verdict JSON artifacts (each transcript records 4 vendor-distinct OpenRouter calls per FIX_PLAN §25.3). Confirm each `CouncilVerdict.chairman_decision` is non-empty.
- [ ] **At least one council deliberation contains preserved dissent.** Evidence: `jq '.preserved_dissents | length' runs/<cycle_id>/artifacts/council_verdict_*.json | sort -u`. At least one value must be `>= 1`. A zero across all four councils flags sycophancy and is a PRD-003 fail.
- [ ] **G4 validation portfolio executed all configured checks.** Evidence: `runs/<cycle_id>/validation/portfolio_report.json` has `checks_run` matching the configured list in `config/validation.yaml`; no entry has `status: skipped` unless `skip_reason` is explicitly documented.
- [ ] **Cross-simulator check ran (if Catalog supports it).** Evidence: `portfolio_report.json` includes a `cross_simulator_check` block with both `simulator_id_a` and `simulator_id_b` populated and a recorded residual. If your Catalog has no `EquivalencePair` for the observable in question, the cycle is not a valid PRD-003 acceptance run -- go back to step 3 and onboard a second simulator.
- [ ] **`RunReport` written to `EvidenceLedger` with full provenance hashes.** Evidence: the SQLite query in step 9 returns one row with non-null `provenance_hash`, `env_hash`, `code_hash`, `input_hash`, `seed`, `simulator_version`, and `container_sha`. Missing any of these is a spec 012 violation.
- [ ] **Total cost within `Budget` artifact's caps.** Evidence: `factory budget show` after completion -- `running_ledger <= per_hypothesis_usd`. Cross-check against `cost_usd` in the ledger row.
- [ ] **If cycle terminated as `intractable`, rollback completed cleanly.** Evidence: `find runs/<cycle_id>/staging -type f` returns nothing; `git status` is clean (no orphaned artifacts in tracked dirs). Spec 008's atomic-promote pattern guarantees this; absence of the guarantee is a Generator-Verifier bug.

Open a `postmortem.md` at the repo root (gitignored if you prefer) and paste the verification table with the evidence paths inline. PRD-003 §8 acceptance requires a written postmortem.

---

## 4. Troubleshooting

| Failure mode | Diagnosis | Recovery |
| :--- | :--- | :--- |
| `factory start` exits with `FactoryNotRunning` after a prior crash | Stale lock under `runs/_control/`; the prior process did not release cleanly. | `factory stop --force` clears the lock; rerun `factory start --cycles 1`. The `--force` is recorded as a `FactoryControlEvent`. |
| `CouncilSycophancyDetected` fires at C1 | Stage-1 pairwise cosine exceeded 0.85 (spec 001 §5.4; threshold restored from §24's 0.92 single-vendor bump back to the multi-vendor baseline per FIX_PLAN §25.4). The persona × vendor mix is collapsing into agreement. | Stop the cycle (`factory stop`), open `docs/runbooks/council-calibration.md`, rotate persona–vendor pairings first, then strengthen the Pessimist persona prompt; verify the 4-vendor lineup in §25.3 is intact (no silent substitution). Re-calibrate, restart. |
| `ChairmanDissentOmission` after both retries | Chairman call is collapsing dissent despite the strict re-prompt. | Rotate chairman via `--chairman-policy round_robin`; if the same vendor is chairman next cycle, switch `chairman_policy` to `weighted_by_cost` or `random` in `config/council/lineup.yaml`. Record in postmortem. |
| `PersonaRefusal` from one call | RLHF flattened the assigned persona on this vendor's turn (spec 001 §6). | First, rotate that persona to a different vendor in `persona_assignment`; some RLHF-aligned models refuse adversarial framing more than others. If a specific vendor consistently refuses the Pessimist persona across probes, mark that vendor unsuitable for Pessimist and pair it with Visionary or Pragmatist instead. Re-run calibration to confirm the new pairing holds the disagreement threshold. |
| OpenRouter rate limit on one vendor | Upstream vendor or OpenRouter passthrough returned 429 / quota-exceeded for one of the 4 council models. | Wait + retry per the SDK's exponential backoff. If the limit is persistent across retries, swap that vendor's model ID in `config/council/lineup.yaml` for an equivalent within the **same vendor family** (e.g., `openai/gpt-5.5` → `openai/gpt-5.5-preview`) to maintain the 4-vendor heterogeneity invariant. Never silently substitute a different vendor — vendor heterogeneity IS the defense. |
| G1.5 `parked_for_lack_of_tooling` | Selector found no Catalog entry that can compute the metric. | The hypothesis is out of scope for the current Catalog. Two paths: (a) accept the park and let the cycle exit clean -- this is still a valid PRD-003 run if other gates do not need to fire; (b) onboard the missing simulator via `docs/runbooks/catalog-onboarding.md` and re-seed discovery. |
| G2.5 dry-run cannot produce any valid output | Tractability filter is doing its job; this candidate is intractable. | The state machine marks the `ExperimentSpec` `intractable` and rolls back. No operator action needed. Verify rollback per the §3 checklist. |
| G3 surrogate disagrees with G4 oracle | Surrogate inherited training-set blind spots (spec 010); OOD detector did not catch this case. | Document in postmortem; do not "fix" the surrogate inside the cycle. Surface to C3 (Claim Interpretation) -- the disagreement is a learning signal, not a failure. |
| G4 cross-simulator check exceeds tolerance | The two simulators disagree on the observable beyond `EquivalencePair.tolerance`. | Treat as `inconclusive` per spec 009. Inspect both simulator outputs under `runs/<cycle_id>/validation/`; if one simulator looks pathological, quarantine it in the Catalog and re-run. |
| Cycle exceeds 72-hour wall clock | Per-gate timeout caps from spec 013 should have kicked in -- they did not. | Stop the cycle; this is a spec 013 enforcement bug. File an issue; rerun only after the timeout is verified in unit tests. |
| `CycleNotFound` when running `factory inspect` | Cycle ID typo or `runs/<cycle-id>/` was pruned. | Use the full ID from the streaming log; never trust shell history for IDs that contain dashes. |
| `TelemetryUnavailable` from `factory status` | Event bus (spec 014) is down or unreachable. Reads degrade to last-known snapshot with stale flag. | Restart the telemetry process; for the duration of the outage, monitor via `tail -f runs/<cycle_id>/cycle.jsonl` directly. Do not restart the factory itself unless a mutation is also failing. |
| OpenRouter passthrough rate limits cause cascading retries that blow the cost cap | Council Library (spec 001 §6) retries with backoff; `CouncilBudgetExceeded` should halt at the next stage boundary. | Verify the budget tracker caught it: `factory budget show` should report exactly `per_hypothesis_usd`, not more. If overspend occurred, file a spec 013 bug. Per-call `timeout_s` plus the Council's retry budget must be sized for OpenRouter's per-vendor passthrough latencies (see https://openrouter.ai/docs). |
| `RunReport` BibTeX references a paper not in the Paper Store | RAG writer (spec 011) fabricated a citation, which is forbidden. | Mark the RunReport `requires_revision` in the ledger; do not publish externally even via the G6 gate. This is a spec 011 violation; file an issue with the offending citation hash. |
| Cycle "completes" but the ledger has no row for it | Atomic promote did not run; the state machine likely crashed between G5 and the ledger write. | Inspect `runs/<cycle_id>/cycle.jsonl` for the last event before the gap. Replay with `factory replay <cycle_id> --dry-run` to confirm the artifacts on disk are intact, then manually invoke the ledger writer (spec 012 has a CLI for this in `factory.ledger`). Do not silently re-run the cycle -- that hides the failure. |

When in doubt, read `runs/<cycle_id>/cycle.jsonl` line by line. Every gate transition, every council session start, and every budget update is structured. The factory does not emit free-text log messages without a structured event name (architectural invariant 1.4).

---

## 5. Related

- **Spec backing this runbook:** `docs/specs/003-state-machine.md` (gate orchestration), with cross-references to:
  - `docs/specs/001-council.md` (C1-C4 plumbing)
  - `docs/specs/004-simulator-catalog.md` (G1.5 substrate)
  - `docs/specs/008-generator-verifier.md` (G2.5 + G4 candidate execution)
  - `docs/specs/009-validation-portfolio.md` (G4 deterministic checks)
  - `docs/specs/012-evidence-ledger.md` (G5 publication target)
  - `docs/specs/013-budget-tracker.md` (cost enforcement)
  - `docs/specs/015-operator-interface.md` (CLI surface used in every step)
- **Adjacent runbooks:**
  - `docs/runbooks/council-calibration.md` -- prerequisite (step 4 depends on it).
  - `docs/runbooks/catalog-onboarding.md` -- prerequisite (step 3 depends on it).
  - `docs/runbooks/operator-cli.md` -- mock-mode quickstart and CLI surface reference; useful for new operators before they attempt this runbook.
- **PRDs:**
  - `docs/prds/PRD-003-first-autonomous-cycle.md` -- this runbook's acceptance authority.
  - `docs/prds/PRD-001-phase-a-mvp.md` -- the broader Phase A envelope this cycle contributes to.
  - `docs/prds/PRD-002-council-library.md` -- council calibration prerequisite.
  - `docs/prds/PRD-004-simulator-catalog-v1.md` -- catalog prerequisite.
