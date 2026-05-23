# Glossary

> Authoritative definitions for every acronym, gate ID, council ID, persona, artifact, and project-specific concept.
> Use this when reading any spec or runbook and encountering an unfamiliar term.
> Definitions are tight (≤3 lines). Each entry ends with a canonical-source pointer.

---

## Gates

Gates run in strict order; no gate is skipped. A failure routes to a documented recovery path, never to a generic retry. The state machine (spec 003) is the sole orchestrator; routes live in `config/gate_routes.yaml`.

### G0 — Domain Check
Verifies the candidate hypothesis lies within the current `DomainScope`. Deterministic. Out-of-scope hypotheses park as `parked_for_scope_expansion` for C5 review; the EvidenceLedger dedup lookup also fires here. → `SPEC.md §4`

### G1 — Falsifiability Filter
Confirms a `GapCandidate` converts cleanly to `gap → falsifiable hypothesis → measurable metric → available simulator/data → baseline → stop condition`. Deterministic. Failures are discarded with rationale; citation-graph holes are not automatically gaps. → `SPEC.md §4`

### G1.5 — Simulability Filter
`SimulatorSelector` must return ≥1 OSI-licensed simulator from the Catalog with a known-working container recipe that can compute the hypothesis's metric. Deterministic. Failure routes to `parked_for_lack_of_tooling`. → `SPEC.md §4`

### G2 — Worthiness Council (C1)
Council deliberation that ranks the hypothesis on novelty × tractability × falsifiability × significance. Council-driven; emits `CouncilVerdict` with preserved dissent. Majority-approved with substantive minority objection enters a "qualified" track requiring intensified G4. → `SPEC.md §4`

### G2.5 — Tractability Filter
A one-iteration dry-run of the proposed solver mutation on a toy problem via the Generator-Verifier loop. Deterministic (no LLM judgement). Static analysis alone is forbidden (halting-problem trap). Failure marks hypothesis `intractable`. → `SPEC.md §4`

### G3 — Cheap-Probe Gate (Surrogate-First)
The mutation must beat the relevant baseline on a learned surrogate model. Deterministic. OOD detection on surrogate inputs is mandatory — OOD candidates skip the surrogate and escalate directly to oracle. → `SPEC.md §4`

### G4 — Validation Portfolio
Nine orthogonal deterministic checks (conservation, convergence, refinement, CFL, held-out symmetry, limiting case, statistical, cross-simulator, provenance). All must pass; failures route to `terminate_falsified` or `terminate_inconclusive`. No LLMs ever execute inside G4. → `SPEC.md §4`, `specs/009-validation-portfolio.md §1`

### G5 — Claim Interpretation (C3) + Peer Review (C4)
Two councils in sequence: C3 derives the strongest defensible claim; C4 peer-reviews the resulting `RunReport`. On pass, result is internally published to the `EvidenceLedger`. → `SPEC.md §4`

### G6 — Human Approval
Required only for external release (arXiv, preprint, blog, any outside-world emission). Internal `EvidenceLedger` updates remain unsupervised. The single human-in-the-loop boundary in the factory. → `SPEC.md §4`, `SPEC.md §1.6`

---

## Councils

Four per-cycle gates plus one slow-cadence program-direction loop. Every council runs the three-stage protocol (First Opinions → Anonymized Cross-Review → Chairman Synthesis) and emits a `CouncilVerdict` with preserved dissent. → `SPEC.md §3`

### C1 — Worthiness Council
Invoked after the Gap Miner emits `GapCandidate`s; powers gate G2. Ranks candidates on novelty × tractability × falsifiability × significance and produces approve/qualified/reject decisions. → `SPEC.md §3.3`

### C2 — Experimental Design Council
Invoked after the Hypothesis Refiner emits a `HypothesisSpec`. Approves `ExperimentSpec`: simulator choice, control definition, fidelity ladder, success metric, kill criteria. → `SPEC.md §3.3`

### C3 — Claim Interpretation Council
Invoked after the G4 validation portfolio passes. Produces the strongest defensible claim from the evidence, or an explicit null. Fires at G5. → `SPEC.md §3.3`

### C4 — Peer Review Council
Invoked before `RunReport` finalization at G5. Decides publishable / falsified / weak and flags for G6 human gate if external release is requested. → `SPEC.md §3.3`

### C5 — Program Direction Council
Slow-cadence (default weekly; Phase B fortnightly) deliberation over the `EvidenceLedger`. Retires saturated gap-clusters, expands or contracts `DomainScope`, and spot-checks internal findings. → `SPEC.md §3.3`, `specs/003-state-machine.md §5.5`

---

## Personas

Each council model is independently prompted under one of three personas. Personas are stage-1 role prompts, orthogonal to and compatible with stage-2 anonymization. Heterogeneous models *and* heterogeneous personas are both required — RLHF-aligned models partially refuse adversarial personas, so neither alone is sufficient. → `SPEC.md §3.1`

### Pessimist (Reviewer 2)
Argues only failure modes, gaps, and methodological holes. The adversarial persona; primary defense against sycophantic agreement. Refusal raises `PersonaRefusal`. → `SPEC.md §3.1`, `specs/001-council.md §LOCAL DEBUG`

### Pragmatist
Evaluates implementation cost, tractability, calendar realism. Emphasizes "can we actually build this in budget" over scientific elegance. → `SPEC.md §3.1`

### Visionary
Argues why the hypothesis, design, or claim is impactful. Counterweight to the Pessimist; ensures real opportunities are not killed by reflexive skepticism. → `SPEC.md §3.1`

---

## Typed Artifacts

The 13 persistent typed artifacts (bumped from 11 by `FIX_PLAN.md §26` to add `Strategy` and `StrategyCycleEvidence`). Versioned JSON, Pydantic-validated, content-hashed, immutable, persisted under `runs/<cycle-id>/artifacts/<hash>.json`. Everything else (UI, orchestration scaffolding, transient state) is non-persistent. The class `Ledger` (spec 012) is the storage backend, **not** an artifact. → `SPEC.md §2`, `specs/002-artifacts.md §1`

### Budget
Per-`HypothesisSpec` resource envelope: `dollar_cap`, `wall_clock_cap_seconds`, `token_cap`, `iteration_cap`, plus an append-only `running_ledger` of `BudgetLedgerEntry`. Producer: state machine (spec 003); consumer: every module that spends. → `SPEC.md §2`, `specs/002-artifacts.md §3`

