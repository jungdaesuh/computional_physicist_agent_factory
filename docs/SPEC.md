# AI Co-Computational Physicist Factory: Specification

## 0. What This Document Is

This is the canonical specification for an autonomous research factory that:
1. Mines literature for falsifiable hypotheses worth experimenting on.
2. Selects an appropriate open-source simulator from a curated catalog.
3. Executes a bounded experiment via a generator-verifier code loop.
4. Validates results with a deterministic physics + statistics portfolio.
5. Emits internally-published evidence (with a human gate before any external release).

This document is intentionally reference-free. It is derived from a separate reference/provenance draft; implementation authority lives here and in `docs/specs/*.md`.

The factory is **not** a "general physics AGI." It is a stateful research loop, bounded by a curated catalog of open-source simulators and a small set of explicit failure-mode defenses. Anything it cannot do, it must refuse cleanly.

---

## 1. Core Principles

1. **Council = judgment gate, never the brain.** Multi-LLM deliberation handles subjective decisions (worthiness, design, claim interpretation, peer review). It never overrules a deterministic physics, statistics, or code-execution check.
2. **Deliberated decisions preserve dissent.** Consensus collapses information. A minority view that flagged a real flaw must survive into the final verdict.
3. **Typed artifacts over pipeline diagrams.** The factory is a state machine over a small set of immutable typed artifacts. Crashes are recoverable; cycles are resumable.
4. **Open-source simulator catalog is the substrate.** The factory is only as broad as its curated `SimulatorCatalog`. Nothing is simulated outside the catalog.
5. **Cheap probe before expensive simulation.** Tractability dry-run → surrogate → physics-light → full-fidelity oracle. The ladder is mandatory.
6. **Internal autonomy ≠ external autonomy.** Internal `EvidenceLedger` updates are unsupervised. arXiv, preprints, or any outside-world emission require a human gate.
7. **Negative results are first-class outputs.** Falsified hypotheses produce an internally-published `RunReport`. Re-litigation is permitted only with new evidence (simulator updated, surrogate retrained, etc.).
8. **Provenance everywhere.** Every artifact carries content hashes for code, env, input, seed, simulator version, and council lineup. Internal findings without provenance do not feed back into hypothesis generation.

---

## 2. Typed Artifacts (Single Source of Truth)

All persistent state lives in thirteen typed artifacts, versioned JSON with content hashes.

| Artifact | Purpose | Key fields |
| :--- | :--- | :--- |
| `GapCandidate` | A literature-derived candidate research direction | `gap_type` ∈ {structural_hole, methodology_transfer, contradiction, negative_result}; `source_papers[]`; `confidence`; `provenance_hash` |
| `HypothesisSpec` | Concretized, falsifiable hypothesis | `if_then`; `measurable_metric`; `expected_effect_size`; `kill_criteria`; `parent_gap_id` |
| `CouncilVerdict` | Output of a council deliberation | `majority_view`; `preserved_dissents[]`; `chairman_decision`; `model_lineup`; `persona_assignment` |
| `ExperimentSpec` | Concrete experimental design | `simulator_id` (from Catalog); `control_definition`; `fidelity_ladder[]`; `seed_set[]`; `success_metric`; `kill_criteria` |
| `Budget` | Per-hypothesis resource envelope | `dollar_cap`; `wall_clock_cap`; `token_cap`; `iteration_cap`; `running_ledger` |
| `DomainScope` | Currently allowed simulator families and physics regimes | `allowed_domains[]`; `allowed_simulator_ids[]`; `expansion_criteria` |
| `EvidenceLedgerEntry` | Persistent record of all results | `hypothesis_id`; `result` ∈ {passed, falsified, intractable, inconclusive}; `provenance`; `uncertainty`; `relitigate_if[]`; `surprise_bits` (spec 016, NULL until scored) |
| `RunReport` | Per-experiment artifact for internal publication | LaTeX source; figures[]; BibTeX from Paper Store; embedded `CouncilVerdict`s |
| `ValidationResult` | Output of the G4 validation portfolio | `experiment_hash`; `per_check_outcomes[]`; `aggregate_outcome` ∈ {pass, fail, inconclusive}; `cross_simulator_present` |
| `SurrogateProbeResult` | Output of the G3 surrogate cheap-probe | `candidate_hash`; `surrogate_id`; `predicted_metric`; `ood_flag`; `escalate_to_oracle` |
| `FactoryControlEvent` | Operator mutation entering the running factory | `event_type` ∈ {pause, resume, approve, reject, halt}; `target_ref`; `actor`; `rationale` |
| `Strategy` | Persistent strategy node in the Strategy Archive (spec 016) | `sha`; `summary_md`; `kind` ∈ {novel, mutate, crossover, library}; `parent_shas[]`; `reward_ema`; `surprise_ema`; `feasibility_distance_ema`; `feasible_count`; `visits`; `behavior_descriptor`; `provenance` |
| `StrategyCycleEvidence` | Per-cycle outcome attribution for a strategy node (spec 016) | `strategy_sha`; `cycle_id`; `best_objective`; `best_feasibility_distance`; `feasible_count`; `constraint_overshoots` |

