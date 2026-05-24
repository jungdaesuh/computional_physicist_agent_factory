# Spec 016: Strategy Archive

> Status: ☐ not started · Owner: TBD · Last updated: 2026-05-23

## CONTEXT (60-second summary — read first)
- The **Strategy Archive** is the factory's *what to try next* substrate: a BFTS (Best-First Tree Search) + Bayesian-surprise + UCT (Upper-Confidence-bound on Trees) + MAP-Elites scaffold that decides which research strategies to spawn, mutate, cross, and inherit across cycles. It is *not* a judgment substrate (that is spec 001 Council) and it is *not* a code executor (that is spec 008 Generator-Verifier); it is the lineage planner that sits *between* them. The state machine (spec 003) calls into this archive at cycle terminals to attribute reward + surprise to the cycle's strategy, and at cycle starts (Phase B) to ask which lineage(s) to walk next.
- The 5 facts: (1) **Bayesian surprise is computed via Dirichlet KL** (or Beta-Bernoulli KL in the cheaper binary mode) over feasibility-bucket beliefs sampled from a separate **GuideLLM** — `KL(posterior || prior)` gated to `0.0` unless the unique dominant pre/post bucket changes (a **polarity gate** that prevents sampling noise from being counted as surprise). (2) **UCT composite scoring** = `reward_alpha × reward_norm + surprise_beta × surprise_norm + feasibility_gamma × feasibility_pressure + uct_exploration_constant × sqrt(log(total_visits) / (visits + 1)) + behavior_novelty_weight × novelty`, with the hard invariant `reward_alpha + surprise_beta == 1.0` enforced at config construction. (3) **Per-strategy EMAs** (`reward_ema`, `surprise_ema`, `feasibility_distance_ema`) are updated on every cycle observation via `new_ema = ema_alpha × observed + (1 - ema_alpha) × old_ema`, with NULL handling on cold start. (4) **Lineage selection** picks K parents for parallel BFTS branches; Phase A defaults to K=1 (single lineage walked through the gate sequence), Phase B promotes to K>1 with MAP-Elites cell-first then full-archive fallback. (5) **The GuideLLM is distinct from the council**: per FIX_PLAN §25.5 every non-council agentic LLM call uses `google/gemini-3.5-flash` via the shared OpenRouter client (`OPENROUTER_API_KEY`). The council adjudicates *judgments*; the GuideLLM elicits *belief shifts*.
- Open first: `factory/strategy/api.py` and the typical-usage test, then `factory/strategy/beliefs.py` for the KL math.

## ENTRY POINTS
- Main module: `factory/strategy/api.py`
- Typical-usage test: `factory/strategy/tests/test_strategy_archive_typical_usage.py`
- CLI: `python -m factory.strategy --help` (subcommands: `add`, `select`, `attribute-surprise`, `attribute-reward`, `top-k`, `transfer-priors`)
- Mock-mode example: `python -m factory.strategy attribute-surprise --strategy-fixture sample --evidence-fixture mid_cycle --mock-mode`
- Runbook: `docs/runbooks/strategy-archive.md`