### CouncilVerdict
Output of a three-stage deliberation. Carries `council_id`, `majority_view`, `preserved_dissents[]`, `chairman_decision` ∈ {approve, reject, qualified, no_consensus}, `model_lineup`, `persona_assignment`. Rationales are carried inside each `DissentEntry` in `preserved_dissents[]`; no separate top-level `dissent_rationales[]` field. Producer: Council library (spec 001); consumer: state machine, Ledger. → `SPEC.md §2`, `specs/002-artifacts.md §3`

### DomainScope
Currently allowed simulator families and physics regimes: `allowed_domains[]`, `allowed_simulator_ids[]`, `expansion_criteria[]`. Producer: C5 council; consumer: G0 gate, state machine. → `SPEC.md §2`

### EvidenceLedgerEntry
Persistent record of all per-hypothesis results. Fields: `hypothesis_id`, `result` ∈ {passed, falsified, intractable, inconclusive}, `terminal_state` (granular state string), `ProvenanceBlock`, `uncertainty` (typed `UncertaintyBlock`), `relitigate_if[]`, `council_verdict_hashes`, `run_report_hash`. Producer: state machine at terminal; consumer: G0 dedup, C5, RAG writer. → `SPEC.md §2`, `specs/002-artifacts.md §3`

### ExperimentSpec
Concrete experimental design: `simulator_id`, `control_definition` (typed `ControlDefinition`), `fidelity_ladder[]`, `seed_set[]`, `success_metric`, `kill_criteria`. Producer: C2 council via Hypothesis Refiner; consumer: Generator-Verifier loop, Validation Portfolio. → `SPEC.md §2`, `specs/002-artifacts.md §3`

### FactoryControlEvent
Operator mutation entering the running factory. Fields: `event_type` ∈ {pause, resume, approve, reject, halt}, `target_ref` (cycle id, hypothesis id, or run-report hash as applicable), `actor` (operator id), `rationale`, `issued_at`. Producer: operator CLI / HTTP API (spec 015); consumer: state machine pause/resume/approve handler (spec 003). Persisted to `runs/_control/events/<ts>.json`. → `SPEC.md §2`, `specs/002-artifacts.md §3`, `specs/015-operator-interface.md`

### GapCandidate
Literature-derived candidate research direction. Fields: `gap_type` ∈ {structural_hole, methodology_transfer, contradiction, negative_result}, `source_papers[]` (OpenAlex Work IDs), `confidence`, `rationale`, `seed_query`. Producer: Gap Miner (spec 007); consumer: G0, C1. → `SPEC.md §2`

### HypothesisSpec
Concretized falsifiable hypothesis. Fields: `hypothesis_id`, `parent_gap_hash`, `if_then`, `measurable_metric`, `expected_effect_size`, `confidence_interval`, `kill_criteria[]`, `pre_registered_metric`, `qualified_track: bool` (set when C1 issued `qualified`). Producer: Hypothesis Refiner; consumer: C2, G2.5, Generator-Verifier, G4. → `SPEC.md §2`, `specs/002-artifacts.md §3`

### RunReport
Per-experiment artifact for internal publication. Fields: `latex_source`, `figure_paths[]`, `bibtex` (from Paper Store), `embedded_council_verdict_hashes[]`, `abstract`, `g6_approved`, `g6_approver`. Producer: RAG Writer (spec 011); consumer: C4, G6, Ledger. → `SPEC.md §2`, `specs/002-artifacts.md §3`

### Strategy
Persistent strategy node in the Strategy Archive (spec 016). Fields: `sha` (content hash of `summary_md`), `summary_md`, `kind ∈ {novel, mutate, crossover, library}`, `parent_shas[]` (empty for novel/library; ≥1 for mutate/crossover), `reward_ema`, `surprise_ema`, `feasibility_distance_ema`, `feasible_count`, `visits`, `behavior_descriptor` (for MAP-Elites), `provenance ∈ {agent_authored, hand_authored, transferred_from_exp_*}`. Producer: Generator-Verifier loop + Strategy Archive (spec 016); consumer: UCT lineage selection, C5 program-direction. → `SPEC.md §2`, `specs/016-strategy-archive.md`, `FIX_PLAN.md §26.2`

### StrategyCycleEvidence
Per-cycle outcome attribution for a strategy node (spec 016). Fields: `strategy_sha`, `cycle_id`, `best_objective`, `best_feasibility_distance`, `feasible_count`, `constraint_overshoots: dict[str, ConstraintOvershootStats]`. Producer: state machine at cycle terminal; consumer: `StrategyArchive.attribute_reward` / `attribute_surprise`. → `SPEC.md §2`, `specs/016-strategy-archive.md`, `FIX_PLAN.md §26.2`

### SurrogateProbeResult
Output of the G3 cheap-probe (surrogate-first) gate. Fields: `candidate_hash`, `surrogate_id`, `predicted_metric`, `baseline_metric`, `delta`, `ood_flag: bool`, `ood_score`, `escalate_to_oracle: bool` (carries the `skip_surrogate` semantics for downstream G4 routing). Producer: Surrogate module (spec 010); consumer: state machine G3 routing, G4. → `SPEC.md §2`, `specs/002-artifacts.md §3`, `specs/010-surrogate-models.md`

### ValidationResult
Output of the G4 validation portfolio. Fields: `experiment_hash`, `per_check_outcomes[]` (one entry per portfolio check: conservation, convergence, refinement, symmetry, limiting case, statistical, cross-simulator, provenance), `aggregate_outcome` ∈ {pass, fail, inconclusive}, `cross_simulator_present: bool`, `qualified_intensified: bool` (true when `HypothesisSpec.qualified_track` triggered intensified portfolio). Producer: Validation module (spec 009); consumer: state machine G4 routing, embedded in `RunReport`. → `SPEC.md §2`, `specs/002-artifacts.md §3`, `specs/009-validation-portfolio.md`

---

## Modules

15 factory modules. Each lives at `factory/<module>/` with 1:1 spec correspondence and a CLI runnable in isolation as `python -m factory.<module>`. → `ARCHITECTURE.md §3`

### artifacts (Spec 002)
Defines the 8 immutable Pydantic-validated typed artifacts plus content-addressed SHA-256 hashing, fixture loading, and `verify-chain`. Foundational — every other module depends on it; it depends on nothing. → `specs/002-artifacts.md`

### adapter (Spec 006)
Domain adapter layer: translates the abstract solver interface (discretization / fidelity / boundary handling / update operator / acceptance / restart / polishing) into each simulator's actual API. Adding a simulator = writing an adapter. → `SPEC.md §5.3`, `specs/006-domain-adapter.md`

