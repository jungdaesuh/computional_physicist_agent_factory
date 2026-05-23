# Spec 008: Generator-Verifier Loop

> Status: ☐ not started · Owner: TBD · Last updated: 2026-05-23

## CONTEXT (60-second summary — read first)
- The **Generator-Verifier Loop** is a multi-turn ReAct agent loop that proposes solver-blueprint code targeting the abstract solver interface (spec 006), executes it inside a subprocess-level sandbox, and on success atomically promotes outputs to the cycle's artifact store. On failure, a debugger turn intercepts the traceback and the loop iterates. Hard cap: 10 iterations per `HypothesisSpec`, with no retries beyond the cap.
- The 5 facts: (1) the loop only gets code to *execute* — it does NOT validate that the code solves the science problem (that is G3 surrogate + G4 portfolio, specs 010 and 009); (2) the sandbox is subprocess-level, not Docker — millisecond startup, restricted filesystem under `runs/<cycle-id>/sandbox/<iteration:03d>/`; (3) staging + atomic promote: outputs land in a per-iteration staging directory and are only moved into `runs/<cycle-id>/artifacts/` after the iteration passes the loop's local gate; (4) iteration budget (10) and dollar budget are enforced via `BudgetTracker` (spec 013) — the loop never reads the frozen `Budget` artifact directly for live state; (5) the same `hypothesis_id` is not re-attempted unless `relitigate_if` fires in the `EvidenceLedger` (spec 012) — that lookup happens at G0 in the state machine, not inside this loop.
- Open first: `factory/genver/api.py` and `factory/genver/tests/test_genver_typical_usage.py`. The clearest single-page picture is the iteration trace fixture at `factory/genver/fixtures/traces/sample_three_iterations.jsonl`.

## ENTRY POINTS
- Main module: `factory/genver/api.py`
- Typical-usage test: `factory/genver/tests/test_genver_typical_usage.py`
- CLI: `python -m factory.genver --help` (subcommands: `run`, `replay`, `inspect`, `diff-iterations`)
- Mock-mode example: `python -m factory.genver run --experiment-fixture sample --mock-mode`
- Runbook: `docs/runbooks/genver-debugging.md`

