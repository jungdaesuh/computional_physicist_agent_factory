# PRD 001: Phase A MVP — First Autonomous Closed Loop

> Status: ☐ not started · Owner: TBD · Target: 90 days from project start

## 1. Goal

By the end of Phase A, the system autonomously proposes one hypothesis the operator did not suggest, selects an appropriate open-source simulator from the curated `SimulatorCatalog`, executes the experiment within budget, validates against the full G4 portfolio (with cross-simulator check where the Catalog permits), and emits a defensible internal `RunReport`. The result may be a positive finding **or** a defensible null. Either qualifies as success.

## 2. Why Now

Every autonomous-science effort to date stalls on one of three failure modes: subjective judgment (worthiness), adversarial code-generation (invariant hacking, numerical gullibility), or unbounded cost. Phase A is the first end-to-end implementation that explicitly defends against all three with the merged architecture in `SPEC.md`. Until one closed loop is observed running under budget with defensible output, the architecture is unvalidated; nothing past Phase A is worth building.

## 3. User Journey

The operator is a single researcher. The journey is:

1. **Initial setup (one-time).**
   - Install factory CLI; provision LLM API keys for ≥4 vendors.
   - Set initial `DomainScope` (one primary domain + one orthogonal physics domain).
   - Hand-curate `SimulatorCatalog` v1 with 5–10 OSI-licensed entries; verify smoke tests pass for each.
   - Configure aggregate dollar cap and daily burn cap.
2. **Operator kicks off literature discovery.**
   - Operator runs `factory discover --seed "<research topic>"`.
   - System runs OpenAlex traversal, ranks papers, populates Paper Store + Evidence Store.
   - Operator reviews a small sample of `GapCandidate`s the Gap Miner surfaced. (Phase A allows operator inspection; Phase B autonomizes this step.)
3. **Factory enters autonomous loop.**
   - Operator runs `factory start` (or schedules it).
   - System pulls top `GapCandidate`s, runs C1 Worthiness council, selects 1.
   - Refines into `HypothesisSpec`, runs C2 Design council, produces `ExperimentSpec`.
   - Runs G2.5 tractability dry-run on a toy problem. Failure → rollback + `intractable` Ledger entry.
   - Runs G3 surrogate probe. Failure → kill.
   - Runs G4 validation portfolio on the selected simulator. Cross-simulator check if available.
   - Runs C3 Claim Interpretation, then C4 Peer Review.
   - Emits `RunReport` to `EvidenceLedger`.
4. **Operator reviews.**
   - Operator opens Mission Control UI (or `factory inspect <hypothesis-id>` CLI).
   - Reads the `RunReport`, council deliberations (with preserved dissent), provenance audit.
   - Decides whether to G6-approve for external release. Phase A does **not** require external release; the milestone is met by internal publication.

## 4. Success Metrics

A Phase A run is **successful** if and only if all of the following hold for at least one completed cycle:

| Metric | Threshold |
| :--- | :--- |
| Hypothesis was autonomously generated (operator did not suggest the specific gap) | yes |
| Total cost per hypothesis (LLM + compute) | ≤ $50 |
| Wall-clock per hypothesis | ≤ 72 hours |
| G4 validation portfolio passed | all checks pass |
| Cross-simulator check ran AND agreed within tolerance | yes (where Catalog supports it) |
| `RunReport` written to `EvidenceLedger` with full provenance | yes |
| Council deliberations preserved dissent (or sycophancy flag fired if no dissent) | yes |
| Negative-result handling: if hypothesis was falsified, a `RunReport` was still emitted (no silent failure) | yes |

A Phase A run is **also successful** if the autonomous loop runs end-to-end and produces a *defensible null* — i.e., the system correctly identifies that the hypothesis cannot be validated within Phase A's tooling and emits an explicit `inconclusive` Ledger entry with provenance. This is preferable to a false positive.

## 5. Scope

### In scope (Phase A)

