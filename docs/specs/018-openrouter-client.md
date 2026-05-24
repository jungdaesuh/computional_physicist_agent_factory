# Spec 018: OpenRouter Client (Shared LLM Substrate)

> Status: ☐ not started · Owner: TBD · Last updated: 2026-05-23

## CONTEXT (60-second summary — read first)
- This module is the **single shared LLM client** used by every LLM-touching module in the factory (council, gap miner, generator-verifier, RAG writer, surrogate OOD audit, telemetry digest). It is a drop-in replacement for the proxima harness's `OpenAICodexClient` and preserves the same `DecisionClient` Protocol → `RateLimitedDecisionClient` → `FileClient` layering pattern so existing consumer code only needs to swap the constructor, not the call shape. Per FIX_PLAN §27.2.
- The 5 facts: (1) **single env var `OPENROUTER_API_KEY`** for all LLM access per FIX_PLAN §25.6 — no vendor-specific keys remain; (2) **OpenAI-SDK compatible** via base-URL override (`https://openrouter.ai/api/v1`) per FIX_PLAN §25.1 — no OpenRouter-specific SDK is shipped; (3) the **`DecisionClient` Protocol** is the contract every consumer imports against, so swapping `OpenRouterClient` ↔ `FileClient` ↔ `MockOpenRouterClient` is a constructor change only; (4) **USD cost is computed locally** from response `usage` block × `config/pricing/openrouter.yaml` per FIX_PLAN §25.6 — never vendor-reported USD, because OpenRouter only returns token counts; (5) the **`RateLimitedDecisionClient` wrapper** provides process-wide rate limiting via a token bucket so concurrent council, agentic, and surrogate calls share one budget without coordinating themselves.
- Open first: `factory/llm_client/api.py` and `factory/llm_client/tests/test_llm_client_typical_usage.py`.

## ENTRY POINTS
- Main module: `factory/llm_client/api.py`
- Typical-usage test: `factory/llm_client/tests/test_llm_client_typical_usage.py`
- CLI: `python -m factory.llm_client --help` (subcommands: `invoke`, `verify-key`, `list-models`, `pricing-check`)
- Mock-mode example: `python -m factory.llm_client invoke --fixture sample_round_trip --mock-mode`
- Runbook: `docs/runbooks/openrouter-client.md`

## LOCAL DEBUG
- Instantiate without API calls: `FileClient(transcript_path=Path("factory/llm_client/fixtures/transcripts/sample_round_trip.json")).invoke(messages=[...], model="google/gemini-3.5-flash")` returns a fixture `OpenRouterResponse` with pre-canned `input_tokens` / `output_tokens` / `cost_usd`.
- Live mode requires **only** `OPENROUTER_API_KEY` in the environment (FIX_PLAN §25.6). All other LLM env vars are intentionally absent — the §25.10 acceptance grep enforces this.
- Common error signatures → recovery:
  - `OpenRouterAuthError` → 401 from upstream; the API key is invalid, revoked, or quota-exhausted at the OpenRouter account level. **Non-retryable.** Operator must rotate the key or settle the account; the client refuses to retry because retrying with the same bad key is wasted spend.
  - `OpenRouterRateLimitError` (inherits `TransientAPIError`) → 429 from upstream. Backoff + retry per `RetryPolicy`; if retries exhausted, raise to the caller and the state machine routes per §6.
  - `OpenRouterConnectError` (inherits `TransientAPIError`) → network/DNS/TCP/connection-reset before the request reached the server. Backoff + retry.
  - `OpenRouterModelUnavailable` → 404 on the model ID; the model has been retired or renamed in the OpenRouter catalog. **Non-retryable.** Operator fixes `config/council/lineup.yaml` or the call site's hard-coded model string and verifies via `python -m factory.llm_client list-models`.
  - `BudgetTokenUsageMissing` → OpenRouter returned a 200 response without a `usage` block (or with the block but missing `prompt_tokens` / `completion_tokens`); computed cost is unavailable. **Non-retryable** from this module — the caller's budget tracker (spec 013) parks the operation per FIX_PLAN §6.4.
- Logs to inspect: every `invoke()` writes a `factory.llm_client.invoke_*` event line to `runs/<cycle-id>/cycle.jsonl`. Filter `module=llm_client` and pivot on `request_id` to correlate a single round-trip's `invoke_started` / `invoke_complete` (or `invoke_failed`) pair.

## DEPENDENCIES
- **Hard:** `openai` Python SDK (≥1.0) — the OpenAI-compatible REST client used against OpenRouter's `https://openrouter.ai/api/v1` base URL (FIX_PLAN §25.1). `config/pricing/openrouter.yaml` — single hybrid pricing table covering all 5 model rows (4 frontier council + `google/gemini-3.5-flash` agentic), loaded **once** at startup per FIX_PLAN §25.6. Spec 002 (artifacts) for `FactoryError` base class.
- **Soft:** Spec 014 (telemetry) — every `invoke()` emits `factory.llm_client.invoke_started` / `invoke_complete` / `invoke_failed` events when a telemetry sink is registered; otherwise the events are dropped with a one-time INFO log so the client stays standalone in mock-mode tests.
- **Mocks available:** `FileClient` replays a fixture transcript from `factory/llm_client/fixtures/transcripts/<name>.json` and never touches the network. `MockOpenRouterClient` returns deterministic responses keyed off `(model, messages_hash)` for unit tests that want to assert call shape without committing to a recorded transcript.

---

## 1. Summary

