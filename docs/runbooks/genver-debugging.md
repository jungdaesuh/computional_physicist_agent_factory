# Runbook: Debugging the Generator-Verifier Loop

> What this covers: triaging iteration-budget exhaustion, dollar-budget exhaustion, sandbox resource overruns, code-gen parse failures, local-gate misses, atomic-promote races, and adapter-unrecoverable terminations across the 10-iteration ReAct loop owned by spec 008. · When to use: a cycle terminated with `terminal_status` in `{intractable_iteration_cap, intractable_dollar_cap, intractable_adapter_failure}`, a sandbox subprocess returned non-zero, the operator alert raised `StagingPromoteRaced` or `RollbackFailed`, or you need to understand why a particular `HypothesisSpec` produced no promoted artifacts. · Estimated time: 15 minutes for a single failed iteration; 45 minutes for a full 10-iteration replay-and-diff postmortem.

## 1. Prerequisites

- A cycle ID with a generator-verifier run. Find it via `factory status` (active cycles) or by listing `runs/`. The relevant subtree is `runs/<cycle-id>/sandbox/`.
- The `Budget` artifact for the hypothesis (provides iteration cap, dollar cap, current ledger). Locate it under `runs/<cycle-id>/artifacts/`; type-filter via `runs/<cycle-id>/artifacts/MANIFEST.json`.
- The `ExperimentSpec` artifact (declares the domain adapter and fidelity ladder used by the loop). Same location.
- `factory` CLI on `$PATH` for cycle/run-level operator commands. Generator-Verifier inspection is per-module: confirm with `python -m factory.genver --help` ([TBD-impl] — the operator CLI does not enumerate a `factory genver` surface; debug invocations stay under `python -m factory.genver`).
- Optional: `git diff --no-index` for comparing two iterations' `blueprint.py` side-by-side when the loop's own `diff.patch` is hard to read.

Mental model: **the loop owns getting code to run; it does not own whether the science is right.** Spec 008 §5.10 is explicit — numerical gullibility and invariant hacking are downstream defenses (G3 surrogate, G4 portfolio). If the failure is "the candidate ran but produced physically wrong output", you are in the wrong runbook — see `validation-debugging.md`.

The loop has exactly four terminal states:
- `promoted` — at least one iteration passed the local gate and outputs are in `runs/<cycle-id>/artifacts/`.
- `intractable_iteration_cap` — 10 iterations elapsed without a local-gate pass.
- `intractable_dollar_cap` — `Budget.dollar_remaining <= 0` before the next iteration could start.
- `intractable_adapter_failure` — spec-006 adapter raised before code-gen produced runnable input, OR three consecutive resource-exceeded events.

The **10-iteration cap is a hard cap.** Do not raise it. The cap exists because beyond ~10 iterations the agent's correction loop becomes pathologically expensive without converging — empirically observed across multiple agent-science projects. If you find yourself wanting to raise it, the right fix is on the producer side: a better prompt, a better starting blueprint, or a different adapter. The cap is in `config/genver.yaml` and is also enforced as an upper bound in `Budget.iteration_cap` (spec 002).

## 2. Steps

### 2.1 Locate the sandbox directory

```bash
ls runs/<cycle-id>/sandbox/
# 000  001  002  003  MANIFEST.json
```

Each `NNN/` is one iteration. `MANIFEST.json` is the index — start there:

```bash
cat runs/<cycle-id>/sandbox/MANIFEST.json
```

The manifest's `iterations[]` array enumerates each iteration's `status` (one of `runtime_error`, `parse_failed`, `resource_exceeded`, `local_gate_failed`, `passed_local_gate`), `duration_s`, and `cost_usd`. The `terminal_status` field at the top tells you the loop outcome.