## LOCAL DEBUG
- Instantiate without LLM calls: `StrategyArchive(config=StrategyArchiveConfig(), conn=sqlite3.connect(":memory:"), guide_llm=MockGuideLLM())` produces a runnable archive on a fresh in-memory DB. `MockGuideLLM` returns deterministic feasibility-bucket fixtures from `factory/strategy/fixtures/guide_llm/` so attribution is reproducible across CI runs.
- Fixture artifacts to feed it: `factory/strategy/fixtures/strategies/sample.md` (a complete `summary_md`), `factory/strategy/fixtures/evidence/mid_cycle.json` (a `StrategyCycleEvidence`), `factory/strategy/fixtures/guide_llm/{prior,posterior}_lt_10.json` (canned categorical samples).
- Common error signatures → recovery:
  - `SurpriseInvariantViolation` → `reward_alpha + surprise_beta` did not equal `1.0` at `StrategyArchiveConfig` construction; the composite UCT score must be a convex combination over `[0, 1]`-normalized reward and surprise terms. Fix the config (do not silently renormalize). Raised in `__post_init__`.
  - `DirichletDegenerateAlpha` → a `dirichlet_kl(...)` call received a non-positive alpha component, which is outside the Dirichlet support; this signals an upstream bug in the bucket-counts arithmetic (the `1 +` prior should make all alphas strictly positive). Do not pass a guard — fix the caller.
  - `BucketCountsEmpty` → `binary_bayesian_surprise` / `graded_bayesian_surprise` saw zero GuideLLM responses on either the pre- or post-evidence side; this means every `guide_llm.boolean(...)` or `guide_llm.feasibility_bucket(...)` call refused or errored. Inspect `runs/<cycle-id>/strategy/guide_llm.jsonl` for the per-call traces and re-run after the upstream issue is fixed.
  - `BehaviorDescriptorMissing` → `select_lineages(k)` was called but no candidate strategy has a populated `behavior_descriptor`; in Phase A that means lineage selection was invoked before any cycle has evaluated a candidate (so behavior descriptors haven't been backfilled from candidate metrics). Either wait until at least one full evaluation cycle has elapsed, or pass `enforce_behavior_descriptors=False` (Phase B only).
  - `GuideLLMRefusal` → `google/gemini-3.5-flash` (via OpenRouter) returned a refusal / safety-filtered response on a belief-eliciting prompt. Retry once with the same prompt; second failure raises. **No silent fallback to a different model** — single-model agentic dispatch is contract per FIX_PLAN §25.5.
  - `UCTAllScoresZero` → every candidate in the archive scored exactly `0.0` on the UCT composite; this is theoretically impossible because the exploration term `sqrt(log(total_visits) / (visits + 1))` is strictly positive for `total_visits >= 1`. If raised it indicates a corrupted SQLite row (likely a NULL `visits` column where the schema disallows it). Inspect `strategies` rows and patch via spec 012 Ledger.
  - `LineageSelectionEmpty` → `select_lineages(k)` returned fewer than `k` SHAs even after the `novel:<index>` filler logic ran; this is a programming bug (the loop should always pad to `k`). If raised, file a bug.
- Logs to inspect: every surprise / reward attribution writes a `factory.strategy.attribute` event with `{strategy_sha, surprise_bits, reward_observed, cycle_id, polarity_gated}` to `runs/<cycle-id>/cycle.jsonl`. Lineage selection writes a `factory.strategy.select_lineages` event with `{k, selected_shas, base_scores, novelty_bonuses, map_elites_bonuses}`. GuideLLM per-call traces (one row per `boolean` / `feasibility_bucket` invocation) land in `runs/<cycle-id>/strategy/guide_llm.jsonl`.

## DEPENDENCIES
- **Hard:** Spec 002 (artifacts) — consumes `Strategy`, `StrategyCycleEvidence`, `BehaviorDescriptor`, `ConstraintOvershootStats`. Spec 012 (Evidence Ledger / `Ledger` backend) — provides the SQLite connection that owns the `strategies`, `strategy_edges`, `strategy_subtree` tables.
- **Soft:** Spec 010 (surrogate models) — in Phase B, the surrogate's posterior variance can supply a *fallback* surprise signal when GuideLLM is unavailable; never overrides a GuideLLM-derived surprise in Phase A. Spec 014 (telemetry) — emits attribution + selection events if a telemetry sink is wired in.
- **Mocks available:** `MockGuideLLM` returning deterministic feasibility-bucket fixtures from `factory/strategy/fixtures/guide_llm/`. `MockSurrogateProbe` (Phase B) returning canned posterior-variance values. The archive itself does not need to be mocked — instantiate it on `sqlite3.connect(":memory:")` with the mock GuideLLM.

---

## 1. Summary

This module is the **lineage-planning substrate** of the factory. It does not judge (the council does) and it does not execute (the Generator-Verifier loop does); it decides *which strategy is worth one more cycle of attention* and tracks *whether the cycle's evidence shifted belief about that strategy's promise*. The archive is essentially a typed, persistent, per-experiment BFTS tree whose nodes carry rolling EMAs for reward and surprise, behavior descriptors for MAP-Elites cells, and a DAG of parent → child edges for crossover and mutation provenance.

The proxima fusion harness (`/Users/suhjungdae/code/software/proxima_fusion/ai-sci-feasible-designs/harness/`) ships a production-tested implementation of this contract — `beliefs.py`, `strategy_config.py`, `strategy_selection.py`, `strategy_evidence.py`, and the SQLite schema in `world_model_schema.py` — under a stellarator-design problem profile. This spec abstracts that implementation across problem profiles so a fresh adapter (spec 006) can plug in without re-prompting any LLM. Per FIX_PLAN §26 the abstraction stays faithful to the source: the KL math is unchanged, the polarity gate is unchanged, the UCT scoring shape is unchanged, the MAP-Elites cell logic is unchanged. Only the surface API and the typed-artifact boundary differ.

Loose coupling. The Generator-Verifier loop (spec 008) reports a `StrategyCycleEvidence` at iteration end; the archive computes surprise + reward EMAs and (optionally, when `parallel_lineages_k > 1`) returns a `parent_strategy_sha` for the next iteration. The state machine (spec 003) C5 program-direction council reads the archive's top-K productive strategies to make `DomainScope` decisions. The evidence ledger (spec 012) gains a `surprise_bits: float | None` column populated by this module's `attribute_surprise` call (per FIX_PLAN §26.2). Everything else is internal.

## 2. Scope

**In scope:**
- **Bayesian surprise computation**, two modes per FIX_PLAN §26.2:
  - **Binary mode (Phase A default)**: Beta-Bernoulli conjugacy on a single yes/no GuideLLM elicitation pre/post evidence. `2n` LLM calls per surprise evaluation (default `n=5` → 10 calls). 0.5-mean polarity gate.
  - **Graded mode (Phase B target)**: Dirichlet conjugacy on a 3-bucket feasibility-fraction GuideLLM elicitation. `2n` calls. Dominant-bucket polarity gate.
- **UCT composite scoring with novelty bonus**, including the `reward_alpha + surprise_beta == 1.0` convex-combination invariant (FIX_PLAN §26.2). Min-max normalization with documented cold-start defaults (`reward_norm: 0.5`, `surprise_norm: 0.0`, `distance_norm: 1.0`).
- **Per-strategy EMA tracking** for `reward_ema`, `surprise_ema`, `feasibility_distance_ema` with NULL-on-cold-start semantics; first observation populates the EMA at the observed value directly (no synthetic prior).
- **MAP-Elites cell bookkeeping**, parameterized over a `BehaviorDescriptor` artifact (spec 002). Phase A populates cells lazily from candidate metrics but does not select on cells (single lineage); Phase B turns on the cell-first selection sweep.
- **Lineage selection** (`select_lineages(k) -> list[str]`): K parent strategy SHAs (or `novel:<idx>` filler tokens when the archive is under-sized) chosen by the UCT score + novelty bonus + (Phase B) MAP-Elites cell bonus.
- **Cross-run prior transfer** (`transfer_priors_from(source_experiment_id, k) -> None`): import top-K strategies from a sibling experiment, prefix `provenance` with `transferred_from_exp_<source_id>`, reset visits / EMAs to NULL so the inheriting experiment starts each transferred lineage with a clean slate.
- **The GuideLLM protocol** (`async def boolean / async def feasibility_bucket`). Concrete implementation `GeminiFlashGuideLLM` uses the shared OpenRouter client (FIX_PLAN §25.1 / §25.5) and calls `google/gemini-3.5-flash`. The council client (spec 001) is reused for transport; only the model ID and the response schema differ.
- **SQLite-backed persistence** of `strategies`, `strategy_edges`, `strategy_subtree` (recursive view) tables. Schema matches the proxima harness contract — see §4 below.
- **Strategy authoring** via `add_strategy(summary_md, parents, kind) -> sha` — the SHA is the content hash of the canonicalized `summary_md`, so identical strategies dedup automatically.
- **CLI** with `add / select / attribute-surprise / attribute-reward / top-k / transfer-priors` subcommands reachable as `python -m factory.strategy <subcommand>`.
- **Mock mode** (`MockGuideLLM`) returning deterministic fixtures so the archive runs in CI with no external services.

**Out of scope:**
- **Strategy authoring prose / code generation** — the actual `summary_md` text and the code that implements a strategy are produced by the Generator-Verifier loop (spec 008). This module is given the markdown; it does not write it.
- **Distillation** of cross-strategy patterns into a higher-level summary (`distill.py` in the proxima harness). Phase B; the file is scaffolded in this spec's repo layout but the prose-generation logic is deferred.
- **Strategy DB FTS5 search** (`search_archive(query, k)` in the proxima harness). Phase B; the table `strategy_search_docs` is not part of this spec.
- **Judgment** — surprise and reward are *signals*, not decisions. Whether a strategy continues lives in the C-council deliberations (spec 001) and the gate routing (spec 003).
- **Sycophancy detection** — that is a council concern (spec 001 §5.4). Surprise has its own polarity gate that serves a different purpose (filtering sampling noise, not adversarial groupthink).
- **Cross-vendor LLM dispatch for GuideLLM** — agentic single-model dispatch is contract (FIX_PLAN §25.5). The council's multi-vendor heterogeneity does not extend here.
- **Active-learning surprise fallback via surrogate posterior variance** — Phase B; described in §9.

## 3. Public Interface

```python
# factory/strategy/api.py

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from factory.artifacts import (
    BehaviorDescriptor,
    ConstraintOvershootStats,
    CycleId,
    FactoryError,
    Strategy,
    StrategyCycleEvidence,
    StrategyKind,
)


# --------------------------------------------------------------------------
# Exception taxonomy — all inherit FactoryError (spec 002)
# --------------------------------------------------------------------------

class StrategyArchiveError(FactoryError): ...
class SurpriseInvariantViolation(StrategyArchiveError): ...
class DirichletDegenerateAlpha(StrategyArchiveError): ...
class BucketCountsEmpty(StrategyArchiveError): ...
class BehaviorDescriptorMissing(StrategyArchiveError): ...
class GuideLLMRefusal(StrategyArchiveError): ...
class UCTAllScoresZero(StrategyArchiveError): ...
class LineageSelectionEmpty(StrategyArchiveError): ...


# --------------------------------------------------------------------------
# Module-local typed aliases
# --------------------------------------------------------------------------

FeasibilityBucket = Literal["lt_10", "10_50", "gt_50"]
"""Three-bucket feasible-candidate fraction. Matches the proxima harness contract."""

# Internal bucket-counts tuple: (lt_10, 10_50, gt_50). Module-private.
_BucketCounts = tuple[int, int, int]


# --------------------------------------------------------------------------
# GuideLLM protocol (FIX_PLAN §25.5 — google/gemini-3.5-flash via OpenRouter)
# --------------------------------------------------------------------------

class GuideLLM(Protocol):
    """Belief-eliciting LLM, separate from the council.

    Concrete implementation `GeminiFlashGuideLLM` calls `google/gemini-3.5-flash`
    via the shared OpenRouter client (FIX_PLAN §25.1, §25.5). The council
    multi-vendor heterogeneity defense does NOT extend here — agentic LLM
    dispatch is single-model and single-vendor by contract.

    `boolean` is used by `binary_bayesian_surprise` (Phase A default).
    `feasibility_bucket` is used by `graded_bayesian_surprise` (Phase B).
    Both are async so a single `asyncio.gather` can dispatch `n` parallel
    calls per side of the evidence.
    """

    async def boolean(self, prompt: str) -> bool: ...
    async def feasibility_bucket(self, prompt: str) -> FeasibilityBucket: ...


# --------------------------------------------------------------------------
# Configuration — FIX_PLAN §26.2 invariants enforced at construction
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class StrategyArchiveConfig:
    """Frozen configuration. Invariants enforced in `__post_init__`.

    Per FIX_PLAN §26.2 the canonical defaults are tuned for Phase A:
      - `surprise_mode = "binary"` — cheaper, 2n = 10 LLM calls per surprise.
      - `parallel_lineages_k = 1` — single lineage walked through the gate sequence.
      - No MAP-Elites cell-first selection at first; cells populate lazily
        from candidate metrics so the Phase B promotion is a config flip.

    Phase B promotes the relevant fields:
      - `surprise_mode = "graded"`
      - `parallel_lineages_k > 1`
      - `cross_run_transfer_k > 0` (Phase A leaves cross-run transfer off)
    """

    enabled: bool = True
    surprise_mode: Literal["graded", "binary"] = "binary"
    surprise_n_samples: int = 5
    reward_alpha: float = 0.7
    surprise_beta: float = 0.3
    feasibility_gamma: float = 1.0
    uct_exploration_constant: float = 1.414         # sqrt(2), classical UCT
    behavior_novelty_weight: float = 0.25
    map_elites_cell_bonus: float = 1.0
    parallel_lineages_k: int = 1
    ema_alpha: float = 0.5
    cross_run_transfer_k: int = 0                   # Phase A: 0 (off); Phase B: 8
    archive_index_top_k: int = 15
    archive_productivity_top_k: int = 5
    llm_max_concurrency: int = 6                    # caps per-process GuideLLM dispatch

    def __post_init__(self) -> None:
        """Enforce invariants. Raise SurpriseInvariantViolation on convex-combination breach."""
        # `reward_alpha + surprise_beta == 1.0` is the load-bearing invariant.
        # The composite UCT score in §5.4 is a convex combination over the
        # `[0, 1]`-normalized reward and surprise terms; breaking it makes
        # the composite uninterpretable.


# --------------------------------------------------------------------------
# Pure functions — Bayesian-surprise math (FIX_PLAN §26.2)
# --------------------------------------------------------------------------

def beta_kl(
    a_post: float,
    b_post: float,
    a_pre: float,
    b_pre: float,
) -> float:
    """`KL(Beta(a_post, b_post) || Beta(a_pre, b_pre))` in closed form.

    Closed form (Cover & Thomas §8.5):

        KL(p || q) = log B(a_pre, b_pre) - log B(a_post, b_post)
                   + (a_post - a_pre) * (psi(a_post) - psi(a_post + b_post))
                   + (b_post - b_pre) * (psi(b_post) - psi(a_post + b_post))

    where `B` is the beta function (use `scipy.special.betaln` to avoid
    overflow) and `psi` is the digamma (`scipy.special.digamma`).

    All four parameters MUST be strictly positive; non-positive shapes are
    outside the Beta support. The caller is responsible — degenerate inputs
    raise `DirichletDegenerateAlpha` (the binary path catches and re-raises
    under that same taxonomy entry for surface uniformity).
    """


def dirichlet_kl(
    alpha_post: tuple[float, ...],
    alpha_pre: tuple[float, ...],
) -> float:
    """`KL(Dirichlet(alpha_post) || Dirichlet(alpha_pre))`.

    Closed form via the multivariate beta function (logspace):

        KL(p || q) = log B(alpha_pre) - log B(alpha_post)
                   + sum_i (alpha_post_i - alpha_pre_i) *
                            (psi(alpha_post_i) - psi(sum_i alpha_post_i))

    with `log B(alpha) = sum_i log Gamma(alpha_i) - log Gamma(sum_i alpha_i)`.

    Implementation: `scipy.special.gammaln` for `log Gamma`, `scipy.special.digamma`
    for `psi`. Both vectors must have the same length; mismatch raises `ValueError`.

    Non-positive alpha components raise `DirichletDegenerateAlpha`. Callers
    construct alphas via `1 + counts` so all components are strictly positive
    by construction; any DirichletDegenerateAlpha here is an upstream bug.
    """


async def binary_bayesian_surprise(
    strategy_md: str,
    evidence: str,
    guide_llm: GuideLLM,
    n: int = 5,
) -> float:
    """Beta-Bernoulli surprise (Phase A default). 2n GuideLLM calls.

    Samples `n` yes/no answers before and after evidence is revealed,
    builds Beta-Bernoulli prior/posterior via conjugacy, applies the
    **0.5-mean polarity gate** (returns `0.0` if the belief mean did not
    cross the 0.5 decision threshold — sampling noise filter), and
    returns the closed-form `KL(posterior || prior)` if the gate opens.

    The 2n calls fire concurrently via `asyncio.gather`; for the default
    n=5 that is 10 parallel calls per surprise evaluation.

    Raises:
        BucketCountsEmpty: if either the pre- or post-evidence elicitation
            yielded zero usable boolean responses (every call refused or
            errored). The caller must inspect `runs/<cycle-id>/strategy/
            guide_llm.jsonl` and re-attempt after the upstream issue is fixed.
        GuideLLMRefusal: if `google/gemini-3.5-flash` returns a safety-filtered
            response even after one retry. **No silent model substitution.**
    """


async def graded_bayesian_surprise(
    strategy_md: str,
    evidence: str,
    guide_llm: GuideLLM,
    n: int = 5,
) -> float:
    """Dirichlet surprise (Phase B target). 2n GuideLLM calls.

    Samples `n` categorical answers (3 buckets: `lt_10`, `10_50`, `gt_50`)
    before and after evidence is revealed, builds Dirichlet prior/posterior
    via conjugacy (`Dirichlet(1 + counts)`), applies the **dominant-bucket
    polarity gate** (returns `0.0` unless both sample sets have a unique
    dominant bucket AND those buckets differ — filters tied modes and
    no-change cases as noise), and returns `dirichlet_kl(...)` if the gate
    opens.

    The 2n calls fire concurrently. Identical taxonomy / raises as the
    binary path.
    """


# --------------------------------------------------------------------------
# Archive class — stateful, owns the SQLite connection + GuideLLM handle
# --------------------------------------------------------------------------

class StrategyArchive:
    """BFTS + UCT + Bayesian-surprise + MAP-Elites archive.

    Stateful but thread-safe at the SQLite level (the connection is
    used in autocommit mode; concurrent writers serialize via SQLite's
    own locking). Async methods do not hold the SQLite connection across
    await points; each `await` block computes off-connection and commits
    in one synchronous transaction.
    """

    def __init__(
        self,
        config: StrategyArchiveConfig,
        conn: sqlite3.Connection,            # owned by the Ledger (spec 012)
        guide_llm: GuideLLM,
        *,
        experiment_id: int,                  # foreign key into `experiments`
        problem_id: str,                     # used for cross-run-transfer filters
    ) -> None:
        """The archive does not open `conn`; the Ledger does (spec 012).

        The archive does not call `conn.close()`. It does call `conn.commit()`
        after each public mutating method (additive only; no nested transactions).
        """

    # --- Attribution (read-write; called by spec 008 + spec 003 at terminals) ---

    async def attribute_surprise(
        self,
        strategy_sha: str,
        evidence: StrategyCycleEvidence,
    ) -> float:
        """Compute surprise for the given strategy + evidence, update `surprise_ema`,
        and return the surprise in bits.

        Dispatches to `binary_bayesian_surprise` or `graded_bayesian_surprise`
        per `config.surprise_mode`. EMA update is single-threaded under the
        SQLite connection's lock. The returned value is what gets written to
        the `EvidenceLedgerEntry.surprise_bits` column (per FIX_PLAN §26.2 +
        spec 012).
        """

    def attribute_reward(
        self,
        strategy_sha: str,
        evidence: StrategyCycleEvidence,
    ) -> float:
        """Compute the per-cycle reward signal for the strategy, update
        `reward_ema` and `feasibility_distance_ema`, and return the reward.

        Reward computation is profile-dependent: §5.6 documents the canonical
        feasible-yield-weighted shape. The method is synchronous because no
        LLM is involved (purely an SQL update over numeric evidence).
        """

    # --- Selection (read-only; called by spec 008 + spec 003 at cycle start) ---

    def select_lineages(self, k: int) -> list[str]:
        """Return K parent strategy SHAs for parallel BFTS branches.

        Phase A default `k=1` returns a single SHA (or `["novel:0"]` if the
        archive is empty). Phase B `k > 1` returns K distinct SHAs, with
        MAP-Elites cell-first selection (one elite per populated cell) and
        full-archive fallback when cells are exhausted.

        Under-sized archives are padded with `novel:<index>` tokens so the
        return list is ALWAYS exactly `k` elements. Empty result raises
        `LineageSelectionEmpty` — but the padding logic guarantees this
        never fires under normal operation; the raise is a tripwire for
        the padding-loop bug.

        See §5.4 for the full UCT scoring + novelty + MAP-Elites algorithm.
        """

    def top_k(self, k: int) -> tuple[Strategy, ...]:
        """Return the top-K productive strategies for C5 program-direction
        and operator inspection. Ranking key is `reward_ema` (descending);
        ties broken by `feasible_count` (descending), then `sha` (ascending,
        for determinism).
        """

    # --- Authoring (write; called by spec 008 after code-gen produces a new strategy) ---

    def add_strategy(
        self,
        summary_md: str,
        parents: tuple[str, ...],            # parent SHAs; empty for novel/library
        kind: StrategyKind,
    ) -> str:
        """Compute the content hash of the canonicalized `summary_md`, insert
        the strategy row (UPSERT — identical `summary_md` dedup automatically),
        write `strategy_edges` for every parent, and return the SHA.

        Inferred-kind discipline: when `kind == "mutate"` exactly one parent
        must be supplied; `crossover` requires ≥ 2; `novel` and `library`
        require zero. Violations raise `StrategyArchiveError` at the boundary.
        """

    # --- Cross-run prior transfer (Phase B; gated by config) ---

    def transfer_priors_from(
        self,
        source_experiment_id: int,
        k: int,
    ) -> None:
        """Import top-K strategies from another experiment (sibling problem).

        For each imported strategy:
          - Insert a new `strategies` row under THIS experiment_id with the
            same `summary_md` (so the SHA is identical — strategies are
            content-addressed).
          - Prefix `provenance` with `transferred_from_exp_<source_experiment_id>`.
          - Reset `visits`, `reward_ema`, `surprise_ema`,
            `feasibility_distance_ema`, `feasible_count`, `behavior_descriptor`
            to NULL / 0 — the importing experiment starts each transferred
            lineage with a clean slate.

        Phase A leaves `config.cross_run_transfer_k = 0` so this is a no-op
        unless explicitly enabled.
        """


# --------------------------------------------------------------------------
# Concrete GuideLLM implementation (FIX_PLAN §25.5)
# --------------------------------------------------------------------------

class GeminiFlashGuideLLM:
    """Concrete `GuideLLM` implementation backed by the shared LLM substrate.

    Imports `from factory.llm_client import OpenRouterClient` (spec 018) — the
    same `DecisionClient` Protocol the council library uses (FIX_PLAN §27.2).
    The only differences are the request shape:
      - model = "google/gemini-3.5-flash"
      - response_format = {"type": "json_object"} so the bool/bucket answer
        parses unambiguously.

    No `openai`-SDK / `base_url` / `OPENROUTER_API_KEY` surface in this module —
    the shared client owns all of that. No `temperature` / `top_p` / `top_k`
    override (FIX_PLAN §25.7).
    """

    async def boolean(self, prompt: str) -> bool: ...
    async def feasibility_bucket(self, prompt: str) -> FeasibilityBucket: ...
```

## 4. Data Structures / Schemas

The artifacts the archive *consumes* (`Strategy`, `StrategyCycleEvidence`, `BehaviorDescriptor`, `ConstraintOvershootStats`) and the new `surprise_bits: float | None` field on `EvidenceLedgerEntry` are defined in spec 002 per FIX_PLAN §26.4. The archive does not redefine them; this section documents the **archive-local types** and the **SQLite schema** the archive owns through the Ledger (spec 012).

### 4.1 Module-local typed aliases

```python
FeasibilityBucket = Literal["lt_10", "10_50", "gt_50"]
"""Three-bucket feasible-candidate fraction. Matches the proxima harness contract."""

# Internal bucket-counts tuple: (lt_10, 10_50, gt_50). Module-private; not part of any artifact.
_BucketCounts = tuple[int, int, int]
```

`StrategyKind` (spec 002) is the four-value enum `novel | mutate | crossover | library`. The string-literal form is used at SQLite boundaries (SQLite has no native enum); Pydantic on the artifact boundary upcasts to the typed enum.

### 4.2 SQLite tables — `strategies`, `strategy_edges`, `strategy_subtree`

The schema matches the proxima harness `world_model_schema.py` lines 95–168. Owned by the Ledger (spec 012) — this module receives an open `sqlite3.Connection` and never opens or closes it. Schema migration is the Ledger's concern.

```sql
-- Archive: one row per strategy. Content-addressed via `sha`.
CREATE TABLE IF NOT EXISTS strategies (
    sha                         TEXT PRIMARY KEY,           -- SHA-256 of canonicalized summary_md
    experiment_id               INTEGER NOT NULL REFERENCES experiments(id),
    summary                     TEXT NOT NULL,              -- one-line summary
    summary_md                  TEXT NOT NULL,              -- full strategy description (markdown)
    kind                        TEXT NOT NULL,              -- 'novel' | 'mutate' | 'crossover' | 'library'
    provenance                  TEXT NOT NULL,              -- 'agent_authored' | 'hand_authored' | 'transferred_from_exp_<id>'

    -- EMAs: NULL until first observation. NEVER zero-on-cold-start
    -- (would corrupt the min/max normalization in §5.4).
    reward_ema                  REAL,
    surprise_ema                REAL,
    feasibility_distance_ema    REAL,

    -- Cumulative counters.
    feasible_count              INTEGER NOT NULL DEFAULT 0,
    visits                      INTEGER NOT NULL DEFAULT 0,

    -- MAP-Elites diversity. Lazy: populated from candidate metrics on first
    -- evaluation. Stored as canonical JSON so the schema is profile-agnostic.
    behavior_descriptor_json    TEXT,                       -- BehaviorDescriptor serialized

    -- Constraint pressure (per-constraint positive overshoot stats).
    -- Serialized as `{constraint_name: ConstraintOvershootStats}` JSON.
    constraint_overshoot_json   TEXT,

    -- Distillation columns (Phase B; spec 016 §9). Phase A writes only `summary_md`
    -- and leaves the version columns at their schema defaults.
    summary_evidence_version    INTEGER NOT NULL DEFAULT 0,
    summary_at_version          INTEGER NOT NULL DEFAULT 0
);

-- DAG edges. Multiple parent rows per child = crossover.
-- Empty parents (no rows) = novel / library / transferred.
CREATE TABLE IF NOT EXISTS strategy_edges (
    parent_sha  TEXT NOT NULL REFERENCES strategies(sha),
    child_sha   TEXT NOT NULL REFERENCES strategies(sha),
    PRIMARY KEY (parent_sha, child_sha)
);

-- Recursive view: every (root, descendant, depth) pair. Depth-capped at 6
-- to prevent runaway expansion in pathological DAGs. The depth cap is a
-- spec 012 (Ledger) concern; spec 016 reads the view but never writes it.
CREATE VIEW IF NOT EXISTS strategy_subtree AS
WITH RECURSIVE descent(root, sha, depth) AS (
    SELECT sha, sha, 0 FROM strategies
    UNION ALL
    SELECT d.root, e.child_sha, d.depth + 1
      FROM descent d JOIN strategy_edges e ON e.parent_sha = d.sha
     WHERE d.depth < 6
)
SELECT * FROM descent;
```

**Index discipline.** Spec 012 owns these but spec 016 *requires* them for the hot reads in §5.4:

- `CREATE INDEX strategies_experiment_id_idx ON strategies(experiment_id);` — `_load_candidates` filters by experiment.
- `CREATE INDEX strategy_edges_parent_sha_idx ON strategy_edges(parent_sha);` — child-count subquery in §5.4 step 4.

### 4.3 The `BehaviorDescriptor` artifact (defined in spec 002)

Per FIX_PLAN §26.2 + §26.4 the artifact is defined in spec 002. The archive consumes it through `Strategy.behavior_descriptor`. The descriptor schema is **per-problem** (FIX_PLAN §26.7 open question) — for the canonical stellarator profile it carries `nfp`, `aspect_band`, `triangularity_sign`, `iota_band`, `elongation_band`; for other profiles the fields differ. The archive treats it as an opaque typed model and only requires that two methods exist:

- `descriptor.to_cell_key() -> tuple[Hashable, ...]` — the MAP-Elites cell key for elite bookkeeping.
- `descriptor.to_vector() -> tuple[float, ...]` — a fixed-length numeric vector for the cosine-distance novelty bonus.

Both are defined on the artifact in spec 002. The archive never reaches into the descriptor's fields directly; profile-specific banding stays in the adapter (spec 006).

### 4.4 The `StrategyCycleEvidence` artifact (defined in spec 002)

The artifact carries one cycle's evidence for one strategy:

```python
# Spec 002 — for reference (defined there, not here).
class StrategyCycleEvidence(_ArtifactBase):
    strategy_sha: str
    cycle_id: CycleId
    best_objective: float | None
    best_feasibility_distance: float | None
    feasible_count: int
    constraint_overshoots: dict[str, ConstraintOvershootStats]
```

`ConstraintOvershootStats` carries `n_violating: int`, `mean_overshoot: float`, `min_overshoot: float`. Both are immutable Pydantic models per spec 002 §3.

### 4.5 GuideLLM trace JSONL (`runs/<cycle-id>/strategy/guide_llm.jsonl`)

Per-call traces of every `boolean` / `feasibility_bucket` invocation. Line format:

```json
{"ts": "...", "event": "guide_llm_call", "kind": "boolean", "prompt": "...", "response": true, "tokens": {"prompt": 230, "completion": 4}, "cost_usd": 0.0000045, "model_id_actual": "google/gemini-3.5-flash"}
{"ts": "...", "event": "guide_llm_refusal", "kind": "feasibility_bucket", "prompt": "...", "raw_response": "I can't speculate...", "retry_n": 1}
```

The trace lets the operator diagnose `GuideLLMRefusal` / `BucketCountsEmpty` after the fact.

## 5. Algorithms / Logic

### 5.1 Beta-Bernoulli surprise — binary mode (Phase A default)

Conjugate-prior workflow over a single yes/no GuideLLM elicitation, gated by the 0.5-mean polarity check.

```text
def binary_bayesian_surprise(strategy_md, evidence, guide_llm, n=5):
    prior_q = render_prior_template(strategy_md)
    post_q  = render_post_template(strategy_md, evidence)

    # n×2 LLM calls fire concurrently via asyncio.gather of two gathers.
    pre_results, post_results = await asyncio.gather(
        asyncio.gather(*(guide_llm.boolean(prior_q) for _ in range(n))),
        asyncio.gather(*(guide_llm.boolean(post_q)  for _ in range(n))),
    )
    if not pre_results or not post_results:
        raise BucketCountsEmpty(...)

    k_pre  = sum(pre_results)
    k_post = sum(post_results)

    # Beta-Bernoulli with uniform prior Beta(1, 1):
    #   - Prior elicitation contributes (k_pre, n - k_pre).
    #   - Post-evidence elicitation contributes (k_post, n - k_post)
    #     IN ADDITION to the prior counts (cumulative).
    a_pre,  b_pre  = 1 + k_pre,            1 + (n - k_pre)
    a_post         = 1 + k_pre + k_post
    b_post         = 1 + (n - k_pre) + (n - k_post)

    # POLARITY GATE — same side of 0.5 OR exactly equal → noise.
    pre_mean  = a_pre  / (a_pre  + b_pre)
    post_mean = a_post / (a_post + b_post)
    if (pre_mean - 0.5) * (post_mean - 0.5) > 0 or pre_mean == post_mean:
        return 0.0

    return beta_kl(a_post, b_post, a_pre, b_pre)
```

**Why the gate.** Without it, two elicitations that both said "this looks promising" — but with slightly different sample variance — would register a numerically nonzero KL purely from sampling noise. The 0.5-mean crossing requirement forces a *directional* belief shift before the surprise counts.

### 5.2 Dirichlet surprise — graded mode (Phase B target)

Same workflow over the 3-bucket categorical elicitation. The polarity gate fires unless **both** sample sets have a unique dominant bucket AND those buckets differ.

```text
def graded_bayesian_surprise(strategy_md, evidence, guide_llm, n=5):
    prior_q = render_graded_prior_template(strategy_md)
    post_q  = render_graded_post_template(strategy_md, evidence)

    pre_results, post_results = await asyncio.gather(
        asyncio.gather(*(guide_llm.feasibility_bucket(prior_q) for _ in range(n))),
        asyncio.gather(*(guide_llm.feasibility_bucket(post_q)  for _ in range(n))),
    )
    if not pre_results or not post_results:
        raise BucketCountsEmpty(...)

    pre_counts  = _bucket_counts(pre_results)    # (n_lt10, n_1050, n_gt50)
    post_counts = _bucket_counts(post_results)

    pre_dom  = _dominant_bucket(pre_counts)      # None if tie
    post_dom = _dominant_bucket(post_counts)

    # POLARITY GATE — tied modes or unchanged dominant bucket → noise.
    if pre_dom is None or post_dom is None or pre_dom == post_dom:
        return 0.0

    alpha_pre  = tuple(float(1 + c) for c in pre_counts)
    alpha_post = tuple(float(1 + cp + co) for cp, co in zip(pre_counts, post_counts))
    return dirichlet_kl(alpha_post, alpha_pre)
```

**Why graded over binary.** The graded mode discriminates *how much* belief moved, not just *whether* the decision boundary was crossed. A strategy that shifted from "almost surely 10-50% feasible" to "almost surely >50% feasible" carries more surprise than one that shifted from "maybe lt_10, maybe 10_50" to "maybe 10_50, maybe gt_50" — same number of buckets crossed, but different concentration. Dirichlet's per-component digamma terms capture this; Beta's two-parameter form cannot.

### 5.3 EMA updates — `attribute_surprise` and `attribute_reward`

EMAs use the canonical update rule with **NULL-on-cold-start** semantics: the first observation populates the EMA at the observed value directly (no synthetic prior).

```text
def _update_ema(old_ema: float | None, observed: float, alpha: float) -> float:
    if old_ema is None:
        return observed                              # cold-start: first observation IS the EMA
    return alpha * observed + (1.0 - alpha) * old_ema
```

For `attribute_surprise(strategy_sha, evidence)`:

1. Dispatch to `binary_bayesian_surprise` or `graded_bayesian_surprise` per `config.surprise_mode`.
2. Read current `surprise_ema` from `strategies.sha = ?`.
3. Compute `surprise_ema_new = _update_ema(surprise_ema, observed_surprise, config.ema_alpha)`.
4. UPDATE `strategies SET surprise_ema = ?, visits = visits + 1 WHERE sha = ?`.
5. INSERT a `factory.strategy.attribute` event into `runs/<cycle-id>/cycle.jsonl`.
6. Return `observed_surprise` (the *cycle's* surprise, not the EMA — the EMA is internal state).

For `attribute_reward(strategy_sha, evidence)`:

1. Compute the per-cycle reward `r` from `StrategyCycleEvidence` (see §5.6 for the canonical shape).
2. Read current `reward_ema` and `feasibility_distance_ema`.
3. Update both EMAs via `_update_ema`. The distance EMA uses the *minimum* feasibility distance over the cycle's candidates (already aggregated in `evidence.best_feasibility_distance`).
4. UPDATE `strategies SET reward_ema = ?, feasibility_distance_ema = ?, feasible_count = feasible_count + ? WHERE sha = ?`.
5. INSERT the event into `cycle.jsonl`.
6. Return `r`.

Both methods are idempotent only across SHA — multiple calls for the same `(strategy_sha, cycle_id)` will *double-count* into the EMA and the visit counter. The caller (spec 003 state machine) is responsible for at-most-once attribution; the archive itself does not deduplicate. This is a deliberate KISS choice — the alternative (a `(strategy_sha, cycle_id)` uniqueness index) would couple the archive to the cycle ID schema, which lives in spec 003.

### 5.4 UCT lineage selection — `select_lineages(k)`

The composite score is a convex combination over `[0, 1]`-normalized terms plus the classical UCT exploration term plus an optional MAP-Elites cell bonus plus a behavior-space novelty bonus. The shape and the `reward_alpha + surprise_beta == 1.0` invariant are locked by FIX_PLAN §26.2.

**Full algorithm:**

```text
def select_lineages(k):
    candidates = _load_candidates(experiment_id)  # one SQL query, see §4.2

    if not candidates:
        return [f"novel:{i}" for i in range(k)]

    # 1. Compute min/max for each term, used for min-max normalization.
    rewards   = [c.reward_ema   for c in candidates if c.reward_ema   is not None]
    surprises = [c.surprise_ema for c in candidates if c.surprise_ema is not None]
    distances = [c.feasibility_distance_ema for c in candidates
                 if c.feasibility_distance_ema is not None]
    reward_lo,   reward_hi   = (min(rewards),   max(rewards))   if rewards   else (None, None)
    surprise_lo, surprise_hi = (min(surprises), max(surprises)) if surprises else (None, None)
    distance_lo, distance_hi = (min(distances), max(distances)) if distances else (None, None)
    total_visits = max(sum(c.visits for c in candidates), 1)
    max_feasible_count = max((c.feasible_count for c in candidates), default=0)

    # 2. Behavior-descriptor vectors and MAP-Elites cell keys.
    #    Both are lazy: None for candidates that haven't been evaluated yet.
    vectors_by_sha = {c.sha: _descriptor_vector(c.behavior_descriptor_json)
                      for c in candidates}
    cells_by_sha   = {c.sha: _descriptor_cell(c.behavior_descriptor_json)
                      for c in candidates}
    all_vectors    = tuple(v for v in vectors_by_sha.values() if v is not None)

    # 3. Compute base score per candidate.
    base_scores: dict[str, float] = {}
    for c in candidates:
        reward_norm   = _normalize(c.reward_ema,   reward_lo,   reward_hi,   cold_start=0.5)
        surprise_norm = _normalize(c.surprise_ema, surprise_lo, surprise_hi, cold_start=0.0)

        if max_feasible_count > 0:
            feasibility_pressure = c.feasible_count / max_feasible_count
        else:
            # Cold start — no feasible candidates yet in the archive.
            # Use the inverse normalized distance as a proxy (closer to feasible = higher pressure).
            distance_norm = _normalize(c.feasibility_distance_ema, distance_lo, distance_hi,
                                       cold_start=1.0)
            feasibility_pressure = 1.0 - distance_norm

        exploration = config.uct_exploration_constant * sqrt(log(total_visits) / (c.visits + 1))

        uct_score = (config.reward_alpha    * reward_norm
                   + config.surprise_beta   * surprise_norm
                   + config.feasibility_gamma * feasibility_pressure
                   + exploration)

        novelty_bonus = config.behavior_novelty_weight * _novelty(
            vectors_by_sha[c.sha], all_vectors
        )

        # Child-count penalty: prefer leaves over heavily-expanded nodes.
        child_penalty = 1.0 / (1.0 + c.children_count)

        base_scores[c.sha] = (uct_score + novelty_bonus) * child_penalty

    # 4. K-greedy selection with MAP-Elites cell-first sweep.
    remaining = {c.sha for c in candidates}
    selected: list[str] = []
    selected_vectors: list[tuple[float, ...]] = []
    elite_shas = _cell_elites(candidates, cells_by_sha)  # one elite per populated cell

    while remaining and len(selected) < k:
        # Prefer elites first; fall back to remaining archive when cells exhausted.
        eligible = remaining & elite_shas if (remaining & elite_shas) else remaining

        scored = []
        for sha in eligible:
            # Diversification bonus: penalize SHAs whose vector is close to already-selected ones.
            selected_bonus = 0.0
            vector = vectors_by_sha[sha]
            if vector is not None and selected_vectors:
                avg_dist = (sum(_cosine_distance(vector, chosen) for chosen in selected_vectors)
                            / len(selected_vectors))
                selected_bonus = config.behavior_novelty_weight * avg_dist
            map_elites_bonus = (config.map_elites_cell_bonus if sha in elite_shas else 0.0)
            scored.append((base_scores[sha] + selected_bonus + map_elites_bonus, sha))

        # Tie-break by SHA (lexicographic) for determinism.
        _score, chosen_sha = min(scored, key=lambda item: (-item[0], item[1]))
        selected.append(chosen_sha)
        remaining.remove(chosen_sha)
        if cells_by_sha[chosen_sha] is not None:
            elite_shas = {s for s in elite_shas
                          if cells_by_sha[s] != cells_by_sha[chosen_sha]}
        if vectors_by_sha[chosen_sha] is not None:
            selected_vectors.append(vectors_by_sha[chosen_sha])

    # 5. Pad to exactly k with novel-token fillers.
    while len(selected) < k:
        selected.append(f"novel:{len(selected)}")

    if len(selected) < k:
        raise LineageSelectionEmpty(f"padding loop failed to fill k={k}")

    return selected
```

**Why cold-start `reward_norm=0.5` but `surprise_norm=0.0`.** A strategy with no observation yet should be neither favored nor punished on the reward axis — `0.5` is the neutral midpoint. Surprise is *new information*; absent any elicitation, the prior on novelty is zero, so the cold-start default biases the agent toward exploration via the UCT term rather than via an inflated surprise prior.

**Why `_normalize` returns `cold_start` when `lo == hi`.** Identical values across the archive (e.g., all rewards exactly equal) make `(value - lo) / (hi - lo)` undefined. Cold-start fallback preserves the normalization contract.

### 5.5 MAP-Elites cell bookkeeping

A *cell* is a discretized region of behavior space, keyed by `BehaviorDescriptor.to_cell_key()`. For the canonical stellarator profile that's `(nfp, aspect_band, triangularity_sign, iota_band, elongation_band)`; for other profiles the tuple shape changes (the archive is profile-agnostic).

**Elite selection per cell** (one row per cell):

```text
def _cell_elites(candidates, cells_by_sha):
    elites: dict[CellKey, _StrategyCandidate] = {}
    for c in candidates:
        cell = cells_by_sha[c.sha]
        if cell is None:                 # behavior descriptor not yet populated
            continue
        current = elites.get(cell)
        if current is None or _elite_key(c) > _elite_key(current):
            elites[cell] = c
    return {c.sha for c in elites.values()}

def _elite_key(c):
    # Lexicographic key: feasible_count first (more feasibles = better),
    # then -distance (closer to feasible = better), then reward, then SHA for stability.
    distance_score = (-c.feasibility_distance_ema
                      if c.feasibility_distance_ema is not None else -inf)
    reward = c.reward_ema if c.reward_ema is not None else -inf
    return (c.feasible_count, distance_score, reward, c.sha)
```

**Phase A note.** With `parallel_lineages_k = 1` the cell-first sweep simply picks the single best-elite-or-archive candidate, then pads with `novel:0` if the archive is empty. The Phase B promotion to `parallel_lineages_k > 1` activates the actual cell-diversification logic.

### 5.6 Per-cycle reward — canonical shape

The reward signal converts `StrategyCycleEvidence` into a scalar. The canonical shape (matching the proxima harness) is:

```text
def _compute_reward(evidence: StrategyCycleEvidence) -> float:
    # Feasible candidates are the load-bearing signal.
    if evidence.feasible_count > 0:
        # Once feasible, reward is the (negated, normalized) objective —
        # higher reward for smaller objective. The archive does not need
        # the objective bounds; the min-max normalization in §5.4 step 1
        # absorbs scale differences across strategies.
        if evidence.best_objective is not None:
            return -float(evidence.best_objective)
        return 0.0

    # Not yet feasible: reward is the (negated) distance-to-feasible.
    # Closer to feasible = higher reward.
    if evidence.best_feasibility_distance is not None:
        return -float(evidence.best_feasibility_distance)
    return -1.0     # no observation at all — reward is a low constant
```

The shape is profile-agnostic. Per-problem variants (e.g., multi-objective Pareto signaling) live in the spec 006 adapter, which returns the per-cycle reward as part of evidence assembly; this function is the *fallback* default.

### 5.7 Cross-run prior transfer

`transfer_priors_from(source_experiment_id, k)` is the Phase B mechanism for letting a new experiment inherit the top-K strategies from a sibling problem (typically run on a different but related simulator family).

```text
def transfer_priors_from(source_experiment_id, k):
    rows = conn.execute("""
        SELECT sha, summary_md, kind, summary
          FROM strategies
         WHERE experiment_id = ?
           AND reward_ema IS NOT NULL
         ORDER BY reward_ema DESC, feasible_count DESC, sha ASC
         LIMIT ?
    """, (source_experiment_id, k)).fetchall()

    for r in rows:
        # IMPORTANT: do NOT copy reward_ema / surprise_ema / visits.
        # The importing experiment starts each transferred lineage with a clean slate.
        conn.execute("""
            INSERT OR IGNORE INTO strategies (
                sha, experiment_id, summary, summary_md, kind, provenance,
                reward_ema, surprise_ema, feasibility_distance_ema,
                feasible_count, visits, behavior_descriptor_json,
                constraint_overshoot_json
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 0, 0, NULL, NULL)
        """, (r["sha"], experiment_id, r["summary"], r["summary_md"],
              r["kind"], f"transferred_from_exp_{source_experiment_id}"))
    conn.commit()
```

The `INSERT OR IGNORE` is intentional: SHAs are content-addressed, so if the importing experiment already has the same `summary_md` (e.g., from a previous transfer), the new row is dropped silently — no double-bookkeeping. Edges are NOT transferred (a transferred strategy is treated as a `library`-style fresh root in the importing tree); this prevents accidental cross-experiment lineage contamination.

### 5.8 Tie-breaking and determinism

Every multi-candidate selection step breaks ties by **lexicographic SHA** (ascending). This makes the archive's behavior **bit-reproducible** across runs given the same seed and the same evidence sequence — critical for the spec 002 provenance-hash contract (replaying a run with the same inputs must produce the same artifacts).

**Sources of non-determinism the archive controls for:**

- Python `set` iteration order (use `sorted(...)` everywhere a set is iterated for output).
- `dict.items()` order (preserve insertion order; do not assume hash order).
- `asyncio.gather` completion order (do not depend on the order; only sum / count the results).

**Sources the archive does NOT control:**

- GuideLLM response variability across runs — this is *expected* sampling, not a bug; the polarity gates absorb the noise.
- SQLite floating-point arithmetic — the schema stores `REAL` (IEEE 754 double); the EMA update uses native Python float, which is also IEEE 754. Determinism here is best-effort.

## 6. Failure Modes

| Error class | When it fires | Recovery action |
| :--- | :--- | :--- |
| `SurpriseInvariantViolation(StrategyArchiveError)` | `StrategyArchiveConfig.__post_init__` detected `reward_alpha + surprise_beta != 1.0` (within `math.isclose` tolerance). Also fires if any of `reward_alpha`, `surprise_beta`, `feasibility_gamma`, `behavior_novelty_weight`, `map_elites_cell_bonus`, `ema_alpha` is outside its documented range. | **Hard fail at config construction.** Operator fixes the config (do not silently renormalize — the composite-score interpretability is load-bearing). |
| `DirichletDegenerateAlpha(StrategyArchiveError)` | `dirichlet_kl(...)` received a non-positive alpha component. The `1 + counts` prior should make all components strictly positive by construction; any breach indicates an upstream bug in the bucket-counts arithmetic. The binary path catches and re-raises through this same taxonomy entry for surface uniformity. | **Raise loud.** The caller's bucket-counts code has a bug; do not add a defensive guard around the math. |
| `BucketCountsEmpty(StrategyArchiveError)` | `binary_bayesian_surprise` or `graded_bayesian_surprise` observed zero responses on either the pre- or post-evidence side (every GuideLLM call refused or errored). | Inspect `runs/<cycle-id>/strategy/guide_llm.jsonl` for refusal traces. Re-attempt after the upstream issue is fixed; do not retry from inside the archive (the GuideLLM error path is a separate concern). |
| `BehaviorDescriptorMissing(StrategyArchiveError)` | `select_lineages(k)` was called with `enforce_behavior_descriptors=True` (Phase B) but no candidate has a populated `behavior_descriptor`. | Wait until at least one full evaluation cycle has elapsed (descriptors populate from candidate metrics on first eval), OR pass `enforce_behavior_descriptors=False` (Phase B-only; Phase A defaults to `False`). |
| `GuideLLMRefusal(StrategyArchiveError)` | `google/gemini-3.5-flash` returned a safety-filtered / refusal response on a belief-eliciting prompt, even after one retry. | Raise immediately. **No silent fallback to a different model.** Operator must investigate the prompt (often a malformed `strategy_md` triggers the filter) and re-run. |
| `UCTAllScoresZero(StrategyArchiveError)` | Every candidate scored exactly `0.0` on the UCT composite. Theoretically impossible given the strictly-positive exploration term `sqrt(log(total_visits) / (visits + 1))` for `total_visits >= 1`. | Indicates a corrupted SQLite row (likely a NULL `visits` where the schema disallows it, or a NaN in an EMA column). Inspect via `python -m factory.strategy top-k --raw` and patch through spec 012 Ledger. |
| `LineageSelectionEmpty(StrategyArchiveError)` | `select_lineages(k)` returned fewer than `k` SHAs even after the `novel:<index>` padding loop ran. | This is a programming bug (the padding loop should always fill to `k`). File a bug; do not retry. The raise is a tripwire that exists specifically to catch a loop-condition regression. |
| `StrategyArchiveError` (base) | Any catch-all path that should not silently degrade: invalid `kind`-vs-parents combination (e.g., `kind="crossover"` with one parent), unknown `surprise_mode`, etc. | Subclassed where possible; the base class is used only at the boundary. |

All errors inherit `FactoryError` per FIX_PLAN §6.3 + spec 002 §3 (so the state machine in spec 003 can `except FactoryError` at gate boundaries).

## 7. Testing

**Mock-mode** (CI, no network):

- `tests/test_strategy_archive_typical_usage.py` — **REQUIRED** per INDEX.md §7. Wires `MockGuideLLM` returning a canned `(prior_bucket, posterior_bucket) = ("lt_10", "10_50")` pattern, adds 3 strategies via `add_strategy`, marks one of them as evaluated by calling `attribute_surprise` + `attribute_reward` with a `StrategyCycleEvidence` fixture, then calls `select_lineages(1)` and verifies the returned SHA is the evaluated strategy. End-to-end smoke test for the archive contract.
- `tests/test_beta_kl.py` — unit tests for `beta_kl` with known closed-form cases (uniform → tight posterior, symmetric mirror pairs returning zero, asymmetric pairs returning expected positive values). Use `scipy.special.betaln` reference values.
- `tests/test_dirichlet_kl.py` — unit tests for `dirichlet_kl` with 3-component and 4-component fixtures (3-component for the canonical feasibility-bucket case; 4-component to verify length-agnostic behavior). Length-mismatch raises `ValueError`. Non-positive alpha raises `DirichletDegenerateAlpha`.
- `tests/test_binary_polarity_gate.py` — verify the 0.5-mean polarity gate: same-side priors return `0.0`; cross-0.5 priors return positive `beta_kl`; exactly-equal means return `0.0`. Use a deterministic `MockGuideLLM` that returns a known counts-pair.
- `tests/test_graded_polarity_gate.py` — verify the dominant-bucket polarity gate: tied modes return `0.0`; unchanged dominant bucket returns `0.0`; changed dominant bucket returns positive `dirichlet_kl`.
- `tests/test_uct_scoring_determinism.py` — same archive state with the same seed must produce identical `select_lineages` output across two invocations. Tie-breaking by SHA must be deterministic.
- `tests/test_uct_cold_start.py` — verify the cold-start defaults: empty archive returns `["novel:0", ..., "novel:k-1"]`; single-strategy archive returns that strategy's SHA + `novel:1`, ...; mixed-NULL EMAs use the documented defaults.
- `tests/test_map_elites_cell_placement.py` — verify `_cell_elites` picks one elite per populated cell with the `(feasible_count, -distance, reward, sha)` key. Phase B test only; Phase A leaves cells lazy.
- `tests/test_ema_cold_start.py` — first observation on a fresh strategy sets `reward_ema = observed_reward` (not `alpha * observed + (1-alpha) * 0`). Subsequent observations apply the standard EMA update.
- `tests/test_ema_idempotence_not_enforced.py` — explicitly verify that two `attribute_surprise(sha, evidence)` calls for the same `(sha, cycle_id)` **double-count** into the EMA. The archive does not deduplicate by design; this test is the regression guard for §5.3's KISS decision.
- `tests/test_add_strategy_kind_invariants.py` — `mutate` requires exactly one parent; `crossover` requires ≥ 2; `novel` and `library` require zero. Violations raise `StrategyArchiveError`.
- `tests/test_transfer_priors_resets_state.py` — verify imported strategies land with NULL EMAs / 0 visits / `provenance LIKE 'transferred_from_exp_%'`. Verify edges are NOT transferred.
- `tests/test_guide_llm_refusal.py` — `MockGuideLLM` configured to raise refusal; archive raises `GuideLLMRefusal` after one retry.
- `tests/test_sqlite_persistence_roundtrip.py` — write a strategy + evidence + EMA update, close the connection, re-open, verify the row is intact.

**Live-mode** (`@pytest.mark.live`, gated):

- `test_live_guide_llm_smoke.py` — single `binary_bayesian_surprise` call against the real `google/gemini-3.5-flash` endpoint via OpenRouter. Verifies the response parses, the 10 calls complete within the cost cap (FIX_PLAN §25.8: ≤ $0.005 / call × 10 = ≤ $0.05 / surprise).
- `test_live_full_cycle_attribution.py` — gated; attaches the real GuideLLM to an end-to-end cycle and verifies `surprise_bits` lands on the `EvidenceLedgerEntry` (spec 012 wiring).

**Property-based tests** (Hypothesis):

- `dirichlet_kl(alpha, alpha) == 0.0` for any positive alpha vector.
- `beta_kl(a, b, a, b) == 0.0` for any positive (a, b).
- `dirichlet_kl(alpha_post, alpha_pre) >= 0.0` for all positive alphas (KL is non-negative).

**Manual verification step** (one-time, documented in runbook):

- Inspect at least one `runs/<cycle-id>/strategy/guide_llm.jsonl` trace by hand to confirm `google/gemini-3.5-flash` is the resolved model (per OpenRouter's `model_id_actual` field).

## 8. Performance & Budget

**Per-cycle cost** (Phase A `surprise_mode = "binary"`):

| Component | Cost | Notes |
| :--- | :--- | :--- |
| `attribute_surprise` (one call) | `2n = 10` GuideLLM calls × ≤ $0.005 ≈ **≤ $0.05** | FIX_PLAN §25.8 per-call ceiling × 10 parallel calls. |
| `attribute_reward` | $0.00 | Purely SQL; no LLM involved. |
| `select_lineages(k)` | $0.00 | In-memory + one SQL query. |
| `add_strategy` | $0.00 | One INSERT (idempotent on SHA). |
| `transfer_priors_from(k=8)` | $0.00 | SQL-only; Phase A leaves `cross_run_transfer_k=0`. |

**Per-cycle compute** (in-memory):

- `_load_candidates`: one SQL query, `O(n_strategies)` rows. Indexed on `experiment_id` — sub-millisecond for `n_strategies < 10⁴`.
- UCT scoring: `O(n_strategies)` arithmetic; vector cosine for novelty is `O(n_strategies × n_dimensions)` where `n_dimensions` is `len(BehaviorDescriptor.to_vector()) ~ 5` for the canonical stellarator profile. Sub-millisecond for `n_strategies < 10³`.
- K-greedy selection loop: `O(k × n_strategies)` because each iteration re-scores the remaining set. With Phase A `k=1` this is `O(n_strategies)`; with Phase B `k=4` this is `O(4 × n_strategies)` — still trivial for archive sizes < 10⁴.
- EMA update: `O(1)` per call.

**Bayesian surprise wall clock**:

- Both modes dispatch `2n` GuideLLM calls in **parallel** via two nested `asyncio.gather`s. With `n=5` and Gemini Flash latency around 1–2 s, surprise evaluation completes in ~2 s of wall clock per attribution call. Single-threaded total cycle latency added by surprise = `n_strategies_evaluated_per_cycle × 2 s` (typically 1 per cycle in Phase A).

**Memory footprint**:

- The archive does not hold strategy state in memory across calls; every public method reads from `conn`, computes, writes back, and returns. The only Python-side cache is the `_load_candidates` result list within a single `select_lineages` invocation — `O(n_strategies)` for the lifetime of that call.

**Cost cap** is not enforced by the archive itself; it relies on the BudgetTracker (spec 013) wrapping the GuideLLM client. Per FIX_PLAN §25.6 the cost is forwarded to `BudgetTracker.record(cost_usd=...)` per call; the tracker raises if the budget is exhausted.

**Full-cycle ledger position** (FIX_PLAN §25.8): the archive's per-cycle cost ceiling (≤ $0.05 binary, ≤ $0.05 graded — same `2n` calls) is < 1% of the per-cycle target ceiling of $5.00, so the archive is *not* a budget-significant component. The cost discipline matters more in spec 008 (Generator-Verifier code-gen) where iteration count is high.

## 9. Open Questions

- **Phase A → Phase B promotion criteria for surprise mode.** Phase A defaults to binary surprise because it is cheaper and the polarity gate is cleaner (0.5 is a hard decision boundary). When the archive's binary-surprise EMAs start clustering near zero across all strategies (a signal that the binary signal has saturated), is that the trigger to promote to graded? Or is graded promotion better tied to the `parallel_lineages_k > 1` flip (so the multi-lineage diversification has finer-grained surprise signals to work with)? Decision deferred to the first post-Phase-A operator review.

- **Phase A → Phase B promotion criteria for `parallel_lineages_k`.** With `k = 1` the archive walks a single lineage through the gate sequence — no MAP-Elites diversification is in play. When the archive has > N populated cells (suggested: `N = 5`), should `k` auto-promote to `min(k_target, n_populated_cells)`? Or should the operator make this an explicit config flip? The proxima harness left it as a config flip (operator-controlled); we may want the auto-promote behavior in the factory, but it needs an explicit "stop multiplying lineages" backstop to avoid runaway parallelism.

- **`BehaviorDescriptor` schema portability across simulators.** The canonical stellarator profile uses `(nfp, aspect_band, triangularity_sign, iota_band, elongation_band)`. For other problems — e.g., catalyst design, materials screening — these fields are wrong. The spec defines the descriptor as profile-agnostic at the archive level (the archive only calls `.to_cell_key()` and `.to_vector()`), but the per-simulator adapter (spec 006) has to produce a descriptor that's *meaningful* in that problem's behavior space. Open: do we want a per-problem `BehaviorDescriptor` subclass registry, or a single descriptor with a `kind: SimulatorId` tag and a `payload: dict[str, str | int | float]`? The proxima harness uses the latter; the factory's typed-artifact discipline (spec 002 §1) wants the former. Decision deferred.

- **Distillation (`distill.py` in the proxima harness) — composition with the council.** The proxima harness has an off-path strategy-distillation step that summarizes patterns across many strategies into a higher-level `summary_md`. In the factory this lands in Phase B, but the open question is *who* writes the distilled summary — the GuideLLM (single agentic model) or the council (multi-vendor)? The distillation is *prose-generative*, which favors the GuideLLM. But it influences strategy authoring downstream, which is closer to a *judgment*, which favors the council. The likely answer is a hybrid: GuideLLM drafts, a single council deliberation gates. Deferred.

- **GuideLLM model substitution policy.** FIX_PLAN §25.5 pins `google/gemini-3.5-flash` for non-council agentic calls. If OpenRouter retires that model ID, the GuideLLM stops working — and unlike the council where vendor heterogeneity is a defense, here it's a single point of failure. Open: do we want a *named-tier* abstraction (e.g., "agentic_fast_tier" → resolved via `config/pricing/openrouter.yaml`), or do we keep the hard-coded model ID? The hard-coded ID is simpler and matches FIX_PLAN §25.5 verbatim; the named-tier is more future-proof. Deferred.

- **Cross-experiment lineage contamination via `transfer_priors_from`.** Currently the transfer copies `summary_md` (so the SHA is identical across experiments) but resets EMAs and drops edges. If two experiments transfer each other's top-K back and forth, the result could be a slow homogenization of the strategy pool — every experiment ends up with the same N strategies. This is probably fine (cross-pollination is the *point*) but should be measured. Open: add a `--anti-homogenization` flag that requires a transferred strategy to be at least one mutation-step removed from any local strategy? Deferred to first multi-experiment session.

- **Surrogate-based fallback surprise (Phase B).** FIX_PLAN §26.4 mentions that after a surrogate is retrained, its posterior variance could supply a fallback surprise signal when GuideLLM is unavailable. This is *cheap* (one surrogate query per attribution) and *vendor-independent*, which is attractive. But the surrogate's posterior variance and the GuideLLM's Bayesian-surprise KL are not in the same units — one is in "predictive uncertainty" units, the other is in bits. The conversion is non-trivial. Deferred to the surrogate-spec discussion (spec 010 §9).

- **`UCTAllScoresZero` real-world likelihood.** The error is a tripwire for a corrupted DB state; in healthy operation it should never fire. But the proxima harness has reportedly hit it once (in a misconfigured run where a manual SQL UPDATE zeroed out `visits` across the table). Worth a runbook entry. Deferred.

## 10. TODO Checklist

- [ ] Scaffold `factory/strategy/` from the canonical module template with submodules `beliefs.py`, `archive.py`, `selection.py`, `evidence.py`, `api.py`, plus `distill.py` placeholder (Phase B).
- [ ] Implement `factory/strategy/beliefs.py` — `beta_kl` and `dirichlet_kl` closed-form functions using `scipy.special.{betaln, gammaln, digamma}`; `binary_bayesian_surprise` and `graded_bayesian_surprise` async helpers with the polarity gates exactly per §5.1 / §5.2; `_bucket_counts` and `_dominant_bucket` module-private helpers.
- [ ] Implement `factory/strategy/strategy_config.py` — `StrategyArchiveConfig` frozen dataclass with all fields from FIX_PLAN §26.2 plus the additional fields from the proxima harness (`archive_index_top_k`, `archive_productivity_top_k`, `llm_max_concurrency`); `__post_init__` enforces the `reward_alpha + surprise_beta == 1.0` invariant and all range checks (raises `SurpriseInvariantViolation`).
- [ ] Implement `factory/strategy/archive.py` — `StrategyArchive` class with `attribute_surprise`, `attribute_reward`, `select_lineages`, `top_k`, `add_strategy`, `transfer_priors_from` methods. The archive does NOT open or close the SQLite connection; it receives one from the Ledger (spec 012).
- [ ] Implement `factory/strategy/selection.py` — `select_lineages_for_parallel` algorithm (§5.4) plus `_load_candidates`, `_normalize`, `_descriptor_vector`, `_descriptor_cell`, `_cosine_distance`, `_novelty`, `_cell_elites`, `_elite_key` helpers.
- [ ] Implement `factory/strategy/evidence.py` — `collect_cycle_strategy_evidence` (aggregates candidate metrics per strategy across one cycle, returns `tuple[StrategyCycleEvidence, ...]`); `positive_constraint_overshoots`; `merge_constraint_overshoot_json`.
- [ ] Define `GuideLLM` Protocol in `factory/strategy/api.py` and the concrete `GeminiFlashGuideLLM` implementation backed by `from factory.llm_client import OpenRouterClient` (spec 018) — the shared LLM substrate; FIX_PLAN §27.2.
- [ ] Add typed artifacts `Strategy`, `StrategyCycleEvidence`, `BehaviorDescriptor`, `ConstraintOvershootStats` to spec 002 (per FIX_PLAN §26.4). The archive imports them; it does NOT define them.
- [ ] Add `surprise_bits: float | None` column to `EvidenceLedgerEntry` (spec 002 + spec 012 schema migration).
- [ ] Implement `factory/strategy/cli.py` with `add`, `select`, `attribute-surprise`, `attribute-reward`, `top-k`, `transfer-priors` subcommands reachable as `python -m factory.strategy <subcommand>`. The `--mock-mode` flag wires `MockGuideLLM` so CI can run all subcommands offline.
- [ ] Implement `MockGuideLLM` returning deterministic fixtures from `factory/strategy/fixtures/guide_llm/`. Fixtures: `prior_lt_10.json`, `prior_10_50.json`, `prior_gt_50.json`, `posterior_*` mirroring the prior set. Mock has a `next_response_queue` for tests that need to script specific response sequences.
- [ ] Author `factory/strategy/fixtures/strategies/sample.md` — a complete sample `summary_md` for the typical-usage test. ~10 lines of markdown describing a stellarator-design strategy.
- [ ] Author `factory/strategy/fixtures/evidence/mid_cycle.json` — a `StrategyCycleEvidence` fixture with `feasible_count=2`, `best_objective=-1.85`, one constraint overshoot entry.
- [ ] Write `test_strategy_archive_typical_usage.py` — REQUIRED per INDEX.md §7. Wires `MockGuideLLM`, adds 3 strategies, attributes evidence on one of them, selects 1 lineage, verifies the selected SHA is the evaluated one.
- [ ] Write the 14 mock-mode tests enumerated in §7 (`test_beta_kl.py`, `test_dirichlet_kl.py`, `test_binary_polarity_gate.py`, `test_graded_polarity_gate.py`, `test_uct_scoring_determinism.py`, `test_uct_cold_start.py`, `test_map_elites_cell_placement.py`, `test_ema_cold_start.py`, `test_ema_idempotence_not_enforced.py`, `test_add_strategy_kind_invariants.py`, `test_transfer_priors_resets_state.py`, `test_guide_llm_refusal.py`, `test_sqlite_persistence_roundtrip.py`).
- [ ] Write Hypothesis property tests for `dirichlet_kl(alpha, alpha) == 0`, `beta_kl(a, b, a, b) == 0`, `dirichlet_kl(...) >= 0` for arbitrary positive alpha vectors.
- [ ] Write `test_live_guide_llm_smoke.py` (gated, manual) — single `binary_bayesian_surprise` call against real `google/gemini-3.5-flash` via OpenRouter; verify cost ≤ $0.05 and the polarity gate behaves on real outputs.
- [ ] Implement `runs/<cycle-id>/strategy/guide_llm.jsonl` writer with the per-call traces shown in §4.5. JSONL append-only; one line per `boolean` / `feasibility_bucket` call (including refusals).
- [ ] Wire the archive into spec 003 state machine: C5 program-direction council reads `archive.top_k(config.archive_productivity_top_k)` to inform `DomainScope` changes; Generator-Verifier loop (spec 008) calls `archive.select_lineages(config.parallel_lineages_k)` at iteration start (Phase B only; Phase A skips with `parallel_lineages_k=1`).
- [ ] Wire the archive into spec 012 Ledger: add the new SQL columns to `EvidenceLedgerEntry` schema, the new `strategies` / `strategy_edges` / `strategy_subtree` tables, and the two required indexes (§4.2 "Index discipline").
- [ ] Author `docs/runbooks/strategy-archive.md` covering: how to bootstrap a fresh archive on a new experiment; how to inspect `surprise_ema` and `reward_ema` distributions for archive-health diagnosis; how to trigger `transfer_priors_from` from the CLI; how to interpret `runs/<cycle-id>/strategy/guide_llm.jsonl` traces; how to recover from `UCTAllScoresZero`.
- [ ] Verify `mypy --strict factory/strategy/` passes with no `Any` and no untyped `dict` at module boundaries.
- [ ] Verify `python -m factory.strategy attribute-surprise --strategy-fixture sample --evidence-fixture mid_cycle --mock-mode` runs on a fresh checkout with no env vars set and writes a single non-zero `surprise_bits` value to the in-memory archive.
- [ ] Acceptance grep (per FIX_PLAN §26.6):
  - `grep -rn "Bayesian surprise" specs/016-strategy-archive.md` — ≥ 1 hit.
  - `grep -rn "surprise_ema" specs/016-strategy-archive.md` — ≥ 1 hit.
  - `grep -rn "dirichlet_kl" specs/016-strategy-archive.md` — ≥ 1 hit.
  - `grep -rn "beta_kl" specs/016-strategy-archive.md` — ≥ 1 hit.
  - `grep -rn "google/gemini-3.5-flash" specs/016-strategy-archive.md` — ≥ 1 hit (confirms FIX_PLAN §25.5 GuideLLM model lock).
  - `grep -rn "reward_alpha + surprise_beta == 1.0" specs/016-strategy-archive.md` — ≥ 1 hit (confirms FIX_PLAN §26.2 invariant).