### budget (Spec 013)
Budget tracker with hard caps (dollar / wall-clock / token / iteration) and an append-only running ledger of `BudgetLedgerEntry`. Owns the aggregate-spend kill switch. → `specs/013-budget-tracker.md`

### catalog (Spec 004)
`SimulatorCatalog` — machine-readable manifests for each curated OSI-licensed simulator: license, domain, I/O schema, container recipe, smoke test, dependency graph, maintenance signal, known pathologies, cross-simulator equivalence map. → `SPEC.md §5.1`, `specs/004-simulator-catalog.md`

### council (Spec 001)
Standalone deliberation library: multi-vendor lineup of 4 frontier models via OpenRouter (one OpenAI-compatible client, single env var `OPENROUTER_API_KEY`), persona prompts, three-stage protocol, anonymized cross-review, chairman synthesis with preserved dissent, sycophancy calibration. Pure library — no factory dependencies beyond artifacts. → `specs/001-council.md`, `FIX_PLAN.md §25` (§25 SUPERSEDES §24)

### genver (Spec 008)
Generator-Verifier loop: multi-turn ReAct agent that proposes solver-blueprint code targeting the abstract solver interface, executes in subprocess sandbox, atomically promotes on success. 10-iteration cap. → `specs/008-generator-verifier.md`

### ledger (Spec 012)
EvidenceLedger persistence: SQLite schema + CRUD + audit query interface + provenance-chain verification. Sole owner of `EvidenceLedgerEntry` durability. → `specs/012-evidence-ledger.md`

### literature (Spec 007)
OpenAlex client + bounded citation-graph traversal (BFS / priority-BFS) + paper ranker + Gap Miner that emits `GapCandidate`s from the four gap types. → `SPEC.md §6`, `specs/007-literature-discovery.md`

### operator (Spec 015)
Operator interface: CLI (`factory start | stop | status | inspect <id>`) and read-only HTTP API for the UI backend. Thin loop above the state machine for multi-cycle continuous operation. → `specs/015-operator-interface.md`

### selector (Spec 005)
`SimulatorSelector` — given a `HypothesisSpec`, returns ranked candidate simulators with compatibility score, cost estimate, and whether ≥2 simulators can compute the observable (enables G4 cross-simulator). → `SPEC.md §5.2`, `specs/005-simulator-selector.md`

### state_machine (Spec 003)
The sole orchestrator. Walks each hypothesis through G0 → G6, persists artifacts after each gate, routes failures via `config/gate_routes.yaml`. Owns sequencing, persistence, and routing — never intelligence or execution. Also hosts `C5Scheduler`. → `specs/003-state-machine.md`

### surrogate (Spec 010)
Surrogate models (random forest, MLP, successors) for G3 cheap-probe scoring, plus an out-of-distribution detector on surrogate inputs that forces oracle escalation. → `SPEC.md §5.4 strategy`, `specs/010-surrogate-models.md`

### telemetry (Spec 014)
Structured event logging + audit trail. Modules emit `{ts, cycle_id, module, level, event, payload}` events to `cycle.jsonl`; no free-text log messages allowed. → `ARCHITECTURE.md §1.4`, `specs/014-telemetry-and-audit.md`

### validation (Spec 009)
G4 validation portfolio: 9 deterministic orthogonal checks (conservation, convergence, refinement, CFL, held-out symmetry, limiting case, statistical, cross-simulator, provenance). Emits `ValidationResult`. No LLM ever runs inside G4. → `specs/009-validation-portfolio.md`

### writer (Spec 011)
RAG-grounded writer. Queries local Paper Store (built during Phase 0), generates `RunReport` LaTeX with citable comparisons, BibTeX never fabricated. No web calls at write time. → `SPEC.md §9`, `specs/011-rag-writer.md`

---

## Failure Modes

Named `FactoryError` subclasses. Every Pytest failure should emit one of these — long stack traces without a typed `FactoryError` indicate an undocumented failure mode (anti-pattern). → `ARCHITECTURE.md §1.9`

### AdapterFailureUnrecoverable (genver)
Spec-006 adapter raised before code-gen produced runnable input, OR three consecutive `SandboxResourceExceeded` events. Routes to `terminate_intractable`; relitigation trigger = "simulator version updated in catalog". → `specs/008-generator-verifier.md §6`

### ArtifactImmutabilityViolation (artifacts)
Caller attempted `artifact.field = x` instead of `artifact.model_copy(update=...)`. Raised at mypy strict at code-review time; runtime guard from Pydantic `ConfigDict(frozen=True)`. → `specs/002-artifacts.md §6`

### ArtifactNotFound (state_machine)
Required input artifact missing — upstream gate didn't persist its output. Halts cycle; terminal outcome = `inconclusive`. → `specs/003-state-machine.md §6`

### ArtifactProvenanceMismatch (artifacts)
`verify_self()` found `compute_hash() != self.provenance_hash`. Artifact was tampered or seed drift. Halts cycle; marks artifact poisoned; full provenance audit before resume. → `specs/002-artifacts.md §6`

### ArtifactValidationError (artifacts)
Pydantic validation failed on construction or `from_json`. State machine routes to the upstream module that produced the bad data; surfaces in `cycle.jsonl`. → `specs/002-artifacts.md §6`

### BudgetExhausted (state_machine / budget)
Per-`HypothesisSpec` dollar / wall-clock / token / iteration cap was breached. Routed automatically to `intractable` EvidenceLedger entry; not propagated as a raised error. → `specs/003-state-machine.md §6`

### ChairmanDissentOmission (council)
Chairman synthesis did not cite required dissent. Auto-rerun once with stricter prompt; on second failure, escalate to operator. → `specs/001-council.md §6`

### CodeGenParseFailed (genver)
After one auto-reformat retry, the response still fails to parse to a valid ReAct `ToolCall`. Iteration recorded as `parse_failed`; loop continues. → `specs/008-generator-verifier.md §6`

### ConservationViolated (validation)
Conservation residual (energy, mass, `∇·B`, momentum) above pre-configured tolerance. Code-gen iterates if real physics violation; fix diagnostic if instrumentation bug. → `specs/009-validation-portfolio.md §LOCAL DEBUG`

### ConvergenceFailed (validation)
Solver reports success but residual norm exceeds tolerance. Bump iteration cap or rebuild candidate. → `specs/009-validation-portfolio.md §LOCAL DEBUG`

### CouncilBudgetExceeded (council)
`cost_cap_usd` was set and reached during deliberation. Halt at next stage boundary; return partial verdict with `chairman_decision="no_consensus"`. → `specs/001-council.md §6`

