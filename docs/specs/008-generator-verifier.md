# Spec 008: Multi-Turn Agent Loop

> Status: ☐ not started · Owner: TBD · Last updated: 2026-05-23

## CONTEXT (60-second summary — read first)
- The **Multi-Turn Agent Loop** is the factory's code-execution substrate: a ReAct loop that drives `google/gemini-3.5-flash` (via the shared OpenRouter client, spec 018) through up to **25 turns** per cycle. Each turn = one LLM round-trip plus dispatch of any tool calls the response carried. The architectural unit is the **turn**, not the iteration — a turn may emit zero, one, or many tool calls in parallel. Module path stays `factory/genver/`.
- The 5 facts: (1) the loop only gets code to *execute and emit candidates* — it does NOT validate that the code solves the science problem (that is G3 surrogate + G4 portfolio, specs 010 and 009); (2) **8-tool ReAct surface** — `query_db`, `read_file`, `list_files`, `run_python`, `write_candidate`, `write_notes`, `done`, `stop_run` — exchanged as fenced-text envelopes (```` ```tool_call ```` and ```` ```tool_result[c-N-i] ````); (3) **token-driven compaction** at `AUTO_COMPACT_TOKEN_LIMIT = 200_000` — older turn-blocks are summarized by a same-model LLM call so cycles can run long without OOM; (4) **atomic all-or-none promotion** — every staged candidate is canonicalized + sanitized; promote all OR preserve staging on failure for forensics, tracking `skipped_duplicate_count` and `skipped_invalid_count` separately; (5) **cold-start pre-stage** + **STOP-file polling** + **`refresh_state` per turn** are the three integration hooks with the outer state machine (spec 003): seed cold-start fixtures on cycle 0, write `runs/<cycle-id>/STOP` from the `stop_run` tool, re-render the `## State` user-message every round-trip.
- Open first: `factory/genver/api.py` and `factory/genver/tests/test_genver_typical_usage.py`. The clearest single-page picture is the multi-turn transcript fixture at `factory/genver/fixtures/transcripts/sample_three_turns.jsonl`.

## ENTRY POINTS
- Main module: `factory/genver/api.py`
- Turn-loop driver: `factory/genver/turn_loop.py`
- Tool surface: `factory/genver/tools.py`
- Compaction: `factory/genver/compaction.py`
- Cold-start pre-stage: `factory/genver/cold_start.py`
- Atomic promotion: `factory/genver/promote.py`
- Typical-usage test: `factory/genver/tests/test_genver_typical_usage.py`
- CLI: `python -m factory.genver --help` (subcommands: `run`, `replay`, `inspect`, `show-turn`, `compact-preview`, `diff-turns`)
- Mock-mode example: `python -m factory.genver run --experiment-fixture sample --mock-mode`
- Runbook: `docs/runbooks/genver-debugging.md`

## LOCAL DEBUG
- Instantiate without OpenRouter access: `GenVerLoop(client=FileClient.from_fixture("sample_three_turns"), adapter=MockAdapter(), tracker=BudgetTracker.from_fixture("small")).run(spec)` returns a deterministic `GenVerResult` reconstructed from the fixture transcript. `FileClient` is supplied by spec 018.
- Live mode requires: (a) `OPENROUTER_API_KEY` (FIX_PLAN §25.6 — single env var for all LLM access; both the agent and the compaction summarizer go through `factory.llm_client.OpenRouterClient` at `model="google/gemini-3.5-flash"`; no temperature override per FIX_PLAN §27.2); (b) the domain adapter (spec 006) wired to a real simulator; (c) `factory.ledger` reachable so the G0 dedup lookup completes upstream; (d) a `BudgetTracker` instance (spec 013) opened against the hypothesis; (e) `runs/<cycle-id>/` writable.
- Common error signatures → recovery:
  - `MaxTurnsReached` → loop hit `MAX_TURNS = 25` without a terminal call; encoded as `terminal_status="intractable_max_turns"` and `error_type="max_turns_no_output"` when no candidates were emitted; routed by the state machine to `terminate_intractable`; staging preserved for forensics.
  - `CompactionFailed` → summarizer call returned unchanged or raised twice in a row above the token budget; encoded as `terminal_status="intractable_compaction_failed"` and `error_type="compaction_failed"`; staging preserved; a `runs/<cycle-id>/sessions/turn_<n>_partial.json` checkpoint is written so the postmortem can replay.
  - `OpenRouterAuthError` → auth rejected (401/403) on either the agent or the summarizer call; non-retryable; encoded as `terminal_status="intractable_openrouter_auth_failed"` and `error_type="openrouter_auth_failed"`; checkpoint written.
  - `TransientAPIError` (rate limit / 5xx / connection error from spec 018) → propagates out of the loop; the state machine decides whether to re-enter the cycle on backoff. The loop itself does not retry — backoff is the OpenRouter client's responsibility.
  - `CandidateValidationError` → at least one staged candidate fails canonicalization or sanitization; **atomic all-or-none** rule fires: nothing is promoted, staging is preserved, `error_type="candidate_validation_failed"` recorded; the failing-candidate name(s) are logged.
  - `LlmInvokeFailed` → an unclassified exception from `client.invoke(...)`; encoded as `error_type="llm_invoke_failed"`; checkpoint written; loop returns.
  - `EmptyOutputDone` → agent called `done` but `candidates_written == []` AND at least one non-terminal tool call earlier in the cycle returned `ok=False`; distinguished from a clean no-improvement cycle so post-run analysis can separate "agent gave up after bungling its writes" from "agent investigated and concluded no improvement available."
  - `StagingPromoteRaced` → another process touched the staging directory between final validation and atomic move; this is a bug, not a recoverable runtime; halt cycle, raise to state machine.
  - `RollbackFailed` → `wipe_staging` raised a filesystem error AFTER `conn.commit()` succeeded; the cycle is durably recorded but staging artifacts leak — operator alert, no automatic recovery.
- Logs to inspect:
  - `runs/<cycle-id>/staging/` — per-cycle staging dir containing `candidate_<n>.json`, optional `candidate_<n>.operator_family` sidecars, and (when promoted) `notes.md`. **Preserved** on validation failure for forensics; wiped only AFTER `conn.commit()` succeeds.
  - `runs/<cycle-id>/notes.md` — agent's own scratchpad markdown (≤ 64 KB) written directly by the `write_notes` tool. NOT subject to atomic-promote — survives every error path.
  - `runs/<cycle-id>/sessions/turn_<n>_partial.json` — checkpoint payload for `oauth_refresh_failed` / `openrouter_auth_failed` / `compaction_failed` / `llm_invoke_failed`. Carries the full message log up to the failing turn so the postmortem can replay.
  - `runs/<cycle-id>/cycle.jsonl` filtered by `module=genver` — one event per turn boundary (`factory.genver.turn_start`, `.turn_end`), per tool dispatch (`.tool_call_start`, `.tool_call_end`), per compaction (`.compaction_attempt`, `.compaction_succeeded`, `.compaction_failed`), per promotion (`.promote_attempt`, `.promote_succeeded`, `.promote_failed`).
  - `runs/<cycle-id>/STOP` — written by the `stop_run` tool; the outer state machine (spec 003) checks this between cycles and halts continuous operation when present.

## DEPENDENCIES
- **Hard:** Spec 002 (artifacts) — reads `HypothesisSpec`, `ExperimentSpec`, `Budget`; emits a `GenVerResult` typed result (NOT a top-level artifact — the state machine writes the downstream `EvidenceLedgerEntry`). Spec 006 (domain adapter) — every `run_python` invocation that exercises the simulator dispatches through the adapter so the loop is simulator-agnostic; per-seed outputs land under `adapter_outputs/<seed>/` per the spec 006 contract when the agent chooses to invoke the simulator. Spec 013 (budget tracker) — every LLM round-trip cost (agent + summarizer) is reported through `tracker.record(...)`; the tracker enforces per-hypothesis dollar, token, wall-clock, and turn caps. Spec 016 (strategy archive) — optional `parent_strategy_sha: str | None = None` parameter on `GenVerLoop.run(...)`; when non-None, the code-gen prompt carries the active strategy lineage and a `StrategyCycleEvidence` artifact (spec 002) is emitted at every turn-loop terminal (success and failure). Spec 018 (OpenRouter Client) — the shared LLM substrate; **every** LLM round-trip (agent invocation, compaction summarizer) goes through `from factory.llm_client import OpenRouterClient` at `model="google/gemini-3.5-flash"` per FIX_PLAN §25 and §27.2.
- **Soft:** Spec 001 (council) — Phase B may invoke `Council.deliberate(...)` at the start of a turn to pick between candidate code mutations; Phase A dispatches one model per turn with no council involvement. Spec 003 (state machine) — consumes `GenVerResult.terminal_status` (mapped to `GateOutcome` via `to_gate_outcome()` per §3) for gate routing; owns the cold-start pre-stage cycle decision and the inter-cycle STOP-file check. Spec 012 (ledger) — read for the G0 dedup lookup the state machine performs BEFORE invoking this loop; the loop never queries the ledger directly. Spec 014 (telemetry) — emits per-turn events when wired; event names declared in `factory/genver/events.py` under the `factory.genver.*` namespace.
- **Mocks available:**
  - `FileClient` (from spec 018) — replays a recorded transcript from `factory/genver/fixtures/transcripts/`; supports forced compaction, forced auth failure, and "stop on turn N" patterns. Implements the `DecisionClient` Protocol.
  - `MockAdapter` — implements the spec-006 abstract solver interface with deterministic fixture outputs; supports forced resource-exceeded.
  - `MockSandbox` — runs `run_python` payloads under restricted globals (for unit testing only — never used in live mode).
  - `BudgetTracker.from_fixture("small")` — 25-turn / $0.50 cap envelope for tests.

---

## 1. Summary

The Multi-Turn Agent Loop is the factory's **code-execution substrate**. The state machine (spec 003) invokes the loop at G2.5 (tractability dry-run) and again post-G4 when the validation portfolio needs a specific solver instantiation. The loop owns nothing scientific — it owns *driving the agent through up to 25 ReAct turns and atomically promoting whatever staged candidates it emits*. Whether the code that ran *also solves the problem* is decided downstream by the surrogate (spec 010), the validation portfolio (spec 009), and ultimately the interpretation/peer-review councils at G5.

Per FIX_PLAN §27 the loop is rewritten to adopt the proxima harness's ReAct architecture:

