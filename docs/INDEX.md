# AI Co-Computational Physicist Factory — Documentation Index

The navigation hub for the project's documentation. The top-level `SPEC.md` is the canonical architectural specification; `ARCHITECTURE.md` defines the modularity and onboarding invariants the codebase must satisfy; this index maps both into detailed component specs and milestone PRDs, with implementation checkboxes per spec.

> **Status legend:** ☐ not started · ◐ in progress · ☑ complete · ⊘ deferred to later phase

---

## 0. Fresh Agent Onboarding (read this if you just opened the repo)

You are productive in **40 minutes** if you follow this path. Do not deviate.

1. **Read this file's §1 Quick Orientation and §4 Top-Level TODO** (~5 min). Identify what's in progress.
2. **Read `ARCHITECTURE.md` §1 (Invariants) and §3 (Repository Layout + Canonical Module Template)** (~10 min). These are the rules every module follows.
3. **Open the one spec relevant to your task** (~15 min). Read the `CONTEXT`, `ENTRY POINTS`, `LOCAL DEBUG`, and `DEPENDENCIES` blocks first; the rest only if needed.
4. **Run the spec's mock-mode example.** Confirm dev environment works (~5 min).
5. **Open the module's `tests/test_<module>_typical_usage.py`** (~5 min). Copy the pattern.

If you find yourself needing to read more than INDEX.md + ARCHITECTURE.md + one spec + one test file, **the spec is missing context — file a doc bug and fix the spec, do not absorb the gap as tribal knowledge.**

A fresh-context agent should *never* need to read the whole codebase to make a productive edit. If you do, that's a signal the architecture has drifted and an invariant in `ARCHITECTURE.md` is being violated.

---

## 1. Quick Orientation

- **What this project is.** See `SPEC.md` §0–§1.
- **What the UI looks like.** See `UI_DESIGN.md` — 11 screen prompts.
- **What we're building first.** See `prds/PRD-001-phase-a-mvp.md`.
- **Critical-path components for Phase A.** Specs 001 (Council), 002 (Artifacts), 003 (State Machine), 004 (Catalog), 008 (Generator-Verifier), 009 (Validation), 012 (Evidence Ledger), 013 (Budget).
- **First runnable artifact.** Council-as-library (Spec 001). Everything else consumes it.

---

## 2. Documentation Map

### Top-level

| Doc | Purpose |
| :--- | :--- |
| `SPEC.md` | Canonical architectural specification (principles, gates, councils, failure modes, phased rollout) |
| `ARCHITECTURE.md` | Modularity invariants + canonical module template |
| `INDEX.md` | This file — navigation + onboarding + status + top-level TODOs |
| `ORCHESTRATION.md` | Subagent orchestration playbook |
| `GLOSSARY.md` | Authoritative term definitions |
| `DIAGRAMS.md` | Mermaid diagrams (dependency, gates, councils, lineage) |
| `UI_DESIGN.md` | 11 UI screen prompts |

### Product Requirements Documents (`prds/`)

PRDs frame **what we ship and why** for each major milestone. They reference specs but do not duplicate them.

| ID | Title | Status | Target | Spec deps |
| :--- | :--- | :---: | :--- | :--- |
| PRD-001 | Phase A MVP — first autonomous closed loop | ☐ | 90 days | 001, 002, 003, 004, 005, 008, 009, 012, 013 |
| PRD-002 | Council Library v1 — standalone deliberation engine | ☐ | Week 2 | 001, 002 (subset) |
| PRD-003 | First end-to-end autonomous cycle | ☐ | Week 8 | All Phase A |
| PRD-004 | Simulator Catalog v1 with 5–10 hand-curated entries | ☐ | Week 4 | 002, 004, 005, 006 |

### Component Specifications (`specs/`)

Each spec is implementation-grade — interfaces, schemas, algorithms, failure modes, tests, and a TODO checklist.