Everything else (UI, orchestration scaffolding, transient state) is non-persistent.

The Strategy Archive (spec 016) is the **what-to-try-next substrate**: it tracks every attempted operator family with Bayesian-surprise + reward + feasibility EMAs and ranks lineages via UCT for the Generator-Verifier loop. The Fidelity Ladder Scheduler (spec 017) is the runtime traversal of `ExperimentSpec.fidelity_ladder` — distinct from the per-run `Discretizer` ABC, it decides *which run* is next on the ladder. See `FIX_PLAN.md §26` for the lock-in rationale.

---

## 3. Council Protocol

### 3.1 Council composition

> §25 SUPERSEDES §24: the single-vendor Gemini constraint is retracted. Council heterogeneity is restored along two orthogonal axes — vendor + persona — routed through OpenRouter.

- **Call count and vendor lineup.** Exactly 4 independent calls per deliberation, one per vendor, via OpenRouter:
  - `openai/gpt-5.5`
  - `anthropic/claude-opus-4.7`
  - `google/gemini-3.1-pro-preview`
  - `x-ai/grok-4.3`

  Each call uses a fresh OpenAI-compatible `chat.completions.create` invocation with no shared chat history. A failure of any single vendor falls back to raising `CouncilError`; there is no silent substitution because vendor heterogeneity IS the defense. See `FIX_PLAN.md §25.3`.
- **Two diversity axes.** Diversity is restored along **vendor** (four distinct frontier providers) **and** **persona** (system-instruction role). Persona assignment to the 4 vendors can rotate per cycle (random / round-robin / weighted), but the four vendors are fixed. Personas remain:
  - **Visionary** — argues why the hypothesis / design / claim is impactful.
  - **Reviewer 2 (Pessimist)** — argues only failure modes, gaps, methodological holes.
  - **Pragmatist** — evaluates implementation cost, tractability, calendar realism.

  Persona is a stage-1 role prompt, orthogonal to (and compatible with) stage-2 anonymization that hides call identity during cross-review. Random chairmanship per session, drawn from the persona set, avoids framing bias toward any single persona. See `FIX_PLAN.md §25.3` and `FIX_PLAN.md §25.4`.

### 3.2 Three-stage deliberation protocol

1. **First Opinions.** Each vendor model answers once under its assigned persona.
2. **Anonymized Cross-Review.** Each response critiques and ranks the others' outputs with model identity stripped.
3. **Chairman Synthesis.** Chairman model produces a `CouncilVerdict` with **preserved dissent** — minority views and their rationale must survive into the verdict. A scalar Go/No-Go output is forbidden.

### 3.3 The five councils

Four per-cycle gates plus one slow-cadence program-direction loop.

| Council | When | Decides |
| :--- | :--- | :--- |
| C1 — Worthiness | After Gap Miner emits `GapCandidate`s | Rank candidates on novelty × tractability × falsifiability × significance |
| C2 — Experimental Design | After Hypothesis Refiner emits `HypothesisSpec` | Approve `ExperimentSpec`: simulator choice, control, fidelity ladder, metrics, kill criteria |
| C3 — Claim Interpretation | After validation portfolio passes | Strongest defensible claim from the evidence, or explicit null |
| C4 — Peer Review | Before `RunReport` finalization | Publishable / falsified / weak; flag for G6 human gate if external |
| C5 — Program Direction | Weekly cadence over `EvidenceLedger` | Retire saturated gap-clusters; expand or contract `DomainScope`; spot-check internal findings |

### 3.4 What councils never decide

- Conservation residuals or other physics invariants.
- Numerical convergence below tolerance.
- Statistical significance tests.
- Code compilation, unit-test outcomes, container build success.

