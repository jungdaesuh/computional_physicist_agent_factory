# Runbook: Council Calibration

> What this covers: how to calibrate the council lineup so it produces genuine disagreement (not sycophancy) before going live.
> When to use: PRD-002 acceptance gate; after any change to the model lineup, persona assignments, or chairman policy; when a `CouncilSycophancyDetected` error fires in production.
> Estimated time: 20-40 minutes (first run), 5-10 minutes (subsequent runs).

This is the **single most important early-validation gate of Phase A**. If the council does not produce useful disagreement on calibration probes, the entire factory architecture is invalidated and must be redesigned before continuing. See `prds/PRD-002-council-library.md` §10.

## 1. Prerequisites

- `factory` package installed (`uv sync` complete in repo root).
- A single LLM API key configured as an environment variable:
  - `OPENROUTER_API_KEY` — OpenRouter API key used by both the 4-vendor council and every agentic LLM call (FIX_PLAN §25.1, which **SUPERSEDES §24**). Legacy keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `XAI_API_KEY`, `GEMINI_FLASH`) are obsolete and must not be referenced as a fallback path.
  - Verify the key is valid before continuing:
    ```bash
    curl -sS -o /dev/null -w '%{http_code}\n' \
      https://openrouter.ai/api/v1/models \
      -H "Authorization: Bearer $OPENROUTER_API_KEY"
    ```
    A `200` response confirms the key reaches OpenRouter. Anything else (`401`, `403`, `5xx`) must be resolved before continuing — calibration depends on live vendor passthrough.
- A council lineup file: `config/council/lineup.yaml` carrying a `CouncilLineup` per FIX_PLAN §25.4. Required keys:
  - `models[]` — exactly 4 `ModelSpec` entries, one per vendor in FIX_PLAN §25.3:
    - `{openrouter_id: "openai/gpt-5.5", vendor: "openai", timeout_s: 60.0, max_tokens: 4096}`
    - `{openrouter_id: "anthropic/claude-opus-4.7", vendor: "anthropic", timeout_s: 60.0, max_tokens: 4096}`
    - `{openrouter_id: "google/gemini-3.1", vendor: "google", timeout_s: 60.0, max_tokens: 4096}`
    - `{openrouter_id: "x-ai/grok-4.3", vendor: "x-ai", timeout_s: 60.0, max_tokens: 4096}`
  - `persona_assignment` — mapping each model id → persona (`Visionary | Pessimist | Pragmatist`); the assignment must span ≥3 distinct personas. Rotation across cycles is permitted but the four vendors are fixed.
  - `chairman_policy` — `random | round_robin | weighted_by_cost`.