### CouncilSycophancyDetected (council)
Stage-1 `max` pairwise embedding cosine similarity exceeds the `sycophancy_threshold` (default **0.85**, restored under multi-vendor heterogeneity per `FIX_PLAN.md §25.4`; statistic is `max` pairwise cosine, not mean, per `FIX_PLAN.md §16`). Calibration must pass before live use; operator must rotate models within the OpenRouter catalog or rebalance personas if it fires. → `specs/001-council.md §6`, `FIX_PLAN.md §25.4` (§25 SUPERSEDES §24)

### CrossSimulatorDisagreement (validation)
Two Catalog simulators disagree past the `cross_simulator_equivalence_map` tolerance. Cycle outcome = `inconclusive` (not failed); operator arbitration. → `specs/009-validation-portfolio.md §LOCAL DEBUG`

### DollarBudgetExhausted (genver)
`Budget.dollar_remaining <= 0` before next iteration starts. Encoded as `terminal_status="intractable_dollar_cap"`. → `specs/008-generator-verifier.md §6`

### FactoryError
Root exception class. Every module's `errors.py` defines its specific subclasses; all `Foo Error` types in this glossary inherit from `FactoryError`. → `ARCHITECTURE.md §3.1`

### FixtureNotFoundError (artifacts)
`from_fixture(name)` could not find the file. Lists available fixtures in the error message. Always a developer error. → `specs/002-artifacts.md §6`

### GateRouteUndefined (state_machine)
Gate returned an outcome with no route in `gate_routes.yaml`. Configuration bug; halts all cycles until YAML fixed. → `specs/003-state-machine.md §6`

### GateTimeoutError (state_machine)
Gate exceeded its configured `timeout_seconds`. Halt gate; terminal outcome = `intractable` with documented timeout cause. → `specs/003-state-machine.md §6`

### HeldoutLeakDetected (validation)
Static scan found a held-out symmetry fixture path inside code-gen-visible context. **Hard halt** the whole cycle and audit — never loosen the symmetry test. → `specs/009-validation-portfolio.md §LOCAL DEBUG`

### ImplementingModuleMissing (state_machine)
Gate's `implementing_module` cannot be imported. Configuration error; halt; fix per-gate YAML. → `specs/003-state-machine.md §6`

### IterationBudgetExhausted (genver)
Loop reached `max_iterations=10` without `passed_local_gate`. Encoded as `terminal_status="intractable_iteration_cap"`. → `specs/008-generator-verifier.md §6`

### LimitingCaseFailed (validation)
A limiting-case test failed (axisymmetric limit of stellarator ≠ tokamak; high-mass limit of relativistic ≠ Newtonian; etc.). Physics bug in the candidate. → `specs/009-validation-portfolio.md §LOCAL DEBUG`

### ModelTimeout (council)
Vendor API exceeded `timeout_s`. Retry once with exponential backoff; >1 timeout per model abandons that opinion. → `specs/001-council.md §6`

### PersonaRefusal (council)
A call returned a meta-response refusing its assigned persona (RLHF kicked in). Re-prompt with a stronger persona instruction; if it still refuses, drop the opinion and reassign the persona to a different vendor in the OpenRouter lineup (4 vendors available — see `Council models`). Do not propagate persona-flattened opinion. → `specs/001-council.md §6`, `FIX_PLAN.md §25.3` (§25 SUPERSEDES §24)

### ProvenanceIncomplete (validation)
A required hash (code / env / input / seed / simulator version / container SHA) is missing from the `ProvenanceBlock`. Refuse to write to ledger. → `specs/009-validation-portfolio.md §LOCAL DEBUG`

### RefinementInconsistent (validation)
Grid-coarsening mismatch — two refinement levels disagree past tolerance. Raise base grid resolution in `ExperimentSpec` and rerun. → `specs/009-validation-portfolio.md §LOCAL DEBUG`

### RollbackFailed (genver)
`wipe_staging` raised a filesystem error during cleanup. Staging left on disk for forensics; cycle halted; operator alert. → `specs/008-generator-verifier.md §6`

### RouteCycleDetected (state_machine)
Startup validation found a cycle in `gate_routes.yaml`. The route graph must be a DAG. Refuse to start until fixed. → `specs/003-state-machine.md §6`

### SandboxResourceExceeded (genver)
Sandbox subprocess exceeded a resource limit: `kind ∈ {cpu, memory, wall_clock, disk, file_descriptor}`. Iteration recorded as `resource_exceeded`; 3 consecutive escalate to `AdapterFailureUnrecoverable`. → `specs/008-generator-verifier.md §6`

### StagingPromoteRaced (genver)
Atomic-promote temp dir non-empty after the per-file move loop. Infrastructure failure; halt cycle with operator alert; staging preserved. → `specs/008-generator-verifier.md §6`

### StatisticalInvalid (validation)
Per-seed variance too high OR the reported metric is not the `pre_registered_metric` in `ExperimentSpec`. Rerun with more seeds or fix metric selection. → `specs/009-validation-portfolio.md §LOCAL DEBUG`

### SymmetryHeldOutFailed (validation)
A held-out symmetry test failed despite all visible invariants passing. Strong invariant-hacking signal; quarantine the candidate — never loosen the test. → `specs/009-validation-portfolio.md §LOCAL DEBUG`

---

## Concepts

### Agentic default model
The cheap single model — `google/gemini-3.5-flash` via OpenRouter — used for every **non-council** LLM call: Generator-Verifier code-gen (spec 008), Gap Miner LLM analysis (spec 007), RAG Writer section drafting (spec 011), Surrogate OOD audit prose (spec 010), Telemetry C5-input digest (spec 014). Justified as single-vendor because its outputs are checked downstream by deterministic gates (G2.5 / G3 / G4) and the council — it is not the judgment substrate. → `FIX_PLAN.md §25.5`

### Anonymized Cross-Review
Stage 2 of council deliberation. Each model is assigned a Voice letter (A, B, C, ...); reviewers see only `Voice X` bodies with model identity stripped, then rank and critique them. Only the chairman sees the de-anonymized matrix. → `SPEC.md §3.2`, `specs/001-council.md §5.2`

### Atomic Promotion
Per-file `os.replace` move from per-iteration staging into `runs/<cycle-id>/artifacts/`. POSIX `rename` is atomic within a filesystem. Whole-promote is all-or-nothing on the happy path; any failure raises and staging is preserved. → `specs/008-generator-verifier.md §5.6`