These are deterministic, with hard checks. A council that votes on whether $\nabla\!\cdot\!\mathbf{B} = 0$ is expensive hallucination by quorum.

---

## 4. Hard Gates

Gates run in strict order. No gate is skipped; a failure routes to a documented recovery path, not retry.

- **G0 — Domain check.** Hypothesis must lie within current `DomainScope`. Out-of-scope hypotheses park in `parked_for_scope_expansion`, reviewed by C5.
- **G1 — Falsifiability filter.** `GapCandidate` must convert to: `gap → falsifiable hypothesis → measurable metric → available simulator/data → baseline → stop condition`. Citation-graph holes are not automatically scientific gaps. Failures are discarded with a brief rationale.
- **G1.5 — Simulability filter.** `SimulatorSelector` must return ≥1 OSI-licensed simulator from the Catalog with a known-working container recipe that can compute the hypothesis's metric. Failures route to `parked_for_lack_of_tooling`.
- **G2 — Worthiness council (C1).** Chairman verdict + preserved dissent. A majority-approved hypothesis with substantive minority objection enters a "qualified approval" track requiring an intensified G4 portfolio.
- **G2.5 — Tractability filter.** One-iteration dry-run of the proposed solver mutation on a toy problem. Static analysis alone is forbidden (halting-problem trap). If the dry-run cannot produce *any* valid output within the iteration budget, the hypothesis is marked `intractable` and rolled back via the staging / atomic-promote pattern.
- **G3 — Cheap-probe gate (surrogate-first).** Mutation must beat the relevant baseline on a learned surrogate model (random forest, MLP, or successor) for the target observables. **OOD detection on surrogate inputs is mandatory:** an out-of-distribution candidate cannot earn a surrogate pass; it must escalate directly to oracle.
- **G4 — Validation portfolio.** All of the following must pass:
  - Physics invariance: conservation residuals, $\nabla\!\cdot\!\mathbf{B} = 0$, $W_{MHD}\ge 0$, etc.
  - Numerical convergence below the pre-registered tolerance.
  - Convergence under grid / mesh refinement (Richardson extrapolation where applicable).
  - Symmetry and limiting-case tests held out from code-gen visibility.
  - Statistical validity: per-seed variance, error bars, no cherry-picking — only the metric pre-registered in `ExperimentSpec` may be reported.
  - **Cross-simulator check** when the Catalog supports it for the observable; otherwise the portfolio is weighted heavier on refinement and symmetry.
- **G5 — Claim Interpretation (C3) + Peer Review (C4).** Result is internally published to `EvidenceLedger`.
- **G6 — Human approval.** Required for and only for external publication (arXiv, blog, citation outside the factory). Internal `EvidenceLedger` updates are unsupervised.

---

## 5. Simulator Catalog and Selector

The factory is simulator-agnostic in intent. In implementation, every simulator must live in the curated `SimulatorCatalog`. This is the most-underestimated component of the design.

### 5.1 Catalog entry requirements

Each entry is a machine-readable manifest containing:

- **License.** OSI-approved (MIT, BSD-{2,3}, Apache-2.0, GPL-{2,3}, LGPL, MPL-2.0, ISC, etc.). *All required runtime dependencies* must also be OSI-approved or freely redistributable inside a container. "Free for academic use," "registration required," or proprietary auxiliary data (e.g., gated DFT pseudopotentials) disqualify entry.
- **Domain & capabilities.** What physics / observables it computes, with explicit limits.
- **I/O schema.** Input file format, configuration DSL, output format (HDF5 / NetCDF / raw).
- **Container recipe.** Docker / Apptainer base image + install steps + **smoke-test target** (a known-good problem with known output, used as a build-verification probe).
- **Dependency graph.** MPI flavor, BLAS variant, CUDA version (if any), compiler version, OS family.
- **Maintenance signal.** Last commit ≤ 24 months *or* explicit upstream stable-release tag.
- **Known pathologies.** Domain-specific failure modes (e.g., stellarator equilibrium codes struggle near rational surfaces; DFT SCF non-convergence often indicates charge sloshing).
- **Cross-simulator equivalence map.** Which observables can be cross-validated against which other Catalog entries.

### 5.2 SimulatorSelector