| ID | Spec | Status | Detail level | Dependencies |
| :--- | :--- | :---: | :--- | :--- |
| 001 | Council Library | ☐ | Full | 002 |
| 002 | Typed Artifacts | ☐ | Full | — |
| 003 | Gate State Machine | ☐ | Full | 001, 002, 008, 009, 012, 013 |
| 004 | Simulator Catalog | ☐ | Full | 002 |
| 005 | Simulator Selector | ☐ | Full | 002, 004 |
| 006 | Domain Adapter | ☐ | Skeleton | 002, 004, 008 |
| 007 | Literature Discovery (OpenAlex + Gap Miner) | ☐ | Skeleton | 002 |
| 008 | Generator-Verifier Loop | ☐ | Full | 001, 002, 006, 013 |
| 009 | Validation Portfolio (G4) | ☐ | Full | 002, 004, 012 |
| 010 | Surrogate Models | ☐ | Skeleton | 002, 012 |
| 011 | RAG Writer | ☐ | Skeleton | 002, 007, 012 |
| 012 | Evidence Ledger | ☐ | Full | 002 |
| 013 | Budget Tracker | ☐ | Full | 002, 012 |
| 014 | Telemetry & Audit | ☐ | Skeleton | 012 |
| 015 | Operator Interface (CLI + HTTP API) | ☐ | Skeleton | 001, 002, 012, 013 |
| 016 | Strategy Archive (BFTS + Bayesian surprise + UCT + MAP-Elites) | ☐ | Full | 002, 012 |
| 017 | Fidelity Ladder Scheduler | ☐ | Full | 002, 010, 006 |

---

## 3. Dependency Graph

```
                                  ┌─────────────────────┐
                                  │ 002 Typed Artifacts │ (foundational — all depend)
                                  └──────────┬──────────┘
                                             │
            ┌────────────┬────────────┬──────┴──────┬──────────────┬──────────────┐
            ▼            ▼            ▼             ▼              ▼              ▼
       ┌────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
       │  001   │  │   004    │  │   007    │  │   012    │  │   013    │  │   014    │
       │Council │  │ Catalog  │  │   Lit    │  │ Evidence │  │  Budget  │  │Telemetry │
       └────┬───┘  └────┬─────┘  │Discovery │  │  Ledger  │  └────┬─────┘  └──────────┘
            │           │        └──────────┘  └────┬─────┘       │
            │           ▼                           │             │
            │      ┌──────────┐                     │             │
            │      │   005    │                     │             │
            │      │ Selector │                     │             │
            │      └────┬─────┘                     │             │
            │           ▼                           │             │
            │      ┌──────────┐                     │             │
            │      │   006    │                     │             │
            │      │  Domain  │                     │             │
            │      │ Adapter  │                     │             │
            │      └────┬─────┘                     │             │
            │           ▼                           │             │
            │      ┌──────────┐                     │             │
            └─────►│   008    │◄────────────────────┘             │
                   │  Gen-Ver │                                   │
                   └────┬─────┘                                   │
                        ▼                                         │
                   ┌──────────┐                                   │
                   │   009    │◄──────────────────────────────────┘
                   │Validation│
                   └────┬─────┘
                        │
                        ▼
                   ┌──────────┐  ┌──────────┐  ┌──────────┐
                   │   010    │  │   011    │  │   015    │
                   │Surrogate │  │   RAG    │  │ Operator │
                   └──────────┘  │  Writer  │  │   API    │
                                 └──────────┘  └──────────┘

                   ┌──────────────────────────────────┐
                   │       003 Gate State Machine     │ (orchestrates all of the above)
                   └──────────────────────────────────┘

       Strategy + Fidelity (FIX_PLAN §26)
       ┌──────────────────────────────────────────────────────────────┐
       │                                                              │
       │  002 ── 012 ──► ┌──────────┐                                 │
       │                 │   016    │ ──► 003 C5 (DomainScope)        │
       │                 │ Strategy │ ──► 008 (mutation selection)    │
       │                 │ Archive  │                                 │
       │                 └──────────┘                                 │
       │                                                              │
       │  002 ── 010 ── 006 ──► ┌──────────┐                          │
       │                        │   017    │ ──► 003 (G3/G4 transition)│
       │                        │ Fidelity │                          │
       │                        │Scheduler │                          │
       │                        └──────────┘                          │
       └──────────────────────────────────────────────────────────────┘
```

---

## 4. Top-Level TODO — Phase A Critical Path

Ordered by dependency. Check off as deliverables land. Each line links to the spec where the implementation TODO lives.

### Foundation (Weeks 1–2)

- [ ] Typed Artifact dataclasses + provenance hashing → `specs/002-artifacts.md`
- [ ] `EvidenceLedger` SQLite schema + CRUD + audit query interface → `specs/012-evidence-ledger.md`
- [ ] `Budget` tracker with hard caps + running ledger → `specs/013-budget-tracker.md`
- [ ] Council library: model client + persona templates + three-stage deliberation + preserved-dissent verdict → `specs/001-council.md`
- [ ] Council calibration suite (sycophancy probe + heterogeneity check) → `specs/001-council.md`

### Catalog (Weeks 3–4)