### Bayesian Surprise
KL divergence between posterior and prior beliefs over feasibility buckets, elicited from a `GuideLLM`. Binary mode uses Beta-Bernoulli (`beta_kl`); graded mode uses Dirichlet over 3 buckets (`lt_10`, `10_50`, `gt_50`) via `dirichlet_kl`. Polarity-gated to `0.0` unless the dominant pre/post bucket changes — prevents counting sampling noise as surprise. Recorded as `surprise_bits` on each `EvidenceLedgerEntry`. → `specs/016-strategy-archive.md §5`, `FIX_PLAN.md §26.2`

### Behavior Descriptor
Vector encoding of a candidate's behavior-space coordinates, used for MAP-Elites cell assignment and novelty scoring in lineage selection. Field on the `Strategy` artifact (lazy; populated when the cell is needed). → `specs/002-artifacts.md`, `specs/016-strategy-archive.md`

### Catalog Growth Policy
Phase A: human-curated, 5–10 entries. Phase B: human-approved onboarding workflow. Phase C: autonomous onboarding from upstream documentation. Catalog size is the practical limit on factory breadth. → `SPEC.md §5.4`

### Chairman Synthesis
Stage 3 of council deliberation. Chairman model produces a `CouncilVerdict` with majority view + every dissent + chairman_decision. Scalar Go/No-Go output is forbidden. Selection policy ∈ {random, round_robin, weighted_by_cost}. → `SPEC.md §3.2`, `specs/001-council.md §5.3`

### Content-Addressed Artifact
Every artifact carries a SHA-256 `provenance_hash` computed over canonical JSON (sorted keys, no whitespace, `provenance_hash` field excluded). Filename in artifact store IS the hash. References between artifacts use hashes, not paths. → `ARCHITECTURE.md §1.8`, `specs/002-artifacts.md §5.1`

### Cross-Simulator Validation
G4 portfolio check that re-runs the candidate's observable on a second OSI-licensed Catalog simulator and compares results against the `cross_simulator_equivalence_map` tolerance. Disagreement → cycle is `inconclusive`. Unavailable when Catalog supports only one simulator for the observable; portfolio reweights toward refinement + symmetry. → `SPEC.md §4 G4`, `SPEC.md §8 final paragraph`

### Diff-Based Iteration Tracking
Each Generator-Verifier iteration writes `diff.patch` against the previous iteration's blueprint via `difflib.unified_diff` (stdlib) or `git diff --no-index`. Used postmortem (`factory.genver diff-iterations`); not fed back into the prompt directly. → `specs/008-generator-verifier.md §5.7`

### Dissent Preservation
Consensus collapses information. Minority views that flag real flaws must survive into the `CouncilVerdict` as `preserved_dissents[]` with rationale. Chairman omission raises `ChairmanDissentOmission`. → `SPEC.md §1.2`, `SPEC.md §3.2`

### Fidelity Ladder
Mandatory escalation order: tractability dry-run → surrogate → physics-light → full-fidelity oracle. Each rung is a `FidelityTier` with `kind ∈ {dry_run, surrogate, mid_fidelity, oracle, cross_simulator}`, cost estimate, runtime estimate, kill threshold. → `SPEC.md §1.5`, `specs/002-artifacts.md §3`

### Fidelity Ladder Scheduler
Runtime traversal of `ExperimentSpec.fidelity_ladder`. Phase A: 3 tiers (`DRY_RUN`, `SURROGATE`, `ORACLE`); Phase B adds `MID_FIDELITY` and `CROSS_SIMULATOR`. Distinct from spec 006's `Discretizer` ABC (which decides grid/mesh choices **within one run**); the scheduler decides **which run** is next on the ladder. Module: `factory/fidelity/`. Public surface: `FidelityLadderScheduler.run_next_tier(hypothesis_id) → TierResult`. → `specs/017-fidelity-scheduler.md`, `FIX_PLAN.md §26.3`

### Gap Types
Four kinds of literature-derived gap a `GapCandidate` may carry: `structural_hole` (citation-graph cavity), `methodology_transfer` (technique unused in adjacent domain), `contradiction` (papers disagree), `negative_result` (replicable null). → `SPEC.md §2`, `specs/002-artifacts.md §3`

### GuideLLM
Belief-eliciting LLM client distinct from the council. Uses `google/gemini-3.5-flash` via OpenRouter (`FIX_PLAN §25.5`, the same agentic default model). Samples `n=5` categorical (`feasibility_bucket → lt_10 | 10_50 | gt_50`) or boolean responses per surprise call. Drives `binary_bayesian_surprise` and `graded_bayesian_surprise` in `factory/strategy/beliefs.py`. → `specs/016-strategy-archive.md §3`, `FIX_PLAN.md §26.2`

### gemini-3.5-flash
The **agentic default model** (not the council model). Accessed via OpenRouter as `google/gemini-3.5-flash` using the OpenAI-compatible SDK; powers every non-council LLM call — Generator-Verifier code-gen (spec 008), Gap Miner LLM analysis (spec 007), RAG Writer section drafting (spec 011), Surrogate OOD audit prose (spec 010), Telemetry C5-input digest (spec 014). Single cheap model, defaults-only sampling, single env var `OPENROUTER_API_KEY`. Council judgment uses 4 frontier vendors instead — see `Council models`. → `FIX_PLAN.md §25.5` (§25 SUPERSEDES §24)

### Held-Out Symmetry Tests
G4 symmetry fixtures kept under `factory/validation/fixtures/symmetry/<domain>/` *outside* any code-gen read-allowlist. Defense against invariant hacking. `verify-holdout-isolation` CLI asserts non-leakage; leak triggers `HeldoutLeakDetected` hard halt. → `specs/009-validation-portfolio.md §2`, `specs/009-validation-portfolio.md §LOCAL DEBUG`

### Council Composition (vendor + persona heterogeneity)
Exactly 4 independent calls per council session, one per vendor via OpenRouter (`openai/gpt-5.5`, `anthropic/claude-opus-4.7`, `google/gemini-3.1`, `x-ai/grok-4.3`), each carrying a Visionary / Pessimist / Pragmatist persona system instruction. Two orthogonal axes of diversity — **vendor** (primary defense) + **persona** (orthogonal reinforcement). Persona-to-vendor assignment rotates per cycle; the 4 vendors are fixed. Random chairmanship per session, drawn from the persona set. Single-vendor failure raises `CouncilError` (no silent substitution — vendor heterogeneity IS the defense). → `SPEC.md §3.1`, `specs/001-council.md §3`, `FIX_PLAN.md §25.3` (§25 SUPERSEDES §24)