This module is the **single shared LLM substrate** for the factory. It is the drop-in replacement for the proxima harness's Codex-OAuth client (`/Users/suhjungdae/code/software/proxima_fusion/ai-sci-feasible-designs/harness/decision_client.py`): the proxima `OpenAICodexClient` (Codex Responses API over ChatGPT subscription OAuth) is swapped for an **OpenRouter Bearer-token client** that speaks the OpenAI-compatible REST surface at `https://openrouter.ai/api/v1`. The Protocol-driven layering — `DecisionClient` Protocol + concrete client + `RateLimitedDecisionClient` wrapper + `FileClient` mock — is **preserved verbatim** so every downstream consumer (council in spec 001, gap miner in spec 007, generator-verifier in spec 008, RAG writer in spec 011, surrogate OOD audit in spec 010, strategy archive in spec 016) imports `from factory.llm_client import OpenRouterClient` and uses the same `client.invoke(messages, model=..., max_tokens=..., response_format=...)` shape. Per FIX_PLAN §27.2 this module is the single point of OpenRouter contact in the factory and the single source of truth for the OpenAI-compatible request shape documented in FIX_PLAN §25.2.

## 2. Scope

**In scope:**
- The shared `OpenRouterClient` class implementing the `DecisionClient` Protocol against OpenRouter's `https://openrouter.ai/api/v1` base URL using the `openai` Python SDK with `base_url` override per FIX_PLAN §25.1.
- The `DecisionClient` Protocol (runtime-checkable) — the contract every consumer imports against.
- The `RateLimitedDecisionClient` wrapper — process-wide token-bucket rate limiting per FIX_PLAN §27.2, configurable `rps`, blocking `acquire()` before each `invoke()`.
- The `FileClient` mock — replays a fixture transcript from `factory/llm_client/fixtures/transcripts/`; used by every consumer's mock-mode test.
- The `MockOpenRouterClient` deterministic mock — keyed responses for unit tests that want to assert call shape.
- `OpenRouterResponse` frozen dataclass — the canonical response shape returned to every consumer.
- `PricingTable` Pydantic model loaded **once** at startup from `config/pricing/openrouter.yaml` per FIX_PLAN §25.6 (5 model rows: 4 frontier council + Gemini Flash).
- `RetryPolicy` config dataclass — exponential backoff with jitter on `TransientAPIError`; max 3 retries by default; **refuse retry on `OpenRouterAuthError`** and on any 4xx that is not 429 (per FIX_PLAN §27.2).
- USD cost computation per response: `(input_tokens × input_per_1m / 1e6) + (output_tokens × output_per_1m / 1e6)` per FIX_PLAN §25.6.
- HTTP status → exception classification (401 → `OpenRouterAuthError`; 429 → `OpenRouterRateLimitError`; 5xx / network / connection-reset → `OpenRouterConnectError`; 404 model → `OpenRouterModelUnavailable`).
- OpenRouter ranking headers on every call: `HTTP-Referer` (loaded from operator config) + constant `X-OpenRouter-Title: ai-co-computational-physicist` per FIX_PLAN §25.1.
- Structured-outputs passthrough — `response_format={"type": "json_object"}` and `response_format={"type": "json_schema", ...}` per FIX_PLAN §25.1.
- Telemetry events on every `invoke()` (`invoke_started` / `invoke_complete` / `invoke_failed`) per FIX_PLAN §27.2.
- Per-module CLI: `invoke`, `verify-key`, `list-models`, `pricing-check`.

**Out of scope:**
- **OAuth refresh logic** — the proxima `harness/auth.py` `ensure_fresh_token(skew=60)` refresh dance is **dropped**. OpenRouter authenticates with a static `Authorization: Bearer ${OPENROUTER_API_KEY}` header; there is no token to refresh. The proxima `CodexAuthError` taxonomy reduces here to `OpenRouterAuthError` and the entire refresh / retry-after-refresh code path is removed.
- **Per-vendor failover** — explicitly dropped on §25 amendment. A single-vendor failure (e.g., the OpenAI-vendor council slot is down) raises `OpenRouterError` and the council's deliberation fails. Vendor heterogeneity is the load-bearing defense per FIX_PLAN §25.3; there is no silent substitution.
- **Prompt management** — consumers own their prompts. This module never assembles a `system_instruction`, never renders a persona template, never decides what model to call. It only ships the messages it is given.
- **Multi-turn ReAct loop logic** — that lives in spec 008 (generator-verifier multi-turn agent loop). This module is the *transport*; the agent loop is the *protocol*.
- **Sampling-parameter overrides** — no `temperature` / `top_p` / `top_k` defaults are applied by this module (per FIX_PLAN §25.7). Consumers that want exploration sampling pass the parameters through `invoke(...)` extra kwargs in Phase B; Phase A leaves them at vendor defaults.
- **Council-specific logic** (anonymization, dissent preservation, sycophancy detection, persona prompting) — all live in spec 001. This module is generic.

## 3. Public Interface