- One primary physics domain + one orthogonal cross-validation domain.
- 5–10 hand-curated simulators in `SimulatorCatalog`.
- C1, C2, C3, C4 councils as per-cycle gates. C5 weekly cadence.
- G0, G1, G1.5, G2, G2.5, G3, G4, G5, G6 all enforced (G6 may be no-op during Phase A — internal publication only).
- All eleven typed artifacts with provenance hashing.
- Budget enforcement (dollar / iteration / wall-clock caps).
- Generator-Verifier loop with sandboxed execution + atomic promotion.
- Validation portfolio with deterministic checks.
- Mission Control and Hypothesis Detail UI surfaces (minimum subset for operator to review cycles).

### Out of scope (Phase A)

- Autonomous Catalog onboarding (Phase C).
- Multi-domain hypothesis generation (cross-domain methodology transfer) (Phase C).
- External arXiv publication (Phase B).
- Full 11-screen UI (Mission Control + Hypothesis Detail + Council Deliberation views only).
- Advanced surrogate retraining (Phase B); Phase A uses a single static surrogate per observable.
- Long-tail simulator support beyond the initial 5–10.

### Deferred to Phase B

- Catalog growth to ~30 entries.
- Cross-simulator validation across 5–6 domains.
- C5 fortnightly cadence with measurable expansion decisions.
- First external `RunReport` published with G6 human approval.

## 6. Deliverables

Each deliverable links to the spec that defines it. Status tracked in `INDEX.md` §4.

| Deliverable | Spec | Notes |
| :--- | :--- | :--- |
| Council library + persona templates + calibration suite | `specs/001-council.md` | Standalone library; ships as PRD-002 first. |
| Typed artifact dataclasses + provenance | `specs/002-artifacts.md` | All eleven artifacts. |
| Gate state machine (G0–G6) with recovery paths | `specs/003-state-machine.md` | The orchestrator. |
| `SimulatorCatalog` v1 with 5–10 entries | `specs/004-simulator-catalog.md` | Catalog ships as PRD-004. |
| `SimulatorSelector` with rank-and-cost | `specs/005-simulator-selector.md` | Queries Catalog; returns ranked + costed. |
| Abstract solver interface + first domain adapter | `specs/006-domain-adapter.md` | Wired to ≥2 simulators in primary domain. |
| OpenAlex client + traversal + Gap Miner | `specs/007-literature-discovery.md` | 4 gap-types: structural-hole / methodology-transfer / contradiction / negative-result. |
| Generator-Verifier loop | `specs/008-generator-verifier.md` | Sandbox + staging + atomic promote + budget. |
| Validation portfolio (G4) | `specs/009-validation-portfolio.md` | Conservation, convergence, refinement, symmetry, statistics, cross-simulator. |
| Surrogate models + OOD detector | `specs/010-surrogate-models.md` | Phase A: static models; OOD escalation to oracle. |
| RAG writer + Paper Store query | `specs/011-rag-writer.md` | BibTeX from cached entries only. |
| `EvidenceLedger` SQLite backend | `specs/012-evidence-ledger.md` | Full provenance + re-litigation triggers. |
| Budget tracker | `specs/013-budget-tracker.md` | Per-hypothesis + aggregate; kill switch. |
| Telemetry & audit log | `specs/014-telemetry-and-audit.md` | Retention + export. |
| Operator CLI + read-only HTTP API | `specs/015-operator-interface.md` | UI backend. |
| Strategy Archive (BFTS + Bayesian surprise + UCT + MAP-Elites) | `specs/016-strategy-archive.md` | What-to-try-next substrate; wired into Generator-Verifier per `FIX_PLAN §26.2`. |
| Fidelity Ladder Scheduler | `specs/017-fidelity-scheduler.md` | Runtime traversal of `ExperimentSpec.fidelity_ladder`; G3 / G4 transitions per `FIX_PLAN §26.3`. |
| OpenRouter Client (shared LLM substrate) | `specs/018-openrouter-client.md` | Week 0 prerequisite — `DecisionClient` Protocol + `OpenRouterClient` + `FileClient`. Per `FIX_PLAN §27`. |
| Mission Control + Hypothesis Detail + Council Deliberation UI screens | `UI_DESIGN.md` §1, §4, §3 | Minimum operator surface. |