### Council models
The 4 OpenRouter model IDs that constitute the per-cycle council lineup, one per vendor: `openai/gpt-5.5`, `anthropic/claude-opus-4.7`, `google/gemini-3.1`, `x-ai/grok-4.3`. Exact ID strings verified at setup time against `curl https://openrouter.ai/api/v1/models -H "Authorization: Bearer $OPENROUTER_API_KEY"`; ID drift updates config only, never code. Distinct from the **agentic default model** (`google/gemini-3.5-flash`) used for non-council LLM calls. → `FIX_PLAN.md §25.3`

### Immutability
Artifacts use Pydantic `ConfigDict(frozen=True)`. Update pattern: `new = old.model_copy(update={...})` — produces a new artifact with a different hash; old is unchanged. → `ARCHITECTURE.md §1.8`, `specs/002-artifacts.md §5.2`

### Internal Hallucination Compounding
Failure mode: a false internal finding shapes future hypotheses and is then "confirmed" by downstream cycles. Defense: per-Ledger-entry provenance + uncertainty + `relitigate_if` triggers; C5 periodic re-audit of top-cited internal findings. → `SPEC.md §10.4`

### Internal vs External Autonomy
Internal `EvidenceLedger` updates are unsupervised. arXiv, preprints, blogs, or any outside-world emission require a human gate at G6. Asymmetric by design. → `SPEC.md §1.6`

### Invariant Hacking
Failure mode: code-gen learns to satisfy *named* invariants (`∇·B=0`, energy conservation) without solving the actual problem. Defense: held-out symmetry / perturbation / limiting-case tests + cross-simulator check. → `SPEC.md §10.3`

### License Contamination
Failure mode: a simulator nominally OSI but depending on a non-redistributable library or proprietary auxiliary data. Defense: full dependency-graph license audit at Catalog onboarding; container build must succeed from scratch with no external secrets. → `SPEC.md §10.9`

### Live Mode
Real LLM APIs, real container builds, real simulator binaries, real OpenAlex calls. Gated in tests by `@pytest.mark.live`. Per-module switching via flags or `FACTORY_MOCK=` exclusion. → `ARCHITECTURE.md §1.2`, `ARCHITECTURE.md §4.6`

### Local Gate (Generator-Verifier)
Strictly mechanical checks the Generator-Verifier loop applies post-sandbox: canonical tensor exists, no NaN / Inf, adapter success flag true, schema matches declared `blueprint_metadata`. Not scientific validation. → `specs/008-generator-verifier.md §5.5`

### MAP-Elites
Diversity-preserving archive that maintains the best candidate per behavior-descriptor cell. Phase B feature of the Strategy Archive; controlled by `StrategyArchiveConfig.map_elites_cell_bonus` and `parallel_lineages_k > 1`. Phase A keeps `parallel_lineages_k = 1` and no MAP-Elites cells. → `specs/016-strategy-archive.md §5.4`, `FIX_PLAN.md §26.7`

### Mock Mode
First-class operating mode where external dependencies (LLMs, containers, simulators, OpenAlex) return fixture data. Switched via `--mock-mode` flag or `FACTORY_MOCK=1` env var. Every CI integration test runs in mock mode. → `ARCHITECTURE.md §1.2`

### Novelty / Correctness Inversion
Failure mode: truly novel findings contradict the grounding literature by construction. Defense: publishable contradiction triggers an *intensified* G4 + adversarial council probe (not rejection); the decision to publish externally sits at G6 with a human. → `SPEC.md §10.5`

### Numerical Gullibility
Failure mode: LLMs evaluate formulas linguistically (elegant, novel, well-cited) rather than numerically. A council can unanimously approve a formula none of the models can actually simulate. Defense: G2.5 tractability dry-run + G3 surrogate + G4 portfolio. → `SPEC.md §10.2`

### Oracle Gate
The full-fidelity simulator run — the most expensive rung of the fidelity ladder. OOD candidates at G3 bypass the surrogate and escalate directly to oracle. → `SPEC.md §1.5`, `SPEC.md §4 G3`

### OOD Detection
Mandatory at G3: candidates whose surrogate inputs are out-of-distribution cannot earn a surrogate pass; they escalate directly to oracle. Defends against surrogate training-set blind spots. → `SPEC.md §4 G3`, `SPEC.md §10.6`

### OpenRouter
Unified LLM gateway used by the factory. All factory LLM access — council deliberation (4 frontier vendors) **and** every agentic call (`google/gemini-3.5-flash`) — routes through `https://openrouter.ai/api/v1` via the OpenAI-compatible SDK using a single env var: `OPENROUTER_API_KEY`. Optional ranking headers `HTTP-Referer` and `X-OpenRouter-Title: ai-co-computational-physicist` are set per call. Model IDs use `<vendor>/<model-id>` format. Reference: https://openrouter.ai/docs. → `FIX_PLAN.md §25` (§25 SUPERSEDES §24)

### OSI-Approved License
Open Source Initiative-approved licenses (MIT, BSD-{2,3}, Apache-2.0, GPL-{2,3}, LGPL, MPL-2.0, ISC, etc.). *All* runtime dependencies must also be OSI-approved or freely redistributable inside the container. Required for Catalog entry. → `SPEC.md §5.1`

### Paper Store
Local cache of PDF / OCR / extracted-schema records for papers promoted from OpenAlex traversal. Source of all BibTeX in `RunReport`s — citations are never fabricated, never web-fetched at write time. → `SPEC.md §6.1`, `SPEC.md §9`

### Preserved Dissent
The required content of `CouncilVerdict.preserved_dissents[]`. Each entry: model_id, persona, view, rationale. The chairman MUST cite ≥1 dissent if dissent exists. → `SPEC.md §1.2`, `specs/002-artifacts.md §3`

### Provenance Block
Required tuple inside every `EvidenceLedgerEntry`: `code_hash`, `env_hash`, `input_hash`, `seed`, `simulator_id`, `simulator_version`, `container_sha`. Missing hashes raise `ProvenanceIncomplete`. → `SPEC.md §1.8`, `specs/002-artifacts.md §3`

### Provenance Hash
SHA-256 over canonical JSON of an artifact (excluding the `provenance_hash` field itself). Filename in artifact store, identity in references, and the durability boundary. Re-running with same inputs + seed must reproduce the same hash. → `ARCHITECTURE.md §1.8`, `specs/002-artifacts.md §5.1`