```python
# factory/llm_client/api.py

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from factory.artifacts import FactoryError


# --------------------------------------------------------------------------
# Exception hierarchy (all inherit FactoryError per FIX_PLAN §27.2)
# --------------------------------------------------------------------------

class LLMClientError(FactoryError):
    """Base for every error this module raises."""


class TransientAPIError(LLMClientError):
    """Retryable infrastructure / protocol failure (network / 5xx / 429).

    Subclasses refine the cause for telemetry. The `RetryPolicy` retries
    these; non-`TransientAPIError` subclasses of `LLMClientError` are NOT
    retried.
    """

    def is_retryable(self) -> bool:
        return True


class OpenRouterAuthError(LLMClientError):
    """OpenRouter rejected the Bearer token (HTTP 401).

    Non-retryable: the API key is invalid, revoked, or the OpenRouter account
    is quota-exhausted at the account tier. Retrying with the same bad key
    burns money for no reason. Operator rotates the key.
    """

    def is_retryable(self) -> bool:
        return False


class OpenRouterRateLimitError(TransientAPIError):
    """OpenRouter HTTP 429 — request rate exceeded the account's per-minute cap.

    Retryable per `RetryPolicy` with exponential backoff and jitter.
    """


class OpenRouterConnectError(TransientAPIError):
    """Network / DNS / TCP / connection-reset before the response was received.

    Retryable per `RetryPolicy`. Includes upstream 5xx (502 / 503 / 504).
    """


class OpenRouterModelUnavailable(LLMClientError):
    """OpenRouter HTTP 404 on the model ID — model was retired or renamed.

    Non-retryable: the catalog has moved. Operator updates the call site
    or `config/council/lineup.yaml` and verifies via the `list-models` CLI.
    """


class BudgetTokenUsageMissing(LLMClientError):
    """Response was 200 but lacks the `usage` block (or `prompt_tokens` /
    `completion_tokens` keys). USD cannot be computed.

    The error class is shared with spec 013 §6.4 — the canonical definition
    lives in `factory.budget`; this module raises the same class so the
    budget tracker's recovery path applies uniformly.
    """


class OpenRouterError(LLMClientError):
    """Catch-all for non-4xx / non-5xx OpenRouter failures (e.g., malformed
    response envelope, unsupported `response_format`, etc.). Non-retryable.
    """


# --------------------------------------------------------------------------
# Response dataclass
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class OpenRouterResponse:
    """One round-trip response in canonical shape.

    Returned by every `DecisionClient.invoke()` implementation (concrete,
    rate-limited, file, or mock). Consumers must not depend on any field
    not listed here; the OpenAI-shaped raw response is intentionally
    discarded after `raw_response_id` is captured.
    """

    text: str                       # `choices[0].message.content`
    model_id_actual: str            # `response.model` — may differ from request
                                    # if OpenRouter internally routes
    input_tokens: int               # `usage.prompt_tokens`
    output_tokens: int              # `usage.completion_tokens`
    cost_usd: float                 # computed from pricing table (§5.4)
    raw_response_id: str            # `response.id` — opaque OpenRouter request ID
                                    # for cross-referencing in the OpenRouter
                                    # dashboard / support tickets


# --------------------------------------------------------------------------
# DecisionClient Protocol (the contract every consumer imports against)
# --------------------------------------------------------------------------

@runtime_checkable
class DecisionClient(Protocol):
    """Synchronous LLM client; one round-trip per call.

    The proxima `harness.decision_client.DecisionClient` is the lineage —
    this is the same Protocol surface, just typed against `OpenRouterResponse`
    instead of returning bare `str`. Consumers (spec 001, 007, 008, 010,
    011, 016) program against this Protocol; concrete dispatch is one of
    `OpenRouterClient`, `RateLimitedDecisionClient`, `FileClient`,
    `MockOpenRouterClient`.
    """

    def invoke(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        max_tokens: int = 4096,
        response_format: dict[str, object] | None = None,
    ) -> OpenRouterResponse: ...


# --------------------------------------------------------------------------
# Retry policy config
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff with jitter, capped at `max_retries`.

    Only applies to `TransientAPIError` subclasses (`OpenRouterRateLimitError`,
    `OpenRouterConnectError`). `OpenRouterAuthError`, `OpenRouterModelUnavailable`,
    `BudgetTokenUsageMissing`, and `OpenRouterError` are NOT retried.
    """

    max_retries: int = 3                  # additional attempts after the initial
    initial_delay_s: float = 0.2          # 200 ms, matches proxima `_BACKOFF_INITIAL_MS`
    backoff_factor: float = 2.0
    jitter_range: tuple[float, float] = (0.9, 1.1)
    rate_limit_sleep_s: float = 5.0       # for 429 specifically (FIX_PLAN §27.2 retry path)


# --------------------------------------------------------------------------
# Pricing table (loaded once at startup from config/pricing/openrouter.yaml)
# --------------------------------------------------------------------------

class PricingEntry(BaseModel):
    """One row of `config/pricing/openrouter.yaml` (FIX_PLAN §25.6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_per_1m_tokens_usd: float = Field(ge=0.0)
    output_per_1m_tokens_usd: float = Field(ge=0.0)


class PricingTable(BaseModel):
    """The 5-row hybrid pricing table (4 frontier council + Gemini Flash)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    models: dict[str, PricingEntry]                # OpenRouter ID → entry
    last_updated_iso: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    @classmethod
    def load(cls, path: Path) -> "PricingTable": ...

    def cost_usd(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Compute USD per FIX_PLAN §25.6. Raises `BudgetTokenUsageMissing`
        if `model` is not in the table."""


# --------------------------------------------------------------------------
# Concrete OpenRouter client
# --------------------------------------------------------------------------

class OpenRouterClient:
    """Concrete `DecisionClient` backed by `openai` SDK + base-URL override.

    Single instance is shared by every consumer via dependency injection
    (FIX_PLAN §27.2). Construct once at factory startup; pass through to
    council, gap miner, generator-verifier, RAG writer, surrogate, strategy
    archive.
    """

    def __init__(
        self,
        api_key: str | None = None,            # reads OPENROUTER_API_KEY if None
        *,
        base_url: str = "https://openrouter.ai/api/v1",
        http_referer: str | None = None,       # for OpenRouter ranking header;
                                               # default loaded from operator config
        pricing_table: PricingTable | None = None,   # default: load once
                                                     # from config/pricing/openrouter.yaml
        retry_policy: RetryPolicy | None = None,     # default: RetryPolicy()
        telemetry_sink: "TelemetrySink | None" = None,  # spec 014; optional
        timeout_s: float = 60.0,
    ) -> None: ...

    def invoke(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        max_tokens: int = 4096,
        response_format: dict[str, object] | None = None,
    ) -> OpenRouterResponse:
        """Dispatch one round-trip through OpenRouter.

        Raises:
            OpenRouterAuthError: HTTP 401. Non-retryable.
            OpenRouterRateLimitError: HTTP 429 after retries exhausted.
            OpenRouterConnectError: Network / DNS / 5xx after retries exhausted.
            OpenRouterModelUnavailable: HTTP 404 on the model ID. Non-retryable.
            BudgetTokenUsageMissing: 200 response lacks `usage` block, OR
                pricing table has no entry for `model`. Non-retryable.
            OpenRouterError: malformed response envelope. Non-retryable.
        """


# --------------------------------------------------------------------------
# Rate-limited wrapper (proxima `RateLimitedDecisionClient` lineage)
# --------------------------------------------------------------------------

class RateLimitedDecisionClient:
    """Wrap any `DecisionClient` with a process-wide token-bucket rate limiter.

    Per FIX_PLAN §27.2: the limiter is enforced at the synchronous `invoke`
    boundary so concurrent council deliberations, agentic code-gen calls,
    and surrogate OOD audits share a single budget without coordinating
    themselves. The token bucket replenishes at `rps` tokens per second
    with a capacity of `max(rps, 1.0)` so short bursts are allowed.

    This wrapper preserves the Protocol surface — wrapped clients are still
    `DecisionClient` instances and can be composed (e.g., a `FileClient`
    wrapped in a `RateLimitedDecisionClient` for tests that want both
    determinism AND rate-limit timing).
    """

    def __init__(self, inner: DecisionClient, *, rps: float = 5.0) -> None: ...

    def invoke(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        max_tokens: int = 4096,
        response_format: dict[str, object] | None = None,
    ) -> OpenRouterResponse: ...

    @property
    def inner(self) -> DecisionClient: ...

    @property
    def rps(self) -> float: ...


# --------------------------------------------------------------------------
# File-backed mock (proxima `FileClient` lineage — script_path on disk)
# --------------------------------------------------------------------------

class FileClient:
    """Replays a fixture transcript file from disk.

    Used by every consumer's mock-mode test. The transcript is a JSON file
    under `factory/llm_client/fixtures/transcripts/` with shape:

        {
          "model": "google/gemini-3.5-flash",
          "messages": [...],                  # echoed for debug only
          "response": {
            "text": "...",
            "model_id_actual": "google/gemini-3.5-flash",
            "input_tokens": 42,
            "output_tokens": 17,
            "cost_usd": 0.000034,
            "raw_response_id": "fixture-001"
          }
        }
    """

    def __init__(self, transcript_path: Path) -> None: ...

    def invoke(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        max_tokens: int = 4096,
        response_format: dict[str, object] | None = None,
    ) -> OpenRouterResponse:
        """Return the fixture's `response` field as an `OpenRouterResponse`.
        `messages`, `model`, `max_tokens`, `response_format` are discarded
        (no recording, no comparison) — `FileClient` is for deterministic
        replay only."""


# --------------------------------------------------------------------------
# Deterministic mock (for unit tests that want call-shape assertions)
# --------------------------------------------------------------------------

class MockOpenRouterClient:
    """Deterministic mock keyed off `(model, hash(messages))`.

    Unlike `FileClient`, this mock records calls so tests can assert the
    request shape (`assert mock.calls == [{"model": ..., "messages": ...}]`)
    and can be programmed with `responses` mapping for `(model, message_hash)
    → OpenRouterResponse`. Used in unit tests for spec 008 multi-turn loop
    and spec 001 council that need to inspect what the consumer sent.
    """

    def __init__(
        self,
        responses: dict[tuple[str, str], OpenRouterResponse] | None = None,
    ) -> None: ...

    def invoke(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        max_tokens: int = 4096,
        response_format: dict[str, object] | None = None,
    ) -> OpenRouterResponse: ...

    @property
    def calls(self) -> list[dict[str, object]]: ...
```