1. A **system prompt** (`prompts/system.md`) declares the 8-tool surface, the ReAct text-fence grammar, the abstract solver interface contract (spec 006), and the cold-start seed pointer (when present).
2. A **per-turn `## State` user message** is re-rendered from the current sandbox state on every round-trip via the `refresh_state` callback — best-feasibility-so-far, candidates-promoted-this-cycle, budget remaining, archive context (when spec 016 enabled).
3. The agent emits **zero or more parallel tool calls** as fenced ```` ```tool_call ```` blocks. The loop parses each, dispatches in order, and appends `tool_result[c-N-i]` blocks to the message history.
4. The loop runs up to **`MAX_TURNS = 25`** rounds. It exits when (a) the agent calls `done` or `stop_run`, (b) the agent replies with no tool calls (treated as natural end-of-turn), or (c) `MAX_TURNS` is reached without a terminal call.
5. When estimated tokens cross **`AUTO_COMPACT_TOKEN_LIMIT = 200_000`**, the loop calls the same OpenRouter client at the same model to summarize older turn-blocks into one synthetic `system` message; the most recent five turn-blocks are preserved intact.
6. On terminal, the loop runs **atomic all-or-none promotion**: every `candidate_<n>.json` in staging is canonicalized + sanitized; if any fails, **nothing is promoted** and staging is preserved with `error_type="candidate_validation_failed"`. If all pass, candidates are enqueued inside the caller's DB transaction and staging is wiped **after** `conn.commit()` succeeds.

The architectural unit is **the turn**, not the iteration. A cycle is up to 25 turns. The agent may emit multiple `write_candidate` (or `run_python` with bulk-write) calls in a single turn (parallel candidate proposals). The loop terminates on: agent calls `done`, agent calls `stop_run`, agent replies with no tool calls, `MAX_TURNS` reached, or one of the propagating infrastructure errors fires.

Numerical gullibility and invariant hacking — the dominant failure modes from `SPEC.md` §10.2–10.3 — are NOT defended by this loop alone. The loop will happily promote candidates whose blueprints produce plausible-looking numerics that are physically wrong, or whose blueprints satisfy named invariants by construction. The defenses live downstream:

- **G2.5 tractability dry-run** uses *this* loop on a toy problem so we observe non-trivial output before committing real budget.
- **G3 surrogate** (spec 010) catches obviously-implausible candidates before oracle execution.
- **G4 validation portfolio** (spec 009) is the actual scientific defense — held-out symmetry tests, refinement convergence, cross-simulator checks.

Specs that confuse "the loop ran" with "the science is right" will be rejected at review.

## 2. Scope

**In scope:**
- Multi-turn ReAct loop with **`MAX_TURNS = 25`** per cycle and **`AUTO_COMPACT_TOKEN_LIMIT = 200_000`** token budget for compaction triggering.
- **8-tool ReAct surface** — `query_db`, `read_file`, `list_files`, `run_python`, `write_candidate`, `write_notes`, `done`, `stop_run` — each with a fully specified `args` schema, safety invariants, and structured `ToolResult` payload.
- **ReAct text-fence protocol** — assistant emits ```` ```tool_call ```` JSON-bodied blocks; the loop assigns IDs `c-<turn>-<idx>` and emits matching ```` ```tool_result[c-N-i] ```` blocks. The agent is FORBIDDEN from emitting `tool_result` blocks; doing so produces a structured protocol-error tool_result.
- **Atomic all-or-none promotion** of staged candidates via `promote_atomic(...)` — validate every `candidate_<n>.json`, promote all OR preserve staging on failure. `GenVerResult` carries `skipped_duplicate_count` and `skipped_invalid_count` separately.
- **Cold-start pre-stage** on cycle 0 only — when `snapshot.done_count == 0` AND no seeds present, copy 3 fixture seeds from `factory/genver/fixtures/cold_start/<problem>/` into `runs/<cycle-id>/seeds/<sha>.json` with `<sha>.meta.json` provenance. Idempotent.
- **STOP-file polling** — the `stop_run` tool writes `runs/<cycle-id>/STOP`; the outer state machine (spec 003) polls between cycles and halts continuous operation when present.
- **`refresh_state` callback per turn** — re-renders the `## State` user message from current sandbox state immediately before every LLM round-trip; prevents the agent from operating on stale state.
- **`notes.md` persistence** — `write_notes` writes directly to `runs/<cycle-id>/notes.md` (≤ 64 KB), NOT subject to atomic-promote; survives every error path.
- **OpenRouter dispatch** — all LLM round-trips (agent invocation, compaction summarizer) go through the shared `OpenRouterClient` (spec 018) at `model="google/gemini-3.5-flash"`. No temperature override. Cost computed from the OpenRouter `usage` block.
- **Token-budget tracker** — `estimate_tokens(messages)` returns `int(sum(len(content)) * 0.25)` (chars / 4, FIX_PLAN §27.1); triggers compaction when the running total exceeds the budget.
- **LLM-driven compaction** — `compact(messages, summarize_fn, preserve_turns=5)` replaces older turn-blocks with one synthetic `system` summary; the summarizer call goes through the same OpenRouter client at the same model.
- **Per-turn checkpointing** for non-retryable failures — `oauth_refresh_failed`, `openrouter_auth_failed`, `compaction_failed`, `llm_invoke_failed` write `runs/<cycle-id>/sessions/turn_<n>_partial.json` carrying the message log up to the failing turn.
- **Protocol-error tool_results** — bundling `done`/`stop_run` with `query_db`/`read_file`/`list_files` rejects the whole response; multiple terminals in one response honor the first and reject the rest. Both paths emit structured `ok=False` tool_results with the protocol-error reason.
- **A `GenVerResult` typed result** with a granular `terminal_status` and a `to_gate_outcome()` mapping method for spec 003 consumption.
- **Recorder schema additions** (spec 012): `harness_version`, `skipped_duplicate_count`, `skipped_invalid_count`, `progress_kind ∈ {first_feasible, improved, regressed, flat}`, `feasibility_delta`. Taxonomized `error_type` values: `compaction_failed`, `openrouter_auth_failed`, `max_turns_no_output`, `candidate_validation_failed`, `llm_invoke_failed`, `empty_output_done`.
- **Strategy archive integration** (spec 016, FIX_PLAN §26.4) — optional `parent_strategy_sha: str | None` on `GenVerLoop.run(...)`; when non-None, threaded into the code-gen prompt; emits `StrategyCycleEvidence` (spec 002) at every cycle terminal.
- CLI: `run`, `replay`, `inspect`, `show-turn`, `compact-preview`, `diff-turns`.
- Mock mode covering: deterministic transcript replay via `FileClient`, deterministic adapter, in-process sandbox, fixture transcripts under `factory/genver/fixtures/transcripts/`.