A typical failed-cycle manifest:
```json
{
  "cycle_id": "20260523-abc",
  "hypothesis_id": "HYP-…",
  "iterations": [
    {"index": 0, "status": "runtime_error",       "duration_s": 11.2,  "cost_usd": 0.04},
    {"index": 1, "status": "runtime_error",       "duration_s": 8.7,   "cost_usd": 0.03},
    {"index": 2, "status": "parse_failed",        "duration_s": 0.0,   "cost_usd": 0.01},
    ...
    {"index": 9, "status": "local_gate_failed",   "duration_s": 41.6,  "cost_usd": 0.05}
  ],
  "terminal_status": "intractable_iteration_cap"
}
```

If `MANIFEST.json` is absent, the loop crashed before its first atomic-manifest write. Check `runs/<cycle-id>/cycle.jsonl` filtered by `module=genver` for the very first error event.

### 2.2 Inspect a single failed iteration

```bash
python -m factory.genver inspect runs/<cycle-id> --iteration 3
```

Or by hand:
```bash
ls runs/<cycle-id>/sandbox/003/
# prompt.md  response.txt  tool_call.json  blueprint.py
# diff.patch  stdout.txt  stderr.txt  traceback.txt
# resource.json  adapter_outputs/  status.json
```

Read in order:
1. **`status.json`** — the iteration's own verdict. Contains `sandbox_outcome`, `traceback_summary`, and `local_gate_findings[]`. This is the highest-signal file.
2. **`traceback.txt`** — distilled traceback the loop passed to the next iteration's debugger turn. If empty, the iteration succeeded the sandbox but failed the local gate (look at `status.json.local_gate_findings`).
3. **`stderr.txt`** — full sandbox subprocess stderr. Use this if `traceback.txt` was truncated or missing.
4. **`resource.json`** — `{cpu_s, peak_memory_mb, wall_clock_s, disk_mb, max_open_files}`. Check against `config/genver.yaml` `sandbox_limits` to confirm resource-exceeded classification was correct.
5. **`blueprint.py`** — the candidate solver source. Compare against the previous iteration's via `diff.patch`.
6. **`response.txt`** — the raw LLM output. Useful when the parser flagged a malformed envelope and you want to confirm the LLM did or did not emit the expected ```` ```tool_call ```` fence.
7. **`prompt.md`** — the exact prompt the code-gen received. Includes the iteration history (previous iterations' tracebacks, diffs, local-gate findings). If the prompt fails to include the previous traceback, the loop is not feeding the debugger turn properly — file a bug against the prompt builder.

### 2.3 Inspect the diff between two iterations

```bash
python -m factory.genver diff-iterations <cycle-id> --from 002 --to 007
```

This concatenates `sandbox/003/diff.patch` through `sandbox/007/diff.patch` and renders a unified view of the agent's correction trajectory. Look for:
- **No-op diffs.** The agent rewrote semantically-identical code. Signals the agent did not understand the traceback.
- **Oscillation.** Iteration N reverts iteration N-1's change. Signals the agent is stuck between two failure modes.
- **Drift.** The blueprint diverges further from the initial structure with each iteration. Signals the agent's prompt-history budget compacted away critical context.

If you see oscillation or drift, the right fix is usually on the prompt side (more compact history, better system prompt) or on the adapter side (clearer error messages from the spec-006 adapter so the agent can correct). It is **not** to raise the iteration cap.

### 2.4 Check the Budget running ledger

```bash
factory budget show --hypothesis <hypothesis-id>
```

Expected:
```
hypothesis: HYP-...
dollar_cap: $1.00
dollar_spent: $0.32
dollar_remaining: $0.68
iteration_cap: 10
iterations_used: 4
running_ledger:
  iter=0 module=genver cost=$0.04 tokens=11823  "code_gen iteration 0"
  iter=1 module=genver cost=$0.03 tokens=10142  "code_gen iteration 1"
  ...