## 4. Data Structures / Schemas

**`OpenRouterResponse`** — the single canonical response shape (§3). `frozen=True` because every artifact at a module boundary in this factory is immutable per ARCHITECTURE.md §1.5. `raw_response_id` is captured so an operator can cross-reference a specific invocation against the OpenRouter dashboard's request log; the rest of the raw response envelope is discarded after `OpenRouterResponse` is constructed.

**`PricingTable`** — the 5-row hybrid pricing table loaded once at startup from `config/pricing/openrouter.yaml` per FIX_PLAN §25.6. The §24 `config/pricing/gemini.yaml` is dropped; `openrouter.yaml` is the canonical (and only) pricing file. Schema (Pydantic `extra="forbid"` so unknown keys raise):

```yaml
# config/pricing/openrouter.yaml (FIX_PLAN §25.6 verbatim)
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

**`RetryPolicy`** — frozen dataclass; the proxima `_BACKOFF_INITIAL_MS=200` and `_BACKOFF_FACTOR=2.0` are preserved verbatim. `rate_limit_sleep_s=5.0` matches the proxima Codex `_RATE_LIMIT_SLEEP` constant.

**Fixture transcript JSON** (`factory/llm_client/fixtures/transcripts/<name>.json`) — exact shape shown in `FileClient` docstring (§3). One file per fixture; checked into the repo because they are deterministic and small (each ≤ 4 KB).

**Telemetry event payloads** (per FIX_PLAN §8 namespacing, prefixed `factory.llm_client.`):
- `factory.llm_client.invoke_started` — `{request_id, model, message_count, max_tokens, response_format_kind}`
- `factory.llm_client.invoke_complete` — `{request_id, model, model_id_actual, input_tokens, output_tokens, cost_usd, raw_response_id, latency_ms}`
- `factory.llm_client.invoke_failed` — `{request_id, model, error_class, error_type, latency_ms, retry_attempt}`

## 5. Algorithms / Logic

### 5.1 `OpenRouterClient.invoke()` — one round-trip

1. Generate `request_id = uuid4()` and emit `invoke_started` telemetry event.
2. Build the OpenRouter call exactly as FIX_PLAN §25.2 prescribes:
   - `extra_headers = {"HTTP-Referer": self._http_referer, "X-OpenRouter-Title": "ai-co-computational-physicist"}`
   - `model = <argument>` (full `<vendor>/<model-id>` form; no implicit prefixing).
   - `messages = <argument>` (passed through verbatim; this module never mutates).
   - `max_completion_tokens = <max_tokens argument>` (default 4096). The `DecisionClient` surface keeps `max_tokens`; the OpenRouter wire request uses the current `max_completion_tokens` field.
   - `response_format = <argument>` (None / `{"type": "json_object"}` / `{"type": "json_schema", ...}`).
   - **No `temperature` / `top_p` / `top_k` override** — vendor defaults stand per FIX_PLAN §25.7.
3. Dispatch via `openai.OpenAI(base_url, api_key).chat.completions.create(...)`.
4. On exception, classify via §5.5 and either retry (§5.2) or raise.
5. On 200 response:
   - If `response.usage is None` OR `response.usage.prompt_tokens is None` OR `response.usage.completion_tokens is None` → raise `BudgetTokenUsageMissing(module="llm_client", model_id=<model>, description="usage block absent")`.
   - Compute `cost_usd = pricing_table.cost_usd(model=model, input_tokens=usage.prompt_tokens, output_tokens=usage.completion_tokens)`. If `model` is not in the table → raise `BudgetTokenUsageMissing(module="llm_client", model_id=model, description="pricing entry missing")`.
   - Construct `OpenRouterResponse(text=choices[0].message.content, model_id_actual=response.model, input_tokens=usage.prompt_tokens, output_tokens=usage.completion_tokens, cost_usd=cost_usd, raw_response_id=response.id)`.
   - Emit `invoke_complete` telemetry event.
   - Return.
6. Total latency is recorded on the `invoke_complete` event for cross-call analysis.

### 5.2 Retry / backoff (`RetryPolicy`)

For `attempt in range(1, max_retries + 1)`:

1. Run §5.1 dispatch.
2. On `OpenRouterAuthError` / `OpenRouterModelUnavailable` / `BudgetTokenUsageMissing` / `OpenRouterError` → **raise immediately**, no retry. Emit `invoke_failed` with `retry_attempt=attempt`.
3. On `OpenRouterRateLimitError` → sleep `rate_limit_sleep_s` (default 5.0 s — matches proxima Codex behavior) then continue the loop.
4. On `OpenRouterConnectError` → sleep `initial_delay_s × backoff_factor^(attempt-1) × jitter(jitter_range)` then continue the loop. Equivalent to proxima `_backoff_delay(attempt)`.
5. If the loop exhausts without success → raise the last-seen exception with retry-budget context (`"retries exhausted after N attempts"`) and emit `invoke_failed` with `retry_attempt=N`.

The retry budget is intentionally conservative (`max_retries=3` default vs. proxima Codex's 5) because OpenRouter is a thinner transport layer than the Codex OAuth proxy — the proxima 5-retry budget was tuned for SSE stream-mid failures that do not occur on OpenRouter's request/response REST surface. Operators may raise the budget via `RetryPolicy(max_retries=5)` if needed.

### 5.3 Rate limiting (`RateLimitedDecisionClient`)

Token-bucket implementation (process-wide, thread-safe):

1. State: `tokens: float`, `last_refill_at: float`, `capacity: float = max(rps, 1.0)`.
2. On `invoke()`:
   a. Acquire a lock (one bucket shared by all threads / call sites).
   b. Refill: `tokens = min(capacity, tokens + (now() - last_refill_at) × rps)`; `last_refill_at = now()`.
   c. If `tokens < 1.0` → release lock, sleep `(1.0 - tokens) / rps`, retry from (a).
   d. `tokens -= 1.0`; release lock.
   e. Delegate to `self._inner.invoke(...)` and return its result.
3. Errors from the inner client propagate unchanged — the wrapper does not retry or transform exceptions.

The proxima reference uses a `threading.BoundedSemaphore` for *concurrency* limiting; this module substitutes a token bucket for *rate* limiting because the dominant cost driver in the factory is per-second request volume against OpenRouter's account-tier RPS quota, not concurrency. A concurrency wrapper can be added later as a sibling without changing the Protocol surface.

### 5.4 Cost computation

Per FIX_PLAN §25.6, **exact formula**:

```python
cost_usd = (input_tokens  * entry.input_per_1m_tokens_usd  / 1_000_000) \
         + (output_tokens * entry.output_per_1m_tokens_usd / 1_000_000)