**Out of scope:**
- Any judgment about whether the candidate boundaries are physically correct (specs 009, 010).
- Council-mediated turn-level deliberation (Phase B; this spec exposes a hook but Phase A does not invoke it).
- Per-vendor LLM substitution / vendor lineup logic (FIX_PLAN §25 / spec 001 owns council vendor heterogeneity; this loop is deliberately single-model `google/gemini-3.5-flash`).
- EvidenceLedger writes (spec 012; the state machine does this after the loop returns).
- Container builds (spec 004 — the simulator container is built once and reused; the loop's `run_python` sandbox is not a container).
- Continuous reuse of the agent's message history across cycles (each cycle starts fresh; cross-cycle memory lives in `notes.md` and the EvidenceLedger).
- Auto-tuning `MAX_TURNS` or `AUTO_COMPACT_TOKEN_LIMIT` (config-only; FIX_PLAN §27.1 fixes both).
- Retries beyond `MAX_TURNS` (a fresh cycle is the only "retry" mechanism, governed by `EvidenceLedger.relitigate_if`).
- Multi-model bandit / model-routing (Phase B; FIX_PLAN §22 lists this as deferred).

## 3. Public Interface

> **LLM access (FIX_PLAN §25 + §27.2 — spec 018).** Every LLM round-trip — agent invocation AND compaction summarizer — goes through the shared `OpenRouterClient` (spec 018) at `model="google/gemini-3.5-flash"`. The single env var is `OPENROUTER_API_KEY`. Base URL is `https://openrouter.ai/api/v1`. There is no Gemini-direct SDK import (`from google import genai` is forbidden). `BudgetTracker.record(cost_usd=..., tokens=...)` is called from the OpenRouter response's `usage` block (`prompt_tokens` + `completion_tokens`). Default sampling parameters; no temperature override.

```python
# factory/genver/api.py

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Protocol, Sequence

from factory.artifacts import (
    ArtifactHash,
    Budget,
    CycleId,
    ExperimentSpec,
    HypothesisId,
    HypothesisSpec,
    StrategyCycleEvidence,
)
from factory.budget import BudgetTracker
from factory.llm_client import (
    DecisionClient,
    OpenRouterAuthError,
    TransientAPIError,
)
from factory.state_machine import GateOutcome


# --- Loop-level constants (FIX_PLAN §27.1, fixed) -------------------------

MAX_TURNS: int = 25
AUTO_COMPACT_TOKEN_LIMIT: int = 200_000
TOKENS_PER_CHAR_FALLBACK: float = 0.25            # 1 token ≈ 4 chars
DEFAULT_PRESERVE_TURNS: int = 5                   # turn-blocks kept intact during compaction
NOTES_BYTES_CAP: int = 64 * 1024                  # write_notes ceiling
READ_BYTES_CAP: int = 256 * 1024                  # read_file ceiling
SQL_RESULT_BYTES_CAP: int = 256 * 1024            # query_db ceiling
SQL_QUERY_TIMEOUT_S: int = 30                     # query_db SIGALRM timeout
SQL_DEFAULT_LIMIT: int = 1000                     # auto-injected if absent
RUN_PYTHON_DEFAULT_TIMEOUT_S: int = 1800          # run_python wall-clock default


# --- Error taxonomy ------------------------------------------------------

class GenVerError(FactoryError): ...
class MaxTurnsReached(GenVerError): ...
class CompactionFailed(GenVerError): ...
class CandidateValidationError(GenVerError): ...
class StagingPromoteRaced(GenVerError): ...
class RollbackFailed(GenVerError): ...
class EmptyOutputDone(GenVerError): ...
class LlmInvokeFailed(GenVerError): ...
class ToolError(Exception):
    """Raised by individual tool handlers; converted to ok=False tool_result by dispatcher.
    Not a GenVerError because tool failures are routine and do not terminate the loop."""


# --- Tool surface (the ReAct contract) ----------------------------------

ToolName = Literal[
    "query_db", "read_file", "list_files", "run_python",
    "write_candidate", "write_notes", "done", "stop_run",
]
TOOL_NAMES: frozenset[ToolName] = frozenset({
    "query_db", "read_file", "list_files", "run_python",
    "write_candidate", "write_notes", "done", "stop_run",
})


@dataclass(frozen=True)
class ToolCall:
    """A parsed tool invocation from the agent's response."""
    id: str                                       # harness-assigned c-<turn>-<idx>
    name: ToolName
    args: dict[str, Any]                          # tool-specific


@dataclass(frozen=True)
class ToolResult:
    """The dispatcher's response to a single tool call."""
    id: str                                       # matches the originating ToolCall.id
    name: ToolName | Literal["<malformed>"]
    ok: bool
    payload: Any                                  # JSON-serializable; {"error": "..."} on ok=False


@dataclass
class ToolContext:
    """Per-cycle state the dispatcher mutates as tools run."""
    run_dir: Path                                 # runs/<cycle-id>/
    staging_dir: Path                             # runs/<cycle-id>/staging/
    db_path: Path                                 # SQLite path for query_db read-only conn
    candidates_written: list[Path] = field(default_factory=list)
    notes_content: str | None = None
    done: bool = False
    stop_run: bool = False
    done_reason: str | None = None
    stop_reason: str | None = None
    tool_failure_count: int = 0                   # used to classify empty_output_done
    parent_strategy_sha: str | None = None        # FIX_PLAN §26.4


# --- Session + result ---------------------------------------------------

@dataclass
class CycleSession:
    """All mutable state for one cycle's multi-turn conversation."""
    messages: list[dict] = field(default_factory=list)
    turn_count: int = 0
    token_usage: int = 0
    ctx: ToolContext | None = None                # caller MUST set before run_cycle()


@dataclass(frozen=True)
class CycleResult:
    """What GenVerLoop receives from run_cycle() before promotion."""
    candidates: list[Path]                        # staged candidate_<n>.json paths
    notes: str | None                             # notes.md content if write_notes was called
    done_reason: str | None
    stop_run: bool
    stop_reason: str | None
    turn_count: int
    token_usage: int
    error: str | None = None                      # taxonomized error_type value (§6)


@dataclass(frozen=True)
class TurnRecord:
    """One turn's transcript entry — appended to runs/<cycle-id>/turns/<NNN>.json."""
    turn_index: int                               # 0-based
    llm_cost_usd: float
    llm_tokens_in: int
    llm_tokens_out: int
    llm_wall_clock_s: float
    tool_calls: tuple[str, ...]                   # tool names dispatched this turn
    tool_failures: int                            # ok=False non-terminal results this turn
    compaction_fired: bool
    token_usage_after: int


@dataclass(frozen=True)
class GenVerResult:
    """Returned to the state machine after the loop terminates."""
    cycle_id: CycleId
    hypothesis_id: HypothesisId
    turns: tuple[TurnRecord, ...]
    terminal_status: Literal[
        "promoted",                               # at least one candidate promoted
        "promoted_no_candidates",                 # agent called done/stop_run with no candidates
        "intractable_max_turns",
        "intractable_compaction_failed",
        "intractable_openrouter_auth_failed",
        "intractable_candidate_validation_failed",
        "intractable_empty_output_done",
        "intractable_llm_invoke_failed",
        "intractable_adapter_failure",
        "stopped_by_agent",                       # stop_run fired
    ]
    promoted_artifact_hashes: tuple[ArtifactHash, ...]
    skipped_duplicate_count: int                  # FIX_PLAN §27.1 — tracked separately
    skipped_invalid_count: int                    # FIX_PLAN §27.1 — tracked separately
    progress_kind: Literal["first_feasible", "improved", "regressed", "flat"]
    feasibility_delta: float | None               # pre/post snapshot best_feasibility delta
    total_cost_usd: float
    total_tokens: int
    total_wall_clock_s: float
    notes_path: Path | None                       # runs/<cycle-id>/notes.md if write_notes fired
    error_type: str | None = None                 # taxonomized — see §6

    def to_gate_outcome(self) -> GateOutcome:
        """Map granular terminal_status to the canonical spec-003 GateOutcome.

        Mapping (FIX_PLAN §2 + spec 003):
          promoted                                       -> GateOutcome.PASS
          promoted_no_candidates                         -> GateOutcome.INCONCLUSIVE
          stopped_by_agent                               -> GateOutcome.PARKED
          intractable_max_turns                          -> GateOutcome.INTRACTABLE
          intractable_compaction_failed                  -> GateOutcome.INTRACTABLE
          intractable_openrouter_auth_failed             -> GateOutcome.INTRACTABLE
          intractable_candidate_validation_failed        -> GateOutcome.INTRACTABLE
          intractable_empty_output_done                  -> GateOutcome.INTRACTABLE
          intractable_llm_invoke_failed                  -> GateOutcome.INTRACTABLE
          intractable_adapter_failure                    -> GateOutcome.INTRACTABLE

        The state machine reads this method's return value to choose the next
        route in `gate_routes.yaml`. The granular terminal_status is preserved
        on the EvidenceLedgerEntry for forensics and to populate
        `relitigate_if` triggers.
        """


# --- Loop driver --------------------------------------------------------

class GenVerLoop:
    def __init__(
        self,
        client: DecisionClient,                   # spec 018 — same instance for agent + summarizer
        adapter: "AbstractSolverAdapter",         # spec 006 — passed into run_python sandbox
        tracker: BudgetTracker,                   # spec 013 — live budget authority
        budget: Budget,                           # spec 002 — frozen caps artifact (audit reference)
        hypothesis_id: HypothesisId,
        cycle_id: CycleId,
        run_dir: Path,
        max_turns: int = MAX_TURNS,
        token_budget: int = AUTO_COMPACT_TOKEN_LIMIT,
        preserve_turns: int = DEFAULT_PRESERVE_TURNS,
        mock_mode: bool = False,
    ) -> None:
        """Validate run_dir exists, allocate the staging dir, prepare the system prompt."""

    def run(
        self,
        hypothesis: HypothesisSpec,
        experiment: ExperimentSpec,
        *,
        parent_strategy_sha: str | None = None,
    ) -> GenVerResult:
        """Execute the loop. Returns a GenVerResult.

        Never raises for normal failure modes (parse, runtime, tool errors,
        compaction failure, candidate validation failure, max-turns) — those
        are encoded in GenVerResult.terminal_status / error_type. Only raises
        for unrecoverable infrastructure errors (StagingPromoteRaced,
        RollbackFailed, AdapterFailureUnrecoverable). Failures propagate to
        the state machine without defensive interception.

        `parent_strategy_sha` (FIX_PLAN §26.4) — optional strategy lineage
        anchor sourced from `StrategyArchive.select_lineages(k)`
        (specs/016-strategy-archive.md). When `StrategyArchiveConfig.enabled
        is True` and `parallel_lineages_k > 1`, the caller (state machine)
        passes the lineage sha so the code-gen prompt can carry the active
        strategy context. Phase A default is `None` (un-parented run,
        backward compatible). On terminal the loop emits a
        `StrategyCycleEvidence` artifact (spec 002) keyed by this sha for
        the archive to attribute surprise and reward against.
        """

    def replay(self, run_dir: Path) -> tuple[TurnRecord, ...]:
        """Walk persisted runs/<cycle-id>/turns/<NNN>.json files and reconstruct
        TurnRecords without re-running anything. Used by
        `python -m factory.genver replay`.
        """


# --- ReAct text protocol — parser surface (declared here so the contract is
#     auditable; implementation lives in factory/genver/turn_loop.py) -----

def parse_tool_calls(response_text: str, *, turn: int) -> list[ToolCall | _MalformedCall]:
    """Extract harness-owned tool calls; reject protocol-owned tool_result.

    IDs are assigned by the harness as ``c-<turn>-<idx>``. The agent never
    emits ``id`` or ``tool_result``. Malformed/protocol-invalid blocks are
    returned as ``_MalformedCall`` so the dispatcher can echo a structured
    error back to the agent (a single ``tool_result[c-<turn>-0]`` with
    payload ``{"error": "..."}``).
    """

def render_tool_result(result: ToolResult) -> str:
    """Format a ToolResult as a fenced ``tool_result[id]`` block.

    Body is ``json.dumps({"ok": result.ok, "payload": result.payload},
    default=str)``. Used by the dispatcher to append into the message log.
    """

def estimate_tokens(messages: Sequence[dict]) -> int:
    """Rough token count: ``int(sum(len(content)) * 0.25)``.

    The OpenRouter SSE stream does not return usage in deltas, and
    tiktoken is not in the dependency set. This char/4 estimate is
    accurate enough to trigger compaction at the right order of magnitude.
    """

def run_cycle(
    session: CycleSession,
    llm_invoke: Callable[[list[dict]], str],
    *,
    summarize: Callable[[Sequence[dict]], str] | None = None,
    refresh_state: Callable[[], str] | None = None,
    max_turns: int = MAX_TURNS,
    token_budget: int = AUTO_COMPACT_TOKEN_LIMIT,
) -> CycleResult:
    """Drive the multi-turn loop until the agent ends the cycle or a cap fires.

    Args:
        session: Mutable state. Must already have ``messages`` seeded with
            the system prompt + initial user message, and ``ctx`` populated.
        llm_invoke: Callable taking the current message list, returning the
            assistant's response text (one OpenRouter round-trip).
        summarize: Optional callable for compaction's summarizer LLM call;
            when None, compaction is disabled (caller's responsibility).
        refresh_state: Optional callback that re-renders the current
            ``## State`` user message before every LLM round-trip.
        max_turns: Hard cap on dispatch iterations.
        token_budget: Token threshold above which compaction triggers.

    Returns:
        CycleResult with candidates emitted, notes content, terminal
        reasons, counts, and taxonomized error if any.
    """


# --- Cold-start pre-stage (FIX_PLAN §27.1 — idempotent, cycle 0 only) ----

@dataclass(frozen=True)
class StagedSeed:
    """One staged seed boundary plus its provenance metadata path."""
    sha: str
    boundary_path: Path                           # runs/<cycle-id>/seeds/<sha>.json
    meta_path: Path                               # runs/<cycle-id>/seeds/<sha>.meta.json

def stage_cold_start_seeds(
    run_dir: Path,
    problem: str,
    *,
    n: int = 3,
) -> tuple[StagedSeed, ...]:
    """Pre-stage ``n`` cold-start seed boundaries under runs/<cycle-id>/seeds/.

    Idempotent: returns the existing seeds if the directory already has
    boundary files. Otherwise loads seeds from
    ``factory/genver/fixtures/cold_start/<problem>/`` and writes both
    ``<sha>.json`` (the boundary) and ``<sha>.meta.json`` (provenance).
    """


# --- Atomic promotion (FIX_PLAN §27.1 — all-or-none) ---------------------

@dataclass(frozen=True)
class PromotionResult:
    """What promote_atomic returns to the loop."""
    inserted_ids: tuple[int, ...]
    skipped_duplicate_count: int
    skipped_invalid_count: int                    # always 0 when promote_atomic returns;
                                                  # non-zero values arrive via raised
                                                  # CandidateValidationError, caught + recorded
                                                  # by the caller
    staging_dir: Path                             # caller wipes ONLY after conn.commit() succeeds

def promote_atomic(
    *,
    conn: "sqlite3.Connection",
    staging_dir: Path,
    run_dir: Path,
    experiment_id: int,
    problem: str,
    cycle_id: int,
    model: str,
) -> PromotionResult:
    """Validate every staged candidate then atomically enqueue.

    Workflow:
      * Collect every ``candidate_<n>.json`` in ``staging_dir``.
      * Canonicalize + sanitize each. If ANY fail, raise
        ``CandidateValidationError`` listing all failures. Staging is
        preserved; the caller records ``error_type=candidate_validation_failed``
        and ``skipped_invalid_count = <count>``.
      * Otherwise enqueue every boundary inside the caller's transaction;
        duplicates (sha collision against existing rows) bump
        ``skipped_duplicate_count``.
      * Staging dir is PRESERVED on return — caller MUST invoke
        ``wipe_staging`` on ``PromotionResult.staging_dir`` AFTER a
        successful ``conn.commit()`` so an interrupted commit leaves
        staging on disk for recovery.
    """

def wipe_staging(staging_dir: Path) -> None:
    """Delete the staging dir tree. Caller invokes ONLY after conn.commit()
    succeeds. Raises ``RollbackFailed`` on filesystem error (cycle is
    durably recorded but staging artifacts leak — operator alert).
    """
```

The state machine consumes `GenVerResult.to_gate_outcome()` to route to the next gate via `config/gate_routes.yaml`. When the outcome is `PASS`, `promoted_artifact_hashes` are added to the cycle's input bundle and forwarded to G3 / G4 dispatch (specs 010 and 009). The granular `terminal_status` is preserved on the downstream `EvidenceLedgerEntry` so `relitigate_if` triggers can distinguish "max-turns reached" from "compaction failed" from "candidate validation failed" from "OpenRouter auth failed."

## 4. Data Structures / Schemas

### 4.1 Per-cycle staging directory layout

Each cycle writes everything under `runs/<cycle-id>/`. The staging subdir is created fresh per cycle (no reuse across cycles). Notes are written directly to the cycle root and survive every error path.

```
runs/<cycle-id>/
├── seeds/                              Cold-start pre-stage (FIX_PLAN §27.1; cycle 0 only).
│   ├── <sha>.json                      Boundary copied from fixtures/cold_start/<problem>/.
│   └── <sha>.meta.json                 {source, problem, rank, n_field_periods}.
├── staging/                            Per-cycle staging; wiped only AFTER conn.commit().
│   ├── candidate_0.json                Canonicalized boundary written by write_candidate
│   │                                   or run_python's bulk-write path.
│   ├── candidate_0.operator_family     Optional sidecar (one line of plain text); attributes
│   │                                   the candidate to the strategy lineage (spec 016).
│   ├── candidate_1.json                ...
│   ├── strategies/                     Optional — mirrored from run_python's strategy_files.
│   │   └── <strategy-sha>.md           YAML-frontmatter rationale; consumed by spec 016 sweep.
│   └── parents/                        Optional — run_python's sandbox temp dir for parent
│                                       boundaries the agent loaded for mutation.
├── notes.md                            Agent's scratchpad (≤ 64 KB). Written directly by
│                                       write_notes. NOT subject to atomic-promote.
├── turns/                              One file per LLM round-trip.
│   ├── 000.json                        TurnRecord + raw response text + parsed tool calls
│   ├── 000.prompt.txt                  The exact message list sent to OpenRouter (verbatim).
│   ├── 000.response.txt                The raw LLM response text (verbatim, pre-parse).
│   └── ...
├── sessions/                           Checkpoints for non-retryable error paths.
│   └── turn_<NNNN>_partial.json        {error, reason, turn_count, token_usage,
│                                       candidates_written, messages}.
├── cycle.jsonl                         Append-only event log (spec 014 namespace).
└── STOP                                Written by stop_run; outer state machine polls between
                                        cycles.
```

The legacy per-iteration layout (`sandbox/<iteration:03d>/`) from the pre-FIX_PLAN-§27 draft of this spec is deprecated. There is no per-iteration directory in the multi-turn architecture — a turn is not an iteration, and turns share the same staging dir.

### 4.2 `runs/<cycle-id>/cycle.jsonl` events (genver namespace)

Append-only JSONL, one record per event. Event names declared in `factory/genver/events.py` under `factory.genver.*`:

| Event | When emitted | Required fields |
| :--- | :--- | :--- |
| `factory.genver.turn_start` | Before LLM round-trip N | `turn`, `cycle_id`, `token_usage_before` |
| `factory.genver.turn_end` | After dispatch of turn N's tool_calls | `turn`, `cost_usd`, `tokens_in`, `tokens_out`, `tool_calls`, `tool_failures` |
| `factory.genver.tool_call_start` | Before dispatching a single tool call | `turn`, `call_id`, `tool_name`, `args_size_bytes` |
| `factory.genver.tool_call_end` | After tool returns (ok or error) | `turn`, `call_id`, `tool_name`, `ok`, `payload_size_bytes`, `duration_ms` |
| `factory.genver.compaction_attempt` | When token_usage exceeds budget | `turn`, `token_usage_before`, `preserve_turns` |
| `factory.genver.compaction_succeeded` | After compaction reduces messages | `turn`, `token_usage_before`, `token_usage_after`, `messages_summarized` |
| `factory.genver.compaction_failed` | Summarizer returned unchanged or raised | `turn`, `consecutive_failures`, `error` |
| `factory.genver.cold_start_pre_stage` | Cold-start seeds copied into seeds/ | `cycle_id`, `problem`, `n_seeds`, `seed_shas` |
| `factory.genver.promote_attempt` | Before promote_atomic call | `cycle_id`, `staged_count` |
| `factory.genver.promote_succeeded` | After successful conn.commit() | `cycle_id`, `inserted_ids`, `skipped_duplicate_count`, `skipped_invalid_count` |
| `factory.genver.promote_failed` | CandidateValidationError raised | `cycle_id`, `failure_count`, `failures` |
| `factory.genver.stop_run` | stop_run tool fired | `turn`, `reason` |

Spec 014's aggregator picks these up at startup; events are no-op when spec 014 is not wired.

### 4.3 Loop config (`config/genver.yaml`)

```yaml
max_turns: 25                          # FIX_PLAN §27.1 — fixed; do not auto-tune
auto_compact_token_limit: 200000       # FIX_PLAN §27.1 — fixed; do not auto-tune
preserve_turns: 5                      # turn-blocks kept intact during compaction
notes_bytes_cap: 65536                 # write_notes ceiling
read_bytes_cap: 262144                 # read_file ceiling
sql_result_bytes_cap: 262144           # query_db ceiling
sql_query_timeout_s: 30                # query_db SIGALRM timeout
sql_default_limit: 1000                # auto-injected when missing
run_python_default_timeout_s: 1800     # run_python wall-clock default
prompt:
  system_template_path: factory/genver/prompts/system.md
  state_template_path: factory/genver/prompts/state.md
  max_tokens_per_call: 8192
  per_call_timeout_s: 90
model:
  # FIX_PLAN §25.5 + §27.2: agentic LLM default is google/gemini-3.5-flash via OpenRouter.
  model_id: google/gemini-3.5-flash
  vendor: google
sandbox:
  imports_whitelist_path: config/sandbox_imports.yaml
  allowed_write_root_subpath: staging  # runs/<cycle-id>/staging/
```

All thresholds are configuration, never code (per `ARCHITECTURE.md` §4.5). FIX_PLAN §27.1 fixes `max_turns=25` and `auto_compact_token_limit=200000`; operators MAY NOT auto-tune these per cycle.

### 4.4 ReAct text-fence protocol (parser contract)

The assistant emits zero or more `tool_call` fenced blocks per response. The harness assigns IDs `c-<turn>-<idx>` and emits matching `tool_result[c-<turn>-<idx>]` blocks. The assistant is FORBIDDEN from emitting `tool_result` blocks; doing so produces a structured protocol-error tool_result and ends the turn.

**Tool-call envelope:**

````
```tool_call
{
  "name": "<one of TOOL_NAMES>",
  "args": { "<tool-specific keys>": ... }
}
```
````

**Tool-result envelope (harness-emitted only):**

````
```tool_result[c-7-0]
{"ok": true, "payload": { "<tool-specific>": ... }}
```
````

Parser rules (`factory/genver/turn_loop.py:parse_tool_calls`):
1. If the response contains any `tool_result` fenced block, reject the whole response: emit one synthetic `tool_result[c-<turn>-0]` with `ok=False` payload `{"error": "assistant must not emit tool_result blocks; only the harness emits tool_result"}` and continue to the next turn.
2. Otherwise iterate all `tool_call` fenced blocks. For each:
   a. JSON-decode the body. On `JSONDecodeError`, emit a malformed-call tool_result and continue.
   b. Validate it is a JSON object. On non-object, emit a malformed-call tool_result and continue.
   c. Validate `name` is a string and is in `TOOL_NAMES`. On unknown/missing name, emit a malformed-call tool_result and continue.
   d. Validate `args` is a JSON object. On non-object, emit a malformed-call tool_result and continue.
   e. Otherwise yield `ToolCall(id=f"c-{turn}-{idx}", name=name, args=args)`.

**Bundling rules** (enforced before dispatch):
- A response containing a terminal call (`done` or `stop_run`) AND a read tool (`query_db` / `read_file` / `list_files`) rejects the WHOLE response with one synthetic protocol-error tool_result. Rationale: a terminal+read bundle means the agent's terminal decision was made BEFORE seeing the read results, so the writes (if any) and the terminal are both based on unread data.
- A response containing multiple terminal calls honors the FIRST and rejects the rest with a protocol-error tool_result. Rationale: silent last-wins overwriting of `done_reason` lets the agent claim contradictory outcomes.
- Otherwise calls dispatch in array order.

**Worked example — single-turn investigation + write:**

````
```tool_call
{"name": "query_db", "args": {"sql": "SELECT id, feasibility FROM candidates WHERE problem='p1' ORDER BY feasibility DESC LIMIT 5"}}
```

```tool_call
{"name": "read_file", "args": {"path": "seeds/abc123.json"}}
```
````

The harness dispatches both, appends two `tool_result` blocks, and continues. The agent then sees the results in the next round-trip and may emit `write_candidate` plus `done` in a single follow-up response (allowed — no reads bundled with terminal).

**Worked example — protocol error (read bundled with terminal):**

````
```tool_call
{"name": "query_db", "args": {"sql": "SELECT COUNT(*) FROM candidates"}}
```

```tool_call
{"name": "done", "args": {"reason": "Investigation complete."}}
```
````

The harness rejects the whole response, emits one `tool_result[c-<turn>-0]` with `ok=False` payload `{"protocol_error": "query_db/read_file/list_files in a response that also contains done/stop_run is a protocol error; the entire response is rejected and no tools are dispatched. Investigate in one turn, then emit writes plus one terminal in the next response."}`, and advances the turn counter without dispatching either call.

**Worked example — tool result (write_candidate success):**

````
```tool_result[c-3-0]
{"ok": true, "payload": {"path": "candidate_2.json"}}
```
````

### 4.5 Per-tool args schemas

| Tool | Args schema | Returns (payload on `ok=True`) | Persists |
| :--- | :--- | :--- | :--- |
| `query_db` | `{"sql": str}` (single SELECT/WITH/EXPLAIN; ≤ 30s; ≤ 256 KB result; auto-inject `LIMIT 1000`) | `{"columns": list[str], "rows": list[list]}` | — |
| `read_file` | `{"path": str}` (relative to `run_dir`; `os.open(O_NOFOLLOW)`; ≤ 256 KB) | `{"text": str}` | — |
| `list_files` | `{"glob": str}` (relative glob; symlinks dropped; ≤ 256 KB serialized) | `{"paths": list[str]}` | — |
| `run_python` | `{"code": str, "timeout": int = 1800}` (subprocess sandbox, see §5.4) | `{"candidates_written": list[str]}` | candidates + sidecars into `staging/`; strategy `.md` files into `staging/strategies/` |
| `write_candidate` | `{"filename": "candidate_<n>.json", "boundary": dict}` (canonicalized) | `{"path": str}` | candidate JSON into `staging/` |
| `write_notes` | `{"content": str}` (≤ 64 KB; overwrite) | `{"bytes": int}` | overwrites `runs/<cycle-id>/notes.md` directly |
| `done` | `{"reason": str}` | `{"acknowledged": true}` | sets `ctx.done = True`, `ctx.done_reason = reason` |
| `stop_run` | `{"reason": str}` | `{"acknowledged": true, "stop_file": str}` | writes `runs/<cycle-id>/STOP`; sets `ctx.done = True`, `ctx.stop_run = True` |

All tool args must be JSON-serializable. Unknown args keys are ignored. Missing required args produce `ok=False, payload={"error": "<key> is required"}`.

### 4.6 `progress_kind` derivation (FIX_PLAN §27.1 recorder schema)

```python
def derive_progress_kind(
    pre_best_feasibility: float | None,
    post_best_feasibility: float | None,
) -> Literal["first_feasible", "improved", "regressed", "flat"]:
    if pre_best_feasibility is None and post_best_feasibility is not None:
        return "first_feasible"
    if pre_best_feasibility is None and post_best_feasibility is None:
        return "flat"
    delta = post_best_feasibility - pre_best_feasibility
    if delta > 0:
        return "improved"
    if delta < 0:
        return "regressed"
    return "flat"
```

`feasibility_delta` is `post - pre` (or `None` if `pre is None`).

## 5. Algorithms / Logic

### 5.1 Top-level `GenVerLoop.run`

```
GenVerLoop.run(hypothesis, experiment, parent_strategy_sha=None):
    assert state_machine has already done EvidenceLedger G0 dedup lookup
    snapshot_pre  = read_snapshot(conn, hypothesis_id)
    pre_best_feasibility = snapshot_pre.best_feasibility

    # 5.2 Cold-start pre-stage (cycle 0 + zero seeds + zero evaluated candidates)
    if snapshot_pre.done_count == 0 and not _seeds_present(run_dir):
        stage_cold_start_seeds(run_dir, experiment.problem_id, n=3)

    # 5.3 Initial message log
    staging_dir = run_dir / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    ctx = ToolContext(
        run_dir=run_dir, staging_dir=staging_dir, db_path=conn.db_path,
        parent_strategy_sha=parent_strategy_sha,
    )
    session = CycleSession(ctx=ctx)
    session.messages = [
        {"role": "system", "content": build_system_prompt(hypothesis, experiment,
                                                           parent_strategy_sha)},
        {"role": "user",   "content": build_state_message(conn, hypothesis_id)},
    ]

    # 5.4 Define the per-turn callbacks
    def llm_invoke(messages):
        resp = client.invoke(messages, model="google/gemini-3.5-flash",
                             max_tokens=cfg.max_tokens_per_call)
        tracker.record(hypothesis_id=hypothesis_id, module="genver",
                       cost_usd=resp.cost_usd, tokens=resp.input_tokens + resp.output_tokens,
                       wall_clock_seconds=resp.wall_clock_seconds,
                       description=f"turn {session.turn_count}")
        return resp.text

    def summarize(older_messages):
        # Same model, dedicated summarization system prompt.
        resp = client.invoke(
            [{"role": "system", "content": summarization_prompt()},
             *older_messages],
            model="google/gemini-3.5-flash", max_tokens=4096,
        )
        tracker.record(hypothesis_id=hypothesis_id, module="genver",
                       cost_usd=resp.cost_usd, tokens=resp.input_tokens + resp.output_tokens,
                       wall_clock_seconds=resp.wall_clock_seconds,
                       description=f"compaction at turn {session.turn_count}")
        return resp.text

    def refresh_state():
        return build_state_message(conn, hypothesis_id)

    # 5.5 Run the multi-turn loop (FIX_PLAN §27.1 — proxima turn_loop.run_cycle)
    cycle_result = run_cycle(
        session, llm_invoke,
        summarize=summarize,
        refresh_state=refresh_state,
        max_turns=MAX_TURNS,
        token_budget=AUTO_COMPACT_TOKEN_LIMIT,
    )

    # 5.6 Translate cycle_result.error into terminal_status
    terminal = _classify_terminal(cycle_result)

    # 5.7 Atomic all-or-none promotion (FIX_PLAN §27.1)
    snapshot_post = snapshot_pre
    skipped_invalid = 0
    if cycle_result.candidates:
        try:
            promotion = promote_atomic(
                conn=conn, staging_dir=staging_dir, run_dir=run_dir,
                experiment_id=experiment.id, problem=experiment.problem_id,
                cycle_id=cycle_id, model="google/gemini-3.5-flash",
            )
            conn.commit()                    # commits BEFORE wipe_staging
            wipe_staging(promotion.staging_dir)
            promoted_hashes = _resolve_hashes(promotion.inserted_ids, conn)
            terminal = "promoted"
            snapshot_post = read_snapshot(conn, hypothesis_id)
        except CandidateValidationError as exc:
            # Atomic all-or-none: NOTHING promoted; staging preserved.
            skipped_invalid = exc.failure_count
            terminal = "intractable_candidate_validation_failed"
            promoted_hashes = ()
    elif terminal == "promoted_no_candidates" and cycle_result.error is None:
        # Agent called done with no candidates and no errors — clean no-improvement.
        promoted_hashes = ()
    else:
        promoted_hashes = ()

    # 5.8 progress_kind + feasibility_delta (FIX_PLAN §27.1 recorder schema)
    progress_kind, feasibility_delta = _derive_progress(
        snapshot_pre.best_feasibility, snapshot_post.best_feasibility,
    )

    # 5.9 StrategyCycleEvidence (FIX_PLAN §26.4; emitted on EVERY terminal)
    emit_strategy_cycle_evidence(StrategyCycleEvidence(
        strategy_sha=parent_strategy_sha,
        cycle_id=cycle_id,
        best_objective=snapshot_post.best_objective,
        best_feasibility_distance=snapshot_post.best_feasibility_distance,
        feasible_count=snapshot_post.feasible_count,
        constraint_overshoots=snapshot_post.constraint_overshoots,
    ))

    return GenVerResult(
        cycle_id=cycle_id, hypothesis_id=hypothesis_id,
        turns=_load_turn_records(run_dir),
        terminal_status=terminal,
        promoted_artifact_hashes=promoted_hashes,
        skipped_duplicate_count=promotion.skipped_duplicate_count if promoted_hashes else 0,
        skipped_invalid_count=skipped_invalid,
        progress_kind=progress_kind,
        feasibility_delta=feasibility_delta,
        total_cost_usd=tracker.cycle_cost(cycle_id),
        total_tokens=tracker.cycle_tokens(cycle_id),
        total_wall_clock_s=tracker.cycle_wall_clock(cycle_id),
        notes_path=(run_dir / "notes.md") if (run_dir / "notes.md").exists() else None,
        error_type=cycle_result.error,
    )
```

The state machine catches `StagingPromoteRaced` / `RollbackFailed` / `AdapterFailureUnrecoverable` — those propagate as exceptions. Every other failure is encoded in the returned `GenVerResult`.

### 5.2 `run_cycle` — the proxima turn_loop pattern

```
run_cycle(session, llm_invoke, summarize, refresh_state, max_turns, token_budget):
    ctx = session.ctx
    consecutive_compaction_failures = 0

    while not ctx.done:
        # 5.2.1 — MAX_TURNS guard
        if session.turn_count >= max_turns:
            return CycleResult(error="max_turns_no_output" if not ctx.candidates_written else None,
                               ...)

        # 5.2.2 — Refresh per-turn state message
        if refresh_state is not None:
            _replace_state_message(session.messages, refresh_state())

        # 5.2.3 — Compaction trigger (FIX_PLAN §27.1 — 200_000 tokens)
        session.token_usage = estimate_tokens(session.messages)
        if summarize is not None and session.token_usage > token_budget:
            new_messages = compact(session.messages, summarize, preserve_turns=5)
            if len(new_messages) == len(session.messages):
                consecutive_compaction_failures += 1
                if consecutive_compaction_failures >= 2:
                    _checkpoint_session(session, ctx, error="compaction_failed",
                                         reason="summarizer returned unchanged twice")
                    return CycleResult(error="compaction_failed", ...)
            else:
                consecutive_compaction_failures = 0
                session.messages = new_messages
                if refresh_state is not None:
                    _replace_state_message(session.messages, refresh_state())
                session.token_usage = estimate_tokens(session.messages)

        # 5.2.4 — LLM round-trip
        try:
            response_text = llm_invoke(session.messages)
        except OpenRouterAuthError as exc:
            _checkpoint_session(session, ctx, error="openrouter_auth_failed", reason=str(exc))
            return CycleResult(error="openrouter_auth_failed", ...)
        except TransientAPIError:
            # Backoff is OpenRouterClient's responsibility (spec 018);
            # if the client gave up, propagate so state machine records it.
            raise
        except Exception as exc:
            _checkpoint_session(session, ctx, error="llm_invoke_failed", reason=str(exc))
            return CycleResult(error=f"llm_invoke_failed: {exc}", ...)

        session.messages.append({"role": "assistant", "content": response_text})

        # 5.2.5 — Parse tool calls
        calls = parse_tool_calls(response_text, turn=session.turn_count)
        if not calls:
            # Text-only response = natural end of turn
            ctx.done = True
            ctx.done_reason = ctx.done_reason or "model produced no tool calls"
            break

        # 5.2.6 — Apply bundling rules and dispatch
        non_terminal = [c for c in calls if not (isinstance(c, ToolCall) and is_terminal(c.name))]
        terminal     = [c for c in calls if isinstance(c, ToolCall) and is_terminal(c.name)]

        if terminal:
            # Terminal in this response — apply bundling rules
            read_calls = [c for c in non_terminal
                          if isinstance(c, ToolCall) and not is_write_tool(c.name)]
            if read_calls:
                # Reject WHOLE response (terminal + read bundle)
                ctx.tool_failure_count += 1
                session.messages.append(_protocol_error_terminal_with_read(read_calls[0]))
                session.turn_count += 1
                continue
            # Writes + first terminal only
            for call in non_terminal:
                session.messages.append(_dispatch_one(call, ctx))
            session.messages.append(_dispatch_one(terminal[0], ctx))
            for extra in terminal[1:]:
                session.messages.append(_protocol_error_extra_terminal(extra))
        else:
            for call in non_terminal:
                session.messages.append(_dispatch_one(call, ctx))

        session.turn_count += 1
        write_turn_record(run_dir, session, response_text, calls)

    # Classify empty-output-done
    if not ctx.candidates_written and ctx.tool_failure_count > 0:
        return CycleResult(error="empty_output_done", ...)
    return CycleResult(...)
```

### 5.3 Compaction

`compact(messages, summarize_fn, preserve_turns=5)` follows the proxima pattern:

1. Split off leading `system` messages — preserve them untouched.
2. Group remaining messages into turn-blocks: each block starts with a `user` or `assistant` message and includes any subsequent `tool` / tool_result messages until the next `user` / `assistant` boundary.
3. If `len(turn_blocks) <= preserve_turns`, return the input unchanged.
4. Older blocks = `turn_blocks[:-preserve_turns]`; recent = `turn_blocks[-preserve_turns:]`.
5. Flatten older blocks to one message list; call `summarize_fn(older_msgs)`.
6. On `TransientAPIError`: re-raise. On any other exception: log and return input unchanged (the caller's consecutive-failure counter handles this).
7. On success: return `head + [summary_msg] + recent` where `summary_msg = {"role": "system", "content": "## Compacted history\n\n..."}`.

The summarization system prompt (FIX_PLAN §27.1; matches proxima `summarization_prompt()`):

```
You are summarizing an autonomous agent's investigation transcript so that the
agent can continue the same task in a new session with reduced context. Produce
a tight summary that preserves:

1. Every SQL query the agent ran AND its result (numerical values, not just
   descriptions).
2. Every hypothesis the agent stated AND whether evaluation supported or
   refuted it.
3. Every candidate boundary the agent emitted AND its measured feasibility/
   objective if known.
4. Every tool error encountered AND what the agent did about it.
5. The agent's current best understanding of which strategy directions are
   productive vs dead.

Drop: agent prose that did not lead to action; helper-function definitions;
speculative discussion that was overridden.

Format: bullet list under headings. Be specific and quantitative. Do NOT add
advice or recommendations of your own — only summarize what the agent did and
learned.
```

If the summarizer LLM call raises `TransientAPIError`, it propagates out of `compact` so the OpenRouterClient's backoff can fire (spec 018). If it raises anything else (or returns identical message count), the caller's `consecutive_compaction_failures` counter increments; **two consecutive failures** terminate the cycle with `error_type="compaction_failed"`.

### 5.4 `run_python` sandbox

The `run_python` tool wraps a subprocess-level sandbox identical to the proxima harness pattern:

1. Spawn `python -m factory.genver.sandbox_runner --code-file <fd> --adapter <adapter_module> --output-root <staging_dir>/parents --timeout <timeout_s>` as a child process.
2. Apply POSIX resource limits via `setrlimit`:
   - `RLIMIT_CPU` → CPU seconds.
   - `RLIMIT_AS` → virtual memory; subsequent allocations fail with `MemoryError` (the wrapper inspects the exit code + captured exception to classify).
   - `RLIMIT_FSIZE` → per-file write cap.
   - `RLIMIT_NOFILE` → open-file count.
3. Apply wall-clock limit via parent-side `subprocess.Popen(...).wait(timeout=timeout_s)`. On timeout, SIGTERM then SIGKILL after 5 s.
4. Restrict filesystem writes to `staging_dir/parents/` via the runner's pre-execution shim (monkey-patches `builtins.open`, `os.open`, `pathlib.Path.open`).
5. Restrict imports to a whitelist loaded from `config/sandbox_imports.yaml` via a `sys.meta_path` finder.
6. After the subprocess exits, the runner emits a `SandboxResult` carrying any `candidate_<n>.json` files written, optional `<name>.operator_family` sidecars, and any `strategies/<sha>.md` rationale files.
7. The dispatcher re-indexes the candidates under the cycle's running counter (`candidate_<len(ctx.candidates_written) + i>.json`), copies them into `ctx.staging_dir/`, and appends them to `ctx.candidates_written`.
8. Strategy files (when present) are mirrored into `ctx.staging_dir/strategies/` for the post-cycle archive sweep.

Resource exceedances surface as `ToolError("sandbox error: SandboxResourceExceeded(kind=...)")` and produce an `ok=False` tool_result. The loop does NOT terminate on a single sandbox failure — the agent decides whether to retry, mutate, or move on. The loop terminates only when the agent calls `done` / `stop_run`, replies with no tool calls, or hits `MAX_TURNS`.

### 5.5 Cold-start pre-stage

Triggered exactly once per cycle 0, by `GenVerLoop.run` before any LLM call:

```
if snapshot.done_count == 0 and not (run_dir / "seeds").exists_with_jsons():
    stage_cold_start_seeds(run_dir, experiment.problem_id, n=3)
```

The function copies 3 boundaries from `factory/genver/fixtures/cold_start/<problem_id>/` (e.g., `p1/`, `p2/`, `p3/`) into `runs/<cycle-id>/seeds/<sha>.json` and writes a `<sha>.meta.json` sidecar with provenance `{"source": "factory/genver/fixtures/cold_start", "problem": <problem_id>, "rank": <int>, "n_field_periods": <int>}`. Idempotent: a second call with the seeds dir already populated returns the existing `StagedSeed` tuples without re-reading the fixtures.

The agent is told about the seeds in the system prompt and the per-turn `## State` block (file pointers + brief description). The agent decides whether to read them; the loop does NOT auto-load them into the context window.

### 5.6 Atomic all-or-none promotion

`promote_atomic` (FIX_PLAN §27.1) is the proxima `promote.py` pattern adapted for the factory:

```
promote_atomic(conn, staging_dir, run_dir, experiment_id, problem, cycle_id, model):
    # 1. Collect every candidate_<n>.json (sorted by name).
    paths = collect_candidate_paths(staging_dir)

    # 2. Validate every candidate (canonicalize + sanitize). If ANY fail,
    #    raise CandidateValidationError listing ALL failures. The caller
    #    catches this, records error_type=candidate_validation_failed, and
    #    sets skipped_invalid_count = failure_count. Staging is preserved.
    boundaries = validate_candidates(paths)

    # 3. Enqueue every boundary inside the caller's transaction.
    #    duplicate detection is on boundary sha collision.
    inserted_ids, duplicate_count = [], 0
    for i, boundary in enumerate(boundaries):
        operator_family = read_operator_family_sidecar(paths[i])
        record = enqueue_candidate(
            conn, experiment_id=experiment_id, problem=problem, run_dir=run_dir,
            batch_id=cycle_id, boundary=boundary,
            seed=cycle_id * 1_000 + i,
            move_family="genver_agent",
            parents=[],
            knobs={"cycle": cycle_id, "index": i},
            novelty_score=None,
            operator_family=operator_family,
            model_route=f"genver/{model}/{cycle_id}",
            cycle_id=cycle_id,
        )
        if record is None:
            duplicate_count += 1
            continue
        inserted_ids.append(record.candidate_id)

    # 4. Return; staging is PRESERVED.
    return PromotionResult(
        inserted_ids=tuple(inserted_ids),
        skipped_duplicate_count=duplicate_count,
        skipped_invalid_count=0,
        staging_dir=staging_dir,
    )
```

The caller's contract:
- Call `promote_atomic(...)` INSIDE an open transaction.
- On success: call `conn.commit()`, THEN call `wipe_staging(promotion.staging_dir)`. If `conn.commit()` raises (lock, disk-full, IO error), staging stays on disk so the cycle can be recovered.
- On `CandidateValidationError`: roll back the transaction (`conn.rollback()`), record `error_type="candidate_validation_failed"` and `skipped_invalid_count = exc.failure_count`, leave staging in place for forensics.

Atomicity is at the **batch level**: either every candidate is promoted OR none are. The proxima per-file `os.replace` dance is unnecessary because candidates live in a SQLite-backed ledger, not a file artifact store — atomicity is the SQLite transaction.

### 5.7 `refresh_state` callback

Before EVERY LLM round-trip, the loop calls `refresh_state()` and replaces the current `## State` user message in `session.messages`. The state message is re-rendered from `conn` so the agent always sees the current snapshot — best_feasibility_so_far, candidates_emitted_this_cycle, budget remaining (read from `BudgetTracker.remaining(hypothesis_id)`), archive context (when spec 016 enabled).

The `## State` message ALWAYS begins with the literal `## State` line. The loop identifies the current state message by prefix match (`content.startswith("## State")`) and replaces it with the new render. If no state message is present (cycle's first turn), the new one is appended.

This prevents the agent from operating on stale state across turns — a common failure mode in long-running ReAct loops where the agent's belief about the world diverges from ground truth between read and write.

### 5.8 Strategy archive integration (FIX_PLAN §26.4 / spec 016)

When `parent_strategy_sha` is non-None on `GenVerLoop.run(...)`:

1. The system prompt's "Strategy lineage" section is populated with `parent_strategy_sha` and a one-paragraph summary fetched via `StrategyArchive.expand(parent_strategy_sha).summary`.
2. The per-turn `## State` block includes a "Lineage" header with the parent sha, reward EMA, surprise EMA, and visit count.
3. On terminal (success or failure), the loop emits a `StrategyCycleEvidence` artifact (spec 002) with the cycle's outcome metrics.
4. The caller (state machine) forwards the evidence into `StrategyArchive.attribute_surprise(...)` and `StrategyArchive.attribute_reward(...)`.

When `parent_strategy_sha is None` (Phase A default; `parallel_lineages_k=1`):
- The system prompt's "Strategy lineage" section is omitted.
- The state block has no "Lineage" header.
- `StrategyCycleEvidence` is still emitted but with `strategy_sha=None`; the archive ignores it.

### 5.9 EvidenceLedger lookup at G0 — interaction contract

The G0 dedup lookup is the state machine's responsibility, not this loop's. Per FIX_PLAN §2 and §3, the state machine handles dedup with a `GateOutcome.PASS` carrying `dedup_skip: True` metadata; that PASS is then routed to `terminate_dedup_skip` per spec 003's routing table.

This loop is invoked only AFTER that check has cleared. The loop never queries the ledger directly (it queries the candidates / experiments tables via `query_db`, which is a different surface); the loop also never writes the ledger. The loop returns a `GenVerResult`; the state machine packages that into the appropriate `EvidenceLedgerEntry`.

### 5.10 Numerical gullibility and invariant hacking — explicit non-defense

Per `SPEC.md` §10.2–10.3, this loop is **not the front line** against:

- **Numerical gullibility** (the agent's `run_python` blueprint produces formulas it cannot actually simulate; the loop dispatches them happily as long as they emit a parseable candidate).
- **Invariant hacking** (the blueprint satisfies named invariants — energy conservation, $\nabla\cdot\mathbf{B}=0$ — without solving the actual problem, often by hard-coding the invariant residual to zero in the output).

The loop's promotion gate is strictly mechanical (canonicalize + sanitize); it checks the boundary *is well-formed*. The promotion gate cannot tell whether the boundary reflects a valid solution or a hand-rolled lie. The layered defenses are:

1. **G2.5 dry-run** — the state machine runs this loop on a toy problem before committing real budget. If the toy fails, the hypothesis is `intractable` before money is spent.
2. **G3 surrogate** (spec 010) — a learned surrogate scores the proposed boundary against the relevant observable distribution. OOD detection forces direct oracle escalation; the surrogate cannot give a clean pass to obviously-distorted candidates.
3. **G4 validation portfolio** (spec 009) — the actual scientific defense. Refinement convergence catches "satisfies invariant but wrong answer at any resolution." Held-out symmetry tests catch invariant hacking. Cross-simulator checks catch simulator-specific over-fitting.

A reviewer who reads this spec and assumes the loop has solved either failure mode has misread the spec. This section exists so that mistake never gets made.

## 6. Failure Modes

| Error class | When it fires | Recovery action |
| :--- | :--- | :--- |
| `MaxTurnsReached` | `session.turn_count >= MAX_TURNS=25` without a terminal call | Encoded as `terminal_status="intractable_max_turns"`; `error_type="max_turns_no_output"` when `candidates_written == []`, else `None`; `to_gate_outcome() = INTRACTABLE`; staging preserved on validation failure or wiped after commit otherwise; checkpoint NOT written (the message log is already on disk via `turns/<NNN>.json`). |
| `CompactionFailed` | Summarizer returned unchanged OR raised twice in a row above the token budget | Encoded as `terminal_status="intractable_compaction_failed"`; `error_type="compaction_failed"`; `to_gate_outcome() = INTRACTABLE`; checkpoint `sessions/turn_<n>_partial.json` written; staging preserved. Distinct from `TransientAPIError` — those propagate. |
| `OpenRouterAuthError` (from spec 018) | OpenRouter rejected the agent or summarizer call with 401/403 | Encoded as `terminal_status="intractable_openrouter_auth_failed"`; `error_type="openrouter_auth_failed"`; `to_gate_outcome() = INTRACTABLE`; non-retryable; checkpoint written; operator must rotate `OPENROUTER_API_KEY`. |
| `TransientAPIError` (from spec 018) | Rate limit, 5xx, connection error from OpenRouter after the client's internal backoff exhausted | Propagates out of `GenVerLoop.run`; the state machine decides whether to re-enter the cycle on backoff. The loop itself does not retry. |
| `CandidateValidationError` | At least one `candidate_<n>.json` in `staging/` fails canonicalize or sanitize | Atomic all-or-none: NOTHING promoted; staging preserved; `terminal_status="intractable_candidate_validation_failed"`; `error_type="candidate_validation_failed"`; `skipped_invalid_count = failure_count`; `to_gate_outcome() = INTRACTABLE`. |
| `LlmInvokeFailed` | Unclassified exception from `client.invoke(...)` (NOT `TransientAPIError`, NOT `OpenRouterAuthError`) | Encoded as `terminal_status="intractable_llm_invoke_failed"`; `error_type="llm_invoke_failed: <message>"`; `to_gate_outcome() = INTRACTABLE`; checkpoint written. |
| `EmptyOutputDone` (classification) | Agent called `done` with `candidates_written == []` AND `tool_failure_count > 0` | Encoded as `terminal_status="intractable_empty_output_done"`; `error_type="empty_output_done"`; `to_gate_outcome() = INTRACTABLE`. Distinct from clean no-improvement (agent investigated, found nothing, called done cleanly — that is `promoted_no_candidates` / `INCONCLUSIVE`). |
| `ToolError` (per call) | Single tool handler raised | Converted to `ok=False` tool_result by the dispatcher; loop continues; `tool_failure_count++` if non-terminal. Does NOT terminate the loop. |
| `ProtocolError: terminal+read` | Agent bundled `done`/`stop_run` with `query_db`/`read_file`/`list_files` in same response | Whole response rejected: single synthetic `ok=False` tool_result with `payload={"protocol_error": "..."}`; turn counter advances; loop continues without dispatching ANY of the bundled calls. `tool_failure_count++`. |
| `ProtocolError: multiple terminals` | Agent emitted multiple `done`/`stop_run` calls in same response | First terminal honored; remaining terminals each receive a synthetic `ok=False` tool_result with `payload={"protocol_error": "multiple terminal calls; only the first is honored"}`. |
| `ProtocolError: assistant tool_result` | Agent emitted a `tool_result` fenced block (forbidden) | Whole response rejected with a synthetic `ok=False` tool_result; turn counter advances; loop continues without dispatching anything. |
| `StagingPromoteRaced` | Another process touched the staging directory between final validation and atomic move | Raised immediately; cycle halted; state machine handles as infrastructure failure; staging preserved on disk for forensics. |
| `RollbackFailed` | `wipe_staging` raised a filesystem error AFTER `conn.commit()` succeeded | Raised immediately; the cycle IS durably recorded but staging artifacts leak; operator alert; no automatic recovery. |
| `AdapterFailureUnrecoverable` | Spec-006 adapter raised before any LLM call could even start (e.g., simulator binary missing) | Encoded as `terminal_status="intractable_adapter_failure"`; `to_gate_outcome() = INTRACTABLE`; relitigation trigger = "simulator version updated in catalog". |

All error classes (except `ToolError`) inherit from `FactoryError` per FIX_PLAN §14. `ToolError` is deliberately NOT a `FactoryError` because tool failures are routine — they do not terminate the loop and they do not propagate to the state machine as exceptions.

The first nine rows are *normal* loop outcomes — encoded in `GenVerResult.terminal_status` / `error_type`, returned without raising. Only `StagingPromoteRaced`, `RollbackFailed`, and `AdapterFailureUnrecoverable` propagate as exceptions; those are infrastructure failures, not scientific failures, and the state machine handles them differently from a normal `intractable`.

## 7. Testing

**Mock-mode** (in CI, no external services):
- `test_genver_typical_usage.py` — REQUIRED. Replay the `sample_three_turns` transcript fixture via `FileClient`. Verify: `terminal_status == "promoted"`, `to_gate_outcome() == GateOutcome.PASS`, `len(turns) == 3`, `len(promoted_artifact_hashes) >= 1`, `notes_path` exists, `staging/` wiped after commit.
- `test_parse_tool_calls_basic.py` — feed a response with one valid `tool_call` block; assert one `ToolCall(id="c-0-0", name="...", args={...})`.
- `test_parse_tool_calls_multiple.py` — feed three valid `tool_call` blocks; assert three `ToolCall`s with sequential IDs `c-0-0`, `c-0-1`, `c-0-2`.
- `test_parse_tool_calls_malformed_json.py` — body is not valid JSON; assert one `_MalformedCall` with the parse-error reason.
- `test_parse_tool_calls_unknown_tool.py` — `name="foobar"`; assert one `_MalformedCall` with the unknown-tool reason.
- `test_parse_tool_calls_assistant_tool_result.py` — assistant emitted a `tool_result` block; assert one `_MalformedCall` and the WHOLE response is rejected.
- `test_bundling_terminal_with_read.py` — response carries `query_db` + `done`; assert one synthetic protocol-error tool_result, neither call dispatched, turn counter advances.
- `test_bundling_multiple_terminals.py` — response carries two `done` calls; assert first honored, second receives protocol-error tool_result.
- `test_bundling_terminal_with_write.py` — response carries `write_candidate` + `done`; assert BOTH dispatched (writes allowed alongside terminal).
- `test_compaction_triggers_at_budget.py` — seed messages whose `estimate_tokens > 200_000`; assert `compact` is called; assert `len(new_messages) < len(old_messages)`; assert `session.token_usage` decreases.
- `test_compaction_disabled_when_summarize_none.py` — pass `summarize=None`; assert compaction never triggers even at 1M tokens; loop terminates on `max_turns_no_output`.
- `test_compaction_consecutive_failure.py` — `summarize_fn` returns identical messages; assert two consecutive calls trigger `terminal_status="intractable_compaction_failed"` and a checkpoint is written.
- `test_compaction_preserves_recent_turns.py` — assert the last 5 turn-blocks are kept intact; older blocks compressed into one synthetic `system` message.
- `test_max_turns_no_output.py` — `FileClient` replays 25 turns with no `write_candidate`; assert `terminal_status="intractable_max_turns"`, `error_type="max_turns_no_output"`, `to_gate_outcome() == INTRACTABLE`.
- `test_empty_output_done.py` — `FileClient` replays an agent that calls `done` with no candidates AND emits a `run_python` call that raised `ToolError`; assert `terminal_status="intractable_empty_output_done"`, `error_type="empty_output_done"`.
- `test_promoted_no_candidates.py` — `FileClient` replays an agent that investigates then calls `done` with no candidates and NO tool failures; assert `terminal_status="promoted_no_candidates"`, `to_gate_outcome() == INCONCLUSIVE`.
- `test_atomic_promotion_all_or_none.py` — staging contains three candidates, one of which fails sanitization; assert `CandidateValidationError` is raised by `promote_atomic`; assert `error_type="candidate_validation_failed"`; assert `skipped_invalid_count == 1`; assert staging is preserved AFTER the call.
- `test_atomic_promotion_duplicate_count.py` — staging contains three candidates, one of which is a duplicate of an existing row; assert `skipped_duplicate_count == 1`; assert `len(promoted_artifact_hashes) == 2`.
- `test_wipe_staging_only_after_commit.py` — inject a `conn.commit()` failure; assert `wipe_staging` is NOT called; assert `staging/` is preserved.
- `test_cold_start_pre_stage_cycle_0.py` — `snapshot.done_count == 0` and no seeds; assert `stage_cold_start_seeds` copies 3 fixture seeds with `.meta.json` sidecars.
- `test_cold_start_idempotent.py` — call `stage_cold_start_seeds` twice; assert second call returns the existing seeds without re-reading fixtures.
- `test_cold_start_skipped_after_cycle_0.py` — `snapshot.done_count > 0`; assert `stage_cold_start_seeds` is NOT called.
- `test_stop_run_writes_stop_file.py` — agent calls `stop_run`; assert `runs/<cycle-id>/STOP` is written with the reason; assert `terminal_status="stopped_by_agent"`, `to_gate_outcome() == PARKED`.
- `test_refresh_state_called_every_turn.py` — wrap `refresh_state` in a counter; assert call count equals turn count.
- `test_refresh_state_replaces_existing.py` — seed the message list with a stale `## State` message; assert the next turn's state replaces it (no duplicate `## State` blocks).
- `test_notes_md_survives_validation_failure.py` — agent calls `write_notes` then emits an invalid candidate; assert `notes.md` is present on disk even though staging is preserved unwiped.
- `test_openrouter_auth_failed_checkpoint.py` — `client.invoke` raises `OpenRouterAuthError`; assert `terminal_status="intractable_openrouter_auth_failed"`, `error_type="openrouter_auth_failed"`, `sessions/turn_<n>_partial.json` is written with the message log.
- `test_transient_api_error_propagates.py` — `client.invoke` raises `TransientAPIError`; assert it propagates out of `GenVerLoop.run` (state machine handles backoff).
- `test_llm_invoke_failed_checkpoint.py` — `client.invoke` raises `RuntimeError("???")`; assert `terminal_status="intractable_llm_invoke_failed"`, `error_type` starts with `"llm_invoke_failed:"`, checkpoint written.
- `test_progress_kind_first_feasible.py` — pre snapshot `best_feasibility = None`, post `best_feasibility = 0.5`; assert `progress_kind="first_feasible"`, `feasibility_delta is None`.
- `test_progress_kind_improved.py` — pre `0.4`, post `0.5`; assert `progress_kind="improved"`, `feasibility_delta=0.1`.
- `test_progress_kind_regressed.py` — pre `0.5`, post `0.4`; assert `progress_kind="regressed"`, `feasibility_delta=-0.1`.
- `test_progress_kind_flat.py` — pre `0.5`, post `0.5`; assert `progress_kind="flat"`, `feasibility_delta=0.0`.
- `test_gate_outcome_mapping.py` — for every value of `terminal_status`, assert `GenVerResult(...).to_gate_outcome()` returns the documented mapping.
- `test_tool_query_db_select_only.py` — `args={"sql": "DROP TABLE x"}`; assert `ok=False` payload `{"error": "..."}`.
- `test_tool_query_db_timeout.py` — `args={"sql": "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM r) SELECT * FROM r"}`; assert `ok=False` payload contains `"30s timeout"`.
- `test_tool_query_db_limit_injected.py` — `args={"sql": "SELECT * FROM candidates"}`; assert returned `len(rows) <= 1000`.
- `test_tool_read_file_o_nofollow.py` — symlink under `run_dir/`; assert `ok=False` payload mentions the open error.
- `test_tool_read_file_escapes_run_dir.py` — `args={"path": "../../etc/passwd"}`; assert `ok=False` payload `{"error": "path escapes RUN_DIR: ..."}`.
- `test_tool_list_files_drops_symlinks.py` — symlinks under `run_dir/`; assert they do not appear in the returned `paths`.
- `test_tool_write_candidate_canonicalizes.py` — `args={"filename": "candidate_0.json", "boundary": {...with non-canonical zeros...}}`; assert the on-disk JSON matches the canonical shape.
- `test_tool_write_candidate_invalid_filename.py` — `args={"filename": "foo.json", ...}`; assert `ok=False` payload `{"error": "filename must match candidate_<n>.json ..."}`.
- `test_tool_write_notes_size_cap.py` — content > 64 KB; assert `ok=False` payload `{"error": "notes exceed 65536 bytes"}`.
- `test_tool_run_python_appends_candidates.py` — sandbox writes 2 candidate JSONs; assert `ctx.candidates_written` grows by 2.
- `test_tool_run_python_sandbox_error.py` — code raises `RuntimeError`; assert `ToolError` is caught and an `ok=False` tool_result is returned; assert `tool_failure_count++`.
- `test_replay.py` — run loop end-to-end, call `replay(run_dir)`; assert reconstructed `TurnRecord`s match.
- `test_strategy_archive_evidence_emitted_on_terminal.py` — pass `parent_strategy_sha="abc123"`; assert `StrategyCycleEvidence` is emitted exactly once at terminal with the correct strategy_sha.
- `test_strategy_archive_evidence_with_none_sha.py` — pass `parent_strategy_sha=None`; assert `StrategyCycleEvidence` is emitted with `strategy_sha=None` (archive ignores it).
- `test_budget_tracker_record_args.py` — assert every LLM call (agent + summarizer) calls `tracker.record(hypothesis_id=..., module="genver", cost_usd=..., tokens=..., wall_clock_seconds=..., description=...)` with the canonical kwarg set.

**Live-mode** (`@pytest.mark.live`, gated):
- `test_live_one_turn.py` — single turn against the real OpenRouter client and a real spec-006 adapter (simplest adapter only). Asserts total cost < $0.05 via `tracker.remaining(...)`.
- `test_live_toy_problem_dry_run.py` — full loop against the toy problem used by G2.5; asserts `terminal_status="promoted"` within 5 turns and total cost < $0.50.

**Acceptance test** (PRD-001 §90-day milestone): the loop completes the G2.5 dry-run for the canonical Phase A hypothesis within 5 turns and ≤ $0.125, with all per-turn artifacts present, atomic-promote verified, `notes.md` populated, and `progress_kind="first_feasible"`.

**Manual verification step** (one-time, runbook): inspect at least one live trace by hand to confirm (a) the `## State` block actually re-renders between turns, (b) `notes.md` contains substantive agent reasoning, (c) the compaction summary (when triggered) preserves the SQL queries the agent ran.

## 8. Performance & Budget

- Per-turn orchestrator overhead (parser + dispatch, excluding LLM call and sandbox): < 100 ms.
- LLM round-trip wall-clock target: < 8 s typical (Gemini Flash via OpenRouter; FIX_PLAN §25.5).
- Per-turn LLM cost target: ≤ $0.005 (8 k input + 4 k output at `google/gemini-3.5-flash` pricing via OpenRouter — FIX_PLAN §25.6 + §27.2).
- Per-cycle cap envelope: **25 turns × $0.005 = $0.125** typical LLM spend. The hypothesis cap in `HypothesisCaps` is the canonical authority and is enforced by `BudgetTracker`, not by this loop's local math.
- Compaction call cost: ≤ $0.01 per fire (≤ 200 k input → ≤ 4 k output summary); typical cycle fires compaction at most once.
- Token estimate (`estimate_tokens`): O(n) over message content lengths; < 1 ms for any realistic message log.
- `query_db` per-call: ≤ 30 s SIGALRM timeout; ≤ 256 KB serialized result.
- `read_file` per-call: ≤ 256 KB.
- `run_python` per-call: ≤ 1800 s wall-clock default (overridable via `args.timeout`).
- Wall-clock per cycle: with 25 turns × 8 s = 200 s LLM time + sandbox time (when `run_python` is called) typically dominates; worst case ~10 minutes per cycle.
- The state machine's per-cycle wall-clock target (spec 003) is 72 hours; this loop's contribution is bounded above by ~10 minutes per cycle on typical hardware.

## 9. Open Questions

- **Compaction policy.** `preserve_turns=5` is the proxima default. Empirical data from the first 100 live cycles will tell us whether 5 is enough to keep the agent coherent across compactions or whether we should preserve more recent turns at the cost of more aggressive older-turn compression. Configurable, not hard-coded.
- **Per-tool token-budget hints.** The OpenRouter `max_tokens` for `client.invoke` is 8 k per turn; a turn that triggers compaction adds another LLM call (4 k summary). Whether to expose a per-tool hint that the agent can use to estimate its own per-turn budget is open.
- **Council-mediated turn deliberation.** Phase B may invoke `Council.deliberate(...)` at the start of a turn to pick between K candidate code mutations rather than dispatching one model. The spec exposes the hook but does not exercise it; the empirical question is whether 4x cost buys enough variance reduction to be worth it.
- **Sandbox import whitelist scope.** The default whitelist allows `numpy`, `scipy`, `jax`, plus the adapter's declared imports. If a Phase B adapter needs e.g. `torch`, the whitelist must be extended in `config/sandbox_imports.yaml`. Whether to support per-adapter whitelists or keep a single global one is open.
- **Cross-cycle memory beyond `notes.md`.** Right now the agent's only cross-cycle memory is `notes.md`. A future "load notes from a specific prior cycle by SHA" tool would let the agent build on its own past work across hypotheses; deferred.
- **Multi-model dispatch.** This loop is single-model `google/gemini-3.5-flash`. A Phase B bandit / model-router that picks between Gemini Flash and a more expensive model per turn (e.g., escalate to Sonnet when the agent is stuck) is FIX_PLAN §22's "deferred Phase B" item.
- **Promotion-of-partial-output.** If the agent emits 5 candidates and 1 fails sanitization, current rule is all-or-nothing. Whether to allow partial promotion is open; the bookkeeping (which 4 of 5 got promoted, how to report `skipped_invalid_count`) is non-trivial.

## 10. TODO Checklist

- [ ] Scaffold `factory/genver/` from the canonical module template per `ARCHITECTURE.md` §1.10.
- [ ] Import `OpenRouterClient` from `factory.llm_client` (spec 018) and wire it as the sole LLM substrate for both agent and summarizer calls. Forbid `from google import genai`.
- [ ] Implement `GenVerLoop.__init__` with config loading (`config/genver.yaml`) and validation (`MAX_TURNS==25`, `AUTO_COMPACT_TOKEN_LIMIT==200_000`, `preserve_turns>=1`, `notes_bytes_cap<=65536`).
- [ ] Implement `factory/genver/turn_loop.py` with `MAX_TURNS`, `AUTO_COMPACT_TOKEN_LIMIT`, `CycleSession`, `CycleResult`, `parse_tool_calls`, `render_tool_result`, `estimate_tokens`, `run_cycle`, `_checkpoint_session`.
- [ ] Implement `factory/genver/tools.py` with the 8-tool surface, the `ToolCall`/`ToolResult`/`ToolContext` dataclasses, the `dispatch` function, `is_terminal`, `is_write_tool`, `TOOL_NAMES`, and the per-tool safety invariants (sqlglot-style SQL allowlist, `O_NOFOLLOW`, glob escape check, subprocess sandbox, canonicalization).
- [ ] Implement `factory/genver/compaction.py` with `compact`, `summarization_prompt`, `DEFAULT_PRESERVE_TURNS`, the same prompt body as the proxima reference (FIX_PLAN §27.1).
- [ ] Implement `factory/genver/cold_start.py` with `stage_cold_start_seeds`, `StagedSeed`, and idempotence (no-op when seeds dir already populated).
- [ ] Implement `factory/genver/promote.py` with `promote_atomic`, `wipe_staging`, `PromotionResult`, `CandidateValidationError`, `collect_candidate_paths`, `validate_candidates`, `read_operator_family_sidecar`.
- [ ] Implement `factory/genver/canonicalize.py` (or share `factory/artifacts/canonicalize.py` if a single canonicalizer is preferred) — `canonicalize_boundary` zeros `r_cos[0][n<0]` AND `z_sin[0][n<=0]` per stellarator symmetry; `sanitize_candidate_boundary` rejects NaN/Inf.
- [ ] Implement `factory/genver/sandbox.py` subprocess launcher with `setrlimit`, wall-clock timer, SIGTERM/SIGKILL escalation, `MemoryError`-capture for `RLIMIT_AS`.
- [ ] Implement `factory/genver/sandbox_runner.py` (child entry point) with import whitelist via `sys.meta_path` finder and write-root restriction via monkey-patched `open` family.
- [ ] Implement `factory/genver/observation.py` with `build_system_prompt(hypothesis, experiment, parent_strategy_sha)` and `build_state_message(conn, hypothesis_id)`.
- [ ] Author `config/sandbox_imports.yaml` with the default whitelist.
- [ ] Author `factory/genver/prompts/system.md` declaring the 8-tool surface, the ReAct text-fence grammar, the spec-006 adapter interface, and the cold-start seed pointer.
- [ ] Author `factory/genver/prompts/state.md` template with placeholders for best-feasibility, candidates-this-cycle, budget remaining, archive lineage block.
- [ ] Author cold-start fixtures: `factory/genver/fixtures/cold_start/p1/`, `p2/`, `p3/` each containing 3 fixture seed boundaries with `.meta.json` sidecars.
- [ ] Author transcript fixtures under `factory/genver/fixtures/transcripts/`: `sample_three_turns.jsonl`, `compaction_trigger.jsonl`, `auth_failure.jsonl`, `protocol_error_terminal_with_read.jsonl`, `empty_output_done.jsonl`, `max_turns_no_output.jsonl`.
- [ ] Implement `GenVerLoop.run` per §5.1 (cold-start, message-log seeding, `run_cycle` call, terminal classification, atomic promotion, `progress_kind` derivation, `StrategyCycleEvidence` emission).
- [ ] Implement `GenVerResult.to_gate_outcome()` per the mapping documented in §3 and verify with `test_gate_outcome_mapping.py`.
- [ ] Implement `GenVerLoop.replay` (walks persisted `turns/<NNN>.json` and reconstructs `TurnRecord`s).
- [ ] Implement `factory/genver/cli.py` with `run`, `replay`, `inspect`, `show-turn`, `compact-preview`, `diff-turns` subcommands.
- [ ] Implement mocks: `MockAdapter`, `MockSandbox` (in-process; unit tests only). Use `FileClient` from spec 018 for the LLM mock.
- [ ] Wire `tracker.record(hypothesis_id=..., module="genver", cost_usd=..., tokens=..., wall_clock_seconds=..., description=...)` for every LLM call (agent + summarizer); never `budget.record_entry(...)` or `budget.dollar_remaining`.
- [ ] Declare telemetry events in `factory/genver/events.py` under the `factory.genver.*` namespace per §4.2; emit when spec 014 is wired, no-op otherwise.
- [ ] Author the mock-mode tests listed in §7. All pass in CI.
- [ ] Author the live-mode tests; manual gate.
- [ ] Write `factory/genver/README.md` (≤ 1 page; mock-mode example).
- [ ] Write `docs/runbooks/genver-debugging.md` covering: how to inspect a failed turn; how to interpret `sessions/turn_<n>_partial.json`; how to extend the import whitelist; how to debug a `compaction_failed`; how to read `tracker.remaining(...)` after an `intractable_*` outcome; how to recover staging after a `conn.commit()` failure.
- [ ] Verify `mypy --strict factory/genver/` passes.
- [ ] Verify `python -m factory.genver run --experiment-fixture sample --mock-mode` works on a fresh checkout.
- [ ] Wire `GenVerResult.to_gate_outcome()` into spec 003's gate routing: G2.5 outcomes (`PASS` → G3; `INCONCLUSIVE` → terminate_no_improvement; `PARKED` → terminate_operator_stop; `INTRACTABLE` → terminate_intractable); post-G4 re-invocation hooks.
- [ ] Wire the outer state machine (spec 003) to (a) poll `runs/<cycle-id>/STOP` between cycles and halt continuous operation when present, (b) decide cold-start cycle 0 vs subsequent cycles, (c) thread `parent_strategy_sha` when `parallel_lineages_k > 1`.
- [ ] PRD-001 acceptance: G2.5 dry-run for the canonical Phase A hypothesis completes in ≤ 5 turns and ≤ $0.125.
- [ ] Plumb `parent_strategy_sha: str | None = None` through `GenVerLoop.run(...)` per §3 and the FIX_PLAN §26.4 contract; thread it into the code-gen prompt only when non-None; default to `None` for Phase A backward compatibility.
- [ ] Emit `StrategyCycleEvidence` (spec 002) at every cycle terminal (success and failure) per §5.8; the archive ignores events with `strategy_sha=None`.