Given a `HypothesisSpec`, returns:
- Ranked candidate simulators with compatibility score.
- Estimated cost (compute, wall-clock, container build time).
- Whether ≥2 simulators can compute the observable (enables G4 cross-simulator check).
- Failure mode: "no available open-source simulator can test this hypothesis" → kills at G1.5.

### 5.3 Domain adapter layer

The Generator-Verifier loop targets an abstract solver interface defined by the project — a small set of pluggable modules covering discretization / fidelity, boundary handling, update operator, acceptance and globalization, restart logic, and local polishing. Each Catalog entry provides an adapter that translates the abstract interface into that simulator's actual API / config format. This isolates code-gen from per-simulator quirks; adding a simulator is *writing an adapter*, not re-prompting the code-gen.

### 5.4 Catalog growth policy

- **Phase A** — human-curated; ~5–10 entries.
- **Phase B** — human-approved onboarding workflow. The factory proposes a candidate entry (manifest + container recipe + smoke test); a human approves before activation. Same pattern as package-registry onboarding.
- **Phase C** — autonomous onboarding from upstream documentation. Open research, not engineering.

"Anything open-source" is an intent statement. Catalog size is the practical limit. Honest framing of this asymmetry is required upfront.

---

## 6. Literature Discovery (Phase 0)

The factory treats literature research as a bounded, read-only discovery stage. The goal is not to crawl the academic graph; it is to surface the smallest high-value paper set that grounds the hypothesis, identifies missing baselines, and extracts method constraints.

### 6.1 Pipeline

```
User seed prompt / open-problems registry
  → query generation
  → candidate seed-paper search via public bibliographic APIs
  → citation-graph expansion via OpenAlex
  → paper ranking & deduplication
  → PDF/OCR only for promoted papers
  → schema extraction into Evidence Store
  → GapCandidate emission for the Gap Miner
```

### 6.2 OpenAlex as graph layer

OpenAlex provides the paper graph edges; the factory implements the traversal. In OpenAlex Works:

- **Backward citation traversal** uses `referenced_works` (works cited by the current paper).
- **Forward citation traversal** uses `/works?filter=cites:<work_id>`.
- **Batch frontier fetches** use `/works?filter=openalex:W1|W2|W3&per_page=100`.
- `related_works` may be used as a semantic-neighbor signal, but is stored as a *non-citation* edge.

### 6.3 Components

1. `OpenAlexClient` — typed API wrapper for `get_work`, `search_works`, `get_backward_references`, `get_forward_citations`, and `batch_get_works`.
2. `OpenAlexGraphStore` — local cache for works, edges, traversal runs, scores, and links to evidence records. Kept *separate* from any internal experiment table — external paper nodes are not run-provenance anchors.
3. `TraversalEngine` — bounded BFS or priority-BFS with explicit `max_depth`, `max_nodes`, `branch_factor`, `max_pages`, and wall-clock limits.
4. `PaperRanker` — relevance, citation count, recency, OA-PDF availability, graph role (bridge / seminal / extension), and diversity / MMR scoring before any PDF or OCR work.

### 6.4 Agent-facing tool surface

| Tool | Purpose |
| :--- | :--- |
| `openalex_seed_search(query, filters)` | Find seed OpenAlex works for a research question. |
| `openalex_expand(work_id, direction, limit)` | Inspect one hop of backward or forward citation edges. |
| `openalex_traverse(seed_ids, policy)` | Run a bounded traversal with a stored policy; return a compact run ID. |
| `openalex_graph_summary(run_id)` | Summarize bridge papers, seminal ancestors, recent extensions, gaps. |
| `promote_papers_to_paper_store(work_ids)` | Move selected works into PDF/OCR + evidence extraction. |

### 6.5 Example traversal policy

```yaml
literature_discovery:
  provider: openalex
  max_depth: 2
  max_nodes: 500
  branch_factor:
    backward: 20
    forward: 20
  filters:
    type: article
    is_oa: true
    publication_year_min: 2015
  scoring:
    relevance_weight: 0.45
    citation_weight: 0.20
    recency_weight: 0.15
    oa_pdf_weight: 0.10
    bridge_weight: 0.10
  promote_top_k_to_evidence_store: 25
```

### 6.6 Hard boundary

```
Literature informs HOW to search.
Experiment DB informs WHERE to search.
```

OpenAlex output can justify method choices, baselines, constraints, simulator choices, and novelty gaps. It cannot justify concrete simulator parameter values unless those values were extracted from a paper with evidence links, or came from the local experiment database.