```

The pricing table is loaded **once** at process startup. Reload requires a process restart — operators editing `config/pricing/openrouter.yaml` mid-flight must restart the factory. This is intentional: a mid-flight price change would silently rewrite the budget arithmetic and is exactly the kind of invisible cost surprise the §25.6 explicit-pricing policy is meant to prevent.

If `response.usage` is None or missing either token count → raise `BudgetTokenUsageMissing` per §5.1 step 5. Never silently default to zero cost (FIX_PLAN §6.4).

### 5.5 Error classification

| Upstream condition | Exception class | Retryable? |
| :--- | :--- | :--- |
| HTTP 401 | `OpenRouterAuthError` | No |
| HTTP 429 | `OpenRouterRateLimitError(TransientAPIError)` | Yes (per §5.2) |
| HTTP 404 on model | `OpenRouterModelUnavailable` | No |
| HTTP 5xx (500 / 502 / 503 / 504) | `OpenRouterConnectError(TransientAPIError)` | Yes |
| `httpx.ConnectError` / `httpx.NetworkError` / DNS failure | `OpenRouterConnectError(TransientAPIError)` | Yes |
| `httpx.ReadTimeout` / `httpx.RemoteProtocolError` | `OpenRouterConnectError(TransientAPIError)` | Yes |
| 200 but `usage` block absent OR pricing entry missing | `BudgetTokenUsageMissing` | No |
| 200 but malformed envelope (no `choices`, missing `message`) | `OpenRouterError` | No |
| Any other 4xx (400 / 403 / 422) | `OpenRouterError` | No |

The classification is centralized in a single function `_classify_exception(exc: Exception) -> LLMClientError` so the same taxonomy is used by `OpenRouterClient`, `RateLimitedDecisionClient`, and tests.

### 5.6 Mock mode (`FileClient`)

1. `__init__(transcript_path)` reads the JSON file at construction time and validates its shape (raises `OpenRouterError` if malformed — caught at test setup, not at call site, so test failures point at the fixture).
2. `invoke(...)` returns the cached `OpenRouterResponse` regardless of arguments.
3. No telemetry events are emitted from `FileClient` — mocks must not pollute telemetry sinks in tests. The wrapping `RateLimitedDecisionClient` (if any) still emits its own bookkeeping.

`MockOpenRouterClient` is a richer mock: it records every call into `self._calls` so tests can assert `mock.calls[0]["model"] == "google/gemini-3.5-flash"` etc. Responses are looked up by `(model, sha256(json.dumps(messages, sort_keys=True)))`; missing key raises `OpenRouterError("mock has no programmed response for this (model, messages)")` so tests fail loudly on unprogrammed paths.

## 6. Failure Modes

| Error class | When it fires | Recovery action |
| :--- | :--- | :--- |
| `OpenRouterAuthError(LLMClientError)` | OpenRouter returns HTTP 401 (key invalid, revoked, or account quota exhausted at the OpenRouter account tier) | **Non-retryable.** Operator rotates `OPENROUTER_API_KEY` and verifies via `python -m factory.llm_client verify-key`. The state machine (spec 003) pauses on `OpenRouterAuthError` because every downstream LLM call would fail identically. |
| `OpenRouterRateLimitError(TransientAPIError)` | HTTP 429 (per-minute rate cap exceeded at the OpenRouter account tier) | Retry per `RetryPolicy.rate_limit_sleep_s` (default 5 s). If retries exhausted, propagate; the council / generator-verifier / writer caller handles per its own spec. |
| `OpenRouterConnectError(TransientAPIError)` | Network / DNS / TCP / `httpx.ConnectError` / `httpx.ReadTimeout` / `httpx.RemoteProtocolError` / HTTP 5xx | Retry per `RetryPolicy` with exponential backoff + jitter. If retries exhausted, propagate. |
| `OpenRouterModelUnavailable(LLMClientError)` | HTTP 404 on the requested model ID (catalog has moved, model retired, vendor prefix changed) | **Non-retryable.** Operator verifies the live catalog via `python -m factory.llm_client list-models` and updates `config/council/lineup.yaml` or the call site's hard-coded model string. |
| `BudgetTokenUsageMissing(LLMClientError)` | 200 response lacks `usage` block (or `prompt_tokens` / `completion_tokens` keys), OR `model` is not in `PricingTable` | **Non-retryable from this module.** Per FIX_PLAN §6.4 and spec 013 §6.4 the canonical recovery is in the budget tracker: the operation is parked, the ledger entry marks `tokens=0, cost_usd=0, description="parked: token usage missing"`, and the operator is paged. The factory does NOT default to $0 spend silently. |
| `OpenRouterError(LLMClientError)` | Any other failure: malformed envelope, unsupported `response_format`, HTTP 400 / 403 / 422, fixture file malformed | **Non-retryable.** Wraps the underlying `openai.OpenAIError` / `httpx.HTTPStatusError` with status code and error body for operator diagnosis. |
| `LLMClientError` | Catch-all base for the above | Caught by `factory.state_machine` per the per-error-type routing in spec 003 — this module does not define recovery itself. |

## 7. Testing

**REQUIRED — typical-usage test:** `factory/llm_client/tests/test_llm_client_typical_usage.py`. Construct a `FileClient(transcript_path=factory/llm_client/tests/sample_transcript.json)`, build messages, call `client.invoke(messages, model="google/gemini-3.5-flash")`, assert the `OpenRouterResponse` matches the fixture, and assert `cost_usd > 0`. Runs offline; no `OPENROUTER_API_KEY` required.

**Unit tests** (mock-mode, run in CI):
- `test_retry_backoff.py` — programmatically inject `OpenRouterConnectError` and `OpenRouterRateLimitError` on attempts 1–3, success on attempt 4; verify `RetryPolicy(max_retries=3)` succeeds; verify `max_retries=2` propagates. Verify `OpenRouterAuthError` is NOT retried (single attempt, immediate raise). Verify `OpenRouterModelUnavailable` is NOT retried.
- `test_rate_limiter.py` — `RateLimitedDecisionClient(MockOpenRouterClient(...), rps=2.0)`; fire 10 invocations from one thread; assert total wall-clock ≥ 5 s (10 calls / 2 rps). Fire 10 invocations from 4 threads concurrently; assert serialization is correct (total ≥ 5 s, no thread starvation).
- `test_cost_computation.py` — feed `PricingTable.cost_usd(model="google/gemini-3.5-flash", input_tokens=1_000_000, output_tokens=500_000)`; assert exact USD per FIX_PLAN §25.6 formula; verify missing model raises `BudgetTokenUsageMissing`.
- `test_error_classification.py` — exhaustively feed `_classify_exception` with each upstream condition in §5.5 table; assert the right class is raised and `is_retryable()` returns the right bool.
- `test_structured_outputs.py` — `MockOpenRouterClient` programmed with a JSON-mode response; verify `response_format={"type": "json_object"}` is passed through to the underlying `chat.completions.create(...)` call (assert via `mock.calls`); verify `response_format={"type": "json_schema", "json_schema": {...}}` is similarly passthrough.
- `test_token_usage_missing.py` — programmed response with `usage=None`; verify `BudgetTokenUsageMissing` raised with `module="llm_client"`, `model_id="<model>"`, `description="usage block absent"`. Programmed response with missing `prompt_tokens`; same. Programmed response 200 + valid `usage` but `model` not in pricing table; verify `BudgetTokenUsageMissing` with `description="pricing entry missing"`.
- `test_protocol_conformance.py` — `isinstance(OpenRouterClient(api_key="..."), DecisionClient)` and same for `RateLimitedDecisionClient`, `FileClient`, `MockOpenRouterClient` — verifies the `@runtime_checkable` Protocol is honored.
- `test_telemetry_events.py` — register an in-memory telemetry sink; one `invoke()` round-trip; assert `invoke_started` and `invoke_complete` were emitted with correct payloads; one failing round-trip; assert `invoke_failed` with `error_class`.
- `test_no_temperature_default.py` — verify `OpenRouterClient.invoke(...)` calls `chat.completions.create` WITHOUT a `temperature` argument (per FIX_PLAN §25.7); regression-guards against accidental default-temperature drift.

**Live-mode tests** (`@pytest.mark.live`, manual gate):
- `test_live_smoke.py` — one real call to `google/gemini-3.5-flash` with a trivial prompt ("Reply with the word OK."); assert `OpenRouterResponse.text` contains "OK"; assert `cost_usd > 0` and `cost_usd < 0.001` (sanity bound); assert `input_tokens > 0` and `output_tokens > 0`.

**Manual verification step** (one-time at setup, documented in `docs/runbooks/openrouter-client.md`):
- `python -m factory.llm_client verify-key` — hits `GET https://openrouter.ai/api/v1/key` with the configured key; reports rate limits and credit balance.
- `python -m factory.llm_client list-models` — hits `GET https://openrouter.ai/api/v1/models`; reports availability of all 5 canonical IDs from FIX_PLAN §25.3.
- `python -m factory.llm_client pricing-check` — diffs `config/pricing/openrouter.yaml` against the live catalog; flags rows where the catalog price has drifted from the local file beyond a configurable epsilon (default 5%).