### Re-Litigation
Permitted only with new evidence. An `EvidenceLedgerEntry` carries `relitigate_if[]` triggers (e.g., "simulator updated", "surrogate retrained", "iteration_cap raised"). G0 dedup lookup checks `currently_satisfied`. → `SPEC.md §1.7`, `specs/002-artifacts.md §3`, `specs/008-generator-verifier.md §5.9`

### Relitigation Trigger
A `RelitigationTrigger` record: `condition` (human-readable), `check_fn` (dotted path), `last_evaluated_at`, `currently_satisfied`. Stored inside `EvidenceLedgerEntry.relitigate_if[]`. → `specs/002-artifacts.md §3`

### Rotating Chairmanship
Random or round-robin or weighted chairman-persona selection per council session, drawn from the persona set (Visionary / Pessimist / Pragmatist). Defends against framing bias toward any single persona. Schedule lives at `config/council/chairman_rotation.yaml`. → `SPEC.md §3.1`, `specs/001-council.md §3`, `FIX_PLAN.md §25.3` (§25 SUPERSEDES §24)

### Sandbox (Generator-Verifier)
Subprocess-level (not Docker) Python child process with POSIX `setrlimit` (`RLIMIT_CPU`, `RLIMIT_AS`, `RLIMIT_FSIZE`, `RLIMIT_NOFILE`), wall-clock timer, write-root restriction, and `sys.meta_path` import whitelist. Hermetic per iteration. → `specs/008-generator-verifier.md §5.4`

### Sandbox Import Whitelist
`config/sandbox_imports.yaml`. Default: stdlib subset + numpy + scipy + jax + adapter-declared modules. Non-whitelisted imports raise `ImportError("sandbox: import 'X' not in whitelist")` from a `sys.meta_path` finder. → `specs/008-generator-verifier.md §5.4`

### Six-component solver blueprint
Locked ABC names per `FIX_PLAN.md §26.1` in `factory/adapter/abstract.py`: `Discretizer` (fidelity & discretization), `ConstraintAggregator` (boundary & constraint aggregation), `UpdateStepOperator` (update & step), `AcceptanceController` (globalization & acceptance), `RestartController` (restart & reset), `LocalPolisher` (polishing & local search). Per-simulator adapters bind concrete subclasses into a `BlueprintComponents` tuple; Generator-Verifier code-gen targets the abstract ABCs only — never the per-simulator concrete implementations. → `specs/006-domain-adapter.md §3`, `FIX_PLAN.md §26.1`

### Staging Directory
Per-iteration directory at `runs/<cycle-id>/sandbox/<iteration:03d>/` containing prompt, response, blueprint, diff, stdout, stderr, traceback, resource ledger, `adapter_outputs/`, and `status.json`. Preserved for forensics; `adapter_outputs/` wiped on terminal non-promotion. → `specs/008-generator-verifier.md §4.1`

### Strategy Archive
Persistent record of all attempted approaches (operator families) with reward / surprise / feasibility-distance EMAs, UCT scoring, MAP-Elites cells (Phase B), and lineage selection for parallel branches. Module: `factory/strategy/` (spec 016). Reference implementation: the proxima harness (`harness/beliefs.py`, `harness/strategy_config.py`, `harness/strategy_selection.py`, `harness/strategy_evidence.py`). Public surface: `StrategyArchive.{attribute_surprise, attribute_reward, select_lineages, add_strategy, transfer_priors_from}`. → `specs/016-strategy-archive.md`, `FIX_PLAN.md §26.2`

### Sycophancy / Groupthink
Failure mode: council calls trained on the same backbone agree without genuine disagreement. Defense (restored multi-vendor): **vendor heterogeneity** (4 frontier vendors via OpenRouter — `openai/gpt-5.5`, `anthropic/claude-opus-4.7`, `google/gemini-3.1`, `x-ai/grok-4.3`) **+** persona heterogeneity (Visionary / Pessimist / Pragmatist) **+** anonymized cross-review **+** dissent-preserving chairman. Vendor heterogeneity is the primary defense; persona is orthogonal reinforcement. `CouncilSycophancyDetected` threshold returns to **0.85** (max pairwise cosine). → `SPEC.md §10.1`, `FIX_PLAN.md §25.4` (§25 SUPERSEDES §24)

