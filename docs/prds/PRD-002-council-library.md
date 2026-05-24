# PRD 002: Council Library v1 — Standalone Deliberation Engine

> Status: ☐ not started · Owner: TBD · Target: Week 2 of Phase A

## 1. Goal

Ship the council library as a standalone, testable Python module before any other component is wired. It must be possible to call `Council.deliberate(question, models, chairman, personas)` and receive a `CouncilVerdict` with preserved dissent, independent of the rest of the factory.

## 2. Why Now

Every per-cycle gate that involves judgment (C1, C2, C3, C4) and the slow-cadence program-direction loop (C5) depends on the council. Building it standalone first means:
- We can run sycophancy calibration before integrating, catching homogeneity issues at config time, not at first cycle.
- We can develop persona prompts in isolation with rapid iteration.
- Downstream specs can assume `Council.deliberate(...)` as a stable API.

If the council does not produce useful disagreement on calibration probes, **the entire factory architecture is invalidated** and we must redesign before continuing. This is the single most important early-validation gate.

## 3. User Journey

The "user" for this PRD is the *developer* of downstream components, not the operator. The developer wants to:

1. Install the library and export a **single** API key (`OPENROUTER_API_KEY`) for the OpenRouter-routed OpenAI-compatible SDK (FIX_PLAN §25, which **SUPERSEDES §24**).
2. Define a council lineup of **4 distinct vendors** routed via OpenRouter — `openai/gpt-5.5`, `anthropic/claude-opus-4.7`, `google/gemini-3.1-pro-preview`, `x-ai/grok-4.3` — each assigned a persona (Visionary / Pessimist / Pragmatist) from the configurable persona pool. The vendor lineup is fixed per FIX_PLAN §25.3; persona assignment per vendor is configurable per cycle.
3. Call `Council.deliberate(question="Is this gap worth experimenting on?", context=<GapCandidate>, council_id="C1")`.
4. Receive a `CouncilVerdict` JSON artifact with majority view, preserved dissents, chairman synthesis, persona lineup, and total cost.
5. Optionally, run `Council.calibrate(probe_set=BUILTIN_DIVISIVE_PROBES)` and receive a sycophancy report calibrated against the multi-vendor disagreement floor.

## 4. Success Metrics

| Metric | Threshold |
| :--- | :--- |
| Deliberation completes within 60s for typical question | yes |
| Cost per deliberation (4 frontier vendor calls + chairman + embeddings) | ≤ $0.50 |
| Preserved dissents are surfaced when ≥1 vendor or persona disagrees | always |
| Sycophancy probe: built-in divisive question set produces overall disagreement-rate ≥ 0.40 | yes |
| Anonymization survives the cross-review stage | verified by test |
| Chairman synthesis includes ≥1 dissent reference when dissent exists | always |
| Library is callable with one import; no factory dependencies | yes |

A council that **always agrees** on divisive probes fails this PRD and triggers redesign.

**Cost threshold rationale.** Four frontier models from four distinct vendors, called through OpenRouter at passthrough prices, are materially more expensive than the §24 single-vendor Gemini Flash design — and that cost is **intentional**. Vendor heterogeneity IS the sycophancy defense; collapsing to one model to save cost retracts the defense. Per FIX_PLAN §25.8 the per-deliberation ceiling is restored to **$0.50** (reverting §24's $0.10 target). The PRD-001 $50 per-hypothesis cap absorbs this; typical full cycles still land ≤ $5.

**Sycophancy threshold rationale (load-bearing tradeoff restored).** This PRD restores the **two orthogonal axes of diversity** the §24 amendment retracted: (i) **vendor heterogeneity** — 4 frontier models from 4 distinct vendors so no single RLHF tuning regime, no single training data distribution, and no single corporate alignment policy can flatten the council's disagreement signal; (ii) **persona heterogeneity** — Visionary / Pessimist / Pragmatist system instructions further fracture the response space orthogonally to the vendor axis. The acceptance threshold returns to **≥ 0.40** overall disagreement rate (reverting §24's lowered 0.25). The empirical floor is **0.30** — below that, persona prompts must be re-calibrated and persona–vendor pairings rotated; if calibration still produces less than 0.30 after that, the council is unusable as configured and the factory must redesign at the config layer (not silently lower the threshold). Defense weight is shared with the G4 validation portfolio (spec 009), but the council itself once again carries primary load. This is the deliberate reversal of §24's collapse to a single vendor.

## 5. Scope

### In scope (v1)