## 8. Performance & Budget

- **Per-`invoke()` latency.** Dominated by upstream model latency: typically 1–3 s for `google/gemini-3.5-flash` agentic calls, 3–10 s for frontier council calls. Local overhead for this module is **<10 ms** end-to-end (request build + JSON serialize + response parse + cost compute + telemetry emit); the openai SDK + `httpx` add ~5–8 ms. The rate-limit wrapper adds bounded blocking when the bucket is empty (no CPU spin).
- **Rate-limit default.** `rps=5.0` per-process. Configurable per-deployment via the `RateLimitedDecisionClient(inner, rps=...)` constructor argument; operators typically raise this to 10–20 RPS in production once they have headroom on the OpenRouter account tier.
- **Cost accounting (per FIX_PLAN §25.6 + §25.8).** This module reports `cost_usd` per `OpenRouterResponse`; downstream consumers feed that into `BudgetTracker.record(cost_usd=...)` per spec 013. Aggregate cost expectations are owned by the council (≤$0.50 per deliberation per FIX_PLAN §25.8) and the generator-verifier (≤$0.005 per code-gen call per FIX_PLAN §25.8); this module does not enforce caps itself.
- **Memory.** The client holds one `openai.OpenAI` instance plus one `httpx.Client` socket pool. `OpenRouterResponse` objects are short-lived; no caching layer is shipped in Phase A.
- **Thread safety.** `OpenRouterClient.invoke()` is thread-safe (the underlying `openai.OpenAI` client is documented thread-safe at SDK ≥1.0). `RateLimitedDecisionClient`'s token-bucket is lock-protected per §5.3.