```

Each iteration's code-gen call is one ledger entry; sandbox compute is bounded by `sandbox_limits.cpu_seconds × max_iterations` and is *not* dollar-metered in Phase A. If `dollar_spent` ≥ `dollar_cap` while iterations remain, the terminal is `intractable_dollar_cap` and not `intractable_iteration_cap` — the distinction matters because the `relitigate_if` triggers differ.

If `dollar_spent` looks impossibly high for the number of iterations, you have a model-cost-reporting bug — confirm the code-gen client is reporting `cost_usd` correctly (some vendors return `null` and the loop falls back to a tokenizer estimate × max-tokens × per-token rate).

### 2.5 Categorize the failure shape

Match the terminal status to the underlying cause:

#### 2.5.1 `intractable_iteration_cap` — 10 iterations, no local-gate pass

The most common failure shape. Walk through the iterations in `MANIFEST.json`:
- **All `runtime_error`.** The agent never produced runnable code. Likely the system prompt or the adapter interface is unclear; inspect `prompt.md` in iteration 0 and confirm the spec-006 adapter's API surface is fully described.
- **Mostly `parse_failed`.** The model is not emitting the ```` ```tool_call ```` envelope at all. Check the iteration 0 `response.txt`; if the model is emitting natural-language explanation instead of a fenced block, the system prompt's envelope grammar is being ignored.
- **Mix of `runtime_error` and `local_gate_failed`.** The agent produces runnable code but the outputs fail the local gate's no-NaN / schema-match checks. Read `status.json.local_gate_findings` per iteration.
- **`resource_exceeded` early, recovered later, then `local_gate_failed`.** Likely the adapter's memory profile is too large for the configured `memory_mb` and the agent eventually shrunk the problem. Check `resource.json` deltas across iterations.

Do **not** raise the iteration cap. The fix is one of:
1. Improve the system prompt or task description so the agent gets it right faster.
2. Improve the spec-006 adapter's error messages so each iteration's traceback teaches the agent something useful.
3. Tighten the fixture data the agent is starting from in `ExperimentSpec.control_definition`.
4. Accept the `intractable` outcome — that is a legitimate result; the EvidenceLedger records the hypothesis as intractable and the state machine surfaces it for C5 review.

#### 2.5.2 `intractable_dollar_cap` — Budget exhausted

Two possible shapes:
- **Per-iteration cost ≪ cap, but lots of iterations.** Self-explanatory — the agent burned budget on near-no-ops. Same fix list as iteration-cap exhaustion.
- **One iteration burned half the budget.** Unusual. Inspect `running_ledger`; if a single `cost_usd` is ≫ the others, the model returned a huge response (output token blowout). Often a sign of an LLM hallucination loop where the model emits page after page of natural language instead of a `tool_call`. Fix: tighten `max_tokens_per_call` in `config/genver.yaml` (Phase A default is 8192) or short-circuit responses that exceed a length threshold.

#### 2.5.3 `intractable_adapter_failure` — adapter raised before code-gen

Two paths into this terminal:
- **`AdapterFailureUnrecoverable` raised on iteration 0 before any code-gen call.** The spec-006 adapter rejected the experiment outright — typically a missing simulator binary, a malformed `ExperimentSpec.control_definition`, or a container-build failure. Check `cycle.jsonl` for the first `module=genver` error event; it carries the adapter's reason.
- **Three consecutive `resource_exceeded` events escalated.** The loop reached its three-strikes ceiling on resource overruns. Inspect `resource.json` across the three failing iterations; if all three failed on the same resource (e.g., memory), bump `sandbox_limits.<kind>` in `config/genver.yaml`. If the resource differs each iteration, you have a genuine adapter-unstable situation and should raise the issue with the adapter's owner.

#### 2.5.4 `SandboxResourceExceeded(kind=...)` per-iteration

Even when the *terminal* status is something else, individual iterations may have been marked resource-exceeded. The detail:

| kind | Most common cause | First fix |
| :--- | :--- | :--- |
| `cpu` | Code-gen wrote a Python-level loop where it should have called a vectorized adapter API | Inspect `blueprint.py`; the next iteration's prompt history will surface this; if the prompt did not include the traceback summary clearly, audit the prompt builder |
| `memory` | Allocated a full mesh in Python before handing to the adapter | Sandbox limit hit by `RLIMIT_AS`; bump `memory_mb` only if the adapter genuinely requires it for the smallest non-toy problem |
| `wall_clock` | Solver did not converge within `wall_clock_seconds` | Likely a convergence problem, not a budget problem — fix the solver / adapter, not the limit |
| `disk` | Adapter wrote oversized intermediate files | `du -sh runs/<cycle-id>/sandbox/<i>/adapter_outputs/`; if intermediates are large, either trim them in the adapter or bump `disk_mb` |
| `file_descriptor` | Adapter leaked file handles | Bug in adapter; do not raise `max_open_files` to compensate |