## 7. Risks & Mitigations

| Risk | Severity | Mitigation |
| :--- | :--- | :--- |
| Council models agree trivially (sycophancy) | High | Sycophancy calibration probe in Spec 001; minimum heterogeneity check at startup; fail loud if agreement-rate > threshold on probe set. |
| Code-gen produces numerically gullible solver mutations | High | G2.5 dry-run + G3 surrogate + G4 portfolio. Each gate is independent; no single failure mode passes all three. |
| Single simulator can be "tricked" by adversarial code-gen | High | Cross-simulator validation when Catalog permits; held-out symmetry tests at G4. |
| Container build failures across simulator family | Medium | Smoke-test on every Catalog onboarding; container build is in CI; failed builds block onboarding. |
| Cost overrun beyond aggregate cap | Medium | Hard kill switch in Budget tracker; cap enforced at per-cycle, per-day, and aggregate levels. |
| Gap Miner produces graph artifacts not real gaps | Medium | G1 falsifiability filter forces every gap into the conversion path; failures discarded with rationale. |
| OpenAlex API rate limits or downtime | Low | Traversal cached locally; offline mode reads from `OpenAlexGraphStore`. |
| Surrogate produces false-positive G3 pass on OOD inputs | Medium | OOD detector mandatory at G3; OOD candidates escalate directly to oracle. |
| First cycle takes longer than 72 hours | Medium | Profile each gate; pre-build all containers; warm surrogate cache. |

## 8. Acceptance Criteria

PRD-001 closes when **all** of:

- [ ] All Phase A specs (001, 002, 003, 004, 005, 006, 007, 008, 009, 010, 011, 012, 013, 014, 015, 016, 017, 018) have status ☑ in `INDEX.md` (17 specs total per FIX_PLAN §26 + §27).
- [ ] One successful end-to-end autonomous cycle completes per the success-metrics table in §4.
- [ ] OR one defensible-null cycle completes that emits an `inconclusive` Ledger entry with full provenance and a clear explanation of why Phase A tooling could not validate the hypothesis.
- [ ] Cross-simulator validation has fired at least once during Phase A (proof that the orthogonal-check defense is live).
- [ ] Sycophancy calibration probe has run at least once on the active council lineup with a documented disagreement-rate score.
- [ ] Total Phase A spend is documented and under the agreed aggregate dollar cap.
- [ ] One operator-written post-mortem documenting what worked, what didn't, and the decision on Phase B scope.

## 9. Linked Specs

- `specs/001-council.md` — Council library; Phase A councils.
- `specs/002-artifacts.md` — All eleven typed artifacts.
- `specs/003-state-machine.md` — Gate orchestrator G0–G6.
- `specs/004-simulator-catalog.md` — Catalog data model + onboarding.
- `specs/005-simulator-selector.md` — Selector logic.
- `specs/006-domain-adapter.md` — Abstract solver interface.
- `specs/007-literature-discovery.md` — Paper Store + Gap Miner.
- `specs/008-generator-verifier.md` — Execution layer.
- `specs/009-validation-portfolio.md` — G4 deterministic checks.
- `specs/010-surrogate-models.md` — Surrogates + OOD.
- `specs/011-rag-writer.md` — `RunReport` generation.
- `specs/012-evidence-ledger.md` — Persistence + queries.
- `specs/013-budget-tracker.md` — Cost enforcement.
- `specs/014-telemetry-and-audit.md` — Observability.
- `specs/015-operator-interface.md` — CLI + API.
- `specs/016-strategy-archive.md` — Strategy Archive + Bayesian surprise + UCT.
- `specs/017-fidelity-scheduler.md` — Multi-fidelity ladder scheduler.
- `specs/018-openrouter-client.md` — Shared LLM substrate (Week 0 prerequisite).
