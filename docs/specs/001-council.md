# Spec 001: Council Library

> Status: ☐ not started · Owner: TBD · Last updated: 2026-05-23

## CONTEXT (60-second summary — read first)
- The **Council Library** is a standalone Python module that runs three-stage deliberation (First Opinions → Anonymized Cross-Review → Chairman Synthesis) by issuing **4 independent `chat.completions.create` calls — one to each of 4 frontier models from 4 distinct vendors**, all routed through **OpenRouter**. Each call also wears a distinct **persona** (Visionary / Pessimist / Pragmatist). It emits a `CouncilVerdict` with **preserved dissent**. Used by every gate that requires judgment (C1, C2, C3, C4) and by the slow-cadence program-direction loop (C5).
- The 5 facts: (1) it's pure library — no factory dependencies; (2) **hybrid LLM access via OpenRouter — frontier models from `openai`, `anthropic`, `google`, `x-ai` vendors for the council; `google/gemini-3.5-flash` for non-council agentic calls** (per FIX_PLAN §25, which **SUPERSEDES** §24); (3) heterogeneity has **two orthogonal axes** — vendor (4 distinct vendors) AND persona (≥3 personas, Pessimist over-weighted); (4) chairman synthesis MUST cite ≥1 dissent if dissent exists; (5) sycophancy is the dominant failure mode — multi-vendor + persona heterogeneity is the **load-bearing defense**; thresholds are restored (sycophancy 0.85, calibration 0.40).
- Open first: `factory/council/api.py` and the typical-usage test.

## ENTRY POINTS
- Main module: `factory/council/api.py`
- Typical-usage test: `factory/council/tests/test_council_typical_usage.py`
- CLI: `python -m factory.council --help` (per-module form; subcommands: `deliberate`, `calibrate`, `show-session`, `show-lineup`, `show-report`, `promote-calibration`)
- Mock-mode example: `python -m factory.council deliberate --council-id C1 --question-fixture sample_worthiness --mock-mode`
- Runbook: `docs/runbooks/council-calibration.md`

