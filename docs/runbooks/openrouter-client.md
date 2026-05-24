# Runbook: OpenRouter Client And Live Council Certification

> What this covers: verifying the shared OpenRouter client, pricing table, four-vendor council path, budget attribution, and loud provider-error behavior before a production gate run.
> When to use: after setting or rotating `OPENROUTER_API_KEY`, after changing `config/council/lineup.yaml`, after refreshing `config/pricing/openrouter.yaml`, or before claiming the council path is production-live.

OpenRouter is the single LLM transport for Phase A. Official OpenRouter docs describe Bearer-token authentication against `https://openrouter.ai/api/v1/chat/completions`, model selection through the `model` field, JSON response formatting through `response_format`, and explicit error statuses including `401`, `404`, `429`, and `5xx`.

References:
- https://openrouter.ai/docs/api/reference/authentication
- https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request
- https://openrouter.ai/docs/guides/features/structured-outputs

## 1. Preconditions

Run from the repository root.

```bash
uv sync
export OPENROUTER_API_KEY=...
```

Do not set vendor-specific fallback keys. The factory uses only `OPENROUTER_API_KEY`.

Verify the key and catalog:

```bash
uv run python -m factory.llm_client verify-key
uv run python -m factory.llm_client list-models
uv run python -m factory.llm_client pricing-check
```

Expected:
- `verify-key` prints one deterministic JSON object with `"status": "ok"`.
- `list-models` includes every configured model in `config/council/lineup.yaml`.
- `pricing-check` reports no drift for the configured OpenRouter pricing table.

## 2. Live Council Certification

Run the production certification command:

```bash
uv run python -m factory.council certify-live --cost-cap-usd 0.50
```

This command performs all required production checks in one live run:
- Loads `config/council/lineup.yaml` and refuses to run unless exactly four frontier vendors are configured: `openai`, `anthropic`, `google`, and `x-ai`.
- Runs a real three-stage council deliberation through OpenRouter with all four configured models.
- Opens a `BudgetTracker` hypothesis, reserves the gate budget, records actual per-call spend from the live usage blocks, and closes the hypothesis.
- Emits a certification artifact under `runs/live_council_certifications/<timestamp>/certification.json`.
- Probes a real missing-model error path and requires `OpenRouterModelUnavailable`.

Required success signals in stdout and `certification.json`:

```json
{
  "status": "passed",
  "lineup_vendor_count": 4,
  "cost_within_cap": true,
  "session": {
    "stage1_response_count": 4,
    "stage2_response_count": 4,
    "stage3_response_count": 1
  },
  "budget": {
    "budget_entry_count": 9
  },
  "error_path": {
    "status": "passed",
    "exception": "OpenRouterModelUnavailable"
  }
}
```

`budget_entry_count` can exceed `9` when the chairman dissent validator requires one re-prompt. It must not be below `9`.

## 3. Failure Handling

If one vendor fails during Stage 1 or Stage 2, the council command must fail loudly with the failing model identified. Do not edit the session log to remove the failed vendor, do not lower the vendor count, and do not substitute a different vendor family.

For `OpenRouterModelUnavailable`, verify the live catalog:

```bash
uv run python -m factory.llm_client list-models
```

Then update the configured model ID in `config/council/lineup.yaml` within the same vendor family.

For `OpenRouterRateLimitError`, wait for account headroom and rerun. Persistent limits should be handled by account-tier changes or lower operator concurrency, not by changing the four-vendor invariant.

For `OpenRouterAuthError`, rotate `OPENROUTER_API_KEY`, restart the process, and rerun `verify-key` before any gate.