### 2.6 Triage `CodeGenParseFailed`

Inspect `response.txt` and `tool_call.json` (the latter absent on parse failure):

```bash
head -40 runs/<cycle-id>/sandbox/<i>/response.txt
test -f runs/<cycle-id>/sandbox/<i>/tool_call.json && echo "parsed" || echo "no envelope"
```

Parser rules (spec 008 §4.4): a single ```` ```tool_call ```` fenced block, JSON-valid body, `tool_name == "write_solver_blueprint"`, non-empty `blueprint_source` that AST-parses as Python ≥3.10, and `blueprint_metadata` matching the adapter's declared schema. One auto-reformat retry happens inside the same iteration; only the second failure marks the iteration `parse_failed`.

If you see repeated `parse_failed`:
1. **Model-side issue.** The configured `code_gen_model.model_id` does not respect fenced-block instructions reliably. Swap to a stronger model via `config/genver.yaml`.
2. **Prompt-side issue.** The system prompt's envelope grammar example is malformed or the parser's strictness exceeds the prompt's description. Reconcile `factory/genver/prompts/system.md` against `factory/genver/parser.py`.

### 2.7 Triage `AdapterFailureUnrecoverable` raised mid-loop

If three consecutive `resource_exceeded` events escalated to this terminal, see §2.5.3.

If the adapter raised before code-gen on a later iteration (rare — usually iteration 0), the most likely cause is a simulator binary disappearing mid-run (container restart, host migration, OOM kill). Confirm by checking `cycle.jsonl` for non-genver events around the same timestamp:

```bash
jq 'select(.cycle_id == "<cycle-id>" and .level == "error")' runs/<cycle-id>/cycle.jsonl
```

If the simulator-side event (`module=adapter` or `module=catalog`) shows a container kill, the fix is infrastructure, not loop config.

### 2.8 Handle `StagingPromoteRaced` (infrastructure failure)

This is a *hard halt*. The atomic-promote pseudocode (spec 008 §5.6):
```
tmp = mkdtemp(dir=artifact_root, prefix="promote-")
... copy files in, os.replace each one ...
if any(tmp.iterdir()): raise StagingPromoteRaced
```

Means: after the per-file `os.replace` loop, the tmp dir was non-empty. Another process (or another loop instance, which should not exist in Phase A) touched the tmp dir. Diagnostic:

```bash
ls -la runs/<cycle-id>/artifacts/promote-*
# the tmp dir is preserved on this failure; contents tell you what was not moved
```

Phase A treats this as terminal `intractable_adapter_failure` — staging is preserved for forensics, the operator is alerted. Recovery: confirm only one factory process is running on the cycle directory; restart the cycle with the same `Budget` (the iteration cap is unaffected — the loop never reached its 10th iteration).

### 2.9 Handle `RollbackFailed`

`wipe_staging(run_dir/sandbox/)` raised a filesystem error during cleanup on a non-promoted terminal. The cycle is halted; staging is left on disk so a postmortem can inspect it. Most common cause: a stale file lock from an editor or `tail -f` on a file under `sandbox/<i>/`. Identify with `lsof | grep runs/<cycle-id>/sandbox/`; close the offending process; manually clean up the staging tree once forensics is complete.

### 2.10 Handle orphaned staging after a promote race

If `runs/<cycle-id>/sandbox/<i>/adapter_outputs/` is non-empty AND `runs/<cycle-id>/artifacts/` shows a partial promote (some hashes present, others absent), you have an orphaned staging directory. **Do not manually move files into `artifacts/`** — that bypasses the hash-verification step and leaves the EvidenceLedger inconsistent. Instead:

1. Confirm via `python -m factory.genver replay <cycle-id>` what the loop thinks the terminal status is. If `replay()` reconstructs the iteration history and reports `promoted` for the iteration whose `adapter_outputs/` is non-empty, the loop's view of the world is correct — the partial promote is an artifact of `os.replace` having succeeded for some files but not others on the same filesystem (which should be impossible for POSIX `rename(2)` — file an infra bug if you see it).
2. If `replay()` reports `intractable_*`, the partial files in `artifacts/` are themselves orphans — delete them after confirming no `EvidenceLedgerEntry` references those hashes.

### 2.11 Run `replay()` to reconstruct without re-executing

```bash
python -m factory.genver replay runs/<cycle-id>
```

Walks `runs/<cycle-id>/sandbox/` and reconstructs the `IterationRecord` sequence without re-running anything (no LLM calls, no sandbox launches). Useful after a crash to confirm what the on-disk state implies the loop did.

## 3. Verification

After applying any fix, confirm:

1. **The loop's terminal state changed as expected.** Re-run the cycle in mock mode and inspect `sandbox/MANIFEST.json`:
   ```bash
   python -m factory.genver run --experiment-fixture <fixture> --mock-mode
   cat runs/<new-cycle-id>/sandbox/MANIFEST.json
   ```
2. **Budget accounting matches the iteration ledger.** `Budget.running_ledger`'s sum equals `factory budget show --hypothesis <id>` `dollar_spent`. Spec 013 owns this enforcement; this runbook only verifies it.
3. **The iteration cap is still 10.** `grep max_iterations config/genver.yaml` — must be `10`. If you raised it, revert.
4. **The sandbox limits are sane.** `grep -A6 sandbox_limits config/genver.yaml` — confirm `cpu_seconds`, `memory_mb`, `wall_clock_seconds`, `disk_mb`, `max_open_files` are within reasonable ranges (defaults: 600 / 4096 / 1800 / 512 / 256).
5. **The parser still rejects malformed envelopes.** Run the parse-failure unit test:
   ```bash
   pytest factory/genver/tests/test_parse_retry.py -q
   ```
6. **The atomic-promote test passes.** Especially if you touched anything near `promote_atomic`:
   ```bash
   pytest factory/genver/tests/test_atomic_promote_idempotent.py factory/genver/tests/test_atomic_promote_race.py -q
   ```
7. **No artifacts leaked into `runs/<cycle-id>/artifacts/` on a non-promoted terminal.** `ls runs/<cycle-id>/artifacts/` should be empty when `MANIFEST.json.terminal_status` is one of the `intractable_*` values. If artifacts are present without a corresponding `promoted` terminal, the rollback contract was violated — file a bug.
8. **Telemetry events are emitted.** If spec 014 is wired, `grep iteration_start runs/<cycle-id>/cycle.jsonl | wc -l` equals the number of iterations the loop ran. Off-by-one suggests the iteration boundary event is mis-wired.

## 4. Troubleshooting

| Symptom | Likely cause | First action |
| :--- | :--- | :--- |
| Loop terminates with `intractable_iteration_cap` after 10 `runtime_error` iterations | Adapter API unclear; agent cannot produce runnable code | Read iteration 0's `prompt.md`; confirm the spec-006 adapter's declared schema is present. Fix the prompt or the adapter — not the cap |
| All iterations show `parse_failed` | Model not emitting fenced `tool_call` block | Inspect `response.txt`; consider a stronger code-gen model in `config/genver.yaml` |
| Iteration 0 spent the entire Budget | LLM emitted an enormous response (token blowout) | Lower `max_tokens_per_call`; cap response length at the client level |
| `resource_exceeded(kind=memory)` after a single iteration's blueprint was visibly small | Adapter's Python-level imports allocate before the blueprint runs | Profile via `python -c 'import <adapter>'` outside the sandbox; if imports themselves exceed limit, the adapter has a config bug |
| `resource_exceeded(kind=wall_clock)` while CPU usage stays low | Solver waiting on I/O (network, lock); should never happen inside the import whitelist | Audit the adapter for hidden network calls — sandbox is supposed to forbid these, but the whitelist may have a hole |
| Three resource-exceeded events escalate but each was a *different* kind | Adapter unstable across iterations | Open an issue against the adapter owner; loop is doing the right thing |
| `StagingPromoteRaced` raised on a single-process system | Filesystem-level mount issue (NFS, overlayfs without atomic rename support) | Confirm `runs/` is on a POSIX-compliant local filesystem; do not deploy on filesystems where `rename(2)` is not atomic |
| `RollbackFailed` raised while `factory inspect` was running on the same staging directory | Editor or inspect tool holding a file handle | Close inspector, retry. Long-term, the loop should not race with read-only inspectors — if this recurs, file a bug |
| `python -m factory.genver replay` reports a different iteration count than `MANIFEST.json` | Manifest written non-atomically (older bug) or manual edits to `MANIFEST.json` | Trust `replay()`; regenerate manifest via `python -m factory.genver replay --write-manifest` |
| Atomic-promote idempotency check fires often | Two cycles legitimately produced identical outputs (rare) or a previous cycle was re-run without clearing `artifacts/` | Spec 008 §5.6: idempotency by hash-equality is correct; if the rates are concerning, investigate why cycles repeat |
| `parse_failed` with response visibly containing a `tool_call` block | Parser strict-mode triggered on a JSON encoding issue (smart quotes, trailing comma) | Inspect `response.txt` raw bytes; if the model is emitting non-ASCII quotes, tighten the system prompt's instruction set |
| Iterations 5-9 all show `local_gate_failed` with the same finding | Agent stuck in a corrective dead end | Diff iteration 5 vs iteration 9 blueprint; if essentially identical, the agent does not know how to fix the local-gate finding — improve the local gate's diagnostic message |
| `diff.patch` empty on iteration N > 0 | Agent emitted identical blueprint twice in a row | Acceptable but signals wasted iteration; if frequent, prompt history is failing to discourage no-ops |
| `python -m factory.genver inspect` reports an iteration that does not exist on disk | Stale `MANIFEST.json` | Regenerate via `replay --write-manifest` |
| Cost per iteration much higher in live mode than mock | Live LLM cost reporting differs from fixture cost | Expected; mock costs are a sentinel value, live costs are the vendor's reported number |

## 5. Related

- Spec 008 (Generator-Verifier Loop) — owns the loop, the sandbox, the local gate, and the atomic-promote contract.
- Spec 006 (Domain Adapter) — owns the abstract solver interface the loop targets. If the failure is "the adapter raised", that spec is where the fix lives.
- Spec 013 (Budget Tracker) — owns the running ledger and the cap enforcement. If the budget numbers look wrong, that spec is the canonical source.
- Spec 003 (Gate State Machine) — owns the dispatch into and out of this loop. Routes `intractable_*` terminals to `terminate_intractable` and `promoted` terminals to G3.
- `docs/specs/008-generator-verifier.md` §5.10 (Numerical gullibility and invariant hacking — explicit non-defense) — required reading before assuming the loop should catch a physics bug.
- `docs/specs/008-generator-verifier.md` §5.8 (Rollback contract) — the precise semantics of "wipe" vs "preserve" on terminal.
- `runbooks/artifacts-debugging.md` — if a `GenVerResult`'s `promoted_artifact_hashes` contains a hash that fails validation downstream, that runbook covers the artifact side.
- `runbooks/validation-debugging.md` — sibling runbook for G4; if the loop promoted artifacts but G4 then failed, that is the next stop.
- `runbooks/operator-cli.md` — operator surface for restarting the cycle (`factory replay`, `factory budget set --aggregate-usd`).
- `factory/genver/tests/test_genver_typical_usage.py` — the canonical 3-iteration trace; copy this pattern when writing a new genver-adjacent test.
- `ARCHITECTURE.md` §4.2 (No silent failures) and §4.3 (Idempotent operations) — the invariants this runbook protects.