## LOCAL DEBUG
- Instantiate without API keys: `Council(lineup=Council.mock_lineup(), session_dir=tmp_path).deliberate(...)` returns fixture verdicts.
- Live mode requires **one env var only**: `OPENROUTER_API_KEY` (single env var for all LLM access — frontier council models AND non-council Gemini Flash agentic calls all route through OpenRouter per FIX_PLAN §25.6).
- Heterogeneity is enforced on **both vendor and persona**: construction requires the `CouncilLineup` to declare exactly one `ModelSpec` per vendor in `{openai, anthropic, google, x-ai}` (4 distinct vendors), with the `persona_assignment` map covering ≥3 distinct personas and Pessimist appearing ≥2 times. Failure raises `CouncilError` at construction time; **there is no silent vendor substitution** — vendor heterogeneity IS the defense (FIX_PLAN §25.3).
- Common error signatures → recovery:
  - `CouncilSycophancyDetected` → hard fail; calibration failed; lineup must be re-tuned before live use. The threshold is **0.85** (restored from §24's 0.92 because multi-vendor baseline pairwise cosine is materially lower). No silent degradation.
  - `ChairmanDissentOmission` → chairman synthesis didn't cite required dissent (NLI contradiction detected); auto-rerun with stricter prompt; if still fails, escalate.
  - `PersonaRefusal` → a vendor's model refused its persona prompt (RLHF kicked in); rotate persona assignment within the lineup, or strengthen prompt. **No vendor substitution.**
  - `ModelTimeout` → a single vendor timed out via OpenRouter; the deliberation **fails** rather than silently falling back to another vendor (vendor heterogeneity is load-bearing).
  - `OpenRouterError` → OpenRouter-side HTTP 4xx/5xx, rate limit, or model retirement; the deliberation fails with this taxonomy entry; operator must check OpenRouter status or pricing/model catalog drift.
- Logs to inspect: every deliberation writes a full transcript to the caller-supplied `session_dir`. The canonical caller (state machine in spec 003) passes `runs/<cycle-id>/councils/<session_id>.jsonl`. Filter `runs/<cycle-id>/cycle.jsonl` by `module=council`.

## DEPENDENCIES
- **Hard:** Spec 002 (artifacts) — emits `CouncilVerdict`. `openai` Python SDK — the OpenAI-compatible REST client used against OpenRouter's `https://openrouter.ai/api/v1` base URL (no OpenRouter-specific SDK required per FIX_PLAN §25.1). That's it.
- **Soft:** Spec 014 (telemetry) — emits events if available. Spec 013 (budget) — costs are tracked if a budget context is provided. Both have graceful no-op fallbacks.
- **Mocks available:** `Council.mock_lineup()` returns a deterministic 4-vendor lineup that produces fixture verdicts without hitting OpenRouter. `MockOpenRouterClient` is also exposed for use in downstream tests.

---

## 1. Summary

This is the **deliberation substrate** of the factory. Every judgment gate is a call to `Council.deliberate(...)`. The library handles multi-vendor OpenRouter dispatch, persona prompting, anonymization, chairman synthesis, dissent preservation, cost tracking, and session logging.

It is shipped as a standalone library first (PRD-002) so we can prove the sycophancy defense holds **before** building anything downstream that depends on council judgment. Per FIX_PLAN §25 (which **supersedes** §24's single-vendor experiment), the council restores **two orthogonal axes of diversity** — vendor (4 distinct vendors) AND persona — because single-vendor + persona-only diversity materially weakened the defense. The hybrid topology (multi-vendor council + single-vendor Gemini Flash for non-council agentic calls) routes all LLM access through a single OpenRouter endpoint with a single `OPENROUTER_API_KEY` env var.

## 2. Scope

**In scope:**
- Three-stage deliberation protocol (First Opinions → Anonymized Cross-Review → Chairman).
- **Hybrid OpenRouter client** wrapping the OpenAI-compatible REST surface at `https://openrouter.ai/api/v1`. Frontier-model council calls plus Gemini-Flash agentic calls share a single `OpenAI(base_url=..., api_key=os.environ["OPENROUTER_API_KEY"])` client instance.
- **Multi-vendor council lineup invariant:** 4 `ModelSpec` entries, one per vendor in `{openai, anthropic, google, x-ai}`, mapped to canonical OpenRouter IDs (FIX_PLAN §25.3):
  - `openai/gpt-5.5`
  - `anthropic/claude-opus-4.7`
  - `google/gemini-3.1-pro-preview`
  - `x-ai/grok-4.3`
- **OpenRouter ranking headers on every call:** `HTTP-Referer` (loaded from operator config) and `X-OpenRouter-Title: ai-co-computational-physicist`.
- Persona prompt templates (Visionary, Pessimist, Pragmatist) loaded from `config/council/personas/{visionary,pessimist,pragmatist}.md`.
- `persona_assignment: dict[str, PersonaName]` mapping each `ModelSpec.openrouter_id` to a persona. The Pessimist persona may be assigned to ≥2 of the 4 models per the configurable map — orthogonal to the vendor axis.
- Lineup config loaded from `config/council/lineup.yaml`.
- `chairman_policy: Literal["random", "round_robin", "weighted_by_cost"]` (restored from §24 — multi-vendor pricing makes weighted-by-cost meaningful again).
- Calibration probes loaded from `config/council/probes.yaml`.
- Anonymization at stage 2 (vendor identity and persona identity stripped before cross-review — Voice A/B/C/D mapping).
- Sycophancy detection (hard fail at the **restored multi-vendor threshold of 0.85**) and `calibrate(probe_set)` for offline lineup tuning against the **restored disagreement-rate floor of 0.40**.
- Session logging to JSONL with full prompts, responses, and timing. Session path is supplied by the caller via the `session_dir` constructor argument; the state machine passes `runs/<cycle-id>/councils/<session_id>.jsonl`.
- Cost accounting per call: tokens are returned by OpenRouter in the standard OpenAI-shaped `usage` block (`prompt_tokens`, `completion_tokens`); USD is computed via `pricing_table.lookup(openrouter_id, kind) * tokens` and forwarded to `BudgetTracker.record(cost_usd=...)` when a budget context is provided (per FIX_PLAN §6.4). The single pricing table lives at `config/pricing/openrouter.yaml` and carries all 5 model entries (4 frontier + Gemini Flash) per FIX_PLAN §25.6.
- `Council.deliberate` returns a `CouncilVerdict` (spec 002) whose `chairman_decision ∈ {approve, reject, qualified, no_consensus}` (all four).
- Per-module CLI with `deliberate`, `calibrate`, `show-session`, `show-lineup`, `show-report`, `promote-calibration` subcommands. Canonical invocation form is `python -m factory.council <subcommand>`.
- Mock mode.

**Out of scope:**
- The gate state machine wiring (spec 003).
- C5 cadence scheduling (spec 003).
- UI rendering of deliberations (spec 015).
- Cross-deliberation learning / memory (Phase B).
- Council DB persistence (Phase B — Phase A logs to JSONL).
- **Silent vendor substitution / fallback.** A single-vendor failure (timeout, rate limit, model retirement) raises `CouncilError`. Vendor heterogeneity is load-bearing per FIX_PLAN §25.3 — there is no silent fallback.
- **Sampling-parameter sweeps.** Council calls use default `temperature` / `top_p` / `top_k`; persona heterogeneity + vendor heterogeneity carry the diversity. Per FIX_PLAN §25.7 an operator-controlled `--exploration-temperature` flag is deferred to Phase B.
- **Non-council agentic LLM dispatch** (code-gen, Gap Miner LLM analysis, RAG writer drafting, surrogate OOD audit, telemetry digest). Those uses are documented in their owning specs (008, 007, 011, 010, 014); they share the OpenRouter client surface defined here but call `google/gemini-3.5-flash`, not the frontier council models.

## 3. Public Interface

```python
# factory/council/api.py

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence
from factory.artifacts import (
    CouncilVerdict, CouncilId, PersonaName, ArtifactHash
)

class CouncilError(FactoryError): ...
class CouncilSycophancyDetected(CouncilError): ...
class ChairmanDissentOmission(CouncilError): ...
class PersonaRefusal(CouncilError): ...
class ModelTimeout(CouncilError): ...
class CouncilBudgetExceeded(CouncilError): ...
class BudgetTokenUsageMissing(CouncilError): ...
class OpenRouterError(CouncilError): ...    # wraps HTTP 4xx/5xx + rate limits from OpenRouter


@dataclass(frozen=True)
class CouncilContext:
    """Typed context envelope passed into deliberation prompts.

    The parent artifact is serialized once as canonical JSON so the council
    boundary never accepts an untyped mutable mapping.
    """
    parent_artifact_type: str
    parent_artifact_hash: ArtifactHash | None
    serialized_parent_json: str


# --- Hybrid OpenRouter client (per FIX_PLAN §27.2 — shared LLM substrate) ---

from factory.llm_client import OpenRouterClient, OpenRouterResponse
# Council instantiates a single `OpenRouterClient` once and dispatches per-model
# via the `model=...` parameter on `OpenRouterClient.invoke(...)`. The client
# is the concrete `DecisionClient` Protocol implementation defined in
# `specs/018-openrouter-client.md`; council retains stage / persona / chairman
# orchestration above it but never owns the SDK / base_url / api_key surface.


# --- Council lineup (multi-vendor + persona — FIX_PLAN §25.4) ---

@dataclass(frozen=True)
class ModelSpec:
    """One frontier model from one vendor, routed through OpenRouter.

    The §24 single-vendor `CouncilCall` is dropped. `ModelSpec` is restored
    with the FIX_PLAN §25.4 shape carrying the vendor axis explicitly.
    """
    openrouter_id: str                 # e.g. "openai/gpt-5.5"
    vendor: Literal["openai", "anthropic", "google", "x-ai"]
    timeout_s: float = 60.0
    max_tokens: int = 4096

@dataclass(frozen=True)
class CouncilLineup:
    """A council lineup is a fixed 4-vendor frontier set + persona assignment.

    Heterogeneity requirements (enforced at construction):
      - len(models) == 4
      - {m.vendor for m in models} == {"openai", "anthropic", "google", "x-ai"}
        (exactly one model per vendor; FIX_PLAN §25.3 — vendor heterogeneity is the defense)
      - persona_assignment.keys() == {m.openrouter_id for m in models}
        (every model has an assigned persona)
      - len(set(persona_assignment.values())) >= 3
        (≥3 distinct personas across the 4 calls)
      - sum(1 for p in persona_assignment.values() if p == "Pessimist") >= 2
        (Pessimist persona may be over-weighted — orthogonal to vendor heterogeneity;
         RLHF flattening of adversarial framing is still a known risk and is
         hedged by Pessimist over-weighting on whichever vendors handle adversarial
         framing best in calibration.)
    """
    models: Sequence[ModelSpec]                       # exactly 4, one per vendor in §25.3
    persona_assignment: dict[str, PersonaName]        # openrouter_id → persona
    chairman_policy: Literal["random", "round_robin", "weighted_by_cost"]

class Council:
    """Standalone deliberation engine — multi-vendor frontier council via OpenRouter."""

    def __init__(
        self,
        lineup: CouncilLineup,
        session_dir: Path,                 # REQUIRED — caller supplies cycle-scoped path
        cost_cap_usd: float | None = None,
        mock_mode: bool = False,
        budget_tracker: "BudgetTracker | None" = None,    # spec 013; optional, graceful no-op
        pricing_table: "PricingTable | None" = None,      # config/pricing/openrouter.yaml loader
        http_referer: str | None = None,                  # for OpenRouter ranking header; default from operator config
    ) -> None:
        """
        session_dir: per-deliberation JSONL transcripts are written to
            `session_dir / "<session_id>.jsonl"`. The canonical caller (state
            machine in spec 003) passes `runs/<cycle-id>/councils/`.
            There is no default — callers MUST supply a path.
        lineup: must satisfy the multi-vendor + persona heterogeneity requirements
            documented on `CouncilLineup`. Heterogeneity is enforced at construction;
            no silent vendor substitution.
        http_referer: the `HTTP-Referer` ranking header sent on every OpenRouter
            call. Default loaded from operator config (`config/operator.yaml`)
            or environment fallback. Combined with the constant
            `X-OpenRouter-Title: ai-co-computational-physicist` per FIX_PLAN §25.1.
        """

    def deliberate(
        self,
        council_id: CouncilId,
        question: str,
        context: CouncilContext,
        parent_hashes: list[ArtifactHash] = (),
    ) -> CouncilVerdict:
        """Run the three-stage protocol. Returns a CouncilVerdict with preserved
        dissent whose `chairman_decision ∈ {approve, reject, qualified, no_consensus}`
        (all four values are valid outputs; consumers must handle each per FIX_PLAN §3.1).

        Raises CouncilSycophancyDetected (hard fail) if `max` pairwise cosine
            similarity across first opinions exceeds `sycophancy_threshold`
            (default **0.85** — restored from §24's 0.92 because multi-vendor
            baseline similarity is materially lower per FIX_PLAN §25.4).
            No silent degradation: the deliberation is aborted before stage 2.
        Raises ChairmanDissentOmission if any first-opinion's stance is NLI-
            `contradiction` against `majority_view` AND that stance is absent
            from `preserved_dissents`. Auto-reruns chairman once with a stricter
            prompt; second failure raises.
        Raises BudgetTokenUsageMissing if an OpenRouter response is missing
            the `usage` block, OR the pricing table has no entry for the
            `(openrouter_id, kind)` lookup. The council does NOT silently
            default to zero cost.
        Raises ModelTimeout if any single vendor times out beyond retries.
            **No silent fallback to another vendor** — vendor heterogeneity
            is load-bearing (FIX_PLAN §25.3).
        Raises OpenRouterError if OpenRouter returns HTTP 4xx/5xx or rate-
            limits the deliberation.
        """

    def calibrate(
        self,
        probe_set: Path | None = None,     # YAML file; default = config/council/probes.yaml
    ) -> "CalibrationReport":
        """Run divisive probes against the current lineup; produce disagreement-rate
        report. **Acceptance threshold is 0.40 overall** (restored from §24's
        0.25 per FIX_PLAN §25.4). If `overall_disagreement_rate < 0.40` the
        lineup is unusable and PRD-002 acceptance fails.
        """

    @classmethod
    def mock_lineup(cls) -> CouncilLineup:
        """Deterministic mock lineup for testing.

        Returns a 4-vendor lineup matching FIX_PLAN §25.3:
            openai/gpt-5.5         → Pessimist
            anthropic/claude-opus-4.7 → Visionary
            google/gemini-3.1-pro-preview      → Pessimist
            x-ai/grok-4.3          → Pragmatist
        with `chairman_policy = "round_robin"`. Persona system_instructions
        are the fixture-mode renderings; no API key is required.
        """

@dataclass(frozen=True)
class CalibrationReport:
    probe_results: list["ProbeResult"]
    overall_disagreement_rate: float
    flagged_sycophancy: bool
    notes: list[str]

@dataclass(frozen=True)
class ProbeResult:
    probe_id: str
    question: str
    responses_by_model: dict[str, str]              # openrouter_id → response text
    responses_by_persona: dict[PersonaName, list[str]]  # persona → list of responses
    disagreement_rate: float                        # 1 - max pairwise cosine similarity (see §5.4)
```

## 4. Data Structures / Schemas

`CouncilVerdict` is defined in spec 002 — Council emits, does not define. Council-local types are in `factory/council/types.py` and include `CouncilLineup`, `ModelSpec`, `OpenRouterResponse`, `CalibrationReport`, `ProbeResult`.

**Stage-1 independence guarantee.** Each `ModelSpec` is dispatched as a **fresh `_CLIENT.chat.completions.create(...)` invocation** under its own `system_instruction` (from the persona assigned to it) and `model=<openrouter_id>`. Calls in the same lineup:
- share no chat session,
- share no `messages=` history,
- share no OpenRouter cache key (each call is an independent request),
- are dispatched in parallel (asyncio gather or threadpool) so timing is not a leak channel between calls,
- carry identical OpenRouter ranking headers (`HTTP-Referer`, `X-OpenRouter-Title: ai-co-computational-physicist`) so OpenRouter analytics attribute the spend correctly.

This guarantee is what makes the per-call (vendor, persona) pair the **sole** source of variation in stage 1.

**Session log format** (`runs/<cycle-id>/councils/<session_id>.jsonl` — cycle-scoped, matching ARCHITECTURE.md §1.4; the caller supplies the directory via the `session_dir` constructor argument):

```json
{"ts": "...", "event": "session_start", "council_id": "C1", "lineup_models": [{"openrouter_id": "openai/gpt-5.5", "vendor": "openai", "persona": "Pessimist"}, ...], "chairman_policy": "round_robin", "chairman_model_id": "anthropic/claude-opus-4.7"}
{"ts": "...", "event": "stage1_prompt", "model_id": "openai/gpt-5.5", "vendor": "openai", "persona": "Pessimist", "system_instruction": "...", "user_content": "..."}
{"ts": "...", "event": "stage1_response", "model_id": "openai/gpt-5.5", "model_id_actual": "openai/gpt-5.5", "response": "...", "input_tokens": ..., "output_tokens": ..., "cost_usd": ...}
{"ts": "...", "event": "stage2_anonymized_prompt", "reviewer_voice": "A", "reviewees": ["B","C","D"], "user_content": "..."}
{"ts": "...", "event": "stage2_response", "reviewer_voice": "A", "rankings": {...}, "critiques": {...}}
{"ts": "...", "event": "stage3_chairman_prompt", "chairman_model_id": "anthropic/claude-opus-4.7", "user_content": "..."}
{"ts": "...", "event": "stage3_response", "chairman_decision": "...", "majority_view": "...", "preserved_dissents": [...]}
{"ts": "...", "event": "session_end", "verdict_hash": "...", "total_cost_usd": ..., "wall_clock_s": ...}
```

**Persona prompt templates** (`config/council/personas/{visionary,pessimist,pragmatist}.md` — per FIX_PLAN §10): markdown files with placeholders `{council_id}`, `{question}`, `{context}`, and persona-specific framing. Loaded at startup and rendered into each model's `system_instruction` via the `persona_assignment` map. Lineup config lives at `config/council/lineup.yaml`; calibration probes at `config/council/probes.yaml`.

**Pricing table** (`config/pricing/openrouter.yaml` — single hybrid table per FIX_PLAN §25.6):

```yaml
# OpenRouter passthrough prices. Verify at https://openrouter.ai/models
# Updated YYYY-MM-DD by operator-during-setup.
models:
  "openai/gpt-5.5":
    input_per_1m_tokens_usd: <fill>
    output_per_1m_tokens_usd: <fill>
  "anthropic/claude-opus-4.7":
    input_per_1m_tokens_usd: <fill>
    output_per_1m_tokens_usd: <fill>
  "google/gemini-3.1-pro-preview":
    input_per_1m_tokens_usd: <fill>
    output_per_1m_tokens_usd: <fill>
  "x-ai/grok-4.3":
    input_per_1m_tokens_usd: <fill>
    output_per_1m_tokens_usd: <fill>
  "google/gemini-3.5-flash":
    input_per_1m_tokens_usd: <fill>
    output_per_1m_tokens_usd: <fill>
last_updated_iso: YYYY-MM-DD
```

The §24 `config/pricing/gemini.yaml` (single-vendor) is **dropped**. `config/pricing/openrouter.yaml` is the canonical (and only) pricing table; it carries entries for all 4 frontier council models plus `google/gemini-3.5-flash` (used by non-council agentic call sites — see spec 007, 008, 010, 011, 014).

## 5. Algorithms / Logic

### 5.1 Stage 1 — First Opinions

For each `ModelSpec` in the lineup, in parallel:
1. Look up the assigned persona from `lineup.persona_assignment[model.openrouter_id]`.
2. Render the persona template (`config/council/personas/<persona>.md`) into a `system_instruction` string with `{council_id}`, `{question}`, `{context}` substituted.
3. Invoke `_CLIENT.chat.completions.create(model=model.openrouter_id, messages=[{"role": "system", ...}, {"role": "user", ...}], max_tokens=model.max_tokens, response_format={"type": "json_object"}, extra_headers=_OPENROUTER_RANKING_HEADERS)` — a wholly independent call per FIX_PLAN §25.2.
4. Parse the JSON response into a structured `FirstOpinion(openrouter_id, vendor, persona, view, self_rank)` record.
5. Log the prompt + response + token usage to the session JSONL.
6. Compute `cost_usd` from `usage.prompt_tokens` × input price + `usage.completion_tokens` × output price (lookup in `config/pricing/openrouter.yaml`); forward to `BudgetTracker.record(cost_usd=...)`. Raise `BudgetTokenUsageMissing` if `usage` block is absent.

If any call fails (timeout, refusal, parse error, OpenRouter 5xx), retry **once** with the same prompt; if still failing, raise `ModelTimeout` / `PersonaRefusal` / `OpenRouterError`. **There is no fallback to another vendor** — vendor heterogeneity IS the defense, so a single-vendor failure must surface (FIX_PLAN §25.3). If fewer than 3 first-opinions would survive, abort with `CouncilError`.

### 5.2 Stage 2 — Anonymized Cross-Review

1. Assign each surviving stage-1 opinion a Voice letter (A, B, C, D) by **random shuffle** of the model indices. The Voice → (openrouter_id, persona) mapping is recorded in the session log but withheld from the stage-2 prompt and from stage-3 prompts where appropriate.
2. For each reviewer call (a fresh `chat.completions.create` invocation, dispatched to its assigned model from `lineup.models`), prompt with: "Here are responses from Voice A, Voice B, ...: [bodies, vendor and persona identities stripped]. Rank them by accuracy and insight. For each, write a one-line critique."
3. Dispatch in parallel. **Reviewer calls share no chat history with their stage-1 counterparts** — each is a new `chat.completions.create` invocation.
4. Collect rankings and critiques into a matrix.
5. Log to session JSONL.

The Voice-to-(vendor, persona) mapping is preserved in the session log so a UI can reveal identities under an explicit toggle. Stage 2 anonymization is preserved unchanged across the §24 → §25 transition (FIX_PLAN §25.4). The matrix passes to stage 3 with vendor + persona labels re-attached for the chairman only.

### 5.3 Stage 3 — Chairman Synthesis with Preserved Dissent

1. The chairman model is selected by `lineup.chairman_policy`:
   - `random`: uniformly random over `lineup.models`.
   - `round_robin`: deterministic by session counter modulo 4 (restored, replayable).
   - `weighted_by_cost`: inversely weighted by `pricing_table.lookup(openrouter_id, "output")` — cheaper models more likely to chair. Meaningful only now that pricing varies across vendors (multi-vendor pricing makes this knob real again per FIX_PLAN §25.4).
2. The chairman call is **one more independent `chat.completions.create` invocation** against the chosen model, with the **same persona** it was assigned in stage 1 (the persona prompt is re-rendered as the system_instruction). It receives: the original question, all first opinions (with vendor + persona labels re-attached), and the stage-2 cross-review matrix (with vendor + persona labels re-attached for the chairman only).
3. Chairman prompt explicitly requires:
   - State the majority view in 1–3 paragraphs.
   - List every dissenting view with its rationale; do NOT omit dissent.
   - Issue a `chairman_decision: approve | reject | qualified | no_consensus` (all four are valid; consumers of `CouncilVerdict` must handle each per FIX_PLAN §3.1).
4. Parse chairman response into the structured `CouncilVerdict` fields.
5. **Validate via NLI (Natural Language Inference)**: cosine similarity is NOT used here — it confuses "disagrees with" with "talks about different things". Use an entailment/contradiction model instead.

   **Procedure:**
   - For each `FirstOpinion.view` `o_i` produced in stage 1, run the NLI model with **premise = `majority_view`** and **hypothesis = `o_i`**. The model returns label probabilities over `{entailment, neutral, contradiction}`.
   - Classify `o_i` as a "material dissent" iff `argmax = contradiction` AND `P(contradiction) ≥ nli_contradiction_threshold` (config default `0.60`).
   - For each material dissent, check whether its stance is represented in `CouncilVerdict.preserved_dissents` (semantic match on dissent body, using the same NLI: a preserved dissent represents `o_i` iff `NLI(premise = preserved_dissent.body, hypothesis = o_i.view).argmax == entailment`).
   - If ANY material dissent has no entailing preserved-dissent entry, raise `ChairmanDissentOmission`. Auto-rerun the chairman once with a stricter re-prompt that re-injects the omitted dissent verbatim. On second failure, raise — do not silently degrade.

   **NLI model pin:** `cross-encoder/nli-deberta-v3-base` (open-weight, local, vendor-agnostic; **independent of every council vendor** so the dissent check is not adjudicated by any of the council members themselves). The `nli_contradiction_threshold` default of `0.60` is calibrated against this model; switching models requires re-calibration of the threshold (recorded in `CalibrationReport.notes`).

   **Why NLI not cosine:** two opinions that say "approve because X" vs. "reject because X" have HIGH cosine similarity (same vocabulary) but logical opposition. NLI catches the polarity; cosine doesn't.

### 5.4 Sycophancy detection

After stage 1 (before spending money on stage 2), compute pairwise semantic similarity across first opinions and emit `CouncilSycophancyDetected` if the lineup is converging. This is a **hard fail** (no silent degradation, no recovery path within the deliberation).

**Multi-vendor restoration (FIX_PLAN §25.4).** The §24 single-vendor architecture lifted the threshold to 0.92 because Gemini-only baseline pairwise cosine was high. With 4 distinct vendors restored, baseline pairwise cosine drops materially — the threshold returns to **0.85**. The G4 validation portfolio (spec 009) returns to its standard burden (no longer needs to default to the "intensified" path on every non-unanimous cycle); restored multi-vendor heterogeneity carries the truth-finding burden alongside G4.

**Statistic — `max`, not `mean`:**

Let `O = {o_1, ..., o_N}` be the surviving stage-1 first opinions (`N = 4` in the canonical lineup; if fewer due to per-call failures, §5.1's abort path may fire instead). Compute the **unordered** pairwise cosine similarity set

```
S = { cos(embed(o_i), embed(o_j)) : 1 ≤ i < j ≤ N }
```

and define

```
agreement = max(S)
```

If `agreement > sycophancy_threshold` (config default `0.85` per FIX_PLAN §25.4), raise `CouncilSycophancyDetected`.

**Why `max` and not `mean`.** The check is meant to fire on **groupthink**, which canonically presents as "3 calls agree tightly + 1 dissenter". In that exact scenario `mean` *dilutes* the signal because the dissenter's low-similarity pairs (3 of the 6 pairs for N=4) drag the average back below threshold. `max` catches the same scenario instantly: if ANY pair of calls is in near-lockstep, the lineup has lost critical heterogeneity, and stage 2 is wasted spend. We are deliberately trading some false-positive rate (a single high-similarity pair will fire the check) for the property that "any subset agreeing tightly fires" — which is the property we actually want.

**Pair count — explicit `N*(N-1)/2` unordered pairs, excluding self-pairs.**

The pairwise set `S` contains exactly

```
|S| = N * (N - 1) / 2
```

unordered pairs `(i, j)` with `i < j`. Self-pairs `(i, i)` are excluded (cos(x, x) = 1 would always saturate the max). Ordered pairs `(i, j)` and `(j, i)` are counted once, not twice (cosine is symmetric: `cos(a, b) = cos(b, a)`).

**Worked example for N=4** (the canonical 4-vendor lineup):

| pair index | (i, j) | vendors in pair | personas in pair (example assignment) |
| ---: | :--- | :--- | :--- |
| 1 | (1, 2) | (openai, anthropic) | (Pessimist, Visionary) |
| 2 | (1, 3) | (openai, google) | (Pessimist, Pessimist)  ← same-persona pair |
| 3 | (1, 4) | (openai, x-ai) | (Pessimist, Pragmatist) |
| 4 | (2, 3) | (anthropic, google) | (Visionary, Pessimist) |
| 5 | (2, 4) | (anthropic, x-ai) | (Visionary, Pragmatist) |
| 6 | (3, 4) | (google, x-ai) | (Pessimist, Pragmatist) |

`|S| = 4 * 3 / 2 = 6` pairs. **Not 16** (16 = `N²` counts self-pairs + double-counts ordered); **not 12** (12 = `N * (N-1)` double-counts ordered without self-pairs); **not 10** (the off-by-one `N * (N-1) / 2 + 1`). Six.

Note: the **same-persona Pessimist-Pessimist pair** is expected to have higher cosine than mixed-persona pairs but is still attenuated by vendor difference. The threshold at 0.85 is calibrated to tolerate one same-persona cross-vendor pair near the high end without firing.

**Embedding model pin — `sentence-transformers/all-mpnet-base-v2`.**

The embedding model is pinned to `sentence-transformers/all-mpnet-base-v2` (open-weight, local, vendor-agnostic, well-calibrated cosine scale — **independent of every council vendor**, so the sycophancy check is not adjudicated by any of the council members themselves). The threshold `sycophancy_threshold = 0.85` is **calibrated against this specific model on the canonical 4-vendor lineup**: it is the empirical 95th-percentile pairwise cosine across the built-in probe set when the multi-vendor + persona lineup is healthy (disagreement-rate ≥ 0.40 per §5.5). Substituting a different embedding model shifts the cosine scale and invalidates the threshold; switching models requires re-running `calibrate()` and recording the new threshold in `CalibrationReport.notes` before live use.

We pick `all-mpnet-base-v2` specifically because: (a) it is open-weight and runs locally with no vendor dependency, preserving the library's standalone property (PRD-002); (b) it produces 768-dim normalized embeddings on a well-studied cosine scale; (c) **it is not from any of the four council vendors** — using a council vendor's own embeddings to police that vendor's own outputs is a self-reinforcing loop and is explicitly avoided.

**Pseudocode:**

```python
def detect_sycophancy(
    opinions: Sequence[FirstOpinion],
    *,
    sycophancy_threshold: float = 0.85,   # FIX_PLAN §25.4 — restored from §24's 0.92
    embedding_model: str = "sentence-transformers/all-mpnet-base-v2",
) -> None:
    n = len(opinions)
    if n < 3:
        return  # §5.1 abort path will fire separately
    embeddings = embed_batch([o.view for o in opinions], model=embedding_model)
    # cosine similarity matrix; we only inspect the strict upper triangle.
    sims = [
        cosine(embeddings[i], embeddings[j])
        for i in range(n)
        for j in range(i + 1, n)
    ]
    assert len(sims) == n * (n - 1) // 2  # N*(N-1)/2 unordered pairs
    agreement = max(sims)
    if agreement > sycophancy_threshold:
        raise CouncilSycophancyDetected(
            f"max pairwise cosine = {agreement:.3f} > threshold {sycophancy_threshold:.3f} "
            f"across {len(sims)} pairs (multi-vendor lineup; threshold per FIX_PLAN §25.4)"
        )
```

### 5.5 Calibration probes

`calibrate()` runs the lineup against the probe set at `config/council/probes.yaml` (or a caller-supplied path). Each probe has a question + expected-disagreement notes.

**Disagreement-rate per probe** = `1 - max_pairwise_cosine_similarity` (the complement of §5.4's `agreement` statistic, using the same `sentence-transformers/all-mpnet-base-v2` embedding model and the same `N*(N-1)/2` unordered-pair enumeration). A probe with a tightly-agreeing pair scores low; a probe where the most-similar pair is still distant scores high.

The report aggregates per-probe and overall.

Built-in probe set covers:
- Subjective physics judgments (interpretation of borderline experimental results).
- Methodological choices (which optimizer to prefer for an ALM problem).
- Significance assessments (does this finding matter).
- Adversarial probes (questions designed to elicit easy agreement).
- Vendor-pressure probes — questions specifically designed to test whether any single vendor's RLHF systematically flattens against adversarial framing (the diagnostic for whether vendor heterogeneity is actually firing across the canonical 4-vendor set).

Minimum 10 probes.

**Acceptance threshold (FIX_PLAN §25.4):** PRD-002 acceptance requires `overall_disagreement_rate ≥ 0.40` (restored from §24's 0.25). Multi-vendor + persona heterogeneity should comfortably clear 0.40; if it does not, the lineup configuration or persona prompts must be re-tuned before live use.

## 6. Failure Modes

| Error class | When it fires | Recovery action |
| :--- | :--- | :--- |
| `CouncilSycophancyDetected` | `max` pairwise cosine across stage-1 first opinions exceeds `sycophancy_threshold` (default **0.85**, calibrated against `sentence-transformers/all-mpnet-base-v2` on the canonical 4-vendor lineup per FIX_PLAN §25.4) | **Hard fail — no silent degradation.** Deliberation is aborted before stage 2. State machine pauses; operator must re-tune persona prompts or rotate model lineup within OpenRouter catalog; `calibrate()` must pass at ≥0.40 before resume. There is no in-deliberation recovery path. |
| `ChairmanDissentOmission` | An `o_i` first-opinion is NLI-classified `contradiction` (`cross-encoder/nli-deberta-v3-base`, P ≥ 0.60) vs. `majority_view` AND has no entailing entry in `preserved_dissents` | Auto-rerun chairman once with a stricter re-prompt that re-injects the omitted dissent verbatim; second failure raises |
| `PersonaRefusal` | A vendor's model returned a meta-response refusing the persona prompt (RLHF rejection of adversarial framing) | Retry once with the same prompt revision; second failure raises. **No silent vendor substitution** — operator must either rotate the persona assignment within the existing 4-vendor lineup or strengthen the persona prompt. |
| `ModelTimeout` | A single vendor's OpenRouter request timed out beyond `ModelSpec.timeout_s` | Retry once with exponential backoff; second timeout raises. **No silent fallback to another vendor.** Vendor heterogeneity is load-bearing per FIX_PLAN §25.3; if a vendor is repeatedly unavailable, the deliberation fails and the operator must investigate (OpenRouter status, vendor outage, or the canonical model ID needs updating against the live catalog). |
| `CouncilBudgetExceeded` | `cost_cap_usd` was set and reached | Halt at next stage boundary; return partial verdict with `chairman_decision="no_consensus"` |
| `BudgetTokenUsageMissing` | An OpenRouter response is missing the `usage` block (token counts), OR `config/pricing/openrouter.yaml` has no entry for the `(openrouter_id, kind)` lookup | Raise immediately. Council does NOT silently default to zero cost. Operator must fix the pricing table or investigate the missing `usage` response. |
| `OpenRouterError` | OpenRouter returns HTTP 4xx/5xx, exceeds rate limits, or the requested model ID has been retired from the catalog | Raise immediately. Wraps the underlying `httpx`/SDK error with status code + OpenRouter error body. Operator must check OpenRouter status, pricing-table drift, or model-catalog updates. No silent retry against a different vendor — that would defeat the multi-vendor defense. |
| `ParseError` (model response invalid) | Couldn't parse structured JSON response (OpenRouter `response_format={"type": "json_object"}` returned malformed JSON) | Retry once with reformat prompt; second failure abandons that opinion |

## 7. Testing

**Mock-mode** (in CI):
- `test_council_typical_usage.py` — REQUIRED. Mock 4-vendor lineup, sample question, verifies `CouncilVerdict` shape + preserved dissent + cost accounting against `config/pricing/openrouter.yaml` (all 5 model entries).
- `test_stages.py` — each stage individually with a `MockOpenRouterClient` (no `openai` SDK live calls).
- `test_chairman_dissent_enforcement.py` — feed chairman a response with omitted dissent; verify rerun + escalation.
- `test_sycophancy_detection.py` — feed identical responses; verify `CouncilSycophancyDetected` at the **0.85** threshold. MUST include an N=4 case with one tightly-agreeing pair to verify `max` catches what `mean` would miss, calibrated against the multi-vendor baseline.
- `test_persona_loading.py` — templates load + render correctly into the `system_instruction` for each `ModelSpec` via `persona_assignment`.
- `test_anonymization.py` — Voice mapping random + identity-blind in stage 2 prompts; vendor + persona labels re-attached for chairman.
- `test_chairman_policy.py` — verify `random`, `round_robin`, `weighted_by_cost` all work; round_robin is deterministically replayable across cycles.
- `test_multi_vendor_invariants.py` — verify construction rejects any lineup whose `{m.vendor for m in models}` is not exactly `{openai, anthropic, google, x-ai}`; verify ranking headers are sent on every call; verify no silent vendor-substitution path exists in `Council.deliberate`.
- `test_openrouter_error_taxonomy.py` — verify `OpenRouterError`, `ModelTimeout`, `BudgetTokenUsageMissing` surface correctly under simulated 4xx/5xx, timeout, and missing-`usage` cases.

**Live-mode** (`@pytest.mark.live`, gated):
- `test_live_calibration.py` — runs `calibrate()` against the real 4-vendor OpenRouter lineup; asserts `overall_disagreement_rate ≥ 0.40` (FIX_PLAN §25.4 threshold).
- `test_live_deliberation_smoke.py` — single deliberation against real OpenRouter; verifies cost ≤ $0.50 (FIX_PLAN §25.8 cost target — restored from §24's $0.10).

**Manual verification step** (one-time, documented in runbook):
- Inspect at least one stage-3 transcript by hand for "real" dissent (not boilerplate hedging).
- Verify model-catalog freshness via `curl https://openrouter.ai/api/v1/models -H "Authorization: Bearer $OPENROUTER_API_KEY"` and confirm all 4 canonical IDs resolve.

## 8. Performance & Budget

- Per deliberation: target ≤60 s wall clock, **≤$0.50 cost** (4 frontier-model calls × 3 stages + chairman + local-embedding sycophancy check + local-NLI dissent check; the two local models add ~0 USD, only GPU/CPU time). Restored from §24's $0.10 target per FIX_PLAN §25.8 — frontier model pricing across 4 vendors is materially higher than Gemini-Flash only, and the sycophancy defense is worth the multiplier.
- OpenRouter calls dispatched in parallel within a stage; stages are sequential.
- Cost is hard-capped by `cost_cap_usd` constructor argument; library never exceeds.
- **Cost accounting (per FIX_PLAN §6.4 + §25.6):** OpenRouter returns token counts via the OpenAI-shaped `usage.prompt_tokens` and `usage.completion_tokens` — never USD. The library computes USD per call via

  ```
  cost_usd = pricing_table.lookup(openrouter_id, "input")  * (prompt_tokens     / 1e6)
           + pricing_table.lookup(openrouter_id, "output") * (completion_tokens / 1e6)
  ```

  where `pricing_table` is loaded **once** from `config/pricing/openrouter.yaml` (single hybrid table — covers all 4 frontier council models AND `google/gemini-3.5-flash` for non-council agentic call sites). The resulting `cost_usd` is forwarded to the optional `BudgetTracker.record(cost_usd=...)` when a budget context is provided to the constructor. If the pricing table has no entry for an `openrouter_id` (or `usage` is missing from the response), the call raises `BudgetTokenUsageMissing` (per FIX_PLAN §6.4 — formerly `BudgetUnknownCost`); the council does NOT silently default to a zero cost.
- Calibration: ~10× the cost of a single deliberation (one call per probe per model × 4 models × ≥10 probes). Run rarely. At the §25.8 ≤$0.50/deliberation target this is ≤$5 per full calibration; the larger cost vs. §24 is the price of restored multi-vendor heterogeneity.

## 9. Open Questions

- **Vendor-specific persona drift.** Each vendor's RLHF shapes adversarial framing differently — Anthropic's Claude may refuse Pessimist where OpenAI's GPT-5.5 complies (or vice versa). Track `PersonaRefusal` rate per `(vendor, persona)` cell during calibration; if any cell exceeds 20%, rotate persona assignment within the existing 4-vendor lineup.
- **OpenRouter routing transparency.** OpenRouter may internally route to different providers for the same model ID. `OpenRouterResponse.model_id_actual` captures the resolved model ID; if it drifts from the requested `openrouter_id`, log and surface but do not fail (this is OpenRouter's contracted behavior).
- **Model-catalog drift.** Vendor model IDs migrate (`gpt-5.5` → `gpt-5-5-preview` etc.). The startup health check (see §10 TODOs) verifies all 4 canonical IDs resolve against `GET /api/v1/models`; if any has been retired, fail at startup rather than at the first deliberation.
- **Chairman persona selection bias.** A chairman policy that systematically picks "qualified" diffuses signal. Track chairman-decision distribution by `(chairman_model_id, persona)` over time; flag if any pair dominates >70%.
- **Cross-deliberation memory.** Phase A is stateless per deliberation. Phase B might inject prior council decisions as context, but that risks feedback loops.
- **`weighted_by_cost` policy semantics.** Now meaningful (multi-vendor pricing varies), but if it systematically routes the chairman to one cheap vendor across many cycles, the chairman persona's vendor bias could leak in. Track and flag.

## 10. TODO Checklist

- [ ] Scaffold `factory/council/` from the canonical module template.
- [ ] Implement **OpenRouter client wrapper** (`factory/council/openrouter_client.py`): module-level `_CLIENT = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"])`; `call_llm(model, system_instruction, user_content, max_tokens, json_mode) -> OpenRouterResponse` matching FIX_PLAN §25.2 verbatim. **No `temperature` / `top_p` / `top_k` override.** **No vendor-fallback retries.** Single client serves both council and any non-council agentic call sites.
- [ ] Wire **OpenRouter ranking headers** on every call: `HTTP-Referer` from operator config + constant `X-OpenRouter-Title: ai-co-computational-physicist`.
- [ ] Implement **per-vendor health check at startup**: hit `GET https://openrouter.ai/api/v1/models` and verify all 4 canonical IDs from FIX_PLAN §25.3 resolve. Fail-fast at startup on retirement / catalog drift — do not let the first deliberation discover this.
- [ ] Implement **pricing-table reader** for `config/pricing/openrouter.yaml` with all 5 model entries (4 frontier council + `google/gemini-3.5-flash`). Raise `BudgetTokenUsageMissing` on lookup miss.
- [ ] Author persona prompt templates at `config/council/personas/{visionary,pessimist,pragmatist}.md`.
- [ ] Author lineup config at `config/council/lineup.yaml` with exactly 4 `ModelSpec` entries (one per vendor) and a `persona_assignment` map (Pessimist may be assigned ≥2 of 4). Load it in `Council.__init__`. **Enforce vendor heterogeneity invariant** (`{m.vendor for m in models} == {openai, anthropic, google, x-ai}`) and persona invariants (≥3 distinct personas, Pessimist ≥2) at construction.
- [ ] Implement `Council.__init__` with required `session_dir: Path` argument (no default), multi-vendor + persona heterogeneity validation, optional `BudgetTracker`, hybrid `PricingTable` loader for `config/pricing/openrouter.yaml`, `http_referer` override.
- [ ] Implement stage 1 dispatcher: one fresh `_CLIENT.chat.completions.create(...)` per `ModelSpec`; parallel dispatch; no shared chat history; ranking headers attached; JSON-mode structured output via `response_format={"type": "json_object"}`.
- [ ] Implement stage 2 anonymizer + cross-review dispatcher + matrix builder. Voice → `(openrouter_id, persona)` mapping recorded in session log; vendor + persona identities stripped from stage-2 prompts.
- [ ] Implement stage 3 chairman synthesis with `random | round_robin | weighted_by_cost` policy (restored — multi-vendor pricing makes `weighted_by_cost` real). Emit all four `chairman_decision` values (`approve | reject | qualified | no_consensus`).
- [ ] Implement NLI-based dissent-omission detection (§5.3 step 5) pinned to `cross-encoder/nli-deberta-v3-base`, threshold P(contradiction) ≥ 0.60, with auto-rerun and second-failure raise.
- [ ] Implement sycophancy detection (§5.4): `max` pairwise cosine, `N*(N-1)/2` explicit pair enumeration, embedding model pinned to `sentence-transformers/all-mpnet-base-v2`, **threshold 0.85 (FIX_PLAN §25.4)**, hard fail (no silent degradation).
- [ ] Implement `calibrate()` runner reading `config/council/probes.yaml`. Acceptance threshold **0.40** (FIX_PLAN §25.4 — restored from §24's 0.25).
- [ ] Author built-in probe set at `config/council/probes.yaml` with ≥10 probes including vendor-pressure probes designed to test cross-vendor RLHF refusal patterns.
- [ ] Implement session JSONL logger writing to caller-supplied `session_dir` (canonical: `runs/<cycle-id>/councils/<session_id>.jsonl`). Log `model_id_actual` alongside requested `openrouter_id` to surface OpenRouter routing.
- [ ] Implement cost accounting: token→USD conversion via hybrid `config/pricing/openrouter.yaml` reader; forward `cost_usd` to `BudgetTracker.record(...)`; raise `BudgetTokenUsageMissing` when pricing entry absent OR `usage` block missing; enforce `cost_cap_usd` ≤$0.50 default.
- [ ] Implement `OpenRouterError` taxonomy: wrap `httpx`/SDK HTTP 4xx/5xx + rate-limit responses with status code + OpenRouter error body. No silent retry against a different vendor.
- [ ] Build mock-mode (`Council.mock_lineup()` + `MockOpenRouterClient`). MockOpenRouterClient must NOT depend on the live `openai` package's network code paths so CI is offline.
- [ ] Write `factory/council/cli.py` with `deliberate / calibrate / show-session / show-lineup / show-report / promote-calibration` subcommands, all reachable as `python -m factory.council <subcommand>`.
- [ ] Write 9 tests (typical-usage + 8 concern-specific including `test_multi_vendor_invariants.py` and `test_openrouter_error_taxonomy.py`). All pass in mock mode. Sycophancy test must include an N=4 case with one tightly-agreeing pair to verify `max` catches what `mean` would miss, calibrated against the 0.85 multi-vendor threshold.
- [ ] Write `tests/test_live_calibration.py` (live; manual gate; asserts ≥0.40 disagreement-rate).
- [ ] Write `factory/council/README.md` (≤ 1 page, mock-mode example).
- [ ] Update `docs/runbooks/council-calibration.md` for multi-vendor OpenRouter lineup setup, 0.40 threshold, ranking-header configuration, and the per-vendor startup health check.
- [ ] Verify `mypy --strict factory/council/` passes.
- [ ] Verify `python -m factory.council deliberate --mock-mode` works on a fresh checkout with only `OPENROUTER_API_KEY` (or no env vars in mock mode).
- [ ] PRD-002 acceptance: live calibration shows ≥0.40 disagreement-rate (per FIX_PLAN §25.4).
- [ ] Acceptance grep (per FIX_PLAN §25.10): `grep -rn "ANTHROPIC_API_KEY\|OPENAI_API_KEY\|XAI_API_KEY\|GEMINI_FLASH\|GOOGLE_API_KEY\|pricing/gemini.yaml" specs/001-council.md` returns zero hits (other than this acceptance bullet itself).