## 9. Open Questions

- **Native OpenAI `tools=` migration (Phase B).** OpenRouter passes the `tools=` schema through to underlying providers that support it. Spec 008's multi-turn agent loop currently uses ReAct text fences (FIX_PLAN §27.1) for parser stability across the heterogeneous council vendors; if Phase B narrows agentic calls to providers with reliable native tool-calling, this module would add a `tools=` keyword to `invoke()`. Deferred.
- **Model-failover policy if `google/gemini-3.5-flash` routes to a degraded provider.** OpenRouter may internally route a request to a slower or smaller-context provider for the same model ID. `OpenRouterResponse.model_id_actual` captures the resolved ID; if it materially drifts from the requested ID (e.g., quality regressions appear), Phase B may add an `allow_routing=False` flag that pins the request to the primary provider via OpenRouter's provider preferences. Deferred — not load-bearing for Phase A.
- **Per-model rate limits.** Currently one token bucket for all model calls. If `openai/gpt-5.5` saturates the per-account RPS independently of `google/gemini-3.5-flash`, a per-model bucket would isolate the failure modes. Adds bookkeeping; deferred until a real saturation event documents the need.
- **Caching layer.** No response cache in Phase A; every `invoke()` hits the network. Some council calibration probes are deterministic and could benefit from an LRU layer keyed off `(model, sha256(messages))`. Adds correctness questions (cache invalidation on pricing changes, transcript-vs-fresh divergence in audits); deferred.
- **Streaming responses.** The proxima Codex client streams SSE because the OAuth proxy returns delta events; OpenRouter supports streaming too. Phase A returns the full response after completion (lower latency variance, simpler error handling); streaming for UI live-rendering is a Phase B concern (spec 015).
- **`OpenRouter-Provider-Preferences` header.** OpenRouter accepts a routing-preferences header that constrains the underlying provider. Not used in Phase A; documented here so a future change can add the header without changing the Protocol surface.