- [ ] `SimulatorCatalog` manifest schema → `specs/004-simulator-catalog.md`
- [ ] First 2 catalog entries (cross-validatable observable in initial domain) → `specs/004-simulator-catalog.md`
- [ ] Container build + smoke test harness → `specs/004-simulator-catalog.md`
- [ ] `SimulatorSelector` rank-and-cost → `specs/005-simulator-selector.md`
- [ ] Abstract solver interface + first domain adapter → `specs/006-domain-adapter.md`

### Execution (Weeks 5–6)

- [ ] Generator-Verifier ReAct loop + sandbox + staging + atomic promote → `specs/008-generator-verifier.md`
- [ ] G2.5 tractability dry-run gate → `specs/003-state-machine.md`
- [ ] G4 validation portfolio (deterministic checks) → `specs/009-validation-portfolio.md`
- [ ] Cross-simulator validation runner → `specs/009-validation-portfolio.md`

### Gates & Orchestration (Weeks 7–8)

- [ ] Gate state machine G0–G6 with recovery paths → `specs/003-state-machine.md`
- [ ] C1–C4 wired to gates → `specs/003-state-machine.md`
- [ ] C5 program-direction council on weekly cadence → `specs/001-council.md`

### Literature & Writing (Weeks 9–10)

- [ ] OpenAlex client + traversal + ranker → `specs/007-literature-discovery.md`
- [ ] Gap Miner (4 gap-types) → `specs/007-literature-discovery.md`
- [ ] Paper Store schema + RAG writer skeleton → `specs/011-rag-writer.md`

### Strategy + Fidelity (Weeks 6–7)

- [ ] Bayesian surprise primitives (`beta_kl`, `dirichlet_kl`, polarity gate) in `beliefs.py` → `specs/016-strategy-archive.md`
- [ ] `StrategyArchive` class + UCT composite-score selection (`reward_alpha + surprise_beta == 1.0` invariant) → `specs/016-strategy-archive.md`
- [ ] `FidelityLadderScheduler` 3-tier (Phase A: DRY_RUN → SURROGATE → ORACLE) → `specs/017-fidelity-scheduler.md`
- [ ] Wire `StrategyArchive` to Generator-Verifier loop for `StrategyCycleEvidence` attribution per iteration → `specs/008-generator-verifier.md`
- [ ] Wire `FidelityLadderScheduler` to state machine at G3/G4 transitions → `specs/003-state-machine.md`

### Integration & Hardening (Weeks 11–12)

- [ ] CLI: `factory start | stop | status | inspect <hypothesis-id>` → `specs/015-operator-interface.md`
- [ ] HTTP read-only API for UI backend → `specs/015-operator-interface.md`
- [ ] End-to-end Phase A acceptance test → `prds/PRD-003-first-autonomous-cycle.md`
- [ ] One published `RunReport` (positive or defensible null) → milestone gate

---

## 5. Cross-Cutting Concerns

Topics that span specs. Tracked here so they don't fall through cracks.

| Concern | Owner spec(s) | Status |
| :--- | :--- | :---: |
| Artifact registry (thirteen typed artifacts + canonical JSON hash) | 002 | ☐ |
| Provenance hashing (content-addressed artifacts) | 002 | ☐ |
| EvidenceLedgerReader (read-only ledger surface for RAG + dedup) | 011, 012 | ☐ |
| Event taxonomy registration (per-module `events.py` registries) | 014 | ☐ |
| Cost accounting (per-LLM-call + per-sim-run) | 013, 014 | ☐ |
| Container build cache + manifest hashing | 004 | ☐ |
| Heterogeneous-model API client (multi-vendor router) | 001 | ☐ |
| Out-of-distribution detection on surrogate inputs | 010 | ☐ |
| Dissent preservation through council pipeline | 001, 003 | ☐ |
| Re-litigation policy when EvidenceLedger entry stale | 012 | ☐ |
| Audit log retention + export | 014 | ☐ |
| Secret management for API keys | 015 | ☐ |
| License auditor for catalog onboarding | 004 | ☐ |
| Bayesian surprise (Dirichlet KL) — polarity-gated belief shift over feasibility buckets | 016 | ☐ |
| MAP-Elites cell bookkeeping (Phase B) — behavior-descriptor diversity archive | 016 | ⊘ |

---

## 6. How to Use This Index

**Starting a new implementation session:**
1. Re-read `SPEC.md` §1 (Core Principles) — anchors decisions.
2. Open this `INDEX.md` to identify the next unchecked critical-path item.
3. Open the linked spec; work the TODO checklist at the bottom of that spec.
4. When closing a spec TODO, also tick the corresponding line in this index.