- Three-stage deliberation: First Opinions → Anonymized Cross-Review → Chairman Synthesis.
- OpenRouter-routed OpenAI-compatible SDK wrapper: **≥4 calls, one per vendor in §25.3 of FIX_PLAN** (`openai/gpt-5.5`, `anthropic/claude-opus-4.7`, `google/gemini-3.1-pro-preview`, `x-ai/grok-4.3`); persona assignment is configurable but the vendor lineup is fixed. Each call is a fresh `chat.completions.create` invocation — no shared chat history, no shared cache key — so stage 1 opinions remain mutually un-anchored.
- Persona prompt templates: Visionary, Pessimist (Reviewer 2), Pragmatist — applied as system instructions orthogonally to the vendor axis.
- `CouncilVerdict` output with `majority_view`, `preserved_dissents[]` (each `DissentEntry` carries its own `rationale` — no separate top-level `dissent_rationales[]` field), `chairman_decision`, `persona_lineup`, `total_cost`, `wall_clock`, `session_id`.
- Sycophancy calibration: `Council.calibrate(probe_set)` returning disagreement-rate per probe against the restored multi-vendor threshold (overall ≥ 0.40; empirical floor 0.30 triggers re-calibration; < 0.30 triggers redesign).
- Anonymization at stage 2 (persona identity stripped during cross-review; reviewers see "Voice A / B / C / D").
- Chairman rotation policy (`random` / `round_robin` / `weighted_by_cost`) over the persona × vendor pool.
- Session logging: every deliberation persisted to a local JSONL file for audit.
- Test suite: unit tests for parsing, integration tests against live OpenRouter (gated by `OPENROUTER_API_KEY`), plus mock-mode tests for offline CI.

### Out of scope (v1)

- Council UI rendering (deferred to UI backend spec 015).
- Embedding councils in the gate state machine (deferred to spec 003).
- C5 program-direction council (uses the same library but the cadence + state are in spec 003).
- Council learning from past deliberations (deferred to Phase B).

## 6. Deliverables

| Deliverable | Spec | Notes |
| :--- | :--- | :--- |
| `factory/council/` Python package with public `Council` class | `specs/001-council.md` | Pure library; no DB, no HTTP. |
| Persona prompt templates (3 files in `factory/council/personas/`) | `specs/001-council.md` | Markdown templates with placeholders. |
| OpenRouter-routed OpenAI-compatible SDK wrapper (`factory/council/openrouter_client.py`) | `specs/001-council.md` | Wraps `openai.OpenAI(base_url="https://openrouter.ai/api/v1", ...)` `chat.completions.create(...)` for the 4 council vendors + the agentic Gemini Flash default. Sampling parameters left at provider defaults per FIX_PLAN §25.7. Reads `OPENROUTER_API_KEY` from the environment; reads pricing from `config/pricing/openrouter.yaml`. |
| `CouncilVerdict` dataclass (referenced from spec 002) | `specs/002-artifacts.md` | Implements the artifact schema. |
| Pricing table `config/pricing/openrouter.yaml` with 5 model entries | `specs/013-budget-tracker.md` | Entries for `openai/gpt-5.5`, `anthropic/claude-opus-4.7`, `google/gemini-3.1-pro-preview`, `x-ai/grok-4.3`, and the agentic default `google/gemini-3.5-flash` (FIX_PLAN §25.6). |
| Calibration probe set (`factory/council/calibration/probes.yaml`) | `specs/001-council.md` | ≥10 divisive physics + meta-research questions. |
| CLI: `python -m factory.council deliberate --question ... --council-id C1 --context <file.json>` | `specs/001-council.md` | For dev iteration. |
| Test suite: pytest, ≥80% branch coverage on parsing + dispatch | `specs/001-council.md` | Mock mode for offline CI. |
| Documentation: usage README in `factory/council/README.md` | `specs/001-council.md` | Quick-start + example invocation. |

## 7. Risks & Mitigations