## 10. TODO Checklist

- [ ] Scaffold `factory/llm_client/` from the canonical module template (`__init__.py`, `api.py`, `cli.py`, `tests/`, `fixtures/transcripts/`).
- [ ] Define the exception hierarchy in `factory/llm_client/api.py`: `LLMClientError(FactoryError)`, `TransientAPIError(LLMClientError)`, `OpenRouterAuthError(LLMClientError)`, `OpenRouterRateLimitError(TransientAPIError)`, `OpenRouterConnectError(TransientAPIError)`, `OpenRouterModelUnavailable(LLMClientError)`, `OpenRouterError(LLMClientError)`. Re-export `BudgetTokenUsageMissing` from `factory.budget` (canonical home per FIX_PLAN §6.4) so this module can raise it.
- [ ] Implement `OpenRouterResponse` frozen dataclass with all six fields from §3.
- [ ] Implement `DecisionClient` Protocol with `@runtime_checkable` decorator; signature `invoke(messages, *, model, max_tokens=4096, response_format=None) -> OpenRouterResponse`.
- [ ] Implement `RetryPolicy` frozen dataclass with defaults from §3 (`max_retries=3`, `initial_delay_s=0.2`, `backoff_factor=2.0`, `jitter_range=(0.9, 1.1)`, `rate_limit_sleep_s=5.0`).
- [ ] Implement `PricingEntry` and `PricingTable` Pydantic models with `ConfigDict(frozen=True, extra="forbid")`; `PricingTable.load(path)` reads `config/pricing/openrouter.yaml`; `PricingTable.cost_usd(...)` per FIX_PLAN §25.6 formula; raises `BudgetTokenUsageMissing` on missing model.
- [ ] Author `config/pricing/openrouter.yaml` skeleton with all 5 model rows from FIX_PLAN §25.3 (operator fills prices at setup).
- [ ] Implement `OpenRouterClient.__init__` reading `OPENROUTER_API_KEY` from environment when `api_key=None`; constructing `openai.OpenAI(base_url, api_key)`; loading default pricing table once; defaulting `http_referer` from operator config (`config/operator.yaml`).
- [ ] Implement `OpenRouterClient.invoke(...)` per §5.1 with full telemetry instrumentation (`invoke_started` / `invoke_complete` / `invoke_failed`) and ranking headers (`HTTP-Referer` + `X-OpenRouter-Title: ai-co-computational-physicist`). **No `temperature` / `top_p` / `top_k` override** per FIX_PLAN §25.7.
- [ ] Implement the centralized `_classify_exception(exc)` function per §5.5 table.
- [ ] Implement retry / backoff loop per §5.2; verify `OpenRouterAuthError` / `OpenRouterModelUnavailable` / `BudgetTokenUsageMissing` / `OpenRouterError` are NOT retried.
- [ ] Implement `RateLimitedDecisionClient` token-bucket per §5.3 (process-wide lock, configurable `rps`, blocking acquire); preserve Protocol surface so wrapped clients are still `DecisionClient` instances.
- [ ] Implement `FileClient(transcript_path)`: load + validate fixture at construction time (raise `OpenRouterError` on malformed); `invoke(...)` returns cached response without inspecting arguments; no telemetry emission.
- [ ] Implement `MockOpenRouterClient(responses=...)`: record calls into `self._calls`; lookup responses by `(model, sha256(json.dumps(messages, sort_keys=True)))`; raise `OpenRouterError` on missing key so tests fail loudly.
- [ ] Author fixture transcripts under `factory/llm_client/fixtures/transcripts/`: at minimum `sample_round_trip.json` (used by typical-usage test); plus per-error fixtures `auth_error.json`, `rate_limit.json`, `usage_missing.json`, `model_unavailable.json`.
- [ ] Write the REQUIRED `factory/llm_client/tests/test_llm_client_typical_usage.py`.
- [ ] Write the 9 unit tests listed in §7 (retry, rate limiter, cost, classification, structured outputs, token-usage-missing, protocol conformance, telemetry, no-temperature-default).
- [ ] Write `factory/llm_client/tests/test_live_smoke.py` gated behind `@pytest.mark.live` per §7.
- [ ] Write `factory/llm_client/cli.py` with `invoke`, `verify-key`, `list-models`, `pricing-check` subcommands; reachable as `python -m factory.llm_client <cmd>`. Each subcommand emits a single deterministic JSON object on stdout for downstream piping.
- [x] Write `docs/runbooks/openrouter-client.md` covering key rotation, catalog drift, pricing-table maintenance, rate-limit handling, and live council certification.
- [ ] Verify `mypy --strict factory/llm_client/` passes (no `Any`, no untyped `dict` at module boundary per ARCHITECTURE.md §1.5 + FIX_PLAN §14).
- [ ] Verify `python -m factory.llm_client invoke --fixture sample_round_trip --mock-mode` works on a fresh checkout with no env vars set.
- [ ] Acceptance grep: `grep -rn "ANTHROPIC_API_KEY\|OPENAI_API_KEY\|XAI_API_KEY\|GEMINI_FLASH\|GOOGLE_API_KEY\|pricing/gemini.yaml" specs/018-openrouter-client.md` returns zero hits (per FIX_PLAN §25.10).
- [ ] Update `INDEX.md` §2 (Component Specifications table) to list spec 018; update §3 dependency graph to show spec 018 as a leaf depended-on by 001 / 007 / 008 / 010 / 011 / 016.