- `config/pricing/openrouter.yaml` populated with current OpenRouter passthrough input/output USD-per-1M token prices for all 5 model IDs (FIX_PLAN §25.6).
- The built-in probe set at `factory/council/calibration/probes.yaml` (or a custom path passed via `--probe-set`).
- Working internet connection to `openrouter.ai`.
- A modest budget envelope — calibration costs roughly 10× a single deliberation (one call per probe × 4 vendor calls × 3 stages). Under the restored 4-vendor lineup, typical wall is $2–$5 per calibration run (reverts §24's $0.50–$2 single-vendor envelope; the cost increase IS the defense).

If any prerequisite is missing, fix it before continuing. The runbook does NOT operate against mock-mode for calibration — calibration is meaningful only against the real lineup that will run in production.

> **Sampling-parameter policy.** Do NOT vary `temperature`, `top_p`, or `top_k` from provider defaults. Diversity comes from vendor heterogeneity + persona system instructions (the two orthogonal axes restored by FIX_PLAN §25.4); sampling-parameter knobs are not a calibration lever.

## 2. Steps

### 2.1 Verify the lineup is vendor- and persona-heterogeneous

```bash
python -m factory.council show-lineup
```

Expected: exactly 4 `ModelSpec` entries covering **all four vendors in FIX_PLAN §25.3** (`openai`, `anthropic`, `google`, `x-ai`), with `persona_assignment` spanning **≥3 distinct personas** (`Visionary`, `Pessimist`, `Pragmatist`). Both axes must be verified — the output prints both the vendor table and the persona assignment. If any vendor in §25.3 is missing, the lineup violates the heterogeneity invariant and calibration cannot pass. Edit `config/council/lineup.yaml` and re-check.

> **Two orthogonal diversity axes (load-bearing).** FIX_PLAN §25 restores the two-axis heterogeneity defense the §24 amendment retracted: (1) **vendor** — 4 distinct frontier vendors so no single RLHF / training distribution dominates; (2) **persona** — Visionary / Pessimist / Pragmatist system instructions further fracture responses orthogonally to the vendor axis. The disagreement-rate threshold returns to 0.40 (§2.5) precisely because both axes are active again.

### 2.2 Verify the four vendors are present and the personas span ≥3

```bash
python -m factory.council show-lineup --field vendors
python -m factory.council show-lineup --field personas
```

Expected:
- `--field vendors` lists exactly `{openai, anthropic, google, x-ai}` — no duplicates, no missing vendors, no other vendors. Vendor heterogeneity is the primary defense.
- `--field personas` shows the persona assigned to each vendor; the set of distinct personas across the 4 assignments is `≥ 3`. Typical assignments: `gpt-5.5 → Visionary`, `claude-opus-4.7 → Pessimist`, `gemini-3.1 → Pragmatist`, `grok-4.3 → Visionary` (or any permutation that respects the ≥3 span).

If either axis fails, edit `config/council/lineup.yaml` and rerun this check. Both axes must pass.

### 2.3 Run the calibration probe set

```bash
factory council calibrate
```

This runs the built-in probe set (≥10 divisive questions) against every `ModelSpec` in the configured lineup, then computes pairwise semantic similarity (cosine on embeddings) and produces a `CalibrationReport`. Each call is `chat.completions.create` against the vendor's model id via OpenRouter under the persona's `system_instruction`; sampling parameters use provider defaults (no temperature / top_p / top_k overrides — FIX_PLAN §25.7).

Expected output:

```
Probe 01: "Should constraint penalty parameters scale with violation norm?"   disagreement=0.52  OK
Probe 02: "Is exponential fidelity scheduling preferred over linear?"          disagreement=0.47  OK
Probe 03: ...
...
Overall disagreement rate: 0.46
Sycophancy flagged: false
Report written: runs/_calibration/<timestamp>/report.json
```

Under the 4-vendor lineup, per-probe values typically land in the 0.40–0.65 range; overall ≥ 0.40 is the acceptance floor.

### 2.4 Inspect the calibration report

```bash
python -m factory.council show-report --path runs/_calibration/<timestamp>/report.json
```

For each probe, the report contains:
- The question.
- The full response per `ModelSpec` (identified by `vendor + openrouter_id + assigned persona`).
- Pairwise disagreement scores across all 4 vendor responses.
- A short critique of which responses showed substantive vs. boilerplate disagreement.

Scan the report by hand for at least 3 probes. Look for **substantive** dissent — actual content disagreement, not "however"-style hedging. If every probe shows hedging without content disagreement, the calibration metric overstated the lineup's diversity even with 4 vendors active.

### 2.5 Interpret the disagreement-rate threshold

The PRD-002 acceptance gate requires **overall disagreement rate ≥ 0.40** (FIX_PLAN §25.4 restored this from §24's lowered 0.25, because the 4-vendor heterogeneity defense is back in force). Above this threshold, the lineup produces enough genuine disagreement to be useful as a judgment substrate.

- **≥ 0.40 — passes.** Continue to §2.6 to persist the calibration baseline.
- **0.30 – 0.40 — borderline.** Re-calibrate persona prompts (tighten the `Pessimist` `system_instruction`, sharpen Visionary vs. Pragmatist contrast). Consider **rotating persona–vendor pairings** in `persona_assignment` — some vendors handle the Pessimist persona more faithfully than others (e.g., Anthropic models often resist agreement framing more naturally; OpenAI models often soften adversarial framing). Inspect at least 5 probes by hand for substantive dissent and rerun §2.3. If after one re-calibration the rate clears 0.40, proceed; if it stays in `0.30–0.40` for two consecutive runs, treat as a deferred fail and flag in the postmortem.
- **< 0.30 — fail.** The configured lineup is unusable. Escalate per FIX_PLAN §25.4: the vendor lineup itself is deficient (one or more frontier models are collapsing into agreement with the others). Fix at the **config layer**, not at runtime — verify each `openrouter_id` is the latest frontier model from that vendor, audit whether any vendor's RLHF policy is flattening the assigned persona, and re-run calibration. Do not proceed to live operation. Silent threshold lowering is forbidden.

### 2.6 Persist the calibration baseline

```bash
python -m factory.council promote-calibration --path runs/_calibration/<timestamp>/report.json
```

This marks the report as the active baseline for sycophancy detection at runtime. The sycophancy threshold (default `max` pairwise cosine 0.85 in `Council.deliberate` per spec 001 §5.4 — restored from §24's lifted 0.92 single-vendor bump, FIX_PLAN §25.4) is anchored to this baseline; deviations are flagged as `CouncilSycophancyDetected` at runtime.

## 3. Verification

After §2.6, the calibration is "live." Verify by:

```bash
python -m factory.council deliberate \
  --council-id C1 \
  --question "Should we test the effect of an exponential fidelity schedule on convergence rate?" \
  --context-fixture sample_gap_candidate \
  --mock-mode false
```

Expected:
- Output is a `CouncilVerdict` with `chairman_decision ∈ {approve, reject, qualified, no_consensus}`.
- `preserved_dissents` is **non-empty** (otherwise sycophancy auto-fires and the deliberation is rejected).
- Total cost < $1, wall-clock < 90 s.
- The verdict file at `runs/<cycle-id>/councils/<session_id>.jsonl` is fully written and parses as JSON-Lines.

If `preserved_dissents` is empty and the calibration claimed disagreement-rate ≥ 0.40, the calibration probe set is not representative of typical production questions — extend the probe set with realistic questions from `docs/specs/001-council.md` §5.5 and recalibrate.

## 4. Troubleshooting

### 4.1 `CouncilSycophancyDetected` at calibration time

The lineup converged on the divisive probes — all four vendor calls agreed even though the probe was designed to produce disagreement.

Diagnosis: even with 4 frontier vendors, certain question shapes can trigger correlated alignment behavior (e.g., questions framed in a way that all RLHF stacks score similarly on "be helpful"). Common patterns:
- One vendor is **dominating** the others stylistically and the cosine similarity score is being driven by lexical convergence on its phrasing.
- The `Pessimist` persona is assigned to a vendor whose RLHF tuning resists adversarial framing more than the others.
- Persona prompts are too similar to each other — `Visionary` and `Pragmatist` converge on the same content.

Recovery (in order):
1. **Rotate persona assignments across the 4 vendors.** Try a permutation where the Pessimist sits on a different vendor (especially favor vendors known to engage adversarial framing — empirically Anthropic and xAI models are often stronger Pessimists than OpenAI's safety-tuned variants).
2. **Audit which model is dominating.** Read the calibration report's pairwise critique — if one vendor's responses are consistently the "closest" to every other vendor, that vendor is homogenizing the council. Consider whether its assigned persona is amplifying the homogenization (e.g., assigning Pragmatist to a vendor that already defaults to neutral framing produces double-neutrality).
3. **Strengthen the Pessimist persona prompt** (`factory/council/personas/pessimist.md`) with explicit framing like "your role is to identify failure modes and disconfirming evidence; agreement with the other voices on a divisive question is a failure mode of your role, not a virtue."
4. **Sharpen the persona prompts against each other** so each one carries distinct framing (Visionary: ambitious framing; Pessimist: failure-mode framing; Pragmatist: cost / tractability framing). Do not let them all read like "be helpful and balanced."
5. Rerun §2.3 calibration.
6. If after the above the overall disagreement rate is still below 0.30, the vendor lineup itself is the problem — verify each `openrouter_id` is the latest frontier model from its vendor and the 4 vendors in §25.3 are all present. Fix at the config layer per FIX_PLAN §25.4. Do not silently lower the threshold.

> **Do not** attempt to fix sycophancy by varying `temperature`, `top_p`, or `top_k`. Per FIX_PLAN §25.7 those parameters stay at provider defaults; diversity comes from the two orthogonal axes (vendor + persona). Do not silently substitute a different vendor for one in §25.3 — vendor heterogeneity IS the defense.

### 4.2 `PersonaRefusal` during calibration

One or more calls returned a meta-response refusing to inhabit the assigned persona (typically: "I can't argue in bad faith…").

Diagnosis: this is RLHF kicking in on a particular phrasing of the persona prompt for that specific vendor. Some RLHF-aligned models refuse adversarial framing more than others — most common when the Pessimist persona is assigned to an OpenAI or Google safety-tuned model.

Recovery:
1. **Rotate to a different persona on the same vendor first.** If `openai/gpt-5.5 → Pessimist` is refusing, try `openai/gpt-5.5 → Pragmatist` and shift Pessimist to a different vendor (e.g., `anthropic/claude-opus-4.7` or `x-ai/grok-4.3`). Persona-vendor pairing is configurable; the vendor lineup itself is fixed.
2. If the refusal persists across persona assignments, **mark that vendor unsuitable for the Pessimist persona** in `config/council/lineup.yaml` (operator-comment annotation; the persona–vendor pairing is then locked away from that combination for this lineup). Some RLHF-aligned models refuse adversarial framing more than others — that's a permanent property of the model, not a per-call accident.
3. As a last resort, rotate to a different persona prompt variant under `factory/council/personas/pessimist.<variant>.md` (e.g., reframe Pessimist as analytical peer reviewer rather than adversary). Variants are selected via the `system_instruction` field on the `ModelSpec` per FIX_PLAN §25.4.
4. **Do not silently substitute a different vendor** in the lineup — vendor heterogeneity per §25.3 is contractual.

### 4.3 Probe set produces only boilerplate disagreement

The metric says 0.46 but inspection shows all responses hedging without content disagreement.

Diagnosis: the embedding-based similarity metric overstated diversity because the calls used different vocabulary for the same position. Even with 4 vendors, frontier models can converge on the same content while diverging stylistically (especially on consensus topics where they share training data).

Recovery:
1. Manually edit `factory/council/calibration/probes.yaml` to include probes with sharper expected disagreement (binary methodological choices, contested physics interpretations).
2. Add 3-5 of your own domain-specific probes — questions where you (the operator) know there is genuine disagreement among experts.
3. Rerun §2.3 calibration.

### 4.4 OpenRouter rate limit on one vendor

A single upstream vendor (or OpenRouter's passthrough quota for that vendor) returned `429` or quota-exceeded for one of the 4 council models.

Recovery:
1. **Wait and retry** per the SDK's exponential backoff. Single-vendor outages are usually transient.
2. If the rate limit is persistent, **swap that vendor's model ID in `config/council/lineup.yaml`** for an equivalent within the **same vendor family** (e.g., `openai/gpt-5.5` → `openai/gpt-5.5-preview`, or `anthropic/claude-opus-4.7` → `anthropic/claude-opus-4.7-20260101`). The replacement must remain from the same vendor to preserve the 4-vendor heterogeneity invariant of FIX_PLAN §25.3.
3. **Never substitute a different vendor** for one in §25.3 — that retracts the defense by stealth.
4. Re-run calibration after the swap to confirm the new model id holds the disagreement threshold.

### 4.5 `ModelTimeout` on a single vendor

OpenRouter's passthrough for one vendor is slow or that vendor's upstream is throttling.

Recovery:
1. Re-check `timeout_s` on the offending `ModelSpec` (default 60 s; some structured-output prompts need 90-120 s; see https://openrouter.ai/docs for per-vendor latency expectations).
2. Stagger calibration to avoid hitting per-vendor daily quotas — the 4-vendor lineup spreads load but each vendor still has its own quota.
3. If timeouts persist on a single vendor, treat as §4.4 (rate limit) and swap to a same-family model id.

### 4.6 Calibration passes but production deliberations all return `chairman_decision="no_consensus"`

The probes were divisive but production questions are too well-defined; chairman synthesizes a clear majority without dissent.

Diagnosis: probe set isn't representative.

Recovery:
1. Re-curate the probe set with a mix of subjective and well-defined questions.
2. Set the sycophancy threshold higher (e.g., 0.90 instead of 0.85) to be more permissive at runtime.
3. Accept that calibration is a lower bound, not an upper bound — `no_consensus` decisions are valid outputs.

## 5. Related

- Spec backing this runbook: `docs/specs/001-council.md` (especially §5.4 sycophancy detection, §5.5 calibration probes).
- PRD: `docs/prds/PRD-002-council-library.md` (acceptance gate definition).
- Architectural defense context: `docs/SPEC.md` §10.1 (Sycophancy / groupthink).
- OpenRouter reference: https://openrouter.ai/docs
- Adjacent runbooks:
  - `docs/runbooks/first-cycle.md` — calibration is a prerequisite for the first cycle.
  - `docs/runbooks/ledger-audit.md` — C5 program-direction council uses the same calibration baseline.
  - `docs/runbooks/operator-cli.md` — reference for the operator `factory council calibrate` command. Other council subcommands (`show-lineup`, `show-report`, `promote-calibration`, `deliberate`) are per-module via `python -m factory.council` per FIX_PLAN §9.2.

> Calibration is not one-shot. Re-run after every lineup change, every persona-prompt edit, and at least quarterly even with a stable lineup. Sycophancy can drift as any of the 4 frontier vendors releases new model revisions; under the multi-vendor design the other 3 vendors typically absorb the drift, but the calibration cadence still matters because correlated alignment changes across vendors do occur.