OpenAlex references (public API):
- Works citation links: https://developers.openalex.org/guides/recipes
- Works listing, filters, pagination, field selection, and API key: https://developers.openalex.org/api-reference/works/list-works

### 6.7 Output

The Gap Miner converts ranked literature + evidence into `GapCandidate` artifacts, which then enter the gate sequence at G0.

---

## 7. Generator-Verifier Loop

A multi-turn agent loop with a sandboxed code-execution layer, a staging directory, and atomic promotion. The factory layer sits above this loop; the loop is responsible only for proposing code, executing it in the sandbox, and either promoting candidates atomically or rolling back.

```
       ┌────────────────────────────────────────────────┐
       │  Code-gen agent proposes solver-blueprint code │
       │  (targeting the abstract solver interface)     │
       └─────────────────────┬──────────────────────────┘
                             ▼
       ┌────────────────────────────────────────────────┐
       │  Execute in physics sandbox via domain adapter │
       └─────────────────────┬──────────────────────────┘
                             │
            ┌────────────────┴────────────────┐
            ▼ syntax / runtime / shape error  ▼ runs successfully
   ┌─────────────────────┐         ┌─────────────────────────┐
   │ Debugger intercepts │         │ Validation portfolio    │
   │ traceback           │         │ (G4) checks invariants, │
   └──────────┬──────────┘         │ convergence, symmetry   │
              │                    └────────────┬────────────┘
              ▼                                 ▼
   ┌─────────────────────┐         ┌─────────────────────────┐
   │ Loop back: correct  │         │ Promote to EvidenceLedger│
   │ and rewrite code    │         │ via atomic-promote       │
   └─────────────────────┘         └─────────────────────────┘
```

Factory-layer enforcement on top of the loop:

- **Iteration budget.** Maximum 10 generator-verifier iterations per `HypothesisSpec`. Hard cap from the `Budget` artifact.
- **Dollar budget.** Per-`HypothesisSpec` cap, tracked by the recorder; running ledger updated each turn.
- **Rollback on exhaustion.** If the iteration or dollar budget is exhausted without a passing build, the `ExperimentSpec` is marked `intractable` and no candidates are promoted. The staging / atomic-promote pattern handles the rollback at the filesystem level.
- **EvidenceLedger lookup at G0.** Identical hypotheses are not re-attempted unless explicitly flagged `relitigate_if` (simulator version changed, surrogate retrained, etc.).

---

## 8. Validation Portfolio (G4)

The Physical Invariance Assurer is one component of a portfolio, not the whole defense. Numerical correctness alone is insufficient against adversarial code-gen.

| Check | What it catches |
| :--- | :--- |
| Conservation / invariants | Energy, mass, $\nabla\!\cdot\!\mathbf{B}$, momentum residuals above tolerance |
| Convergence below tolerance | Solver claims success but residual norm too high |
| Refinement convergence | Solver converges to a wrong answer because the grid was too coarse (Richardson where applicable) |
| Symmetry tests held out from prompts | Code-gen that satisfies seen invariants but not unseen symmetries |
| Limiting-case tests | Axisymmetric limit of stellarator = tokamak; high-mass limit of relativistic = Newtonian; etc. |
| Statistical validity | Per-seed variance; error bars; the metric reported is the one pre-registered in `ExperimentSpec` |
| Cross-simulator check | When ≥2 OSI-licensed simulators in the Catalog can compute the observable, independently re-run on the second |
| Provenance hashing | Env hash, code hash, input hash, seed, simulator version, container SHA recorded on every Ledger entry |

When cross-simulator validation is unavailable for an observable, the portfolio is reweighted toward refinement and symmetry. The Catalog should be grown deliberately to enable cross-simulator validation in each active domain.

The `surprise_bits` field on each `EvidenceLedgerEntry` (sourced from the Strategy Archive in spec 016) is recorded alongside the `ValidationResult` for downstream C5 ranking. It is **informational, not gating** — G4 outcomes are decided purely by the deterministic portfolio above; surprise is consumed by `top_high_surprise_with_dependents` audit queries (spec 012) and by C5 program-direction (spec 003).

---

## 9. RAG-Grounded Writing

Instead of relying on general LLM memory for the manuscript:

- The Writer is a RAG pipeline querying the **local Paper Store** built during Phase 0. No web calls at write time.
- The Related Work section writes direct, citable comparisons (e.g., *"Our algorithm scales grid resolutions exponentially, whereas Smith et al. (2024) used linear steps, resulting in a 40% reduction in solver runtime"*).
- BibTeX is generated from the cached Paper Store entries — never fabricated.
- C4 (Peer Review council) reviews the draft against the underlying `RunReport`, with preserved dissent.
- The draft is published to `EvidenceLedger` internally. External release (arXiv, blog, paper submission) requires G6 human approval.

---

## 10. Named Failure Modes and Defenses

The factory must explicitly defend against each of the following. These are not hypothetical — at least four have already been observed in prior agentic-science experiments.

1. **Sycophancy / groupthink.** Council calls trained on the same backbone agree without genuine disagreement.
   - *Defense (restored multi-vendor heterogeneity; §25 SUPERSEDES §24).* Two orthogonal diversity axes: **vendor heterogeneity** — 4 frontier models from 4 distinct vendors (`openai/gpt-5.5`, `anthropic/claude-opus-4.7`, `google/gemini-3.1-pro-preview`, `x-ai/grok-4.3`) routed via OpenRouter — **plus** **persona heterogeneity** (Visionary / Pessimist / Pragmatist) **+** anonymized cross-review **+** dissent-preserving chairman. Vendor heterogeneity is the primary defense; persona heterogeneity is orthogonal reinforcement. The `CouncilSycophancyDetected` threshold returns to **0.85** (max pairwise cosine). Calibration acceptance threshold returns to **≥ 0.40** overall disagreement-rate. See `FIX_PLAN.md §25.4`.
2. **Numerical gullibility.** LLMs evaluate formulas linguistically (elegant, novel, well-cited) rather than numerically (NaN-stable, gradient-bounded). A council can unanimously approve a formula none of the models can actually simulate in head.
   - *Defense:* G2.5 tractability dry-run **+** G3 surrogate **+** G4 portfolio. Councils never approve a formula that has not been numerically executed.
3. **Invariant hacking.** Code-gen learns to satisfy the *named* invariants ($\nabla\!\cdot\!\mathbf{B}=0$, energy conservation) without solving the actual problem.
   - *Defense:* held-out symmetry / perturbation / limiting-case tests; cross-simulator check.
4. **Internal hallucination compounding.** A false internal finding shapes future hypotheses, then is itself "confirmed" by downstream cycles.
   - *Defense:* per-Ledger-entry provenance + uncertainty + `relitigate_if` triggers; C5 periodic re-audit of top-cited internal findings.
5. **Novelty / correctness inversion.** Truly novel findings contradict the literature you grounded on — by construction.
   - *Defense:* a publishable result that contradicts the Paper Store triggers an *intensified* validation portfolio (full G4 + adversarial council probe), not rejection. The policy decision of whether to publish *against* the grounding sits at G6 with a human.
6. **Surrogate inherits training-set blind spots.** A surrogate trained on past valid runs has no signal about novel-failure-mode candidates.
   - *Defense:* OOD detector at G3 with forced oracle escalation for OOD candidates.
7. **Cost escalation.** N hypotheses × ≥4 council calls × M fidelity tiers × K runs → $$$.
   - *Defense:* `Budget` artifact with per-hypothesis dollar / wall-clock / iteration / token caps and an aggregate kill switch.
8. **Worthiness gaming.** Any scalar "novel × tractable × significant" objective is gameable.
   - *Defense:* multi-criteria scoring in C1, randomized chairmanship, slow-cadence human spot-check in C5. Not solved; mitigated.
9. **License contamination.** A simulator nominally MIT but depending on a non-redistributable library, or with proprietary auxiliary data.
   - *Defense:* full dependency-graph license audit at Catalog onboarding; container build must succeed from scratch with no external secrets.

---

## 11. Phased Rollout

### Phase A — first 90 days

**Scope.** A single physics domain plus one orthogonal physics domain, used solely to enable a cross-simulator check on a single shared observable. No claim of broader generality. The initial domain is selected to be one where multiple OSI-licensed simulators exist for the same observable, enabling cross-simulator validation from day one.

**Catalog.** 5–10 hand-curated entries spanning the two initial domains, including utility codes where they widen cross-validation coverage.