### Sycophancy Calibration
`Council.calibrate(probe_set)` runs the multi-vendor lineup against the built-in probe set + ≥5 operator-supplied domain-specific probes, computes `max` pairwise cosine similarity, reports overall disagreement-rate. Live operations require disagreement-rate **≥ 0.40** (restored from §24's 0.25 once multi-vendor heterogeneity returned). Above `sycophancy_threshold` (default **0.85**) raises `CouncilSycophancyDetected`. → `specs/001-council.md §5.4`, `specs/001-council.md §5.5`, `FIX_PLAN.md §25.4` (§25 SUPERSEDES §24)

### Three-Stage Deliberation
Council protocol: (1) First Opinions — each (model × persona) cell answers independently; (2) Anonymized Cross-Review — each cell critiques and ranks others; (3) Chairman Synthesis — chairman emits `CouncilVerdict` with preserved dissent. → `SPEC.md §3.2`, `specs/001-council.md §5`

### Tractability Dry-Run
G2.5 mechanism: one-iteration run of the proposed solver mutation on a toy problem through the Generator-Verifier loop. Static analysis alone is forbidden. Failure marks hypothesis `intractable`. → `SPEC.md §4 G2.5`

### UCT
Upper Confidence bounds applied to Trees — the lineage-selection scoring rule used by the Strategy Archive. Composite score = `reward_alpha × reward + surprise_beta × surprise + feasibility_gamma × pressure + uct_exploration_constant × √(log(N) / (visits + 1))`. **Invariant:** `reward_alpha + surprise_beta == 1.0` (enforced in `StrategyArchiveConfig`). Default exploration constant `1.414` (≈ √2). → `specs/016-strategy-archive.md §5.4`, `FIX_PLAN.md §26.2`

### Voice Letter
Stage-2 anonymization label (A, B, C, D, ...) assigned randomly to each model. Reviewers see only `Voice X` bodies during cross-review; identity is restored only for the chairman. → `specs/001-council.md §5.2`

### Worthiness Gaming
Failure mode: any scalar "novel × tractable × significant" objective is gameable. Defense (mitigated, not solved): multi-criteria scoring in C1, randomized chairmanship, slow-cadence human spot-check in C5. → `SPEC.md §10.8`, `SPEC.md §13`

---

## Phases

### Phase A — First 90 Days
**Scope.** One physics domain plus one orthogonal domain (for cross-simulator on a shared observable). Catalog: 5–10 hand-curated entries. No claim of broader generality. **Success.** One bounded experiment autonomously proposed and executed, defensibly validated, internally published as a `RunReport` (positive finding *or* defensible null). → `SPEC.md §11`, `SPEC.md §12`

### Phase B — Year 1
**Scope.** Catalog grows to ~30 entries across 5–6 domains via human-approved onboarding. Cross-simulator validation enabled for ≥1 observable per active domain. C5 promoted to fortnightly cadence. G6 wired end-to-end with first external arXiv submission. `DomainScope` expansion criteria formalized. → `SPEC.md §11`

### Phase C — Year 2+
**Scope.** Autonomous Catalog onboarding from upstream documentation. Cross-domain hypothesis generation (e.g., MD methodology transferred to plasma). C5 budget over $1k/hypothesis becomes routine; aggregate $-cap enforced. Open research, not engineering. → `SPEC.md §11`

---

## Operational States

Terminal classifications produced by gates and emitted into `EvidenceLedgerEntry.result` or as parked states. → `SPEC.md §4`, `specs/003-state-machine.md §4.1`

### falsified
Terminal `EvidenceResult`. G3 surrogate failed, OR G4 portfolio failed, OR C4 peer review rejected. Internally published as a negative-result `RunReport`; first-class output. → `SPEC.md §1.7`, `specs/002-artifacts.md §3`

### inconclusive
Terminal `EvidenceResult`. G4 cross-simulator disagreement, missing input artifact, or G5 review judged "weak". Result is recorded but does not feed hypothesis generation. → `specs/002-artifacts.md §3`, `specs/003-state-machine.md §4.1`

### intractable
Terminal `EvidenceResult`. G2.5 dry-run failed, OR iteration cap reached, OR dollar cap reached, OR adapter unrecoverable. Encoded with `relitigate_if` trigger (e.g., "iteration_cap raised"). → `SPEC.md §4 G2.5`, `specs/008-generator-verifier.md §6`

### parked_for_lack_of_tooling
Non-terminal park state set at G1.5 when `SimulatorSelector` returns no OSI-licensed simulator. Reviewed by C5; relitigation trigger when a simulator supporting the hypothesis is added to the Catalog. → `SPEC.md §4 G1.5`

### parked_for_scope_expansion
Non-terminal park state set at G0 when the hypothesis falls outside the current `DomainScope`. Reviewed by C5 for possible `DomainScope` expansion. → `SPEC.md §4 G0`

### passed
Terminal `EvidenceResult`. Full G0 → G5 traversal succeeded. Internally published `RunReport`; eligible for G6 if external release is requested. → `SPEC.md §1.6`, `specs/002-artifacts.md §3`

### qualified
Council outcome at G2 / G4. Majority-approved with substantive minority objection; routes to an intensified G4 portfolio (full G4 + adversarial council probe). Distinct from `pass`. → `SPEC.md §4 G2`, `specs/003-state-machine.md §3`

---

## Tools / Files

### `config/gate_routes.yaml`
Authoritative static YAML for "what happens after gate X with outcome Y". The entire control flow in one file. Validated as a DAG at startup; cycles raise `RouteCycleDetected`. → `specs/003-state-machine.md §4.1`

### `config/gates/<gate>.yaml`
Per-gate config: `gate`, `timeout_seconds`, `implementing_module`, `required_artifacts`, `output_artifact`, plus gate-specific thresholds (e.g., `ood_threshold` for G3). → `specs/003-state-machine.md §4.2`

### `config/genver.yaml`
Generator-Verifier loop configuration: `max_iterations`, `parse_retry_count`, `sandbox_limits`, prompt template paths, code-gen model id, local-gate thresholds, diff tool. All thresholds are configuration, not code. → `specs/008-generator-verifier.md §4.3`

### `config/sandbox_imports.yaml`
Default import whitelist for the Generator-Verifier sandbox: stdlib subset + numpy + scipy + jax + adapter-declared modules. Extension requires Phase-B review. → `specs/008-generator-verifier.md §5.4`

### `runs/<cycle-id>/councils/<session_id>.jsonl`
Full per-deliberation transcript: `session_start`, every `stageN_prompt`, every `stageN_response` with tokens + cost, `session_end` with `verdict_hash` and `total_cost_usd`. JSON-line format. Session path is supplied to `Council.__init__` by the caller (state machine) — there is no module-local default. → `specs/001-council.md §4`

### `runs/<cycle-id>/artifacts/<hash>.json`
One file per emitted typed artifact. Filename IS the SHA-256 hash. Append-only directory; `INDEX.json` provides hash → type lookup for grep-ability. → `ARCHITECTURE.md §1.4`, `specs/002-artifacts.md §4`

### `runs/<cycle-id>/cycle.jsonl`
JSON-line log of every cycle event. Fields: `{ts, cycle_id, module, level, event, payload}`. No free-text log messages. The `factory inspect` reconstruction reads this. → `ARCHITECTURE.md §1.4`

### `runs/<cycle-id>/MANIFEST.json`
Cycle index — artifact hashes, gate sequence, terminal outcome. Reconstructs the cycle without re-execution. → `ARCHITECTURE.md §1.4`, `specs/003-state-machine.md §4.3`

### `runs/<cycle-id>/sandbox/<iteration:03d>/`
Per-iteration staging directory for the Generator-Verifier loop. Holds prompt, response, blueprint, diff, stdout/stderr, traceback, `resource.json`, `adapter_outputs/`, and `status.json`. → `specs/008-generator-verifier.md §4.1`

### `runs/<cycle-id>/sandbox/MANIFEST.json`
Index of iteration directories with status ∈ {`failed_runtime`, `failed_parse`, `passed_local_gate`, `promoted`, `wiped`}, durations, costs. Atomically updated at iteration boundaries. → `specs/008-generator-verifier.md §4.2`

### `runs/_paper_store/`
Local cache of PDF / OCR / extracted-schema records for papers promoted from OpenAlex traversal. Source of all BibTeX for `RunReport`s. No web calls at write time. → `SPEC.md §6.1`, `SPEC.md §9`

### `docs/schemas/<artifact>.schema.json`
Auto-generated JSON Schema Draft 2020-12 for every typed artifact, emitted by `python -m factory.artifacts emit-schemas`. CI step diffs against committed version; drift fails CI. → `specs/002-artifacts.md §4`, `specs/002-artifacts.md §7`
