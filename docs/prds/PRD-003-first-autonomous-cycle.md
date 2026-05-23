# PRD 003: First End-to-End Autonomous Cycle

> Status: ☐ not started · Owner: TBD · Target: Week 8 of Phase A

## 1. Goal

Run one complete autonomous cycle from `GapCandidate` through `RunReport`, with all gates wired, all councils firing, and all artifacts persisted to `EvidenceLedger` with provenance. The cycle does not need to produce a *positive* finding; it must demonstrate the loop runs end-to-end without operator intervention.

## 2. Why Now

PRD-001 (Phase A MVP) acceptance requires a passing cycle. This PRD is the integration milestone where the Council Library (PRD-002), Simulator Catalog (PRD-004), and all per-component specs converge into a runnable system. It's the gate between "we have parts" and "we have a system."

## 3. User Journey

1. Operator confirms all dependencies green: Council calibrated (PRD-002), Catalog has ≥2 cross-validatable simulators (PRD-004), all spec TODOs at the foundational layer are ☑.
2. Operator runs `factory discover --seed "<topic>"` and reviews surfaced `GapCandidate`s.
3. Operator runs `factory start --cycles 1` to execute exactly one cycle.
4. Operator monitors via Mission Control UI or `factory status`.
5. Cycle completes; operator inspects the resulting `RunReport` and the trail of `CouncilVerdict`s.

## 4. Success Metrics

| Metric | Threshold |
| :--- | :--- |
| Cycle traverses G0 → G6 without manual intervention | yes |
| All four per-cycle councils (C1–C4) fire and emit `CouncilVerdict` | yes |
| At least one council deliberation contains preserved dissent | yes (otherwise sycophancy flag) |
| G4 validation portfolio executes all configured checks | yes |
| Cross-simulator check runs (if Catalog supports it for the chosen observable) | yes |
| `RunReport` is written to `EvidenceLedger` with full provenance hashes | yes |
| Total cost is within `Budget` artifact's caps | yes |
| If cycle terminates as `intractable`, rollback completed cleanly (no orphaned staging dirs) | yes |

## 5. Scope

### In scope

- One cycle, one hypothesis, end-to-end.
- Cycle may terminate at any gate as long as the termination is *correct* (the gate logic produced the expected result).
- Operator-supplied seed query is acceptable for literature discovery; the *hypothesis itself* must be autonomously generated, not operator-suggested.

### Out of scope

- Multi-cycle runs (continuous operation is Phase A acceptance; this PRD is the single-cycle integration test).
- C5 program-direction execution (C5 runs on cadence, not per-cycle).
- G6 external publication (Phase B).

## 6. Deliverables

- Integration test runner: `pytest tests/integration/test_one_cycle.py` that runs an end-to-end cycle in mock-mode against fixture data.
- Live-mode operator runbook: `docs/runbooks/first-cycle.md` documenting how to execute the first real cycle.
- Cycle trace dump: every artifact + every log line from one successful cycle, archived for postmortem.

## 7. Risks & Mitigations

| Risk | Severity | Mitigation |
| :--- | :--- | :--- |
| Gates interact in unforeseen ways (e.g., G3 surrogate disagrees with G4 oracle) | High | Document the disagreement; treat as a *learning signal*, not a failure. Surface in C3 Interpretation. |
| Staging/atomic-promote races during budget exhaustion | High | Unit + integration tests for rollback on every gate failure path. |
| First cycle hits unforeseen simulator-specific bug | Medium | Smoke tests passed on Catalog onboarding; if simulator breaks at G4, mark Catalog entry as quarantined. |
| Cycle exceeds 72-hour wall clock during integration | Medium | Per-gate timeout caps from spec 003 §8. |

## 8. Acceptance Criteria

- [ ] Integration test passes in CI in mock mode.
- [ ] Live cycle executes end-to-end; total wall-clock ≤ 72h, total cost ≤ $50.
- [ ] All required artifacts persisted with provenance.
- [ ] Postmortem written documenting any gate timings, surprise behaviors, and follow-up TODOs.

## 9. Linked Specs

- All Phase A specs (001–015). This PRD is the integration gate; every spec must be at least partial-functional for this PRD to close.