**Deliverables.**
- Council-as-library: a Python implementation of the three-stage deliberation protocol (~200 LOC). Multi-vendor lineup via OpenRouter (4 models from §25.3) using the OpenAI-compatible SDK against `https://openrouter.ai/api/v1`, single env var `OPENROUTER_API_KEY`. See `FIX_PLAN.md §25.1`–`§25.3`.
- Persona prompt templates (Visionary, Pessimist, Pragmatist) with adversarial calibration tests.
- `SimulatorCatalog` v1 with 5–10 hand-curated entries, each with container recipe + smoke test.
- `SimulatorSelector` with rank-and-cost output.
- Domain adapter for the abstract solver interface, wired to ≥2 simulators in the initial domain.
- Tractability dry-run gate (G2.5) and budget enforcement wired to the staging / atomic-promote layer.
- `EvidenceLedger` schema with provenance hashing.
- C1–C5 councils running; C5 weekly.
- G0–G6 gate enforcement.

**90-day milestone.**
> The system autonomously proposes one hypothesis the operator did not suggest, selects an appropriate open-source simulator from the Catalog, executes the experiment within budget, validates against the full G4 portfolio (with cross-simulator check where Catalog permits), and emits a defensible internal `RunReport`. The result may be a positive finding *or* a defensible null. Either qualifies as success.

### Phase B — year 1

- Catalog grows to ~30 entries across 5–6 domains via the human-approved onboarding workflow.
- Cross-simulator validation enabled for ≥1 observable in each active domain.
- C5 promoted to fortnightly cadence with measurable retire-saturated / expand-direction decisions.
- External-publication path (G6) wired end-to-end; first external arXiv submission, with the human gate exercised.
- Domain expansion criteria in `DomainScope` formalized and enforced.

### Phase C — year 2+

- Autonomous Catalog onboarding from upstream documentation.
- Cross-domain hypothesis generation (e.g., methodology transferred from MD into plasma).
- C5 budget over $1k/hypothesis becomes routine; aggregate $-cap enforced.

**LLM substrate.** Spec 018 (`specs/018-openrouter-client.md`) is the **LLM substrate** of the factory — every LLM call routes through `OpenRouterClient`, the concrete `DecisionClient` Protocol implementation backed by the `openai` SDK against `https://openrouter.ai/api/v1`. This satisfies the single-env-var invariant in `FIX_PLAN.md §25` (only `OPENROUTER_API_KEY`). Consumers (specs 001, 007, 008, 010, 011, 016) import `from factory.llm_client import OpenRouterClient`; tests use the drop-in `FileClient` fixture-replay mock. See `FIX_PLAN.md §27.2`.

---

## 12. 90-Day Reality Check

The 90-day target is plausible only if scoped tightly: one domain family, one simulator catalog of 5–10 entries, one class of hypothesis. Do not optimize for a fully general physics scientist on day one. "Friday-evening-turn-on" is the correct *milestone description*, not the project timeline — the prerequisites (Council-as-library, persona templates, tractability filter, surrogate integration, EvidenceLedger schema, budget enforcement, rollback wiring) are ~2–3 weeks of focused build before the loop runs end-to-end.

The single proof-of-concept criterion is: **one bounded experiment, autonomously proposed and executed, defensibly validated, with a published internal report.** That single result determines whether the architecture earns further investment or whether it is another expensive RAG-with-extra-steps.

---

## 13. Honest Open Problems

These remain unsolved by the architecture and constitute the research surface of the project:

- **Worthiness is gameable.** Multi-criteria + preserved dissent + low-cadence human spot-check is the best current answer, not a solution.
- **Catalog growth is the bottleneck.** "Anything open-source" is intent; Catalog size is reality. Until autonomous onboarding (Phase C) works, the factory's domain is human-curated.
- **Generator-Verifier generalization across simulator interfaces.** Code-gen that knows one simulator cold has zero priors on a different simulator's input language. Cross-domain code-gen is unproven at the level of fidelity this factory requires.
- **The "novel contradicts grounding" decision is policy-shaped, not technical.** When a result contradicts the Paper Store, validation is intensified; whether to *publish* against the literature is encoded at G6 as a human call.
- **Council calibration is empirical.** Whether C1 worthiness rankings track expert judgment is a question to be tested in Phase A. If they do not, the factory has no traction and the architecture needs a different judgment substrate.
- **Cross-simulator validation often does not exist.** In well-trodden domains it does; in most physics problems it does not. The "orthogonal check" defense is strongest in well-trodden domains and weaker the further the Catalog strays.