## LOCAL DEBUG
- Instantiate without API keys or simulators: `GenVerLoop(adapter=MockAdapter(), code_gen=MockCodeGen(), tracker=BudgetTracker.from_fixture("small")).run(spec)` returns a deterministic terminal result from `factory/genver/fixtures/traces/`.
- Live mode requires: (a) `OPENROUTER_API_KEY` (FIX_PLAN §25.6 — single env var for all LLM access; the loop's code-gen call goes through the shared OpenRouter client at `google/gemini-3.5-flash`; it is NOT a council), (b) the domain adapter (spec 006) wired to a real simulator, (c) `factory.ledger` reachable so the G0 dedup lookup completes upstream, (d) a `BudgetTracker` instance (spec 013) opened against the hypothesis.
- Common error signatures → recovery:
  - `IterationBudgetExhausted` → routed by state machine to `terminate_intractable`; no artifacts promoted; staging wiped; ledger entry records final traceback summary.
  - `DollarBudgetExhausted` → same routing as `IterationBudgetExhausted`; ledger entry distinguishes the cause.
  - `SandboxResourceExceeded(kind=cpu|memory|wall_clock|disk|file_descriptor)` → current iteration is recorded as a failed step; debugger turn receives the resource-exceeded class as part of the traceback; if three consecutive iterations exceed resources, escalate as `AdapterFailureUnrecoverable`.
  - `AdapterFailureUnrecoverable` → adapter (spec 006) raised before code-gen even produced runnable input (e.g., simulator binary missing); halt loop; route to `terminate_intractable`; ledger entry blames adapter, not code-gen.
  - `CodeGenParseFailed` → code-gen response could not be parsed into the required ReAct `tool_call` envelope; one auto-reformat retry inside the same turn; on second failure the iteration counts as consumed and the loop continues with a debugger turn.
  - `StagingPromoteRaced` → another process touched the staging directory between the loop's final validation and `os.replace`; this is a bug, not a recoverable runtime; halt cycle.
  - `RollbackFailed` → staging cleanup failed (filesystem error); halt cycle with operator alert; staging is left on disk for forensics.
- Logs to inspect:
  - `runs/<cycle-id>/sandbox/<iteration:03d>/` — per-iteration code, stdout, stderr, resource ledger, diff vs previous iteration.
  - `runs/<cycle-id>/sandbox/<iteration:03d>/adapter_outputs/<seed>/` — per-seed adapter output bundle (one subdirectory per seed declared in `ExperimentSpec.seed_set`).
  - `runs/<cycle-id>/cycle.jsonl` filtered by `module=genver` — one event per loop turn boundary, plus one event per sandbox lifecycle (`factory.genver.sandbox_open`, `factory.genver.sandbox_exit`).
  - `runs/<cycle-id>/sandbox/MANIFEST.json` — index of iteration dirs with their status (`failed_runtime`, `failed_parse`, `passed_local_gate`, `promoted`, `wiped`).

## DEPENDENCIES
- **Hard:** Spec 002 (artifacts) — reads `HypothesisSpec`, `ExperimentSpec`, `Budget`; emits a `GenVerResult` typed result (NOT a top-level artifact — the state machine writes the downstream `EvidenceLedgerEntry`). Spec 006 (domain adapter) — every sandbox execution dispatches through the adapter so the loop is simulator-agnostic; per-seed outputs land under `adapter_outputs/<seed>/run_artifacts.json` per the spec 006 contract. Spec 013 (budget tracker) — every iteration cost is reported through `tracker.record(...)`; the tracker enforces the per-hypothesis dollar, token, wall-clock, and iteration caps. Spec 003 (state machine) — consumes `GenVerResult.terminal_status` (mapped to `GateOutcome` via the `to_gate_outcome()` method documented in §3) for gate routing.
- **Soft:** Spec 001 (council) — if the operator opts into council-mediated code-gen selection (Phase B), the loop calls `Council.deliberate(...)` to pick which of several proposed code mutations to execute first. In Phase A the dispatcher invokes one model per iteration, with no council involvement. Spec 014 (telemetry) — emits per-iteration events when wired; event names declared in `factory/genver/events.py` under the `factory.genver.*` namespace. Spec 012 (ledger) — read for the G0 dedup lookup the state machine performs *before* invoking this loop; the loop does not itself query the ledger. `specs/016-strategy-archive.md` (FIX_PLAN §26.4) — when `StrategyArchiveConfig.enabled=True` and `parallel_lineages_k > 1`, the loop receives a `parent_strategy_sha: str` per iteration from `StrategyArchive.select_lineages(k)` so the code-gen prompt can carry the active strategy lineage; otherwise (Phase A default: `parallel_lineages_k=1`) the loop runs un-parented as today, with `parent_strategy_sha=None`. On each iteration end the loop emits `StrategyCycleEvidence` (spec 002 artifact) which the archive consumes via `attribute_surprise(...)` and `attribute_reward(...)`.
- **Mocks available:**
  - `MockCodeGen` — replays a recorded code-mutation sequence from `fixtures/code_gen_replays/`; supports forcing parse failure, runtime failure, and "success on iteration N" patterns.
  - `MockAdapter` — implements the spec-006 abstract solver interface with deterministic fixture outputs; supports forced resource-exceeded.
  - `MockSandbox` — runs the code in-process under restricted globals (for unit testing only — never used in live mode).
  - `BudgetTracker.from_fixture("small")` — 10-iteration / $1 cap envelope for tests.

---

## 1. Summary

The Generator-Verifier Loop is the factory's **code-execution substrate**. The state machine (spec 003) invokes the loop at G2.5 (tractability dry-run) and again post-G4 when the validation portfolio needs a specific solver instantiation. The loop owns nothing scientific — it owns *getting code to run*. Whether the code that ran *also solves the problem* is decided downstream by the surrogate (spec 010), the validation portfolio (spec 009), and ultimately the interpretation/peer-review councils at G5.

The loop is intentionally narrow:

1. A **code-gen turn** asks one LLM model for a solver-blueprint mutation targeting the abstract solver interface (spec 006). The model's output is parsed as a single ReAct `tool_call` envelope.
2. A **sandbox turn** runs the candidate code through the domain adapter inside a subprocess-level sandbox with hard resource limits.
3. On runtime error, a **debugger turn** feeds the traceback (and a short summary of the offending source span) back to the code-gen model. The next iteration begins.
4. On runtime success, the loop runs its own **local gate** — a strictly mechanical set of checks (output schema matches what the spec-006 adapter declared, no NaNs in the canonical output tensor, success/failure flags present). The local gate is NOT scientific validation; it is the minimum signal needed to decide whether to promote.
5. On local-gate pass, outputs are **atomically promoted** from the per-iteration staging directory to the cycle's artifact store. The `GenVerResult` is returned to the state machine.
6. On budget exhaustion (iteration cap or dollar cap), the loop terminates with an `intractable` result. Staging's `adapter_outputs/` subtrees are wiped per §5.8. No artifacts are promoted. There are no retries beyond the 10-iteration cap.

Numerical gullibility and invariant hacking — the dominant failure modes from `SPEC.md` §10.2–10.3 — are NOT defended by this loop alone. The loop will happily run code that produces plausible-looking numerics that are physically wrong, or code that satisfies named invariants by construction without solving the problem. The defenses live downstream:

- **G2.5 tractability dry-run** uses *this* loop on a toy problem so we observe non-trivial output before committing real budget.
- **G3 surrogate** (spec 010) catches obviously-implausible candidates before oracle execution.
- **G4 validation portfolio** (spec 009) is the actual scientific defense — held-out symmetry tests, refinement convergence, cross-simulator checks.

Specs that confuse "the loop ran" with "the science is right" will be rejected at review.

## 2. Scope

**In scope:**
- Multi-turn ReAct loop with iteration budget (10) and dollar budget enforcement (delegating to spec 013's `BudgetTracker`).
- Subprocess-level sandbox with restricted filesystem access, CPU/memory/wall-clock/disk/file-descriptor limits.
- Per-iteration staging directory under `runs/<cycle-id>/sandbox/<iteration:03d>/`.
- Per-seed adapter output bundle under `runs/<cycle-id>/sandbox/<iteration:03d>/adapter_outputs/<seed>/`.
- Atomic promotion of accepted outputs from staging to `runs/<cycle-id>/artifacts/`.
- Rollback on budget exhaustion (wipe `adapter_outputs/` subtrees; no partial promote; preserve per-iteration code + diffs + logs for forensics).
- Diff-based iteration tracking (`diff.patch` per iteration vs previous).
- One LLM model per iteration (no in-loop council in Phase A); model is `google/gemini-3.5-flash` dispatched through the **shared OpenRouter client** (FIX_PLAN §25.2) — the same `openai`-SDK-backed client surface the council uses, but with a single-shot interface (no persona, no stages, no chairman).
- Code-gen output parsed as a strict ReAct `tool_call` envelope; one auto-reformat retry on parse failure.
- Local gate (output schema match, no NaNs in canonical tensor, success flag present) — strictly mechanical, no LLM involvement.
- A `GenVerResult` typed result with a granular `terminal_status` and a `to_gate_outcome()` mapping method for spec 003 consumption.
- CLI: `run`, `replay`, `inspect`, `diff-iterations`.
- Mock mode covering: deterministic code-gen, deterministic adapter, in-process sandbox, fixture traces.

**Out of scope:**
- Any judgment about whether the code is physically correct (specs 009, 010).
- Council-mediated code-gen selection (Phase B; this spec exposes a hook but Phase A does not invoke it).
- Code-gen across multiple simulator adapters in a single iteration (spec 006 owns simulator-specific concerns).
- LLM choice / lineup / persona logic (this loop dispatches one configured model per iteration; no persona).
- EvidenceLedger writes (spec 012; the state machine does this after the loop returns).
- Container builds (spec 004 — the simulator container is built once and reused; the loop's sandbox is not a container).
- Continuous reuse of sandbox processes across iterations (each iteration is a fresh subprocess for hermeticity).
- Auto-tuning the budget (spec 013).
- Retries beyond the 10-iteration cap (a fresh cycle is the only "retry" mechanism, governed by `EvidenceLedger.relitigate_if`).

## 3. Public Interface

> **LLM access (FIX_PLAN §25.2).** The code-gen turn uses
> `code_gen.generate(prompt) -> CodeGenResponse`; the underlying call is the shared
> OpenRouter client (`openai` SDK, base URL `https://openrouter.ai/api/v1`) with
> `model="google/gemini-3.5-flash"`. There is no Gemini-direct SDK import
> (`from google import genai` is forbidden); the only LLM env var is
> `OPENROUTER_API_KEY`. `BudgetTracker.record(cost_usd=..., tokens=...)` is called
> from the OpenRouter response's `usage` block (`prompt_tokens` + `completion_tokens`).
> (§25 supersedes §24's Gemini-only constraint and restores multi-vendor council in
> spec 001; this loop remains single-model — `google/gemini-3.5-flash` is the cheap
> agentic default for code-gen.)

```python
# factory/genver/api.py

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from factory.artifacts import (
    ArtifactHash, HypothesisSpec, ExperimentSpec, Budget,
    CycleId, HypothesisId,
)
from factory.budget import BudgetTracker
from factory.state_machine import GateOutcome

class GenVerError(FactoryError): ...
class IterationBudgetExhausted(GenVerError): ...
class DollarBudgetExhausted(GenVerError): ...
class SandboxResourceExceeded(GenVerError):
    kind: Literal["cpu", "memory", "wall_clock", "disk", "file_descriptor"]
class AdapterFailureUnrecoverable(GenVerError): ...
class CodeGenParseFailed(GenVerError): ...
class StagingPromoteRaced(GenVerError): ...
class RollbackFailed(GenVerError): ...

class CodeGenClient(Protocol):
    """Single-shot LLM client used for one code-gen turn per iteration.
    Not the same as spec 001's Council surface — there is no persona, no
    stages, no chairman. The loop dispatches one model per iteration and
    parses the response as a strict ReAct tool_call envelope.

    Per FIX_PLAN §25.5, the underlying call is the shared OpenRouter client
    (`openai` SDK, `model="google/gemini-3.5-flash"`). Cost + tokens are
    populated from the OpenRouter response's `usage` block.
    """
    def generate(
        self,
        prompt: str,
        max_tokens: int,
        timeout_s: float,
    ) -> "CodeGenResponse": ...

@dataclass(frozen=True)
class CodeGenResponse:
    raw_text: str
    parsed_tool_call: "ToolCall | None"     # None when parse failed
    cost_usd: float
    tokens_in: int
    tokens_out: int

@dataclass(frozen=True)
class ToolCall:
    tool_name: Literal["write_solver_blueprint"]
    blueprint_source: str                    # Python source targeting spec-006 interface
    blueprint_metadata: dict                 # adapter-declared schema

@dataclass(frozen=True)
class SandboxLimits:
    allowed_write_root: Path                 # REQUIRED; MUST be a per-iteration staging dir
                                             # under runs/<cycle-id>/sandbox/<iteration:03d>/
    cpu_seconds: int = 600
    memory_mb: int = 4096
    wall_clock_seconds: int = 1800
    disk_mb: int = 512
    max_open_files: int = 256

@dataclass(frozen=True)
class IterationRecord:
    iteration_index: int                     # 0-based
    code_gen_cost_usd: float
    sandbox_outcome: Literal[
        "parse_failed", "runtime_error",
        "resource_exceeded", "local_gate_failed",
        "passed_local_gate",
    ]
    sandbox_duration_s: float
    sandbox_peak_memory_mb: float
    traceback_summary: str | None            # short string suitable for next debugger turn
    diff_path: Path                          # diff.patch vs previous iteration's blueprint
    staging_dir: Path                        # absolute path under runs/<cycle-id>/sandbox/<iteration:03d>/

@dataclass(frozen=True)
class GenVerResult:
    """Returned to the state machine after the loop terminates."""
    cycle_id: CycleId
    hypothesis_id: HypothesisId
    iterations: list[IterationRecord]
    terminal_status: Literal[
        "promoted",                          # last iteration passed local gate; outputs in artifacts/
        "intractable_iteration_cap",
        "intractable_dollar_cap",
        "intractable_adapter_failure",
    ]
    promoted_artifact_hashes: list[ArtifactHash]   # empty unless terminal_status == "promoted"
    total_cost_usd: float
    total_wall_clock_s: float

    def to_gate_outcome(self) -> GateOutcome:
        """Map granular terminal_status to the canonical spec-003 GateOutcome.

        Mapping:
          promoted                       -> GateOutcome.PASS
          intractable_iteration_cap      -> GateOutcome.INTRACTABLE
          intractable_dollar_cap         -> GateOutcome.INTRACTABLE
          intractable_adapter_failure    -> GateOutcome.INTRACTABLE

        The state machine reads this method's return value to choose the next
        route in `gate_routes.yaml`. The granular terminal_status is preserved
        on the EvidenceLedgerEntry for forensics and to populate
        `relitigate_if` triggers.
        """

class GenVerLoop:
    def __init__(
        self,
        code_gen: CodeGenClient,
        adapter: "AbstractSolverAdapter",    # spec 006
        tracker: BudgetTracker,              # spec 013 — live budget authority
        budget: Budget,                      # spec 002 — frozen caps artifact (audit reference)
        hypothesis_id: HypothesisId,
        cycle_id: CycleId,
        run_dir: Path,
        sandbox_limits: SandboxLimits,       # REQUIRED; no default — allowed_write_root has no default
        max_iterations: int = 10,
        parse_retry_count: int = 1,
        mock_mode: bool = False,
    ) -> None: ...

    def run(
        self,
        hypothesis: HypothesisSpec,
        experiment: ExperimentSpec,
        parent_strategy_sha: str | None = None,
    ) -> GenVerResult:
        """Execute the loop. Returns a GenVerResult.
        Never raises for normal failure modes (parse, runtime, resource, budget) — those
        are encoded in IterationRecord / terminal_status. Only raises for unrecoverable
        infrastructure errors (StagingPromoteRaced, RollbackFailed, AdapterFailureUnrecoverable).
        Failures propagate to the state machine without defensive interception.

        `parent_strategy_sha` (FIX_PLAN §26.4) — optional strategy lineage anchor sourced
        from `StrategyArchive.select_lineages(k)` (`specs/016-strategy-archive.md`). When
        `StrategyArchiveConfig.enabled=True` and `parallel_lineages_k > 1`, the caller
        (state machine) passes the lineage sha so the code-gen prompt can carry the
        active strategy context. Phase A default is `None` (un-parented run, backward
        compatible). On each iteration end the loop emits a `StrategyCycleEvidence`
        artifact (spec 002) keyed by this sha for the archive to attribute surprise and
        reward against.
        """

    def replay(self, sandbox_root: Path) -> list[IterationRecord]:
        """Walk persisted sandbox/<iteration:03d>/ directories and reconstruct IterationRecords
        without re-running anything. Used by `python -m factory.genver replay`.
        """
```

The state machine consumes `GenVerResult.to_gate_outcome()` to route to the next gate via `config/gate_routes.yaml`. When the outcome is `PASS`, `promoted_artifact_hashes` are added to the cycle's input bundle and forwarded to G3 / G4 dispatch (specs 010 and 009). The granular `terminal_status` is preserved on the downstream `EvidenceLedgerEntry` so `relitigate_if` triggers can distinguish "iteration cap raised" from "dollar cap raised" from "adapter version updated."

## 4. Data Structures / Schemas

### 4.1 Per-iteration staging directory layout

Each iteration writes everything to `runs/<cycle-id>/sandbox/<iteration:03d>/`. The directory is created fresh per iteration (no reuse across iterations). Adapter outputs are bucketed per seed under `adapter_outputs/<seed>/`, matching the canonical sandbox layout (FIX_PLAN §7) shared with spec 006.

```
runs/<cycle-id>/sandbox/004/
├── prompt.md                       The exact prompt the code-gen model received.
├── response.txt                    The raw LLM response (verbatim, before parsing).
├── tool_call.json                  Parsed ToolCall envelope (absent if parse failed).
├── blueprint.py                    The candidate solver blueprint source.
├── diff.patch                      Unified diff vs sandbox/003/blueprint.py (empty for iteration 0).
├── stdout.log                      Sandbox subprocess stdout.
├── stderr.log                      Sandbox subprocess stderr.
├── traceback.txt                   Distilled traceback for next debugger turn (absent on success).
├── resource.json                   {cpu_s, peak_memory_mb, wall_clock_s, disk_mb, max_open_files}.
├── adapter_outputs/                Files the adapter wrote during execution (sandbox-allowed root).
│   └── <seed>/                     One subdirectory per seed in ExperimentSpec.seed_set.
│       ├── run_artifacts.json      RunArtifacts (spec 006 §4) — canonical adapter output.
│       ├── observables.json        Pre-registered metric values for this seed.
│       └── diagnostics.json        Residuals + invariants + adapter-declared diagnostics.
└── status.json                     {sandbox_outcome, traceback_summary, local_gate_findings[]}
```

Promotion (§5.6) walks `adapter_outputs/<seed>/` subtrees and moves each file into `runs/<cycle-id>/artifacts/<hash>/` via a temp-dir + `os.replace` dance. The per-iteration code, diffs, prompts, response, and logs are preserved for forensics regardless of outcome — only `adapter_outputs/` subtrees are wiped on rollback.

The legacy per-simulator-id layout (`sandbox/<simulator_id>/<seed>/`) referenced in early drafts of spec 006 is deprecated. The simulator identity is implicit in `ExperimentSpec.simulator_id`; the cycle root carries one cycle's worth of experiment.

### 4.2 `runs/<cycle-id>/sandbox/MANIFEST.json`

Index for `python -m factory.genver inspect`. Updated atomically after each iteration boundary.

```json
{
  "cycle_id": "20260523-abc",
  "hypothesis_id": "HYP-…",
  "iterations": [
    {"index": 0, "status": "runtime_error",       "duration_s": 11.2,  "cost_usd": 0.04},
    {"index": 1, "status": "runtime_error",       "duration_s": 8.7,   "cost_usd": 0.03},
    {"index": 2, "status": "parse_failed",        "duration_s": 0.0,   "cost_usd": 0.01},
    {"index": 3, "status": "passed_local_gate",   "duration_s": 41.6,  "cost_usd": 0.05}
  ],
  "terminal_status": "promoted",
  "promoted_at": "2026-05-23T12:08:11Z"
}
```

### 4.3 Loop config (`config/genver.yaml`)

```yaml
max_iterations: 10
parse_retry_count: 1
sandbox_limits:
  cpu_seconds: 600
  memory_mb: 4096
  wall_clock_seconds: 1800
  disk_mb: 512
  max_open_files: 256
prompt:
  system_template_path: factory/genver/prompts/system.md
  debugger_template_path: factory/genver/prompts/debugger.md
  max_tokens_per_call: 8192
  per_call_timeout_s: 90
code_gen_model:
  # FIX_PLAN §25.5: agentic LLM default is google/gemini-3.5-flash via OpenRouter.
  model_id: google/gemini-3.5-flash
  vendor: google
local_gate:
  require_canonical_tensor: true
  forbid_nan_in_canonical: true
  forbid_inf_in_canonical: true
  require_adapter_success_flag: true
diff_tool: difflib                # 'difflib' (stdlib) or 'git' (subprocess `git diff --no-index`).
```

All thresholds are configuration, never code (per `ARCHITECTURE.md` §4.5).

### 4.4 ReAct `tool_call` envelope (parser contract)

The code-gen response must contain exactly one fenced block of the form:

````
```tool_call
{
  "tool_name": "write_solver_blueprint",
  "blueprint_source": "<python source>",
  "blueprint_metadata": { "<adapter-declared keys>": ... }
}
```
````

Parser rules (`factory/genver/parser.py`):
1. Locate the first ```` ```tool_call ```` fenced block. If none, parse fails.
2. JSON-decode the body. If invalid JSON, parse fails.
3. Validate `tool_name == "write_solver_blueprint"`. If not, parse fails.
4. Validate `blueprint_source` is a non-empty string and parses as Python 3.10+ via `ast.parse`. If not, parse fails.
5. Validate `blueprint_metadata` keys match the schema declared by the spec-006 adapter for this experiment. If not, parse fails.
6. Return a `ToolCall` instance.

On parse failure, the loop performs one auto-reformat retry: the model is re-prompted with the previous response and a short reformatting hint. If the retry also fails to parse, the iteration is marked `parse_failed` and counted against the iteration budget; the next iteration proceeds normally with a debugger turn fed the parse error.

## 5. Algorithms / Logic

### 5.1 Top-level loop

```
GenVerLoop.run(hypothesis, experiment):
    assert state_machine has already done EvidenceLedger G0 dedup lookup
    prepare run_dir/sandbox/
    iterations = []
    previous_blueprint = None

    for i in range(max_iterations):
        # Live budget read — never touch the frozen Budget artifact for state.
        remaining = tracker.remaining(hypothesis_id)
        if remaining.hypothesis.dollars <= 0:
            terminal = "intractable_dollar_cap"; break
        # Also enforce the iteration tier via the tracker.
        # (The tracker raises BudgetExhausted(surface="iterations") if exceeded; the
        # state machine maps that to terminal_status="intractable_iteration_cap".)

        iter_dir = run_dir/sandbox/f"{i:03d}"
        mkdir iter_dir
        # adapter_outputs/<seed>/ subdirectories are created by the adapter during run.

        # 5.2 — build prompt
        prompt = build_prompt(hypothesis, experiment, previous_iterations=iterations)
        write iter_dir/prompt.md

        # 5.3 — code-gen turn (pre-check before LLM call)
        if tracker.would_exceed(hypothesis_id, additional_cost_usd=estimated_call_cost).dollars:
            terminal = "intractable_dollar_cap"; break

        response = code_gen.generate(prompt, max_tokens=cfg.max_tokens_per_call,
                                     timeout_s=cfg.per_call_timeout_s)
        write iter_dir/response.txt
        tracker.record(
            hypothesis_id=hypothesis_id,
            module="genver",
            cost_usd=response.cost_usd,
            tokens=response.tokens_in + response.tokens_out,
            wall_clock_seconds=response.wall_clock_seconds,
            description=f"code_gen iteration {i}",
        )
        tracker.record_iteration(hypothesis_id=hypothesis_id, module="genver")

        tool_call = parse_tool_call(response.raw_text)
        if tool_call is None:
            # one auto-reformat retry inside the same iteration
            tool_call = retry_parse(response.raw_text)
        if tool_call is None:
            record IterationRecord(sandbox_outcome="parse_failed", traceback_summary=...)
            continue

        write iter_dir/tool_call.json
        write iter_dir/blueprint.py := tool_call.blueprint_source

        # 5.4 — diff
        if previous_blueprint is not None:
            write iter_dir/diff.patch := unified_diff(previous_blueprint, blueprint)
        else:
            write iter_dir/diff.patch := ""    # iteration 0 has no predecessor

        # 5.5 — sandbox execution; allowed_write_root is the iteration's adapter_outputs/
        sandbox_result = run_sandbox(
            iter_dir, adapter, sandbox_limits,
            allowed_write_root=iter_dir/"adapter_outputs",
            seeds=experiment.seed_set,
        )

        if sandbox_result.outcome == "resource_exceeded":
            record IterationRecord(...resource_exceeded...)
            if 3rd consecutive resource_exceeded: raise AdapterFailureUnrecoverable
            continue
        if sandbox_result.outcome == "runtime_error":
            record IterationRecord(...with distilled traceback...)
            continue

        # 5.6 — local gate (runs against every seed bucket)
        gate_outcome = local_gate(iter_dir/"adapter_outputs", experiment.adapter_schema, experiment.seed_set)
        if not gate_outcome.passed:
            record IterationRecord(...local_gate_failed...)
            continue

        # 5.7 — atomic promote (walks each seed bucket; collects all RunArtifacts files)
        promoted_hashes = promote_atomic(iter_dir/"adapter_outputs",
                                         run_dir/"artifacts")
        record IterationRecord(...passed_local_gate...)
        update sandbox/MANIFEST.json terminal_status="promoted"
        previous_blueprint = blueprint

        # 5.7.1 — emit StrategyCycleEvidence (spec 002, FIX_PLAN §26.4) for the archive.
        # Always emitted at iteration end (success or failure); when parent_strategy_sha
        # is None, the archive ignores the event. When non-None, the archive calls
        # StrategyArchive.attribute_surprise(parent_strategy_sha, evidence) and
        # StrategyArchive.attribute_reward(parent_strategy_sha, evidence).
        evidence = StrategyCycleEvidence(
            strategy_sha=parent_strategy_sha,        # may be None in Phase A
            cycle_id=cycle_id,
            best_objective=local_gate.best_objective_seen,
            best_feasibility_distance=local_gate.best_feasibility_distance,
            feasible_count=local_gate.feasible_seed_count,
            constraint_overshoots=local_gate.constraint_overshoots,
        )
        emit_strategy_cycle_evidence(evidence)

        return GenVerResult(terminal_status="promoted",
                             promoted_artifact_hashes=promoted_hashes, ...)

        previous_blueprint = blueprint        # if loop continues (resource/local-gate failure)
        # 5.7.2 — emit StrategyCycleEvidence on every non-promoted iteration as well
        # (FIX_PLAN §26.4). The archive needs negative evidence (failed iterations,
        # local-gate-failed runs, resource-exceeded) to attribute reward correctly.
        emit_strategy_cycle_evidence(StrategyCycleEvidence(
            strategy_sha=parent_strategy_sha,
            cycle_id=cycle_id,
            best_objective=None,
            best_feasibility_distance=None,
            feasible_count=0,
            constraint_overshoots={},
        ))

    # Loop exited without promotion. No retries beyond the cap.
    terminal = terminal or "intractable_iteration_cap"
    wipe_staging(run_dir/sandbox/)            # NOTE §5.8: this wipes adapter_outputs/ across all
                                              # iterations but PRESERVES sandbox/<i>/ subtrees for
                                              # forensics. See §5.8 for the precise contract.
    return GenVerResult(terminal_status=terminal, promoted_artifact_hashes=[], ...)
```

### 5.2 Prompt construction

The prompt has three layered components:

1. **System prompt** (`prompts/system.md`) — declares the abstract solver interface from spec 006 (function signatures, declared adapter schema, output filename contract under `adapter_outputs/<seed>/`), the ReAct envelope grammar, and the prohibition on importing outside the whitelist defined in `factory/genver/sandbox_imports.yaml`.
2. **Task description** — serialized `HypothesisSpec.if_then`, `measurable_metric`, and the relevant `ExperimentSpec` configuration. Does NOT include `kill_criteria` or `pre_registered_metric` — those are downstream-only.
3. **Iteration history** — for iterations > 0, the previous `n` iterations' (a) parsed `blueprint_metadata`, (b) diff against the one before it, (c) traceback summary or local-gate findings. The history is bounded by token budget (oldest iterations are summarized once we exceed half the prompt budget).

The debugger turn is not a separate model call — it is the *same* code-gen call on the next iteration, with the failure narrative present in the iteration history. Modeling the debugger as a distinct turn was considered and rejected: it doubles the per-iteration cost without changing the agent's failure-correction behavior, and it complicates budget accounting.

### 5.3 Code-gen dispatch

`CodeGenClient.generate(...)` is a single-shot call. The client invokes the **shared OpenRouter client** (FIX_PLAN §25.2) with `model="google/gemini-3.5-flash"` — the same OpenAI-compatible REST client used by the council (spec 001), with `Council`-specific concerns stripped: no persona, no stage, no anonymization. There is no Gemini-direct SDK in this code path; `from google import genai` is forbidden. Cost is computed from the OpenRouter response's `usage` block (`prompt_tokens`, `completion_tokens`) using the `google/gemini-3.5-flash` row of `config/pricing/openrouter.yaml`, reported back via `CodeGenResponse.cost_usd`, and immediately recorded on the live budget through `BudgetTracker.record(hypothesis_id=..., module="genver", cost_usd=..., tokens=..., wall_clock_seconds=..., description=...)`. The frozen `Budget` artifact is never written to and never read for live state — it carries the cap envelope and is referenced for audit only.

Timeout (`per_call_timeout_s`) is enforced by the client; on timeout the iteration is marked `runtime_error` with traceback `"code-gen timeout after N s"`. Timeout cost is accounted at the partial-token rate OpenRouter returns; if OpenRouter returns no `usage` block, `BudgetTokenUsageMissing` is raised per spec 013 — the iteration is parked, never silently charged $0.

### 5.4 Sandbox

The sandbox is **subprocess-level**, not Docker. Rationale: millisecond startup, no container build cost per iteration, full reuse of the host-installed simulator binaries (which are themselves inside a container — see spec 004 — but the *call* into the simulator is from our process). Docker is for the simulator catalog entry (spec 004), not the per-iteration code wrapper.

Subprocess construction (`factory/genver/sandbox.py`):
1. Spawn `python -m factory.genver.sandbox_runner --blueprint <iter_dir>/blueprint.py --adapter <adapter_module> --output-root <iter_dir>/adapter_outputs --seeds <seed_set> --metadata <iter_dir>/tool_call.json` as a child process.
2. Set `cwd` to `iter_dir` so the blueprint cannot reach into the cycle-root by mistake.
3. Apply resource limits (POSIX `setrlimit`):
   - `RLIMIT_CPU` → `cpu_seconds`. Exceeding it sends SIGXCPU to the child; the child terminates and the wrapper records `SandboxResourceExceeded(kind=cpu)`.
   - `RLIMIT_AS` (virtual memory) → `memory_mb << 20`. **Semantics:** `RLIMIT_AS` causes subsequent memory allocations to fail with `MemoryError`. POSIX rlimits do not kill the process; the wrapper inspects Python's exit code and the captured `MemoryError` to surface `SandboxResourceExceeded(kind=memory)`.
   - `RLIMIT_FSIZE` → `disk_mb << 20`. Per-file write-size cap; exceeding raises `OSError(EFBIG)` in the child, surfaced as `SandboxResourceExceeded(kind=disk)`.
   - `RLIMIT_NOFILE` → `max_open_files`. Exceeding raises `OSError(EMFILE)`, surfaced as `SandboxResourceExceeded(kind=file_descriptor)`.
4. Apply wall-clock limit via parent-side timer using `subprocess.Popen(...).wait(timeout=wall_clock_seconds)`. On timeout, SIGTERM then SIGKILL after 5 s; surface as `SandboxResourceExceeded(kind=wall_clock)`.
5. Restrict filesystem writes to `iter_dir/adapter_outputs/<seed>/` via the sandbox runner's pre-execution shim, which monkey-patches `builtins.open`, `os.open`, and `pathlib.Path.open` to refuse any write path that does not resolve under the allowed root. (This is defense-in-depth on top of the `cwd` discipline; sophisticated attacks can bypass it but the threat model is "LLM code-gen makes a mistake," not "adversarial code-gen with intent.")
6. Restrict imports to a whitelist (`config/sandbox_imports.yaml`): standard library subset, `numpy`, `scipy`, `jax`, simulator-binding modules declared by the spec-006 adapter, and the adapter's own module. `import` of anything outside the whitelist raises `ImportError("sandbox: import 'X' not in whitelist")` from the runner's `sys.meta_path` finder.

Resource accounting:
- Peak memory: read from `/proc/<pid>/status` (Linux) or `resource.getrusage` (POSIX fallback) after the child exits. Combined with the captured `MemoryError` (if any) to classify `kind=memory`.
- Disk usage: `du -s --bytes <iter_dir>` after exit; if it exceeded `disk_mb`, classify as `SandboxResourceExceeded(kind=disk)`.
- File descriptors: if the subprocess died with `OSError(EMFILE)`, classify as `SandboxResourceExceeded(kind=file_descriptor)`.
- The numeric values are written to `iter_dir/resource.json` regardless of outcome.

### 5.5 Local gate

After the sandbox subprocess exits cleanly (return code 0), the loop runs a mechanical local gate against the contents of `iter_dir/adapter_outputs/<seed>/` for **each seed in `ExperimentSpec.seed_set`**:

1. **Required canonical tensor.** `iter_dir/adapter_outputs/<seed>/canonical.npz` must exist for every seed (the adapter's declared canonical output filename — actual name comes from the adapter, `canonical.npz` is a placeholder). Missing → fail.
2. **No NaN, no Inf.** Load the canonical tensor for each seed. If any element is `nan` or `inf`, fail.
3. **Adapter success flag.** Each seed bucket's `run_artifacts.json` carries a `success: true/false, reason: "..."` field per the spec 006 contract. The loop requires `success == true` for every seed.
4. **Schema match.** The keys present in each seed's outputs match the `blueprint_metadata` the code-gen declared. Missing keys or extra keys both fail.

The local gate is **not** scientific validation. It catches: code that "ran" but produced no output, code that produced output full of NaNs, code that produced output the adapter itself rejected, code that proposed an output schema and then wrote a different schema. Numerical correctness, invariants, and convergence are entirely downstream (spec 009).

If the local gate fails on any seed, the iteration is recorded as `local_gate_failed` and the loop continues. Subsequent iterations see the local-gate finding in their prompt history so the code-gen can correct.

### 5.6 Atomic promotion

```
promote_atomic(staging_outputs: Path, artifact_root: Path) -> list[ArtifactHash]:
    # staging_outputs = run_dir/sandbox/<iteration:03d>/adapter_outputs/
    # artifact_root   = run_dir/artifacts/
    promoted = []
    # 1. Walk every seed bucket; compute hashes per file.
    for seed_dir in staging_outputs.iterdir():
        for file in walk(seed_dir):
            h = sha256(file.read_bytes()).hexdigest()
            promoted.append((file, h))

    # 2. Stage into a per-promotion temp dir under the artifact root.
    tmp = mkdtemp(dir=artifact_root, prefix="promote-")
    for file, h in promoted:
        target = tmp / f"{h}.{file.suffix}"
        shutil.copy2(file, target)

    # 3. Atomic move via os.replace per file (POSIX rename(2) is atomic on same filesystem).
    final_paths = []
    for tmp_file in tmp.iterdir():
        final = artifact_root / tmp_file.name
        if final.exists():
            # Identical content already promoted by an earlier cycle — verify hash and skip.
            assert sha256(final.read_bytes()).hexdigest() == tmp_file.stem.split(".")[0]
            tmp_file.unlink()
        else:
            os.replace(tmp_file, final)
            final_paths.append(final)

    # 4. Cleanup tmp dir. If non-empty (race), raise StagingPromoteRaced.
    if any(tmp.iterdir()):
        raise StagingPromoteRaced(f"tmp dir {tmp} non-empty after promote")
    tmp.rmdir()

    return [ArtifactHash(p.stem.split(".")[0]) for p in final_paths]
```

Atomicity is at the **per-file** level (POSIX `rename` is atomic within a filesystem). The whole-promote level is "all-or-nothing on the happy path"; the rollback story is "if any single step raises, the loop wipes the per-promotion tmp dir and reports failure." Because the staging files remain in `iter_dir/adapter_outputs/<seed>/`, Phase A treats any promote failure as terminal `intractable_adapter_failure` rather than retrying. Retries beyond the 10-iteration cap are out of scope — a relitigation requires a fresh cycle gated by `EvidenceLedger.relitigate_if`.

### 5.7 Diff-based iteration tracking

Each iteration writes `diff.patch` against the previous iteration's blueprint. The diff is:
- Generated via `difflib.unified_diff` (stdlib) by default, or by `git diff --no-index <prev> <curr>` if `diff_tool == "git"` in config.
- Empty (zero-byte file) for iteration 0.
- Used by `python -m factory.genver diff-iterations <cycle-id> --from 002 --to 007` to inspect the agent's correction trajectory after a failed cycle.

The diff is logged but NOT fed back into the prompt directly (the next iteration's blueprint replaces the previous in the prompt history). The diff is for postmortem.

### 5.8 Rollback contract

"Rollback" in this loop has a specific definition:

- **No artifacts are promoted** when `terminal_status != "promoted"`. The `runs/<cycle-id>/artifacts/` directory is touched only by the atomic-promote path (§5.6), so a budget-exhausted cycle never leaves stale files in `artifacts/`.
- **Staging is preserved for forensics.** The `sandbox/<iteration:03d>/` subtrees are *not* wiped on budget exhaustion. They contain code, prompts, responses, tracebacks, resource ledgers, and diffs — exactly the data a postmortem needs. The `wipe_staging(...)` call at the end of `run` deletes only the per-iteration `adapter_outputs/` subtrees (because those are large and were never promoted), not the rest.
- **A failed atomic promote** (`StagingPromoteRaced` or filesystem error) raises immediately. The state machine catches and routes to `terminate_intractable` with a forensic note; this is treated as infrastructure failure, not a normal loop outcome.

The state machine then writes the `EvidenceLedgerEntry` whose `result` is `intractable` for budget-exhaustion outcomes, with `relitigate_if` triggers populated from the failure mode (e.g., `intractable_iteration_cap` → trigger "iteration_cap raised in budget config"; `intractable_adapter_failure` → trigger "adapter version bumped in catalog"). The granular `terminal_status` carried on `GenVerResult` (not just the `GateOutcome.INTRACTABLE` summary) is what drives these triggers.

### 5.9 EvidenceLedger lookup at G0 (interaction contract)

The G0 dedup lookup is the state machine's responsibility, not this loop's. Per FIX_PLAN §2 and §3, the state machine handles dedup with a `GateOutcome.PASS` carrying `dedup_skip: True` metadata; that PASS is then routed to `terminate_dedup_skip` per spec 003's routing table. The legacy `pass_dedup_skip` outcome enum value is gone — there is only the canonical `PASS` plus the metadata flag.

```
state_machine.run_gate(G0, inputs):
    ledger_hit = ledger.query_by_hypothesis_id(hypothesis.hypothesis_id)
    if ledger_hit is not None:
        if not any(t.currently_satisfied for t in ledger_hit.relitigate_if):
            return GateResult(
                outcome=GateOutcome.PASS,
                metadata={"dedup_skip": True},
                # spec 003 gate_routes.yaml routes PASS+dedup_skip -> terminate_dedup_skip
            )
        # else fall through; relitigation is permitted because at least one trigger fires
    # ...
```

This loop is invoked only after that check has cleared. The loop never queries the ledger; the loop also never *writes* the ledger. The loop returns a `GenVerResult`; the state machine packages that into the appropriate `EvidenceLedgerEntry` (or forwards to G3 / G4 if promoted).

### 5.10 Numerical gullibility and invariant hacking — explicit non-defense

Per `SPEC.md` §10.2–10.3, this loop is **not the front line** against:

- **Numerical gullibility** (the code-gen LLM produces formulas it cannot actually simulate; the loop runs them happily as long as they don't NaN).
- **Invariant hacking** (the code satisfies named invariants — energy conservation, $\nabla\cdot\mathbf{B}=0$ — without solving the actual problem, often by hard-coding the invariant residual to zero in the output).

The loop's local gate (§5.5) is strictly mechanical; it checks the output *exists, has no NaNs, and matches the declared schema*. The local gate cannot tell whether `canonical.npz` reflects a valid solution or a hand-rolled lie. The layered defenses are:

1. **G2.5 dry-run** — the state machine runs this loop on a toy problem before committing real budget. If the toy fails, the hypothesis is `intractable` before money is spent.
2. **G3 surrogate** (spec 010) — a learned surrogate scores the proposed solver's output against the relevant observable distribution. OOD detection forces direct oracle escalation; the surrogate cannot give a clean pass to obviously-distorted candidates.
3. **G4 validation portfolio** (spec 009) — the actual scientific defense. Refinement convergence catches "satisfies invariant but wrong answer at any resolution." Held-out symmetry tests catch invariant hacking. Cross-simulator checks catch simulator-specific over-fitting.

A reviewer who reads this spec and assumes the loop has solved either failure mode has misread the spec. This section exists so that mistake never gets made.

## 6. Failure Modes

| Error class | When it fires | Recovery action |
| :--- | :--- | :--- |
| `IterationBudgetExhausted` | Loop reached `max_iterations` without `passed_local_gate`, OR `BudgetTracker.record_iteration` raised `BudgetExhausted(surface="iterations")` | Encoded as `terminal_status="intractable_iteration_cap"`; loop returns normally; `to_gate_outcome()` returns `GateOutcome.INTRACTABLE`; state machine routes to `terminate_intractable`; ledger entry's `relitigate_if` includes "iteration_cap raised" |
| `DollarBudgetExhausted` | `tracker.remaining(hypothesis_id).dollars <= 0` or `tracker.would_exceed(hypothesis_id, additional_cost_usd).dollars` true before next iteration starts | Encoded as `terminal_status="intractable_dollar_cap"`; `to_gate_outcome()` returns `GateOutcome.INTRACTABLE`; same routing as above with a different relitigation trigger |
| `SandboxResourceExceeded(kind=cpu)` | `RLIMIT_CPU` hit; child terminated by SIGXCPU | Iteration recorded as `resource_exceeded`; loop continues; if 3 consecutive resource-exceeded events fire, escalate to `AdapterFailureUnrecoverable` |
| `SandboxResourceExceeded(kind=memory)` | `RLIMIT_AS` caused subsequent allocations to fail with `MemoryError`; the wrapper inspects exit code + captured `MemoryError` to classify | Same as above. POSIX rlimits do not kill the process — classification comes from the wrapper, not the OS. |
| `SandboxResourceExceeded(kind=wall_clock)` | Parent-side wall-clock timer fired before child exit | Same as above; child SIGTERM then SIGKILL |
| `SandboxResourceExceeded(kind=disk)` | `du` over `adapter_outputs/` exceeded `disk_mb` OR child raised `OSError(EFBIG)` from `RLIMIT_FSIZE` | Same as above; staging dir's `adapter_outputs/` partially wiped to free space |
| `SandboxResourceExceeded(kind=file_descriptor)` | Child died with `OSError(EMFILE)` from `RLIMIT_NOFILE` | Same as above |
| `AdapterFailureUnrecoverable` | Spec-006 adapter raised before code-gen output was even attempted (e.g., simulator binary missing), OR 3 consecutive resource-exceeded events | Encoded as `terminal_status="intractable_adapter_failure"`; `to_gate_outcome()` returns `GateOutcome.INTRACTABLE`; state machine routes to `terminate_intractable`; relitigation trigger = "simulator version updated in catalog" |
| `CodeGenParseFailed` | After reformat retry, response still doesn't parse to a valid `ToolCall` | Iteration recorded as `parse_failed`; loop continues with next iteration; no error raised |
| `StagingPromoteRaced` | Atomic-promote temp dir non-empty after the per-file move loop | Raised immediately to the state machine; treated as infrastructure failure; staging preserved; halt cycle with operator alert |
| `RollbackFailed` | `wipe_staging` raised a filesystem error during cleanup on terminal | Raised immediately; staging left on disk for forensics; cycle halted; operator alert |

The first ten rows are *normal* loop outcomes — encoded in `GenVerResult.terminal_status` or `IterationRecord.sandbox_outcome`, returned without raising. Only `AdapterFailureUnrecoverable`, `StagingPromoteRaced`, and `RollbackFailed` propagate as exceptions; those are infrastructure failures, not scientific failures, and the state machine handles them differently from a normal `intractable`. Failures propagate to the state machine without defensive interception inside the loop.

## 7. Testing

**Mock-mode** (in CI, no external services):
- `test_genver_typical_usage.py` — REQUIRED. Run a 3-iteration trace (runtime_error → runtime_error → passed_local_gate). Verify: `terminal_status == "promoted"`, `to_gate_outcome() == GateOutcome.PASS`, `len(iterations) == 3`, `len(promoted_artifact_hashes) >= 1`, manifest written, per-iteration directories present, per-seed buckets under `adapter_outputs/<seed>/` present.
- `test_parse_retry.py` — code-gen returns malformed envelope; verify exactly one reformat retry happens, then iteration is marked `parse_failed` if the retry also fails.
- `test_iteration_budget.py` — force 10 consecutive runtime errors; verify `terminal_status == "intractable_iteration_cap"`, `to_gate_outcome() == GateOutcome.INTRACTABLE`, no artifacts promoted, `adapter_outputs/` wiped while `sandbox/<i>/` subtrees survive.
- `test_dollar_budget.py` — open hypothesis with `HypothesisCaps(dollars=0.10, ...)`, fixture code-gen reports cost $0.05/call; verify loop terminates after ≤2 iterations with `intractable_dollar_cap` and `tracker.remaining(...).hypothesis.dollars` decremented accordingly.
- `test_budget_tracker_record_args.py` — assert that every iteration calls `tracker.record(hypothesis_id=..., module="genver", cost_usd=..., tokens=..., wall_clock_seconds=..., description=...)` with the canonical keyword set; explicitly assert no calls to a hypothetical `budget.record_entry(...)` happen.
- `test_gate_outcome_mapping.py` — for each value of `terminal_status`, assert `GenVerResult(...).to_gate_outcome()` returns the documented mapping (promoted → PASS, intractable_* → INTRACTABLE).
- `test_sandbox_resource_limits.py` — fixture blueprint allocates 8 GB in a `memory_mb=1024` sandbox; verify `MemoryError` is captured by the wrapper and surfaced as `resource_exceeded(kind=memory)` (the process is NOT killed by the OS — the rlimit causes allocation failure).
- `test_sandbox_wall_clock.py` — fixture blueprint runs `time.sleep(120)` in `wall_clock_seconds=10` sandbox; verify `resource_exceeded(kind=wall_clock)`.
- `test_sandbox_import_whitelist.py` — fixture blueprint imports `requests`; verify import refused inside sandbox.
- `test_sandbox_write_outside_root.py` — fixture blueprint tries `open("/tmp/x", "w")`; verify refused.
- `test_sandbox_limits_required.py` — instantiating `SandboxLimits(...)` without `allowed_write_root` raises `TypeError`; instantiating it with a path that does not resolve under `runs/<cycle-id>/sandbox/<iteration:03d>/` is rejected by `GenVerLoop.__init__`.
- `test_consecutive_resource_exceeded_escalation.py` — three resource-exceeded events in a row escalate to `AdapterFailureUnrecoverable`.
- `test_local_gate_no_nan.py` — fixture blueprint produces output with one `nan` in one seed bucket; verify `local_gate_failed`.
- `test_local_gate_schema_mismatch.py` — blueprint declares one schema, writes another; verify `local_gate_failed`.
- `test_local_gate_per_seed.py` — `ExperimentSpec.seed_set = [0, 1, 2]`; fixture writes valid output for seeds 0 and 1 but omits seed 2's bucket; verify `local_gate_failed` with the missing-seed finding.
- `test_atomic_promote_idempotent.py` — same hash already in `artifacts/` from a prior cycle; verify the existing file is preserved (hash-verified) and no error.
- `test_atomic_promote_race.py` — manually populate the temp dir after the move loop; verify `StagingPromoteRaced`.
- `test_diff_patch_generated.py` — iteration 1's `diff.patch` is a non-empty unified diff against iteration 0's `blueprint.py`.
- `test_replay.py` — run loop end-to-end, then call `replay()`; verify the reconstructed `IterationRecord`s match.
- `test_g0_dedup_is_state_machine_not_loop.py` — loop runs even when an `EvidenceLedgerEntry` for the same `hypothesis_id` exists; the loop does not query the ledger; the dedup check is the state machine's responsibility (the state machine emits `GateOutcome.PASS` with metadata `dedup_skip: True`, routed to `terminate_dedup_skip` — the loop sees no dedup logic).

**Live-mode** (`@pytest.mark.live`, gated):
- `test_live_one_iteration.py` — single iteration against the real code-gen client and a real spec-006 adapter (simplest adapter only). Asserts total cost < $0.50 via `tracker.remaining(...)`.
- `test_live_toy_problem_dry_run.py` — full loop against the toy problem used by G2.5; asserts terminal `promoted` within 3 iterations.

**Acceptance test** (PRD-001 §90-day milestone): the loop completes the G2.5 dry-run for the canonical Phase A hypothesis within 3 iterations and ≤$0.50, with all per-iteration artifacts present, per-seed adapter outputs bucketed under `adapter_outputs/<seed>/`, and atomic-promote verified.

**Manual verification step** (one-time, runbook): inspect at least one live trace by hand to confirm the debugger turn's prompt history actually contains useful traceback context (not just a generic "previous iteration failed").

## 8. Performance & Budget

- Per-iteration overhead (orchestrator only, excluding LLM call and sandbox): < 200 ms.
- Sandbox startup (subprocess fork + setrlimit + import whitelist init): < 50 ms typical; depends on the adapter's import surface.
- Sandbox teardown (resource accounting + manifest update): < 100 ms.
- Per-iteration LLM cost target: ≤ $0.005 (FIX_PLAN §25.8) — 8 k input + 4 k output at `google/gemini-3.5-flash` pricing via OpenRouter.
- Per-loop cap envelope: 10 iterations × $0.005 ≈ $0.05 typical LLM spend; the hypothesis cap in `HypothesisCaps` is the canonical authority and is enforced by the tracker, not by this loop's local math. Sandbox compute is bounded by `cpu_seconds × max_iterations`.
- Wall-clock per loop: with `wall_clock_seconds=1800` and `max_iterations=10`, worst case 5 hours; typical (3 iterations to promotion) ~10 minutes.
- The state machine's per-cycle wall-clock target (spec 003) is 72 hours; this loop's contribution is bounded above by ~5 hours.

## 9. Open Questions

- **Debugger as a distinct turn.** Phase A folds the debugger into the next iteration's code-gen turn via prompt history. Phase B may revisit this if empirical data shows the agent fails to use traceback context productively. Splitting the turn doubles cost — the decision must be data-driven.
- **Council-mediated code-gen selection.** Phase B may invoke `Council.deliberate(...)` at the start of an iteration to choose between K candidate code mutations rather than dispatching one model. The spec exposes the hook but does not exercise it; the empirical question is whether 4x cost buys enough variance reduction to be worth it.
- **Sandbox import whitelist scope.** The default whitelist allows `numpy`, `scipy`, `jax`, plus the adapter's declared imports. If a Phase B adapter needs e.g. `torch`, the whitelist must be extended in `config/sandbox_imports.yaml`. Whether to support per-adapter whitelists or keep a single global one is open.
- **Cross-iteration code reuse.** Right now each iteration's blueprint is independent — the agent may rewrite a working component for no reason. A "stage previous successful component, only mutate one piece" workflow could reduce iterations-to-promotion but adds significant scoping complexity. Deferred.
- **Differential cost of a parse retry.** The parse retry is charged the same as a normal iteration. If the model's tokenizer treats the retry prompt as much cheaper, we may want to under-charge it; if much more expensive, over-charge. Currently flat.
- **Promotion of partial outputs.** If a multi-seed `adapter_outputs/` directory passes the local gate for some seeds but not all, do we promote the passing seeds or fail the whole iteration? Current rule: all-or-nothing across seeds. Phase B may relax this for large multi-stage outputs, but the bookkeeping is non-trivial.

## 10. TODO Checklist

- [ ] Scaffold `factory/genver/` from the canonical module template.
- [ ] Implement `GenVerLoop.__init__` with config loading (`config/genver.yaml`) and validation (max_iterations ≤ `HypothesisCaps.iterations`, `SandboxLimits.allowed_write_root` resolves under the cycle's sandbox dir).
- [ ] Implement `GenVerResult.to_gate_outcome()` per the mapping documented in §3 and verify with `test_gate_outcome_mapping.py`.
- [ ] Implement `CodeGenClient.generate(...)` against the shared OpenRouter client (FIX_PLAN §25.2) with `model="google/gemini-3.5-flash"`, persona/stage hooks disabled, and OpenRouter `usage`-block-driven cost reporting.
- [ ] Implement `parse_tool_call` strict parser + reformat-retry helper.
- [ ] Implement `factory/genver/sandbox.py` subprocess launcher with `setrlimit`, wall-clock timer, and SIGTERM/SIGKILL escalation, plus `MemoryError`-capture for `RLIMIT_AS` semantics.
- [ ] Implement `factory/genver/sandbox_runner.py` (child entry point) with import whitelist (`sys.meta_path` finder) and write-root restriction (monkey-patched `open` family).
- [ ] Author `config/sandbox_imports.yaml` with the default whitelist.
- [ ] Implement per-iteration staging directory layout (§4.1), including per-seed bucketing under `adapter_outputs/<seed>/`.
- [ ] Implement local gate (§5.5): canonical-tensor check, NaN/Inf scan, schema match, adapter success flag — all evaluated per seed.
- [ ] Implement `promote_atomic` walking per-seed buckets with per-file `os.replace` and `StagingPromoteRaced` detection.
- [ ] Implement `wipe_staging` (deletes `adapter_outputs/` per iteration, preserves the rest).
- [ ] Implement `unified_diff` writer (stdlib `difflib`) and optional `git diff --no-index` backend.
- [ ] Implement `sandbox/MANIFEST.json` writer with atomic write (`os.replace(..., MANIFEST.json)`).
- [ ] Implement prompt builders: system prompt template, task description renderer, iteration-history renderer with token-bounded summarization.
- [ ] Implement `GenVerLoop.run` top-level loop (§5.1) using `tracker.record(...)`, `tracker.record_iteration(...)`, `tracker.remaining(...)`, and `tracker.would_exceed(...)` — never `budget.record_entry(...)` or `budget.dollar_remaining`.
- [ ] Implement `GenVerLoop.replay` (§3 surface — walks persisted sandbox dirs, reconstructs IterationRecords).
- [ ] Implement `factory/genver/cli.py` with `run`, `replay`, `inspect`, `diff-iterations` subcommands.
- [ ] Implement mocks: `MockCodeGen` (replay-driven), `MockAdapter`, `MockSandbox` (in-process; unit tests only).
- [ ] Author the mock-mode tests listed in §7. All pass in CI.
- [ ] Author 2 live-mode tests (`@pytest.mark.live`); manual gate.
- [ ] Write `factory/genver/README.md` (≤ 1 page; mock-mode example).
- [ ] Write `docs/runbooks/genver-debugging.md` covering: how to inspect a failed iteration; how to interpret `diff.patch`; how to extend the import whitelist; how to debug a sandbox resource-exceeded; how to handle `StagingPromoteRaced`; how to read `tracker.remaining(...)` after a `intractable_dollar_cap` outcome.
- [ ] Verify `mypy --strict factory/genver/` passes.
- [ ] Verify `python -m factory.genver run --experiment-fixture sample --mock-mode` works on a fresh checkout.
- [ ] Wire `GenVerResult.to_gate_outcome()` into spec 003's gate routing: G2.5 outcomes (`PASS` → G3; `INTRACTABLE` → terminate_intractable); post-G4 re-invocation hooks.
- [ ] Wire `BudgetTracker.record(...)` for each code-gen call and `BudgetTracker.record_iteration(...)` for each iteration boundary (spec 013).
- [ ] Declare telemetry events in `factory/genver/events.py` under the `factory.genver.*` namespace (event names: `factory.genver.iteration_start`, `.iteration_end`, `.sandbox_open`, `.sandbox_exit`, `.promote_attempt`, `.promote_succeeded`, `.promote_failed`) so spec 014's aggregator picks them up at startup; emit when spec 014 is wired, no-op otherwise.
- [ ] PRD-001 acceptance: G2.5 dry-run for the canonical Phase A hypothesis completes in ≤3 iterations and ≤$0.50.
- [ ] Plumb `parent_strategy_sha: str | None = None` through `GenVerLoop.run(...)` per §3 and the FIX_PLAN §26.4 contract; thread it into the code-gen prompt only when non-None; default to `None` for Phase A backward compatibility (`parallel_lineages_k=1`, un-parented runs).
- [ ] Emit a `StrategyCycleEvidence` artifact (spec 002) at every iteration end (success and failure) per §5.7.1 / §5.7.2; when `parent_strategy_sha is None`, emission is still performed but the archive ignores the event. When non-None, the state machine forwards the evidence into `StrategyArchive.attribute_surprise(...)` and `attribute_reward(...)` from `specs/016-strategy-archive.md`.