| Risk | Severity | Mitigation |
| :--- | :--- | :--- |
| **Council homogeneity (echo chamber).** Even with 4 distinct vendors, frontier models share enough training data and RLHF alignment patterns that disagreement can collapse on certain question shapes. | High | (a) **Vendor heterogeneity (primary)** — 4 distinct vendors from §25.3, no silent substitution on vendor failure; (b) **Persona heterogeneity (orthogonal)** — Visionary / Pessimist / Pragmatist system instructions further fracture responses along an axis independent of vendor; (c) **stage-1 isolation** — each call is a fresh `chat.completions.create` with no shared chat history or cache key; (d) **calibration gate** — `Council.calibrate` must clear the restored 0.40 disagreement threshold, with re-calibration trigger at 0.30 and full redesign trigger below 0.30 (FIX_PLAN §25.4). |
| **OpenRouter outage or rate limit on one vendor.** OpenRouter is the single networking surface; a single-vendor passthrough failure (or a global OpenRouter outage) can stall deliberation. | High | Fail the deliberation **loudly** — never silently substitute a different vendor. Raise `CouncilError` (with the failing vendor identified) and pause the cycle; the operator decides whether to retry, wait the outage out, or swap the failing vendor's model ID for an equivalent within the same vendor family (e.g., `openai/gpt-5.5` → `openai/gpt-5.5-preview`) at the config layer. Vendor heterogeneity IS the defense, so silent fallback to a third-party vendor would retract the defense by stealth. |
| Single vendor's RLHF flattens a given persona on a given probe | Medium | The other three vendors carry the persona axis independently; the chairman synthesis explicitly cites cross-vendor dissent. If one vendor consistently refuses the Pessimist framing across calibration probes, rotate that vendor away from Pessimist in the persona–vendor pairing config rather than dropping the persona. |
| OpenRouter rate limits or upstream vendor outages cascading | Medium | OpenAI-compatible SDK's built-in retries with exponential backoff via the `openai` package; per-call `timeout_s=60.0` on each `ModelSpec`; failed calls surface as `CouncilVendorTransient` and the cycle pauses rather than silently dropping calls. |
| Chairman synthesis collapses dissent | High | Chairman prompt explicitly requires citing ≥1 dissent if any exists; verdict schema enforces this at parse time. The chairman is one more `chat.completions.create` call routed to the chairman-policy-selected vendor (`random` / `round_robin` / `weighted_by_cost`). |
| Cost-per-deliberation balloons during iteration | Low | Per-deliberation budget enforced at the library level; cost surfaced in the returned `CouncilVerdict` via the single `config/pricing/openrouter.yaml` table covering all 5 model IDs. Typical deliberation lands at ≤ $0.50 per FIX_PLAN §25.8. |

## 8. Acceptance Criteria

PRD-002 closes when **all** of:

- [ ] `factory/council/` package installs cleanly with `uv sync` or `pip install -e .`, exposing the OpenRouter-routed `factory/council/openrouter_client.py` wrapper.
- [ ] `python -m factory.council deliberate ...` CLI runs end-to-end against live OpenRouter (reading `OPENROUTER_API_KEY` from the environment) and returns a parsed `CouncilVerdict`.
- [ ] `python -m factory.council certify-live --cost-cap-usd 0.50` runs all four frontier vendors live, records budget entries for every LLM call, and proves a missing-model provider failure raises loudly.
- [ ] `python -m factory.council calibrate` runs on the built-in probe set against the 4-vendor lineup and produces a disagreement report.
- [ ] **Heterogeneity check.** The configured lineup contains ≥4 `ModelSpec` entries, **one per vendor in FIX_PLAN §25.3** (`openai`, `anthropic`, `google`, `x-ai`), with persona assignments spanning ≥3 distinct personas (`Visionary`, `Pessimist`, `Pragmatist`). Verified by a config-validation test that fails the build if the vendor lineup is incomplete or the persona span is less than 3.
- [ ] **Threshold check.** Calibration on the built-in probes plus ≥5 operator-supplied domain probes returns an overall disagreement-rate ≥ 0.40. A rate in `0.30–0.40` triggers persona-prompt re-calibration (and optionally a rotation of persona–vendor pairings). A rate below 0.30 fails PRD-002 and the redesign trigger fires (FIX_PLAN §25.4).
- [ ] At least one calibration probe surfaces *substantive* dissent (not boilerplate "however"-style hedging) — verified manually.
- [ ] Test suite passes in mock mode in CI.
- [ ] At least one chairman synthesis correctly cites a preserved dissent.
- [ ] Library has been called from at least one downstream stub (e.g., a placeholder C1 worthiness call) without modification.

## 9. Linked Specs

- `specs/001-council.md` — full implementation spec.
- `specs/002-artifacts.md` — `CouncilVerdict` schema.

## 10. Next milestone after this

Once PRD-002 ships, the immediate next consumers are:
- C1 Worthiness wired into the gate state machine (spec 003).
- Gap Miner stub uses C1 to filter `GapCandidate`s (spec 007).

If PRD-002 fails calibration, the entire program pauses to redesign the deliberation substrate. This is the single biggest go/no-go check in Phase A.