**Adding a new spec or PRD:**
1. Create the file under `specs/NNN-name.md` or `prds/PRD-NNN-name.md` using the template in §7 below.
2. Add a row to the relevant table in §2.
3. Add edges to the dependency graph in §3 if it changes.
4. Add cross-cutting concerns to §5 if applicable.

**Closing a PRD:**
1. All linked spec TODOs are ☑.
2. Acceptance criteria in the PRD are satisfied with evidence (link to `RunReport`s, test runs, or `EvidenceLedger` entries).
3. Update the PRD status in §2.

---

## 7. Spec & PRD Templates

### Spec template (use for new specs in `specs/`)

Front-matter blocks are **required** and come BEFORE §1 Summary. They enable a fresh-context agent to become productive in 40 minutes (see `ARCHITECTURE.md` §1.10).

```markdown
# Spec NNN: <Component Name>

> Status: ☐ not started · Owner: <name> · Last updated: YYYY-MM-DD

## CONTEXT (60-second summary — read first)
- One sentence: what this is.
- 3–5 facts you need to know to work here.
- The one file/test to open first.

## ENTRY POINTS
- Main module: `factory/<module>/api.py`
- Typical-usage test: `factory/<module>/tests/test_<module>_typical_usage.py`
- CLI: `python -m factory.<module> --help`
- Mock-mode example: `python -m factory.<module> <cmd> --mock-mode`
- Runbook (if any): `docs/runbooks/<name>.md`

## LOCAL DEBUG
- How to instantiate this in isolation (mock mode).
- Fixture artifacts to feed it: `factory/<module>/fixtures/...`
- Common error signatures → recovery action:
  - `<ErrorClass>` → <what to do>
- Logs to inspect: `runs/<cycle-id>/cycle.jsonl` (filter `module=<module>`).

## DEPENDENCIES
- **Hard:** Spec NNN (used for X). Spec MMM (used for Y).
- **Soft:** Spec PPP (optional, fallback: <behavior>).
- **Mocks available:** <list of mocks for testing in isolation>.

---

## 1. Summary
One paragraph. What this component is and why it exists.

## 2. Scope
**In scope:** bullet list.
**Out of scope:** bullet list.

## 3. Public Interface
Function signatures, class APIs, HTTP endpoints. The CONTRACT — other modules import this and only this.

## 4. Data Structures / Schemas
Dataclasses, JSON schemas, DB tables. If the component owns an artifact, link to its definition in spec 002.

## 5. Algorithms / Logic
Pseudocode or prose for the non-trivial parts.

## 6. Failure Modes
| Error class | When it fires | Recovery action |
| :--- | :--- | :--- |
| `<Foo>Error(FactoryError)` | <condition> | <how state machine recovers> |

## 7. Testing
Unit, integration, and acceptance tests required.
- **Mock-mode tests:** must run in CI without external services.
- **Live-mode tests:** gated behind `@pytest.mark.live`.
- **Typical-usage test:** REQUIRED at `tests/test_<module>_typical_usage.py`.

## 8. Performance & Budget
Time/space/cost characteristics; caps where applicable.

## 9. Open Questions
Unresolved design questions for future iteration.

## 10. TODO Checklist
- [ ] Concrete implementation steps in dependency order.
```

### PRD template (use for new PRDs in `prds/`)

```markdown
# PRD NNN: <Milestone Name>

> Status: ☐ not started · Owner: <name> · Target: <date>

## 1. Goal
One sentence.

## 2. Why now
Strategic context.

## 3. User journey
Step-by-step from operator's perspective.

## 4. Success metrics
Quantitative / observable outcomes.

## 5. Scope
**In scope** / **Out of scope** / **Deferred to next milestone.**

## 6. Deliverables
Concrete artifacts.

## 7. Risks & mitigations
Risk register.

## 8. Acceptance criteria
What evidence proves the PRD is complete.

## 9. Linked specs
- Spec NNN — role in this milestone.
```

---

## 8. Document Conventions

- All artifacts referenced as backticked types (e.g., `HypothesisSpec`).
- Gate IDs as `G0`, `G1`, `G1.5`, `G2`, `G2.5`, `G3`, `G4`, `G5`, `G6`.
- Council IDs as `C1`–`C5`.
- Content hashes shown as 7-char prefixes (e.g., `7a3b2c1`).
- Specs use 4-space indents in code blocks; YAML and JSON use 2-space.
- Cross-references between specs use relative paths: `specs/002-artifacts.md`.
- TODO checkboxes use `- [ ]` (incomplete) and `- [x]` (complete) — keep in sync with §2 status column and the top-level TODO in §4.
